# Implementation Plan: MVP v2 — Slice 1 (Multi-Detalle operativo)

**Branch**: `mvp-v2-multidetalle` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/010-slice1-multidetalle/spec.md`

## Summary

Slice 0 (Foundation) dejo el dominio ya preparado para N Detalles: el
resolver de BR-REP-012 (`resolver_situacion_orden`) ya recibe una
secuencia de Detalles, `OrdenReparacion.reparaciones_detail` ya es una
lista, y `total`/`puntaje_total` ya suman sobre todos. Lo que faltaba
era la capa de aplicacion/servicio, que en tres puntos concretos
asumia "un unico Detalle" a pesar de que el modelo ya no lo hacia:

1. `application.ingreso.definir_reparacion` creaba el Detalle Y
   habilitaba la Orden en la misma llamada -una Orden nunca podia
   recibir un segundo Detalle.
2. `application.acciones.detalle_trabajable` devolvia solo el primer
   Detalle trabajable -la UI nunca veia los demas.
3. `services.reparaciones.aprobar_control_tecnico` aprobaba todos los
   Detalles de una vez, exigiendo que todos estuvieran COMPLETO antes
   de aprobar ninguno.

La decision tecnica central es que las tres correcciones son
**aditivas y minimas**, no un rediseño:

- `definir_reparacion` gana un parametro `finalizar_definicion: bool =
  True` (default preserva el comportamiento exacto de HP-REP-001 con 1
  Detalle). En `False`, agrega el Detalle y no hace nada mas; Recepcion
  vuelve a llamar al mismo endpoint por cada Detalle, y en el ultimo
  omite el parametro (o lo pasa en `True`) para que corra comprobante +
  factibilidad + habilitacion.
- `application.acciones` gana `detalles_trabajables()` (plural), que
  devuelve la lista completa; `acciones_disponibles()` itera sobre ella
  y emite un `AccionDisponible(INICIAR_DETALLE, detalle_id=...)` por
  cada uno. `detalle_trabajable()` (singular) se conserva tal cual para
  no romper a quien ya la importa (`happy_path.py`,
  `test_acciones_disponibles.py`).
- `aprobar_control_tecnico` gana `detalle_id: str | None = None`, pero
  conserva intacta la precondicion de que PROC-REP-220 solo se alcanza
  con la Orden ENTERA terminal (todos los Detalles COMPLETO) -ahora
  exigida siempre, con o sin `detalle_id`, no solo en el camino bulk
  anterior-. Con un id, aprueba solo ese Detalle; sin id, preserva el
  camino bulk anterior exacto (aprueba todos a la vez).
  `application.cierre.aprobar_control` solo invoca
  `marcar_reparacion_lista` cuando, despues de la aprobacion, TODOS los
  Detalles de la Orden quedan APROBADO -sea que eso pase en la primera
  llamada (1 Detalle) o en la enesima (N Detalles).

PROC-REP-212/213 (¿continuar o liberar?) ya estaban previstos como
Tasks `NOT_IMPLEMENTED` desde `specs/004-feat-rep-004-hp-slice/`. Este
slice los completa con un service nuevo,
`services.tomas.liberar_orden`, que cierra la toma activa y devuelve la
Orden a `EN_COLA`. "Continuar" no necesita codigo nuevo: ya es posible
porque `evaluar_situacion_orden` (Slice 0) deja la toma ACTIVA cuando
el resolver da `ABIERTA_TRABAJABLE`, y `seleccionar_detalle` ya acepta
cualquier `detalle_id` de la Orden.

Ningun mecanismo generico nuevo: sin builder de Detalles, sin motor de
reglas para el control, sin maquina de estados explicita para
"continuar/liberar". Tres parametros opcionales y un service nuevo de
20 lineas.

## Technical Context

**Language/Version**: Python 3.11+ (backend), TypeScript/React (frontend)

**Primary Dependencies**: FastAPI, Pydantic v2 (sin nuevas dependencias)

**Storage**: JSON local, sin cambios de esquema de persistencia -ningun
campo nuevo, ninguna clave renombrada

**Testing**: pytest (backend), `tsc --noEmit` + `vite build` (frontend)

**Target Platform**: servicio backend local (MVP)

**Project Type**: web application (backend + frontend)

**Performance Goals**: no aplica

**Constraints**: Ruff `line-length = 79`; sin ORM, sin BPM engine, sin
motor de reglas generico (Constitution VII)

**Scale/Scope**: 3 funciones de aplicacion/servicio extendidas
(`definir_reparacion`, `acciones_disponibles`, `aprobar_control_tecnico`
+ `aprobar_control`), 1 service nuevo (`liberar_orden`, con su comando
de aplicacion y endpoint), 4 tests nuevos + 2 aserciones de
caracterizacion actualizadas, 1 componente de frontend nuevo
(`FormularioDefinirReparacion`) mas ajustes en `AccionesOrden.tsx` /
`PanelOrdenes.tsx` / `api/ordenes.ts`.

## Constitution Check

| Principio | Estado | Evidencia |
|---|---|---|
| I. Business YAML fuente de verdad | PASS | Ningun YAML de `business/` se modifico; multi-Detalle sigue siendo MECHANISM_ONLY, no un Scenario nuevo |
| II. IDs estables | PASS | Ningun ID de negocio (`BR-REP-*`, `PROC-REP-*`) se renombra; PROC-REP-212/213 pasan de `implemented: false` a `true` sin cambiar su ID ni su texto |
| III. Trazabilidad E2E | PASS | [traceability.md](./traceability.md); `npm run validate:traceability` en verde |
| IV. Modelo de datos transversal | PASS | Ningun modelo de dominio nuevo: se reutilizan `ReparacionDetail`, `TomaOrden`, `EjecucionReparacion` tal como Slice 0 los dejo |
| V. No inferir funcional desde codigo | PASS | `liberar_orden` cita PROC-REP-213/BR-REP-018 tal como los describe `docs/discovery/README.md`; no se inventa ninguna regla |
| VI. Separacion de capas | PASS | El cambio nuevo vive en `services/tomas.py` (service puro) y se orquesta desde `application/taller.py`, igual que el resto de los comandos |
| VII. Sin sobreingenieria | PASS | Sin builder de Detalles, sin maquina de estados para "continuar/liberar": son parametros opcionales y un service de 20 lineas |
| VIII. Tests vinculados | PASS | Ver [traceability.md](./traceability.md) |
| IX. UAT distinto | PASS | Ningun UAT se marca aprobado; siguen PENDING |
| X. PEP 8 / Ruff | PASS | `ruff check app/ tests/` limpio |
| XI. Slice vs Feature | PASS | HP-REP-001 sigue siendo el unico Scenario operativo; ninguna Feature se declara IMPLEMENTED |

**Violaciones a justificar**: ninguna.

## Project Structure

### Documentation (this feature)

```text
specs/010-slice1-multidetalle/
├── spec.md
├── plan.md
├── tasks.md
└── traceability.md
```

### Source Code (repository root)

```text
app/backend/app/
├── application/
│   ├── ingreso.py       # definir_reparacion: + finalizar_definicion
│   ├── acciones.py       # + detalles_trabajables, + ACCION_LIBERAR_ORDEN,
│   │                      # INICIAR_DETALLE y APROBAR_CONTROL ahora emiten
│   │                      # una accion por Detalle
│   ├── cierre.py          # aprobar_control: + detalle_id, gate de
│   │                      # marcar_reparacion_lista movido aqui
│   └── taller.py          # + liberar_orden (comando de aplicacion)
├── services/
│   ├── reparaciones.py    # aprobar_control_tecnico: + detalle_id
│   └── tomas.py            # + liberar_orden (PROC-REP-213)
└── api/
    ├── schemas.py          # + finalizar_definicion, + detalle_id,
    │                       # + LiberarOrdenIn
    └── ordenes.py           # + POST /{orden_id}/release

app/backend/tests/
├── test_multidetalle.py            # NUEVO: 3 tests (E2E, compat HP1, liberar)
└── test_caracterizacion_hp1.py     # 2 aserciones actualizadas (justificadas)

app/frontend/src/
├── api/ordenes.ts                                    # firmas ampliadas + liberarOrden
└── features/ordenes-reparacion/
    ├── AccionesOrden.tsx    # FormularioDefinirReparacion nuevo,
    │                        # APROBAR_CONTROL con detalle_id, caso LIBERAR_ORDEN
    └── PanelOrdenes.tsx      # ejecutor actualizado

traceability/hp-rep-001.yaml   # FR-REP-067..070, TR-REP-065..068,
                                # TASK-REP-158..160 (+ 061/062 a DONE),
                                # CODE-REP-121..126, TEST-REP-223..225
```

**Structure Decision**: cero archivos nuevos en `domain/` o `services/`
salvo la funcion `liberar_orden` dentro de `services/tomas.py` (donde ya
vive el resto de la mecanica de toma/seleccion). El resto son
extensiones aditivas de funciones existentes, exactamente en los tres
puntos que el analisis de gap identifico.

## Data Model (artefacto transversal)

Sin cambios: este slice no agrega ni modifica ningun modelo de dominio.
`ReparacionDetail.control_estado/control_usuario_id/control_fecha/
control_observaciones` ya eran campos por Detalle desde antes de este
slice -solo el service que los escribia era bulk; ahora tambien puede
ser granular.

## Technical Requirements

Ver `traceability/hp-rep-001.yaml` (`TR-REP-065`..`TR-REP-068`) y el
detalle narrativo en [traceability.md](./traceability.md).

## Dependencies

- **Depende de**: `specs/009-mvp2-foundation/` (resolver completo de
  BR-REP-012, `CondicionReparacionDetail`, cierre de toma solo en
  resultados terminales -sin esto, completar un Detalle con otro
  pendiente habria lanzado una excepcion despues de persistir el
  inventario).
- **Nodos compartidos**: `PROC-REP-211` (ya evaluado por Slice 0, sin
  cambios); este slice agrega comportamiento en `PROC-REP-212/213`,
  hasta ahora sin ningun comando que los alcanzara.
- **Consumido por**: ningun slice posterior depende todavia de esto de
  forma documentada; deja la base para que HP-REP-002/003 (otros
  origenes) puedan definir sus propios N Detalles sin repetir el
  refactor.
- **Externa**: ninguna dependencia nueva.

## Complexity Tracking

> Sin violaciones de la Constitution que requieran justificacion.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| — | — | — |
