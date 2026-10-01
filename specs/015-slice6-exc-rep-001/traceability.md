# Traceability: EXC-REP-001

Vista narrativa. La fuente machine-readable es `traceability/exc-rep-001.yaml`
(validada con `npx tsx scripts/validate-traceability.ts traceability/exc-rep-001.yaml`
y, junto al resto, con `npm run validate:traceability:global`).

## Archivo propio

EXC-REP-001 no se agrupa con EXC-REP-002 (regla de `traceability/README.md`):
ambos parten de PROC-REP-090 "Ninguno trabajable", pero tienen decisión
distinta (esperar vs. forzar), actor distinto en la resolución, ciclo
distinto y UAT distinto, y se implementan en Slices separados.

## Numeración

`US-REP-029..031`, `ACC-REP-044..048`, `FR-REP-101..111`, `TR-REP-104..111`,
`TASK-REP-192..194` (más `TASK-REP-043`, `044`, `046`, `047`, `048`
reutilizadas), `CODE-REP-178..194`, `TEST-REP-357..392`,
`UAT-REP-029..032` (`PENDING`).

## Reutilización de Tasks

`TASK-REP-043/044/046/047/048` existían `NOT_IMPLEMENTED` en
`hp-rep-001.yaml`; pasan a `DONE` con una `note` que apunta a este Slice y se
redeclaran en `exc-rep-001.yaml` (mismo id, type y name) para enlazarlas con
los TR nuevos. En `hp-rep-001.yaml` (que debe validar por sí solo) se enlazan
con TR existentes de ese archivo:

- `043`, `044`, `048` → `TR-REP-026` (`validar_factibilidad_detalles`,
  **ampliado**: evalúa por Detalle, fija la condición en cada ejecución —también
  al revalidar—, devuelve "al menos un Detalle trabajable" y registra 100 por
  Detalle).
- `046` → `TR-REP-026` y `TR-REP-022` (`evaluar_situacion_orden`, **ampliado**:
  registra 211, cierra la toma cuando corresponde y, para `PENDIENTE_RECURSOS`,
  continúa directo a 120). El circuito de espera/revalidación queda así cubierto
  en los dos puntos de entrada (ingreso y 211).
- `047` → `TR-REP-060` (`ReparacionDetail.condicion` separa el bloqueo del estado).

`TASK-REP-045` (override) sigue `NOT_IMPLEMENTED`.

## User Story → Feature

| US | Feature | Resumen |
|---|---|---|
| `US-REP-029` | `FEAT-REP-003` | La Orden sin recursos espera sin habilitarse |
| `US-REP-030` | `FEAT-REP-003` | Revalidar desbloquea y continúa |
| `US-REP-031` | `FEAT-REP-003` | Factibilidad parcial en Multi-Detalle |

## System Action → FR → TR

| ACC | FR | TR |
|---|---|---|
| `ACC-REP-044` factibilidad por Detalle y 100 | `FR-REP-101`, `103`, `104` | `TR-REP-104`, `106` |
| `ACC-REP-045` esperar (110 No → 120) | `FR-REP-105`, `106`, `110` | `TR-REP-105`, `110` |
| `ACC-REP-046` revalidar (120 → 080) | `FR-REP-107` | `TR-REP-106`, `107` |
| `ACC-REP-047` acciones y condición expuesta | `FR-REP-108`, `109` | `TR-REP-108`, `109` |
| `ACC-REP-048` factibilidad parcial | `FR-REP-102` | `TR-REP-104` |

## Decisiones que el grafo no expresa por sí solo

- `PENDIENTE_RECURSOS` es un agregado derivado: no hay `FR/TR` de un estado de
  workflow nuevo.
- `habilitar_orden` se amplió para aceptar `EN_REPARACION`, pero el gate de
  Slice 4 (090 `Si`) no se relajó.
- El Scenario oficial declara `FEAT-REP-003`; ese es el único Feature de este
  archivo.
