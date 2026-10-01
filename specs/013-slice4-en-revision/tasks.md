---
description: "Tareas de VAR-REP-001 + VAR-REP-002 (EN_REVISION)"
---

# Tasks: VAR-REP-001 + VAR-REP-002

**Input**: `specs/013-slice4-en-revision/spec.md`, `plan.md`

- [x] **TASK-REP-179** [US-REP-026] `OrdenReparacion.detalles_origen_ids` (default `[]`), completado por la garantía directa y la garantía en revisión.
      → `app/backend/app/domain/models/orden_reparacion.py`, `app/backend/app/services/ordenes.py`
- [x] **TASK-REP-180** [US-REP-023] `marcar_orden_en_revision` (045 No → 055) y `habilitar_orden` desde `EN_REVISION`.
      → `app/backend/app/services/ordenes.py`
- [x] **TASK-REP-181** [US-REP-023] `enviar_a_revision` + `POST /send-to-review`.
      → `app/backend/app/application/ingreso.py`, `app/backend/app/api/ordenes.py`
- [x] **TASK-REP-182** [US-REP-024] `services.revisiones` + `application.revision.realizar_revision` + `POST /technical-review`.
      → `app/backend/app/services/revisiones.py`, `app/backend/app/application/revision.py`
- [x] **TASK-REP-183** [US-REP-025] `definir_reparacion_detail_luego_revision` con helper de snapshot compartido con PROC-REP-070.
      → `app/backend/app/services/reparaciones.py`
- [x] **TASK-REP-184** [US-REP-025] `definir_reparacion_desde_revision` + `POST /review/details`; separar `_validar_y_habilitar` de `_finalizar_definicion`.
      → `app/backend/app/application/ingreso.py`
- [x] **TASK-REP-185** [US-REP-026] `crear_garantia_rma_en_revision` + `POST /warranty-rma/review`.
      → `app/backend/app/application/ingreso.py`
- [x] **TASK-REP-186** [US-REP-023] Acciones del circuito de revisión en `acciones_disponibles`.
      → `app/backend/app/application/acciones.py`
- [x] **TASK-REP-187** [US-REP-023] Ruta de progreso de revisión derivada.
      → `app/backend/app/application/progreso.py`
- [x] **TASK-REP-188** [US-REP-024] Frontend del circuito de revisión.
      → `app/frontend/src/**`
