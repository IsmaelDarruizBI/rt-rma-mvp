# Traceability: VAR-REP-003 (Ejecución interrumpida)

Vista narrativa. La fuente machine-readable es `traceability/var-rep-003.yaml`
(validada con `npx tsx scripts/validate-traceability.ts traceability/var-rep-003.yaml`
y, junto al resto, con `npm run validate:traceability:global`).

## Archivo propio

VAR-REP-003 no se agrupa con VAR-REP-001/002 (regla de `traceability/README.md`):
activa otra Feature (`FEAT-REP-005`), ocurre en otro punto del proceso
(PROC-REP-200, no el ingreso) y agrega otra mecánica técnica.

## Numeración

`US-REP-027..028`, `ACC-REP-041..043`, `FR-REP-095..100`, `TR-REP-097..103`,
`TASK-REP-189..191` (más `TASK-REP-087` y `TASK-REP-091` reutilizadas),
`CODE-REP-169..177`, `TEST-REP-330..356`, `UAT-REP-027..028` (`PENDING`).

## Reutilización de Tasks

`TASK-REP-087` y `TASK-REP-091` existían `NOT_IMPLEMENTED` en
`hp-rep-001.yaml`; pasan a `DONE` con una `note` que apunta a este Slice y
se redeclaran en `var-rep-003.yaml` (mismo id, type y name) para enlazarlas
con los TR nuevos. En `hp-rep-001.yaml` se enlazan con `TR-REP-061`
(ampliado: `completar_ejecucion` e `interrumpir_ejecucion` comparten
`_cerrar_ejecucion`) y `TR-REP-034` (identidad del ejecutor y pertenencia de la Ejecución a su toma). `TASK-REP-089/090` (DESPERDICIO) siguen
`NOT_IMPLEMENTED`.

## User Story → Feature

| US | Feature | Resumen |
|---|---|---|
| `US-REP-027` | `FEAT-REP-005` | Interrumpir conservando lo realizado |
| `US-REP-028` | `FEAT-REP-005` | Continuar con una Ejecución nueva |

## System Action → FR → TR

| ACC | FR | TR |
|---|---|---|
| `ACC-REP-041` registrar Interrumpido (200 → 210 → 211) | `FR-REP-095`, `096`, `097`, `098` | `TR-REP-097`, `098`, `099`, `100` |
| `ACC-REP-042` publicar `INTERRUMPIR_EJECUCION` | `FR-REP-099` | `TR-REP-101`, `102` |
| `ACC-REP-043` continuar con Ejecución nueva | `FR-REP-100` | `TR-REP-102`, `103` |

## Decisiones que el grafo no expresa por sí solo

- `DESPERDICIO` queda fuera: no hay `FR/TR` que lo afirme.
- Los tests de transversalidad (`RT_INTERNO`, garantía RMA) verifican
  `FR-REP-095`; no se declaran artefactos por Origen.
