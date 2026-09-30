# Implementation Plan: HP-REP-002 — Equipo RT Interno

**Branch**: `mvp-v2-hp2` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/011-slice2-hp-rep-002/spec.md`

## Summary

Conectar el origen `RT_INTERNO` -ya representado en el dominio y en
`domain.politicas` por MVP v2 Foundation (`specs/009-mvp2-foundation/`)-
al flujo operativo real, siguiendo exactamente
`business/scenarios/repair-management-scenarios-v1.3.yaml` (HP-REP-002).
Decision tecnica central: **el Origen decide el comportamiento
exclusivamente a traves de `PoliticaOrigen`**, nunca mediante un
condicional sobre el Origen o el Scenario en `application/acciones.py`,
`services/documentos.py` o `services/pagos.py`. Un segundo eje, agregado
tras la revision del slice: distinguir explicitamente en
`AccionDisponible`/`AccionOut` una accion humana (`requiere_actor: true`) de un nodo `actor: ACT-SYSTEM`
*sin ningun actor humano* (`roles: []`, `requiere_actor: false`), en vez
de conflacionar ambos casos bajo `roles: []`.

## Technical Context

**Language/Version**: Python 3.11+ (backend), TypeScript/React (frontend)

**Primary Dependencies**: FastAPI, Pydantic v2 (sin nuevas dependencias)

**Storage**: JSON local; `OrdenReparacion.cliente` pasa a `Optional` y
`referencia_rt` se agrega, ambos compatibles con el JSON persistido
antes de este slice

**Testing**: pytest (backend, 349 tests: 316 baseline + 33 de este
slice), `tsc --noEmit` + `vite build` (frontend)

**Target Platform**: servicio backend local (MVP)

**Project Type**: web application (backend + frontend)

**Performance Goals**: no aplica

**Constraints**: Ruff `line-length = 79`; sin ORM, sin BPM engine, sin
motor de reglas generico (Constitution VII); no crear Features nuevas
(HP-REP-002 reutiliza las 8 de HP-REP-001)

**Scale/Scope**: 3 services nuevos (`crear_orden_rt_interno`,
`informar_resultado_rt`, `devolver_equipo_rt`), 1 service generalizado
(`generar_comprobante_recepcion`), 1 service con un chequeo nuevo
(`registrar_pago`), 3 endpoints nuevos, 1 campo nuevo en
`AccionDisponible`/`AccionOut` (`requiere_actor`), 2 campos nuevos en el
dominio (`cliente: Optional`, `referencia_rt`), 33 tests nuevos

## Constitution Check

| Principio | Estado | Evidencia |
|---|---|---|
| I. Business YAML fuente de verdad | PASS | La secuencia PROC-REP-250/290/270 y `skipped_nodes` citan exactamente `business/scenarios/repair-management-scenarios-v1.3.yaml` (HP-REP-002); ningun YAML de `business/` se modifico |
| II. IDs estables | PASS | PROC-REP-270 se reutiliza tal como el proceso lo declara (`nota` en el YAML de negocio); ningun ID de negocio se renombra |
| III. Trazabilidad E2E | PASS | [traceability.md](./traceability.md); grafo machine-readable en `traceability/hp-rep-002.yaml`, validado |
| IV. Modelo de datos transversal | PASS | `PoliticaOrigen` (ya existente) gobierna comprobante/notificacion/pago/entrega/informar-RT de forma uniforme; `requiere_actor` es reusable por cualquier accion `ACT-SYSTEM` futura |
| V. No inferir funcional desde codigo | PASS | El estado terminal `PENDIENTE_DE_DEFINIR` y el orden 290->270 citan literalmente el Scenario y `docs/discovery/README.md`, no se inventaron |
| VI. Separacion de capas | PASS | Los nuevos services no conocen FastAPI; los nuevos endpoints no deciden negocio |
| VII. Sin sobreingenieria | PASS | Sin motor de reglas: `PoliticaOrigen` sigue siendo un dict de dataclasses; `requiere_actor` es un `bool` aditivo, no un sistema de permisos |
| VIII. Tests vinculados | PASS | Ver [traceability.md](./traceability.md) |
| IX. UAT distinto | PASS | `UAT-REP-017`..`020` quedan `PENDING` |
| X. PEP 8 / Ruff | PASS | `ruff check app/ tests/` limpio |
| XI. Slice vs Feature | PASS | Las 8 Features siguen `draft`; lo implementado es el slice de HP-REP-002 (segundo Scenario sobre las mismas Features) |

**Violaciones a justificar**: ninguna.

## Project Structure

### Documentation (this feature)

```text
specs/011-slice2-hp-rep-002/
├── spec.md
├── plan.md
├── tasks.md
└── traceability.md
```

### Source Code (repository root)

```text
app/backend/app/
├── domain/
│   └── models/
│       └── orden_reparacion.py   # cliente: Cliente | None, + referencia_rt
├── services/
│   ├── documentos.py              # generar_comprobante_recepcion: por PoliticaOrigen
│   ├── ordenes.py                 # + crear_orden_rt_interno, informar_resultado_rt,
│   │                               #   devolver_equipo_rt
│   ├── pagos.py                   # registrar_pago: + chequeo condicion_comercial COBRABLE
│   └── __init__.py                # re-exporta los 3 services nuevos
├── application/
│   ├── ingreso.py                 # + crear_orden_rt
│   ├── cierre.py                  # + informar_rt, devolver_rt
│   ├── acciones.py                # + ACCION_INFORMAR_RT/DEVOLVER_RT, AccionDisponible.requiere_actor,
│   │                               #   corte de acciones por current_process == EVT-REP-999
│   ├── progreso.py                # + _RUTA_RT_INTERNO
│   └── __init__.py                # exporta los comandos nuevos
├── api/
│   ├── schemas.py                 # CrearOrdenRtIn, DevolverRtIn, cliente/referencia_rt/
│   │                               #   condicion_comercial/requiere_actor en los *Out
│   └── ordenes.py                 # POST /rt-interno, /{id}/inform-rt (sin body), /{id}/return-rt
└── ...

app/frontend/src/
├── types/api.ts                   # Cliente|null, referencia_rt, condicion_comercial,
│                                   #   requiere_actor, OrigenOrden
├── api/ordenes.ts                 # crearOrdenRt, informarRt (sin usuarioId), devolverRt
└── features/ordenes-reparacion/
    ├── ListadoOrdenes.tsx          # FormularioNuevaOrdenRt
    ├── AccionesOrden.tsx           # botones INFORMAR_RT/DEVOLVER_RT, habilitada por requiere_actor
    ├── DetalleOrden.tsx            # cliente nullable, condicion_comercial, origen
    └── PanelOrdenes.tsx            # wiring de los 2 comandos nuevos
```

**Structure Decision**: cero modulos nuevos de infraestructura -todo el
delta vive en los mismos modulos que ya organizan HP-REP-001 por
responsabilidad (ingreso/cierre/acciones/progreso, no por Scenario)-,
consistente con la decision de Foundation de separar
"politica / resolucion tecnica / acciones / progreso" en modulos fijos.

## Data Model (artefacto transversal)

| Entidad | Archivo | Rol |
|---|---|---|
| `OrdenReparacion.cliente` | `app/backend/app/domain/models/orden_reparacion.py` | `Optional`, `None` para `RT_INTERNO` |
| `OrdenReparacion.referencia_rt` | `app/backend/app/domain/models/orden_reparacion.py` | Contexto minimo de PROC-REP-020 |
| `AccionDisponible.requiere_actor` / `AccionOut.requiere_actor` | `application/acciones.py`, `api/schemas.py` | Distingue accion humana de nodo `ACT-SYSTEM` sin actor |
| `ResumenComercialOut.condicion_comercial` | `app/backend/app/api/schemas.py` | `PoliticaOrigen.condicion_comercial` expuesta a la API/UI |

## Technical Requirements

Ver `traceability/hp-rep-002.yaml` (`TR-REP-070`..`TR-REP-078`) y el
detalle narrativo en [traceability.md](./traceability.md).

## Dependencies

- **Depende de**: `specs/009-mvp2-foundation/` (`PoliticaOrigen`,
  `politica_de()`, `OrigenOrden.RT_INTERNO`, resolver BR-REP-012
  generalizado), y de los slices de HP-REP-001 (`001`..`008`) para el
  tramo tecnico compartido, sin cambios de comportamiento.
- **Nodos compartidos**: `PROC-REP-270` (reutilizado, entrega comercial
  o devolucion RT segun Origen); el tramo `045..245` (definir, factibilidad,
  toma, `180 -> 212 [Si] -> 181` de Multi-Detalle, ejecucion, control,
  consolidacion de puntaje) sin cambios.
- **Consumido por**: ningun slice todavia (HP-REP-002 es hoja del arbol
  de dependencias de MVP v2 por ahora).
- **Coordinacion de rama**: `specs/010-slice1-multidetalle/` (Multi-Detalle
  operativo) se desarrolla en paralelo en otra rama/worktree
  (`mvp-v2-multidetalle`); comparte `application/acciones.py`,
  `api/schemas.py` y trazabilidad como archivos sensibles, pero este
  slice no modifica su mecanica.
- **Externa**: ninguna dependencia nueva.

## Complexity Tracking

> Sin violaciones de la Constitution que requieran justificacion.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| — | — | — |
