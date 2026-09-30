---
description: "Tareas de HP-REP-002 (Equipo RT Interno)"
---

# Tasks: HP-REP-002 — Equipo RT Interno

**Input**: Design documents from `/specs/011-slice2-hp-rep-002/`

**Prerequisites**: `spec.md`, `plan.md`, y `specs/009-mvp2-foundation/`
(`PoliticaOrigen`, resolver BR-REP-012 generalizado)

> Orden real de ejecucion: implementacion inicial de HP-REP-002 completo
> (Fases 1-6), seguida de una revision funcional que identifico tres
> correcciones puntuales (Fase 7) y de una verificacion puntual de que
> esas correcciones no afectaron por error la semantica de actor humano
> de PROC-REP-270 (Fase 8), antes de cerrar el slice.

## Phase 1: Dominio (aditivo, sin romper JSON existente)

- [x] **TASK-REP-158** [US-REP-017] Ampliar `OrdenReparacion` con
      `cliente: Cliente | None = None` y el campo `referencia_rt: str |
      None`, preservando compatibilidad con el JSON persistido antes de
      este slice.
      → `app/backend/app/domain/models/orden_reparacion.py`
      → test: `tests/test_repositories_json.py::test_una_orden_hp1_anterior_a_referencia_rt_sigue_cargando`

## Phase 2: Ingreso RT (sin Cliente, sin comprobante)

- [x] **TASK-REP-159** [US-REP-017] Implementar `crear_orden_rt_interno`
      (PROC-REP-010 -> 020 -> 040), el comando de aplicacion
      `crear_orden_rt` y el endpoint `POST /api/orders/rt-interno`.
      → `app/backend/app/services/ordenes.py::crear_orden_rt_interno`,
        `app/backend/app/application/ingreso.py::crear_orden_rt`,
        `app/backend/app/api/ordenes.py`
      → test: `tests/test_hp_rep_002.py::test_orden_rt_nace_sin_cliente_con_referencia_de_contexto`,
        `tests/test_api_hp_rep_002.py::test_crear_orden_rt_no_pide_ni_devuelve_cliente`
- [x] **TASK-REP-160** [US-REP-017] Reescribir `generar_comprobante_recepcion`
      para bifurcar segun `PoliticaOrigen.requiere_comprobante_recepcion`
      en vez de un chequeo de Origen hardcodeado a `CLIENTE_EXTERNO`.
      → `app/backend/app/services/documentos.py::generar_comprobante_recepcion`
      → test: `tests/test_hp_rep_002.py::test_ingreso_rt_no_pasa_por_registro_de_cliente_ni_comprobante`

**Checkpoint**: Orden `RT_INTERNO` se crea sin Cliente y llega a
`HABILITADA` sin comprobante de recepcion, reutilizando factibilidad y
habilitacion sin cambios.

## Phase 3: Acciones y progreso generalizados

- [x] **TASK-REP-161** [US-REP-018] Extender `acciones_disponibles` con
      `ACCION_INFORMAR_RT` / `ACCION_DEVOLVER_RT` gobernadas por
      `politica_de(...).requiere_informar_rt` y el corte de acciones
      cuando `current_process == "EVT-REP-999"`.
      → `app/backend/app/application/acciones.py::acciones_disponibles`
      → test: `tests/test_hp_rep_002.py::test_rt_interno_no_ofrece_registrar_pago_ni_notificar_ni_entregar`,
        `::test_devolver_rt_esta_disponible_recien_despues_de_informar`,
        `::test_orden_terminada_no_ofrece_ninguna_accion`
- [x] **TASK-REP-164** [US-REP-017] Declarar `_RUTA_RT_INTERNO` en
      `application/progreso.py` como ruta de referencia propia para
      Ordenes `RT_INTERNO`.
      → `app/backend/app/application/progreso.py::_RUTA_RT_INTERNO`

## Phase 4: Cierre RT (informar + devolver)

- [x] **TASK-REP-162** [US-REP-019] Implementar `informar_resultado_rt`
      (PROC-REP-250 "No" -> PROC-REP-290), el comando de aplicacion
      `informar_rt` y el endpoint `POST /api/orders/{id}/inform-rt`.
      → `app/backend/app/services/ordenes.py::informar_resultado_rt`,
        `app/backend/app/application/cierre.py::informar_rt`
      → test: `tests/test_hp_rep_002.py::test_informar_rt_registra_250_no_y_290`
- [x] **TASK-REP-163** [US-REP-020] Implementar `devolver_equipo_rt`
      (PROC-REP-270 reutilizado, sin `ENTREGADA`), el comando de
      aplicacion `devolver_rt` y el endpoint `POST /api/orders/{id}/return-rt`.
      → `app/backend/app/services/ordenes.py::devolver_equipo_rt`,
        `app/backend/app/application/cierre.py::devolver_rt`
      → test: `tests/test_hp_rep_002.py::test_devolucion_rt_llega_a_evt_999_sin_marcar_entregada`

**Checkpoint**: HP-REP-002 completo por servicios (creacion ->
definicion -> cola -> toma -> ejecucion -> control -> informar RT ->
devolver) llega a `EVT-REP-999`.

## Phase 5: Frontend minimo

- [x] **TASK-REP-165** Adaptar el frontend: formulario de alta
      `RT_INTERNO`, acciones `INFORMAR_RT`/`DEVOLVER_RT`, render de
      Cliente nullable y de `condicion_comercial`.
      → `app/frontend/src/types/api.ts`, `app/frontend/src/api/ordenes.ts`,
        `app/frontend/src/features/ordenes-reparacion/*.tsx`
      → verificado con `tsc --noEmit` + `vite build`

## Phase 6: E2E por HTTP

- [x] Recorrer HP-REP-002 completo por HTTP en un unico test, y
      confirmar que `CLIENTE_EXTERNO` no se degrada al convivir con
      `RT_INTERNO` en el mismo backend.
      → `tests/test_api_hp_rep_002.py::test_hp_rep_002_end_to_end_por_http`,
        `::test_cliente_externo_sigue_funcionando_igual_junto_a_rt_interno`

**Checkpoint**: `pytest` completo en verde: 335 tests (316 baseline +
19 de HP-REP-002).

## Phase 7: Correcciones de revision (post-implementacion inicial)

Tres puntos detectados en la revision funcional del slice, antes de
cerrarlo.

- [x] **TASK-REP-166** [US-REP-018] Rechazar `registrar_pago` en el
      service cuando `politica_de(orden.origen).condicion_comercial` no
      es `COBRABLE` (BR-REP-016/017): la omision en `acciones_disponibles`
      no alcanzaba -el service seguia siendo invocable directo-.
      → `app/backend/app/services/pagos.py::registrar_pago`
      → test: `tests/test_hp_rep_002.py::test_registrar_pago_rechaza_una_orden_rt_interno`,
        `::test_registrar_pago_sigue_funcionando_en_cliente_externo`,
        `tests/test_api_hp_rep_002.py::test_registrar_pago_rechaza_rt_interno_con_admin_activo_por_http`,
        `::test_registrar_pago_cliente_externo_no_se_ve_afectado`
- [x] Modelar PROC-REP-290 fielmente como `actor: ACT-SYSTEM`: quitar
      `usuario_id`/`Usuario` de `informar_resultado_rt`, del comando
      `informar_rt` y del endpoint (ya no recibe body); el historial de
      PROC-REP-290 queda con `usuario_id: null`. Agregar
      `AccionDisponible.requiere_actor: bool` (y su espejo en
      `AccionOut`) para distinguir esto de "rol humano sin definir"
      (`roles: []` con `requiere_actor: true`, como Registrar Pago antes
      de BR-REP-017) en vez de sobrecargar `roles: ()`.
      → `app/backend/app/services/ordenes.py::informar_resultado_rt`,
        `app/backend/app/application/cierre.py::informar_rt`,
        `app/backend/app/api/ordenes.py::post_informar_rt`,
        `app/backend/app/application/acciones.py::AccionDisponible`,
        `app/backend/app/api/schemas.py::AccionOut`
      → test: `tests/test_hp_rep_002.py::test_informar_rt_no_registra_ningun_actor_humano`,
        `::test_informar_rt_se_publica_como_accion_de_sistema_sin_actor`,
        `tests/test_api_hp_rep_002.py::test_hp_rep_002_end_to_end_por_http`
        (assertions de `requiere_actor` y `usuario_id: null`)
- [x] Confirmar con test que el snapshot comercial de una Orden RT
      ($80000 de ejemplo) no se presenta como deuda pendiente del
      cliente: `ResumenComercialOut.condicion_comercial` ya lo
      distinguia, asi que no hizo falta ningun cambio de representacion,
      solo demostrarlo.
      → sin cambios de codigo (verificacion)
      → test: `tests/test_hp_rep_002.py::test_representacion_comercial_rt_no_es_deuda_pendiente`,
        `tests/test_api_hp_rep_002.py::test_representacion_comercial_rt_no_es_deuda_pendiente_por_http`
- [x] Confirmar con test que `DEVOLVER_RT` no puede ejecutarse antes de
      PROC-REP-290 (ya lo exigia `devolver_equipo_rt`; se agrego el
      test negativo explicito).
      → test: `tests/test_hp_rep_002.py::test_devolver_rt_no_puede_ejecutarse_antes_de_informar`,
        `tests/test_api_hp_rep_002.py::test_hp_rep_002_end_to_end_por_http`
        (409 antes de informar)

**Checkpoint**: `pytest` completo en verde: 344 tests (316 baseline +
28 de HP-REP-002, incluida la Fase 7).

## Phase 8: Verificacion de actores del cierre (PROC-REP-270 vs. 290)

Punto de revision adicional: confirmar que la correccion de PROC-REP-290
(Fase 7) no se habia aplicado por error a PROC-REP-270, que -a
diferencia de 290- SI es un nodo con actor humano
(`actor: ACT-ADMIN`, `actores_alternativos: [ACT-RECEP]`). El codigo ya
era correcto (`devolver_equipo_rt` siempre exigio `Usuario` y
`ROLES_ENTREGA`); faltaba la cobertura de test explicita.

- [x] Agregar tests que demuestren, a nivel service y HTTP, que
      `devolver_equipo_rt`/`POST /{id}/return-rt`: acepta ADMINISTRADOR
      y RECEPCION registrando su `usuario_id` real en PROC-REP-270,
      rechaza TECNICO, y que tras la devolucion `current_process ==
      EVT-REP-999` sin `estado_workflow == ENTREGADA`.
      → sin cambios de codigo (verificacion; `devolver_equipo_rt` ya
        era correcto)
      → test: `tests/test_hp_rep_002.py::test_devolver_rt_con_administrador_registra_su_usuario_id`,
        `::test_devolver_rt_con_recepcion_registra_su_usuario_id`,
        `::test_devolver_rt_rechaza_tecnico`,
        `tests/test_api_hp_rep_002.py::test_devolver_rt_rechaza_tecnico_por_http`,
        `::test_devolver_rt_con_recepcion_registra_su_usuario_por_http`

**Checkpoint final**: `pytest` completo en verde: 349 tests (316
baseline + 33 de HP-REP-002, incluidas las Fases 7 y 8). `ruff check`,
`npm run validate:all`, `tsc --noEmit` y `vite build` limpios.

## Dependencies & Execution Order

```text
(specs/009-mvp2-foundation: PoliticaOrigen, resolver BR-REP-012)
  └── Fase 1 (dominio: cliente Optional, referencia_rt)
        └── Fase 2 (ingreso RT: crear_orden_rt_interno, comprobante por politica)
              └── Fase 3 (acciones/progreso generalizados)
                    └── Fase 4 (cierre RT: informar + devolver)
                          └── Fase 5 (frontend)
                                └── Fase 6 (E2E HTTP)
                                      └── Fase 7 (correcciones de revision)
                                            └── Fase 8 (verificacion actores 270 vs 290)
```

## Estado real de implementacion

| Fase | Tareas | `[x]` con evidencia codigo+test | `[ ]` |
|---|---|---|---|
| Dominio | 1 | 1 | 0 |
| Ingreso RT | 2 | 2 | 0 |
| Acciones/progreso | 2 | 2 | 0 |
| Cierre RT | 2 | 2 | 0 |
| Frontend | 1 | 1 | 0 |
| E2E HTTP | 1 | 1 | 0 |
| Correcciones de revision | 4 | 4 | 0 |
| Verificacion actores 270 vs 290 | 1 | 1 | 0 |
| **Total** | **14** | **14** | **0** |
