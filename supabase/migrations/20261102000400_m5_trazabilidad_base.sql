-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 0400. M5 Trazabilidad y auditoría: acciones, tipos de evento, equivalencias y auditoría técnica.
--
-- Una acción CONFIRMADA se inserta dentro de la transacción de la operación:
-- si la operación falla, la acción y sus eventos desaparecen con ella. Una
-- operación rechazada que deba auditarse se registra después, en una
-- transacción propia, como acción RECHAZADA sin eventos de negocio.

create table rma.accion_usuario (
  id uuid primary key default gen_random_uuid(),
  usuario_id uuid references rma.usuario (id),
  rol_codigo text,
  proceso text,
  operacion text not null check (btrim(operacion) <> ''),
  clave_idempotencia text check (clave_idempotencia is null or btrim(clave_idempotencia) <> ''),
  resultado text not null check (resultado in ('CONFIRMADA', 'RECHAZADA')),
  motivo_rechazo text,
  respuesta jsonb,
  orden_id uuid,
  registrada_en timestamptz not null default now(),
  constraint accion_responsable check (
    (usuario_id is not null and proceso is null)
    or (usuario_id is null and proceso is not null)
  ),
  constraint accion_rechazo_con_motivo check (
    resultado = 'CONFIRMADA' or motivo_rechazo is not null
  ),
  unique (id, resultado)
);

-- Un reintento con la misma clave devuelve el resultado ya confirmado (G-9).
create unique index accion_usuario_idempotencia
  on rma.accion_usuario (usuario_id, clave_idempotencia) nulls not distinct
  where clave_idempotencia is not null and resultado = 'CONFIRMADA';
create index accion_usuario_orden on rma.accion_usuario (orden_id) where orden_id is not null;
create index accion_usuario_fecha on rma.accion_usuario (registrada_en);

-- La acción se inserta al principio de la transacción (los eventos la
-- referencian) y al final se completan, una sola vez, la respuesta y la Orden
-- creada. El resto del registro es inmutable.
create or replace function rma.accion_usuario_solo_completar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Las acciones no se borran.' using errcode = 'restrict_violation';
  end if;
  if (old.respuesta is not null and new.respuesta is distinct from old.respuesta)
     or (old.orden_id is not null and new.orden_id is distinct from old.orden_id)
     or (to_jsonb(new) - 'respuesta' - 'orden_id') is distinct from (to_jsonb(old) - 'respuesta' - 'orden_id') then
    raise exception 'Una acción solo admite completar su respuesta y su Orden, una vez cada una.'
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

comment on function rma.accion_usuario_solo_completar() is
  'Permite completar una sola vez la respuesta y la Orden de una acción; impide cualquier otro cambio y el borrado.';

create trigger accion_usuario_solo_completar before update or delete on rma.accion_usuario
  for each row execute function rma.accion_usuario_solo_completar();

comment on table rma.accion_usuario is
  'Cada pedido que cambia datos, de una persona o de un proceso del sistema. Agrupa los eventos de una transacción, guarda la clave de idempotencia y conserva las operaciones rechazadas que deben auditarse.';
comment on column rma.accion_usuario.id is 'Identificador interno de la acción.';
comment on column rma.accion_usuario.usuario_id is 'Usuario que hizo el pedido (referencia a usuario); vacío si la acción es de un proceso del sistema.';
comment on column rma.accion_usuario.rol_codigo is 'Rol con el que actuó el usuario en ese momento, copiado para que un cambio de roles posterior no altere la historia.';
comment on column rma.accion_usuario.proceso is 'Nombre del proceso del sistema que originó la acción, cuando no la pidió una persona (por ejemplo una revalidación programada o una importación).';
comment on column rma.accion_usuario.operacion is 'Operación pedida, con el nombre de la operación de la API (por ejemplo REGISTRAR_PAGO o CERRAR_EJECUCION).';
comment on column rma.accion_usuario.clave_idempotencia is 'Clave que envía la pantalla y repite en cada reintento; una clave confirmada no vuelve a procesarse para el mismo usuario.';
comment on column rma.accion_usuario.resultado is 'CONFIRMADA si la operación se confirmó junto con sus cambios; RECHAZADA si se rechazó y se registró aparte para auditoría, sin eventos de negocio.';
comment on column rma.accion_usuario.motivo_rechazo is 'Por qué se rechazó la operación; obligatorio en una acción RECHAZADA.';
comment on column rma.accion_usuario.respuesta is 'Resultado devuelto al confirmar la operación, para responder igual a un reintento con la misma clave. Se completa una sola vez, al final de la transacción.';
comment on column rma.accion_usuario.orden_id is 'Orden sobre la que actuó, si corresponde (referencia a orden). En el alta de una Orden se completa una sola vez, después de crearla.';
comment on column rma.accion_usuario.registrada_en is 'Fecha y hora de la transacción que registró la acción.';

create table rma.tipo_evento (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  nombre text not null check (btrim(nombre) <> ''),
  entidad text not null,
  es_negocio boolean not null default true,
  visible_historial_actual boolean not null default false,
  activo boolean not null default true
);

create trigger tipo_evento_sin_borrado before delete on rma.tipo_evento
  for each row execute function rma.impedir_borrado();

comment on table rma.tipo_evento is
  'Catálogo de tipos de evento: los 51 eventos de negocio aprobados y un tipo técnico para los pasos de decisión del proceso. Sus códigos son nuevos y no reutilizan ACC-REP.';
comment on column rma.tipo_evento.id is 'Identificador interno del tipo de evento.';
comment on column rma.tipo_evento.codigo is 'Código estable del tipo: EV-REP-nnn para eventos de negocio y EV-SIS-nnn para pasos técnicos. Un código nunca cambia de significado.';
comment on column rma.tipo_evento.nombre is 'Nombre del evento, por ejemplo «Pago registrado».';
comment on column rma.tipo_evento.entidad is 'Entidad principal que el evento afecta (por ejemplo orden, detalle, pago o insumo).';
comment on column rma.tipo_evento.es_negocio is 'Si es un evento de negocio; falso para los pasos de decisión del proceso, que solo se conservan por compatibilidad con el historial.';
comment on column rma.tipo_evento.visible_historial_actual is 'Si sus eventos aparecen en el historial que muestra hoy la pantalla de la Orden; los tipos nuevos quedan ocultos hasta un rediseño aprobado.';
comment on column rma.tipo_evento.activo is 'Si el tipo puede usarse en eventos nuevos.';

create table rma.equivalencia_historial (
  id uuid primary key default gen_random_uuid(),
  tipo_referencia text not null check (tipo_referencia in ('PROCESS_NODE', 'FUNCTIONAL_ACTION')),
  referencia_id text not null,
  accion text,
  tipo_evento_id uuid not null references rma.tipo_evento (id),
  constraint equivalencia_unica unique nulls not distinct (tipo_referencia, referencia_id, accion)
);

create index equivalencia_historial_tipo on rma.equivalencia_historial (tipo_evento_id);

create trigger equivalencia_historial_sin_borrado before delete on rma.equivalencia_historial
  for each row execute function rma.impedir_borrado();

comment on table rma.equivalencia_historial is
  'Traduce cada entrada del historial actual (identificador y acción) a un tipo de evento, sin renumerar los identificadores PROC-REP y ACC-REP guardados. Resuelve los choques de ACC-REP-021 a 028.';
comment on column rma.equivalencia_historial.id is 'Identificador interno de la equivalencia.';
comment on column rma.equivalencia_historial.tipo_referencia is 'Clase de entrada del historial actual: PROCESS_NODE (nodo del proceso) o FUNCTIONAL_ACTION (acción transversal).';
comment on column rma.equivalencia_historial.referencia_id is 'Identificador guardado en el historial actual, por ejemplo PROC-REP-185 o ACC-REP-021.';
comment on column rma.equivalencia_historial.accion is 'Acción guardada junto al identificador, por ejemplo ANULAR_PAGO; vacía en la equivalencia por defecto del identificador.';
comment on column rma.equivalencia_historial.tipo_evento_id is 'Tipo de evento que corresponde a esa entrada (referencia a tipo_evento).';

create table rma.auditoria_tecnica (
  id uuid primary key default gen_random_uuid(),
  tipo text not null check (tipo in (
    'OPERACION_RECHAZADA', 'PERMISO_DENEGADO', 'ERROR_INTEGRIDAD',
    'DIFERENCIA_CONCILIACION', 'LIMPIEZA_FOTOS', 'ACCESO'
  )),
  usuario_id uuid references rma.usuario (id),
  proceso text,
  accion_id uuid references rma.accion_usuario (id),
  ocurrida_en timestamptz not null default now(),
  detalle jsonb not null default '{}'::jsonb check (jsonb_typeof(detalle) = 'object')
);

create index auditoria_tecnica_fecha on rma.auditoria_tecnica (ocurrida_en);
create index auditoria_tecnica_tipo on rma.auditoria_tecnica (tipo, ocurrida_en);

create trigger auditoria_tecnica_inmutable before update or delete on rma.auditoria_tecnica
  for each row execute function rma.impedir_modificacion();

comment on table rma.auditoria_tecnica is
  'Registros técnicos que no son eventos de negocio y nunca se muestran en la Orden: operaciones rechazadas, permisos denegados, errores de integridad, diferencias de conciliación, limpieza de fotos y accesos.';
comment on column rma.auditoria_tecnica.id is 'Identificador interno del registro.';
comment on column rma.auditoria_tecnica.tipo is 'Qué se registra: OPERACION_RECHAZADA, PERMISO_DENEGADO, ERROR_INTEGRIDAD, DIFERENCIA_CONCILIACION, LIMPIEZA_FOTOS o ACCESO.';
comment on column rma.auditoria_tecnica.usuario_id is 'Usuario involucrado, si lo hay (referencia a usuario).';
comment on column rma.auditoria_tecnica.proceso is 'Proceso del sistema involucrado, si no fue una persona.';
comment on column rma.auditoria_tecnica.accion_id is 'Acción relacionada, por ejemplo la acción rechazada (referencia a accion_usuario).';
comment on column rma.auditoria_tecnica.ocurrida_en is 'Fecha y hora del registro.';
comment on column rma.auditoria_tecnica.detalle is 'Datos del caso: mensaje, entidad, valores comparados u objetos afectados.';
