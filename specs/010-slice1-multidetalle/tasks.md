---
description: "Tareas de Slice 1 (MVP v2 - Multi-Detalle operativo)"
---

# Tasks: MVP v2 — Slice 1 (Multi-Detalle operativo)

**Input**: Design documents from `/specs/010-slice1-multidetalle/`

**Prerequisites**: `spec.md`, `plan.md`, y `specs/009-mvp2-foundation/`
(resolver completo de BR-REP-012, cierre de toma no destructivo)

> Orden real de ejecucion (verificado con `pytest` en cada paso):
> mapear el codigo real antes de tocar nada, extender backend
> function-por-funcion confirmando PASS despues de cada una, agregar el
> E2E de Multi-Detalle, y recien despues frontend + traceability.

## Phase 1: Definir N Detalles antes de habilitar

- [x] **TASK-REP-158** [US-REP-003] Agregar `finalizar_definicion: bool
      = True` a `application.ingreso.definir_reparacion`: siempre
      agrega el Detalle; solo genera el comprobante, valida
      factibilidad y habilita la Orden cuando es verdadero. Extender
      `DefinirReparacionIn`/`post_definir_reparacion` de forma aditiva.
      → `app/backend/app/application/ingreso.py::definir_reparacion`,
        `app/backend/app/api/schemas.py::DefinirReparacionIn`,
        `app/backend/app/api/ordenes.py::post_definir_reparacion`
      → test: `tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`,
        `tests/test_multidetalle.py::test_hp_rep_001_un_solo_detalle_sigue_igual`

**Checkpoint**: una Orden puede recibir 2 Detalles por API; con 1
Detalle y el default, el comportamiento es identico al de antes.

## Phase 2: Seleccion entre varios Detalles trabajables

- [x] **TASK-REP-159** [US-REP-007] Agregar
      `application.acciones.detalles_trabajables` (plural, devuelve
      todos los Detalles DEFINIDO+SIN_BLOQUEO); `acciones_disponibles`
      emite un `AccionDisponible(INICIAR_DETALLE, detalle_id=...)` por
      cada uno en vez de elegir el primero. `detalle_trabajable`
      (singular) se conserva para compatibilidad
      (`application/happy_path.py`,
      `tests/test_acciones_disponibles.py`).
      → `app/backend/app/application/acciones.py::detalles_trabajables`
      → test: `tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`

**Checkpoint**: con 2 Detalles trabajables, la Orden ofrece 2 acciones
`INICIAR_DETALLE`; con 1, sigue ofreciendo exactamente 1 (sin cambio
para HP-REP-001 de un Detalle).

## Phase 3: ¿Iniciar un Detalle de reparacion, o liberar la Orden? (PROC-REP-212/213)

- [x] **TASK-REP-061** (actualizada, ver nota en `traceability.md`)
      Implementar PROC-REP-212 (decision explicita del tecnico: iniciar
      un Detalle o liberar la Orden, BR-REP-018).
      → Resuelto: la decision no persiste estado propio, queda
        representada en el historial. **Correccion de revision**:
        originalmente PROC-REP-212 solo era alcanzable desde
        PROC-REP-211 (continuacion multi-Detalle); se corrigio para que
        se alcance SIEMPRE con toma activa y sin Ejecucion en curso,
        renombrandolo a "¿Iniciar un Detalle de reparacion?" y
        reemplazando el edge `PROC-REP-180 -> PROC-REP-181` (directo)
        por `PROC-REP-180 -> PROC-REP-212` (el edge
        `PROC-REP-212 -> PROC-REP-181 [Si]` ya existia).
      → `app/backend/app/services/tomas.py::seleccionar_detalle`
        (registra `PROC-REP-212 [Si]` antes de `PROC-REP-181`, via el
        helper `_registrar_decision_iniciar_detalle`),
        `business/processes/repair-management-v1.3.yaml` (nombre,
        descripcion, edge), `business/rules/business-rules-v1.3.yaml`
        (`BR-REP-018` reescrita),
        `business/scenarios/repair-management-scenarios-v1.3.yaml`
        (HP-REP-001/002/003: `steps[]` via 212), `traceability/hp-rep-001.yaml`
        (`PROC-REP-212`: nombre + `in_scenario: true`),
        `scripts/test-scenarios.ts` (assertion de
        "mecanica multi-Detalle sigue sin convertirse en Scenario"
        corregida: `212::Si::181` ya no es exclusiva de Multi-Detalle)
      → test: `tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`
        (Casos B y C, con aserciones de historial exactas)
- [x] **TASK-REP-062** (actualizada, ver nota en `traceability.md`)
      Implementar PROC-REP-213 (liberar Orden: cerrar la participacion
      con fecha/hora de fin y devolver la Orden a EN_COLA).
      → `app/backend/app/services/tomas.py::liberar_orden` (registra
        `PROC-REP-212 [No] -> PROC-REP-213 -> PROC-REP-170`, cierra la
        toma, deja `estado_workflow=EN_COLA` y
        `current_process=PROC-REP-170`),
        `app/backend/app/application/taller.py::liberar_orden`,
        `app/backend/app/api/schemas.py::LiberarOrdenIn`,
        `app/backend/app/api/ordenes.py::post_liberar_orden`
      → Accion `LIBERAR_ORDEN` publicada por `acciones_disponibles`
        mientras hay toma activa y ninguna Ejecucion en curso -tanto
        recien tomada como despues de completar un Detalle con otro
        pendiente-.
      → test: `tests/test_multidetalle.py::test_liberar_orden_devuelve_la_orden_a_en_cola`
        (Caso A, con aserciones de historial exactas: `180 -> 212 [No]
        -> 213 -> 170`),
        `tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`

**Checkpoint**: al completar un Detalle con otro pendiente, la toma
sigue activa y el tecnico puede seleccionar el siguiente sin re-tomar
la Orden (historial: `211 [ABIERTA_TRABAJABLE] -> 212 [Si] -> 181`);
`POST /release` la libera explicitamente (historial: `212 [No] -> 213
-> 170`) tanto recien tomada como despues de completar un Detalle, y
la devuelve a EN_COLA.

## Phase 3c: PROC-REP-212 [Si] solo cuando realmente se transita por esa decision (correccion de revision)

- [x] Corregir `seleccionar_detalle` para que registre `PROC-REP-212
      [Si]` SOLO cuando `current_process` esta en
      `{PROC-REP-180, PROC-REP-211}` -ni un Scenario ID ni un flag
      persistido nuevo, solo el estado real de la Orden
      (`_ORIGENES_DE_LA_DECISION_212`)-. Antes registraba `212` en
      toda llamada, acoplando el service a la idea de que TODA
      seleccion implica esa decision; caminos futuros que reentren a
      `PROC-REP-181` sin pasar por 180/211 (incompatibilidad de
      estacion, reserva fallida -no implementados-) no deben inventar
      una segunda 212. Validado que hoy esto no cambia ningun
      resultado observable: en todos los caminos actualmente
      alcanzables, `current_process` ya es 180 o 211 cada vez que
      `seleccionar_detalle` se llama sobre una Orden persistida.
      → `app/backend/app/services/tomas.py::seleccionar_detalle`
      → test: `tests/test_proc212_registro_condicional.py` (2
        funciones: registra 212 desde 180; una reentrada sin volver a
        pasar por 180/211 no duplica 212), mas la cobertura ya
        existente de `test_multidetalle.py` (Casos B/C, sin cambios de
        resultado)

**Checkpoint**: `212 [Si]` se registra exactamente una vez por cada
transito real por la decision; una reentrada a `seleccionar_detalle`
sin volver a pasar por 180/211 no la duplica.

## Phase 4: Control tecnico granular por Detalle

- [x] **TASK-REP-160** [US-REP-010] Agregar `detalle_id: str | None =
      None` a `aprobar_control_tecnico`, preservando la precondicion de
      que PROC-REP-220 solo se alcanza con TODOS los Detalles de la
      Orden COMPLETO (igual que antes de este slice, ahora exigida
      siempre, con o sin `detalle_id`): con id, aprueba solo ese
      Detalle; sin id, preserva el camino bulk anterior exacto.
      `application.cierre.aprobar_control` solo invoca
      `marcar_reparacion_lista` cuando, tras la aprobacion, TODOS los
      Detalles quedan APROBADO. **Correccion de revision**: una
      aprobacion parcial registraba `PROC-REP-230` con observacion
      "No", como si significara "todavia falta aprobar otro" -pero
      `PROC-REP-230=No` significa que un Detalle fue RECHAZADO (fuera
      de scope). Se corrigio para que una aprobacion parcial registre
      UNICAMENTE `PROC-REP-220` (nunca `PROC-REP-230`), y para que
      `PROC-REP-230` solo se registre -siempre "Si"- cuando esa
      aprobacion deja TODOS los Detalles APROBADO; recien ahi se
      encadenan `PROC-REP-245`/`PROC-REP-240`.
      → `app/backend/app/services/reparaciones.py::aprobar_control_tecnico`,
        `app/backend/app/application/cierre.py::aprobar_control`,
        `app/backend/app/api/schemas.py::AprobarControlIn`,
        `app/backend/app/api/ordenes.py::post_aprobar_control`
      → test: `tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`
        (con aserciones de historial exactas: la primera aprobacion
        agrega solo `["PROC-REP-220"]`; la ultima agrega
        `["PROC-REP-220", "PROC-REP-230", "PROC-REP-245", "PROC-REP-240"]`),
        `tests/test_multidetalle.py::test_control_tecnico_rechaza_si_algun_detalle_no_es_terminal`
        (test negativo: rechaza aprobar un Detalle COMPLETO mientras
        otro de la misma Orden siga DEFINIDO)

**Checkpoint**: con un Detalle todavia no terminal, `APROBAR_CONTROL`
ni siquiera se ofrece y el comando se rechaza (409) para cualquier
Detalle, incluso uno ya COMPLETO. Con todos terminales, aprobar DET-001
registra solo `PROC-REP-220` y NO marca REPARACION_LISTA mientras
DET-002 siga PENDIENTE; aprobar el ultimo encadena `220 -> 230 [Si] ->
245 -> 240`.

## Phase 4c: BR-REP-009 / PROC-REP-245 — puntaje inmediato vs consolidacion final (correccion de revision)

- [x] Sin cambio de comportamiento computado (no habia bug):
      `OrdenReparacion.puntaje_total` ya sumaba los Detalles con
      control APROBADO desde Slice 0, asi que DET-001 ya aportaba su
      puntaje de inmediato al aprobarse, sin esperar a
      `PROC-REP-245`. Lo que se corrigio fue la interpretacion de
      negocio: `PROC-REP-245` se renombro de "Calcular puntaje de la
      reparacion" a **"Consolidar puntaje de la reparacion"**
      (`business/processes/repair-management-v1.3.yaml`) y su
      descripcion aclara que NO crea el puntaje por Detalle -eso ya
      ocurre en PROC-REP-230 sobre ESE Detalle-, solo consolida el
      total de la Orden cuando el control completo termina. `BR-REP-009`
      (`business/rules/business-rules-v1.3.yaml`) se reescribio en el
      mismo sentido. Se renombraron tambien, por consistencia, la
      etiqueta de progreso (`application/progreso.py`: "Calcular
      puntaje" -> "Consolidar puntaje") y el `accion` del historial
      (`services/reparaciones.py::calcular_puntaje`:
      `CALCULAR_PUNTAJE` -> `CONSOLIDAR_PUNTAJE`, tambien en el fixture
      declarativo `tests/fixtures/hp_rep_001.py`).
      → test: `tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`
        (nueva asercion: `puntaje_total == 10` -solo DET-001- justo
        despues de la primera aprobacion, antes de `PROC-REP-245`)

**Checkpoint**: `puntaje_total` refleja el aporte de cada Detalle desde
su propia aprobacion; `PROC-REP-245` solo aparece en el historial junto
con la aprobacion que deja todos los Detalles APROBADO.

## Phase 4b: Guard de backend para Detalle trabajable (DEFINIDO+SIN_BLOQUEO)

- [x] **TASK-REP-161** [US-REP-007] Alinear `services.tomas.
      seleccionar_detalle`, `services.tomas.validar_estacion_trabajo` y
      `services.ejecuciones.reservar_insumos_e_iniciar_ejecucion` con
      la definicion de Detalle trabajable ya usada por
      `application/acciones.py` (`DEFINIDO + SIN_BLOQUEO`).
      **Correccion de revision**: las tres funciones validaban solo
      `estado == DEFINIDO`, sin mirar `condicion`; una llamada directa
      de API con un Detalle `BLOQUEADO_POR_RECURSOS` o
      `REQUIERE_DEFINICION` no se rechazaba, aunque la UI ya lo
      ocultara.
      → `app/backend/app/services/tomas.py::seleccionar_detalle`,
        `app/backend/app/services/tomas.py::validar_estacion_trabajo`,
        `app/backend/app/services/ejecuciones.py::reservar_insumos_e_iniciar_ejecucion`
      → test: `tests/test_detalle_bloqueado_guard.py` (4 funciones, 7
        casos: `seleccionar_detalle` y
        `reservar_insumos_e_iniciar_ejecucion` rechazan ambas
        condiciones bloqueadas -parametrizado-,
        `validar_estacion_trabajo` invalida si el unico Detalle esta
        bloqueado -parametrizado-, mas un test de control que confirma
        que `SIN_BLOQUEO` si se acepta)

**Checkpoint**: un intento directo de API (sin pasar por
`acciones_disponibles`) sobre un Detalle bloqueado se rechaza en los
tres puntos de entrada, no solo se oculta en la UI.

## Phase 5: Caracterizacion actualizada (cambios justificados)

- [x] Actualizar `tests/test_caracterizacion_hp1.py::test_toma_activa_sin_ejecucion`:
      agrega `("LIBERAR_ORDEN", (TECNICO,), None)` a la lista esperada
      -PROC-REP-212/213 ya implementados, la accion pasa a estar
      disponible en ese estado.
- [x] Actualizar `tests/test_caracterizacion_hp1.py::test_espera_control`:
      `APROBAR_CONTROL` pasa de `detalle_id=None` a
      `detalle_id=flujo_mvp.DETALLE_ID` -control granular por Detalle,
      unica excepcion deliberada de este slice.

**Checkpoint**: `pytest` completo en verde (329 tests: 316 baseline +
4 en `test_multidetalle.py` + 7 en `test_detalle_bloqueado_guard.py` +
2 en `test_proc212_registro_condicional.py`). Unico cambio de
expectativa: las dos aserciones de arriba, documentadas y deliberadas.

## Phase 6: Frontend minimo

- [x] `api/ordenes.ts`: `definirReparacion` gana
      `finalizarDefinicion = true`; `aprobarControl` gana `detalleId`;
      nueva `liberarOrden`.
      → `app/frontend/src/api/ordenes.ts`
- [x] `AccionesOrden.tsx`: nuevo `FormularioDefinirReparacion` (tipo +
      casilla "Finalizar la definicion", tildada por defecto);
      `APROBAR_CONTROL` pasa `accion.detalle_id`; nuevo caso
      `LIBERAR_ORDEN`.
      → `app/frontend/src/features/ordenes-reparacion/AccionesOrden.tsx`
- [x] `PanelOrdenes.tsx`: `ejecutor` actualizado a las firmas nuevas.
      → `app/frontend/src/features/ordenes-reparacion/PanelOrdenes.tsx`
      → verificado con `tsc --noEmit` + `vite build`

## Phase 7: Fuera de este slice — NO implementado

Corresponden a otros slices en paralelo o a Exceptions/Variants fuera
del alcance MVP v2 confirmado.

- [ ] `RT_INTERNO` / `RMA_GARANTIA_REPARACION` operativos (HP-REP-002/003).
- [ ] `EN_REVISION` (VAR-REP-001/002).
- [ ] Recursos insuficientes persistidos, override (EXC-REP-001/002/003).
- [ ] Ejecucion interrumpida (VAR-REP-003).
- [ ] Control rechazado / retrabajo (EXC-REP-005, `EstadoControl.RECHAZADO`).
- [ ] `REQUIERE_REVISION` operativo (EXC-REP-004).
- [ ] Cancelacion de Detalle / Orden (FEAT-REP-009).
- [ ] Inventario UI, PostgreSQL.

## Dependencies & Execution Order

```text
(specs/009-mvp2-foundation: resolver completo, cierre de toma no destructivo)
  └── Fase 1 (definir N Detalles)
        └── Fase 2 (seleccion entre varios trabajables)
              └── Fase 3 (¿iniciar Detalle o liberar?, PROC-REP-212/213)
                    └── Fase 3c (212 [Si] solo cuando corresponde)
                          └── Fase 4 (control granular por Detalle)
                                └── Fase 4c (puntaje inmediato vs consolidacion)
                                      └── Fase 4b (guard de backend Detalle trabajable)
                                            └── Fase 5 (caracterizacion actualizada)
                                                  └── Fase 6 (frontend)
```

## Estado real de implementacion

| Fase | Tareas | `[x]` con evidencia codigo+test | `[ ]` |
|---|---|---|---|
| Definir N Detalles | 1 | 1 | 0 |
| Seleccion entre varios | 1 | 1 | 0 |
| ¿Iniciar Detalle o liberar? | 2 | 2 | 0 |
| 212 [Si] condicional | 1 | 1 | 0 |
| Control granular | 1 | 1 | 0 |
| Puntaje inmediato vs consolidacion | 1 | 1 | 0 |
| Guard de backend | 1 | 1 | 0 |
| Caracterizacion | 2 | 2 | 0 |
| Frontend | 3 | 3 | 0 |
| Fuera del slice | 8 | 0 | 8 |
| **Total** | **21** | **13** | **8** |
