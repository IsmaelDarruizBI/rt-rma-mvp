# Traceability: Slice 0 (MVP v2 - Foundation)

Vista narrativa. La fuente machine-readable es
`traceability/hp-rep-001.yaml` (items + links). Este slice **amplia**
items existentes y agrega los mínimos necesarios; no declara ninguna
Feature, User Story ni System Action nueva.

## Por que no hay IDs nuevos de US/ACC/Feature

Slice 0 es transversal a tres Features ya declaradas (`FEAT-REP-001`,
`FEAT-REP-005`, `FEAT-REP-007`), no una capacidad de negocio propia. El
validador exige que todo `functional_requirement` derive de un
`system_action`, que toda `system_action` realice un `user_story`, y
que todo `user_story` pertenezca a una `feature`. En vez de inventar una
Feature "Foundation" que no existe en `business/features/*.yaml`
-violaria la Constitution, Principio I: el YAML de negocio es la fuente
de verdad, no se agregan Features fuera de el-, cada Functional
Requirement nuevo o ampliado cuelga del `system_action`/`user_story`
existente que ya representaba esa porcion del dominio:

| Mecanismo | FR | ACC / US / Feature reutilizados |
|---|---|---|
| Orígenes de MVP v2 + política por Origen | `FR-REP-066` (nuevo) | `ACC-REP-001` → `US-REP-001` → `FEAT-REP-001` |
| Resolver BR-REP-012 + condición del Detalle + fix de persistencia | `FR-REP-037` (ampliado) | `ACC-REP-016` → `US-REP-009` → `FEAT-REP-005` |
| Fix BR-REP-017 (Registrar Pago) | `FR-REP-048` (ampliado) | `ACC-REP-020` → `US-REP-012` → `FEAT-REP-007` |

## Functional Requirement -> Technical Requirement

| FR | TR | Que agrega Slice 0 |
|---|---|---|
| `FR-REP-037` | `TR-REP-022` *(ampliado)* | `evaluar_situacion_orden` separa clasificación (resolver puro) de efectos |
| `FR-REP-037` | `TR-REP-059` (nuevo) | `resolver_situacion_orden` clasifica los 8 resultados de BR-REP-012 sin lanzar |
| `FR-REP-037` | `TR-REP-060` (nuevo) | `CondicionReparacionDetail` separa el bloqueo del estado técnico, con default compatible |
| `FR-REP-037` | `TR-REP-061` (nuevo) | `completar_ejecucion` ya no puede fallar después de persistir el inventario |
| `FR-REP-066` | `TR-REP-057` (nuevo) | `OrigenOrden` + `EstadoWorkflow.EN_REVISION` aditivos |
| `FR-REP-066` | `TR-REP-058` (nuevo) | `domain.politicas.politica_de(origen)` |
| `FR-REP-066` | `TR-REP-062` (nuevo) | `acciones_disponibles` consulta la política del Origen |
| `FR-REP-066` | `TR-REP-063` (nuevo) | `progreso()` resuelve la ruta esperada por Origen |
| `FR-REP-048` | `TR-REP-045` *(ampliado)* | `registrar_pago` exige `ROLES_PAGO` |
| `FR-REP-048` | `TR-REP-064` (nuevo) | `ROLES_PAGO` como fuente única, consumida por backend y por `acciones_disponibles` |

## Technical Requirement -> Task -> Code

| TR | TASK | CODE (archivo::símbolo) |
|---|---|---|
| `TR-REP-057` | `TASK-REP-151` | `app/backend/app/domain/models/enums.py::OrigenOrden`, `::EstadoWorkflow` |
| `TR-REP-058` | `TASK-REP-152` | `app/backend/app/domain/politicas.py::politica_de` |
| `TR-REP-059` | `TASK-REP-088`, `TASK-REP-153` | `app/backend/app/services/resolucion.py::resolver_situacion_orden` |
| `TR-REP-060` | `TASK-REP-154` | `app/backend/app/domain/models/enums.py::CondicionReparacionDetail`, `app/backend/app/domain/models/reparacion.py::ReparacionDetail` |
| `TR-REP-061` | `TASK-REP-155` | `app/backend/app/services/ordenes.py::evaluar_situacion_orden` |
| `TR-REP-062` | `TASK-REP-156` | `app/backend/app/application/acciones.py::acciones_disponibles` |
| `TR-REP-063` | `TASK-REP-156` | `app/backend/app/application/progreso.py::progreso` |
| `TR-REP-064` | `TASK-REP-123`, `TASK-REP-157` | `app/backend/app/services/pagos.py::ROLES_PAGO` |

## Internal Tests (nuevos o renombrados en Slice 0)

| TEST (archivo::función) | Verifica |
|---|---|
| `tests/test_resolucion_orden.py` (13 funciones, matriz completa BR-REP-012) | `FR-REP-037` |
| `tests/test_completar_ejecucion_consistencia.py::test_completar_un_detalle_con_otro_pendiente_no_lanza` | `FR-REP-037` |
| `tests/test_politica_origen.py` (5 funciones) | `FR-REP-066` |
| `tests/test_hp_rep_001_persistido.py::test_un_json_anterior_a_slice_0_sigue_cargando` | `TR-REP-060` (compatibilidad JSON) |
| `tests/test_caracterizacion_hp1.py` (10 funciones) | `FR-REP-066` (acciones/progreso generalizados, comportamiento HP-REP-001 preservado) |
| `tests/test_services_autorizacion.py::test_registrar_pago_permite_administrador_recepcion_y_coordinador` *(renombrado)* | `FR-REP-048` |
| `tests/test_services_autorizacion.py::test_registrar_pago_rechaza_al_tecnico` (nuevo) | `FR-REP-048` |
| `tests/test_api_reconcile.py::test_un_tecnico_no_puede_registrar_un_pago_por_http` (nuevo) | `FR-REP-048` |

Total: 31 tests nuevos + 1 test renombrado (dividido en dos). El
backend pasa de 283 a 314 tests, todos en verde.

## Tasks actualizadas de slices anteriores

Slice 0 completa tres tareas que estaban `NOT_IMPLEMENTED` en slices
previos, sin reabrir esos specs:

| TASK | Spec original | Antes | Ahora |
|---|---|---|---|
| `TASK-REP-088` | `005-feat-rep-005-hp-slice` | `NOT_IMPLEMENTED` (ramas del resolver) | `DONE` (clasificación completa; `TODO_CANCELADO` formalmente correcta pero inalcanzable hasta que exista Cancelación) |
| `TASK-REP-123` | `007-feat-rep-007-hp-slice` | `NOT_IMPLEMENTED` (rol de Pago) | `DONE` (`ROLES_PAGO`) |

Y dos ítems quedan documentados como desactualizados por precisión,
sin cambiar su evidencia:

- `TASK-REP-002` (`001-feat-rep-001-hp-slice`): su descripción original
  decía "`OrigenOrden` con único valor `CLIENTE_EXTERNO`"; ya no es
  así. Se agregó una `note` apuntando a `TASK-REP-151`.
- `CODE-REP-082` (`ResultadoEvaluacionOrden`): se movió de
  `services/ordenes.py` a `services/resolucion.py` (re-exportado desde
  `ordenes.py` por compatibilidad); su `source` se actualizó.

## UAT

Ningún UAT nuevo: Slice 0 no entrega una capacidad de negocio
demostrable de punta a punta por sí sola (es arquitectura), así que no
corresponde un ítem de aceptación de usuario propio. Los UAT existentes
de `US-REP-001`, `US-REP-009` y `US-REP-012` siguen `PENDING`.
