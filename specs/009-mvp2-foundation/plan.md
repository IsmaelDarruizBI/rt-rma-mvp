# Implementation Plan: MVP v2 — Slice 0 (Foundation)

**Branch**: `mvp-v2` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-mvp2-foundation/spec.md`

## Summary

Slice 0 no agrega comportamiento de negocio nuevo (salvo el fix de
BR-REP-017): generaliza la arquitectura que HP-REP-001 dejo acoplada a
si misma, para que los slices siguientes (HP-REP-002/003,
EN_REVISION, recursos, retrabajo) puedan construirse sin repetir el
mismo refactor. La decision tecnica central es **separar clasificacion
de efectos** en dos lugares distintos:

1. `resolver_situacion_orden` (BR-REP-012) es una funcion pura que
   clasifica; `evaluar_situacion_orden` aplica lo que esa clasificacion
   implica (registrar el paso, cerrar la toma solo si corresponde).
2. `acciones_disponibles()`/`progreso()` se separan de la ruta fija de
   HP-REP-001 (`application/happy_path.py`) hacia
   `application/acciones.py` y `application/progreso.py`, que leen el
   estado real de la Orden y `domain.politicas.politica_de(origen)` en
   vez de un condicional fijo por CLIENTE_EXTERNO.

Ningun mecanismo nuevo interpreta YAML en runtime ni ejecuta un grafo
de procesos generico: las rutas y politicas son datos explicitos
(tuplas, dataclasses, dicts), no un motor.

## Technical Context

**Language/Version**: Python 3.11+ (backend), TypeScript/React (frontend,
cambio minimo)

**Primary Dependencies**: FastAPI, Pydantic v2 (sin nuevas dependencias)

**Storage**: JSON local, sin cambios de esquema de persistencia mas alla
de un campo nuevo con default

**Testing**: pytest (backend), `tsc --noEmit` + `vite build` (frontend)

**Target Platform**: servicio backend local (MVP)

**Project Type**: web application (backend + frontend)

**Performance Goals**: no aplica

**Constraints**: Ruff `line-length = 79`; sin ORM, sin BPM engine, sin
motor de reglas generico (Constitution VII)

**Scale/Scope**: 2 modulos de dominio nuevos (`domain/politicas.py`,
enum `CondicionReparacionDetail`), 1 modulo de service nuevo
(`services/resolucion.py`), 2 modulos de aplicacion nuevos
(`application/acciones.py`, `application/progreso.py`), 1 modulo
convertido en fachada (`application/happy_path.py`), 31 tests nuevos,
1 test renombrado

## Constitution Check

| Principio | Estado | Evidencia |
|---|---|---|
| I. Business YAML fuente de verdad | PASS | El resolver usa exactamente la matriz de BR-REP-012 y los nombres de `docs/discovery/README.md`; no se modifico ningun YAML de `business/` |
| II. IDs estables | PASS | Ningun ID de negocio (`BR-REP-*`, `PROC-REP-*`) se renombra |
| III. Trazabilidad E2E | PASS | [traceability.md](./traceability.md); grafo actualizado y validado |
| IV. Modelo de datos transversal | PASS | `PoliticaOrigen` y `CondicionReparacionDetail` son N:1 reusables por los slices siguientes |
| V. No inferir funcional desde codigo | PASS | La matriz del resolver y las politicas citan `BR-REP-012`/`BR-REP-016`/`docs/discovery/README.md`, no se inventaron reglas |
| VI. Separacion de capas | PASS | `domain/politicas.py` no importa FastAPI ni repositories; `services/resolucion.py` es una funcion pura sin repositories |
| VII. Sin sobreingenieria | PASS | Sin BPM engine, sin DSL de reglas, sin registries genericos: dataclasses, dict y funciones explicitas |
| VIII. Tests vinculados | PASS | Ver [traceability.md](./traceability.md) |
| IX. UAT distinto | PASS | Ningun UAT se marca aprobado |
| X. PEP 8 / Ruff | PASS | `ruff check app/ tests/` limpio |
| XI. Slice vs Feature | PASS | HP-REP-001 sigue siendo el unico Scenario operativo; la Constitution no se toca porque esa afirmacion sigue siendo cierta |

**Violaciones a justificar**: ninguna.

## Project Structure

### Documentation (this feature)

```text
specs/009-mvp2-foundation/
├── spec.md
├── plan.md
├── tasks.md
└── traceability.md
```

### Source Code (repository root)

```text
app/backend/app/
├── domain/
│   ├── models/
│   │   ├── enums.py          # OrigenOrden +2, EstadoWorkflow +1 (EN_REVISION),
│   │   │                     # CondicionReparacionDetail (nuevo)
│   │   ├── reparacion.py     # ReparacionDetail.condicion (nuevo campo)
│   │   └── __init__.py       # exporta CondicionReparacionDetail
│   └── politicas.py          # NUEVO: PoliticaOrigen, politica_de()
├── services/
│   ├── resolucion.py         # NUEVO: ResultadoEvaluacionOrden, resolver_situacion_orden
│   ├── ordenes.py            # evaluar_situacion_orden delega en el resolver
│   ├── pagos.py              # ROLES_PAGO, registrar_pago exige rol
│   └── __init__.py           # re-exporta ROLES_PAGO, resolver_situacion_orden
├── application/
│   ├── acciones.py           # NUEVO: AccionDisponible, acciones_disponibles
│   ├── progreso.py           # NUEVO: PasoProgreso, progreso, rutas por Origen
│   ├── happy_path.py         # convertido en fachada de compatibilidad
│   ├── taller.py             # sin cambios de comportamiento (el fix de
│   │                         # persistencia es consecuencia del resolver)
│   └── __init__.py           # importa de acciones.py / progreso.py
├── api/
│   └── schemas.py            # PasoHappyPath -> PasoProgreso
└── ...

app/frontend/src/features/ordenes-reparacion/
└── DetalleOrden.tsx          # titulo "Progreso HP-REP-001" -> "Progreso de la orden"
```

**Structure Decision**: la separacion "politica / resolucion tecnica /
acciones / progreso" que el analisis de gap identifico como necesaria
se resuelve en exactamente 4 modulos nuevos (mas la fachada), sin capas
intermedias vacias. `happy_path.py` no se borra: seguiria siendo
importable por cualquier codigo externo al repo que dependiera de el.

## Data Model (artefacto transversal)

| Entidad | Archivo | Rol |
|---|---|---|
| `CondicionReparacionDetail` | `app/backend/app/domain/models/enums.py` | Bloqueo del Detalle, independiente del estado tecnico |
| `PoliticaOrigen` | `app/backend/app/domain/politicas.py` | Requerimientos de proceso y condicion comercial por Origen |
| `ResultadoEvaluacionOrden` | `app/backend/app/services/resolucion.py` | Los 8 resultados de BR-REP-012 (movido desde `services/ordenes.py`, re-exportado ahi) |
| `AccionDisponible` | `app/backend/app/application/acciones.py` | Movido desde `happy_path.py`, sin cambio de forma |
| `PasoProgreso` | `app/backend/app/application/progreso.py` | Renombrado desde `PasoHappyPath` |

## Technical Requirements

Ver `traceability/hp-rep-001.yaml` (`TR-REP-057`..`TR-REP-064`, mas
`TR-REP-022`/`TR-REP-045` ampliados) y el detalle narrativo en
[traceability.md](./traceability.md).

## Dependencies

- **Depende de**: `specs/001-feat-rep-001-hp-slice/` (creacion de
  Orden), `specs/005-feat-rep-005-hp-slice/` (evaluar_situacion_orden,
  inventario), `specs/007-feat-rep-007-hp-slice/` (Registrar Pago).
- **Nodos compartidos**: ninguno nuevo; PROC-REP-211 sigue siendo el
  unico nodo que invoca al resolver.
- **Consumido por**: todos los slices funcionales de MVP v2
  (HP-REP-002, HP-REP-003, EN_REVISION, recursos, retrabajo). Ver
  `docs/discovery/README.md` seccion "MVP v2 - Scope funcional
  cerrado" para el detalle de cada uno.
- **Externa**: ninguna dependencia nueva.

## Complexity Tracking

> Sin violaciones de la Constitution que requieran justificacion.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| — | — | — |
