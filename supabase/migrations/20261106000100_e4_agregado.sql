-- E4 (A0): persistencia del agregado Orden de Reparación.
--
-- Aditiva: agrega columnas nulas, una función, filas de referencia y una
-- restricción; no borra ni reescribe datos.
-- Diseño: docs/postgresql/e4-e7-diseno-integrado.md (DA-5, DA-6, DA-7, DA-10).

-- DA-7 / QA-E2-5. El número de Orden no se trunca: OR-000001 ... OR-999999,
-- OR-1000000. El default anterior (lpad a 6) cortaba los números de 7 cifras.
create or replace function rma.formatear_numero_orden(p_numero bigint)
returns text
language sql
immutable
set search_path = rma, pg_temp
as $$
  select 'OR-' || lpad(p_numero::text, greatest(6, length(p_numero::text)), '0')
$$;

comment on function rma.formatear_numero_orden(bigint) is
  'Número de Orden con al menos 6 dígitos, sin truncar los más largos.';

revoke all on function rma.formatear_numero_orden(bigint) from public;
grant execute on function rma.formatear_numero_orden(bigint) to rma_backend;

alter table rma.orden
  alter column codigo set default rma.formatear_numero_orden(nextval('rma.orden_numero_seq'));

-- DA-5. Campos del dominio que el esquema no conservaba.

-- La última modificación según el dominio (updated_at). modificado_en lo
-- fija un trigger con la hora de la base y no sirve para reproducirlo.
alter table rma.orden add column actualizado_en timestamptz;
comment on column rma.orden.actualizado_en is
  'Última modificación de la Orden según la aplicación (updated_at del dominio). modificado_en es la hora técnica de la base.';

-- La garantía con que quedó la versión anterior al reemplazarla: puede
-- haberse ajustado después de definirla (ajuste_garantia), y la fila de esa
-- versión es inmutable.
alter table rma.detalle_version
  add column garantia_dias_reemplazada integer check (garantia_dias_reemplazada >= 0);
comment on column rma.detalle_version.garantia_dias_reemplazada is
  'Días de garantía que tenía la versión anterior al ser reemplazada por esta (vacío en la versión 1).';

-- Posición en las listas del dominio que no tienen fecha única: dos
-- registros con la misma fecha conservan su orden.
alter table rma.orden_detalle_origen add column posicion integer check (posicion >= 1);
alter table rma.decision_cliente add column posicion integer check (posicion >= 1);
alter table rma.ajuste_garantia add column posicion integer check (posicion >= 1);
alter table rma.control_tecnico add column posicion integer check (posicion >= 1);
alter table rma.toma add column posicion integer check (posicion >= 1);
alter table rma.ejecucion add column posicion integer check (posicion >= 1);
alter table rma.ejecucion_insumo add column posicion integer check (posicion >= 1);

comment on column rma.orden_detalle_origen.posicion is 'Orden en la lista de la Orden (1, 2, ...).';
comment on column rma.decision_cliente.posicion is 'Orden entre las decisiones del Detalle (1, 2, ...).';
comment on column rma.ajuste_garantia.posicion is 'Orden entre los ajustes del Detalle (1, 2, ...).';
comment on column rma.control_tecnico.posicion is 'Orden entre los controles del Detalle (1, 2, ...).';
comment on column rma.toma.posicion is 'Orden entre las tomas de la Orden (1, 2, ...).';
comment on column rma.ejecucion.posicion is 'Orden entre las Ejecuciones de la Orden (1, 2, ...).';
comment on column rma.ejecucion_insumo.posicion is 'Orden entre los insumos de la Ejecución (1, 2, ...).';

-- DA-6 / F-06. Una Orden entregada o terminada (EVT-REP-999) tiene fecha de
-- cierre. Con orden_cierre_coherente, cerrada_en no nulo equivale a cerrada.
alter table rma.orden add constraint orden_cerrada_con_fecha check (
  cerrada_en is not null
  or (estado_workflow <> 'ENTREGADA' and posicion_proceso <> 'EVT-REP-999')
);

-- DA-10 / E4-MP. Los medios de pago predeterminados del dominio existen como
-- filas: un pago los referencia por clave foránea. Idempotente: no cambia
-- los que ya estén cargados.
insert into rma.medio_pago (codigo, nombre, orden) values
  ('EFECTIVO', 'Efectivo', 1),
  ('TRANSFERENCIA', 'Transferencia', 2),
  ('TARJETA_DEBITO', 'Tarjeta de debito', 3),
  ('TARJETA_CREDITO', 'Tarjeta de credito', 4),
  ('OTRO', 'Otro', 5)
on conflict (codigo) do nothing;
