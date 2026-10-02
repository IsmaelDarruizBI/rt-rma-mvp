# Traceability: EXC-REP-004

Vista narrativa. La fuente machine-readable es `traceability/exc-rep-004.yaml`
(validada con `npx tsx scripts/validate-traceability.ts traceability/exc-rep-004.yaml`
y, junto al resto, con `npm run validate:traceability:global`).

## Archivo propio

EXC-REP-004 no se agrupa con EXC-REP-001/002/003: trigger propio
(`211 → 125`), Feature `FEAT-REP-002` (resuelve `REQUIERE_DEFINICION`) con
dependencia de `FEAT-REP-005` (la produce al cerrar una Ejecución), ciclo y UAT
propios.

```
EXC-REP-004
  └─ FEAT-REP-002 (125/126/127/080) + FEAT-REP-005 (200/210/211, productor)
  └─ BR-REP-001 · BR-REP-003 · BR-REP-004 · BR-REP-012 · BR-REP-015 · BR-REP-018
  └─ TASK-REP-030 (reutilizada) + TASK-REP-201..208
```

`steps[]` del Scenario no cambia (`211 → 125 → 126 → 127 → 080`): 200, 210 y
211 se trazan como nodos productores (`in_scenario: false`).

## Numeración

`US-REP-036..037`, `ACC-REP-055..058`, `FR-REP-128..137`, `TR-REP-127..135`,
`TASK-REP-201..208` (más `TASK-REP-030` reutilizada), `CODE-REP-215..229`,
`TEST-REP-470..510`, `UAT-REP-037..039` (`PENDING`).

## Reutilización de `TASK-REP-030`

Existía `NOT_IMPLEMENTED` en `hp-rep-001.yaml`; pasa a `DONE` con una `note` y se
redeclara en `exc-rep-004.yaml` (mismo id, type y name, sin `spec`) enlazada con
`TR-REP-129..131/133`. En `hp-rep-001.yaml` se enlaza con `TR-REP-022`
(`evaluar_situacion_orden`, que ahora compone 211 → 125).

## Corrección de `TASK-REP-088`

Su nota apuntaba a `TASK-REP-101` para el comando de `REQUIERE_REVISION` (era
incorrecto: 101 es PROC-REP-235, EXC-REP-005). Se corrigió en la preparación y,
al cerrar el Slice, indica que `REQUIERE_REVISION` ya se produce por API (Slice
9, `TASK-REP-030`). Su status no cambia.

## User Story → Feature

| US | Feature | Resumen |
|---|---|---|
| `US-REP-036` | `FEAT-REP-005` | El Técnico declara que la definición ya no sirve al cerrar la Ejecución |
| `US-REP-037` | `FEAT-REP-002` | Recepción redefine el mismo Detalle conservando la definición anterior |

## System Action → FR → TR

| ACC | FR | TR |
|---|---|---|
| `ACC-REP-055` cierre "Requiere redefinicion" + 210 | `FR-REP-128..130` | `TR-REP-127`, `128`, `134` |
| `ACC-REP-056` 211 → 125 o continuar | `FR-REP-131` | `TR-REP-128`, `129`, `135` |
| `ACC-REP-057` revisión 126 | `FR-REP-132` | `TR-REP-130`, `134`, `135` |
| `ACC-REP-058` redefinición 127 → 080 | `FR-REP-133..137` | `TR-REP-131..135` |

## UAT (PENDING)

- `UAT-REP-037` — único Detalle: Requiere redefinición → 125 → 126 → 127 → 080 →
  reingreso al flujo.
- `UAT-REP-038` — Multi-Detalle: A requiere redefinición, se continúa con B y
  después la Orden entra al circuito de A.
- `UAT-REP-039` — Recepción ve la definición anterior conservada y el override
  previo ya no aplica.
