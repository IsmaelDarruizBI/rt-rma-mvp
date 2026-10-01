# Feature Specification: VAR-REP-003 — Ejecución interrumpida

**Feature Branch**: `mvp-v2-slice5-var-rep-003`

**Created**: 2026-10-01

**Status**: Implemented (Scenario VAR-REP-003, Variant)

**Business Feature involucrada**: `FEAT-REP-005` (la que declara el Scenario)

**Source Process**: `PROC-REP` V1.3

**Implemented Scenario**: `VAR-REP-003`
(`business/scenarios/repair-management-scenarios-v1.3.yaml`); aplica a
`HP-REP-001`, `HP-REP-002` y `HP-REP-003`.

**Reglas**: `BR-REP-004`, `BR-REP-005`, `BR-REP-007`, `BR-REP-012`, `BR-REP-018`.

> **ALCANCE.** PROC-REP-200 tiene dos desenlaces igualmente normales:
> Completado (ya implementado) e **Interrumpido** (este Slice). La mecánica
> es transversal: no hay ramas por Origen ni por Scenario.

## Flujo implementado

```
185 → 190 → 200 (Interrumpido) → 210 → 211
```

| Elemento | Resultado |
|---|---|
| `EjecucionReparacion.estado` | `EN_PROGRESO` → `INTERRUMPIDO` (terminal) |
| `fin` | fecha/hora de la interrupción |
| `insumos_utilizados` | lo realmente usado hasta ese momento |
| `observaciones` | se preservan |
| `ReparacionDetail.estado` | `EN_PROGRESO` → `DEFINIDO` (representación técnica de PENDIENTE; no existe un estado nuevo) |
| `ReparacionDetail.condicion` | permanece `SIN_BLOQUEO` |
| PROC-REP-211 | lo calcula el resolver: `ABIERTA_TRABAJABLE` con un Detalle trabajable |
| Toma | **sigue `ACTIVA`** |
| `estado_workflow` | sigue `EN_REPARACION` |

`EstadoEjecucion` ahora es `EN_PROGRESO | COMPLETADO | INTERRUMPIDO`; la
adición es aditiva y compatible con JSON previo. No hay campo `resultado`
aparte ni estado `PENDIENTE` nuevo.

## Endpoint y acciones

`POST /api/orders/{orden_id}/executions/{ejecucion_id}/interrupt` — 200
`OrdenOut`. Body: `usuario_id`, `insumos_utilizados` (default `[]`) y
`observaciones`. `/complete` no cambia.

Con una Ejecución activa el backend publica `COMPLETAR_EJECUCION` e
`INTERRUMPIR_EJECUCION` (rol TECNICO, con `detalle_id` y `ejecucion_id`).
Tras interrumpir no hay Ejecución activa: se ofrecen `INICIAR_DETALLE` y
`LIBERAR_ORDEN` (más `REGISTRAR_PAGO` cuando corresponde por su regla
propia). No existe una acción `CONTINUAR_EJECUCION`.

Valida lo mismo que completar: usuario TECNICO, Ejecución existente (404
si no), `EN_PROGRESO`, propietario y toma activa correspondiente (409).

## Inventario (PROC-REP-210)

Mismo mecanismo que Completado (`aplicar_movimientos_inventario`), con
`insumos_utilizados` como fuente de verdad. Reserva de 2:

| Utilizado | Movimientos | Stock físico |
|---|---|---|
| 0 | `LIBERACION_RESERVA 2` | sin cambio |
| 1 | `CONSUMO 1` + `LIBERACION_RESERVA 1` | −1 |
| 2 | `CONSUMO 2` | −2 |

En ningún caso quedan reservas activas.

**Gate nuevo.** `generar_movimientos_inventario` ahora rechaza con
`PrecondicionInvalidaError` una Ejecución `EN_PROGRESO` y solo concilia
`COMPLETADO` o `INTERRUMPIDO` (invariante respaldada por PROC-REP-210; no
depende del Scenario).

## Continuar = Ejecución nueva

- Una Ejecución interrumpida **nunca se reutiliza ni se sobrescribe**.
  Continuar crea una Ejecución con id, inicio, toma, técnico e insumos
  propios.
- **Mismo técnico:** la toma sigue activa; vuelve a iniciar el Detalle
  (212 Sí → 181 → 174 → 185). Queda `EJE-1 INTERRUMPIDO`, `EJE-2` nueva.
- **Otro técnico:** el primero libera la Orden (212 No → 213, vuelve a
  `EN_COLA`, toma `CERRADA`) y el segundo la toma y la inicia: 2 tomas y 2
  Ejecuciones históricas.
- **No se calcula "insumo restante"** descontando lo consumido por
  Ejecuciones anteriores: PROC-REP-185 reserva los previstos de la nueva
  Ejecución y Business no define otro algoritmo para una continuación. Si
  el stock no alcanza para la nueva reserva, el comportamiento es el
  existente de 185 (409), sin lógica especial.
- La **toma no se cierra automáticamente** al interrumpir.

## Fuera de alcance

- **`DESPERDICIO`** (PROC-REP-210 / BR-REP-005): el modelo no tiene ese
  movimiento y Business no define su contrato. No se agregó
  `DESPERDICIO`, `insumos_desperdiciados`, cantidades ni motivos. Se usa
  solo la reconciliación operativa (`CONSUMO`, `LIBERACION_RESERVA`).
  `TASK-REP-089` y `TASK-REP-090` **siguen `NOT_IMPLEMENTED`**.
- `EXC-REP-001/002/003`, reserva fallida (186), override de recursos,
  revisión posterior (125/126/127), rechazo de control (235), cancelación,
  `OrdenRevision`, `RT_GARANTIA_VENTA`, PostgreSQL.

UAT (`UAT-REP-027/028`) siguen `PENDING`.
