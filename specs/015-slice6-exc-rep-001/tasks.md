---
description: "Tareas de EXC-REP-001 (recursos insuficientes, en espera)"
---

# Tasks: EXC-REP-001

**Input**: `specs/015-slice6-exc-rep-001/spec.md`, `plan.md`

Se **reutilizan** `TASK-REP-043`, `044`, `046`, `047` y `048` de
`hp-rep-001.yaml` (pendientes desde HP-REP-001); pasan a `DONE`.
`TASK-REP-045` (override, PROC-REP-110 Sí / 130) **sigue `NOT_IMPLEMENTED`**:
es EXC-REP-002. Tampoco se toca PROC-REP-186 (reserva fallida).

- [x] **TASK-REP-043** Rama "Ninguno trabajable" de PROC-REP-090 y agregado `PENDIENTE_RECURSOS` (derivado por el resolver, no un estado de workflow).
      → `app/backend/app/services/reparaciones.py`, `app/backend/app/application/ingreso.py`
- [x] **TASK-REP-044** PROC-REP-100 por Detalle con sus faltantes.
      → `app/backend/app/services/reparaciones.py`
- [x] **TASK-REP-046** PROC-REP-120 y su circuito de espera/revalidación.
      → `app/backend/app/services/recursos.py`, `app/backend/app/application/recursos.py`, `app/backend/app/api/ordenes.py`
- [x] **TASK-REP-047** Condición de bloqueo del Detalle expuesta (el modelo ya existía; se publica en `DetalleOut` y se muestra).
      → `app/backend/app/api/schemas.py`, `app/frontend/src/**`
- [x] **TASK-REP-048** Multi-Detalle con factibilidad parcial (BR-REP-002: basta uno trabajable).
      → `tests/test_exc_rep_001.py`, `tests/test_api_exc_rep_001.py`
- [x] **TASK-REP-192** `ESPERAR_RECURSOS` / `REVALIDAR_RECURSOS` en `acciones_disponibles`.
      → `app/backend/app/application/acciones.py`
- [x] **TASK-REP-193** Frontend: acciones de recursos y condición del Detalle.
      → `app/frontend/src/**`
- [x] **TASK-REP-194** Ruta de progreso con 100/110/120 por evidencia.
      → `app/backend/app/application/progreso.py`
- [ ] **TASK-REP-045** Override — `NOT_IMPLEMENTED` (EXC-REP-002).
