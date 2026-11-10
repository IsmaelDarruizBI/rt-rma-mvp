-- DC31: circuito de cancelación (cancelar Detalles no cancela la Orden;
-- cancelar la Orden es explícito y terminal).
--
-- Aditiva y solo datos de referencia: equivalencias del historial para los
-- pasos nuevos. No cambia tablas, ni las equivalencias existentes, ni el
-- historial ya guardado (los eventos anteriores conservan su tipo).
--   * PROC-REP-307, Orden sin trabajos vigentes: paso de decisión del proceso.
--   * PROC-REP-308, Cancelar Orden: la Orden se cancela.
--   * PROC-REP-305 con la acción CANCELAR_TRABAJOS_PENDIENTES: hoy cancela
--     trabajos, no la Orden (Detalle cancelado). Sin acción (historial
--     anterior) sigue siendo "Orden cancelada".
-- Idempotente: se puede ejecutar otra vez sin duplicar filas.

insert into rma.equivalencia_historial (tipo_referencia, referencia_id, accion, tipo_evento_id)
select v.tipo_referencia, v.referencia_id, v.accion, t.id
from (values
  ('PROCESS_NODE', 'PROC-REP-307', null, 'EV-SIS-001'),
  ('PROCESS_NODE', 'PROC-REP-308', null, 'EV-REP-045'),
  ('PROCESS_NODE', 'PROC-REP-305', 'CANCELAR_TRABAJOS_PENDIENTES', 'EV-REP-044')
) as v (tipo_referencia, referencia_id, accion, codigo)
join rma.tipo_evento t on t.codigo = v.codigo
on conflict on constraint equivalencia_unica do nothing;
