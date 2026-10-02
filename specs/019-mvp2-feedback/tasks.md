---
description: "Tareas del feedback de pruebas MVP v2"
---

# Tasks: Feedback MVP v2

**Input**: `specs/019-mvp2-feedback/spec.md`, `plan.md`

**Estado**: implementado. Todas las Tasks quedan `DONE`.

Se **reutilizan** `TASK-REP-028` y `TASK-REP-138` de `hp-rep-001.yaml`
(pendientes desde HP-REP-001; pasan a `DONE`). IDs nuevos verificados libres:
`TASK-REP-209..214`.

- [x] **TASK-REP-028** PROC-REP-069 (SIN_REPARACION, BR-REP-010): 068 No → 069, motivo obligatorio, Subtotal 0, sin estado nuevo. *(existente, reutilizada)*
- [x] **TASK-REP-138** Comprobante final de una Orden SIN_REPARACION: sin garantía de reparación; cierre por Origen con `lista_para_cierre`. *(existente, reutilizada)*
- [x] **TASK-REP-209** Separar agregar Detalle de finalizar la definición: comando, endpoint y acción `FINALIZAR_DEFINICION`, sin el flag `finalizar_definicion`.
- [x] **TASK-REP-210** Frontend: formulario SIN_REPARACION y etiqueta derivada.
- [x] **TASK-REP-211** Garantía RMA canónica: un único comando, endpoint y acción para 1..N Detalles origen con revisión obligatoria; sin bypass ni endpoints por Detalle.
- [x] **TASK-REP-212** Detalles origen por nombre (consulta + DTO) y frontend: casillas de selección y selector de origen luego de la revisión.
- [x] **TASK-REP-213** Override como capacidad transversal por Detalle (ACC-REP-049): autorizar con factibilidad parcial sin reiniciar; 110/130 solo desde 100.
- [x] **TASK-REP-214** Frontend: `FormularioEjecucion` con modo explícito y Completar \| Interrumpir lado a lado (apiladas en mobile).

Fuera de las Tasks: el paralelismo de Detalles/Ejecuciones queda como
**PENDING BUSINESS DECISION** (ver `spec.md`); no se implementa.
