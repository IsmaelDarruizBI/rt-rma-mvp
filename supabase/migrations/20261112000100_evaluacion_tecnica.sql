-- Evaluación técnica de los Detalles diagnosticados por Recepción
-- (BR-REP-035 y BR-REP-036; PROC-REP-182, 183 y 184; HP-REP-001/002 y
-- VAR-REP-019).
--
-- Aditiva y compatible con el código anterior:
--   * `detalle.origen_diagnostico` admite vacío: los Detalles existentes no
--     exigen evaluación (transición de datos) y el código anterior no la
--     escribe;
--   * `cancelacion_origen` suma el valor DESCARTE_TECNICO; los valores
--     anteriores siguen valiendo;
--   * tabla nueva `evaluacion_tecnica`, inmutable;
--   * equivalencias del historial para los pasos nuevos.
-- Idempotente: se puede ejecutar otra vez sin duplicar nada.

alter table rma.detalle
  add column if not exists origen_diagnostico text
    check (origen_diagnostico in ('RECEPCION', 'REVISION_TECNICA'));

comment on column rma.detalle.origen_diagnostico is
  'Quién diagnosticó la definición vigente (BR-REP-026): RECEPCION exige una evaluación técnica CONFIRMADO antes de la primera Ejecución (BR-REP-035); REVISION_TECNICA no. Vacío en los Detalles anteriores, que no la exigen.';

alter table rma.detalle drop constraint detalle_cancelacion_origen_check;
alter table rma.detalle add constraint detalle_cancelacion_origen_check
  check (cancelacion_origen in ('INTERNA', 'RECHAZO_CLIENTE', 'DESISTIMIENTO_CLIENTE', 'DESCARTE_TECNICO'));

comment on column rma.detalle.cancelacion_origen is
  'Por qué se canceló: INTERNA, RECHAZO_CLIENTE, DESISTIMIENTO_CLIENTE o DESCARTE_TECNICO (evaluación técnica, BR-REP-036); solo en un Detalle CANCELADO.';

create table if not exists rma.evaluacion_tecnica (
  id uuid primary key default gen_random_uuid(),
  detalle_id uuid not null references rma.detalle (id),
  version_definicion integer not null check (version_definicion >= 1),
  resultado text not null check (resultado in ('CONFIRMADO', 'DESCARTADO', 'REQUIERE_REDEFINICION')),
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null default now(),
  observaciones text,
  posicion integer not null check (posicion >= 1),
  constraint evaluacion_motivo check (
    resultado = 'CONFIRMADO' or btrim(coalesce(observaciones, '')) <> ''
  ),
  constraint evaluacion_posicion_unica unique (detalle_id, posicion)
);

create index if not exists evaluacion_tecnica_detalle on rma.evaluacion_tecnica (detalle_id, posicion);

drop trigger if exists evaluacion_tecnica_inmutable on rma.evaluacion_tecnica;
create trigger evaluacion_tecnica_inmutable before update or delete on rma.evaluacion_tecnica
  for each row execute function rma.impedir_modificacion();

comment on table rma.evaluacion_tecnica is
  'Cada evaluación técnica de un Detalle diagnosticado por Recepción (PROC-REP-183): sobre la definición vigente, con un resultado principal. Inmutable; una redefinición deja la anterior en el historial.';
comment on column rma.evaluacion_tecnica.id is 'Identificador interno de la evaluación.';
comment on column rma.evaluacion_tecnica.detalle_id is 'Detalle evaluado (referencia a detalle).';
comment on column rma.evaluacion_tecnica.version_definicion is 'Versión de la definición evaluada (1 + las redefiniciones anteriores).';
comment on column rma.evaluacion_tecnica.resultado is 'CONFIRMADO, DESCARTADO o REQUIERE_REDEFINICION.';
comment on column rma.evaluacion_tecnica.usuario_id is 'Técnico que evaluó (referencia a usuario).';
comment on column rma.evaluacion_tecnica.registrado_en is 'Fecha y hora de la evaluación.';
comment on column rma.evaluacion_tecnica.observaciones is 'Motivo u observaciones; obligatorias en DESCARTADO y REQUIERE_REDEFINICION.';
comment on column rma.evaluacion_tecnica.posicion is 'Orden de la evaluación dentro del Detalle.';

grant select, insert on rma.evaluacion_tecnica to rma_backend;

insert into rma.equivalencia_historial (tipo_referencia, referencia_id, accion, tipo_evento_id)
select v.tipo_referencia, v.referencia_id, v.accion, t.id
from (values
  ('PROCESS_NODE', 'PROC-REP-182', null, 'EV-SIS-001'),
  ('PROCESS_NODE', 'PROC-REP-183', null, 'EV-REP-025'),
  ('PROCESS_NODE', 'PROC-REP-184', null, 'EV-SIS-001'),
  -- PROC-REP-128: el tecnico agrega una reparacion adicional (alta de
  -- Detalle, como 070 y 075).
  ('PROCESS_NODE', 'PROC-REP-128', null, 'EV-REP-010')
) as v (tipo_referencia, referencia_id, accion, codigo)
join rma.tipo_evento t on t.codigo = v.codigo
on conflict on constraint equivalencia_unica do nothing;
