# Feature Specification: MVP v2 — Slice 1 (Multi-Detalle operativo)

**Feature Branch**: `mvp-v2-multidetalle`

**Created**: 2026-09-30

**Status**: Implemented (Slice funcional, transversal a Features existentes)

**Business Features involucradas**: `FEAT-REP-002`, `FEAT-REP-004`,
`FEAT-REP-005`, `FEAT-REP-006` (ninguna se completa: este slice amplia
mecanismos que ya tenian un slice implementado para HP-REP-001 con un
unico Detalle)

**Source Process**: `PROC-REP` V1.3

**Implemented Scenario**: `HP-REP-001` (sin cambios de comportamiento
para 1 Detalle; con 2 o mas Detalles recorre el mismo Scenario)

| Campo | Valor |
|---|---|
| `feature_status` (de las Features involucradas) | `draft` |
| `implemented_scenario` | `HP-REP-001` |
| `implemented_slice_status` | Este slice no es una Feature nueva: ver `traceability.md` |

> **ALCANCE.** Este slice NO agrega ningun Happy Path, Variant o
> Exception nuevo. Segun `docs/discovery/README.md` ("MVP v2 - Scope
> funcional cerrado"), la mecanica multi-Detalle (CAND-REP-028/029/030)
> es `MECHANISM_ONLY`: que una Orden tenga 1..N Detalles y que, al
> terminar uno, el tecnico pueda continuar con la misma toma o liberar
> la Orden, es comportamiento normal del proceso (BR-REP-018), no una
> desviacion que necesite su propio Scenario. Por eso no se numera como
> `01X-feat-rep-00X` sino como slice `010` transversal.

## Por que este slice

La Foundation de MVP v2 (`specs/009-mvp2-foundation/`) dejo el dominio
listo para Multi-Detalle -el resolver de BR-REP-012 ya acepta N
Detalles, `OrdenReparacion.reparaciones_detail` ya es una lista, los
computed fields (`total`, `puntaje_total`) ya suman sobre todos los
Detalles- pero documento explicitamente el gap pendiente en su seccion
de Edge Cases:

> "`ABIERTA_TRABAJABLE` / `EN_EJECUCION` / `REQUIERE_REVISION` /
> `PENDIENTE_RECURSOS` desde la API: el resolver los clasifica, pero
> `application.ingreso.definir_reparacion` sigue aceptando un unico
> Detalle por llamada -multi-Detalle operativo por API es un slice
> posterior-."

Este slice cierra ese gap. El analisis encontro tres funciones que
todavia asumian un unico Detalle a pesar de que el modelo de datos ya
era una lista:

1. `application.ingreso.definir_reparacion` creaba un Detalle y
   habilitaba la Orden en la misma llamada: una Orden nunca podia
   recibir un segundo Detalle por API.
2. `application.acciones.detalle_trabajable` devolvia solo el primer
   Detalle trabajable, ocultando cualquier otro a la UI.
3. `services.reparaciones.aprobar_control_tecnico` aprobaba todos los
   Detalles COMPLETO de una vez y exigia que TODOS lo estuvieran antes
   de aprobar ninguno.

Tambien encontro dos Tasks ya previstas y documentadas como
`NOT_IMPLEMENTED` desde `specs/004-feat-rep-004-hp-slice/`
(`TASK-REP-061`, `TASK-REP-062`): PROC-REP-212 (¿el tecnico quiere
seguir?) y PROC-REP-213 (liberar la Orden). Este slice las completa.

## User Scenarios & Testing *(mandatory)*

### User Story `US-REP-003`\* — Definir varios Detalles antes de habilitar (Priority: P1)

Como **Recepcionista**, quiero poder registrar mas de un Detalle de
Reparacion para la misma Orden antes de que quede habilitada, para que
un equipo con varios trabajos pendientes (por ejemplo, bateria y
pantalla) se defina completo desde el ingreso.

\* No se crea un ID nuevo de User Story: esta capacidad amplia
`US-REP-003` (`FEAT-REP-002`), que ya cubre "registrar los Detalles de
Reparacion que el equipo necesita".

**Why this priority**: es la precondicion de todo lo demas -sin poder
definir 2 Detalles, no hay nada que seleccionar, ejecutar ni controlar
por separado.

**Independent Test**:
`tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`,
`tests/test_multidetalle.py::test_hp_rep_001_un_solo_detalle_sigue_igual`.

**Acceptance Scenarios**:

1. **Given** una Orden en REQUERIMIENTO, **When** Recepcion define un
   Detalle con `finalizar_definicion=false`, **Then** el Detalle se
   agrega, la Orden sigue en REQUERIMIENTO y `DEFINIR_REPARACION` sigue
   disponible.
2. **Given** esa misma Orden, **When** Recepcion define un segundo
   Detalle sin pasar `finalizar_definicion` (default `true`), **Then**
   se agrega el segundo Detalle Y se genera el comprobante de
   recepcion, se valida factibilidad sobre los dos Detalles y la Orden
   queda HABILITADA -un unico comprobante para toda la Orden, no uno
   por Detalle.
3. **Given** una Orden a la que Recepcion define un unico Detalle sin
   tocar `finalizar_definicion`, **When** se compara contra el
   comportamiento anterior a este slice, **Then** el resultado es
   identico: HP-REP-001 con 1 Detalle no cambia.

---

### User Story `US-REP-007`\* — Elegir cual Detalle trabajar cuando hay varios (Priority: P1)

Como **Tecnico**, quiero que la Orden me ofrezca una accion "Iniciar
el Detalle" por cada Detalle realmente trabajable, para poder elegir
yo cual empezar en vez de que el sistema me imponga uno.

\* Amplia `US-REP-007` (`FEAT-REP-005`), que ya cubre "elegir cual
Detalle trabajar".

**Independent Test**:
`tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`,
`tests/test_detalle_bloqueado_guard.py`.

**Acceptance Scenarios**:

1. **Given** una Orden tomada con 2 Detalles DEFINIDO y SIN_BLOQUEO,
   **When** se consulta `acciones_disponibles`, **Then** aparecen 2
   acciones `INICIAR_DETALLE`, una por Detalle, sin que el backend
   elija arbitrariamente una.
2. **Given** esa Orden con solo 1 Detalle trabajable (el otro ya
   COMPLETO), **When** se consulta `acciones_disponibles`, **Then**
   aparece una unica accion `INICIAR_DETALLE`, con el `detalle_id` del
   que sigue pendiente.

**Correccion de revision - guard de backend**: "Detalle trabajable" es
`DEFINIDO + SIN_BLOQUEO` (Foundation, `application/acciones.py`), pero
antes de esta correccion solo `acciones_disponibles` respetaba la
condicion: una llamada directa de API a `seleccionar_detalle`,
`validar_estacion_trabajo` o `reservar_insumos_e_iniciar_ejecucion`
con un `detalle_id` bloqueado (`BLOQUEADO_POR_RECURSOS` o
`REQUIERE_DEFINICION`) no la exigia. Los tres services ahora la
rechazan tambien (`PrecondicionInvalidaError`), sin que la UI necesite
ocultar el boton para que la regla se cumpla:

3. **Given** un Detalle `DEFINIDO + BLOQUEADO_POR_RECURSOS` o
   `DEFINIDO + REQUIERE_DEFINICION`, **When** se llama directamente a
   `seleccionar_detalle` o `reservar_insumos_e_iniciar_ejecucion` con
   su `detalle_id` -sin pasar por `acciones_disponibles`-, **Then** se
   rechaza.
4. **Given** una Orden EN_COLA cuyo unico Detalle esta bloqueado,
   **When** se llama a `validar_estacion_trabajo`, **Then** devuelve
   invalido ("la Orden no tiene ningun Detalle trabajable"), igual que
   si no hubiera ningun Detalle.

---

### User Story `US-REP-006`\* — ¿Iniciar un Detalle de reparacion, o liberar la Orden? (Priority: P1)

Como **Tecnico**, con la Orden tomada y sin ninguna Ejecucion en curso
-recien tomada, o con un Detalle recien terminado-, quiero que el
sistema me pregunte si quiero iniciar un Detalle o liberar la Orden,
para poder seguir trabajando sin volver a tomarla, o liberarla
explicitamente si no voy a seguir ahora.

\* Amplia `US-REP-006` (`FEAT-REP-004`), que declaraba explicitamente
`slice_note: "Sin liberacion explicita"` antes de este slice.

**Correccion de revision**: `PROC-REP-212` se renombro de "¿Tecnico
desea continuar trabajando esta Orden?" a "¿Iniciar un Detalle de
reparacion?", y el grafo del proceso se corrigio para que se alcance
SIEMPRE que hay toma activa y ninguna Ejecucion en curso -no solo
despues de completar un Detalle-: `PROC-REP-180` (tomar) ya no va
directo a `PROC-REP-181` (seleccionar), pasa por `PROC-REP-212`
primero. Ver `business/processes/repair-management-v1.3.yaml` (nodo y
edges) y `business/rules/business-rules-v1.3.yaml` (`BR-REP-018`).

**Independent Test**:
`tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`
(Casos B y C, con aserciones de historial),
`tests/test_multidetalle.py::test_liberar_orden_devuelve_la_orden_a_en_cola`
(Caso A).

**Acceptance Scenarios**:

1. **Caso A - liberar inmediatamente despues de tomar**: **Given** una
   Orden recien tomada, sin haber seleccionado ni iniciado ningun
   Detalle, **When** el tecnico libera (`POST /release`), **Then** el
   historial registra exactamente `180 -> 212 [No] -> 213 -> 170`, la
   toma queda CERRADA, `estado_workflow = EN_COLA` y
   `current_process = PROC-REP-170`.
2. **Caso B - iniciar el primer Detalle**: **Given** esa misma Orden
   recien tomada, **When** el tecnico inicia un Detalle
   (`POST /details/{id}/start`), **Then** el historial registra
   `180 -> 212 [Si] -> 181 -> 174 -> 185`.
3. **Caso C - completar DET-001 y continuar con DET-002**: **Given**
   una Orden con 2 Detalles tomada, **When** el tecnico completa la
   Ejecucion del primer Detalle y el resolver (`PROC-REP-211`) da
   `ABIERTA_TRABAJABLE`, **Then** la toma sigue ACTIVA (no se cierra ni
   se crea una nueva) y, al iniciar el segundo Detalle, el historial
   registra `211 [ABIERTA_TRABAJABLE] -> 212 [Si] -> 181 -> 174 -> 185`,
   sin volver a pasar por `180`.
4. **Given** una Orden con el ultimo Detalle recien completado
   (resolver = `COMPLETA`), **When** se consulta `acciones_disponibles`,
   **Then** `LIBERAR_ORDEN` ya no aparece: `evaluar_situacion_orden` ya
   cerro la toma automaticamente (comportamiento de Slice 0, sin
   cambios) y ese camino nunca pasa por `PROC-REP-212`.

No se persiste ningun estado tipo `DECIDIO_CONTINUAR`: la decision
queda representada unicamente en el historial (BR-REP-018).

---

### User Story `US-REP-010`\* — Aprobar el control tecnico Detalle por Detalle (Priority: P1)

Como **Recepcionista**, con TODOS los Detalles de la Orden ya
COMPLETO, quiero poder aprobar el control tecnico Detalle por Detalle
-en vez de en un unico paso para toda la Orden-, para que la
aprobacion sea realmente granular como exige BR-REP-008. PROC-REP-220
sigue alcanzandose solo cuando la Orden entera es terminal: lo que
cambia es que, a partir de ahi, cada Detalle se aprueba por separado.

\* Amplia `US-REP-010` (`FEAT-REP-006`); su docstring original ya decia
"Recepcion controla la Orden completa pero aprueba Detalle por
Detalle. El MVP implementa solo la aprobacion total" -este slice
completa esa brecha.

**Correccion de revision (BR-REP-009/PROC-REP-245)**: aprobar un
Detalle no solo cambia su `control_estado`: tambien hace que su
puntaje empiece a aportar a `puntaje_total` de inmediato (computed
field, Slice 0), sin esperar a que el resto de los Detalles se
aprueben. `PROC-REP-245` ("Consolidar puntaje de la reparacion", antes
"Calcular puntaje de la reparacion") no crea ese puntaje: solo
consolida/registra el total en el historial cuando el control completo
de la Orden termina.

**Independent Test**:
`tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`,
`tests/test_multidetalle.py::test_control_tecnico_rechaza_si_algun_detalle_no_es_terminal`.

**Acceptance Scenarios**:

1. **Given** una Orden con DET-001 COMPLETO y DET-002 todavia
   DEFINIDO (no terminal), **When** Recepcion intenta aprobar el
   control -con o sin `detalle_id`-, **Then** se rechaza
   (`PrecondicionInvalidaError`, 409): PROC-REP-220 no se alcanza
   mientras quede un Detalle no terminal, ni siquiera para aprobar el
   que ya esta COMPLETO. `acciones_disponibles` tampoco ofrece
   `APROBAR_CONTROL` en ese estado.
2. **Given** esa Orden con DET-002 tambien COMPLETO, **When** Recepcion
   aprueba el control con `detalle_id=DET-001`, **Then** solo DET-001
   queda `control_estado APROBADO`, `puntaje_total` ya refleja
   unicamente el puntaje de DET-001 (aunque DET-002 siga sin aprobar),
   la Orden NO pasa a REPARACION_LISTA todavia (DET-002 sigue
   PENDIENTE) y el historial registra UNICAMENTE `PROC-REP-220` -NO
   `PROC-REP-230`, que significaria "algun Detalle RECHAZADO" (fuera de
   scope), no "todavia falta aprobar otro"-.
3. **Given** esa misma Orden, **When** Recepcion aprueba
   `detalle_id=DET-002`, **Then** con los 2 Detalles APROBADO el
   historial encadena `PROC-REP-220 -> PROC-REP-230 [Si] ->
   PROC-REP-245 -> PROC-REP-240` (REPARACION_LISTA) en esa misma
   llamada.
4. **Given** una Orden con un unico Detalle COMPLETO, **When** Recepcion
   aprueba el control sin pasar `detalle_id` (compatibilidad), **Then**
   el comportamiento es identico al de antes de este slice: aprueba
   ese unico Detalle y encadena `220 -> 230 [Si] -> 245 -> 240` en el
   mismo paso.

### Edge Cases

- **Rechazo de control (`RECHAZADO`)**: fuera de scope (EXC-REP-005).
  `EstadoControl` sigue teniendo solo `PENDIENTE`/`APROBADO`.
  **Correccion de revision**: `PROC-REP-230` se registra UNICAMENTE
  cuando esa aprobacion deja TODOS los Detalles APROBADO, y siempre con
  observacion "Si" -"No" significaria que algun Detalle fue RECHAZADO
  (fuera de scope), nunca "todavia falta aprobar otro". Una aprobacion
  parcial no registra `PROC-REP-230` en absoluto (ni "Si" ni "No"), solo
  `PROC-REP-220`.
- **Recursos insuficientes, interrupcion, EN_REVISION, control
  rechazado, devolucion RT, RT_INTERNO / RMA_GARANTIA_REPARACION**:
  explicitamente fuera de scope de este slice (ver `NO tocar` en el
  brief del agente). Ningun camino nuevo los alcanza.
- **Liberar sin toma activa, o con una Ejecucion en curso**: rechazado
  por `services.tomas.liberar_orden` (`PrecondicionInvalidaError`, 409)
  -no se agrego logica de interrupcion, solo la precondicion minima.
- **`LIBERAR_ORDEN` con un unico Detalle**: sigue apareciendo mientras
  haya una toma activa y ninguna Ejecucion en curso (por ejemplo, entre
  tomar la Orden y empezar a trabajarla), consistente con PROC-REP-211
  siendo el unico punto que cierra la toma automaticamente sin pasar
  por PROC-REP-212.
- **`seleccionar_detalle` sobre un Detalle bloqueado**: rechazado
  (`PrecondicionInvalidaError`) aunque el caller no haya consultado
  `acciones_disponibles` antes -el guard de backend no confia en que la
  UI ya filtro (ver `test_detalle_bloqueado_guard.py`).

## Requirements *(mandatory)*

### Functional Requirements

Los identificadores amplian FR existentes de `traceability/hp-rep-001.yaml`
(ver "Por que no hay IDs nuevos de US/ACC" en `traceability.md`), mas
cinco nuevos que cuelgan de System Actions ya existentes:

- **FR-REP-067** *(nuevo)*: permitir definir mas de un Detalle sobre la
  misma Orden antes de habilitarla, mediante un parametro aditivo
  (`finalizar_definicion`) que pospone comprobante, factibilidad y
  habilitacion hasta el ultimo Detalle.
- **FR-REP-068** *(nuevo)*: ofrecer una accion `INICIAR_DETALLE` por
  cada Detalle DEFINIDO y SIN_BLOQUEO, sin elegir arbitrariamente uno
  solo cuando hay varios trabajables.
- **FR-REP-069** *(nuevo)*: preguntar siempre -con toma activa y sin
  Ejecucion en curso- si el tecnico quiere iniciar un Detalle
  (`PROC-REP-212`) o liberar la Orden (`PROC-REP-213`), tanto
  inmediatamente despues de tomarla como despues de completar un
  Detalle con otro todavia trabajable; devolver la Orden a EN_COLA sin
  cerrar la toma automaticamente mientras quede trabajo.
- **FR-REP-070** *(nuevo)*: aprobar el control tecnico Detalle por
  Detalle (`detalle_id` opcional) solo cuando la Orden entera es
  terminal, marcando REPARACION_LISTA (y registrando PROC-REP-230/245/
  240) unicamente cuando esa aprobacion deja todos los Detalles con
  control APROBADO -nunca en una aprobacion parcial.
- **FR-REP-071** *(nuevo)*: rechazar, a nivel backend y no solo en la
  UI, la seleccion o el inicio de un Detalle DEFINIDO pero bloqueado
  (`BLOQUEADO_POR_RECURSOS` o `REQUIERE_DEFINICION`): solo
  DEFINIDO+SIN_BLOQUEO es trabajable.

### Key Entities *(include if feature involves data)*

Ningun modelo de dominio nuevo. `ReparacionDetail`, `TomaOrden`,
`EjecucionReparacion` y el resolver de BR-REP-012 ya estaban listos
desde Slice 0 -este slice es enteramente capa de aplicacion y servicio.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-032**: los 316 tests de la baseline (Foundation) siguen en
  verde, mas 13 tests nuevos de Multi-Detalle (4 en `test_multidetalle.py`
  + 4 funciones/7 casos en `test_detalle_bloqueado_guard.py` + 2 en
  `test_proc212_registro_condicional.py`) -329 en total-, sin ningun
  cambio de expectativa salvo los dos documentados en
  `test_caracterizacion_hp1.py` (`detalle_id` de `APROBAR_CONTROL` y la
  nueva accion `LIBERAR_ORDEN`).
- **SC-033**: una Orden puede recibir 2 Detalles por API
  (`POST /details` dos veces) y recorrer HP-REP-001 completo hasta
  REPARACION_LISTA, con un unico comprobante de recepcion y movimientos
  de inventario vinculados al Detalle correcto.
- **SC-034**: HP-REP-001 con 1 Detalle no cambia de comportamiento
  observable para el usuario: una unica llamada a `POST /details` sigue
  agregando el Detalle y habilitando la Orden en el mismo paso.
- **SC-035**: el control tecnico puede aprobarse Detalle por Detalle;
  ni `PROC-REP-230`/`245`/`240` se registran en una aprobacion parcial,
  ni `REPARACION_LISTA` se alcanza hasta que todos estan APROBADO.
- **SC-036**: `PROC-REP-212` ("¿Iniciar un Detalle de reparacion?") se
  alcanza siempre que hay toma activa y ninguna Ejecucion en curso -el
  grafo real (`business/processes/repair-management-v1.3.yaml`) lo
  conecta desde `PROC-REP-180`, no solo desde `PROC-REP-211`-, y el
  historial permite reconstruir `212 [No] -> 213 -> 170` o
  `212 [Si] -> 181` en cualquiera de los dos casos. `seleccionar_detalle`
  solo registra `212 [Si]` cuando `current_process` realmente viene de
  esa decision (`PROC-REP-180` o `PROC-REP-211`); una reentrada sin
  pasar de nuevo por ahi no duplica `212`.
- **SC-037**: un Detalle `DEFINIDO` pero bloqueado
  (`BLOQUEADO_POR_RECURSOS` o `REQUIERE_DEFINICION`) es rechazado por
  `seleccionar_detalle`, `validar_estacion_trabajo` y
  `reservar_insumos_e_iniciar_ejecucion`, no solo ocultado por
  `acciones_disponibles`.
- **SC-038** *(correccion de revision, BR-REP-009/PROC-REP-245)*: al
  aprobar un Detalle, `puntaje_total` refleja su aporte de inmediato
  -es un computed field, no algo que `PROC-REP-245` "cree"-.
  `PROC-REP-245` ("Consolidar puntaje de la reparacion") solo se
  registra en el historial junto con la aprobacion que deja TODOS los
  Detalles APROBADO, nunca antes.

## Assumptions

- Multi-Detalle es comportamiento normal de HP-REP-001, no un Scenario
  nuevo (`docs/discovery/README.md`).
- El rechazo de control (`RECHAZADO`), la interrupcion de Ejecucion, y
  los origenes `RT_INTERNO`/`RMA_GARANTIA_REPARACION` siguen fuera de
  scope; otro slice los implementa en paralelo.
- La ejecucion de Detalles sigue siendo secuencial (una Ejecucion activa
  a la vez por Orden, BR-REP-007): Multi-Detalle no habilita trabajo
  concurrente sobre dos Detalles de la misma Orden.
