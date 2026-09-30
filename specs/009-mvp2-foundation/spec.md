# Feature Specification: MVP v2 — Slice 0 (Foundation)

**Feature Branch**: `mvp-v2`

**Created**: 2026-09-30

**Status**: Implemented (Foundation slice, transversal)

**Business Features involucradas**: `FEAT-REP-001`, `FEAT-REP-005`, `FEAT-REP-007`
(ninguna se completa: este slice amplia mecanismos que ya tenian un
slice implementado para HP-REP-001)

**Source Process**: `PROC-REP` V1.3

**Implemented Scenario**: `HP-REP-001` (sin cambios de comportamiento,
salvo el fix deliberado de BR-REP-017)

| Campo | Valor |
|---|---|
| `feature_status` (de las Features involucradas) | `draft` |
| `implemented_scenario` | `HP-REP-001` |
| `implemented_slice_status` | Este slice no es una Feature: ver `traceability.md` |

> **ALCANCE.** Este slice NO agrega ningun Happy Path, Variant o
> Exception nuevo. Es la base tecnica comun que consumiran los slices
> siguientes (HP-REP-002, HP-REP-003, EN_REVISION, recursos, retrabajo),
> preservando exactamente el comportamiento observable de HP-REP-001 -
> con la unica excepcion deliberada de BR-REP-017 (Registrar Pago)-.
> Por eso no se numera como `010-feat-rep-00X` sino como slice `009`
> transversal: no pertenece a una sola Feature de negocio.

## Por que este slice

El analisis de gap MVP v1 -> MVP v2 identifico seis puntos donde el
codigo dice explicitamente "esto es solo para HP-REP-001" y que los
siete slices funcionales siguientes (HP-REP-002/003, EN_REVISION,
recursos insuficientes, ejecucion interrumpida, REQUIERE_REVISION,
control rechazado) necesitan generalizados **antes** de poder
construirse sin acoplarse de nuevo a un solo Scenario:

1. `application/happy_path.py` decidia `acciones_disponibles()` y
   `progreso()` sobre una tupla fija de 32 nodos de HP-REP-001.
2. `OrigenOrden` solo tenia `CLIENTE_EXTERNO`.
3. `ReparacionDetail` no distinguia "avance tecnico" de "condicion de
   bloqueo": no habia donde representar `BLOQUEADO_POR_RECURSOS` ni
   `REQUIERE_DEFINICION`.
4. `evaluar_situacion_orden` (PROC-REP-211, BR-REP-012) solo sabia
   calcular `COMPLETA` y lanzaba una excepcion para cualquier otra
   combinacion legitima de Detalles.
5. Esa misma excepcion, disparada DESPUES de que
   `aplicar_movimientos_inventario` ya habia persistido la Orden y
   descontado stock, era un riesgo de persistencia parcial latente.
6. `registrar_pago` no exigia ningun rol: BR-REP-017 ya define que un
   Tecnico no puede registrar un Pago, y el codigo todavia tenia la
   semantica vieja.

## User Scenarios & Testing *(mandatory)*

### User Story `US-REP-017`* — Impedir que un Tecnico registre un Pago (Priority: P1)

Como **Administrador** (o cualquier rol no-Tecnico activo), quiero que
el sistema impida que un Tecnico registre un Pago, para que la
autorizacion de BR-REP-017 se cumpla de verdad y no dependa de que la
UI oculte un boton.

\* No se crea un nuevo ID de User Story en la trazabilidad: esta
capacidad amplia `US-REP-012` (`FEAT-REP-007`), que ya cubre Registrar
Pago. Se referencia aqui solo para narrar el cambio.

**Why this priority**: es la correccion de un bug funcional confirmado,
no una capacidad nueva.

**Independent Test**: `tests/test_services_autorizacion.py::test_registrar_pago_rechaza_al_tecnico`
y `tests/test_api_reconcile.py::test_un_tecnico_no_puede_registrar_un_pago_por_http`.

**Acceptance Scenarios**:

1. **Given** un Tecnico activo, **When** intenta registrar un Pago,
   **Then** el backend lo rechaza (`PrecondicionInvalidaError`, 409),
   sin importar si la UI le muestra o no el boton.
2. **Given** un Administrador, Recepcionista o Coordinador RMA activo,
   **When** registra un Pago, **Then** la operacion se completa igual
   que antes.
3. **Given** la Orden con saldo pendiente, **When** se consulta
   `acciones_disponibles`, **Then** `REGISTRAR_PAGO` declara
   `roles: [ADMINISTRADOR, RECEPCION, COORDINADOR_RMA]` en vez de
   `roles: []`.

---

### User Story `US-REP-018`\* — Arquitectura preparada para MVP v2, sin activar sus flujos (Priority: P1)

Como **desarrollador** de los slices siguientes, quiero que el dominio y
la capa de aplicacion ya sepan representar y clasificar lo que
HP-REP-002, HP-REP-003 y las Variants/Exceptions van a necesitar, para
no tener que volver a tocar `application/happy_path.py` ni el resolver
de BR-REP-012 en cada slice nuevo.

\* Tampoco es un ID nuevo de trazabilidad: en `traceability/hp-rep-001.yaml`
esta capacidad cuelga de `US-REP-001` (origenes y politica) y
`US-REP-009` (resolver y condicion del Detalle), que ya existian.

**Why this priority**: sin esto, cada slice funcional futuro repetiria
el mismo refactor de navegacion, con el riesgo de volver a acoplarse a
un Scenario particular.

**Independent Test**: `tests/test_resolucion_orden.py`,
`tests/test_politica_origen.py`,
`tests/test_completar_ejecucion_consistencia.py`,
`tests/test_caracterizacion_hp1.py`.

**Acceptance Scenarios**:

1. **Given** una lista de Detalles con cualquier combinacion legitima de
   estado y condicion, **When** se llama a `resolver_situacion_orden`,
   **Then** devuelve uno de los ocho resultados de BR-REP-012 sin
   lanzar una excepcion.
2. **Given** una Orden con dos Detalles donde solo uno se completa,
   **When** se llama a `completar_ejecucion` (comando de aplicacion,
   con repositories reales), **Then** el comando termina en
   `ABIERTA_TRABAJABLE` sin haber dejado el inventario persistido a
   medias.
3. **Given** los tres valores de `OrigenOrden`, **When** se consulta
   `politica_de(origen)`, **Then** devuelve la condicion comercial y los
   requerimientos de proceso (comprobante, notificacion, entrega a
   cliente, informar RT) que le corresponden, aunque solo
   `CLIENTE_EXTERNO` tenga hoy un comando de creacion.
4. **Given** los 10 estados principales del recorrido de HP-REP-001,
   **When** se consulta `acciones_disponibles()` y `progreso()`,
   **Then** el resultado es identico al de antes del refactor, salvo
   los roles de `REGISTRAR_PAGO`.
5. **Given** un JSON de Orden persistido antes de Slice 0 (sin el campo
   `condicion` en cada Detalle), **When** se carga con el modelo
   actual, **Then** se reconstruye sin tocarse, con `condicion`
   resuelta a `SIN_BLOQUEO`.

### Edge Cases

- **`CONTEXTO_INCONSISTENTE`**: fail-safe tecnico del resolver para una
  combinacion que el dominio actual no deberia poder producir. No es un
  estado de negocio ni se persiste como tal.
- **`TODO_CANCELADO`**: la matriz de BR-REP-012 lo contempla, pero con
  el catalogo actual (`EstadoReparacionDetail` sin `CANCELADO`, la
  Cancelacion -BR-REP-014- fuera de scope de MVP v2) es formalmente
  correcto pero inalcanzable.
- **`RT_INTERNO` y `RMA_GARANTIA_REPARACION`**: existen en `OrigenOrden`
  y tienen `PoliticaOrigen` declarada, pero ningun comando de la API
  puede crear una Orden con esos origenes todavia.
- **`EstadoWorkflow.EN_REVISION`**: existe en el enum, pero ninguna
  Orden creada en este slice puede alcanzarlo: el circuito
  PROC-REP-055/065/068/075 no esta conectado.
- **`ABIERTA_TRABAJABLE` / `EN_EJECUCION` / `REQUIERE_REVISION` /
  `PENDIENTE_RECURSOS` desde la API**: el resolver los clasifica, pero
  `application.ingreso.definir_reparacion` sigue aceptando un unico
  Detalle por llamada -multi-Detalle operativo por API es un slice
  posterior-, asi que solo son alcanzables componiendo services
  directamente (como en `tests/test_completar_ejecucion_consistencia.py`).

## Requirements *(mandatory)*

### Functional Requirements

Los identificadores reutilizan y amplian FR existentes de
`traceability/hp-rep-001.yaml` (ver seccion "Por que no hay IDs nuevos
de US/ACC" en `traceability.md`), mas uno nuevo:

- **FR-REP-037** *(ampliado)*: calcular la situacion agregada de la
  Orden con la matriz de prioridad **completa** de BR-REP-012 (ocho
  resultados), sin lanzar para ningun resultado de negocio legitimo.
  *(antes: solo `COMPLETA`, con excepcion para el resto)*
- **FR-REP-048** *(ampliado)*: Registrar un Pago exige usuario activo y
  rol distinto de Tecnico (BR-REP-017). *(antes: solo usuario activo)*
- **FR-REP-066** *(nuevo)*: representar en el dominio los origenes de
  MVP v2 (`RT_INTERNO`, `RMA_GARANTIA_REPARACION`) y la politica de
  proceso/comercial de cada Origen, sin habilitar todavia su creacion
  por API.

### Key Entities *(include if feature involves data)*

- **`CondicionReparacionDetail`**: segunda dimension del Detalle,
  independiente de `EstadoReparacionDetail`. Valores: `SIN_BLOQUEO`,
  `REQUIERE_DEFINICION`, `BLOQUEADO_POR_RECURSOS`. Default
  `SIN_BLOQUEO`, compatible con JSON persistido antes de este slice.
- **`PoliticaOrigen`** (`app.domain.politicas`): frozen dataclass con
  `condicion_comercial`, `requiere_comprobante_recepcion`,
  `requiere_notificacion`, `requiere_entrega_cliente`,
  `requiere_informar_rt`. Una por cada valor de `OrigenOrden`.
- **`ResultadoEvaluacionOrden`** (`app.services.resolucion`, movido
  desde `app.services.ordenes`): los ocho resultados de BR-REP-012.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-028**: los 283 tests de la baseline y HP-REP-001 completo (los
  tres niveles: services, persistido, API) siguen en verde despues del
  refactor, sin ningun cambio de expectativa salvo los roles de
  `REGISTRAR_PAGO`.
- **SC-029**: un Tecnico activo recibe 409 al intentar registrar un
  Pago, tanto a nivel service como HTTP.
- **SC-030**: `resolver_situacion_orden` clasifica los ocho resultados
  de BR-REP-012 sin lanzar, para cualquier combinacion de Detalles
  representable con el dominio actual.
- **SC-031**: un JSON de Orden anterior a este slice se sigue cargando
  sin modificarse.

## Assumptions

- Ningun Scenario nuevo (HP-REP-002/003, Variants, Exceptions) se
  activa en este slice: es exclusivamente arquitectura y correccion de
  bug.
- La condicion de bloqueo (`CondicionReparacionDetail`) y los
  resultados del resolver mas alla de `COMPLETA` estan clasificados y
  testeados, pero no tienen todavia ningun comando de la API que los
  produzca: eso es responsabilidad de los slices siguientes.
- `application/happy_path.py` no se elimina: queda como fachada de
  compatibilidad sobre `application/acciones.py` y
  `application/progreso.py`.
