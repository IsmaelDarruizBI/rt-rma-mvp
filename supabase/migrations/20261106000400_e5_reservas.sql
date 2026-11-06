-- E5 (A6): reservas de insumos del agregado Orden, QA-A2-M1 y QA-A2-M4.
--
-- Aditiva: agrega una columna nula y un índice, cambia la clave de una tabla
-- sin filas en DEV/UAT, y corrige un bloqueo y una vista. No borra ni reescribe
-- datos. Diseño: docs/postgresql/e4-e7-diseno-integrado.md (sección 17).

-- Orden exacto de los movimientos de cada Orden, como en A4: un comando crea
-- varias reservas en el mismo instante y la lista del dominio conserva el
-- orden de llegada. Los movimientos sin Orden (ingresos y ajustes) y las filas
-- anteriores quedan sin posición.
alter table rma.movimiento_inventario add column posicion integer check (posicion >= 1);

comment on column rma.movimiento_inventario.posicion is 'Orden entre los movimientos de la Orden (1, 2, ...). Vacía en ingresos y ajustes, y en las filas anteriores a E5, que se leen primero.';

create unique index movimiento_inventario_posicion on rma.movimiento_inventario (orden_id, posicion)
  where posicion is not null;

-- QA-A2-M1. Una Ejecución puede declarar dos líneas del mismo insumo (el
-- dominio y la API JSON lo admiten): la clave pasa a ser la línea. posicion la
-- escribe guardar desde A2 en toda fila; DEV y UAT no tienen Órdenes. Un
-- INSERT que no la trae (scripts SQL anteriores) recibe la siguiente de su
-- Ejecución: quien inserta ya tiene la Orden bloqueada.
create or replace function rma.ejecucion_insumo_posicion()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if new.posicion is null then
    select coalesce(max(posicion), 0) + 1 into new.posicion
      from rma.ejecucion_insumo where ejecucion_id = new.ejecucion_id;
  end if;
  return new;
end;
$$;

comment on function rma.ejecucion_insumo_posicion() is
  'Asigna la siguiente línea de la Ejecución a un insumo utilizado que llega sin posición.';

create trigger ejecucion_insumo_posicion before insert on rma.ejecucion_insumo
  for each row execute function rma.ejecucion_insumo_posicion();

alter table rma.ejecucion_insumo drop constraint ejecucion_insumo_pkey;
alter table rma.ejecucion_insumo alter column posicion set not null;
alter table rma.ejecucion_insumo add constraint ejecucion_insumo_pkey primary key (ejecucion_id, posicion);
create index ejecucion_insumo_ejecucion_insumo on rma.ejecucion_insumo (ejecucion_id, insumo_id);

comment on column rma.ejecucion_insumo.posicion is 'Línea de la declaración (1, 2, ...): un mismo insumo puede aparecer en más de una.';

-- Con varias líneas del mismo insumo, lo declarado es su suma. Mismas columnas.
create or replace view rma.v_ejecucion_insumo_consumo as
with declarado as (
  select ejecucion_id, insumo_id, sum(cantidad_utilizada) as cantidad
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

-- QA-A2-M4. El trigger del libro bloqueaba el insumo con FOR UPDATE, que choca
-- con el KEY SHARE de las claves foráneas que lo referencian (ejecucion_insumo,
-- override_insumo, el propio libro): dos transacciones que referencian el
-- insumo y después insertan un movimiento terminaban en deadlock. FOR NO KEY
-- UPDATE no choca con KEY SHARE y sigue chocando consigo mismo: los
-- movimientos de un insumo se siguen aplicando de a uno. Mismo cuerpo.
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
begin
  select * into v_insumo from rma.insumo where id = new.insumo_id for no key update;

  -- Este trigger cambia saldos antes de que PostgreSQL resuelva un ON CONFLICT:
  -- un código repetido se rechaza aquí, para que un INSERT ... ON CONFLICT DO
  -- NOTHING nunca aplique un movimiento que luego se descarta. La verificación
  -- va después del bloqueo del insumo, así ve los movimientos ya confirmados.
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

  -- Vínculo con el movimiento de origen.
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

  -- Efecto sobre los saldos.
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
  'Valida el vínculo de origen de cada movimiento y actualiza los saldos del insumo en la misma transacción. Rechaza el movimiento si dejaría el disponible negativo. Bloquea el insumo con FOR NO KEY UPDATE, para no chocar con las claves foráneas que lo referencian.';
