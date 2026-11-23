-- Ajustes funcionales, bloque 2 (DEC-AJ-04, 23/11/2026; BF-18): el check-in
-- que falta se registra en la misma confirmación de la entrega y deja en el
-- historial el paso PROC-REP-269 («Orden pendiente de check-in»), seguido de
-- la condición de entrega (PROC-REP-265), el comprobante (280) y la entrega
-- (270).
--
-- Aditiva y solo datos de referencia: la equivalencia del historial para ese
-- paso, con el tipo de evento «Check-in registrado» (EV-REP-033). No cambia
-- tablas, ni las equivalencias existentes, ni el historial ya guardado.
--
-- Quién retira (DEC-AJ-09, P-05) no necesita migración: se guarda en las
-- columnas que rma.salida ya tenía (retira_nombre, retira_telefono y
-- retira_vinculo, TITULAR o TERCERO).
--
-- Idempotente: se puede ejecutar otra vez sin duplicar filas.

insert into rma.equivalencia_historial (tipo_referencia, referencia_id, accion, tipo_evento_id)
select v.tipo_referencia, v.referencia_id, v.accion, t.id
from (values
  ('PROCESS_NODE', 'PROC-REP-269', null, 'EV-REP-033')
) as v (tipo_referencia, referencia_id, accion, codigo)
join rma.tipo_evento t on t.codigo = v.codigo
on conflict on constraint equivalencia_unica do nothing;
