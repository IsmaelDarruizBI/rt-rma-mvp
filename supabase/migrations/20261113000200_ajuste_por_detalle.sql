-- Ajuste Comercial por Detalle (macroiteración integral, DEC-MI-03; DC09,
-- BR-REP-016).
--
-- Aditiva y compatible con el código anterior:
--   * `descuento.detalle_id` admite vacío: los registros existentes y los
--     que escribe el código anterior son ajustes de la Orden, como siempre;
--   * la vista `v_orden_saldo` conserva sus columnas. Suma los ajustes de
--     cada Detalle no cancelado (sobre su precio) y el de la Orden sobre lo
--     que queda, sin prorratearlo. Sin ajustes de Detalle da lo mismo que
--     antes.

alter table rma.descuento
  add column if not exists detalle_id uuid references rma.detalle (id);

create index if not exists descuento_detalle on rma.descuento (detalle_id)
  where detalle_id is not null;

comment on column rma.descuento.detalle_id is
  'Detalle al que se aplica el ajuste (referencia a detalle); vacío si es de la Orden. El de la Orden se aplica sobre lo que queda después de los de cada Detalle y no se prorratea (DEC-MI-03).';

create or replace view rma.v_orden_saldo as
with trabajos as (
  select d.orden_id, d.id as detalle_id, d.estado, v.precio
  from rma.detalle d
  join rma.v_detalle_version_vigente v on v.detalle_id = d.id
),
ajuste_detalle as (
  select distinct on (detalle_id) detalle_id, tipo, valor
  from rma.descuento
  where detalle_id is not null
  order by detalle_id, posicion desc nulls last, registrado_en desc, id desc
),
por_detalle as (
  select t.orden_id, t.estado, t.precio,
         case
           when t.estado = 'CANCELADO' or a.tipo is null or t.precio <= 0 then 0
           when a.tipo = 'PORCENTAJE' then least(round(t.precio * a.valor / 100, 2), t.precio)
           else least(a.valor, t.precio)
         end as ajuste
  from trabajos t
  left join ajuste_detalle a on a.detalle_id = t.detalle_id
),
resumen as (
  select orden_id,
         count(*) filter (where estado <> 'CANCELADO') as detalles_cobrables,
         coalesce(sum(precio) filter (where estado <> 'CANCELADO'), 0) as subtotal,
         coalesce(sum(ajuste), 0) as ajuste_detalles
  from por_detalle
  group by orden_id
),
descuento_vigente as (
  select distinct on (orden_id) orden_id, tipo, valor
  from rma.descuento
  where detalle_id is null
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
    coalesce(r.subtotal, 0) as subtotal,
    coalesce(r.detalles_cobrables, 0) as detalles_cobrables,
    coalesce(r.ajuste_detalles, 0)
      + case
          when coalesce(r.subtotal, 0) - coalesce(r.ajuste_detalles, 0) <= 0 or dv.tipo is null then 0
          when dv.tipo = 'PORCENTAJE' then least(
            round((r.subtotal - r.ajuste_detalles) * dv.valor / 100, 2),
            r.subtotal - r.ajuste_detalles
          )
          else least(dv.valor, r.subtotal - r.ajuste_detalles)
        end as descuento_aplicado,
    coalesce(c.pagado, 0) as pagado,
    coalesce(x.devuelto, 0) as devuelto
  from rma.orden o
  left join resumen r on r.orden_id = o.id
  left join descuento_vigente dv on dv.orden_id = o.id
  left join cobros c on c.orden_id = o.id
  left join devoluciones x on x.orden_id = o.id
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
