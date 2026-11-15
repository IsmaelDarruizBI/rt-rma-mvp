-- Lotes, series, desperdicio y devolución en el libro de inventario
-- (macroiteración integral, DEC-MI-10; cierra ABI-22).
--
-- Aditiva y compatible con el stock existente:
--   * `insumo.control` (SIN_LOTE por defecto: todos los insumos actuales
--     siguen igual) y `insumo.precio` (lo configura Administración,
--     DEC-MI-09);
--   * `lote_insumo`: lotes y unidades serializadas, inmutables;
--   * `movimiento_inventario.lote_id`: el lote de cada movimiento, si lo
--     tiene. El saldo de un lote es la suma de sus movimientos: no se guarda
--     aparte. El stock SIN LOTE IDENTIFICADO es el físico menos los saldos de
--     los lotes: así queda el stock que existía antes de controlar el insumo
--     por lote, sin inventar números históricos;
--   * se habilitan DESPERDICIO (cierra una reserva, como el consumo) y
--     DEVOLUCION (vuelve al stock lo consumido, al mismo lote), ya previstos
--     por el libro (movimiento_tipo_con_operacion);
--   * `ejecucion_insumo` guarda también el desperdicio declarado y el lote.
--     `cantidad_utilizada` sigue siendo todo lo que salió del stock en esa
--     línea (utilizado más desperdicio, siempre mayor que cero) y
--     `desperdicio` es la parte inutilizada: así se conserva la restricción
--     original y la versión anterior de la aplicación puede leer cualquier
--     fila durante una vuelta atrás (para ella, lo desperdiciado cuenta como
--     utilizado). `v_ejecucion_insumo_consumo` declara solo lo utilizado.
--
-- La disponibilidad sigue siendo una por insumo (físico menos reservado):
-- los lotes desagregan el físico. El trigger del libro valida los lotes.

alter table rma.insumo add column if not exists control text not null default 'SIN_LOTE'
  check (control in ('SIN_LOTE', 'LOTE', 'SERIE'));
alter table rma.insumo add column if not exists precio numeric(12, 2)
  check (precio is null or precio >= 0);
comment on column rma.insumo.control is
  'SIN_LOTE, LOTE o SERIE (DEC-MI-10). Lo configura Administración; pasar a LOTE o SERIE deja el stock existente como «sin lote identificado».';
comment on column rma.insumo.precio is
  'Precio del insumo que configura Administración (DEC-MI-09); vacío si no se definió.';
grant update (control, precio) on rma.insumo to rma_backend;

create table if not exists rma.lote_insumo (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  insumo_id uuid not null references rma.insumo (id),
  numero text not null check (btrim(numero) <> ''),
  serie boolean not null default false,
  origen text not null check (origen in ('COMPRA', 'INGRESO_MANUAL')),
  referencia text,
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null,
  constraint lote_insumo_numero unique (insumo_id, numero),
  constraint lote_insumo_de_insumo unique (id, insumo_id)
);

drop trigger if exists lote_insumo_inmutable on rma.lote_insumo;
create trigger lote_insumo_inmutable before update or delete on rma.lote_insumo
  for each row execute function rma.impedir_modificacion();

comment on table rma.lote_insumo is
  'Lotes y unidades serializadas de los insumos (DEC-MI-10). Inmutables. El saldo sale del libro (v_saldo_lote).';
comment on column rma.lote_insumo.id is 'Identificador interno del lote.';
comment on column rma.lote_insumo.codigo is 'Identificador público del lote (LOT-...).';
comment on column rma.lote_insumo.insumo_id is 'Insumo del lote (referencia a insumo).';
comment on column rma.lote_insumo.numero is 'Número de lote o de serie, único por insumo.';
comment on column rma.lote_insumo.serie is 'Si es una unidad serializada (cantidad 1).';
comment on column rma.lote_insumo.origen is 'COMPRA (recepción de una orden de compra) o INGRESO_MANUAL.';
comment on column rma.lote_insumo.referencia is 'Referencia del origen, por ejemplo la recepción de compra.';
comment on column rma.lote_insumo.usuario_id is 'Quién lo registró (referencia a usuario).';
comment on column rma.lote_insumo.registrado_en is 'Fecha y hora del alta.';

alter table rma.movimiento_inventario add column if not exists lote_id uuid;
alter table rma.movimiento_inventario drop constraint if exists movimiento_lote;
alter table rma.movimiento_inventario add constraint movimiento_lote
  foreign key (lote_id, insumo_id) references rma.lote_insumo (id, insumo_id);
create index if not exists movimiento_lote_idx on rma.movimiento_inventario (lote_id) where lote_id is not null;
comment on column rma.movimiento_inventario.lote_id is
  'Lote o unidad serializada del movimiento (referencia a lote_insumo); vacío: stock sin lote identificado.';

-- DESPERDICIO y DEVOLUCION pasan a tener operación (DEC-MI-10).
alter table rma.movimiento_inventario drop constraint if exists movimiento_tipo_con_operacion;

alter table rma.ejecucion_insumo add column if not exists desperdicio numeric(12, 3) not null default 0
  check (desperdicio >= 0);
alter table rma.ejecucion_insumo add column if not exists lote_id uuid;
alter table rma.ejecucion_insumo drop constraint if exists ejecucion_insumo_lote;
alter table rma.ejecucion_insumo add constraint ejecucion_insumo_lote
  foreign key (lote_id, insumo_id) references rma.lote_insumo (id, insumo_id);
alter table rma.ejecucion_insumo drop constraint if exists ejecucion_insumo_desperdicio_incluido;
alter table rma.ejecucion_insumo add constraint ejecucion_insumo_desperdicio_incluido
  check (desperdicio <= cantidad_utilizada);
comment on column rma.ejecucion_insumo.cantidad_utilizada is 'Todo lo que salió del stock en la línea: lo utilizado más el desperdicio (siempre mayor que cero).';
comment on column rma.ejecucion_insumo.desperdicio is 'Parte de cantidad_utilizada que se inutilizó (DEC-MI-10); lo utilizado es la diferencia.';

-- Lo declarado como utilizado excluye el desperdicio, que sale del stock como
-- DESPERDICIO y no como CONSUMO. Mismas columnas.
create or replace view rma.v_ejecucion_insumo_consumo as
with declarado as (
  select ejecucion_id, insumo_id, sum(cantidad_utilizada - desperdicio) as cantidad
  from rma.ejecucion_insumo
  group by ejecucion_id, insumo_id
),
consumido as (
  select ejecucion_id, insumo_id, sum(cantidad) as cantidad
  from rma.movimiento_inventario
  where tipo = 'CONSUMO'
  group by ejecucion_id, insumo_id
)
select
  coalesce(d.ejecucion_id, c.ejecucion_id) as ejecucion_id,
  coalesce(d.insumo_id, c.insumo_id) as insumo_id,
  coalesce(d.cantidad, 0) as utilizada_declarada,
  coalesce(c.cantidad, 0) as consumida,
  greatest(coalesce(d.cantidad, 0) - coalesce(c.cantidad, 0), 0) as sin_respaldo
from declarado d
full join consumido c on c.ejecucion_id = d.ejecucion_id and c.insumo_id = d.insumo_id;
comment on column rma.ejecucion_insumo.lote_id is 'Lote de donde salió (referencia a lote_insumo); vacío: sin lote identificado.';

create or replace view rma.v_saldo_lote as
select
  l.id as lote_id,
  l.insumo_id,
  l.numero,
  l.serie,
  coalesce(sum(case
    when m.tipo in ('INGRESO', 'AJUSTE_POSITIVO', 'DEVOLUCION') then m.cantidad
    when m.tipo in ('CONSUMO', 'DESPERDICIO', 'AJUSTE_NEGATIVO') then -m.cantidad
    else 0 end), 0) as saldo
from rma.lote_insumo l
left join rma.movimiento_inventario m on m.lote_id = l.id
group by l.id;

comment on view rma.v_saldo_lote is 'Saldo de cada lote, calculado desde el libro (DEC-MI-10).';
comment on column rma.v_saldo_lote.lote_id is 'Lote (referencia a lote_insumo).';
comment on column rma.v_saldo_lote.insumo_id is 'Insumo (referencia a insumo).';
comment on column rma.v_saldo_lote.numero is 'Número de lote o de serie.';
comment on column rma.v_saldo_lote.serie is 'Si es una unidad serializada.';
comment on column rma.v_saldo_lote.saldo is 'Ingresos, ajustes positivos y devoluciones menos consumos, desperdicios y ajustes negativos del lote.';
grant select on rma.v_saldo_lote to rma_backend;

create or replace function rma.aplicar_movimiento_inventario()
returns trigger
language plpgsql
security definer
set search_path = rma, pg_temp
as $$
declare
  v_insumo rma.insumo%rowtype;
  v_origen rma.movimiento_inventario%rowtype;
  v_cerrado numeric(12, 3);
  v_aplica_a text;
  v_sentido text;
  v_cerrada_orden timestamptz;
  v_fisico numeric(12, 3);
  v_reservado numeric(12, 3);
  v_signo integer;
  v_saldo_lote numeric(12, 3);
  v_en_lotes numeric(12, 3);
begin
  select * into v_insumo from rma.insumo where id = new.insumo_id for no key update;

  if exists (select 1 from rma.movimiento_inventario where codigo = new.codigo) then
    raise exception 'El movimiento % ya existe. El libro no admite ON CONFLICT: un reintento se resuelve con la clave de idempotencia de la acción.', new.codigo
      using errcode = 'unique_violation';
  end if;

  if new.orden_id is not null then
    select cerrada_en into v_cerrada_orden from rma.orden where id = new.orden_id;
    if v_cerrada_orden is not null then
      raise exception 'La Orden está cerrada: no admite movimientos de inventario.'
        using errcode = 'restrict_violation';
    end if;
  end if;

  if new.tipo in ('RESERVA', 'INGRESO', 'AJUSTE_POSITIVO') and not v_insumo.activo then
    raise exception 'El insumo % está inactivo: no admite reservas ni ingresos nuevos.', v_insumo.codigo
      using errcode = 'check_violation';
  end if;

  if new.tipo in ('CONSUMO', 'LIBERACION_RESERVA', 'DESPERDICIO') then
    select * into v_origen from rma.movimiento_inventario where id = new.movimiento_origen_id;
    if v_origen.tipo <> 'RESERVA'
       or v_origen.orden_id <> new.orden_id
       or v_origen.detalle_id <> new.detalle_id then
      raise exception 'Un % debe cerrar una RESERVA del mismo insumo, Orden y Detalle.', new.tipo
        using errcode = 'check_violation';
    end if;
    select coalesce(sum(cantidad), 0) into v_cerrado
      from rma.movimiento_inventario
     where movimiento_origen_id = v_origen.id
       and tipo in ('CONSUMO', 'LIBERACION_RESERVA', 'DESPERDICIO');
    if v_cerrado + new.cantidad > v_origen.cantidad then
      raise exception 'La reserva % tiene pendiente %, menos que % de %.',
        v_origen.codigo, v_origen.cantidad - v_cerrado, new.cantidad, new.tipo
        using errcode = 'check_violation';
    end if;
  elsif new.tipo = 'DEVOLUCION' then
    select * into v_origen from rma.movimiento_inventario where id = new.movimiento_origen_id;
    if v_origen.tipo <> 'CONSUMO'
       or v_origen.orden_id <> new.orden_id
       or v_origen.detalle_id <> new.detalle_id then
      raise exception 'Una DEVOLUCION debe referenciar un CONSUMO del mismo insumo, Orden y Detalle.'
        using errcode = 'check_violation';
    end if;
    if new.lote_id is distinct from v_origen.lote_id then
      raise exception 'Una DEVOLUCION vuelve al mismo lote del CONSUMO que devuelve.'
        using errcode = 'check_violation';
    end if;
    select coalesce(sum(cantidad), 0) into v_cerrado
      from rma.movimiento_inventario
     where movimiento_origen_id = v_origen.id and tipo = 'DEVOLUCION';
    if v_cerrado + new.cantidad > v_origen.cantidad then
      raise exception 'La devolución supera lo consumido en % menos lo ya devuelto.', v_origen.codigo
        using errcode = 'check_violation';
    end if;
  elsif new.tipo in ('AJUSTE_POSITIVO', 'AJUSTE_NEGATIVO') then
    select aplica_a into v_aplica_a from rma.motivo_ajuste where id = new.motivo_ajuste_id;
    v_sentido := case new.tipo when 'AJUSTE_POSITIVO' then 'POSITIVO' else 'NEGATIVO' end;
    if v_aplica_a not in ('AMBOS', v_sentido) then
      raise exception 'El motivo elegido no aplica a un %.', new.tipo using errcode = 'check_violation';
    end if;
  end if;

  -- DEC-MI-10: lotes.
  v_signo := case
    when new.tipo in ('INGRESO', 'AJUSTE_POSITIVO', 'DEVOLUCION') then 1
    when new.tipo in ('CONSUMO', 'DESPERDICIO', 'AJUSTE_NEGATIVO') then -1
    else 0 end;
  if new.lote_id is not null and v_insumo.control = 'SIN_LOTE' then
    raise exception 'El insumo % no se controla por lote.', v_insumo.codigo
      using errcode = 'check_violation';
  end if;
  if new.tipo = 'INGRESO' and v_insumo.control <> 'SIN_LOTE' and new.lote_id is null then
    raise exception 'El insumo % se controla por lote o serie: el ingreso nombra su lote.', v_insumo.codigo
      using errcode = 'check_violation';
  end if;
  if new.lote_id is not null and v_signo <> 0 then
    select coalesce(sum(case
      when tipo in ('INGRESO', 'AJUSTE_POSITIVO', 'DEVOLUCION') then cantidad
      when tipo in ('CONSUMO', 'DESPERDICIO', 'AJUSTE_NEGATIVO') then -cantidad
      else 0 end), 0)
      into v_saldo_lote
      from rma.movimiento_inventario where lote_id = new.lote_id;
    v_saldo_lote := v_saldo_lote + v_signo * new.cantidad;
    if v_saldo_lote < 0 then
      raise exception 'El lote no alcanza: quedaría en %.', v_saldo_lote
        using errcode = 'check_violation';
    end if;
    if v_saldo_lote > 1 and exists (select 1 from rma.lote_insumo where id = new.lote_id and serie) then
      raise exception 'Una unidad serializada no puede estar más de una vez en stock.'
        using errcode = 'check_violation';
    end if;
  end if;

  v_fisico := v_insumo.stock_fisico;
  v_reservado := v_insumo.stock_reservado;
  case new.tipo
    when 'RESERVA' then v_reservado := v_reservado + new.cantidad;
    when 'LIBERACION_RESERVA' then v_reservado := v_reservado - new.cantidad;
    when 'CONSUMO' then v_fisico := v_fisico - new.cantidad; v_reservado := v_reservado - new.cantidad;
    when 'DESPERDICIO' then v_fisico := v_fisico - new.cantidad; v_reservado := v_reservado - new.cantidad;
    when 'DEVOLUCION' then v_fisico := v_fisico + new.cantidad;
    when 'INGRESO' then v_fisico := v_fisico + new.cantidad;
    when 'AJUSTE_POSITIVO' then v_fisico := v_fisico + new.cantidad;
    when 'AJUSTE_NEGATIVO' then v_fisico := v_fisico - new.cantidad;
  end case;

  if v_fisico < v_reservado then
    raise exception 'El movimiento dejaría el stock físico de % en % con % reservado: el disponible no puede ser negativo. Regularizá antes las reservas.',
      v_insumo.codigo, v_fisico, v_reservado
      using errcode = 'check_violation';
  end if;

  -- El stock sin lote identificado (físico menos lotes) nunca queda negativo.
  if v_signo <> 0 and v_insumo.control <> 'SIN_LOTE' then
    select coalesce(sum(case
      when tipo in ('INGRESO', 'AJUSTE_POSITIVO', 'DEVOLUCION') then cantidad
      when tipo in ('CONSUMO', 'DESPERDICIO', 'AJUSTE_NEGATIVO') then -cantidad
      else 0 end), 0)
      into v_en_lotes
      from rma.movimiento_inventario
     where insumo_id = new.insumo_id and lote_id is not null;
    if new.lote_id is not null then
      v_en_lotes := v_en_lotes + v_signo * new.cantidad;
    end if;
    if v_fisico < v_en_lotes then
      raise exception 'El stock sin lote identificado de % quedaría negativo: elegí el lote.', v_insumo.codigo
        using errcode = 'check_violation';
    end if;
  end if;

  new.stock_fisico_anterior := v_insumo.stock_fisico;
  new.stock_fisico_resultante := v_fisico;
  new.stock_reservado_resultante := v_reservado;

  update rma.insumo
     set stock_fisico = v_fisico, stock_reservado = v_reservado
   where id = new.insumo_id;

  return new;
end;
$$;

comment on function rma.aplicar_movimiento_inventario() is
  'Valida el vínculo de origen de cada movimiento y sus lotes (DEC-MI-10) y actualiza los saldos del insumo en la misma transacción. Rechaza el movimiento si dejaría el disponible, un lote o el stock sin lote identificado negativos. Bloquea el insumo con FOR NO KEY UPDATE.';

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
  where r.pendiente < 0
  union all
  select 'LOTE_NEGATIVO', l.codigo, format('saldo %s', s.saldo)
  from rma.v_saldo_lote s
  join rma.lote_insumo l on l.id = s.lote_id
  where s.saldo < 0
  union all
  select 'SIN_LOTE_NEGATIVO', i.codigo,
         format('físico %s, en lotes %s', i.stock_fisico, sum(s.saldo))
  from rma.insumo i
  join rma.v_saldo_lote s on s.insumo_id = i.id
  group by i.id
  having i.stock_fisico < sum(s.saldo);
$$;

grant select, insert on rma.lote_insumo to rma_backend;
