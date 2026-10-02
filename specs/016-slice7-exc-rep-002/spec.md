# Feature Specification: EXC-REP-002 — Recursos insuficientes, resuelto por override

**Feature Branch**: `mvp-v2-slice7-exc-rep-002`

**Created**: 2026-10-01

**Status**: Implemented (Scenario EXC-REP-002, Exception)

**Business Feature involucrada**: `FEAT-REP-003`

**Source Process**: `PROC-REP` V1.3

**Implemented Scenario**: `EXC-REP-002`
(`business/scenarios/repair-management-scenarios-v1.3.yaml`); aplica a
`HP-REP-001`, `HP-REP-002` y `HP-REP-003`.

**Reglas**: `BR-REP-002`, `BR-REP-003` (más `BR-REP-005/006` por el efecto
posterior en 185/210).

> **ALCANCE.** Misma situación inicial que EXC-REP-001 (`090 Ninguno
> trabajable → 100`), pero un **Coordinador RMA** decide forzar un Detalle
> bloqueado: `110 Sí → 130 → 140`. Cierra `TASK-REP-045`.

## Decisión de negocio confirmada (BR-REP-003)

Cuando un Coordinador RMA hace un override de factibilidad sobre un Detalle
bloqueado por recursos, **autoriza explícitamente que ese Detalle continúe
aunque no haya stock suficiente**. Esto habilita, para ESE Detalle, la
reserva (PROC-REP-185) y el consumo (PROC-REP-210) posteriores aunque la
disponibilidad o el stock físico resultantes sean negativos. La aclaración
quedó reflejada en `BR-REP-003` y en la descripción de `EXC-REP-002`
(`business/`), sin cambiar IDs ni el Process Graph, y **sin** agregar 185/210
como `affected_nodes`: son consecuencia downstream del override.

## Flujo

```
090 [Ninguno trabajable] → 100 → 110 [Sí] → 130 → 140   (HABILITADA)
```

- `OVERRIDE_RECURSOS` (por Detalle `BLOQUEADO_POR_RECURSOS`, rol
  `COORDINADOR_RMA`) se publica en PROC-REP-100 **junto a** `ESPERAR_RECURSOS`
  (`110 No → 120`, sin cambios). En 120 no se publica.
- `POST /api/orders/{orden_id}/details/{detalle_id}/resources/override`
  (`usuario_id`, `motivo`): `200 OrdenOut`; `404` Orden/Detalle inexistente;
  `409` precondición (rol, nodo ≠ 100, Detalle no bloqueado, motivo en
  blanco); `422` request inválido (motivo vacío/ausente).
- Precondiciones: `current_process == PROC-REP-100`, Detalle `DEFINIDO` +
  `BLOQUEADO_POR_RECURSOS`, usuario activo `COORDINADOR_RMA`, motivo no vacío.
- Recepción, Técnico y Administrador son rechazados (409).
- Registra `PROC-REP-110` con observación `Si` (y el `usuario_id` del
  Coordinador) y `PROC-REP-130` con usuario, fecha, `reparacion_detail_id` y
  una observación con la validación ignorada (factibilidad por recursos,
  PROC-REP-080/090) y el motivo (BR-REP-003). Después, `habilitar_orden`.
- El comando persiste la Orden una sola vez.

## El override vive en el historial

No hay flag en `ReparacionDetail`. `tiene_override_factibilidad(orden,
detalle_id)` (en `services/recursos.py`) deriva el override de un
`PROC-REP-130` registrado para ese `reparacion_detail_id`; es el **único**
lugar donde se busca y lo consultan: la factibilidad (no rebloquea un Detalle
forzado), la reserva (185) y el consumo (210). Un override de un Detalle
nunca alcanza a otro.

## Gate de PROC-REP-140

`habilitar_orden` acepta **una** de dos condiciones:

- **A)** `current_process == PROC-REP-090` y el último 090 con resultado `Si`
  (flujo normal, sin cambios);
- **B)** `current_process == PROC-REP-130` con un override válido: el último
  `PROC-REP-130` apunta a un Detalle que existe, está `DEFINIDO` y quedó
  `SIN_BLOQUEO` (`override_listo_para_habilitar`).

**No se fabrica un 090 `Si`.** El historial real es
`080 · 090 Ninguno · 100 · 110 Sí · 130 · 140`. Habilitar directo desde 100 o
110 sigue rechazado, y un `current_process = 130` sin override válido
registrado también.

## Stock: 130 / 185 / 210

El override **solo autoriza**; no toca el stock:

| Nodo | Efecto |
|---|---|
| `130` | registra la autorización. Sin reserva, sin cambio de stock |
| `185` | con override *del Detalle*: reserva **todas** las previstas aunque no alcance (todo o nada); sin override: la reserva fallida se registra como EXC-REP-003 (185 "Reserva fallida" → 186 → 211, ver `specs/017-slice8-exc-rep-003`); `RecursoNoDisponibleError` queda como guard defensivo de bajo nivel |
| `210` | `CONSUMO` baja `stock_fisico`, que puede quedar negativo **solo** si el consumo viene de un Detalle con override; `LIBERACION_RESERVA` no lo toca; sin override sigue rechazado |

Ejemplo: `stock_fisico = 0`, requerido 1, override → 185: `RESERVA 1`
(`stock_disponible = −1`, `stock_fisico = 0`) → 210: `CONSUMO 1` →
`stock_fisico = −1`. Con reserva 2 y uso 1: `CONSUMO 1 + LIBERACION 1` →
`stock_fisico = −1` (no −2). La política es una sola
(`tiene_override_factibilidad` en reserva y consumo, sin `if` dispersos).
`Insumo.stock_fisico` ya no tiene `ge=0`; la protección vive en los services,
no en el tipo.

## Multi-Detalle

Con `DET-A` y `DET-B` bloqueados, el override de `DET-A` deja `DET-A →
SIN_BLOQUEO`, `DET-B` bloqueado y la Orden `HABILITADA`. `INICIAR_DETALLE` se
ofrece solo para `DET-A`; iniciar `DET-B` por llamada directa da 409.

## Fuera de alcance

`EXC-REP-003` (reserva fallida, PROC-REP-186), `EXC-REP-004`
(125/126/127), `EXC-REP-005`, `DESPERDICIO`, `OrdenRevision`, un override
global de Orden, y cualquier cambio en la rama `110 No → 120` o en
EXC-REP-001. `UAT-REP-033/034` siguen `PENDING`.
