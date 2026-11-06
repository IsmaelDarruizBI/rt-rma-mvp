-- E5 (A7): ingresos y ajustes de stock, y DI-8.
--
-- Aditiva: agrega columnas nulas, una secuencia e índices, y relaja una
-- restricción. No borra ni reescribe datos.
-- Diseño: docs/postgresql/e4-e7-diseno-integrado.md (sección 18).

-- DI-8 (aprobada): un ajuste guarda el motivo como texto libre, como la API.
-- El código del catálogo de motivos queda opcional, para una clasificación
-- futura: no se inventa. Las demás condiciones de cada tipo no cambian.
alter table rma.movimiento_inventario drop constraint movimiento_vinculos_por_tipo;
alter table rma.movimiento_inventario add constraint movimiento_vinculos_por_tipo check (
  (tipo = 'RESERVA'
     and orden_id is not null and detalle_id is not null
     and movimiento_origen_id is null and motivo_ajuste_id is null)
  or (tipo in ('CONSUMO', 'LIBERACION_RESERVA', 'DESPERDICIO')
     and orden_id is not null and detalle_id is not null and ejecucion_id is not null
     and movimiento_origen_id is not null and motivo_ajuste_id is null)
  or (tipo = 'DEVOLUCION'
     and orden_id is not null and detalle_id is not null
     and movimiento_origen_id is not null and motivo_ajuste_id is null)
  or (tipo = 'INGRESO'
     and orden_id is null and detalle_id is null and ejecucion_id is null
     and movimiento_origen_id is null and motivo_ajuste_id is null
     and motivo_texto is not null)
  or (tipo in ('AJUSTE_POSITIVO', 'AJUSTE_NEGATIVO')
     and orden_id is null and detalle_id is null and ejecucion_id is null
     and movimiento_origen_id is null
     and motivo_texto is not null and usuario_id is not null)
);

alter table rma.movimiento_inventario add constraint movimiento_motivo_texto_no_vacio
  check (motivo_texto is null or btrim(motivo_texto) <> '');

comment on column rma.movimiento_inventario.motivo_ajuste_id is 'Motivo del catálogo, opcional (DI-8): el motivo del ajuste es el texto libre de motivo_texto.';

-- DI-4. Clave del envío que registró un ingreso o un ajuste: un reintento
-- con la misma clave no se aplica dos veces, como en JSON (única entre todos
-- los movimientos que la tienen).
alter table rma.movimiento_inventario add column operacion_id text check (operacion_id is null or btrim(operacion_id) <> '');

comment on column rma.movimiento_inventario.operacion_id is 'Clave del envío que registró el ingreso o el ajuste: un reintento con la misma clave no lo duplica. Vacía en los movimientos de las Órdenes.';

create unique index movimiento_inventario_operacion on rma.movimiento_inventario (operacion_id)
  where operacion_id is not null;

-- Orden de llegada de los movimientos: el historial de ingresos y ajustes
-- conserva el orden en que se registraron aunque compartan el instante. Solo
-- las filas nuevas reciben número; las anteriores quedan vacías y se leen
-- primero.
create sequence rma.movimiento_inventario_secuencia;
alter table rma.movimiento_inventario add column secuencia bigint;
alter table rma.movimiento_inventario alter column secuencia set default nextval('rma.movimiento_inventario_secuencia');
alter sequence rma.movimiento_inventario_secuencia owned by rma.movimiento_inventario.secuencia;
grant usage, select on sequence rma.movimiento_inventario_secuencia to rma_backend;

comment on column rma.movimiento_inventario.secuencia is 'Orden de llegada del movimiento. Vacía en las filas anteriores a E5, que se leen primero.';
