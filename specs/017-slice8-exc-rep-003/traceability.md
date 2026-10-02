# Traceability: EXC-REP-003

Vista narrativa. La fuente machine-readable es `traceability/exc-rep-003.yaml`
(validada con `npx tsx scripts/validate-traceability.ts traceability/exc-rep-003.yaml`
y, junto al resto, con `npm run validate:traceability:global`).

## Archivo propio

EXC-REP-003 no se agrupa con EXC-REP-001/002 (regla de
`traceability/README.md`): el disparador es otro (PROC-REP-185 → 186, dentro del
taller y con la toma activa), la Feature es `FEAT-REP-005` (no `FEAT-REP-003`),
y tiene ciclo y UAT propios.

## Numeración

`US-REP-034..035`, `ACC-REP-052..054`, `FR-REP-120..127`, `TR-REP-120..126`,
`TASK-REP-198..200` (más `TASK-REP-086` reutilizada), `CODE-REP-207..214`,
`TEST-REP-425..469`, `UAT-REP-035..036` (`PENDING`).

## Reutilización de `TASK-REP-086`

Existía `NOT_IMPLEMENTED` en `hp-rep-001.yaml`; pasa a `DONE` con una `note` y se
redeclara en `exc-rep-003.yaml` (mismo id, type y name, sin `spec`) para enlazarla
con los TR nuevos (`TR-REP-121..124`). En `hp-rep-001.yaml` se enlaza con
`TR-REP-022` (211 → 120) y `TR-REP-033` (reserva todo-o-nada).

Otros ajustes en `hp-rep-001.yaml`: la `note` de `TASK-REP-088` (PENDIENTE_RECURSOS
ya se produce por API; REQUIERE_REVISION sigue pendiente) y `TR-REP-027`
(`habilitar_orden` acepta `EN_COLA` sin relajar el gate). En `exc-rep-002.yaml`:
`FR-REP-117` y el nombre de `TEST-REP-422` (ahora 200 + 186).

## User Story → Feature

| US | Feature | Resumen |
|---|---|---|
| `US-REP-034` | `FEAT-REP-005` | El Técnico ve la reserva fallida, el Detalle bloqueado y continúa o libera |
| `US-REP-035` | `FEAT-REP-005` | La Orden pendiente de recursos se revalida o se fuerza y vuelve a habilitarse |

## System Action → FR → TR

| ACC | FR | TR |
|---|---|---|
| `ACC-REP-052` reserva fallida (185 + 186) | `FR-REP-120`, `121`, `124`, `125` | `TR-REP-120`, `121`, `122`, `124` |
| `ACC-REP-053` recalcular 211 (continuar o 120) | `FR-REP-122`, `123` | `TR-REP-123` |
| `ACC-REP-054` habilitar desde `EN_COLA` + progreso | `FR-REP-126`, `127` | `TR-REP-125`, `126` |

## Decisiones que el grafo no expresa por sí solo

- 120 y 140 se declaran como `in_scenario: false` (consecuencias de 211 y de la
  revalidación); los nodos del Scenario son 185, 186 y 211.
- El Scenario dice `PENDIENTE`; el modelo usa `DEFINIDO` (mapping documentado en
  `enums.py` y en el spec).
- `EXC-REP-004`/`005` siguen `NOT_IMPLEMENTED` y no se trazan aquí.
- No existe un flag de "reserva fallida": el estado sale del historial y de la
  `condicion` del Detalle.
