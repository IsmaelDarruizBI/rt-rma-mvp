-- Ajustes funcionales, bloque 3: ingreso (23/11/2026).
--
-- Aditiva: cuatro columnas nuevas en rma.recepcion, con valores que dejan
-- igual lo registrado antes, y los comentarios de recepcion_version. No
-- borra, renombra ni reutiliza columnas: en particular no toca
-- recepcion.checkin_ingreso, el check-in anterior a UAT-009, que la
-- verificación del ingreso NO reemplaza (DEC-AJ-07).
--
-- - DEC-AJ-05 (BF-04): trabajo_solicitado, lo que pide el cliente en texto
--   libre, distinto de las observaciones del equipo. No crea Detalles.
-- - DEC-AJ-07 (BF-08): funcionalidades_verificadas y
--   observaciones_verificacion, la pregunta del ingreso «¿Se pudieron
--   verificar las funcionalidades del equipo?». Informativa: no es el
--   check-in de entrega (rma.checkin) y no cambia la garantía.
-- - DEC-AJ-06 (BF-05): imei_no_disponible, la marca «IMEI no disponible»
--   del ingreso. El IMEI queda vacío (nunca uno ficticio) y el equipo se
--   identifica con su código interno (EQP-…).
--
-- El IMEI real que se registra después, también con la custodia
-- confirmada (DEC-AJ-06), no necesita columnas: actualiza rma.equipo.imei y
-- la copia de la Orden (orden.equipo_imei), como la corrección del ingreso,
-- y su auditoría es una fila más de rma.recepcion_version (motivo y cambio),
-- que solo crece. rma.recepcion no se actualiza después de decidir la
-- custodia (trigger recepcion_decidida_no_cambia, sin cambios).
--
-- No agrega tablas: los scripts de reinicio del UAT no cambian.
-- Idempotente: se puede ejecutar otra vez.

alter table rma.recepcion
  add column if not exists trabajo_solicitado text,
  add column if not exists funcionalidades_verificadas boolean,
  add column if not exists observaciones_verificacion text,
  add column if not exists imei_no_disponible boolean not null default false;

comment on column rma.recepcion.trabajo_solicitado is
  'Trabajo que pide el cliente, en texto libre y distinto de las observaciones del equipo (DEC-AJ-05); no crea Detalles. Vacío en lo registrado antes.';
comment on column rma.recepcion.funcionalidades_verificadas is
  'Respuesta del ingreso a «¿Se pudieron verificar las funcionalidades del equipo?» (DEC-AJ-07): true sí, false no, vacía sin responder. Informativa: no es el check-in de entrega ni cambia la garantía.';
comment on column rma.recepcion.observaciones_verificacion is
  'Observaciones opcionales de la verificación de funcionalidades del ingreso (DEC-AJ-07).';
comment on column rma.recepcion.imei_no_disponible is
  'El ingreso marcó «IMEI no disponible» (DEC-AJ-06): el IMEI quedó vacío y el equipo se identifica con su código interno, provisorio. Es un hecho del ingreso: no cambia cuando después se registra el IMEI real. false en lo registrado antes.';

comment on table rma.recepcion_version is
  'Datos del ingreso y del equipo reemplazados por una corrección antes de decidir la custodia, o por el registro del IMEI real, que se admite hasta la entrega (DEC-AJ-06).';
