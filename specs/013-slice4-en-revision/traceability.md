# Traceability: VAR-REP-001 + VAR-REP-002

Vista narrativa. La fuente machine-readable es
`traceability/var-rep-001-002.yaml`, validada individualmente por
`npx tsx scripts/validate-traceability.ts traceability/var-rep-001-002.yaml`
y en conjunto por `npm run validate:traceability:global` (IDs sin
colisión y capa de negocio idéntica a `business/`).

## Un archivo, dos Scenarios

Los dos Scenarios son la misma capacidad funcional y se implementan en el
mismo Slice; solo difieren en si el Origen requiere comprobante
(`PoliticaOrigen`). Por la regla de agrupación de `traceability/README.md`
comparten archivo y artefactos, y cada uno conserva ID, definición en
`business/`, tests propios (campo `scenario`) y UAT. No existe un Scenario
`VAR-REP-001-002`.

## Numeración

`US-REP-023..026`, `ACC-REP-036..040`, `FR-REP-087..094`,
`TR-REP-087..096`, `TASK-REP-179..188`, `CODE-REP-157..168`,
`TEST-REP-288..326`, `UAT-REP-023..026` (UAT todos `PENDING`). Ademas, el gate de PROC-REP-140
(`habilitar_orden` solo tras 090 Si) agrego `TEST-REP-327..329` en
`hp-rep-001.yaml` (verifican `TR-REP-027`, que se amplio).

## User Story → Feature

| US | Feature | Resumen |
|---|---|---|
| `US-REP-023` | `FEAT-REP-002` | Enviar a revisión una Orden sin diagnóstico |
| `US-REP-024` | `FEAT-REP-002` | El técnico registra el resultado de la revisión |
| `US-REP-025` | `FEAT-REP-002` | Recepción define Detalles luego de la revisión |
| `US-REP-026` | `FEAT-REP-002` | Garantía RMA directamente en revisión (la Feature oficial de VAR-REP-001) |

## System Action → FR → TR

| ACC | FR | TR |
|---|---|---|
| `ACC-REP-036` enviar a revisión + comprobante por política | `FR-REP-087`, `088`, `094` | `TR-REP-088`, `089`, `095` |
| `ACC-REP-037` revisión técnica (065) | `FR-REP-089` | `TR-REP-090` |
| `ACC-REP-038` definir luego de revisión (068/075 → 140) | `FR-REP-090`, `092` | `TR-REP-091`, `092` |
| `ACC-REP-039` garantía en revisión | `FR-REP-091` | `TR-REP-087`, `093` |
| `ACC-REP-040` acciones publicadas | `FR-REP-093` | `TR-REP-094`, `096` |

## Decisiones que el grafo no expresa por sí solo

- La frontera de revisión (`services/revisiones.py`) es una capacidad, no
  una entidad: `OrdenRevision` queda como aggregate futuro (ver `spec.md`).
  Por eso `TR-REP-090` no tiene un `DM-REP-*`.
- `detalles_origen_ids` (Orden) y `detalle_origen_id` (Detalle) son dos
  niveles distintos de BR-REP-019 y se trazan por separado
  (`TR-REP-087`, `FR-REP-091/092`).
- Este archivo declara solo `FEAT-REP-002`, la Feature que `business/`
  asigna a ambos Scenarios; `FEAT-REP-001/003` son reutilizacion tecnica
  y no se presentan como Features de estos Scenarios.
- Las Tasks son compartidas por ambos Scenarios y por eso no llevan
  campo `scenario`; los tests especificos si.
- Los HP-REP-001/002/003 no se modifican; sus tests de caracterización
  cambiaron solo por las acciones nuevas.
