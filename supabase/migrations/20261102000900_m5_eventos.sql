-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 0900. M5 Eventos de negocio e historial visible.
--
-- Garantías de la base:
--   * Un evento solo puede apuntar a una acción CONFIRMADA (clave foránea con
--     una columna generada constante): como la acción y sus eventos se
--     insertan en la misma transacción, una transacción fallida no deja
--     ningún evento de éxito.
--   * La secuencia por Orden la asigna un trigger que incrementa el contador
--     de la Orden; esa actualización bloquea la fila y serializa los eventos.
--   * Los eventos son inmutables.

create table rma.evento_negocio (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid references rma.orden (id),
  secuencia integer check (secuencia >= 1),
  cliente_id uuid references rma.cliente (id),
  insumo_id uuid references rma.insumo (id),
  tipo_evento_id uuid not null references rma.tipo_evento (id),
  accion_id uuid not null,
  accion_resultado text not null generated always as ('CONFIRMADA') stored,
  ocurrido_en timestamptz not null default now(),
  responsable_tipo text not null check (responsable_tipo in ('USUARIO', 'SISTEMA')),
  usuario_id uuid references rma.usuario (id),
  rol_codigo text,
  detalle_id uuid references rma.detalle (id),
  ejecucion_id uuid references rma.ejecucion (id),
  pago_id uuid references rma.pago (id),
  posicion_proceso text check (posicion_proceso ~ '^(PROC-REP-[0-9]{3}|EVT-REP-[0-9]{3})$'),
  estado_anterior text,
  estado_nuevo text,
  datos jsonb not null default '{}'::jsonb check (jsonb_typeof(datos) = 'object'),
  observacion text,
  historial_tipo_referencia text check (historial_tipo_referencia in ('PROCESS_NODE', 'FUNCTIONAL_ACTION')),
  historial_referencia_id text,
  historial_accion text,
  heredado boolean not null default false,
  constraint evento_accion_confirmada foreign key (accion_id, accion_resultado)
    references rma.accion_usuario (id, resultado),
  constraint evento_con_entidad check (orden_id is not null or cliente_id is not null or insumo_id is not null),
  constraint evento_responsable check ((responsable_tipo = 'USUARIO') = (usuario_id is not null)),
  constraint evento_historial_completo check (
    (historial_referencia_id is null) = (historial_tipo_referencia is null)
    and (historial_referencia_id is null) = (historial_accion is null)
  ),
  constraint evento_heredado_con_historial check (not heredado or historial_referencia_id is not null)
);

create unique index evento_secuencia_por_orden on rma.evento_negocio (orden_id, secuencia) where orden_id is not null;
create index evento_tipo_fecha on rma.evento_negocio (tipo_evento_id, ocurrido_en);
create index evento_accion on rma.evento_negocio (accion_id);
create index evento_cliente on rma.evento_negocio (cliente_id) where cliente_id is not null;
create index evento_insumo on rma.evento_negocio (insumo_id) where insumo_id is not null;
create index evento_detalle on rma.evento_negocio (detalle_id) where detalle_id is not null;

create or replace function rma.evento_asignar_secuencia()
returns trigger
language plpgsql
security definer
set search_path = rma, pg_temp
as $$
begin
  if new.orden_id is null then
    new.secuencia := null;
    return new;
  end if;
  -- Incrementa el contador de la Orden; la actualización bloquea su fila.
  update rma.orden
     set ultima_secuencia_evento = ultima_secuencia_evento + 1
   where id = new.orden_id
  returning ultima_secuencia_evento into new.secuencia;
  return new;
end;
$$;

comment on function rma.evento_asignar_secuencia() is
  'Asigna al evento el siguiente número de secuencia de su Orden, incrementando el contador con la fila de la Orden bloqueada. Ignora cualquier secuencia enviada por el llamador.';

create trigger evento_asignar_secuencia before insert on rma.evento_negocio
  for each row execute function rma.evento_asignar_secuencia();
create trigger evento_inmutable before update or delete on rma.evento_negocio
  for each row execute function rma.impedir_modificacion();

comment on table rma.evento_negocio is
  'Hechos del dominio, en orden por Orden. Se registran en la misma transacción que el cambio que describen y nunca se modifican. Incluye las entradas del historial actual, con su identificador y acción originales, para reproducir el historial visible.';
comment on column rma.evento_negocio.id is 'Identificador interno del evento.';
comment on column rma.evento_negocio.orden_id is 'Orden en la que ocurrió (referencia a orden); vacía en eventos de Cliente o de stock sin Orden.';
comment on column rma.evento_negocio.secuencia is 'Posición del evento dentro de su Orden, desde 1, sin repetidos; la asigna la base y reproduce el orden histórico.';
comment on column rma.evento_negocio.cliente_id is 'Cliente afectado en eventos de Cliente (referencia a cliente).';
comment on column rma.evento_negocio.insumo_id is 'Insumo afectado en eventos de stock (referencia a insumo).';
comment on column rma.evento_negocio.tipo_evento_id is 'Tipo de evento (referencia a tipo_evento).';
comment on column rma.evento_negocio.accion_id is 'Acción confirmada que produjo el evento (referencia a accion_usuario).';
comment on column rma.evento_negocio.accion_resultado is 'Constante CONFIRMADA usada por la clave foránea para impedir eventos de acciones rechazadas.';
comment on column rma.evento_negocio.ocurrido_en is 'Fecha y hora del hecho.';
comment on column rma.evento_negocio.responsable_tipo is 'USUARIO si lo hizo una persona; SISTEMA si es un paso automático, cuyo responsable sale de la acción que lo originó.';
comment on column rma.evento_negocio.usuario_id is 'Usuario responsable (referencia a usuario); vacío si el responsable es el sistema.';
comment on column rma.evento_negocio.rol_codigo is 'Rol con el que actuó el usuario en ese momento.';
comment on column rma.evento_negocio.detalle_id is 'Detalle afectado, si corresponde (referencia a detalle).';
comment on column rma.evento_negocio.ejecucion_id is 'Ejecución afectada, si corresponde (referencia a ejecucion).';
comment on column rma.evento_negocio.pago_id is 'Pago afectado, si corresponde (referencia a pago).';
comment on column rma.evento_negocio.posicion_proceso is 'Nodo del proceso en que ocurrió (PROC-REP-nnn) o EVT-REP-999.';
comment on column rma.evento_negocio.estado_anterior is 'Estado de la entidad antes del evento, cuando el evento lo cambia.';
comment on column rma.evento_negocio.estado_nuevo is 'Estado de la entidad después del evento, cuando el evento lo cambia.';
comment on column rma.evento_negocio.datos is 'Datos propios del tipo de evento, por ejemplo el resultado de una decisión, los faltantes de stock o la cantidad sin respaldo de un override.';
comment on column rma.evento_negocio.observacion is 'Observación en texto, como la guarda hoy el historial.';
comment on column rma.evento_negocio.historial_tipo_referencia is 'Clase de entrada del historial actual (PROCESS_NODE o FUNCTIONAL_ACTION); vacía si el evento no aparece en el historial visible.';
comment on column rma.evento_negocio.historial_referencia_id is 'Identificador de la entrada del historial actual, por ejemplo PROC-REP-185 o ACC-REP-020, conservado sin renumerar.';
comment on column rma.evento_negocio.historial_accion is 'Acción de la entrada del historial actual, por ejemplo RESERVAR_INSUMOS_E_INICIAR_EJECUCION.';
comment on column rma.evento_negocio.heredado is 'Verdadero si el evento se importó del historial JSON anterior; su responsable es el usuario elegido entonces, sin autenticación.';

-- ---------------------------------------------------------------------------
-- Historial visible: el mismo contenido y orden que muestra hoy la pantalla.
-- ---------------------------------------------------------------------------
create view rma.v_historial_visible as
select
  e.orden_id,
  e.secuencia,
  e.historial_tipo_referencia as tipo_referencia,
  e.historial_referencia_id as referencia_id,
  e.historial_accion as accion,
  e.ocurrido_en as fecha,
  u.codigo as usuario_id,
  d.codigo as reparacion_detail_id,
  x.codigo as ejecucion_id,
  p.codigo as pago_id,
  e.observacion
from rma.evento_negocio e
left join rma.usuario u on u.id = e.usuario_id
left join rma.detalle d on d.id = e.detalle_id
left join rma.ejecucion x on x.id = e.ejecucion_id
left join rma.pago p on p.id = e.pago_id
where e.orden_id is not null
  and e.historial_referencia_id is not null;

comment on view rma.v_historial_visible is
  'Historial de cada Orden con el formato y el orden de la respuesta actual de la API (HistorialOut). Solo incluye los eventos que hoy aparecen en el historial; los tipos nuevos quedan fuera hasta un rediseño aprobado.';
comment on column rma.v_historial_visible.orden_id is 'Orden del historial (referencia a orden).';
comment on column rma.v_historial_visible.secuencia is 'Orden de la entrada dentro del historial de la Orden.';
comment on column rma.v_historial_visible.tipo_referencia is 'PROCESS_NODE o FUNCTIONAL_ACTION, como en la API actual.';
comment on column rma.v_historial_visible.referencia_id is 'Identificador PROC-REP o ACC-REP de la entrada.';
comment on column rma.v_historial_visible.accion is 'Acción de la entrada.';
comment on column rma.v_historial_visible.fecha is 'Fecha y hora de la entrada.';
comment on column rma.v_historial_visible.usuario_id is 'Código público del usuario responsable, si lo hay.';
comment on column rma.v_historial_visible.reparacion_detail_id is 'Código del Detalle (DET-nnn) afectado, si lo hay.';
comment on column rma.v_historial_visible.ejecucion_id is 'Código de la Ejecución afectada, si la hay.';
comment on column rma.v_historial_visible.pago_id is 'Código del pago afectado, si lo hay.';
comment on column rma.v_historial_visible.observacion is 'Observación de la entrada.';
