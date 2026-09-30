# Traceability: Slice 1 (MVP v2 - Multi-Detalle operativo)

Vista narrativa. La fuente machine-readable es
`traceability/hp-rep-001.yaml` (items + links). Este slice **amplia**
items existentes y agrega los minimos necesarios; no declara ninguna
Feature, User Story ni System Action nueva.

## Por que no hay IDs nuevos de US/ACC/Feature

Multi-Detalle es, segun `docs/discovery/README.md` ("MVP v2 - Scope
funcional cerrado"), `MECHANISM_ONLY`: que una Orden tenga 1..N
Detalles y que el tecnico pueda continuar con otro o liberar la Orden
al terminar uno, es comportamiento normal del proceso (BR-REP-018), no
un Scenario nuevo. En consecuencia tampoco es una Feature de negocio
propia: es transversal a cuatro Features ya declaradas (`FEAT-REP-002`,
`FEAT-REP-004`, `FEAT-REP-005`, `FEAT-REP-006`). Siguiendo el mismo
criterio que `specs/009-mvp2-foundation/` (Constitution, Principio I:
el YAML de negocio es la fuente de verdad, no se agregan Features fuera
de el), cada Functional Requirement nuevo cuelga del
`system_action`/`user_story` existente que ya representaba esa porcion
del dominio:

| Mecanismo | FR | ACC / US / Feature reutilizados |
|---|---|---|
| Definir N Detalles antes de habilitar | `FR-REP-067` (nuevo) | `ACC-REP-004` → `US-REP-003` → `FEAT-REP-002` |
| Elegir cual Detalle trabajar entre varios | `FR-REP-068` (nuevo) | `ACC-REP-011` → `US-REP-007` → `FEAT-REP-005` |
| Continuar la misma toma o liberar la Orden (PROC-REP-212/213) | `FR-REP-069` (nuevo) | `ACC-REP-010` → `US-REP-006` → `FEAT-REP-004` |
| Control tecnico granular por Detalle | `FR-REP-070` (nuevo) | `ACC-REP-017` → `US-REP-010` → `FEAT-REP-006` |

`ACC-REP-010` ("Abrir la toma o participacion activa del tecnico sobre
la Orden") ademas gana un link `covers` hacia `PROC-REP-213`
(`Liberar Orden de Reparacion`), que hasta este slice no estaba
cubierto por ninguna System Action.

### Aclaracion de negocio sobre liberar la Orden (BR-REP-018/PROC-REP-212/213)

Revisando la implementacion se confirmo una decision funcional que el
texto original de `BR-REP-018`/`PROC-REP-212` dejaba ambigua: liberar
la Orden (`LIBERAR_ORDEN`, PROC-REP-213) **no depende de haber
completado antes ningun Detalle**. La regla es, siempre, *toma activa Y
ausencia de Ejecucion activa* -eso alcanza para liberar, tanto
inmediatamente despues de tomar la Orden (antes de seleccionar o
iniciar el primer Detalle) como despues de completar un Detalle con
otros todavia pendientes-. `business/rules/business-rules-v1.3.yaml`
(`BR-REP-018`) y `business/processes/repair-management-v1.3.yaml`
(`PROC-REP-212`, `PROC-REP-213`) se actualizaron con esta aclaracion,
de forma minima, para que el texto de negocio y el codigo no
diverjan; el codigo ya se comportaba asi desde la primera version de
este slice, asi que no hubo cambio de comportamiento, solo de
documentacion.

## Functional Requirement -> Technical Requirement

| FR | TR | Que agrega Slice 1 |
|---|---|---|
| `FR-REP-067` | `TR-REP-065` (nuevo) | `definir_reparacion` acepta `finalizar_definicion` (aditivo, default `True`); agrega el Detalle siempre, y solo genera comprobante/factibilidad/habilitacion cuando es verdadero |
| `FR-REP-068` | `TR-REP-066` (nuevo) | `detalles_trabajables` (plural) enumera todos los Detalles trabajables; `acciones_disponibles` emite un `INICIAR_DETALLE` por cada uno |
| `FR-REP-069` | `TR-REP-067` (nuevo) | `services.tomas.liberar_orden` (PROC-REP-213) cierra la toma activa y devuelve la Orden a EN_COLA; solo `evaluar_situacion_orden` y `liberar_orden` cierran una toma, nunca otra ruta |
| `FR-REP-070` | `TR-REP-068` (nuevo) | `aprobar_control_tecnico` sigue exigiendo que TODOS los Detalles esten COMPLETO antes de aprobar ninguno (PROC-REP-220 solo se alcanza con la Orden terminal); con `detalle_id` aprueba solo ese Detalle; `aprobar_control` solo llama a `marcar_reparacion_lista` cuando TODOS quedan APROBADO |

## Technical Requirement -> Task -> Code

| TR | TASK | CODE (archivo::simbolo) |
|---|---|---|
| `TR-REP-065` | `TASK-REP-158` | `app/backend/app/application/ingreso.py::definir_reparacion` |
| `TR-REP-066` | `TASK-REP-159` | `app/backend/app/application/acciones.py::detalles_trabajables` |
| `TR-REP-067` | `TASK-REP-061`, `TASK-REP-062` | `app/backend/app/services/tomas.py::liberar_orden`, `app/backend/app/application/taller.py::liberar_orden` |
| `TR-REP-068` | `TASK-REP-160` | `app/backend/app/services/reparaciones.py::aprobar_control_tecnico`, `app/backend/app/application/cierre.py::aprobar_control` |

## Internal Tests (nuevos en Slice 1)

| TEST (archivo::función) | Verifica |
|---|---|
| `tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http` | `FR-REP-067`, `FR-REP-068`, `FR-REP-070` (recorrido completo con 2 Detalles: definicion, selección, ejecución sucesiva, toma que no se cierra hasta terminar el segundo, control granular, snapshots y movimientos de inventario independientes, comprobante único) |
| `tests/test_multidetalle.py::test_hp_rep_001_un_solo_detalle_sigue_igual` | `FR-REP-067` (compatibilidad: HP-REP-001 con 1 Detalle sin cambios) |
| `tests/test_multidetalle.py::test_liberar_orden_devuelve_la_orden_a_en_cola` | `FR-REP-069` |
| `tests/test_multidetalle.py::test_control_tecnico_rechaza_si_algun_detalle_no_es_terminal` | `FR-REP-070` (test negativo: PROC-REP-220 no se alcanza mientras quede un Detalle no terminal, ni siquiera para aprobar uno que ya esta COMPLETO) |
| `tests/test_caracterizacion_hp1.py::test_toma_activa_sin_ejecucion` *(actualizado)* | `FR-REP-069` (LIBERAR_ORDEN pasa a estar disponible) |
| `tests/test_caracterizacion_hp1.py::test_espera_control` *(actualizado)* | `FR-REP-070` (APROBAR_CONTROL ahora declara `detalle_id`) |

Total: 4 tests nuevos + 2 aserciones actualizadas (documentadas en
`tasks.md`, Fase 5). El backend pasa de 316 a 320 tests, todos en
verde.

## Tasks actualizadas de slices anteriores

Slice 1 completa dos tareas que estaban `NOT_IMPLEMENTED` desde
`specs/004-feat-rep-004-hp-slice/`, sin reabrir ese spec:

| TASK | Spec original | Antes | Ahora |
|---|---|---|---|
| `TASK-REP-061` | `004-feat-rep-004-hp-slice` | `NOT_IMPLEMENTED` (PROC-REP-212) | `DONE` (la decision no persiste estado propio: es implicita entre seleccionar otro Detalle o liberar, ver `TASK-REP-062`) |
| `TASK-REP-062` | `004-feat-rep-004-hp-slice` | `NOT_IMPLEMENTED` (PROC-REP-213) | `DONE` (`services/tomas.py::liberar_orden`) |

Los items de negocio `PROC-REP-212` y `PROC-REP-213`
(`traceability/hp-rep-001.yaml`) pasan de `implemented: false` a
`implemented: true`. `in_scenario` se mantiene en `false`: el recorrido
guionado de HP-REP-001 con un unico Detalle -el que `business/scenarios/
repair-management-scenarios-v1.3.yaml` describe paso a paso- nunca
alcanza estos nodos; solo son recorridos cuando la Orden tiene mas de
un Detalle, que es mecanica del proceso y no un paso obligatorio del
Scenario.

## UAT

Ningun UAT nuevo: Slice 1 amplia capacidades de User Stories ya
existentes (`US-REP-003`, `US-REP-006`, `US-REP-007`, `US-REP-010`),
cuyos UAT (`UAT-REP-003`, `UAT-REP-006`, `UAT-REP-007`, `UAT-REP-010`)
ya estaban declarados y siguen `PENDING`. Los 3 tests internos nuevos
de este slice, igual que el resto de la suite, NO son evidencia de
aceptacion de usuario (Constitution, Principio IX).
