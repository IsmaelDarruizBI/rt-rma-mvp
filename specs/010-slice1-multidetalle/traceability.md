# Traceability: Slice 1 (MVP v2 - Multi-Detalle operativo)

Vista narrativa. La fuente machine-readable es
`traceability/hp-rep-001.yaml` (items + links). Este slice **amplia**
items existentes y agrega los minimos necesarios; no declara ninguna
Feature, User Story ni System Action nueva.

## Por que no hay IDs nuevos de US/ACC/Feature

Multi-Detalle es, segun `docs/discovery/README.md` ("MVP v2 - Scope
funcional cerrado"), `MECHANISM_ONLY`: que una Orden tenga 1..N
Detalles y que el tecnico pueda iniciar otro Detalle o liberar la
Orden al terminar uno, es comportamiento normal del proceso
(BR-REP-018), no un Scenario nuevo. En consecuencia tampoco es una
Feature de negocio propia: es transversal a cuatro Features ya
declaradas (`FEAT-REP-002`, `FEAT-REP-004`, `FEAT-REP-005`,
`FEAT-REP-006`). Siguiendo el mismo criterio que
`specs/009-mvp2-foundation/` (Constitution, Principio I: el YAML de
negocio es la fuente de verdad, no se agregan Features fuera de el),
cada Functional Requirement nuevo cuelga del `system_action`/
`user_story` existente que ya representaba esa porcion del dominio:

| Mecanismo | FR | ACC / US / Feature reutilizados |
|---|---|---|
| Definir N Detalles antes de habilitar | `FR-REP-067` (nuevo) | `ACC-REP-004` → `US-REP-003` → `FEAT-REP-002` |
| Elegir cual Detalle trabajar entre varios | `FR-REP-068` (nuevo) | `ACC-REP-011` → `US-REP-007` → `FEAT-REP-005` |
| ¿Iniciar un Detalle, o liberar la Orden? (PROC-REP-212/213) | `FR-REP-069` (nuevo) | `ACC-REP-010` → `US-REP-006` → `FEAT-REP-004` |
| Control tecnico granular por Detalle | `FR-REP-070` (nuevo) | `ACC-REP-017` → `US-REP-010` → `FEAT-REP-006` |
| Guard de backend para Detalle trabajable | `FR-REP-071` (nuevo) | `ACC-REP-011` → `US-REP-007` → `FEAT-REP-005` |

`ACC-REP-010` ("Abrir la toma o participacion activa del tecnico sobre
la Orden") ademas gana un link `covers` hacia `PROC-REP-213`
(`Liberar Orden de Reparacion`), que hasta este slice no estaba
cubierto por ninguna System Action.

## Correcciones de revision (pre-merge)

Una revision del commit encontro tres inconsistencias con PROC-REP
V1.3 y las corrigio antes del merge, sin ampliar el scope ni crear
Scenario/Feature/User Story nuevos.

### 1. PROC-REP-212 renombrado, grafo corregido (no solo el texto)

La primera version de este slice ya dejaba liberar la Orden
inmediatamente despues de tomarla (sin exigir haber completado un
Detalle antes), pero el grafo de negocio y el historial no lo
representaban: `PROC-REP-212` solo era alcanzable, segun el texto
original, desde `PROC-REP-211` (continuacion multi-Detalle), y el edge
real `PROC-REP-180 -> PROC-REP-181` saltaba `PROC-REP-212` por
completo en el camino "recien tomada".

Se corrigio:

- `PROC-REP-212.name`: de "¿Tecnico desea continuar trabajando esta
  Orden?" a **"¿Iniciar un Detalle de reparacion?"**
  (`business/processes/repair-management-v1.3.yaml`).
- El edge `PROC-REP-180 -> PROC-REP-181` (directo) se reemplazo por
  `PROC-REP-180 -> PROC-REP-212` -el edge `PROC-REP-212 ->
  PROC-REP-181 [Si]` ya existia en el grafo, no hizo falta agregarlo-.
- `BR-REP-018` se reescribio para declarar la regla general: *toma
  activa Y ausencia de Ejecucion activa* habilita la decision, tanto
  recien tomada como despues de completar un Detalle.
- `business/scenarios/repair-management-scenarios-v1.3.yaml`:
  HP-REP-001, HP-REP-002 y HP-REP-003 actualizaron su `steps[]` -el
  edge literal `180 -> 181` paso a ser `180 -> 212` seguido de
  `212 -> 181 [Si]`-.
- `scripts/test-scenarios.ts`: la assertion "mecanica multi-Detalle
  (CAND-REP-028/029/030) sigue sin convertirse en Scenario real"
  declaraba `PROC-REP-212::Si::PROC-REP-181` como mecanismo prohibido
  en cualquier `steps[]` de Scenario -eso dejo de ser cierto: ahora es
  la rama que CUALQUIER Happy Path toma para seguir adelante-. Se
  corrigio para mantener prohibidos unicamente los edges que siguen
  siendo exclusivos de una continuacion multi-Detalle real
  (`PROC-REP-211 -> PROC-REP-212`, `PROC-REP-211 -> PROC-REP-170` sin
  toma activa) o de liberar (`PROC-REP-212 -> PROC-REP-213 [No]`).
- Codigo: `services.tomas.seleccionar_detalle` ahora registra
  `PROC-REP-212 [Si]` (via el helper privado
  `_registrar_decision_iniciar_detalle`) antes de `PROC-REP-181`;
  `services.tomas.liberar_orden` registra `PROC-REP-212 [No] ->
  PROC-REP-213 -> PROC-REP-170` (este ultimo ACT-SYSTEM), cierra la
  toma con fecha/hora y deja `estado_workflow=EN_COLA`,
  `current_process=PROC-REP-170`.

`traceability/hp-rep-001.yaml`: el `process_node` `PROC-REP-212`
actualiza su `name` y pasa `in_scenario: false -> true` (ahora es parte
del recorrido base de cualquier Happy Path, no solo mecanica
multi-Detalle).

### 2. Control granular: PROC-REP-230=No no es "falta aprobar otro"

Una aprobacion parcial (DET-001 aprobado, DET-002 todavia PENDIENTE)
registraba `PROC-REP-230` con observacion "No". Segun el Business
Process, `PROC-REP-230=No` significa que **algun Detalle fue
RECHAZADO** (fuera de scope, EXC-REP-005) -no "todavia falta aprobar
otro". Se corrigio `aprobar_control_tecnico` para NO registrar
`PROC-REP-230` en absoluto en una aprobacion parcial (unicamente
`PROC-REP-220`), y para registrarlo -siempre "Si"- solo cuando esa
aprobacion deja TODOS los Detalles APROBADO; recien ahi
`aprobar_control` encadena `PROC-REP-245`/`PROC-REP-240`.
`puntaje_total` sigue siendo un computed field (Slice 0): una
aprobacion parcial ya muestra su puntaje parcial sin necesidad de
registrar `PROC-REP-245` por adelantado.

### 3. Guard de "Detalle trabajable" solo en la UI, no en el backend

`application/acciones.py` ya filtraba por `DEFINIDO + SIN_BLOQUEO`,
pero `services.tomas.seleccionar_detalle`,
`services.tomas.validar_estacion_trabajo` y
`services.ejecuciones.reservar_insumos_e_iniciar_ejecucion` solo
validaban `estado == DEFINIDO`: una llamada directa de API con un
`detalle_id` bloqueado (`BLOQUEADO_POR_RECURSOS` o
`REQUIERE_DEFINICION`) no se rechazaba, aunque la UI nunca la
hubiera ofrecido. Los tres services ahora tambien exigen
`condicion == SIN_BLOQUEO`.

## Correcciones de revision, ronda 2

Dos inconsistencias finales detectadas en una segunda revision del
commit, corregidas sin ampliar scope.

### 4. BR-REP-009 / PROC-REP-245 — puntaje por Detalle vs consolidacion final

La correccion de la ronda 1 (punto 2 arriba: no usar
`PROC-REP-230=No` como "faltan controles") se mantuvo intacta. Lo que
se corrigio ahora fue la **interpretacion de negocio** de
`PROC-REP-245`, no el comportamiento computado -no habia bug-:
`OrdenReparacion.puntaje_total` ya sumaba los Detalles con control
APROBADO desde Slice 0, asi que un Detalle recien aprobado ya aportaba
su puntaje de inmediato, sin esperar a `PROC-REP-245`. El texto de
negocio no lo dejaba claro: `PROC-REP-245` se renombro de "Calcular
puntaje de la reparacion" a **"Consolidar puntaje de la reparacion"**
(`business/processes/repair-management-v1.3.yaml`), y su descripcion
-junto con `BR-REP-009` en `business/rules/business-rules-v1.3.yaml`-
ahora aclara que este nodo NO calcula el puntaje de cada Detalle por
primera vez, solo consolida/registra el total de la Orden cuando el
control tecnico completo termina satisfactoriamente. Por consistencia
se renombraron tambien la etiqueta de progreso
(`application/progreso.py`: "Calcular puntaje" -> "Consolidar
puntaje") y el `accion` del historial
(`services/reparaciones.py::calcular_puntaje`: `CALCULAR_PUNTAJE` ->
`CONSOLIDAR_PUNTAJE`, replicado en el fixture declarativo
`tests/fixtures/hp_rep_001.py`).

### 5. PROC-REP-212 [Si] no debe registrarse indiscriminadamente

`services.tomas.seleccionar_detalle` registraba `PROC-REP-212 [Si]` en
TODA llamada, acoplando el service a la idea de que toda seleccion de
Detalle implica esa decision. Se corrigio para que solo la registre
cuando la Orden realmente viene de ella -`current_process` en
`{PROC-REP-180, PROC-REP-211}`, sin usar Scenario ID ni un flag
persistido nuevo (`_ORIGENES_DE_LA_DECISION_212`)-. Verificado que hoy
esto no cambia ningun resultado observable: en todos los caminos
actualmente alcanzables, `current_process` ya es 180 o 211 cada vez
que `seleccionar_detalle` se llama sobre una Orden persistida. El
guard deja el service correcto para caminos futuros que puedan
reentrar a `PROC-REP-181` sin pasar por la decision -incompatibilidad
de estacion (PROC-REP-176/178/179) o reserva fallida (PROC-REP-186),
ninguno implementado en este slice-.

## Functional Requirement -> Technical Requirement

| FR | TR | Que agrega Slice 1 |
|---|---|---|
| `FR-REP-067` | `TR-REP-065` (nuevo) | `definir_reparacion` acepta `finalizar_definicion` (aditivo, default `True`); agrega el Detalle siempre, y solo genera comprobante/factibilidad/habilitacion cuando es verdadero |
| `FR-REP-068` | `TR-REP-066` (nuevo) | `detalles_trabajables` (plural) enumera todos los Detalles trabajables; `acciones_disponibles` emite un `INICIAR_DETALLE` por cada uno |
| `FR-REP-069` | `TR-REP-067` (nuevo) | `PROC-REP-212` se registra SOLO cuando `current_process` esta en `{PROC-REP-180, PROC-REP-211}` -no en toda llamada-: `seleccionar_detalle` encadena `212[Si]->181` en ese caso (sin duplicar 212 en una reentrada), `liberar_orden` encadena `212[No]->213->170` y deja `EN_COLA`/`current_process=PROC-REP-170` |
| `FR-REP-070` | `TR-REP-068` (nuevo) | `aprobar_control_tecnico` exige TODOS los Detalles COMPLETO antes de aprobar ninguno; el Detalle aprobado aporta su puntaje a `puntaje_total` de inmediato (BR-REP-009); una aprobacion parcial registra unicamente `PROC-REP-220` (nunca `PROC-REP-230`); `PROC-REP-230` (observacion "Si") y `PROC-REP-245` (consolidacion, no calculo)/`240` solo se encadenan cuando esa aprobacion deja todo APROBADO |
| `FR-REP-071` | `TR-REP-069` (nuevo) | `seleccionar_detalle`, `validar_estacion_trabajo` y `reservar_insumos_e_iniciar_ejecucion` rechazan un Detalle DEFINIDO pero bloqueado; el guard vive en el backend, no solo en `acciones_disponibles` |

## Technical Requirement -> Task -> Code

| TR | TASK | CODE (archivo::simbolo) |
|---|---|---|
| `TR-REP-065` | `TASK-REP-158` | `app/backend/app/application/ingreso.py::definir_reparacion` |
| `TR-REP-066` | `TASK-REP-159` | `app/backend/app/application/acciones.py::detalles_trabajables` |
| `TR-REP-067` | `TASK-REP-061`, `TASK-REP-062` | `app/backend/app/services/tomas.py::seleccionar_detalle`, `app/backend/app/services/tomas.py::liberar_orden`, `app/backend/app/application/taller.py::liberar_orden` |
| `TR-REP-068` | `TASK-REP-160` | `app/backend/app/services/reparaciones.py::aprobar_control_tecnico`, `app/backend/app/application/cierre.py::aprobar_control` |
| `TR-REP-069` | `TASK-REP-161` | `app/backend/app/services/tomas.py::seleccionar_detalle`, `app/backend/app/services/tomas.py::validar_estacion_trabajo`, `app/backend/app/services/ejecuciones.py::reservar_insumos_e_iniciar_ejecucion` |

## Internal Tests (nuevos en Slice 1)

| TEST (archivo::función) | Verifica |
|---|---|
| `tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http` | `FR-REP-067`, `FR-REP-068`, `FR-REP-069`, `FR-REP-070` (recorrido completo con 2 Detalles: definicion, seleccion con historial `212[Si]->181` explicito -Casos B y C-, ejecucion sucesiva, toma que no se cierra hasta terminar el segundo, control granular con historial exacto por aprobacion, snapshots y movimientos de inventario independientes, comprobante unico) |
| `tests/test_multidetalle.py::test_hp_rep_001_un_solo_detalle_sigue_igual` | `FR-REP-067` (compatibilidad: HP-REP-001 con 1 Detalle sin cambios) |
| `tests/test_multidetalle.py::test_liberar_orden_devuelve_la_orden_a_en_cola` | `FR-REP-069` (Caso A: `180 -> 212[No] -> 213 -> 170`, inmediatamente tras tomar, sin seleccionar ningun Detalle) |
| `tests/test_multidetalle.py::test_control_tecnico_rechaza_si_algun_detalle_no_es_terminal` | `FR-REP-070` (test negativo: PROC-REP-220 no se alcanza mientras quede un Detalle no terminal, ni siquiera para aprobar uno que ya esta COMPLETO) |
| `tests/test_detalle_bloqueado_guard.py` (4 funciones, 7 casos) | `FR-REP-071` (`seleccionar_detalle`, `validar_estacion_trabajo`, `reservar_insumos_e_iniciar_ejecucion` rechazan `BLOQUEADO_POR_RECURSOS`/`REQUIERE_DEFINICION`; control: `SIN_BLOQUEO` se acepta) |
| `tests/test_proc212_registro_condicional.py` (2 funciones) | `FR-REP-069` (212 [Si] se registra desde `PROC-REP-180`; una reentrada a `seleccionar_detalle` sin volver a pasar por 180/211 no duplica `PROC-REP-212`) |
| `tests/test_caracterizacion_hp1.py::test_toma_activa_sin_ejecucion` *(actualizado)* | `FR-REP-069` (LIBERAR_ORDEN pasa a estar disponible) |
| `tests/test_caracterizacion_hp1.py::test_espera_control` *(actualizado)* | `FR-REP-070` (APROBAR_CONTROL ahora declara `detalle_id`) |

Total: 4 tests en `test_multidetalle.py` (incluye la nueva asercion de
`puntaje_total` parcial) + 1 archivo nuevo
(`test_detalle_bloqueado_guard.py`, 4 funciones/7 casos) + 1 archivo
nuevo (`test_proc212_registro_condicional.py`, 2 funciones) + 2
aserciones de caracterizacion actualizadas (documentadas en
`tasks.md`, Fase 5). El backend pasa de 316 a 329 tests, todos en
verde.

## Tasks actualizadas de slices anteriores

Slice 1 completa dos tareas que estaban `NOT_IMPLEMENTED` desde
`specs/004-feat-rep-004-hp-slice/`, sin reabrir ese spec:

| TASK | Spec original | Antes | Ahora |
|---|---|---|---|
| `TASK-REP-061` | `004-feat-rep-004-hp-slice` | `NOT_IMPLEMENTED` (PROC-REP-212) | `DONE` (la decision no persiste estado propio: se registra en el historial via `seleccionar_detalle`/`liberar_orden`) |
| `TASK-REP-062` | `004-feat-rep-004-hp-slice` | `NOT_IMPLEMENTED` (PROC-REP-213) | `DONE` (`services/tomas.py::liberar_orden`) |

Los items de negocio `PROC-REP-212` y `PROC-REP-213`
(`traceability/hp-rep-001.yaml`) pasan de `implemented: false` a
`implemented: true`. A diferencia de la primera version de este slice,
`PROC-REP-212` ahora tambien pasa `in_scenario: false -> true`: tras la
correccion del grafo (ver arriba), es parte del recorrido base de
CUALQUIER Happy Path -incluido HP-REP-001 con un unico Detalle-, no
solo de una continuacion multi-Detalle. `PROC-REP-213` se mantiene en
`in_scenario: false`: ningun Happy Path lo recorre (siempre elige "Si,
iniciar un Detalle"), solo se alcanza cuando el tecnico decide liberar,
que es una desviacion, no el camino feliz.

## UAT

Ningun UAT nuevo: Slice 1 amplia capacidades de User Stories ya
existentes (`US-REP-003`, `US-REP-006`, `US-REP-007`, `US-REP-010`),
cuyos UAT (`UAT-REP-003`, `UAT-REP-006`, `UAT-REP-007`, `UAT-REP-010`)
ya estaban declarados y siguen `PENDING`. Los tests internos de este
slice, igual que el resto de la suite, NO son evidencia de aceptacion
de usuario (Constitution, Principio IX).
