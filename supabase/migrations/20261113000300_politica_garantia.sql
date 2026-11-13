-- Política de garantía por Tipo de Reparación y corrección del check-in
-- (macroiteración integral, DEC-MI-01 y DEC-MI-05; DC15A, BR-REP-041 y
-- BR-REP-045).
--
-- Aditiva y compatible con el código anterior:
--   * `tipo_reparacion`: plazos con y sin check-in realizado (90 y 30 por
--     defecto: lo que el producto aplicaba fijo) y la política para los
--     trabajos hechos dentro de una garantía RMA, que admite vacío (sin
--     definir, ABI-38: rige el comportamiento anterior);
--   * `detalle`: la copia de esa política al definirlo (BR-REP-015); vacía
--     en los Detalles anteriores, que siguen con 90/30;
--   * `checkin.motivo`: el motivo de una corrección; vacío en el primer
--     registro y en los anteriores.

alter table rma.tipo_reparacion
  add column if not exists garantia_con_checkin integer not null default 90
    check (garantia_con_checkin >= 0),
  add column if not exists garantia_sin_checkin integer not null default 30
    check (garantia_sin_checkin >= 0),
  add column if not exists politica_garantia_rma text
    check (politica_garantia_rma in ('NUEVO_PLAZO', 'PLAZO_RESTANTE', 'SIN_GARANTIA'));

comment on column rma.tipo_reparacion.garantia_con_checkin is
  'Días de garantía sugeridos con el check-in de entrega realizado (DEC-MI-01).';
comment on column rma.tipo_reparacion.garantia_sin_checkin is
  'Días de garantía sugeridos con el check-in de entrega no realizado (DEC-MI-01).';
comment on column rma.tipo_reparacion.politica_garantia_rma is
  'Garantía de un trabajo hecho dentro de una garantía RMA: NUEVO_PLAZO, PLAZO_RESTANTE o SIN_GARANTIA. Vacío: sin definir (ABI-38), rige el plazo del Tipo.';

alter table rma.detalle
  add column if not exists garantia_con_checkin integer check (garantia_con_checkin >= 0),
  add column if not exists garantia_sin_checkin integer check (garantia_sin_checkin >= 0),
  add column if not exists politica_garantia_rma text
    check (politica_garantia_rma in ('NUEVO_PLAZO', 'PLAZO_RESTANTE', 'SIN_GARANTIA'));

comment on column rma.detalle.garantia_con_checkin is
  'Copia del plazo con check-in realizado del Tipo al definir el Detalle (BR-REP-015). Vacío en los anteriores: 90.';
comment on column rma.detalle.garantia_sin_checkin is
  'Copia del plazo con check-in no realizado del Tipo al definir el Detalle. Vacío en los anteriores: 30.';
comment on column rma.detalle.politica_garantia_rma is
  'Copia de la política RMA del Tipo al definir el Detalle.';

alter table rma.checkin add column if not exists motivo text;

comment on column rma.checkin.motivo is
  'Motivo de una corrección del check-in (DEC-MI-05); vacío en el primer registro.';
