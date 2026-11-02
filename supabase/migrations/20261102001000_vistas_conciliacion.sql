-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 1000. Vistas de valores calculados y verificaciones de integridad.
--
-- Lo calculado no se guarda: versión vigente, pendiente de reservas, consumo
-- frente a lo declarado, total y saldo. rma.verificar_integridad() devuelve las
-- diferencias entre los saldos guardados y el libro, y otras invariantes; vacía
-- significa que todo concilia.

create view rma.v_detalle_version_vigente as
select distinct on (v.detalle_id)
  v.detalle_id,
  v.id as detalle_version_id,
  v.numero,
  v.tipo_reparacion_id,
  v.descripcion,
  v.precio,
  v.puntaje,
  v.garantia_dias
from rma.detalle_version v
order by v.detalle_id, v.numero desc;

comment on view rma.v_detalle_version_vigente is
  'Versión de definición vigente de cada Detalle: la de mayor número (ABI-16).';
comment on column rma.v_detalle_version_vigente.detalle_id is 'Detalle (referencia a detalle).';
comment on column rma.v_detalle_version_vigente.detalle_version_id is 'Versión vigente (referencia a detalle_version).';
comment on column rma.v_detalle_version_vigente.numero is 'Número de la versión vigente.';
comment on column rma.v_detalle_version_vigente.tipo_reparacion_id is 'Tipo de reparación de la versión vigente (referencia a tipo_reparacion).';
comment on column rma.v_detalle_version_vigente.descripcion is 'Descripción de la reparación «Otros», si corresponde.';
comment on column rma.v_detalle_version_vigente.precio is 'Precio en pesos de la versión vigente.';
comment on column rma.v_detalle_version_vigente.puntaje is 'Puntaje de la versión vigente.';
comment on column rma.v_detalle_version_vigente.garantia_dias is 'Garantía de catálogo en días de la versión vigente.';

create view rma.v_reserva_pendiente as
select
  r.id as reserva_id,
  r.insumo_id,
  r.orden_id,
  r.detalle_id,
  r.cantidad as reservado,
  coalesce(sum(c.cantidad), 0) as cerrado,
  r.cantidad - coalesce(sum(c.cantidad), 0) as pendiente
from rma.movimiento_inventario r
left join rma.movimiento_inventario c
  on c.movimiento_origen_id = r.id
 and c.tipo in ('CONSUMO', 'LIBERACION_RESERVA', 'DESPERDICIO')
where r.tipo = 'RESERVA'
group by r.id;

comment on view rma.v_reserva_pendiente is
  'Cada RESERVA con lo que ya la cerró (consumos, liberaciones y desperdicios) y lo que queda pendiente, calculado desde el libro.';
comment on column rma.v_reserva_pendiente.reserva_id is 'Movimiento RESERVA (referencia a movimiento_inventario).';
comment on column rma.v_reserva_pendiente.insumo_id is 'Insumo reservado (referencia a insumo).';
comment on column rma.v_reserva_pendiente.orden_id is 'Orden de la reserva (referencia a orden).';
comment on column rma.v_reserva_pendiente.detalle_id is 'Detalle de la reserva (referencia a detalle).';
comment on column rma.v_reserva_pendiente.reservado is 'Cantidad reservada originalmente.';
comment on column rma.v_reserva_pendiente.cerrado is 'Cantidad ya consumida, liberada o desperdiciada desde esa reserva.';
comment on column rma.v_reserva_pendiente.pendiente is 'Cantidad todavía comprometida: reservado menos cerrado.';

create view rma.v_ejecucion_insumo_consumo as
with consumido as (
  select ejecucion_id, insumo_id, sum(cantidad) as cantidad
  from rma.movimiento_inventario
  where tipo = 'CONSUMO'
  group by ejecucion_id, insumo_id
)
select
  coalesce(d.ejecucion_id, c.ejecucion_id) as ejecucion_id,
  coalesce(d.insumo_id, c.insumo_id) as insumo_id,
  coalesce(d.cantidad_utilizada, 0) as utilizada_declarada,
  coalesce(c.cantidad, 0) as consumida,
  greatest(coalesce(d.cantidad_utilizada, 0) - coalesce(c.cantidad, 0), 0) as sin_respaldo
from rma.ejecucion_insumo d
full join consumido c on c.ejecucion_id = d.ejecucion_id and c.insumo_id = d.insumo_id;

comment on view rma.v_ejecucion_insumo_consumo is
  'Por Ejecución e insumo: lo declarado (ejecucion_insumo), lo efectivamente consumido (CONSUMO del libro) y lo usado sin respaldo de stock, que solo puede ser mayor que cero con override.';
comment on column rma.v_ejecucion_insumo_consumo.ejecucion_id is 'Ejecución (referencia a ejecucion).';
comment on column rma.v_ejecucion_insumo_consumo.insumo_id is 'Insumo (referencia a insumo).';
comment on column rma.v_ejecucion_insumo_consumo.utilizada_declarada is 'Cantidad que declaró el técnico.';
comment on column rma.v_ejecucion_insumo_consumo.consumida is 'Cantidad descontada del inventario: suma de los CONSUMO de esa Ejecución e insumo.';
comment on column rma.v_ejecucion_insumo_consumo.sin_respaldo is 'Declarada menos consumida: lo usado sin respaldo de stock, que no genera movimiento ni deuda futura.';

create view rma.v_orden_saldo as
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
  order by orden_id, registrado_en desc, id desc
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

comment on view rma.v_orden_saldo is
  'Situación comercial calculada de cada Orden, con las mismas reglas que el MVP: saldo = total − pagado vigente + devuelto (BR-REP-038). Nada de esto se guarda.';
comment on column rma.v_orden_saldo.orden_id is 'Orden (referencia a orden).';
comment on column rma.v_orden_saldo.subtotal is 'Suma de los precios de la versión vigente de los Detalles no cancelados, en pesos.';
comment on column rma.v_orden_saldo.descuento_aplicado is 'Lo que descuenta el descuento vigente sobre el subtotal, redondeado al centavo y nunca mayor que el subtotal.';
comment on column rma.v_orden_saldo.total is 'Total cobrable: subtotal menos descuento aplicado.';
comment on column rma.v_orden_saldo.pagado is 'Suma de los pagos no anulados.';
comment on column rma.v_orden_saldo.devuelto is 'Suma de las devoluciones de dinero.';
comment on column rma.v_orden_saldo.saldo is 'Positivo: el cliente debe; cero: sin diferencias; negativo: saldo a favor del cliente pendiente de devolver.';
comment on column rma.v_orden_saldo.estado_pago is 'PENDIENTE, PARCIAL, PAGADO o SALDO_A_FAVOR, derivado del saldo y de lo pagado.';

create view rma.v_conciliacion_inventario as
with libro as (
  select
    insumo_id,
    sum(case
          when tipo in ('INGRESO', 'AJUSTE_POSITIVO', 'DEVOLUCION') then cantidad
          when tipo in ('CONSUMO', 'DESPERDICIO', 'AJUSTE_NEGATIVO') then -cantidad
          else 0
        end) as fisico,
    sum(case
          when tipo = 'RESERVA' then cantidad
          when tipo in ('CONSUMO', 'LIBERACION_RESERVA', 'DESPERDICIO') then -cantidad
          else 0
        end) as reservado
  from rma.movimiento_inventario
  group by insumo_id
)
select
  i.id as insumo_id,
  i.codigo,
  i.stock_fisico,
  coalesce(l.fisico, 0) as stock_fisico_libro,
  i.stock_reservado,
  coalesce(l.reservado, 0) as stock_reservado_libro,
  i.stock_fisico = coalesce(l.fisico, 0) and i.stock_reservado = coalesce(l.reservado, 0) as concilia
from rma.insumo i
left join libro l on l.insumo_id = i.id;

comment on view rma.v_conciliacion_inventario is
  'Compara, por insumo, los saldos guardados con los que resultan de sumar el libro de movimientos.';
comment on column rma.v_conciliacion_inventario.insumo_id is 'Insumo (referencia a insumo).';
comment on column rma.v_conciliacion_inventario.codigo is 'Código del insumo.';
comment on column rma.v_conciliacion_inventario.stock_fisico is 'Stock físico guardado en el insumo.';
comment on column rma.v_conciliacion_inventario.stock_fisico_libro is 'Stock físico según el libro: ingresos, ajustes positivos y devoluciones menos consumos, desperdicios y ajustes negativos.';
comment on column rma.v_conciliacion_inventario.stock_reservado is 'Stock reservado guardado en el insumo.';
comment on column rma.v_conciliacion_inventario.stock_reservado_libro is 'Stock reservado según el libro: reservas menos lo que las cerró.';
comment on column rma.v_conciliacion_inventario.concilia is 'Verdadero si los dos saldos guardados coinciden con el libro.';

create or replace function rma.verificar_integridad()
returns table (verificacion text, referencia text, detalle text)
language sql
stable
set search_path = rma, pg_temp
as $$
  select 'CONCILIACION_INVENTARIO', c.codigo,
         format('físico %s (libro %s), reservado %s (libro %s)',
                c.stock_fisico, c.stock_fisico_libro, c.stock_reservado, c.stock_reservado_libro)
  from rma.v_conciliacion_inventario c
  where not c.concilia
  union all
  select 'CONSUMO_SUPERA_DECLARADO', x.codigo,
         format('insumo %s: declarado %s, consumido %s', i.codigo, v.utilizada_declarada, v.consumida)
  from rma.v_ejecucion_insumo_consumo v
  join rma.ejecucion x on x.id = v.ejecucion_id
  join rma.insumo i on i.id = v.insumo_id
  where v.consumida > v.utilizada_declarada
  union all
  select 'DETALLE_SIN_VERSION', o.codigo || '/' || d.codigo, 'el Detalle no tiene versión de definición'
  from rma.detalle d
  join rma.orden o on o.id = d.orden_id
  where not exists (select 1 from rma.detalle_version v where v.detalle_id = d.id)
  union all
  select 'SECUENCIA_EVENTOS', o.codigo,
         format('contador %s, eventos %s, máxima secuencia %s',
                o.ultima_secuencia_evento, count(e.id), coalesce(max(e.secuencia), 0))
  from rma.orden o
  left join rma.evento_negocio e on e.orden_id = o.id
  group by o.id
  having count(e.id) <> o.ultima_secuencia_evento or coalesce(max(e.secuencia), 0) <> o.ultima_secuencia_evento
  union all
  select 'RESERVA_SOBRECERRADA', r.reserva_id::text, format('pendiente %s', r.pendiente)
  from rma.v_reserva_pendiente r
  where r.pendiente < 0;
$$;

comment on function rma.verificar_integridad() is
  'Devuelve una fila por cada invariante violada: conciliación del inventario con el libro, consumo mayor que lo declarado, Detalles sin versión, secuencia de eventos con huecos y reservas cerradas de más. Vacía si todo concilia.';
