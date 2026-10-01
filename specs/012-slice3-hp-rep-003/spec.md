# Feature Specification: HP-REP-003 — Garantía de reparación RMA

**Feature Branch**: `mvp-v2-slice3-hp-rep-003`

**Created**: 2026-09-30

**Status**: Implemented (Scenario HP-REP-003, E2E, Happy Path)

**Business Features involucradas**: `FEAT-REP-001`..`FEAT-REP-008` (las
mismas 8 que activan HP-REP-001 y HP-REP-002; ninguna se completa)

**Source Process**: `PROC-REP` V1.3

**Implemented Scenario**: `HP-REP-003`
(`business/scenarios/repair-management-scenarios-v1.3.yaml`)

**Reglas**: `BR-REP-015` (snapshot), `BR-REP-016` (condición comercial por
Origen), `BR-REP-017` (cobro), `BR-REP-018` (toma), `BR-REP-019` (garantía
RMA: Orden nueva vinculada y Detalle origen).

| Campo | Valor |
|---|---|
| `feature_status` | `draft` |
| `implemented_scenario` | `HP-REP-001`, `HP-REP-002`, `HP-REP-003` |
| `implemented_slice_status` | `IMPLEMENTED` |

> **ALCANCE.** Desde una Orden **ENTREGADA**, Recepción selecciona un
> Detalle ya reparado y genera una **NUEVA** Orden de origen
> `RMA_GARANTIA_REPARACION`. La Orden origen no se reabre ni se modifica.
> La nueva Orden converge con el circuito técnico de HP-REP-001 y termina
> `ENTREGADA` / `EVT-REP-999`.

## Flujo implementado

```
EVT-REP-002 → PROC-REP-035 → 040 → 045 → 070 → 050 → 060 → 080 → 090 → 140
→ 150 → 170 → 172 → 180 → 212 → 181 → 174 → 185 → 190 → 200 → 210 → 211
→ 220 → 230 → 245 → 240 → 250 → 260 → 265 → 280 → 270 → EVT-REP-999
```

No recorre `PROC-REP-010`, `030`, `266` ni `290`.

## User Scenarios

### US-REP-021 — Generar la garantía de un Detalle entregado (P1)

Como Recepcionista quiero generar una garantía RMA de un Detalle de una
Orden ya entregada para que el cliente reciba una nueva Orden vinculada a
la original sin volver a registrar sus datos ni reabrir la Orden
entregada.

1. **Given** una Orden `ENTREGADA` con Cliente, **When** se consulta
   `acciones_disponibles`, **Then** el backend publica
   `GENERAR_GARANTIA_RMA` (rol `RECEPCION`) una vez por Detalle.
2. **Given** esa Orden, **When** Recepcionista ejecuta
   `POST /api/orders/{orden}/details/{detalle}/warranty-rma`, **Then** se
   crea una Orden **nueva** (`201`) con `origen =
   RMA_GARANTIA_REPARACION`, `orden_origen_id` = la origen, Cliente y
   Equipo copiados, un Detalle con `detalle_origen_id` y snapshot propio,
   y queda `HABILITADA` tras `035 → 040 → 045 → 070 → 050 → 060 → 080 →
   090 → 140`.
3. **Given** la Orden origen, **When** se crea y recorre la garantía,
   **Then** la origen permanece **exactamente igual**.

### US-REP-022 — Garantía sin cobro (P1)

Como Recepcionista quiero que una garantía RMA no genere ningún cobro pero
pueda notificarse y entregarse al cliente para cerrarla sin registrar
pagos ficticios.

1. **Given** una garantía `REPARACION_LISTA`, **Then** no se ofrece
   `REGISTRAR_PAGO` y `POST /payments` responde `409`.
2. **Given** la notificación, **Then** `PROC-REP-265` aprueba con
   observación `NO_COBRABLE_POR_ORIGEN` aunque el saldo nominal sea > 0, y
   no se registra `PROC-REP-266`.
3. **Given** `265` aprobado, **Then** se emite el comprobante final y se
   entrega (`PROC-REP-280 → 270`), y la Orden termina `ENTREGADA` /
   `EVT-REP-999` con `pagos = []`.

## Requisitos

- **FR-REP-080**: nueva Orden `RMA_GARANTIA_REPARACION` desde Orden
  `ENTREGADA`; Cliente/Equipo recuperados; sin `010`/`030`.
- **FR-REP-081**: vínculo Orden→Orden origen y Detalle→Detalle origen con
  snapshot comercial propio del Tipo de Reparación vigente.
- **FR-REP-082**: la Orden origen permanece históricamente inmutable.
- **FR-REP-083**: `265` aprueba por origen `NO_COBRABLE`, sin pagos ni
  `266`.
- **FR-REP-084**: comprobante final y entrega con saldo nominal > 0, sin
  relajar ninguna otra precondición.
- **FR-REP-085**: el backend publica `GENERAR_GARANTIA_RMA` por Detalle
  (no para `RT_INTERNO` terminado).
- **FR-REP-086**: ruta de progreso propia de HP-REP-003.

Ver `traceability/hp-rep-003.yaml` para la cadena completa.

## Decisiones

- **Saldo nominal ≠ deuda.** El precio snapshot sigue existiendo (valoración
  del trabajo, reporting); no se fuerza `saldo = 0` ni `PAGADO`, ni se
  registra un Pago ficticio. La ausencia de cobro proviene del Origen
  (`PoliticaOrigen.condicion_comercial = NO_COBRABLE`).
- **Un solo comando de aplicación** (`crear_garantia_rma`) compone `035 →
  140` porque Recepción ya eligió el Detalle a reprocesar.
- **Mismo Tipo de Reparación**: el Detalle nuevo usa el `tipo_reparacion_id`
  del origen y toma un snapshot nuevo del catálogo vigente (BR-REP-015).
- **`condicion_entrega_cumplida(orden)`** centraliza la condición de
  entrega a partir de `PoliticaOrigen`: sin entrega a cliente → no aplica;
  `COBRABLE` → `saldo <= 0`; `NO_COBRABLE` → `True`.
- **`historial` de `PROC-REP-035`** deja `orden_origen_id` y
  `detalle_origen_id` en `observacion`; la relación estructurada vive en
  `OrdenReparacion.orden_origen_id` y `ReparacionDetail.detalle_origen_id`.
- **Compatibilidad**: los dos campos nuevos tienen default `None`; un JSON
  anterior a este slice carga sin migración.

## Fuera de alcance

`RT_GARANTIA_VENTA`, `OrdenRevision`, garantía vencida o vigencia por
`garantia_dias`, motivo de garantía, cantidad máxima de garantías, rechazo,
cambio directo, `VAR-REP-*`, `EXC-REP-*`, `SIN_REPARACION`, `EN_REVISION`,
cortesías, reembolsos, cancelación, distribución de puntaje, PostgreSQL.

El Happy Path **asume** que no ocurren: Tipo original inactivo o eliminado,
garantía fuera de plazo, Detalle origen cancelado, Orden origen sin
Cliente, garantía de una garantía, más de un Detalle origen por garantía.
Ninguno se resuelve con una regla inventada: el backend solo rechaza lo que
este Scenario necesita (origen no `ENTREGADA`, Detalle inexistente, actor
distinto de Recepción, origen sin Cliente).
