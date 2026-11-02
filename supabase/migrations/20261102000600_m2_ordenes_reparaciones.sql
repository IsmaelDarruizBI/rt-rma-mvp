-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 0600. M2 Órdenes y reparaciones.
--
-- La Orden es la unidad de consistencia: toda operación bloquea su fila
-- (SELECT ... FOR UPDATE) y confirma sus cambios en una sola transacción.
-- Las claves foráneas compuestas (por ejemplo detalle_id + orden_id)
-- garantizan que los registros relacionados pertenezcan a la misma Orden.

create sequence rma.orden_numero_seq;

comment on sequence rma.orden_numero_seq is
  'Numeración correlativa de las Órdenes; produce el código público OR-000001.';

-- ---------------------------------------------------------------------------
-- orden
-- ---------------------------------------------------------------------------
create table rma.orden (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique
    default ('OR-' || lpad(nextval('rma.orden_numero_seq')::text, 6, '0'))
    check (codigo ~ '^OR-[0-9]{6,}$'),
  origen text not null check (origen in ('CLIENTE_EXTERNO', 'RT_INTERNO', 'RMA_GARANTIA_REPARACION')),
  estado_workflow text not null check (estado_workflow in (
    'REQUERIMIENTO', 'EN_REVISION', 'HABILITADA', 'EN_COLA', 'EN_REPARACION',
    'REPARACION_LISTA', 'ENTREGADA', 'CANCELADA'
  )),
  posicion_proceso text not null check (posicion_proceso ~ '^(PROC-REP-[0-9]{3}|EVT-REP-[0-9]{3})$'),
  prioridad smallint not null default 0 check (prioridad >= 0),
  referencia_rt text,
  orden_origen_id uuid references rma.orden (id),
  cliente_id uuid references rma.cliente (id),
  equipo_id uuid not null references rma.equipo (id),
  -- Copia del Cliente al crear la Orden.
  cliente_tipo_persona text check (cliente_tipo_persona in ('FISICA', 'JURIDICA')),
  cliente_nombre text,
  cliente_documento_tipo text,
  cliente_documento_numero text,
  cliente_telefono text,
  cliente_email text,
  -- Copia del Equipo al crear la Orden (o al corregir la recepción antes de confirmarla).
  equipo_modelo_equipo_id uuid references rma.modelo_equipo (id),
  equipo_marca text not null check (btrim(equipo_marca) <> ''),
  equipo_modelo text not null check (btrim(equipo_modelo) <> ''),
  equipo_variante text,
  equipo_capacidad_gb integer check (equipo_capacidad_gb > 0),
  equipo_capacidad_texto text,
  equipo_color text,
  equipo_imei text,
  equipo_numero_serie text,
  equipo_tipo_producto_id text,
  falla_reportada text not null,
  -- Marcas de documento de Órdenes anteriores a los documentos emitidos.
  comprobante_recepcion_generado_en timestamptz,
  comprobante_final_generado_en timestamptz,
  garantia_generada_en timestamptz,
  version integer not null default 1 check (version >= 1),
  ultima_secuencia_evento integer not null default 0 check (ultima_secuencia_evento >= 0),
  creada_en timestamptz not null default now(),
  modificado_en timestamptz not null default now(),
  cerrada_en timestamptz,
  unique (id, orden_origen_id),
  constraint orden_cliente_segun_origen check (
    (origen = 'RT_INTERNO' and cliente_id is null)
    or (origen <> 'RT_INTERNO' and cliente_id is not null)
  ),
  constraint orden_copia_cliente check (cliente_id is null or cliente_nombre is not null),
  constraint orden_garantia_con_origen check (
    (origen = 'RMA_GARANTIA_REPARACION') = (orden_origen_id is not null)
  ),
  constraint orden_no_es_su_origen check (orden_origen_id is null or orden_origen_id <> id),
  constraint orden_cierre_coherente check (
    cerrada_en is null or estado_workflow = 'ENTREGADA' or posicion_proceso = 'EVT-REP-999'
  )
);

create index orden_estado on rma.orden (estado_workflow) where cerrada_en is null;
create index orden_cola on rma.orden (prioridad, creada_en) where estado_workflow = 'EN_COLA';
create index orden_cliente on rma.orden (cliente_id) where cliente_id is not null;
create index orden_equipo on rma.orden (equipo_id);
create index orden_origen on rma.orden (orden_origen_id) where orden_origen_id is not null;

create or replace function rma.orden_cerrada_no_cambia()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Las Órdenes no se borran.' using errcode = 'restrict_violation';
  end if;
  -- En una Orden cerrada solo avanza el contador de eventos: los eventos del
  -- propio cierre se registran después de la actualización que la cierra.
  if old.cerrada_en is not null
     and (to_jsonb(new) - 'ultima_secuencia_evento' - 'modificado_en')
         is distinct from (to_jsonb(old) - 'ultima_secuencia_evento' - 'modificado_en') then
    raise exception 'La Orden % está cerrada y no admite cambios (E1).', old.codigo
      using errcode = 'restrict_violation';
  end if;
  new.modificado_en := now();
  return new;
end;
$$;

comment on function rma.orden_cerrada_no_cambia() is
  'Impide modificar o borrar una Orden cerrada (entregada o en EVT-REP-999), salvo el contador de secuencia de eventos, y actualiza su fecha de modificación.';

create trigger orden_cerrada_no_cambia before update or delete on rma.orden
  for each row execute function rma.orden_cerrada_no_cambia();

-- Registros que no pueden agregarse a una Orden cerrada.
create or replace function rma.exigir_orden_abierta()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_cerrada timestamptz;
begin
  -- FOR SHARE: un cierre concurrente espera a este registro, o este ve el cierre confirmado.
  select cerrada_en into v_cerrada from rma.orden where id = new.orden_id for share;
  if v_cerrada is not null then
    raise exception 'La Orden está cerrada: no admite registros nuevos en %.', tg_table_name
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

comment on function rma.exigir_orden_abierta() is
  'Rechaza registros nuevos sobre una Orden cerrada. El cierre de la Orden debe ser la última actualización de la transacción que la cierra.';

comment on table rma.orden is
  'Orden de Reparación: unidad de gestión del proceso y límite de consistencia. Se crea sin Detalles. Guarda una copia de Cliente y Equipo al momento del ingreso; una Orden cerrada no se modifica.';
comment on column rma.orden.id is 'Identificador interno de la Orden.';
comment on column rma.orden.codigo is 'Número público de la Orden con formato OR-000001, asignado por la secuencia orden_numero_seq.';
comment on column rma.orden.origen is 'Origen: CLIENTE_EXTERNO, RT_INTERNO (equipo de Gestión RT, sin Cliente) o RMA_GARANTIA_REPARACION (garantía de una Orden entregada).';
comment on column rma.orden.estado_workflow is 'Hito del proceso: REQUERIMIENTO, EN_REVISION, HABILITADA, EN_COLA, EN_REPARACION, REPARACION_LISTA, ENTREGADA o CANCELADA. La situación técnica, la custodia y el cobro se calculan, no se guardan.';
comment on column rma.orden.posicion_proceso is 'Último nodo del proceso recorrido (PROC-REP-nnn) o EVT-REP-999 cuando el proceso terminó.';
comment on column rma.orden.prioridad is 'Prioridad de cola: 1 Urgente, 2 Alta, 3 Media, 4 Normal; 0 todavía sin priorizar. Se conservan los valores históricos fuera de esa escala.';
comment on column rma.orden.referencia_rt is 'Referencia de Gestión RT para un equipo RT_INTERNO; vacía en los demás orígenes.';
comment on column rma.orden.orden_origen_id is 'Orden entregada de la que nace una garantía RMA (referencia a orden); vacía en los demás orígenes.';
comment on column rma.orden.cliente_id is 'Cliente que deja el equipo (referencia a cliente); vacío en RT_INTERNO.';
comment on column rma.orden.equipo_id is 'Equipo físico que se repara (referencia a equipo); una garantía RMA apunta al mismo Equipo que su Orden de origen.';
comment on column rma.orden.cliente_tipo_persona is 'Copia del tipo de persona del Cliente al crear la Orden.';
comment on column rma.orden.cliente_nombre is 'Copia del nombre o razón social del Cliente al crear la Orden; es la que muestran sus documentos.';
comment on column rma.orden.cliente_documento_tipo is 'Copia del código del tipo de documento principal del Cliente al crear la Orden.';
comment on column rma.orden.cliente_documento_numero is 'Copia del número del documento principal del Cliente al crear la Orden.';
comment on column rma.orden.cliente_telefono is 'Copia del teléfono del Cliente al crear la Orden.';
comment on column rma.orden.cliente_email is 'Copia del correo del Cliente al crear la Orden.';
comment on column rma.orden.equipo_modelo_equipo_id is 'Copia del modelo técnico elegido al ingresar (referencia a modelo_equipo); vacía si se cargó a mano.';
comment on column rma.orden.equipo_marca is 'Copia de la marca del equipo al ingresar.';
comment on column rma.orden.equipo_modelo is 'Copia del modelo comercial del equipo al ingresar.';
comment on column rma.orden.equipo_variante is 'Copia de la variante del equipo al ingresar; vacía en la versión estándar.';
comment on column rma.orden.equipo_capacidad_gb is 'Copia de la capacidad normalizada en GB al ingresar.';
comment on column rma.orden.equipo_capacidad_texto is 'Copia de la capacidad tal como se cargó (texto original de Órdenes anteriores).';
comment on column rma.orden.equipo_color is 'Copia del color del equipo al ingresar.';
comment on column rma.orden.equipo_imei is 'Copia del IMEI del equipo al ingresar.';
comment on column rma.orden.equipo_numero_serie is 'Copia del número de serie del equipo al ingresar.';
comment on column rma.orden.equipo_tipo_producto_id is 'tp_id del catálogo comercial de Ventas en Órdenes anteriores al catálogo técnico; dato histórico sin relación (G-4).';
comment on column rma.orden.falla_reportada is 'Falla que declaró quien dejó el equipo, al momento del ingreso.';
comment on column rma.orden.comprobante_recepcion_generado_en is 'Marca histórica: cuándo se generó el comprobante de recepción en Órdenes sin copia del documento emitido.';
comment on column rma.orden.comprobante_final_generado_en is 'Marca histórica: cuándo se generó el comprobante final en Órdenes sin copia del documento emitido.';
comment on column rma.orden.garantia_generada_en is 'Marca histórica: cuándo se generó la garantía en Órdenes sin copia del documento emitido.';
comment on column rma.orden.version is 'Versión de la Orden; aumenta en cada operación que la modifica y permite detectar pantallas desactualizadas.';
comment on column rma.orden.ultima_secuencia_evento is 'Último número de secuencia asignado a un evento de esta Orden; lo mantiene el trigger de evento_negocio.';
comment on column rma.orden.creada_en is 'Fecha y hora de creación de la Orden.';
comment on column rma.orden.modificado_en is 'Fecha y hora de la última modificación de la Orden.';
comment on column rma.orden.cerrada_en is 'Fecha y hora en que la Orden quedó cerrada (entregada o en EVT-REP-999); vacía mientras está abierta.';

alter table rma.accion_usuario
  add constraint accion_usuario_orden_fk foreign key (orden_id) references rma.orden (id);

-- ---------------------------------------------------------------------------
-- recepcion
-- ---------------------------------------------------------------------------
create table rma.recepcion (
  orden_id uuid primary key references rma.orden (id),
  registro text not null default 'INGRESO' check (registro in ('INGRESO', 'REGULARIZACION')),
  estado_fisico text,
  accesorios text[] not null default '{}',
  observaciones text,
  notas_internas text,
  checkin_ingreso boolean,
  registrado_por uuid not null references rma.usuario (id),
  registrado_en timestamptz not null default now(),
  entrega_nombre text,
  entrega_documento_tipo text,
  entrega_documento_numero text,
  entrega_telefono text,
  entrega_vinculo text check (entrega_vinculo in ('TITULAR', 'EMPLEADO_REPRESENTANTE', 'TERCERO')),
  confirmada_por uuid references rma.usuario (id),
  confirmada_en timestamptz,
  confirmacion_observaciones text,
  no_recibido_por uuid references rma.usuario (id),
  no_recibido_en timestamptz,
  no_recibido_motivo text,
  modificado_en timestamptz not null default now(),
  constraint recepcion_confirmacion_completa check (
    (confirmada_por is null) = (confirmada_en is null)
  ),
  constraint recepcion_no_recibido_completo check (
    (no_recibido_por is null) = (no_recibido_en is null)
    and (no_recibido_en is null or no_recibido_motivo is not null)
  ),
  constraint recepcion_una_decision check (confirmada_en is null or no_recibido_en is null),
  constraint recepcion_persona_entrega check (entrega_vinculo is null or entrega_nombre is not null)
);

create or replace function rma.recepcion_decidida_no_cambia()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'La recepción de una Orden no se borra.' using errcode = 'restrict_violation';
  end if;
  if old.confirmada_en is not null or old.no_recibido_en is not null then
    raise exception 'La custodia ya se decidió: los datos de recepción no se corrigen; se agregan notas.'
      using errcode = 'restrict_violation';
  end if;
  new.modificado_en := now();
  return new;
end;
$$;

comment on function rma.recepcion_decidida_no_cambia() is
  'Impide corregir la recepción una vez decidida la custodia (confirmada o no recibida) e impide su borrado.';

create trigger recepcion_decidida_no_cambia before update or delete on rma.recepcion
  for each row execute function rma.recepcion_decidida_no_cambia();

comment on table rma.recepcion is
  'Ingreso físico del equipo y decisión de custodia. La custodia se calcula a partir de esta fila y de la salida; se decide una sola vez (confirmada o no recibida) y después solo se agregan notas. Una Orden sin recepción es la situación histórica SIN_REGISTRO.';
comment on column rma.recepcion.orden_id is 'Orden a la que pertenece la recepción (referencia a orden); una por Orden.';
comment on column rma.recepcion.registro is 'Cómo nació: INGRESO, al crear la Orden, o REGULARIZACION, registrada después en una Orden anterior.';
comment on column rma.recepcion.estado_fisico is 'Estado físico del equipo al recibirlo, visible en los comprobantes.';
comment on column rma.recepcion.accesorios is 'Accesorios recibidos con el equipo; ya no se piden al ingresar y se conservan en las Órdenes que los tienen.';
comment on column rma.recepcion.observaciones is 'Observaciones del equipo (daños, humedad, faltantes), visibles para el taller y en los comprobantes.';
comment on column rma.recepcion.notas_internas is 'Notas operativas que solo se ven dentro de la aplicación; nunca salen en un documento.';
comment on column rma.recepcion.checkin_ingreso is 'Check-in registrado al ingresar en Órdenes anteriores a UAT-009; las nuevas lo registran antes de la entrega en checkin.';
comment on column rma.recepcion.registrado_por is 'Usuario que registró los datos del ingreso (referencia a usuario).';
comment on column rma.recepcion.registrado_en is 'Fecha y hora en que se registraron los datos vigentes del ingreso.';
comment on column rma.recepcion.entrega_nombre is 'Nombre de la persona que entregó el equipo al ingresar, sea o no el titular; prevista hasta que la pantalla la pida.';
comment on column rma.recepcion.entrega_documento_tipo is 'Tipo de documento de la persona que entregó el equipo, si se informó.';
comment on column rma.recepcion.entrega_documento_numero is 'Número de documento de la persona que entregó el equipo, si se informó.';
comment on column rma.recepcion.entrega_telefono is 'Teléfono de la persona que entregó el equipo, si se informó.';
comment on column rma.recepcion.entrega_vinculo is 'Vínculo de quien entregó el equipo con el Cliente: TITULAR, EMPLEADO_REPRESENTANTE o TERCERO.';
comment on column rma.recepcion.confirmada_por is 'Usuario que confirmó la recepción física del equipo (referencia a usuario).';
comment on column rma.recepcion.confirmada_en is 'Fecha y hora en que se confirmó que el equipo quedó en el local; desde entonces está bajo custodia.';
comment on column rma.recepcion.confirmacion_observaciones is 'Observaciones de la confirmación de recepción.';
comment on column rma.recepcion.no_recibido_por is 'Usuario que registró que el equipo nunca ingresó (referencia a usuario).';
comment on column rma.recepcion.no_recibido_en is 'Fecha y hora en que se registró que el equipo nunca ingresó; nunca se deduce.';
comment on column rma.recepcion.no_recibido_motivo is 'Por qué se registró el equipo como no recibido.';
comment on column rma.recepcion.modificado_en is 'Fecha y hora de la última modificación de la fila.';

-- ---------------------------------------------------------------------------
-- recepcion_version
-- ---------------------------------------------------------------------------
create table rma.recepcion_version (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null references rma.recepcion (orden_id),
  datos jsonb not null check (jsonb_typeof(datos) = 'object'),
  registrado_por uuid not null references rma.usuario (id),
  registrado_en timestamptz not null,
  reemplazado_por uuid not null references rma.usuario (id),
  reemplazado_en timestamptz not null default now(),
  check (reemplazado_en >= registrado_en)
);

create index recepcion_version_orden on rma.recepcion_version (orden_id, reemplazado_en);

create trigger recepcion_version_inmutable before update or delete on rma.recepcion_version
  for each row execute function rma.impedir_modificacion();

comment on table rma.recepcion_version is
  'Datos del ingreso y del equipo reemplazados por una corrección, antes de decidir la custodia.';
comment on column rma.recepcion_version.id is 'Identificador interno de la versión.';
comment on column rma.recepcion_version.orden_id is 'Recepción corregida (referencia a recepcion, por la Orden).';
comment on column rma.recepcion_version.datos is 'Copia completa de los datos del ingreso y del equipo tal como estaban antes de la corrección.';
comment on column rma.recepcion_version.registrado_por is 'Usuario que había registrado esos datos (referencia a usuario).';
comment on column rma.recepcion_version.registrado_en is 'Fecha y hora en que se habían registrado esos datos.';
comment on column rma.recepcion_version.reemplazado_por is 'Usuario que los reemplazó con la corrección (referencia a usuario).';
comment on column rma.recepcion_version.reemplazado_en is 'Fecha y hora de la corrección.';

-- ---------------------------------------------------------------------------
-- recepcion_nota
-- ---------------------------------------------------------------------------
create table rma.recepcion_nota (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null references rma.recepcion (orden_id),
  texto text not null check (btrim(texto) <> ''),
  interna boolean not null default false,
  usuario_id uuid not null references rma.usuario (id),
  registrada_en timestamptz not null default now()
);

create index recepcion_nota_orden on rma.recepcion_nota (orden_id, registrada_en);

create trigger recepcion_nota_inmutable before update or delete on rma.recepcion_nota
  for each row execute function rma.impedir_modificacion();
create trigger recepcion_nota_orden_abierta before insert on rma.recepcion_nota
  for each row execute function rma.exigir_orden_abierta();

comment on table rma.recepcion_nota is
  'Notas agregadas después del ingreso, también después de confirmar la custodia.';
comment on column rma.recepcion_nota.id is 'Identificador interno de la nota.';
comment on column rma.recepcion_nota.orden_id is 'Recepción a la que se agrega la nota (referencia a recepcion, por la Orden).';
comment on column rma.recepcion_nota.texto is 'Texto de la nota.';
comment on column rma.recepcion_nota.interna is 'Si la nota es interna: solo se ve dentro de la aplicación y nunca sale en un documento.';
comment on column rma.recepcion_nota.usuario_id is 'Usuario que agregó la nota (referencia a usuario).';
comment on column rma.recepcion_nota.registrada_en is 'Fecha y hora en que se agregó la nota.';

-- ---------------------------------------------------------------------------
-- checkin
-- ---------------------------------------------------------------------------
create table rma.checkin (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null references rma.orden (id),
  realizado boolean not null,
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null default now()
);

create index checkin_orden on rma.checkin (orden_id, registrado_en);

create trigger checkin_inmutable before update or delete on rma.checkin
  for each row execute function rma.impedir_modificacion();
create trigger checkin_orden_abierta before insert on rma.checkin
  for each row execute function rma.exigir_orden_abierta();

comment on table rma.checkin is
  'Registros del check-in antes de la entrega: si se pudieron verificar las funciones básicas del equipo. El vigente es el último (ABI-32). Registrarlo reasigna la garantía sugerida de cada Detalle en la misma transacción.';
comment on column rma.checkin.id is 'Identificador interno del registro.';
comment on column rma.checkin.orden_id is 'Orden a la que pertenece (referencia a orden).';
comment on column rma.checkin.realizado is 'Verdadero si se pudieron verificar las funciones básicas (garantía sugerida de 90 días); falso si no (30 días).';
comment on column rma.checkin.usuario_id is 'Usuario que registró el check-in (referencia a usuario).';
comment on column rma.checkin.registrado_en is 'Fecha y hora del registro.';

-- ---------------------------------------------------------------------------
-- salida
-- ---------------------------------------------------------------------------
create table rma.salida (
  orden_id uuid primary key references rma.orden (id),
  tipo text not null check (tipo in ('REPARACION_TERMINADA', 'DEVOLUCION_SIN_REPARACION', 'DEVOLUCION_GESTION_RT')),
  entregado_por uuid not null references rma.usuario (id),
  retira_nombre text not null check (btrim(retira_nombre) <> ''),
  retira_identificacion text,
  retira_telefono text,
  retira_vinculo text check (retira_vinculo in ('TITULAR', 'EMPLEADO_REPRESENTANTE', 'TERCERO', 'GESTION_RT')),
  registrada_en timestamptz not null default now(),
  observaciones text
);

create trigger salida_inmutable before update or delete on rma.salida
  for each row execute function rma.impedir_modificacion();

comment on table rma.salida is
  'Salida física del equipo: entrega de una reparación terminada, devolución sin reparar o devolución a Gestión RT. Una por Orden; una devolución no convierte una CANCELADA en ENTREGADA.';
comment on column rma.salida.orden_id is 'Orden cuyo equipo sale (referencia a orden).';
comment on column rma.salida.tipo is 'REPARACION_TERMINADA, DEVOLUCION_SIN_REPARACION (Orden cancelada o sin reparación) o DEVOLUCION_GESTION_RT (equipo RT_INTERNO).';
comment on column rma.salida.entregado_por is 'Usuario que entregó el equipo (referencia a usuario).';
comment on column rma.salida.retira_nombre is 'Nombre de la persona que retiró el equipo, tal como se registró en el acto; no exige ser un Cliente.';
comment on column rma.salida.retira_identificacion is 'Identificación de quien retiró (DNI u otra), tal como se registró.';
comment on column rma.salida.retira_telefono is 'Teléfono de quien retiró, si se informó.';
comment on column rma.salida.retira_vinculo is 'Vínculo de quien retiró con el Cliente: TITULAR, EMPLEADO_REPRESENTANTE, TERCERO o GESTION_RT.';
comment on column rma.salida.registrada_en is 'Fecha y hora de la salida; desde ella corre la garantía de cada trabajo.';
comment on column rma.salida.observaciones is 'Observaciones de la entrega o devolución.';

-- ---------------------------------------------------------------------------
-- foto
-- ---------------------------------------------------------------------------
create table rma.foto (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  orden_id uuid not null references rma.orden (id),
  objeto_clave text not null unique,
  tipo_contenido text not null check (tipo_contenido like 'image/%'),
  tamano_bytes integer not null check (tamano_bytes > 0),
  nombre_original text,
  usuario_id uuid not null references rma.usuario (id),
  registrada_en timestamptz not null default now()
);

create index foto_orden on rma.foto (orden_id, registrada_en);

create or replace function rma.foto_limite_por_orden()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  -- Bloquea la Orden para que dos altas simultáneas no superen el límite.
  perform 1 from rma.orden where id = new.orden_id for update;
  if (select count(*) from rma.foto where orden_id = new.orden_id) >= 10 then
    raise exception 'La Orden ya tiene 10 fotos, el máximo.' using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

comment on function rma.foto_limite_por_orden() is
  'Rechaza la undécima foto de una Orden. Bloquea la Orden antes de contar, así que el límite se respeta aunque haya altas simultáneas.';

create trigger foto_limite_por_orden before insert on rma.foto
  for each row execute function rma.foto_limite_por_orden();
create trigger foto_orden_abierta before insert on rma.foto
  for each row execute function rma.exigir_orden_abierta();
create trigger foto_inmutable before update or delete on rma.foto
  for each row execute function rma.impedir_modificacion();

comment on table rma.foto is
  'Referencias a las fotos del equipo de una Orden, como máximo 10. La imagen vive en el almacenamiento de objetos privado, nunca en la base.';
comment on column rma.foto.id is 'Identificador interno de la foto.';
comment on column rma.foto.codigo is 'Identificador público de la foto, el que hoy usa la API.';
comment on column rma.foto.orden_id is 'Orden a la que pertenece (referencia a orden).';
comment on column rma.foto.objeto_clave is 'Clave del objeto en el almacenamiento privado donde está la imagen.';
comment on column rma.foto.tipo_contenido is 'Tipo de la imagen, por ejemplo image/jpeg.';
comment on column rma.foto.tamano_bytes is 'Tamaño de la imagen en bytes.';
comment on column rma.foto.nombre_original is 'Nombre del archivo tal como lo subió el usuario.';
comment on column rma.foto.usuario_id is 'Usuario que subió la foto (referencia a usuario).';
comment on column rma.foto.registrada_en is 'Fecha y hora en que se agregó la foto.';

-- ---------------------------------------------------------------------------
-- detalle
-- ---------------------------------------------------------------------------
create table rma.detalle (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null references rma.orden (id),
  codigo text not null check (codigo ~ '^DET-[0-9]{3,}$'),
  estado text not null default 'DEFINIDO' check (estado in ('DEFINIDO', 'EN_PROGRESO', 'COMPLETO', 'CANCELADO')),
  condicion text not null default 'SIN_BLOQUEO'
    check (condicion in ('SIN_BLOQUEO', 'REQUIERE_DEFINICION', 'BLOQUEADO_POR_RECURSOS')),
  control_estado text not null default 'PENDIENTE' check (control_estado in ('PENDIENTE', 'APROBADO')),
  control_usuario_id uuid references rma.usuario (id),
  control_en timestamptz,
  control_observaciones text,
  garantia_dias integer not null check (garantia_dias >= 0),
  garantia_dias_sugerida integer check (garantia_dias_sugerida >= 0),
  detalle_origen_id uuid references rma.detalle (id),
  observaciones text,
  cancelacion_origen text check (cancelacion_origen in ('INTERNA', 'RECHAZO_CLIENTE', 'DESISTIMIENTO_CLIENTE')),
  cancelacion_motivo text,
  cancelado_por uuid references rma.usuario (id),
  cancelado_en timestamptz,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now(),
  unique (orden_id, codigo),
  unique (id, orden_id),
  constraint detalle_cancelacion_completa check (
    (estado = 'CANCELADO') = (cancelado_en is not null)
    and (cancelado_en is null or (cancelacion_origen is not null and cancelacion_motivo is not null and cancelado_por is not null))
  ),
  constraint detalle_control_completo check (
    control_estado = 'PENDIENTE' or (control_usuario_id is not null and control_en is not null)
  ),
  constraint detalle_no_es_su_origen check (detalle_origen_id is null or detalle_origen_id <> id)
);

create index detalle_origen on rma.detalle (detalle_origen_id) where detalle_origen_id is not null;

create trigger detalle_modificacion before update on rma.detalle
  for each row execute function rma.marcar_modificacion();
create trigger detalle_sin_borrado before delete on rma.detalle
  for each row execute function rma.impedir_borrado();
create trigger detalle_orden_abierta before insert on rma.detalle
  for each row execute function rma.exigir_orden_abierta();

comment on table rma.detalle is
  'Detalle de Reparación: un trabajo de la Orden con identidad estable y su estado actual. Su definición vive en detalle_version; la vigente es la de mayor número. Nunca se borra.';
comment on column rma.detalle.id is 'Identificador interno del Detalle; no cambia al redefinirlo.';
comment on column rma.detalle.orden_id is 'Orden a la que pertenece (referencia a orden).';
comment on column rma.detalle.codigo is 'Número público del Detalle dentro de su Orden, con formato DET-001.';
comment on column rma.detalle.estado is 'Avance técnico: DEFINIDO (pendiente), EN_PROGRESO, COMPLETO o CANCELADO. COMPLETO vuelve a DEFINIDO solo por un rechazo en el control.';
comment on column rma.detalle.condicion is 'Bloqueo, independiente del estado: SIN_BLOQUEO, REQUIERE_DEFINICION (tras «Requiere redefinición») o BLOQUEADO_POR_RECURSOS (sin insumos).';
comment on column rma.detalle.control_estado is 'Control técnico vigente: PENDIENTE o APROBADO. El historial de controles está en control_tecnico.';
comment on column rma.detalle.control_usuario_id is 'Usuario que hizo el control vigente (referencia a usuario).';
comment on column rma.detalle.control_en is 'Fecha y hora del control vigente.';
comment on column rma.detalle.control_observaciones is 'Observaciones del control vigente.';
comment on column rma.detalle.garantia_dias is 'Plazo definitivo de garantía del trabajo, en días corridos desde la entrega; es el que sale en el documento.';
comment on column rma.detalle.garantia_dias_sugerida is 'Plazo sugerido por el check-in (90 o 30 días) o, sin check-in, el del catálogo; vacío en Detalles anteriores.';
comment on column rma.detalle.detalle_origen_id is 'En una garantía RMA, el Detalle de la Orden de origen que motiva el reproceso (referencia a detalle).';
comment on column rma.detalle.observaciones is 'Observaciones del Detalle.';
comment on column rma.detalle.cancelacion_origen is 'Por qué se canceló: INTERNA, RECHAZO_CLIENTE o DESISTIMIENTO_CLIENTE; solo en un Detalle CANCELADO.';
comment on column rma.detalle.cancelacion_motivo is 'Motivo de la cancelación.';
comment on column rma.detalle.cancelado_por is 'Usuario que canceló el Detalle (referencia a usuario).';
comment on column rma.detalle.cancelado_en is 'Fecha y hora de la cancelación; un Detalle cancelado conserva su definición y deja de cobrarse.';
comment on column rma.detalle.creado_en is 'Fecha y hora en que se agregó el Detalle.';
comment on column rma.detalle.modificado_en is 'Fecha y hora de la última modificación del estado actual.';

-- ---------------------------------------------------------------------------
-- orden_detalle_origen
-- ---------------------------------------------------------------------------
create table rma.orden_detalle_origen (
  orden_id uuid not null,
  orden_origen_id uuid not null,
  detalle_id uuid not null,
  primary key (orden_id, detalle_id),
  constraint orden_detalle_origen_orden foreign key (orden_id, orden_origen_id)
    references rma.orden (id, orden_origen_id),
  constraint orden_detalle_origen_detalle foreign key (detalle_id, orden_origen_id)
    references rma.detalle (id, orden_id)
);

create index orden_detalle_origen_detalle_idx on rma.orden_detalle_origen (detalle_id);

create trigger orden_detalle_origen_inmutable before update or delete on rma.orden_detalle_origen
  for each row execute function rma.impedir_modificacion();

comment on table rma.orden_detalle_origen is
  'Detalles de la Orden de origen que reclama una garantía RMA. Las claves foráneas garantizan que cada Detalle pertenezca a esa Orden de origen.';
comment on column rma.orden_detalle_origen.orden_id is 'Orden de garantía (referencia a orden).';
comment on column rma.orden_detalle_origen.orden_origen_id is 'Orden entregada de la que nace la garantía, repetida para validar el vínculo (referencia a orden).';
comment on column rma.orden_detalle_origen.detalle_id is 'Detalle reclamado de la Orden de origen (referencia a detalle).';

-- ---------------------------------------------------------------------------
-- detalle_version
-- ---------------------------------------------------------------------------
create table rma.detalle_version (
  id uuid primary key default gen_random_uuid(),
  detalle_id uuid not null references rma.detalle (id),
  numero integer not null check (numero >= 1),
  tipo_reparacion_id uuid not null references rma.tipo_reparacion (id),
  descripcion text,
  precio numeric(14, 2) not null check (precio >= 0),
  puntaje integer not null check (puntaje >= 0),
  garantia_dias integer not null check (garantia_dias >= 0),
  definida_por uuid references rma.usuario (id),
  definida_en timestamptz not null default now(),
  motivo text,
  reemplaza_a uuid,
  unique (detalle_id, numero),
  unique (id, detalle_id),
  constraint detalle_version_reemplazo foreign key (reemplaza_a, detalle_id)
    references rma.detalle_version (id, detalle_id),
  constraint detalle_version_primera check ((numero = 1) = (reemplaza_a is null))
);

create trigger detalle_version_inmutable before update or delete on rma.detalle_version
  for each row execute function rma.impedir_modificacion();

comment on table rma.detalle_version is
  'Definiciones inmutables de cada Detalle (ABI-16). La versión 1 es la inicial; cada redefinición crea la siguiente sin modificar las anteriores. La vigente es la de mayor número.';
comment on column rma.detalle_version.id is 'Identificador interno de la versión.';
comment on column rma.detalle_version.detalle_id is 'Detalle definido (referencia a detalle).';
comment on column rma.detalle_version.numero is 'Número de versión dentro del Detalle, desde 1.';
comment on column rma.detalle_version.tipo_reparacion_id is 'Tipo de reparación elegido (referencia a tipo_reparacion); TR-OTROS para la reparación no tipificada.';
comment on column rma.detalle_version.descripcion is 'Qué se repara en una reparación «Otros»; vacía en los tipos del catálogo.';
comment on column rma.detalle_version.precio is 'Precio en pesos copiado del catálogo, o cargado a mano en «Otros», al momento de definir; no se relee del catálogo.';
comment on column rma.detalle_version.puntaje is 'Puntaje copiado del catálogo al momento de definir.';
comment on column rma.detalle_version.garantia_dias is 'Garantía de catálogo en días copiada al momento de definir.';
comment on column rma.detalle_version.definida_por is 'Usuario que definió o redefinió, cualquiera sea su rol (PC-02) (referencia a usuario); vacío si un registro histórico no lo conserva.';
comment on column rma.detalle_version.definida_en is 'Fecha y hora de la definición.';
comment on column rma.detalle_version.motivo is 'Motivo de la redefinición, cuando se informó.';
comment on column rma.detalle_version.reemplaza_a is 'Versión anterior del mismo Detalle que esta reemplaza (referencia a detalle_version); vacía en la versión 1.';

-- ---------------------------------------------------------------------------
-- decision_cliente
-- ---------------------------------------------------------------------------
create table rma.decision_cliente (
  id uuid primary key default gen_random_uuid(),
  detalle_version_id uuid not null references rma.detalle_version (id),
  resultado text not null check (resultado in ('AUTORIZADO', 'RECHAZADO')),
  canal text not null check (canal in ('PRESENCIAL', 'TELEFONO', 'WHATSAPP', 'EMAIL', 'OTRO')),
  usuario_id uuid not null references rma.usuario (id),
  registrada_en timestamptz not null default now(),
  observaciones text,
  persona_decide text
);

create index decision_cliente_version on rma.decision_cliente (detalle_version_id, registrada_en);

create trigger decision_cliente_inmutable before update or delete on rma.decision_cliente
  for each row execute function rma.impedir_modificacion();

comment on table rma.decision_cliente is
  'Autorizaciones y rechazos del cliente sobre una versión de definición. «Sin respuesta» no se registra: el pendiente se deriva de la versión vigente sin decisión. Una redefinición no hereda la decisión anterior.';
comment on column rma.decision_cliente.id is 'Identificador interno de la decisión.';
comment on column rma.decision_cliente.detalle_version_id is 'Versión de definición decidida (referencia a detalle_version).';
comment on column rma.decision_cliente.resultado is 'AUTORIZADO o RECHAZADO.';
comment on column rma.decision_cliente.canal is 'Por dónde respondió el cliente: PRESENCIAL, TELEFONO, WHATSAPP, EMAIL u OTRO.';
comment on column rma.decision_cliente.usuario_id is 'Usuario que registró la decisión (referencia a usuario).';
comment on column rma.decision_cliente.registrada_en is 'Fecha y hora en que se registró la decisión.';
comment on column rma.decision_cliente.observaciones is 'Observaciones de la decisión.';
comment on column rma.decision_cliente.persona_decide is 'Persona que tomó la decisión en nombre de una empresa; prevista, sin captura en esta etapa.';

-- ---------------------------------------------------------------------------
-- ajuste_garantia
-- ---------------------------------------------------------------------------
create table rma.ajuste_garantia (
  id uuid primary key default gen_random_uuid(),
  detalle_id uuid not null references rma.detalle (id),
  dias_anteriores integer not null check (dias_anteriores >= 0),
  dias_nuevos integer not null check (dias_nuevos >= 0),
  motivo text not null check (btrim(motivo) <> ''),
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null default now()
);

create index ajuste_garantia_detalle on rma.ajuste_garantia (detalle_id, registrado_en);

create trigger ajuste_garantia_inmutable before update or delete on rma.ajuste_garantia
  for each row execute function rma.impedir_modificacion();

comment on table rma.ajuste_garantia is
  'Cambios manuales del plazo de garantía de un Detalle. Un ajuste manual nunca lo pisa el check-in.';
comment on column rma.ajuste_garantia.id is 'Identificador interno del ajuste.';
comment on column rma.ajuste_garantia.detalle_id is 'Detalle ajustado (referencia a detalle).';
comment on column rma.ajuste_garantia.dias_anteriores is 'Plazo en días antes del ajuste.';
comment on column rma.ajuste_garantia.dias_nuevos is 'Plazo en días después del ajuste.';
comment on column rma.ajuste_garantia.motivo is 'Motivo del ajuste.';
comment on column rma.ajuste_garantia.usuario_id is 'Usuario que ajustó el plazo (referencia a usuario).';
comment on column rma.ajuste_garantia.registrado_en is 'Fecha y hora del ajuste.';

-- ---------------------------------------------------------------------------
-- toma
-- ---------------------------------------------------------------------------
create table rma.toma (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  orden_id uuid not null references rma.orden (id),
  usuario_id uuid not null references rma.usuario (id),
  mesa_trabajo_id uuid not null references rma.mesa_trabajo (id),
  estado text not null default 'ACTIVA' check (estado in ('ACTIVA', 'CERRADA')),
  inicio timestamptz not null default now(),
  fin timestamptz,
  liberada_por uuid references rma.usuario (id),
  motivo_liberacion text,
  unique (id, orden_id),
  constraint toma_cierre_coherente check ((estado = 'CERRADA') = (fin is not null)),
  constraint toma_fin_ordenado check (fin is null or fin >= inicio),
  constraint toma_liberacion_ajena check (liberada_por is null or motivo_liberacion is not null)
);

-- Como máximo una toma activa por Orden.
create unique index toma_activa_por_orden on rma.toma (orden_id) where estado = 'ACTIVA';
create index toma_orden on rma.toma (orden_id, inicio);
create index toma_usuario on rma.toma (usuario_id) where estado = 'ACTIVA';

create trigger toma_sin_borrado before delete on rma.toma
  for each row execute function rma.impedir_borrado();
create trigger toma_orden_abierta before insert on rma.toma
  for each row execute function rma.exigir_orden_abierta();

comment on table rma.toma is
  'Participación activa de un técnico sobre una Orden, desde una Mesa. Puede cerrarse sin haber iniciado ninguna Ejecución. Como máximo una ACTIVA por Orden.';
comment on column rma.toma.id is 'Identificador interno de la toma.';
comment on column rma.toma.codigo is 'Identificador público de la toma, el que hoy usa la API.';
comment on column rma.toma.orden_id is 'Orden tomada (referencia a orden).';
comment on column rma.toma.usuario_id is 'Técnico titular de la toma (referencia a usuario).';
comment on column rma.toma.mesa_trabajo_id is 'Mesa desde la que se tomó la Orden (referencia a mesa_trabajo).';
comment on column rma.toma.estado is 'ACTIVA mientras el técnico trabaja la Orden; CERRADA al liberarla o cuando el flujo la cierra.';
comment on column rma.toma.inicio is 'Fecha y hora en que se tomó la Orden.';
comment on column rma.toma.fin is 'Fecha y hora en que se cerró la toma; vacía mientras está activa.';
comment on column rma.toma.liberada_por is 'Usuario distinto del titular que liberó la toma (referencia a usuario); vacío si la cerró su titular o el flujo.';
comment on column rma.toma.motivo_liberacion is 'Motivo de la liberación por otro usuario.';

-- ---------------------------------------------------------------------------
-- ejecucion
-- ---------------------------------------------------------------------------
create table rma.ejecucion (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  orden_id uuid not null,
  detalle_id uuid not null,
  detalle_version_id uuid not null,
  toma_id uuid not null,
  usuario_id uuid not null references rma.usuario (id),
  estado text not null default 'EN_PROGRESO' check (estado in ('EN_PROGRESO', 'COMPLETADO', 'INTERRUMPIDO')),
  inicio timestamptz not null default now(),
  fin timestamptz,
  observaciones text,
  motivo_interrupcion text,
  motivo_redefinicion text,
  unique (id, detalle_id),
  unique (id, orden_id),
  constraint ejecucion_detalle foreign key (detalle_id, orden_id) references rma.detalle (id, orden_id),
  constraint ejecucion_version foreign key (detalle_version_id, detalle_id) references rma.detalle_version (id, detalle_id),
  constraint ejecucion_toma foreign key (toma_id, orden_id) references rma.toma (id, orden_id),
  constraint ejecucion_cierre_coherente check ((estado = 'EN_PROGRESO') = (fin is null)),
  constraint ejecucion_fin_ordenado check (fin is null or fin >= inicio),
  constraint ejecucion_motivos check (
    estado = 'INTERRUMPIDO' or (motivo_interrupcion is null and motivo_redefinicion is null)
  )
);

-- Como máximo una Ejecución en curso por Orden (BR-REP-007).
create unique index ejecucion_en_curso_por_orden on rma.ejecucion (orden_id) where estado = 'EN_PROGRESO';
create index ejecucion_orden on rma.ejecucion (orden_id, inicio);
create index ejecucion_detalle on rma.ejecucion (detalle_id, inicio);
create index ejecucion_toma on rma.ejecucion (toma_id);

create or replace function rma.ejecucion_terminada_no_cambia()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Las Ejecuciones no se borran.' using errcode = 'restrict_violation';
  end if;
  if old.estado <> 'EN_PROGRESO' then
    raise exception 'La Ejecución % ya terminó y no se reabre: continuar es una Ejecución nueva.', old.codigo
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

comment on function rma.ejecucion_terminada_no_cambia() is
  'Impide modificar una Ejecución terminada (COMPLETADO o INTERRUMPIDO) e impide borrar Ejecuciones.';

create trigger ejecucion_terminada_no_cambia before update or delete on rma.ejecucion
  for each row execute function rma.ejecucion_terminada_no_cambia();
create trigger ejecucion_orden_abierta before insert on rma.ejecucion
  for each row execute function rma.exigir_orden_abierta();

comment on table rma.ejecucion is
  'Un trabajo concreto sobre un Detalle, dentro de una toma. Una Ejecución terminada no se reabre; continuar un Detalle interrumpido es una Ejecución nueva.';
comment on column rma.ejecucion.id is 'Identificador interno de la Ejecución.';
comment on column rma.ejecucion.codigo is 'Identificador público de la Ejecución, el que hoy usa la API.';
comment on column rma.ejecucion.orden_id is 'Orden a la que pertenece, repetida para validar el vínculo y la unicidad de la Ejecución en curso (referencia a orden).';
comment on column rma.ejecucion.detalle_id is 'Detalle que se trabaja (referencia a detalle).';
comment on column rma.ejecucion.detalle_version_id is 'Versión de definición vigente al iniciar la Ejecución (referencia a detalle_version).';
comment on column rma.ejecucion.toma_id is 'Toma dentro de la cual se ejecuta (referencia a toma).';
comment on column rma.ejecucion.usuario_id is 'Técnico que ejecuta (referencia a usuario).';
comment on column rma.ejecucion.estado is 'EN_PROGRESO, COMPLETADO o INTERRUMPIDO (incluye «Requiere redefinición», que además deja el Detalle en REQUIERE_DEFINICION).';
comment on column rma.ejecucion.inicio is 'Fecha y hora de inicio, cuando se reservaron los insumos.';
comment on column rma.ejecucion.fin is 'Fecha y hora de cierre; vacía mientras está en curso.';
comment on column rma.ejecucion.observaciones is 'Observaciones del técnico al cerrar la Ejecución.';
comment on column rma.ejecucion.motivo_interrupcion is 'Motivo por el que se interrumpió el trabajo, incluida la interrupción por liberación de la toma.';
comment on column rma.ejecucion.motivo_redefinicion is 'Motivo por el que la definición del Detalle dejó de servir («Requiere redefinición»).';

-- ---------------------------------------------------------------------------
-- ejecucion_insumo
-- ---------------------------------------------------------------------------
create table rma.ejecucion_insumo (
  ejecucion_id uuid not null references rma.ejecucion (id),
  insumo_id uuid not null references rma.insumo (id),
  cantidad_utilizada numeric(12, 3) not null check (cantidad_utilizada > 0),
  primary key (ejecucion_id, insumo_id)
);

create index ejecucion_insumo_insumo on rma.ejecucion_insumo (insumo_id);

create trigger ejecucion_insumo_inmutable before update or delete on rma.ejecucion_insumo
  for each row execute function rma.impedir_modificacion();

comment on table rma.ejecucion_insumo is
  'Lo que el técnico declara como utilizado al cerrar una Ejecución, por insumo. Es la única cantidad que se guarda aquí: lo consumido sale de los CONSUMO del libro y lo usado sin respaldo de stock es la diferencia (vista v_ejecucion_insumo_consumo).';
comment on column rma.ejecucion_insumo.ejecucion_id is 'Ejecución cerrada (referencia a ejecucion).';
comment on column rma.ejecucion_insumo.insumo_id is 'Insumo declarado (referencia a insumo).';
comment on column rma.ejecucion_insumo.cantidad_utilizada is 'Cantidad que el técnico declaró como utilizada, en la unidad del insumo. Sin override no supera lo reservado; con override puede superar lo descontado del inventario.';

-- ---------------------------------------------------------------------------
-- control_tecnico
-- ---------------------------------------------------------------------------
create table rma.control_tecnico (
  id uuid primary key default gen_random_uuid(),
  detalle_id uuid not null references rma.detalle (id),
  ejecucion_id uuid,
  resultado text not null check (resultado in ('APROBADO', 'RECHAZADO')),
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null default now(),
  observaciones text,
  constraint control_ejecucion foreign key (ejecucion_id, detalle_id) references rma.ejecucion (id, detalle_id)
);

create index control_tecnico_detalle on rma.control_tecnico (detalle_id, registrado_en);

create trigger control_tecnico_inmutable before update or delete on rma.control_tecnico
  for each row execute function rma.impedir_modificacion();

comment on table rma.control_tecnico is
  'Cada aprobación o rechazo del control técnico. El control vigente del Detalle es el último; un rechazo reabre el Detalle para retrabajo.';
comment on column rma.control_tecnico.id is 'Identificador interno del control.';
comment on column rma.control_tecnico.detalle_id is 'Detalle controlado (referencia a detalle).';
comment on column rma.control_tecnico.ejecucion_id is 'Ejecución cuyo resultado se controló (referencia a ejecucion); vacía en controles históricos que no la registraron.';
comment on column rma.control_tecnico.resultado is 'APROBADO o RECHAZADO.';
comment on column rma.control_tecnico.usuario_id is 'Usuario que hizo el control (referencia a usuario).';
comment on column rma.control_tecnico.registrado_en is 'Fecha y hora del control.';
comment on column rma.control_tecnico.observaciones is 'Observaciones del control.';
