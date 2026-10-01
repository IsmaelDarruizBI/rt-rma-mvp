# Feature Specification: VAR-REP-001 + VAR-REP-002 — Ingreso sin diagnóstico conocido (EN_REVISION)

**Feature Branch**: `mvp-v2-slice4-var-rep-001-002`

**Created**: 2026-10-01

**Status**: Implemented (Scenarios VAR-REP-001 y VAR-REP-002, Variants)

**Business Feature involucrada**: `FEAT-REP-002` (la que declaran ambos
Scenarios); reutiliza técnicamente `FEAT-REP-001` (ingreso/garantía) y
`FEAT-REP-003` (080/090/140), sin completar ninguna.

**Source Process**: `PROC-REP` V1.3

**Implemented Scenarios**: `VAR-REP-001`, `VAR-REP-002`
(`business/scenarios/repair-management-scenarios-v1.3.yaml`)

**Reglas**: `BR-REP-001`, `BR-REP-015`, `BR-REP-016`, `BR-REP-019`.

> **ALCANCE.** Dos Scenarios de negocio distintos que son una única unidad
> de implementación:
>
> - **VAR-REP-001** (con comprobante): `CLIENTE_EXTERNO` y
>   `RMA_GARANTIA_REPARACION`.
> - **VAR-REP-002** (sin comprobante): `RT_INTERNO`.
>
> La diferencia de comprobante depende **exclusivamente** de
> `politica_de(orden.origen).requiere_comprobante_recepcion`. No hay ramas
> por Scenario.

## Flujo implementado

```
PROC-REP-045 = No
→ 055 (EN_REVISION)
→ 050 → [060 según PoliticaOrigen]
→ 065 (Técnico registra el resultado)
→ 068 = Sí
→ 075 (Recepción define 1..N Detalles)
→ 080 → 090 → 140 (HABILITADA)
```

Después de 140 converge con el circuito normal de cada Origen. Los Happy
Paths HP-REP-001/002/003 **no cambian**: siguen siendo `045 Sí → 070`.

## Intenciones humanas y endpoints

| Intención | Rol | Endpoint | Nodos |
|---|---|---|---|
| Enviar a revisión una Orden existente | RECEPCION | `POST /api/orders/{id}/send-to-review` | 045 No → 055 → 050 [→ 060] |
| Garantía RMA directamente en revisión | RECEPCION | `POST /api/orders/{origen}/details/{detalle}/warranty-rma/review` (201) | 035 → 040 → 045 No → 055 → 050 → 060 |
| Realizar la revisión | TECNICO | `POST /api/orders/{id}/technical-review` | 065 |
| Definir la reparación luego de la revisión | RECEPCION | `POST /api/orders/{id}/review/details` | 068 Sí (una vez) → 075 [→ 080 → 090 → 140] |

`POST /details` y `POST /warranty-rma` conservan exactamente su semántica
(045 Sí → 070). Actor incorrecto, estado incorrecto, revisión repetida y
Tipo inactivo resuelven `409`; resultado vacío `422`; Detalle origen
inexistente `404`.

Acciones publicadas por el backend: `ENVIAR_A_REVISION` (junto a
`DEFINIR_REPARACION` en una Orden sin Detalles), `REALIZAR_REVISION`,
`DEFINIR_REPARACION_DESDE_REVISION` (mientras no se finalice la
definición) y `GENERAR_GARANTIA_RMA_REVISION` (junto a
`GENERAR_GARANTIA_RMA`, por Detalle, en una Orden entregada con Cliente).

## Decisiones de modelado

- **`EN_REVISION` admite cero Detalles.** No existe un Detalle ficticio de
  "Diagnóstico" ni un Tipo de Reparación de revisión.
- **Persistencia mínima de la revisión.** PROC-REP-065 se registra en
  `HistorialWorkflow`: `usuario_id` = técnico, `fecha`, `observacion` =
  resultado (texto libre no vacío, sin catálogo rígido). De ahí salen
  quién revisó, cuándo, qué resultado, cuánto estuvo la Orden en
  EN_REVISION y cuándo se definió (075) — sin tablas nuevas ni KPIs.
- **Procedencia de la garantía.** `OrdenReparacion.detalles_origen_ids`
  (default `[]`) guarda los Detalles origen identificados en PROC-REP-035.
  Convive con `ReparacionDetail.detalle_origen_id` (Detalle nuevo → Detalle
  origen concreto): una garantía en revisión todavía no tiene Detalles
  propios. La relación **no se recupera parseando el historial**. Con un
  único Detalle origen se usa automáticamente; con más de uno el comando
  exige indicarlo (`detalle_origen_id`).
- **PROC-REP-068 una sola vez, PROC-REP-075 por Detalle** (Multi-Detalle con
  `finalizar_definicion`), y **sin repetir 050/060**: el comprobante se
  generó antes del diagnóstico.
- **Sin traza falsa**: definir luego de revisión no usa
  `definir_reparacion_detail` (que registraría 045 Sí y 070); comparte
  solo el helper privado del snapshot (BR-REP-015).
- **Progreso.** La ruta de revisión se deriva de la del Origen cuando
  `PROC-REP-055` está en el historial; no se guarda ningún id de Scenario.
- **`habilitar_orden`** acepta `EN_REVISION` (con Detalles ya definidos) y
  exige, para cualquier camino (HP-REP-001/002/003 y VAR-REP-001/002), que
  la Orden venga de `PROC-REP-090` con resultado `Si`
  (`current_process == "PROC-REP-090"` y la ultima evaluacion de 090 en el
  historial con observacion `Si`). Una invocacion directa que saltee
  080/090 -desde 070 o desde 075- o con faltantes se rechaza con
  `PrecondicionInvalidaError`; la precondicion es del nodo 140, no del
  Scenario.
- **Factibilidad fallida luego de revision.** Sin recursos, 090 no aprueba
  y el comando responde 409 sin llegar a 140 (100/110/120/130 y
  EXC-REP-001/002 siguen fuera de alcance). Como en `definir_reparacion`,
  el comando falla antes de persistir: la Orden queda como estaba despues
  de PROC-REP-065.

## Decisión arquitectónica: `OrdenRevision` es un aggregate futuro

`OrdenRevision` será un aggregate **independiente** de `OrdenReparacion`.
El diseño actual no debe impedir:

1. `OrdenRevision` antes de existir una `OrdenReparacion` (puede crearla o
   no);
2. una `OrdenReparacion` existente que necesita revisión profunda →
   `OrdenRevision` → continúa la misma OR o la cierra;
3. `RT_GARANTIA_VENTA` → `OrdenRevision` → reparación / cambio directo /
   no aplica.

Por eso **no** se modeló `orden.revision_tecnica`, ni `orden_revision_id`,
ni `class OrdenRevision`, ni repositorio/storage/estado de revisión. La
frontera preparada es:

```text
OrdenReparacion → necesita revisión → capacidad de revisión
                → resultado → continuar el proceso
```

Hoy la capacidad es `app/backend/app/services/revisiones.py`
(`registrar_revision_tecnica`: valida y registra PROC-REP-065 sobre el
aggregate recibido; no decide Detalles, no consulta el catálogo, no
habilita). Mañana puede ser satisfecha por un `OrdenRevision` sin cambiar
el circuito posterior. `EN_REVISION` significa "la Orden espera o
atraviesa la resolución de una revisión antes de poder definir sus
Detalles", no "la revisión está embebida en la Orden".

## Datos anteriores a este Slice (garantias historicas)

Las Ordenes `RMA_GARANTIA_REPARACION` persistidas antes de Slice 4 pueden
cargar con `detalles_origen_ids = []`. La relacion historica Detalle →
Detalle origen continua disponible en `ReparacionDetail.detalle_origen_id`.
Los consumidores y reportes **no deben asumir** que `detalles_origen_ids`
este poblado retroactivamente en datos anteriores a Slice 4. No hay
migracion ni inferencia automatica; el campo conserva
`default_factory=list`.

## Fuera de alcance

`PROC-REP-068 No` / `PROC-REP-069` (SIN_REPARACION), `OrdenRevision`,
revisión técnica como entidad persistida, `RT_GARANTIA_VENTA`,
`EXC-REP-001..005` (incluida `EXC-REP-004`: revisión posterior de un
Detalle ya existente; `125/126/127`, `REQUIERE_DEFINICION` operativo),
reserva fallida, override, retrabajo, cancelación, PostgreSQL.

UAT (`UAT-REP-023..026`) siguen `PENDING`: no hubo aceptación de negocio.
