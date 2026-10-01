---
description: "Tareas de EXC-REP-002 (override de recursos)"
---

# Tasks: EXC-REP-002

**Input**: `specs/016-slice7-exc-rep-002/spec.md`, `plan.md`

Se **reutiliza** `TASK-REP-045` de `hp-rep-001.yaml` (pendiente desde
HP-REP-001); pasa a `DONE`.

- [x] **TASK-REP-045** PROC-REP-110 (Sí) + PROC-REP-130: override justificado de un Detalle bloqueado (BR-REP-003) con usuario, fecha, Detalle, validación ignorada y motivo; gate de 140 desde 130; comando y endpoint.
      → `app/backend/app/services/recursos.py`, `app/backend/app/services/ordenes.py`, `app/backend/app/application/recursos.py`, `app/backend/app/api/ordenes.py`
- [x] **TASK-REP-195** Reserva (185) y consumo (210) con override: disponible y stock físico negativos solo para el Detalle forzado.
      → `app/backend/app/services/ejecuciones.py`, `app/backend/app/services/inventario_global.py`, `app/backend/app/domain/models/catalogos.py`
- [x] **TASK-REP-196** `OVERRIDE_RECURSOS` en `acciones_disponibles` y nodo 130 en el progreso.
      → `app/backend/app/application/acciones.py`, `app/backend/app/application/progreso.py`
- [x] **TASK-REP-197** Frontend: acción y formulario de motivo.
      → `app/frontend/src/**`
