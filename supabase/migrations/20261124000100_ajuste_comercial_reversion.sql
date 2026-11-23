-- Rosario Tecno RMA — Ajuste Comercial: corrección, reversión y evidencia
-- (ajustes funcionales, iteración 2, bloque 5; DEC-AJ-10, BR-REP-016).
--
-- Aditiva y compatible con los registros existentes:
--   * `descuento` suma columnas opcionales: el código estable del registro,
--     la evidencia de sus importes (precio original, importe aplicado y
--     precio final), el registro que corrige y la reversión (quién, cuándo y
--     por qué). Las filas anteriores quedan sin evidencia y sin revertir;
--   * el registro sigue siendo inmutable, salvo completar su reversión una
--     única vez y con la Orden abierta (como la anulación de un pago);
--   * tabla nueva `descuento_recalculo`: evidencia inmutable de cada
--     recálculo de un ajuste vigente por una redefinición o una cancelación;
--   * la vista `v_orden_saldo` conserva sus columnas y excluye los registros
--     revertidos: por destino rige el último no revertido. Sin reversiones da
--     lo mismo que antes;
--   * el historial de la Orden registra cada alta, cambio, retiro,
--     corrección, reversión y recálculo como EV-REP-041.

-- ---------------------------------------------------------------------------
-- descuento: código, evidencia, corrección y reversión
-- ---------------------------------------------------------------------------
alter table rma.descuento
  add column if not exists codigo text,
  add column if not exists precio_original numeric(14, 2),
  add column if not exists importe_aplicado numeric(14, 2),
  add column if not exists precio_final numeric(14, 2),
  add column if not exists corrige_a uuid references rma.descuento (id),
  add column if not exists revertido_por uuid references rma.usuario (id),
  add column if not exists revertido_en timestamptz,
  add column if not exists reversion_motivo text;

alter table rma.descuento
  add constraint descuento_reversion_completa check (
    (revertido_en is null and revertido_por is null and reversion_motivo is null)
    or (revertido_en is not null and revertido_por is not null
        and reversion_motivo is not null and btrim(reversion_motivo) <> '')
  ),
  add constraint descuento_evidencia_completa check (
    (precio_original is null and importe_aplicado is null and precio_final is null)
    or (precio_original >= 0 and importe_aplicado >= 0
        and importe_aplicado <= precio_original
        and precio_final = precio_original - importe_aplicado)
  ),
  add constraint descuento_no_se_corrige_a_si_mismo check (corrige_a is distinct from id),
  add constraint descuento_id_orden unique (id, orden_id);

create unique index if not exists descuento_codigo on rma.descuento (orden_id, codigo)
  where codigo is not null;
-- Un registro revertido se corrige una sola vez.
create unique index if not exists descuento_corrige_a on rma.descuento (corrige_a)
  where corrige_a is not null;

comment on table rma.descuento is
  'Cada registro del Ajuste Comercial (DESCUENTO o CORTESIA) de una Orden o de un Detalle: aplicarlo, cambiarlo o quitarlo. Por destino rige el último registro no revertido, salvo que quite el ajuste. No cambia precios. Si deja el total por debajo de lo cobrado, queda saldo a favor del cliente, que se devuelve antes de entregar (DEC-MI-03). Solo admite completar su reversión una vez (DEC-AJ-10).';
comment on column rma.descuento.codigo is 'Identificador estable del registro en la aplicación; vacío en los registros anteriores a DEC-AJ-10, que se identifican por su id.';
comment on column rma.descuento.precio_original is 'Evidencia (DEC-AJ-10): la base a la que se aplicó al registrarlo (el precio del Detalle o lo que quedaba de la Orden). Vacía en los registros anteriores.';
comment on column rma.descuento.importe_aplicado is 'Evidencia (DEC-AJ-10): lo que descontaba al registrarlo. Vacía en los registros anteriores.';
comment on column rma.descuento.precio_final is 'Evidencia (DEC-AJ-10): precio original menos importe aplicado. Vacía en los registros anteriores.';
comment on column rma.descuento.corrige_a is 'Registro revertido que este corrige (referencia a descuento); vacío si no es una corrección.';
comment on column rma.descuento.revertido_por is 'Usuario que revirtió el registro (referencia a usuario); vacío si no se revirtió.';
comment on column rma.descuento.revertido_en is 'Fecha y hora de la reversión; un registro revertido deja de contar y vuelve a regir el anterior de su destino.';
comment on column rma.descuento.reversion_motivo is 'Motivo de la reversión.';

-- El registro es inmutable: solo se completa su reversión, una vez, con la
-- Orden abierta (DEC-AJ-10, D-10.3). Reemplaza a descuento_inmutable.
create or replace function rma.descuento_validar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_cerrada timestamptz;
begin
  if tg_op = 'DELETE' then
    raise exception 'Un ajuste comercial nunca se borra: se revierte.' using errcode = 'restrict_violation';
  end if;
  if old.revertido_en is not null
     or new.revertido_en is null
     or row(new.orden_id, new.tipo, new.valor, new.motivo, new.usuario_id, new.registrado_en,
            new.posicion, new.clase, new.detalle_id, new.codigo, new.precio_original,
            new.importe_aplicado, new.precio_final, new.corrige_a)
        is distinct from
        row(old.orden_id, old.tipo, old.valor, old.motivo, old.usuario_id, old.registrado_en,
            old.posicion, old.clase, old.detalle_id, old.codigo, old.precio_original,
            old.importe_aplicado, old.precio_final, old.corrige_a) then
    raise exception 'Un ajuste comercial solo admite registrar su reversión, una única vez.'
      using errcode = 'restrict_violation';
  end if;
  select cerrada_en into v_cerrada from rma.orden where id = new.orden_id for share;
  if v_cerrada is not null then
    raise exception 'La Orden está cerrada: el ajuste comercial ya no se revierte.'
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

comment on function rma.descuento_validar() is
  'Impide borrar un ajuste comercial y solo permite completar su reversión una única vez, con la Orden abierta (DEC-AJ-10).';

drop trigger if exists descuento_inmutable on rma.descuento;
create trigger descuento_validar before update or delete on rma.descuento
  for each row execute function rma.descuento_validar();

-- Una corrección apunta a un registro revertido de la misma Orden y del
-- mismo destino.
create or replace function rma.descuento_correccion_valida()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_corregido rma.descuento;
begin
  if new.corrige_a is null then
    return new;
  end if;
  select * into v_corregido from rma.descuento where id = new.corrige_a;
  if v_corregido.orden_id is distinct from new.orden_id
     or v_corregido.detalle_id is distinct from new.detalle_id
     or v_corregido.revertido_en is null then
    raise exception 'Una corrección apunta a un ajuste revertido de la misma Orden y del mismo destino.'
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

comment on function rma.descuento_correccion_valida() is
  'Exige que la corrección de un ajuste comercial apunte a un registro revertido de la misma Orden y del mismo destino (DEC-AJ-10).';

create trigger descuento_correccion_valida before insert on rma.descuento
  for each row execute function rma.descuento_correccion_valida();

grant update (revertido_por, revertido_en, reversion_motivo) on rma.descuento to rma_backend;

-- ---------------------------------------------------------------------------
-- descuento_recalculo
-- ---------------------------------------------------------------------------
create table rma.descuento_recalculo (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null references rma.orden (id),
  descuento_id uuid not null,
  causa text not null check (causa in ('REDEFINICION', 'CANCELACION')),
  detalle_id uuid references rma.detalle (id),
  precio_anterior numeric(14, 2) not null check (precio_anterior >= 0),
  precio_nuevo numeric(14, 2) not null check (precio_nuevo >= 0),
  importe_anterior numeric(14, 2) not null check (importe_anterior >= 0),
  importe_nuevo numeric(14, 2) not null check (importe_nuevo >= 0),
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null default now(),
  posicion integer not null check (posicion >= 1),
  constraint descuento_recalculo_ajuste foreign key (descuento_id, orden_id)
    references rma.descuento (id, orden_id),
  constraint descuento_recalculo_cambia check (importe_anterior <> importe_nuevo),
  unique (orden_id, posicion)
);

create index descuento_recalculo_descuento on rma.descuento_recalculo (descuento_id);

create trigger descuento_recalculo_inmutable before update or delete on rma.descuento_recalculo
  for each row execute function rma.impedir_modificacion();
create trigger descuento_recalculo_orden_abierta before insert on rma.descuento_recalculo
  for each row execute function rma.exigir_orden_abierta();

comment on table rma.descuento_recalculo is
  'Evidencia inmutable de cada recálculo de un ajuste comercial vigente: una redefinición o una cancelación cambió la base a la que se aplica y con ella su importe efectivo. No es un ajuste nuevo (DEC-AJ-10, D-10.4).';
comment on column rma.descuento_recalculo.id is 'Identificador interno del recálculo.';
comment on column rma.descuento_recalculo.orden_id is 'Orden del ajuste (referencia a orden).';
comment on column rma.descuento_recalculo.descuento_id is 'Ajuste comercial recalculado (referencia a descuento de la misma Orden).';
comment on column rma.descuento_recalculo.causa is 'REDEFINICION o CANCELACION del trabajo.';
comment on column rma.descuento_recalculo.detalle_id is 'Detalle del ajuste (referencia a detalle); vacío si el ajuste es de la Orden.';
comment on column rma.descuento_recalculo.precio_anterior is 'Base a la que se aplicaba el ajuste antes del cambio.';
comment on column rma.descuento_recalculo.precio_nuevo is 'Base a la que se aplica después del cambio (0 si el trabajo se canceló).';
comment on column rma.descuento_recalculo.importe_anterior is 'Lo que descontaba el ajuste antes del cambio.';
comment on column rma.descuento_recalculo.importe_nuevo is 'Lo que descuenta después del cambio.';
comment on column rma.descuento_recalculo.usuario_id is 'Usuario que redefinió o canceló (referencia a usuario).';
comment on column rma.descuento_recalculo.registrado_en is 'Fecha y hora del recálculo.';
comment on column rma.descuento_recalculo.posicion is 'Orden entre los recálculos de la Orden (1, 2, ...).';

grant select, insert on rma.descuento_recalculo to rma_backend;

-- ---------------------------------------------------------------------------
-- v_orden_saldo: los registros revertidos no cuentan
-- ---------------------------------------------------------------------------
create or replace view rma.v_orden_saldo as
with trabajos as (
  select d.orden_id, d.id as detalle_id, d.estado, v.precio
  from rma.detalle d
  join rma.v_detalle_version_vigente v on v.detalle_id = d.id
),
ajuste_detalle as (
  select distinct on (detalle_id) detalle_id, tipo, valor
  from rma.descuento
  where detalle_id is not null and revertido_en is null
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
  where detalle_id is null and revertido_en is null
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

-- ---------------------------------------------------------------------------
-- Historial: EV-REP-041 para la acción del ajuste comercial (ACC-REP-072)
-- ---------------------------------------------------------------------------
insert into rma.equivalencia_historial (tipo_referencia, referencia_id, accion, tipo_evento_id)
select 'FUNCTIONAL_ACTION', 'ACC-REP-072', null, t.id
from rma.tipo_evento t
where t.codigo = 'EV-REP-041'
on conflict do nothing;

-- DEC-AJ-10 (f): cada operación del ajuste queda en el historial de la Orden.
update rma.tipo_evento
set nombre = 'Ajuste comercial aplicado, cambiado, quitado, corregido, revertido o recalculado',
    visible_historial_actual = true
where codigo = 'EV-REP-041';
