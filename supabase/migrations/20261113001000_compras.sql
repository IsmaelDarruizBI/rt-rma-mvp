-- Compras: proveedores, solicitudes, órdenes de compra y recepciones
-- (macroiteración integral, DEC-MI-09; cierra ABI-12). Proceso propio, fuera
-- de PROC-REP (DC24).
--
-- Aditiva. El ingreso de stock de cada recepción es un INGRESO del libro de
-- inventario (con su lote o serie, DEC-MI-10); acá queda la trazabilidad de
-- la compra: quién crea y quién confirma, proveedor, cantidades, costos
-- acordados y reales, recepciones parciales y diferencias. Sin pagos a
-- proveedores ni integración contable.

create table if not exists rma.proveedor (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (codigo ~ '^PRV-[0-9A-Z-]+$'),
  nombre text not null check (btrim(nombre) <> ''),
  cuit text,
  telefono text,
  email text,
  contacto text,
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

drop trigger if exists proveedor_sin_borrado on rma.proveedor;
create trigger proveedor_sin_borrado before delete on rma.proveedor
  for each row execute function rma.impedir_borrado();

comment on table rma.proveedor is 'Proveedores con datos básicos (DEC-MI-09). Los administra Administración, con auditoría (entidad PROVEEDOR). No se borran: se desactivan.';
comment on column rma.proveedor.id is 'Identificador interno del proveedor.';
comment on column rma.proveedor.codigo is 'Código público del proveedor (PRV-...).';
comment on column rma.proveedor.nombre is 'Nombre o razón social.';
comment on column rma.proveedor.cuit is 'CUIT, si se informó.';
comment on column rma.proveedor.telefono is 'Teléfono de contacto.';
comment on column rma.proveedor.email is 'Correo de contacto.';
comment on column rma.proveedor.contacto is 'Persona de contacto.';
comment on column rma.proveedor.activo is 'Si se le pueden hacer órdenes de compra nuevas.';
comment on column rma.proveedor.creado_en is 'Fecha y hora de alta.';
comment on column rma.proveedor.modificado_en is 'Fecha y hora del último cambio.';

create table if not exists rma.orden_compra (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (codigo ~ '^OC-[0-9]{6,}$'),
  proveedor_id uuid not null references rma.proveedor (id),
  creada_por uuid not null references rma.usuario (id),
  creada_en timestamptz not null,
  confirmada_por uuid references rma.usuario (id),
  confirmada_en timestamptz,
  cancelada_por uuid references rma.usuario (id),
  cancelada_en timestamptz,
  motivo_cancelacion text,
  observaciones text,
  constraint orden_compra_confirmacion check ((confirmada_por is null) = (confirmada_en is null)),
  constraint orden_compra_cancelacion check (
    (cancelada_por is null) = (cancelada_en is null)
    and (cancelada_en is null or btrim(coalesce(motivo_cancelacion, '')) <> ''))
);

comment on table rma.orden_compra is 'Órdenes de compra (DEC-MI-09): las crean y confirman Recepción, Coordinación RMA o Administración, sin aprobación. Estado: borrador, confirmada, parcial o recibida (por sus recepciones) o cancelada.';
comment on column rma.orden_compra.id is 'Identificador interno.';
comment on column rma.orden_compra.codigo is 'Código público (OC-000001).';
comment on column rma.orden_compra.proveedor_id is 'Proveedor (referencia a proveedor).';
comment on column rma.orden_compra.creada_por is 'Quién la creó (referencia a usuario).';
comment on column rma.orden_compra.creada_en is 'Fecha y hora de creación.';
comment on column rma.orden_compra.confirmada_por is 'Quién la confirmó (referencia a usuario).';
comment on column rma.orden_compra.confirmada_en is 'Fecha y hora de confirmación.';
comment on column rma.orden_compra.cancelada_por is 'Quién la canceló (referencia a usuario); solo sin recepciones.';
comment on column rma.orden_compra.cancelada_en is 'Fecha y hora de la cancelación.';
comment on column rma.orden_compra.motivo_cancelacion is 'Por qué se canceló.';
comment on column rma.orden_compra.observaciones is 'Observaciones de la orden.';

-- Una orden confirmada o cancelada no vuelve atrás ni cambia sus datos.
create or replace function rma.orden_compra_transicion()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Una orden de compra no se borra.' using errcode = 'restrict_violation';
  end if;
  if old.cancelada_en is not null
     or (old.confirmada_en is not null and new.confirmada_en is distinct from old.confirmada_en)
     or new.codigo <> old.codigo or new.proveedor_id <> old.proveedor_id
     or new.creada_por <> old.creada_por or new.creada_en <> old.creada_en then
    raise exception 'La orden de compra % solo admite confirmarse o cancelarse una vez.', old.codigo
      using errcode = 'restrict_violation';
  end if;
  if new.cancelada_en is not null and exists (
    select 1 from rma.recepcion_compra where orden_compra_id = old.id
  ) then
    raise exception 'La orden de compra % tiene recepciones: no se cancela.', old.codigo
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

create table if not exists rma.orden_compra_item (
  orden_compra_id uuid not null references rma.orden_compra (id),
  insumo_id uuid not null references rma.insumo (id),
  cantidad numeric(12, 3) not null check (cantidad > 0),
  costo_unitario numeric(12, 2) not null check (costo_unitario >= 0),
  posicion integer not null check (posicion >= 1),
  primary key (orden_compra_id, insumo_id),
  constraint orden_compra_item_posicion unique (orden_compra_id, posicion)
);

drop trigger if exists orden_compra_item_inmutable on rma.orden_compra_item;
create trigger orden_compra_item_inmutable before update or delete on rma.orden_compra_item
  for each row execute function rma.impedir_modificacion();

comment on table rma.orden_compra_item is 'Insumos de una orden de compra con la cantidad y el costo acordados. Inmutables.';
comment on column rma.orden_compra_item.orden_compra_id is 'Orden de compra (referencia a orden_compra).';
comment on column rma.orden_compra_item.insumo_id is 'Insumo pedido (referencia a insumo).';
comment on column rma.orden_compra_item.cantidad is 'Cantidad pedida.';
comment on column rma.orden_compra_item.costo_unitario is 'Costo unitario acordado.';
comment on column rma.orden_compra_item.posicion is 'Orden del insumo en la orden de compra.';

create table if not exists rma.solicitud_compra (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (codigo ~ '^SC-[0-9]{6,}$'),
  insumo_id uuid not null references rma.insumo (id),
  cantidad numeric(12, 3) not null check (cantidad > 0),
  origen text not null check (origen in ('MANUAL', 'FALTANTE')),
  motivo text not null check (btrim(motivo) <> ''),
  ordenes text[] not null default '{}',
  usuario_id uuid not null references rma.usuario (id),
  registrada_en timestamptz not null,
  estado text not null default 'PENDIENTE' check (estado in ('PENDIENTE', 'EN_ORDEN', 'DESCARTADA')),
  orden_compra_id uuid references rma.orden_compra (id),
  descartada_por uuid references rma.usuario (id),
  descartada_en timestamptz,
  motivo_descarte text,
  constraint solicitud_compra_estado check (
    (estado = 'PENDIENTE' and orden_compra_id is null and descartada_en is null)
    or (estado = 'EN_ORDEN' and orden_compra_id is not null and descartada_en is null)
    or (estado = 'DESCARTADA' and descartada_en is not null and descartada_por is not null
        and btrim(coalesce(motivo_descarte, '')) <> ''))
);

comment on table rma.solicitud_compra is 'Solicitudes de compra (DEC-MI-09): manuales o sugeridas por un faltante y confirmadas por un usuario; nunca automáticas.';
comment on column rma.solicitud_compra.id is 'Identificador interno.';
comment on column rma.solicitud_compra.codigo is 'Código público (SC-000001).';
comment on column rma.solicitud_compra.insumo_id is 'Insumo solicitado (referencia a insumo).';
comment on column rma.solicitud_compra.cantidad is 'Cantidad solicitada.';
comment on column rma.solicitud_compra.origen is 'MANUAL o FALTANTE (sugerida por las Órdenes que esperan recursos).';
comment on column rma.solicitud_compra.motivo is 'Por qué se pide.';
comment on column rma.solicitud_compra.ordenes is 'Órdenes con el faltante que la originó (códigos), si corresponde.';
comment on column rma.solicitud_compra.usuario_id is 'Quién la registró (referencia a usuario).';
comment on column rma.solicitud_compra.registrada_en is 'Fecha y hora del registro.';
comment on column rma.solicitud_compra.estado is 'PENDIENTE, EN_ORDEN (incluida en una orden de compra) o DESCARTADA.';
comment on column rma.solicitud_compra.orden_compra_id is 'Orden de compra que la incluye (referencia a orden_compra).';
comment on column rma.solicitud_compra.descartada_por is 'Quién la descartó (referencia a usuario).';
comment on column rma.solicitud_compra.descartada_en is 'Fecha y hora del descarte.';
comment on column rma.solicitud_compra.motivo_descarte is 'Por qué se descartó.';

create or replace function rma.solicitud_compra_transicion()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Una solicitud de compra no se borra.' using errcode = 'restrict_violation';
  end if;
  if old.estado = 'DESCARTADA'
     or (old.estado = 'EN_ORDEN' and not (new.estado = 'PENDIENTE' and new.orden_compra_id is null))
     or new.codigo <> old.codigo or new.insumo_id <> old.insumo_id
     or new.cantidad <> old.cantidad or new.usuario_id <> old.usuario_id then
    raise exception 'La solicitud % no admite ese cambio.', old.codigo using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

drop trigger if exists solicitud_compra_transicion on rma.solicitud_compra;
create trigger solicitud_compra_transicion before update or delete on rma.solicitud_compra
  for each row execute function rma.solicitud_compra_transicion();

drop trigger if exists orden_compra_transicion on rma.orden_compra;

create table if not exists rma.recepcion_compra (
  id uuid primary key default gen_random_uuid(),
  orden_compra_id uuid not null references rma.orden_compra (id),
  codigo text not null check (codigo ~ '^REC-[0-9]{2,}$'),
  usuario_id uuid not null references rma.usuario (id),
  registrada_en timestamptz not null,
  remito text,
  observaciones text,
  constraint recepcion_compra_codigo unique (orden_compra_id, codigo)
);

create unique index if not exists recepcion_compra_remito
  on rma.recepcion_compra (orden_compra_id, lower(remito)) where remito is not null;

create trigger orden_compra_transicion before update or delete on rma.orden_compra
  for each row execute function rma.orden_compra_transicion();

drop trigger if exists recepcion_compra_inmutable on rma.recepcion_compra;
create trigger recepcion_compra_inmutable before update or delete on rma.recepcion_compra
  for each row execute function rma.impedir_modificacion();

comment on table rma.recepcion_compra is 'Recepciones de una orden de compra (DEC-MI-09): varias parciales, sin repetir remito. Inmutables.';
comment on column rma.recepcion_compra.id is 'Identificador interno.';
comment on column rma.recepcion_compra.orden_compra_id is 'Orden de compra recibida (referencia a orden_compra).';
comment on column rma.recepcion_compra.codigo is 'Código de la recepción dentro de la orden (REC-01...).';
comment on column rma.recepcion_compra.usuario_id is 'Quién recibió (referencia a usuario).';
comment on column rma.recepcion_compra.registrada_en is 'Fecha y hora de la recepción.';
comment on column rma.recepcion_compra.remito is 'Remito del proveedor, si lo hay; no se repite en la misma orden.';
comment on column rma.recepcion_compra.observaciones is 'Observaciones de la recepción.';

create table if not exists rma.recepcion_compra_linea (
  recepcion_id uuid not null references rma.recepcion_compra (id),
  posicion integer not null check (posicion >= 1),
  insumo_id uuid not null references rma.insumo (id),
  cantidad numeric(12, 3) not null check (cantidad > 0),
  costo_unitario numeric(12, 2) not null check (costo_unitario >= 0),
  lote text,
  series text[] not null default '{}',
  movimientos text[] not null default '{}',
  diferencia text,
  primary key (recepcion_id, posicion)
);

create index if not exists recepcion_compra_linea_insumo on rma.recepcion_compra_linea (insumo_id);

-- Nunca se recibe más de lo pedido, aun con dos recepciones a la vez: se
-- bloquea la orden de compra antes de sumar.
create or replace function rma.recepcion_compra_linea_pendiente()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_orden uuid;
  v_pedido numeric(12, 3);
  v_recibido numeric(12, 3);
begin
  select orden_compra_id into v_orden from rma.recepcion_compra where id = new.recepcion_id;
  perform 1 from rma.orden_compra where id = v_orden for update;
  select cantidad into v_pedido from rma.orden_compra_item
   where orden_compra_id = v_orden and insumo_id = new.insumo_id;
  if v_pedido is null then
    raise exception 'El insumo no está en la orden de compra.' using errcode = 'check_violation';
  end if;
  select coalesce(sum(l.cantidad), 0) into v_recibido
    from rma.recepcion_compra_linea l
    join rma.recepcion_compra r on r.id = l.recepcion_id
   where r.orden_compra_id = v_orden and l.insumo_id = new.insumo_id;
  if v_recibido + new.cantidad > v_pedido then
    raise exception 'Se recibiría % de % pedidos.', v_recibido + new.cantidad, v_pedido
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

drop trigger if exists recepcion_compra_linea_pendiente on rma.recepcion_compra_linea;
create trigger recepcion_compra_linea_pendiente before insert on rma.recepcion_compra_linea
  for each row execute function rma.recepcion_compra_linea_pendiente();
drop trigger if exists recepcion_compra_linea_inmutable on rma.recepcion_compra_linea;
create trigger recepcion_compra_linea_inmutable before update or delete on rma.recepcion_compra_linea
  for each row execute function rma.impedir_modificacion();

comment on table rma.recepcion_compra_linea is 'Líneas de una recepción: cantidad, costo real (histórico), lote o series y los ingresos de stock que generó. Inmutables.';
comment on column rma.recepcion_compra_linea.recepcion_id is 'Recepción (referencia a recepcion_compra).';
comment on column rma.recepcion_compra_linea.posicion is 'Orden de la línea.';
comment on column rma.recepcion_compra_linea.insumo_id is 'Insumo recibido (referencia a insumo).';
comment on column rma.recepcion_compra_linea.cantidad is 'Cantidad recibida.';
comment on column rma.recepcion_compra_linea.costo_unitario is 'Costo unitario real que registró quien recibió.';
comment on column rma.recepcion_compra_linea.lote is 'Número de lote, si el insumo se controla por lote.';
comment on column rma.recepcion_compra_linea.series is 'Números de serie, si el insumo se controla por serie.';
comment on column rma.recepcion_compra_linea.movimientos is 'Códigos de los ingresos de stock que generó.';
comment on column rma.recepcion_compra_linea.diferencia is 'Diferencia registrada (por ejemplo, costo real distinto del acordado).';

grant select, insert, update on rma.proveedor to rma_backend;
grant select, insert on rma.orden_compra to rma_backend;
grant update (confirmada_por, confirmada_en, cancelada_por, cancelada_en, motivo_cancelacion)
  on rma.orden_compra to rma_backend;
grant select, insert on rma.orden_compra_item to rma_backend;
grant select, insert on rma.solicitud_compra to rma_backend;
grant update (estado, orden_compra_id, descartada_por, descartada_en, motivo_descarte)
  on rma.solicitud_compra to rma_backend;
grant select, insert on rma.recepcion_compra to rma_backend;
grant select, insert on rma.recepcion_compra_linea to rma_backend;
