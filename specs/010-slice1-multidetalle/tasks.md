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

## Phase 3: Continuar con otro Detalle o liberar la Orden (PROC-REP-212/213)

- [x] Confirmar que "continuar" no requiere codigo nuevo:
      `evaluar_situacion_orden` (Slice 0) ya deja la toma ACTIVA cuando
      el resolver da `ABIERTA_TRABAJABLE`, y `seleccionar_detalle` ya
      acepta cualquier `detalle_id` de la Orden. Verificado por
      `tests/test_completar_ejecucion_consistencia.py` (ya verde antes
      de este slice) y confirmado end-to-end por
      `tests/test_multidetalle.py`.
- [x] **TASK-REP-061** (actualizada, ver nota en `traceability.md`)
      Implementar PROC-REP-212 (decision explicita del tecnico:
      continuar con otro Detalle o liberar la Orden, BR-REP-018).
      → Resuelto: la decision no persiste estado propio (es implicita
        entre seguir seleccionando un Detalle o llamar a `liberar_orden`,
        ver TASK-REP-062).
- [x] **TASK-REP-062** (actualizada, ver nota en `traceability.md`)
      Implementar PROC-REP-213 (liberar Orden: cerrar la participacion
      con fecha/hora de fin y devolver la Orden a EN_COLA).
      → `app/backend/app/services/tomas.py::liberar_orden`,
        `app/backend/app/application/taller.py::liberar_orden`,
        `app/backend/app/api/schemas.py::LiberarOrdenIn`,
        `app/backend/app/api/ordenes.py::post_liberar_orden`
      → Accion `LIBERAR_ORDEN` publicada por `acciones_disponibles`
        mientras hay toma activa y ninguna Ejecucion en curso.
      → test: `tests/test_multidetalle.py::test_liberar_orden_devuelve_la_orden_a_en_cola`,
        `tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`

**Checkpoint**: al completar un Detalle con otro pendiente, la toma
sigue activa y el tecnico puede seleccionar el siguiente sin re-tomar
la Orden; `POST /release` la libera explicitamente y la devuelve a
EN_COLA.

## Phase 4: Control tecnico granular por Detalle

- [x] **TASK-REP-160** [US-REP-010] Agregar `detalle_id: str | None =
      None` a `aprobar_control_tecnico`, preservando la precondicion de
      que PROC-REP-220 solo se alcanza con TODOS los Detalles de la
      Orden COMPLETO (igual que antes de este slice, ahora exigida
      siempre, con o sin `detalle_id`): con id, aprueba solo ese
      Detalle; sin id, preserva el camino bulk anterior exacto.
      `application.cierre.aprobar_control` solo invoca
      `marcar_reparacion_lista` cuando, tras la aprobacion, TODOS los
      Detalles quedan APROBADO.
      → `app/backend/app/services/reparaciones.py::aprobar_control_tecnico`,
        `app/backend/app/application/cierre.py::aprobar_control`,
        `app/backend/app/api/schemas.py::AprobarControlIn`,
        `app/backend/app/api/ordenes.py::post_aprobar_control`
      → test: `tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`,
        `tests/test_multidetalle.py::test_control_tecnico_rechaza_si_algun_detalle_no_es_terminal`
        (test negativo: rechaza aprobar un Detalle COMPLETO mientras
        otro de la misma Orden siga DEFINIDO)

**Checkpoint**: con un Detalle todavia no terminal, `APROBAR_CONTROL`
ni siquiera se ofrece y el comando se rechaza (409) para cualquier
Detalle, incluso uno ya COMPLETO. Con todos terminales, aprobar DET-001
no marca REPARACION_LISTA mientras DET-002 siga PENDIENTE; aprobar el
ultimo si.

## Phase 5: Caracterizacion actualizada (cambios justificados)

- [x] Actualizar `tests/test_caracterizacion_hp1.py::test_toma_activa_sin_ejecucion`:
      agrega `("LIBERAR_ORDEN", (TECNICO,), None)` a la lista esperada
      -PROC-REP-212/213 ya implementados, la accion pasa a estar
      disponible en ese estado.
- [x] Actualizar `tests/test_caracterizacion_hp1.py::test_espera_control`:
      `APROBAR_CONTROL` pasa de `detalle_id=None` a
      `detalle_id=flujo_mvp.DETALLE_ID` -control granular por Detalle,
      unica excepcion deliberada de este slice.

**Checkpoint**: `pytest` completo en verde (320 tests: 316 baseline +
4 nuevos de Multi-Detalle). Unico cambio de expectativa: las dos
aserciones de arriba, documentadas y deliberadas.

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
              └── Fase 3 (continuar / liberar, PROC-REP-212/213)
                    └── Fase 4 (control granular por Detalle)
                          └── Fase 5 (caracterizacion actualizada)
                                └── Fase 6 (frontend)
```

## Estado real de implementacion

| Fase | Tareas | `[x]` con evidencia codigo+test | `[ ]` |
|---|---|---|---|
| Definir N Detalles | 1 | 1 | 0 |
| Seleccion entre varios | 1 | 1 | 0 |
| Continuar / liberar | 2 | 2 | 0 |
| Control granular | 1 | 1 | 0 |
| Caracterizacion | 2 | 2 | 0 |
| Frontend | 3 | 3 | 0 |
| Fuera del slice | 8 | 0 | 8 |
| **Total** | **18** | **10** | **8** |
