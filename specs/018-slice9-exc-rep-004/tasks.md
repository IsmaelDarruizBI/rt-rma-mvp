---
description: "Tareas de EXC-REP-004 (redefinicion de un Detalle existente)"
---

# Tasks: EXC-REP-004

**Input**: `specs/018-slice9-exc-rep-004/spec.md`, `plan.md`

**Estado**: implementado (Slice 9). Todas las Tasks quedan `DONE`.

Se **reutiliza** `TASK-REP-030` de `hp-rep-001.yaml` (pendiente desde
HP-REP-001; pasa a `DONE`). IDs nuevos
verificados libres: `TASK-REP-201..208`.

- [x] **TASK-REP-030** Circuito 125 → 126 → 127 con la condición `REQUIERE_DEFINICION` del Detalle: 125 (ACT-SYSTEM), 126 (revisión técnica, TECNICO, sin toma) y 127 (redefinición del mismo Detalle, RECEPCION) encadenando 080. *(existente, reutilizada)*
- [x] **TASK-REP-201** Tercer resultado de PROC-REP-200 "Requiere redefinicion": Ejecución `INTERRUMPIDO`, Detalle `DEFINIDO` + `REQUIERE_DEFINICION`, motivo obligatorio, 210 y 211 reutilizando el cierre de Ejecución existente (service + comando de taller). *(A + B)*
- [x] **TASK-REP-202** 211 `REQUIERE_REVISION` → cierre automático de toma → 125 en `evaluar_situacion_orden`. *(C)*
- [x] **TASK-REP-203** Definición histórica append-only del Detalle y snapshot nuevo en 127 (también con el mismo Tipo), sin tocar `detalle_origen_id`. *(E)*
- [x] **TASK-REP-204** Vigencia del override: `tiene_override_factibilidad` solo cuenta un 130 posterior al último 127 del Detalle. *(F)*
- [x] **TASK-REP-205** Acciones (`REQUIERE_REDEFINICION`, `REVISAR_DETALLE`, `REDEFINIR_DETALLE`), endpoints y frontend. *(H)*
- [x] **TASK-REP-206** Progreso: 200 "Requiere redefinicion", 125, 126 y 127 por evidencia del historial. *(I)*
- [x] **TASK-REP-207** Tests de services y API (Caso A/B, 210, 125, 126/127, histórico, override, 127 → 080, precio/saldo, orígenes, una escritura, regresión). *(J)*
- [x] **TASK-REP-208** Trazabilidad `traceability/exc-rep-004.yaml`, `TASK-REP-030` → DONE y UATs `PENDING`. *(K)*

D (126) y G (127 → 080) se cubren dentro de `TASK-REP-030`: son el circuito que
esa Task ya describe; separarlas sería artificial.
