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
Orden a `EN_COLA`.

Ningun mecanismo generico nuevo: sin builder de Detalles, sin motor de
reglas para el control, sin maquina de estados explicita para
"continuar/liberar". Parametros opcionales y dos services nuevos
pequenos (`liberar_orden`, `_registrar_decision_iniciar_detalle`).

### Correccion de revision (pre-merge)

Una revision del commit encontro tres puntos de inconsistencia con
PROC-REP V1.3 y los corrigio antes del merge, sin ampliar el scope:

1. **Liberacion, trazabilidad incompleta**: la funcionalidad ya era
   correcta (liberar con toma activa y sin Ejecucion, incluso
   inmediatamente despues de tomar), pero el grafo de negocio y el
   historial no la representaban de punta a punta. Se renombro
   `PROC-REP-212` de "¿Tecnico desea continuar trabajando esta Orden?"
   a **"¿Iniciar un Detalle de reparacion?"**, y se corrigio el grafo
   real (`business/processes/repair-management-v1.3.yaml`, edges) para
   que se alcance SIEMPRE que hay toma activa y ninguna Ejecucion en
   curso: el edge `PROC-REP-180 -> PROC-REP-181` (directo) se reemplazo
   por `PROC-REP-180 -> PROC-REP-212` -el edge `PROC-REP-212 ->
   PROC-REP-181 [Si]` ya existia-. `seleccionar_detalle` ahora registra
   `PROC-REP-212 [Si]` antes de `PROC-REP-181`; `liberar_orden` registra
   `PROC-REP-212 [No] -> PROC-REP-213 -> PROC-REP-170` (este ultimo
   ACT-SYSTEM) y deja `estado_workflow=EN_COLA`,
   `current_process=PROC-REP-170`. `BR-REP-018` y los tres Scenarios
   HP-REP-001/002/003 (`business/scenarios/...`) se actualizaron para
   reflejar el mismo grafo. No se persiste ningun estado nuevo: la
   decision vive solo en el historial.
2. **Control granular, uso incorrecto de PROC-REP-230=No**: una
   aprobacion parcial (queda otro Detalle PENDIENTE) registraba
   `PROC-REP-230` con observacion "No", como si significara "todavia
   falta aprobar otro". Segun el Business Process, `PROC-REP-230=No`
   significa que un Detalle fue RECHAZADO (fuera de scope,
   EXC-REP-005). Se corrigio `aprobar_control_tecnico` para NO
   registrar `PROC-REP-230` en absoluto en una aprobacion parcial -solo
   `PROC-REP-220`-, y para registrarlo (siempre "Si") unicamente cuando
   esa aprobacion deja TODOS los Detalles APROBADO; recien ahi
   `application.cierre.aprobar_control` encadena `PROC-REP-245` y
   `PROC-REP-240`. `puntaje_total` sigue siendo un computed field: una
   aprobacion parcial ya muestra su puntaje parcial sin necesidad de
   registrar `PROC-REP-245` por adelantado.
3. **Detalle trabajable, guard solo en la UI**: `application/acciones.py`
   ya filtraba por `DEFINIDO + SIN_BLOQUEO`, pero `services.tomas.
   seleccionar_detalle`, `services.tomas.validar_estacion_trabajo` y
   `services.ejecuciones.reservar_insumos_e_iniciar_ejecucion` solo
   validaban `estado == DEFINIDO`, sin mirar `condicion`: una llamada
   directa de API con un Detalle bloqueado (`BLOQUEADO_POR_RECURSOS` o
   `REQUIERE_DEFINICION`) podia pasar. Los tres services ahora exigen
   tambien `condicion == SIN_BLOQUEO`.

Ningun cambio de estos tres agrega un Scenario, un origen, un estado de
control nuevo, ni logica de recursos/interrupcion/revision.

### Correccion de revision, ronda 2 (dos inconsistencias finales)

1. **BR-REP-009 / PROC-REP-245 -puntaje por Detalle vs consolidacion
   final**: la correccion de la ronda 1 (no registrar `PROC-REP-230`
   en una aprobacion parcial) se mantiene intacta. Lo que se corrigio
   ahora es la interpretacion de negocio de `PROC-REP-245`: NO calcula
   el puntaje de cada Detalle por primera vez -eso ya ocurre en el
   momento de la aprobacion de ESE Detalle, porque
   `OrdenReparacion.puntaje_total` es un computed field que ya suma los
   Detalles con control APROBADO (Slice 0)-. `PROC-REP-245` se
   renombro a **"Consolidar puntaje de la reparacion"**
   (`business/processes/repair-management-v1.3.yaml`) y `BR-REP-009`
   (`business/rules/business-rules-v1.3.yaml`) se reescribio para
   dejar esto explicito. Sin cambio de comportamiento computado -no
   habia bug-: `calcular_puntaje()` y su `accion` (renombrada a
   `CONSOLIDAR_PUNTAJE`) siguen llamandose solo cuando todos los
   Detalles quedan APROBADO.
2. **PROC-REP-212 [Si] no debe registrarse indiscriminadamente**:
   `seleccionar_detalle()` registraba `PROC-REP-212 [Si]` en TODA
   llamada. Se corrigio para que solo lo registre cuando la Orden
   realmente viene de esa decision -`current_process` en
   `{PROC-REP-180, PROC-REP-211}`-, sin usar Scenario ID ni un flag
   persistido nuevo. Hoy esto no cambia ningun resultado observable
   (los unicos callers reales llegan siempre con `current_process` en
   ese conjunto), pero deja el service correcto para caminos futuros
   que puedan reentrar a `PROC-REP-181` sin pasar por la decision
   (incompatibilidad de estacion, reserva fallida -ninguno
   implementado-).

Ninguna de las dos toca Scenarios, Features, ni agrega estado
persistido nuevo.

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

**Scale/Scope**: 5 funciones de aplicacion/servicio extendidas
(`definir_reparacion`, `acciones_disponibles`, `seleccionar_detalle`,
`aprobar_control_tecnico` + `aprobar_control`), 2 services nuevos
(`liberar_orden`, `_registrar_decision_iniciar_detalle`, con su comando
de aplicacion y endpoint), 3 guards de backend alineados
(`validar_estacion_trabajo`, `reservar_insumos_e_iniciar_ejecucion`),
4 tests en `test_multidetalle.py` (con aserciones de historial y
puntaje parcial explicitas) + 1 archivo nuevo
(`test_detalle_bloqueado_guard.py`, 4 funciones/7 casos) + 1 archivo
nuevo (`test_proc212_registro_condicional.py`, 2 funciones) + 2
aserciones de caracterizacion actualizadas,
1 componente de frontend nuevo (`FormularioDefinirReparacion`) mas
ajustes en `AccionesOrden.tsx` / `PanelOrdenes.tsx` / `api/ordenes.ts`.
Correccion pre-merge: 1 nodo de negocio renombrado + 2 edges del grafo
(`business/processes/...`), 3 Scenarios actualizados
(`business/scenarios/...`), `BR-REP-018` reescrita, 1 assertion de
`scripts/test-scenarios.ts` corregida.

## Constitution Check

| Principio | Estado | Evidencia |
|---|---|---|
| I. Business YAML fuente de verdad | PASS | `business/processes/repair-management-v1.3.yaml` y `business/rules/business-rules-v1.3.yaml` se corrigieron (nombre/descripcion de PROC-REP-212, edges, BR-REP-018) para que el grafo represente la decision funcional real -el codigo se adapto al proceso corregido, no al reves-; multi-Detalle sigue siendo MECHANISM_ONLY, no un Scenario nuevo (`npm run validate:v1.3` en verde) |
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
│   │                      # una accion por Detalle; _detalles_en_espera_de_control
│   │                      # exige TODOS COMPLETO antes de ofrecer APROBAR_CONTROL
│   ├── cierre.py          # aprobar_control: + detalle_id, calcular_puntaje y
│   │                      # marcar_reparacion_lista solo si todos APROBADO
│   └── taller.py          # + liberar_orden (comando de aplicacion)
├── services/
│   ├── reparaciones.py    # aprobar_control_tecnico: + detalle_id, PROC-REP-230
│   │                      # solo se registra (Si) cuando todos quedan APROBADO;
│   │                      # calcular_puntaje() docstring + accion="CONSOLIDAR_PUNTAJE"
│   ├── tomas.py            # PROC-REP-212 renombrado; + liberar_orden
│   │                      # (212[No]->213->170); seleccionar_detalle registra
│   │                      # 212[Si] SOLO si current_process in {180, 211}
│   │                      # (_ORIGENES_DE_LA_DECISION_212) y exige condicion
│   │                      # SIN_BLOQUEO; guard en validar_estacion_trabajo
│   └── ejecuciones.py      # reservar_insumos_e_iniciar_ejecucion: guard de
│                           # condicion SIN_BLOQUEO
├── application/progreso.py # etiqueta de PROC-REP-245: "Consolidar puntaje"
└── api/
    ├── schemas.py          # + finalizar_definicion, + detalle_id,
    │                       # + LiberarOrdenIn
    └── ordenes.py           # + POST /{orden_id}/release

app/backend/tests/
├── test_multidetalle.py               # 4 tests (E2E con historial y puntaje
│                                       # parcial explicitos, compat HP1,
│                                       # liberar con historial, control
│                                       # rechaza no-terminal)
├── test_detalle_bloqueado_guard.py    # 4 funciones / 7 casos
├── test_proc212_registro_condicional.py # NUEVO: 2 funciones
├── fixtures/hp_rep_001.py             # accion="CONSOLIDAR_PUNTAJE" (PROC-245)
└── test_caracterizacion_hp1.py        # 2 aserciones actualizadas (justificadas)

app/frontend/src/
├── api/ordenes.ts                                    # firmas ampliadas + liberarOrden
└── features/ordenes-reparacion/
    ├── AccionesOrden.tsx    # FormularioDefinirReparacion nuevo,
    │                        # APROBAR_CONTROL con detalle_id, caso LIBERAR_ORDEN
    └── PanelOrdenes.tsx      # ejecutor actualizado

business/processes/repair-management-v1.3.yaml   # PROC-REP-212 renombrado
                                # ("¿Iniciar un Detalle de reparacion?");
                                # edge PROC-REP-180->181 reemplazado por
                                # PROC-REP-180->212; descripciones 212/213;
                                # PROC-REP-245 renombrado ("Consolidar
                                # puntaje de la reparacion") y redescripto
business/rules/business-rules-v1.3.yaml           # BR-REP-018 reescrita;
                                # BR-REP-009 redescripta (puntaje inmediato
                                # por Detalle vs consolidacion en 245)
business/scenarios/repair-management-scenarios-v1.3.yaml  # HP-REP-001/002/003:
                                # steps[] via PROC-REP-212 en vez de 180->181 directo
scripts/test-scenarios.ts      # 1 assertion corregida (212::Si::181 ya no es
                                # mecanismo exclusivo de Multi-Detalle)

traceability/hp-rep-001.yaml   # FR-REP-067..071, TR-REP-065..069 (067/068
                                # redescriptos), TASK-REP-158..161 (+
                                # 061/062 a DONE), CODE-REP-121..129,
                                # TEST-REP-223..228, PROC-REP-212 (name +
                                # in_scenario: true), PROC-REP-245 (name)
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

Ver `traceability/hp-rep-001.yaml` (`TR-REP-065`..`TR-REP-069`) y el
detalle narrativo en [traceability.md](./traceability.md).

## Dependencies

- **Depende de**: `specs/009-mvp2-foundation/` (resolver completo de
  BR-REP-012, `CondicionReparacionDetail`, cierre de toma solo en
  resultados terminales -sin esto, completar un Detalle con otro
  pendiente habria lanzado una excepcion despues de persistir el
  inventario).
- **Nodos compartidos**: `PROC-REP-211` (ya evaluado por Slice 0, sin
  cambios) ahora tiene un edge adicional hacia `PROC-REP-212`, que a su
  vez tambien se alcanza desde `PROC-REP-180` -el mismo nodo sirve a
  ambos puntos de entrada, sin duplicar la decision.
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
