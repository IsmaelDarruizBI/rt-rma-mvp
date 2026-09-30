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
`tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`.

**Acceptance Scenarios**:

1. **Given** una Orden tomada con 2 Detalles DEFINIDO y SIN_BLOQUEO,
   **When** se consulta `acciones_disponibles`, **Then** aparecen 2
   acciones `INICIAR_DETALLE`, una por Detalle, sin que el backend
   elija arbitrariamente una.
2. **Given** esa Orden con solo 1 Detalle trabajable (el otro ya
   COMPLETO), **When** se consulta `acciones_disponibles`, **Then**
   aparece una unica accion `INICIAR_DETALLE`, con el `detalle_id` del
   que sigue pendiente.

---

### User Story `US-REP-006`\* — Continuar con otro Detalle o liberar la Orden (Priority: P1)

Como **Tecnico**, con la Orden tomada y un Detalle recien terminado,
quiero poder seguir trabajando otro Detalle sin volver a tomar la
Orden, o liberarla explicitamente si no voy a seguir ahora, para que
otro tecnico (o yo mismo mas tarde) pueda tomarla.

\* Amplia `US-REP-006` (`FEAT-REP-004`), que declaraba explicitamente
`slice_note: "Sin liberacion explicita"` antes de este slice.

**Independent Test**:
`tests/test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http`,
`tests/test_multidetalle.py::test_liberar_orden_devuelve_la_orden_a_en_cola`.

**Acceptance Scenarios**:

1. **Given** una Orden con 2 Detalles, tomada, **When** el tecnico
   completa la Ejecucion del primer Detalle, **Then** el resolver
   (PROC-REP-211) da `ABIERTA_TRABAJABLE`, la toma sigue ACTIVA (no se
   cierra ni se crea una nueva) y el tecnico puede seleccionar el
   segundo Detalle sin tomar la Orden de nuevo (BR-REP-018).
2. **Given** esa misma situacion, **When** el tecnico decide liberar la
   Orden en vez de continuar (`POST /release`, PROC-REP-212 "No" ->
   213), **Then** la toma activa se cierra con fecha de fin y la Orden
   vuelve a EN_COLA, disponible para el mismo u otro tecnico.
3. **Given** una Orden recien tomada, sin haber seleccionado ni
   iniciado todavia ningun Detalle, **When** se consulta
   `acciones_disponibles`, **Then** `LIBERAR_ORDEN` ya aparece -la
   regla general es *toma activa Y ausencia de Ejecucion activa*, no
   "despues de completar un Detalle": liberar no depende de haber
   trabajado nada todavia (ampliacion de BR-REP-018/PROC-REP-213, ver
   `business/rules/business-rules-v1.3.yaml`).
4. **Given** una Orden con el ultimo Detalle recien completado
   (resolver = `COMPLETA`), **When** se consulta `acciones_disponibles`,
   **Then** `LIBERAR_ORDEN` ya no aparece: `evaluar_situacion_orden` ya
   cerro la toma automaticamente (comportamiento de Slice 0, sin
   cambios).

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
   queda `control_estado APROBADO`, la Orden NO pasa a
   REPARACION_LISTA todavia (DET-002 sigue PENDIENTE).
3. **Given** esa misma Orden, **When** Recepcion aprueba
   `detalle_id=DET-002`, **Then** con los 2 Detalles APROBADO recien
   ahi se ejecuta PROC-REP-245 (puntaje) y PROC-REP-240
   (REPARACION_LISTA).
4. **Given** una Orden con un unico Detalle COMPLETO, **When** Recepcion
   aprueba el control sin pasar `detalle_id` (compatibilidad), **Then**
   el comportamiento es identico al de antes de este slice: aprueba
   ese unico Detalle y pasa a REPARACION_LISTA en el mismo paso.

### Edge Cases

- **Rechazo de control (`RECHAZADO`)**: fuera de scope (EXC-REP-005).
  `EstadoControl` sigue teniendo solo `PENDIENTE`/`APROBADO`; el
  resolver de PROC-REP-230 solo distingue "todos aprobados" (Si) de
  "todavia no" (No), nunca "alguno rechazado".
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
  siendo el unico punto que cierra la toma automaticamente.

## Requirements *(mandatory)*

### Functional Requirements

Los identificadores amplian FR existentes de `traceability/hp-rep-001.yaml`
(ver "Por que no hay IDs nuevos de US/ACC" en `traceability.md`), mas
cuatro nuevos que cuelgan de System Actions ya existentes:

- **FR-REP-067** *(nuevo)*: permitir definir mas de un Detalle sobre la
  misma Orden antes de habilitarla, mediante un parametro aditivo
  (`finalizar_definicion`) que pospone comprobante, factibilidad y
  habilitacion hasta el ultimo Detalle.
- **FR-REP-068** *(nuevo)*: ofrecer una accion `INICIAR_DETALLE` por
  cada Detalle DEFINIDO y SIN_BLOQUEO, sin elegir arbitrariamente uno
  solo cuando hay varios trabajables.
- **FR-REP-069** *(nuevo)*: permitir que el tecnico continue trabajando
  la misma toma con otro Detalle trabajable, o la libere explicitamente,
  devolviendo la Orden a EN_COLA sin cerrar la toma automaticamente
  mientras quede trabajo.
- **FR-REP-070** *(nuevo)*: aprobar el control tecnico Detalle por
  Detalle (`detalle_id` opcional), marcando REPARACION_LISTA solo
  cuando todos los Detalles de la Orden quedan con control APROBADO.

### Key Entities *(include if feature involves data)*

Ningun modelo de dominio nuevo. `ReparacionDetail`, `TomaOrden`,
`EjecucionReparacion` y el resolver de BR-REP-012 ya estaban listos
desde Slice 0 -este slice es enteramente capa de aplicacion y servicio.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-032**: los 316 tests de la baseline (Foundation) siguen en
  verde, mas 4 tests nuevos de Multi-Detalle -320 en total-, sin ningun
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
- **SC-035**: el control tecnico puede aprobarse Detalle por Detalle, y
  `REPARACION_LISTA` no se alcanza hasta que todos estan APROBADO.

## Assumptions

- Multi-Detalle es comportamiento normal de HP-REP-001, no un Scenario
  nuevo (`docs/discovery/README.md`).
- El rechazo de control (`RECHAZADO`), la interrupcion de Ejecucion, y
  los origenes `RT_INTERNO`/`RMA_GARANTIA_REPARACION` siguen fuera de
  scope; otro slice los implementa en paralelo.
- La ejecucion de Detalles sigue siendo secuencial (una Ejecucion activa
  a la vez por Orden, BR-REP-007): Multi-Detalle no habilita trabajo
  concurrente sobre dos Detalles de la misma Orden.
