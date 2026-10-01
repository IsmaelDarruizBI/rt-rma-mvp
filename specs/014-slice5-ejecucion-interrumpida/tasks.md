---
description: "Tareas de VAR-REP-003 (Ejecución interrumpida)"
---

# Tasks: VAR-REP-003 — Ejecución interrumpida

**Input**: `specs/014-slice5-ejecucion-interrumpida/spec.md`, `plan.md`

Se **reutilizan** `TASK-REP-087` y `TASK-REP-091` de `hp-rep-001.yaml`
(pendientes desde HP-REP-001); pasan a `DONE`. No se crearon Tasks
duplicadas.

- [x] **TASK-REP-087** [US-REP-027] Resultado `Interrumpido` de PROC-REP-200 (BR-REP-004): `EstadoEjecucion.INTERRUMPIDO`, `registrar_ejecucion_interrumpida`, `interrumpir_ejecucion`, endpoint `/interrupt`.
      → `app/backend/app/domain/models/enums.py`, `app/backend/app/services/ejecuciones.py`, `app/backend/app/application/taller.py`, `app/backend/app/api/ordenes.py`
- [x] **TASK-REP-091** [US-REP-028] Ejercitar varias Ejecuciones históricas sobre el mismo Detalle (mismo y otro técnico).
      → `tests/test_var_rep_003.py`, `tests/test_api_var_rep_003.py`
- [x] **TASK-REP-189** [US-REP-027] Gate de PROC-REP-210: solo se concilia una Ejecución terminada.
      → `app/backend/app/services/inventario.py`
- [x] **TASK-REP-190** [US-REP-027] `INTERRUMPIR_EJECUCION` en `acciones_disponibles`.
      → `app/backend/app/application/acciones.py`
- [x] **TASK-REP-191** [US-REP-027] Frontend: estado, cliente, formulario y listado de Ejecuciones.
      → `app/frontend/src/**`
- [ ] **TASK-REP-089** / **TASK-REP-090** DESPERDICIO — `NOT_IMPLEMENTED`, fuera de alcance.
