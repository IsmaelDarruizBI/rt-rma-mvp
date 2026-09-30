---
description: "Tareas de Slice 0 (MVP v2 - Foundation)"
---

# Tasks: MVP v2 — Slice 0 (Foundation)

**Input**: Design documents from `/specs/009-mvp2-foundation/`

**Prerequisites**: `spec.md`, `plan.md`, y los slices de
`FEAT-REP-001`, `FEAT-REP-005` y `FEAT-REP-007`

> Orden real de ejecucion (verificado con `pytest` en cada paso, ver
> §8 de `plan.md` y el brief de la iteracion): caracterizar antes de
> refactorizar, confirmar PASS con la implementacion vieja, refactorizar,
> confirmar PASS de nuevo con la unica excepcion deliberada de
> BR-REP-017.

## Phase 1: Caracterizacion (antes de tocar `happy_path.py`)

- [x] **TASK-REP-156a** Agregar `tests/test_caracterizacion_hp1.py`:
      congela `progreso()`/`acciones_disponibles()` para los 10 estados
      principales de HP-REP-001, importando desde `app.application` (el
      paquete, no el modulo interno).
      → Corrido y confirmado PASS contra la implementacion sin tocar
        (293 tests, baseline 283 + 10 caracterizacion) antes de
        refactorizar nada.

## Phase 2: Dominio (aditivo, sin romper JSON existente)

- [x] **TASK-REP-151** [US-REP-018] Extender `OrigenOrden` con
      `RT_INTERNO` y `RMA_GARANTIA_REPARACION`, y `EstadoWorkflow` con
      `EN_REVISION`, de forma aditiva y sin nuevo comando de creacion.
      → `app/backend/app/domain/models/enums.py`
      → test: `tests/test_politica_origen.py::test_los_tres_origenes_del_enum_tienen_politica_declarada`
- [x] **TASK-REP-154** [US-REP-018] Agregar `CondicionReparacionDetail`
      y el campo `condicion` a `ReparacionDetail`, con default
      `SIN_BLOQUEO` compatible con el JSON persistido antes de este
      slice.
      → `app/backend/app/domain/models/enums.py`,
        `app/backend/app/domain/models/reparacion.py`
      → test: `tests/test_hp_rep_001_persistido.py::test_un_json_anterior_a_slice_0_sigue_cargando`
- [x] **TASK-REP-152** [US-REP-018] Implementar `domain/politicas.py`
      con `PoliticaOrigen` (frozen dataclass) y `politica_de()` para los
      tres origenes de MVP v2.
      → `app/backend/app/domain/politicas.py`
      → test: `tests/test_politica_origen.py`

**Checkpoint**: `pytest` sigue en 314 (293 + 21 nuevos de esta fase y
las siguientes se acumulan; ver el numero final en la Fase 6).

## Phase 3: Resolver BR-REP-012 (funcion pura)

- [x] **TASK-REP-153** [US-REP-018] Implementar `resolver_situacion_orden`
      puro (BR-REP-012 completo: 8 resultados, sin excepciones para
      ningun resultado de negocio legitimo) en `services/resolucion.py`.
      → `app/backend/app/services/resolucion.py::resolver_situacion_orden`
      → test: `tests/test_resolucion_orden.py` (13 tests, matriz completa)
- [x] **TASK-REP-155** [US-REP-018] Refactorizar `evaluar_situacion_orden`
      para delegar la clasificacion en el resolver y cerrar la toma
      activa solo en resultados terminales (`COMPLETA`,
      `TODO_CANCELADO`), eliminando el riesgo de persistencia parcial
      de `completar_ejecucion`.
      → `app/backend/app/services/ordenes.py::evaluar_situacion_orden`
      → test: `tests/test_completar_ejecucion_consistencia.py::test_completar_un_detalle_con_otro_pendiente_no_lanza`

**Checkpoint**: `evaluar_situacion_orden` clasifica los 8 resultados;
HP-REP-001 sigue llegando a `COMPLETA` exactamente igual.

## Phase 4: Navegacion generalizada (acciones + progreso)

- [x] **TASK-REP-156** [US-REP-018] Separar `acciones_disponibles` y
      `progreso` de `application/happy_path.py` hacia
      `application/acciones.py` y `application/progreso.py`,
      consultando `politica_de(orden.origen)` en vez de un condicional
      fijo por `CLIENTE_EXTERNO`. `happy_path.py` queda como fachada de
      compatibilidad (re-exporta los mismos nombres).
      → `app/backend/app/application/acciones.py`,
        `app/backend/app/application/progreso.py`
      → test: `tests/test_caracterizacion_hp1.py` (debe seguir en
        verde salvo `REGISTRAR_PAGO.roles`)
- [x] **TASK-REP-156b** Renombrar `PasoHappyPath` a `PasoProgreso` en
      `app.application` y `api/schemas.py` (aditivo: el JSON de salida
      de la API no cambia de forma, solo el nombre del tipo Python).
      → `app/backend/app/api/schemas.py`

**Checkpoint**: `tests/test_caracterizacion_hp1.py` en verde salvo
`REGISTRAR_PAGO` (paso esperado, ver Fase 5).

## Phase 5: Fix BR-REP-017 (Registrar Pago)

- [x] **TASK-REP-157** [US-REP-017] Centralizar `ROLES_PAGO` en
      `services/pagos.py` (`ADMINISTRADOR`, `RECEPCION`,
      `COORDINADOR_RMA`) y exigirlo tanto en `registrar_pago`
      (`validar_alguno_de`) como en la accion `REGISTRAR_PAGO`
      publicada por `acciones_disponibles` -una sola fuente, consumida
      por las dos puntas-.
      → `app/backend/app/services/pagos.py::ROLES_PAGO`,
        `app/backend/app/application/acciones.py`
      → test: `tests/test_services_autorizacion.py::test_registrar_pago_permite_administrador_recepcion_y_coordinador`,
        `::test_registrar_pago_rechaza_al_tecnico`,
        `tests/test_api_reconcile.py::test_un_tecnico_no_puede_registrar_un_pago_por_http`
- [x] **TASK-REP-123** (actualizada, ver nota en `traceability.md`)
      Definir e implementar que rol puede registrar un pago.
      → Resuelto por `ROLES_PAGO` (arriba).
- [x] Actualizar `tests/test_caracterizacion_hp1.py`: las aserciones de
      `REGISTRAR_PAGO` pasan de `roles=()` a `ROLES_PAGO` -unica
      excepcion deliberada del caracterizado-.
- [x] Actualizar `tests/test_api_reconcile.py::test_el_anticipo_habilita_la_accion_de_pago_temprano`:
      `pago["roles"]` pasa de `[]` a
      `["ADMINISTRADOR", "RECEPCION", "COORDINADOR_RMA"]`.
- [x] Renombrar y dividir `tests/test_services_autorizacion.py::test_registrar_pago_no_exige_un_rol_concreto`
      (parametrizado con TECNICO esperando exito, el bug) en
      `test_registrar_pago_permite_administrador_recepcion_y_coordinador`
      (sin TECNICO) + `test_registrar_pago_rechaza_al_tecnico` (nuevo).

**Checkpoint**: `pytest` completo en verde (314 tests: 283 baseline +
31 nuevos). Unico cambio de expectativa: los tres puntos de arriba,
documentados y deliberados.

## Phase 6: Frontend minimo

- [x] Desacoplar visualmente `DetalleOrden.tsx:ProgresoHappyPath` de
      HP-REP-001: titulo `"Progreso HP-REP-001"` -> `"Progreso de la
      orden"`. El frontend no necesita ningun cambio de logica: ya
      consume `accion.roles` sin condicionales de rol hardcodeados, asi
      que el fix de BR-REP-017 se propaga solo.
      → `app/frontend/src/features/ordenes-reparacion/DetalleOrden.tsx`
      → verificado con `tsc --noEmit` + `vite build`

## Phase 7: Fuera de este slice — NO implementado

Corresponden a los slices funcionales siguientes de MVP v2.

- [ ] **TASK-REP-013** Implementar el origen `RT_INTERNO` operativo
      (PROC-REP-020, HP-REP-002).
- [ ] **TASK-REP-015** Implementar el origen `RMA_GARANTIA_REPARACION`
      operativo (PROC-REP-035, HP-REP-003).
- [ ] Implementar el circuito EN_REVISION (PROC-REP-055/065/068/075,
      VAR-REP-001/002).
- [ ] **TASK-REP-086** Implementar PROC-REP-186 (reserva fallida
      persistida, EXC-REP-003).
- [ ] Implementar los comandos REVALIDAR y OVERRIDE de recursos
      (EXC-REP-001/002).
- [ ] **TASK-REP-087** Implementar el resultado Interrumpido de
      PROC-REP-200 (VAR-REP-003).
- [ ] **TASK-REP-101** Implementar PROC-REP-235 (control rechazado,
      EXC-REP-005).
- [ ] Implementar PROC-REP-125/126/127 (REQUIERE_REVISION operativo,
      EXC-REP-004).
- [ ] Multi-Detalle operativo por API (`application.ingreso.definir_reparacion`
      sigue aceptando un unico Detalle por llamada).

## Dependencies & Execution Order

```text
(FEAT-REP-001: crear Orden)
(FEAT-REP-005: evaluar_situacion_orden, inventario)
(FEAT-REP-007: Registrar Pago)
  └── Fase 1 (caracterizacion)
        └── Fase 2 (dominio: enums, condicion, politica)
              └── Fase 3 (resolver puro + evaluar_situacion_orden)
                    └── Fase 4 (acciones/progreso generalizados)
                          └── Fase 5 (fix BR-REP-017)
                                └── Fase 6 (frontend)
```

## Estado real de implementacion

| Fase | Tareas | `[x]` con evidencia codigo+test | `[ ]` |
|---|---|---|---|
| Caracterizacion | 1 | 1 | 0 |
| Dominio | 3 | 3 | 0 |
| Resolver | 2 | 2 | 0 |
| Navegacion | 2 | 2 | 0 |
| Fix BR-REP-017 | 6 | 6 | 0 |
| Frontend | 1 | 1 | 0 |
| Fuera del slice | 9 | 0 | 9 |
| **Total** | **24** | **15** | **9** |
