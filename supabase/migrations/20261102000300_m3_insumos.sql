-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 0300. M3 Inventario: insumos y sus saldos. M6: insumos previstos por tipo de reparación.
--
-- Los saldos del insumo (stock_fisico y stock_reservado) solo cambian por los
-- movimientos del libro de inventario: un trigger del libro los actualiza en la
-- misma transacción (migración 0700). Al crear un insumo empiezan en cero; el
-- stock inicial entra como un movimiento INGRESO.

create table rma.insumo (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  nombre text not null check (btrim(nombre) <> ''),
  unidad text,
  stock_fisico numeric(12, 3) not null default 0,
  stock_reservado numeric(12, 3) not null default 0,
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now(),
  constraint insumo_reservado_no_negativo check (stock_reservado >= 0),
  constraint insumo_fisico_cubre_reservado check (stock_fisico >= stock_reservado)
);

create or replace function rma.insumo_saldos_iniciales()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  -- Un insumo nace sin stock: el stock inicial es un movimiento INGRESO.
  new.stock_fisico := 0;
  new.stock_reservado := 0;
  return new;
end;
$$;

comment on function rma.insumo_saldos_iniciales() is
  'Fuerza saldos en cero al crear un insumo, para que todo el stock quede explicado por el libro de inventario.';

create trigger insumo_saldos_iniciales before insert on rma.insumo
  for each row execute function rma.insumo_saldos_iniciales();
create trigger insumo_modificacion before update on rma.insumo
  for each row execute function rma.marcar_modificacion();
create trigger insumo_sin_borrado before delete on rma.insumo
  for each row execute function rma.impedir_borrado();

comment on table rma.insumo is
  'Repuestos y materiales con stock. El disponible (físico menos reservado) nunca es negativo: la base exige que el físico cubra siempre lo reservado (G-2).';
comment on column rma.insumo.id is 'Identificador interno del insumo.';
comment on column rma.insumo.codigo is 'Código legible del insumo (por ejemplo BAT-IP14); el identificador público actual se conserva como código.';
comment on column rma.insumo.nombre is 'Nombre del insumo tal como se muestra.';
comment on column rma.insumo.unidad is 'Unidad de medida en que se expresan las cantidades (por ejemplo «unidad»); vacía si no se informó.';
comment on column rma.insumo.stock_fisico is 'Unidades que existen en el depósito, en la unidad del insumo. Solo cambia por movimientos del libro de inventario y nunca es menor que el reservado.';
comment on column rma.insumo.stock_reservado is 'Cantidad de unidades comprometidas para reparaciones que todavía no fueron consumidas ni liberadas. Solo cambia por movimientos del libro de inventario.';
comment on column rma.insumo.activo is 'Si el insumo puede usarse en movimientos y en insumos previstos nuevos.';
comment on column rma.insumo.creado_en is 'Fecha y hora de alta del insumo.';
comment on column rma.insumo.modificado_en is 'Fecha y hora de la última modificación de la fila, incluidos los cambios de saldo.';

create table rma.tipo_reparacion_insumo (
  tipo_reparacion_id uuid not null references rma.tipo_reparacion (id),
  insumo_id uuid not null references rma.insumo (id),
  cantidad numeric(12, 3) not null check (cantidad > 0),
  primary key (tipo_reparacion_id, insumo_id)
);

create index tipo_reparacion_insumo_insumo on rma.tipo_reparacion_insumo (insumo_id);

comment on table rma.tipo_reparacion_insumo is
  'Insumos y cantidades que reserva cada tipo de reparación al iniciar un Detalle. La reparación «Otros» no tiene insumos previstos.';
comment on column rma.tipo_reparacion_insumo.tipo_reparacion_id is 'Tipo de reparación que prevé el insumo (referencia a tipo_reparacion).';
comment on column rma.tipo_reparacion_insumo.insumo_id is 'Insumo previsto (referencia a insumo).';
comment on column rma.tipo_reparacion_insumo.cantidad is 'Cantidad prevista por cada Detalle de ese tipo, en la unidad del insumo.';
