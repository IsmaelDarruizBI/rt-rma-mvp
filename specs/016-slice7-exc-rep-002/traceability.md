# Traceability: EXC-REP-002

Vista narrativa. La fuente machine-readable es `traceability/exc-rep-002.yaml`
(validada con `npx tsx scripts/validate-traceability.ts traceability/exc-rep-002.yaml`
y, junto al resto, con `npm run validate:traceability:global`).

## Archivo propio

EXC-REP-002 no se agrupa con EXC-REP-001 (regla de `traceability/README.md`):
misma situación inicial (090 Ninguno → 100) pero decisión distinta (forzar en
vez de esperar), actor distinto en la resolución (ACT-COORD), ciclo y UAT
distintos, implementados en Slices separados.

## Numeración

`US-REP-032..033`, `ACC-REP-049..051`, `FR-REP-112..119`, `TR-REP-112..119`,
`TASK-REP-195..197` (más `TASK-REP-045` reutilizada), `CODE-REP-195..206`,
`TEST-REP-393..424`, `UAT-REP-033..034` (`PENDING`).

## Reutilización de `TASK-REP-045`

Existía `NOT_IMPLEMENTED` en `hp-rep-001.yaml`; pasa a `DONE` con una `note` y
se redeclara en `exc-rep-002.yaml` (mismo id, type y name) para enlazarla con
los TR nuevos (`TR-REP-112/113/114/117`). En `hp-rep-001.yaml` se enlaza con
`TR-REP-027` (`habilitar_orden`, **ampliado**: acepta 090 Sí o 130 con override
válido). Los TR específicos del override están en `exc-rep-002.yaml`.

## User Story → Feature

| US | Feature | Resumen |
|---|---|---|
| `US-REP-032` | `FEAT-REP-003` | El Coordinador fuerza un Detalle bloqueado con motivo |
| `US-REP-033` | `FEAT-REP-003` | El Detalle forzado se reserva y consume aunque falte stock |

## System Action → FR → TR

| ACC | FR | TR |
|---|---|---|
| `ACC-REP-049` override (110 Sí → 130 → 140) | `FR-REP-112..116` | `TR-REP-112`, `113`, `114`, `117` |
| `ACC-REP-050` publicar `OVERRIDE_RECURSOS` | `FR-REP-119` | `TR-REP-118`, `119` |
| `ACC-REP-051` reservar y consumir con override | `FR-REP-117`, `118` | `TR-REP-113`, `115`, `116` |

## Decisiones que el grafo no expresa por sí solo

- 185 y 210 se declaran como nodos `in_scenario: false` (consecuencia downstream
  del override), no como nodos de EXC-REP-002.
- EXC-REP-003 (PROC-REP-186) sigue `NOT_IMPLEMENTED` y no se traza aquí.
- El override se deriva del historial: no hay `FR/TR` de un flag en el Detalle.
