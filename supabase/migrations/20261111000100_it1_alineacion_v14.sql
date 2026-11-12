-- Iteración 1: alineación con la baseline V1.4 (DC15B, DC07, DC11).
--
-- Aditiva: solo agrega columnas que admiten vacío (o con valor por defecto
-- igual al comportamiento anterior), restricciones que las filas existentes
-- ya cumplen y datos de referencia. No cambia ni borra columnas, filas ni
-- equivalencias existentes; el historial ya guardado conserva sus tipos.
--   * DC15B: vigencia de la garantía de cada Detalle reclamado y la
--     excepción autorizada (quién, cuándo y por qué) en la Orden RMA.
--   * DC07: solicitud de desistimiento del cliente sobre un Detalle en
--     ejecución, separada de la cancelación efectiva; estado del trabajo y
--     reversibilidad al interrumpir esa Ejecución.
--   * DC11: clase del ajuste comercial (DESCUENTO o CORTESIA).
-- Idempotente: se puede ejecutar otra vez sin duplicar nada.

-- --- DC15B: vigencia y excepción de la garantía RMA -------------------------

alter table rma.orden
  add column if not exists excepcion_garantia_por uuid references rma.usuario (id),
  add column if not exists excepcion_garantia_en timestamptz,
  add column if not exists excepcion_garantia_motivo text;

alter table rma.orden drop constraint if exists orden_excepcion_garantia_completa;
alter table rma.orden add constraint orden_excepcion_garantia_completa check (
  (excepcion_garantia_por is null and excepcion_garantia_en is null and excepcion_garantia_motivo is null)
  or (
    excepcion_garantia_por is not null and excepcion_garantia_en is not null
    and btrim(coalesce(excepcion_garantia_motivo, '')) <> ''
    and origen = 'RMA_GARANTIA_REPARACION'
  )
);

comment on column rma.orden.excepcion_garantia_por is
  'Garantía RMA con algún Detalle vencido: usuario que autorizó la excepción (referencia a usuario). Vacío si no hubo excepción.';
comment on column rma.orden.excepcion_garantia_en is
  'Fecha y hora en que se autorizó la excepción de garantía.';
comment on column rma.orden.excepcion_garantia_motivo is
  'Motivo de la excepción de garantía autorizada.';

alter table rma.orden_detalle_origen
  add column if not exists garantia_dias integer check (garantia_dias >= 0),
  add column if not exists garantia_vence date,
  add column if not exists garantia_vigente boolean;

comment on column rma.orden_detalle_origen.garantia_dias is
  'Días de garantía del Detalle reclamado, evaluados al iniciar la garantía RMA (PROC-REP-036). Vacío en garantías anteriores a la validación.';
comment on column rma.orden_detalle_origen.garantia_vence is
  'Último día de garantía del Detalle reclamado (entrega más los días).';
comment on column rma.orden_detalle_origen.garantia_vigente is
  'Si la garantía del Detalle reclamado estaba vigente al iniciar la garantía RMA.';

-- --- DC07: desistimiento solicitado y resultado de la interrupción -------------

alter table rma.detalle
  add column if not exists desistimiento_solicitado_por uuid references rma.usuario (id),
  add column if not exists desistimiento_solicitado_en timestamptz,
  add column if not exists desistimiento_motivo text,
  add column if not exists desistimiento_canal text
    check (desistimiento_canal in ('PRESENCIAL', 'TELEFONO', 'WHATSAPP', 'EMAIL', 'OTRO'));

alter table rma.detalle drop constraint if exists detalle_desistimiento_completo;
alter table rma.detalle add constraint detalle_desistimiento_completo check (
  (desistimiento_solicitado_por is null and desistimiento_solicitado_en is null
   and desistimiento_motivo is null and desistimiento_canal is null)
  or (desistimiento_solicitado_por is not null and desistimiento_solicitado_en is not null
      and desistimiento_motivo is not null and desistimiento_canal is not null)
);

comment on column rma.detalle.desistimiento_solicitado_por is
  'Usuario que registró la solicitud de desistimiento del cliente (referencia a usuario). Vacío si no la hubo.';
comment on column rma.detalle.desistimiento_solicitado_en is
  'Fecha y hora de la solicitud de desistimiento; la cancelación efectiva se registra aparte.';
comment on column rma.detalle.desistimiento_motivo is
  'Motivo de la solicitud de desistimiento.';
comment on column rma.detalle.desistimiento_canal is
  'Por dónde pidió el cliente desistir: PRESENCIAL, TELEFONO, WHATSAPP, EMAIL u OTRO.';

alter table rma.ejecucion
  add column if not exists estado_trabajo text,
  add column if not exists reversible boolean;

alter table rma.ejecucion drop constraint if exists ejecucion_resultado_desistimiento;
alter table rma.ejecucion add constraint ejecucion_resultado_desistimiento check (
  estado = 'INTERRUMPIDO' or (estado_trabajo is null and reversible is null)
);

comment on column rma.ejecucion.estado_trabajo is
  'Ejecución interrumpida por un desistimiento: en qué estado quedó el trabajo.';
comment on column rma.ejecucion.reversible is
  'Ejecución interrumpida por un desistimiento: si lo hecho puede revertirse.';

-- --- DC11: clase del ajuste comercial -----------------------------------------

alter table rma.descuento
  add column if not exists clase text not null default 'DESCUENTO'
    check (clase in ('DESCUENTO', 'CORTESIA'));

comment on column rma.descuento.clase is
  'DESCUENTO (rebaja) o CORTESIA (la Orden no se cobra; con pagos previos deja saldo a devolver).';

-- --- Historial -----------------------------------------------------------------

insert into rma.tipo_evento (codigo, nombre, entidad, es_negocio, visible_historial_actual)
values ('EV-REP-052', 'Excepción de garantía autorizada', 'orden', true, true)
on conflict (codigo) do nothing;

insert into rma.equivalencia_historial (tipo_referencia, referencia_id, accion, tipo_evento_id)
select v.tipo_referencia, v.referencia_id, v.accion, t.id
from (values
  ('PROCESS_NODE', 'PROC-REP-036', null, 'EV-SIS-001'),
  ('PROCESS_NODE', 'PROC-REP-036', 'AUTORIZAR_EXCEPCION_GARANTIA', 'EV-REP-052'),
  ('PROCESS_NODE', 'PROC-REP-046', 'SOLICITAR_DESISTIMIENTO_CLIENTE', 'EV-REP-046')
) as v (tipo_referencia, referencia_id, accion, codigo)
join rma.tipo_evento t on t.codigo = v.codigo
on conflict on constraint equivalencia_unica do nothing;

comment on table rma.tipo_evento is
  'Catálogo de tipos de evento: los eventos de negocio aprobados (51 de la base y EV-REP-052, excepción de garantía, de V1.4) y un tipo técnico para los pasos de decisión del proceso. Sus códigos son nuevos y no reutilizan ACC-REP.';
