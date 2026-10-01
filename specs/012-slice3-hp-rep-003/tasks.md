---
description: "Tareas de HP-REP-003 (Garantía de reparación RMA)"
---

# Tasks: HP-REP-003 — Garantía de reparación RMA

**Input**: `specs/012-slice3-hp-rep-003/spec.md`, `plan.md`

- [x] **TASK-REP-171** [US-REP-021] Agregar `orden_origen_id` a
      `OrdenReparacion` y `detalle_origen_id` a `ReparacionDetail`, con
      default `None`.
      → `app/backend/app/domain/models/orden_reparacion.py`,
      `app/backend/app/domain/models/reparacion.py`
      → test: `test_orden_persistida_antes_de_slice3_sigue_cargando`
- [x] **TASK-REP-172** [US-REP-021] `services.ordenes.crear_orden_garantia_rma`
      con validaciones (RECEPCION, origen `ENTREGADA`, Detalle existente,
      Cliente presente) e historial `PROC-REP-035` y `PROC-REP-040`.
      → `app/backend/app/services/ordenes.py`
- [x] **TASK-REP-173** [US-REP-021] `application.ingreso.crear_garantia_rma`;
      extraer `_finalizar_definicion` (050 → 060 → 080 → 090 → 140) y
      reutilizarlo desde `definir_reparacion`.
      → `app/backend/app/application/ingreso.py`
- [x] **TASK-REP-174** [US-REP-021] Endpoint `POST .../warranty-rma` y campos
      de origen en los DTOs.
      → `app/backend/app/api/ordenes.py`, `app/backend/app/api/schemas.py`
- [x] **TASK-REP-175** [US-REP-022] Generalizar `PROC-REP-265`, el
      comprobante final y la entrega por `PoliticaOrigen`
      (`condicion_entrega_cumplida`).
      → `app/backend/app/services/pagos.py`, `documentos.py`, `ordenes.py`,
      `app/backend/app/application/cierre.py`
- [x] **TASK-REP-176** [US-REP-021] Publicar `GENERAR_GARANTIA_RMA` en
      `acciones_disponibles`.
      → `app/backend/app/application/acciones.py`
- [x] **TASK-REP-177** [US-REP-021] Ruta de progreso de HP-REP-003.
      → `app/backend/app/application/progreso.py`
- [x] **TASK-REP-178** [US-REP-021] Frontend: tipos, cliente API, acción y
      referencias de origen.
      → `app/frontend/src/**`
