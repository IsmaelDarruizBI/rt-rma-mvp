-- E4 (A3): pagos, devoluciones de dinero y descuentos del agregado Orden.
--
-- Aditiva: agrega columnas nulas e índices, desempata una vista y corrige un
-- bloqueo. No borra ni reescribe datos: las filas ya guardadas son inmutables
-- (salvo completar la anulación de un pago, como antes) y conservan su orden.
-- Diseño: docs/postgresql/e4-e7-diseno-integrado.md (sección 15).

-- Clave con que quien registra evita duplicar un pago o una devolución ante un
-- reintento (la envía la UI). Como en JSON, se repite como mucho una vez por
-- Orden en cada tabla. Vacía en las filas anteriores y cuando no se envía.
alter table rma.pago add column operacion_id text;
alter table rma.devolucion_dinero add column operacion_id text;

comment on column rma.pago.operacion_id is 'Clave del envío que registró el pago: un reintento con la misma clave no lo duplica. Vacía si no se envió.';
comment on column rma.devolucion_dinero.operacion_id is 'Clave del envío que registró la devolución: un reintento con la misma clave no la duplica. Vacía si no se envió.';

create unique index pago_operacion on rma.pago (orden_id, operacion_id) where operacion_id is not null;
create unique index devolucion_dinero_operacion on rma.devolucion_dinero (orden_id, operacion_id) where operacion_id is not null;

-- Orden exacto de cada lista del dominio, como en A4. Una fecha no alcanza:
-- dos registros pueden compartirla, y en los descuentos el vigente es el
-- último. Las filas anteriores quedan sin posicion y se leen primero.
alter table rma.pago add column posicion integer check (posicion >= 1);
alter table rma.devolucion_dinero add column posicion integer check (posicion >= 1);
alter table rma.descuento add column posicion integer check (posicion >= 1);

comment on column rma.pago.posicion is 'Orden entre los pagos de la Orden (1, 2, ...). Vacía en las filas anteriores a E4, que se leen primero.';
comment on column rma.devolucion_dinero.posicion is 'Orden entre las devoluciones de dinero de la Orden (1, 2, ...). Vacía en las filas anteriores a E4, que se leen primero.';
comment on column rma.descuento.posicion is 'Orden entre los cambios de descuento de la Orden (1, 2, ...); el vigente es el último. Vacía en las filas anteriores a E4, que se leen primero.';

create unique index pago_posicion on rma.pago (orden_id, posicion) where posicion is not null;
create unique index devolucion_dinero_posicion on rma.devolucion_dinero (orden_id, posicion) where posicion is not null;
create unique index descuento_posicion on rma.descuento (orden_id, posicion) where posicion is not null;

-- El descuento vigente es el último registro. Con dos registros en el mismo
-- instante, la fecha no decide: decide la posición, y las filas sin posición
-- (anteriores) quedan antes que las numeradas. Mismas columnas que antes.
create or replace view rma.v_orden_saldo as
with trabajos as (
  select d.orden_id,
         count(*) as detalles,
         count(*) filter (where d.estado <> 'CANCELADO') as detalles_cobrables,
         coalesce(sum(v.precio) filter (where d.estado <> 'CANCELADO'), 0) as subtotal
  from rma.detalle d
  join rma.v_detalle_version_vigente v on v.detalle_id = d.id
  group by d.orden_id
),
descuento_vigente as (
  select distinct on (orden_id) orden_id, tipo, valor
  from rma.descuento
  order by orden_id, posicion desc nulls last, registrado_en desc, id desc
),
cobros as (
  select orden_id, coalesce(sum(monto) filter (where anulado_en is null), 0) as pagado
  from rma.pago group by orden_id
),
devoluciones as (
  select orden_id, coalesce(sum(monto), 0) as devuelto
  from rma.devolucion_dinero group by orden_id
),
calculo as (
  select
    o.id as orden_id,
    coalesce(t.subtotal, 0) as subtotal,
    coalesce(t.detalles_cobrables, 0) as detalles_cobrables,
    case
      when coalesce(t.subtotal, 0) <= 0 or dv.tipo is null then 0
      when dv.tipo = 'PORCENTAJE' then least(round(t.subtotal * dv.valor / 100, 2), t.subtotal)
      else least(dv.valor, t.subtotal)
    end as descuento_aplicado,
    coalesce(c.pagado, 0) as pagado,
    coalesce(r.devuelto, 0) as devuelto
  from rma.orden o
  left join trabajos t on t.orden_id = o.id
  left join descuento_vigente dv on dv.orden_id = o.id
  left join cobros c on c.orden_id = o.id
  left join devoluciones r on r.orden_id = o.id
)
select
  orden_id,
  subtotal,
  descuento_aplicado,
  subtotal - descuento_aplicado as total,
  pagado,
  devuelto,
  subtotal - descuento_aplicado - pagado + devuelto as saldo,
  case
    when subtotal - descuento_aplicado - pagado + devuelto < 0 then 'SALDO_A_FAVOR'
    when detalles_cobrables = 0 then 'PENDIENTE'
    when subtotal - descuento_aplicado - pagado + devuelto = 0 then 'PAGADO'
    when pagado > 0 then 'PARCIAL'
    else 'PENDIENTE'
  end as estado_pago
from calculo;

-- QA-A2-M4, como foto_limite_por_orden en A4. FOR UPDATE choca con el KEY
-- SHARE de las claves foráneas que referencian el pago (devolucion_dinero,
-- evento_negocio). FOR NO KEY UPDATE no choca con KEY SHARE y sigue chocando
-- consigo mismo y con la anulación (un UPDATE sin cambiar la clave): dos
-- devoluciones simultáneas del mismo pago se serializan igual.
create or replace function rma.devolucion_dinero_validar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_pago rma.pago%rowtype;
  v_devuelto numeric(14, 2);
begin
  select * into v_pago from rma.pago where id = new.pago_id for no key update;
  if v_pago.anulado_en is not null then
    raise exception 'No se devuelve dinero desde un pago anulado.' using errcode = 'check_violation';
  end if;
  select coalesce(sum(monto), 0) into v_devuelto from rma.devolucion_dinero where pago_id = new.pago_id;
  if v_devuelto + new.monto > v_pago.monto then
    raise exception 'La devolución supera lo cobrado en el pago % menos lo ya devuelto.', v_pago.codigo
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

comment on function rma.devolucion_dinero_validar() is
  'Impide devolver dinero desde un pago anulado o por encima de lo cobrado en ese pago. Bloquea el pago con FOR NO KEY UPDATE, para no chocar con las claves foráneas. El límite del saldo a favor lo verifica FastAPI con la Orden bloqueada.';
