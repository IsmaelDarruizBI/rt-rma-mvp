# Traceability: HP-REP-003 (Garantía de reparación RMA)

Vista narrativa. La fuente machine-readable es
`traceability/hp-rep-003.yaml`, validada individualmente por
`npx tsx scripts/validate-traceability.ts traceability/hp-rep-003.yaml` y
en conjunto por `npm run validate:traceability:global` (IDs sin colisión
entre archivos y capa de negocio idéntica a `business/`).

## Numeración

Continúa la numeración global: `US-REP-021..022`, `ACC-REP-033..035`,
`FR-REP-080..086`, `TR-REP-079..086`, `TASK-REP-171..178`,
`CODE-REP-144..155`, `TEST-REP-262..284`, `UAT-REP-021..022`.

## User Story → Feature

| US | Feature | Resumen |
|---|---|---|
| `US-REP-021` | `FEAT-REP-001` | Generar la garantía de un Detalle entregado |
| `US-REP-022` | `FEAT-REP-007` | Garantía sin cobro, con notificación y entrega |

## System Action → FR → TR

| ACC | FR | TR | Resumen |
|---|---|---|---|
| `ACC-REP-033` | `FR-REP-080`, `081`, `082`, `086` | `TR-REP-079`, `080`, `081`, `082`, `085` | Crear la Orden de garantía vinculada |
| `ACC-REP-034` | `FR-REP-083`, `084` | `TR-REP-083` | `265` por `NO_COBRABLE`; comprobante y entrega |
| `ACC-REP-035` | `FR-REP-085` | `TR-REP-084`, `086` | Publicar `GENERAR_GARANTIA_RMA` |

## Decisiones que el grafo no expresa por sí solo

- Las Features se redeclaran con `implemented_scenario:
  [HP-REP-001, HP-REP-002, HP-REP-003]`, igual que hace `hp-rep-002.yaml`;
  `hp-rep-001.yaml` y `hp-rep-002.yaml` no se modifican.
- El circuito técnico compartido (`150 … 245`) no se redeclara: vive en
  `hp-rep-001.yaml`.
- Los UAT quedan `PENDING`: no hubo ronda formal de aceptación.
