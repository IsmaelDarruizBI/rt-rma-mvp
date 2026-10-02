---
description: "Tareas de EXC-REP-003 (reserva de insumos fallida)"
---

# Tasks: EXC-REP-003

**Input**: `specs/017-slice8-exc-rep-003/spec.md`, `plan.md`

Se **reutiliza** `TASK-REP-086` de `hp-rep-001.yaml` (pendiente desde
HP-REP-001); pasa a `DONE`.

- [x] **TASK-REP-086** PROC-REP-185 "Reserva fallida" + PROC-REP-186: la reserva insuficiente sin override del Detalle es un resultado persistido (Detalle `BLOQUEADO_POR_RECURSOS`, sin Ejecución ni reservas ni cambios de stock), con 211 evaluado y, si corresponde, 211 → 120; una sola escritura en la sección crítica.
      → `app/backend/app/services/ejecuciones.py`, `app/backend/app/application/taller.py`
- [x] **TASK-REP-198** Helper compartido de faltantes de disponibilidad por Detalle (factibilidad y reserva).
      → `app/backend/app/services/inventario.py`, `app/backend/app/services/reparaciones.py`
- [x] **TASK-REP-199** `habilitar_orden` acepta `EN_COLA` tras el circuito 186 → 211 → 120 sin relajar el gate (090 Sí o 130 válido).
      → `app/backend/app/services/ordenes.py`
- [x] **TASK-REP-200** Progreso: 186 tras 185 y 120 tras 211 por evidencia del historial.
      → `app/backend/app/application/progreso.py`
- [x] Actualizar el comentario de `_ORIGENES_DE_LA_DECISION_212` (186 → 211 → 212 → 181).
      → `app/backend/app/services/tomas.py`
- [x] Actualizar los tests que fijaban 409 por reserva insuficiente (HP-REP-001 y EXC-REP-002) y los de `habilitar_orden` por hito.
