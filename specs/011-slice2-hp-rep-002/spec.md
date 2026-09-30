# Feature Specification: HP-REP-002 — Equipo RT Interno

**Feature Branch**: `mvp-v2-hp2`

**Created**: 2026-09-30

**Status**: Implemented (Scenario HP-REP-002, E2E)

**Business Features involucradas**: `FEAT-REP-001`, `FEAT-REP-002`,
`FEAT-REP-003`, `FEAT-REP-004`, `FEAT-REP-005`, `FEAT-REP-006`,
`FEAT-REP-007`, `FEAT-REP-008` (las mismas 8 que activa HP-REP-001;
ninguna se completa: HP-REP-002 es un segundo Scenario sobre el mismo
conjunto de Features `draft`)

**Source Process**: `PROC-REP` V1.3

**Implemented Scenario**: `HP-REP-002` (`business/scenarios/repair-management-scenarios-v1.3.yaml`)

| Campo | Valor |
|---|---|
| `feature_status` (de las Features involucradas) | `draft` |
| `implemented_scenario` | `HP-REP-002` (segundo Scenario sobre las mismas 8 Features; ver `traceability.md`) |
| `implemented_slice_status` | `IMPLEMENTED` |

> **ALCANCE.** Este slice implementa HP-REP-002 completo: una Orden de
> origen `RT_INTERNO` (equipo propio de Rosario Tecno, gestionado en
> Gestion RT) recorre el mismo tramo tecnico que HP-REP-001 -definir
> Detalle, factibilidad, toma, ejecucion, control tecnico, puntaje- sin
> cambios de comportamiento, y diverge en el ingreso (sin Cliente, sin
> comprobante de recepcion) y en el cierre (informar a Gestion RT y
> devolver el equipo, sin notificar, cobrar ni entregar a un cliente).
> NO agrega Multi-Detalle, HP-REP-003, ninguna Variant/Exception, ni
> EN_REVISION: todo eso queda fuera de este slice (ver Assumptions).

## Por que este slice

MVP v2 Foundation (`specs/009-mvp2-foundation/`) dejo el dominio
preparado para representar `RT_INTERNO` y su `PoliticaOrigen`, pero
ningun comando de la API podia crear ni operar una Orden con ese origen.
Este slice conecta ese origen al flujo operativo real, siguiendo
exactamente `business/scenarios/repair-management-scenarios-v1.3.yaml`
(HP-REP-002) y `docs/discovery/README.md` (seccion HP-REP-002).

## User Scenarios & Testing *(mandatory)*

### User Story `US-REP-017` — Ingresar un equipo RT sin registrar un Cliente (Priority: P1)

Como **Recepcionista**, quiero ingresar un equipo `RT_INTERNO` con su
referencia de contexto, sin tener que registrar un Cliente, para
reflejar que el equipo es propio de Rosario Tecno.

**Independent Test**: `tests/test_hp_rep_002.py::test_orden_rt_nace_sin_cliente_con_referencia_de_contexto`,
`tests/test_api_hp_rep_002.py::test_crear_orden_rt_no_pide_ni_devuelve_cliente`.

**Acceptance Scenarios**:

1. **Given** un Recepcionista activo, **When** crea una Orden `RT_INTERNO`
   con equipo y `referencia_rt`, **Then** la Orden nace en
   `REQUERIMIENTO` con `cliente: null` (PROC-REP-010 -> 020 -> 040).
2. **Given** esa Orden, **When** Recepcion define la reparacion,
   **Then** PROC-REP-050 resuelve "No" (BR-REP-016) y PROC-REP-060 no se
   ejecuta: `comprobante_recepcion.generado` queda `false`.
3. **Given** un JSON de Orden persistido antes de este slice (sin el
   campo `referencia_rt`), **When** se carga con el modelo actual,
   **Then** se reconstruye sin tocarse, con `referencia_rt` resuelto a
   `null` y `cliente` intacto.

---

### User Story `US-REP-018` — Una Orden RT nunca ofrece cobro ni entrega a cliente (Priority: P1)

Como **Administrador**, quiero que una Orden `RT_INTERNO` no ofrezca
cobrar, registrar Pago, notificar ni entregar a un cliente, porque no
hay ningun cliente involucrado -y quiero que el backend lo garantice,
no solo que la UI oculte el boton.

**Independent Test**: `tests/test_hp_rep_002.py::test_rt_interno_no_ofrece_registrar_pago_ni_notificar_ni_entregar`,
`::test_registrar_pago_rechaza_una_orden_rt_interno`,
`::test_registrar_pago_sigue_funcionando_en_cliente_externo`,
`tests/test_api_hp_rep_002.py::test_registrar_pago_rechaza_rt_interno_con_admin_activo_por_http`,
`::test_registrar_pago_cliente_externo_no_se_ve_afectado`.

**Acceptance Scenarios**:

1. **Given** una Orden `RT_INTERNO` `REPARACION_LISTA`, **When** se
   consulta `acciones_disponibles`, **Then** ni `REGISTRAR_PAGO` ni
   `NOTIFICAR` ni `ENTREGAR` aparecen.
2. **Given** esa misma Orden, **When** un Administrador activo invoca
   `registrar_pago` directamente (no por la UI), **Then** el backend lo
   rechaza (`PrecondicionInvalidaError`, 409): `PoliticaOrigen.condicion_comercial`
   no es `COBRABLE`.
3. **Given** una Orden `CLIENTE_EXTERNO`, **When** Administrador,
   Recepcion o Coordinador RMA registran un Pago, **Then** la operacion
   se completa exactamente igual que antes de este slice.
4. **Given** el precio snapshot del Detalle ($80000, por ejemplo),
   **When** se consulta el resumen comercial, **Then** `total` y
   `saldo` conservan ese valor nominal -no se pone en 0-, pero
   `condicion_comercial: NO_COBRABLE_AL_CLIENTE` le dice a la API/UI que
   no es una deuda a cobrar.

---

### User Story `US-REP-019` — Informar el resultado a Gestion RT (Priority: P1)

Como **paso de Sistema** (`PROC-REP-290`, `actor: ACT-SYSTEM` en
PROC-REP V1.3), se informa el resultado de la reparacion a Gestion RT
antes de que el equipo se devuelva, para dejar constancia formal.

**Independent Test**: `tests/test_hp_rep_002.py::test_informar_rt_registra_250_no_y_290`,
`::test_informar_rt_no_registra_ningun_actor_humano`,
`::test_informar_rt_se_publica_como_accion_de_sistema_sin_actor`,
`tests/test_api_hp_rep_002.py::test_hp_rep_002_end_to_end_por_http`.

**Acceptance Scenarios**:

1. **Given** una Orden `RT_INTERNO` `REPARACION_LISTA`, **When** se
   informa el resultado, **Then** se registran PROC-REP-250
   (observacion "No") y PROC-REP-290, sin pasar por PROC-REP-260/265/266/280.
2. **Given** que PROC-REP-290 es `actor: ACT-SYSTEM` (ningun actor
   humano definido), **When** se dispara este paso, **Then** ni el
   service ni el comando de aplicacion ni el endpoint reciben
   `usuario_id`, y el historial queda con `usuario_id: null`.
3. **Given** la accion publicada en `acciones_disponibles`, **When** se
   inspecciona `INFORMAR_RT`, **Then** declara `requiere_actor: false` -
   una dimension distinta de `roles: []`: indica que no hay actor
   humano que autorizar (nodo `ACT-SYSTEM`).

---

### User Story `US-REP-020` — Devolver el equipo a Gestion RT (Priority: P1)

Como **Administrador o Recepcionista**, quiero devolver el equipo a
Gestion RT una vez informado el resultado, sin que el sistema afirme un
estado `ENTREGADA` que el negocio todavia no definio.

**Independent Test**: `tests/test_hp_rep_002.py::test_devolucion_rt_llega_a_evt_999_sin_marcar_entregada`,
`::test_devolver_rt_no_puede_ejecutarse_antes_de_informar`,
`::test_devolver_rt_esta_disponible_recien_despues_de_informar`,
`::test_rt_interno_no_exige_saldo_cero_para_devolver`.

**Acceptance Scenarios**:

1. **Given** una Orden `RT_INTERNO` que todavia NO paso por
   PROC-REP-290, **When** se intenta devolver el equipo, **Then** el
   backend lo rechaza: PROC-REP-270 (RT) exige `current_process ==
   "PROC-REP-290"`.
2. **Given** una Orden ya informada a RT, **When** Administracion o
   Recepcion devuelven el equipo, **Then** `current_process` pasa a
   `EVT-REP-999`, sin exigir saldo 0, comprobante final ni garantia.
3. **Given** esa devolucion, **When** se inspecciona `estado_workflow`,
   **Then** sigue en `REPARACION_LISTA` -NO pasa a `ENTREGADA`-: el
   estado terminal definitivo de `RT_INTERNO` sigue
   `PENDIENTE_DE_DEFINIR` segun V1.3 (`business/scenarios/repair-management-scenarios-v1.3.yaml`,
   `HP-REP-002.expected.terminal_state`).
4. **Given** la Orden en `EVT-REP-999`, **When** se consulta
   `acciones_disponibles`, **Then** devuelve una lista vacia: el fin de
   proceso se detecta tambien por `current_process`, no solo por
   `estado_workflow == ENTREGADA`.

### Edge Cases

- **Registrar Pago invocado directo (no por la UI)**: el rechazo vive en
  `services.pagos.registrar_pago`, no solo en `acciones_disponibles`.
  Cualquier caller -service, comando de aplicacion, endpoint HTTP- queda
  cubierto por el mismo chequeo.
- **`requiere_actor` en acciones ya existentes**: todas las acciones
  humanas normales (`DEFINIR_REPARACION`, `TOMAR`, `APROBAR_CONTROL`,
  etc.) declaran `requiere_actor: true` (el default): este slice no les
  cambia el comportamiento.
- **`RMA_GARANTIA_REPARACION`**: `generar_comprobante_recepcion` ahora
  consulta `PoliticaOrigen` para los tres origenes, no solo para
  `RT_INTERNO`; esto NO activa HP-REP-003 -sigue sin haber comando de
  creacion para ese origen-, es una generalizacion segura de un service
  ya existente.
- **Multi-Detalle**: HP-REP-002 se probo con un unico Detalle
  (`detail_count: 1` en el Scenario). El resolver de BR-REP-012 ya
  soporta varios Detalles (Foundation), pero conectar ese flujo operativo
  es responsabilidad de otro slice (`specs/010-slice1-multidetalle/`, en
  otra rama) y no se toca aqui.

## Requirements *(mandatory)*

### Functional Requirements

Ver el detalle completo en `traceability/hp-rep-002.yaml` (`FR-REP-072`
a `FR-REP-079`). Resumen:

- **FR-REP-072**: crear la Orden `RT_INTERNO` sin exigir Cliente,
  conservando el equipo y `referencia_rt`, con cero Detalles.
- **FR-REP-073**: no generar comprobante de recepcion para un Origen
  cuya politica no lo requiere.
- **FR-REP-074**: no ofrecer Registrar Pago, Notificar ni Entregar en
  una Orden `NO_COBRABLE_AL_CLIENTE` sin entrega a cliente.
- **FR-REP-075**: informar el resultado a Gestion RT solo con la Orden
  `REPARACION_LISTA`, antes de poder devolver el equipo.
- **FR-REP-076**: devolver el equipo solo despues de informar, sin
  exigir saldo cero, comprobante final ni garantia.
- **FR-REP-077**: no asentar `ENTREGADA` al devolver un equipo
  `RT_INTERNO`.
- **FR-REP-078**: ruta de progreso propia para `RT_INTERNO`, distinta de
  `CLIENTE_EXTERNO`.
- **FR-REP-079** *(nuevo tras revision)*: rechazar Registrar Pago a
  nivel backend para toda Orden cuyo Origen no sea `COBRABLE`, sin
  depender de que la UI oculte la accion.

### Key Entities *(include if feature involves data)*

- **`OrdenReparacion.cliente`**: `Cliente | None`, `None` para
  `RT_INTERNO`.
- **`OrdenReparacion.referencia_rt`**: `str | None`, el contexto minimo
  que PROC-REP-020 recibe de Gestion RT.
- **`AccionDisponible.requiere_actor`** / **`AccionOut.requiere_actor`**:
  `bool`, default `true`. `false` marca un nodo `actor: ACT-SYSTEM` (hoy
  solo `INFORMAR_RT`/PROC-REP-290): ningun actor humano que autorizar,
  distinto de una accion humana con `requiere_actor: true`.
- **`ResumenComercialOut.condicion_comercial`**: `str`
  (`COBRABLE`/`NO_COBRABLE_AL_CLIENTE`/`NO_COBRABLE`), la
  `PoliticaOrigen.condicion_comercial` de BR-REP-016. Le dice a la
  API/UI si `total`/`saldo` representan una deuda real o un valor
  nominal.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-032**: los 316 tests de la baseline de MVP v2 Foundation siguen
  en verde despues de este slice, sin ningun cambio de expectativa.
- **SC-033**: HP-REP-002 completo (creacion -> definicion -> cola ->
  toma -> ejecucion -> control -> informar RT -> devolver) se recorre
  end-to-end por HTTP, en un unico test (`test_hp_rep_002_end_to_end_por_http`).
- **SC-034**: `registrar_pago` rechaza toda Orden cuyo Origen no sea
  `COBRABLE`, verificado a nivel service y HTTP, sin afectar
  `CLIENTE_EXTERNO`.
- **SC-035**: PROC-REP-290 no registra ningun `usuario_id` en el
  historial, y la accion publicada declara `requiere_actor: false`.
- **SC-036**: una Orden `RT_INTERNO` devuelta llega a `current_process
  == EVT-REP-999` sin `estado_workflow == ENTREGADA`.
- **SC-037**: `CLIENTE_EXTERNO` (HP-REP-001) sigue comportandose
  identico: mismos 316 tests, mas los nuevos de regresion cruzada
  (`test_cliente_externo_sigue_funcionando_igual_junto_a_rt_interno`,
  `test_registrar_pago_cliente_externo_no_se_ve_afectado`).

## Assumptions

- Ningun otro Scenario, Variant o Exception se activa en este slice:
  HP-REP-003, VAR-REP-001/002/003 y EXC-REP-001..005 quedan fuera.
- Multi-Detalle operativo (mas de un Detalle por Orden via API) es
  responsabilidad de otro slice/rama (`specs/010-slice1-multidetalle/`);
  este slice no lo toca.
- El estado terminal definitivo de una Orden `RT_INTERNO` sigue
  `PENDIENTE_DE_DEFINIR` (V1.3): no se crea `DEVUELTA_RT` ni se asume
  `ENTREGADA`.
- `RMA_GARANTIA_REPARACION` sigue sin comando de creacion en la API:
  la generalizacion de `generar_comprobante_recepcion` por
  `PoliticaOrigen` no lo activa.
