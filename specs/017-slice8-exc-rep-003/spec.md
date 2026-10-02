# Feature Specification: EXC-REP-003 — Reserva de insumos fallida al iniciar la Ejecución

**Feature Branch**: `mvp-v2-slice8-exc-rep-003`

**Created**: 2026-10-01

**Status**: Implemented (Scenario EXC-REP-003, Exception)

**Business Feature involucrada**: `FEAT-REP-005`

**Source Process**: `PROC-REP` V1.3

**Implemented Scenario**: `EXC-REP-003`
(`business/scenarios/repair-management-scenarios-v1.3.yaml`); aplica a
`HP-REP-001`, `HP-REP-002` y `HP-REP-003`.

**Reglas**: `BR-REP-006` (principal), `BR-REP-012`, `BR-REP-018`;
`BR-REP-003` como contraste (override de EXC-REP-002).

> **ALCANCE.** La factibilidad (PROC-REP-080) fue correcta, pero al intentar
> la reserva real (PROC-REP-185) faltan insumos y el Detalle **no** tiene un
> override propio. La reserva falla, la Ejecución no nace y el Detalle queda
> bloqueado por recursos. Cierra `TASK-REP-086`.

## Flujo

```
185 ── Reserva exitosa ──→ 190                                   (sin cambios)
    └─ Reserva fallida ──→ 186 ──→ 211 ─┬─ ABIERTA_TRABAJABLE (+ toma activa) → 212 → 181
                                        └─ PENDIENTE_RECURSOS → cierra la toma → 120
```

Historial persistido de un intento fallido:

```
[212 Sí]  181  174 Sí  185 "Reserva fallida"  186  211  [120]
```

- `212 Sí` solo si `current_process` es 180 o 211 (regla existente de
  `seleccionar_detalle`).
- `185` registra al técnico y el Detalle, **sin** `ejecucion_id` (la Ejecución
  nunca nació) y con `observacion = "Reserva fallida"`.
- `186` es ACT-SYSTEM (`usuario_id = None`), con el Detalle y
  `observacion = "Faltantes: INS-xxx, INS-yyy"` (todos, ordenados).
- `211` lo calcula `evaluar_situacion_orden` (sin duplicar el resolver).
- `120` se alcanza **directo** desde 211 (EXC-REP-001): nunca pasa por 100 ni
  110, porque ya estamos dentro del taller.

## Condición exacta

EXC-REP-003 ocurre **solo** cuando, en PROC-REP-185:

```
Detalle seleccionado
+ faltan insumos previstos (stock_fisico − reservas propias − reservas ajenas)
+ SIN tiene_override_factibilidad(orden, detalle_id) para ESE Detalle
```

Con override del mismo Detalle (EXC-REP-002) **no** hay EXC-REP-003: 185 reserva
aunque no alcance. El override de otro Detalle no cuenta.

## Mapping de estados (decisión cerrada)

| Contrato funcional | Técnico |
|---|---|
| Detalle `PENDIENTE` | `EstadoReparacionDetail.DEFINIDO` |
| Detalle `EN_PROCESO` | `EstadoReparacionDetail.EN_PROGRESO` |

No se crea ningún enum nuevo. Tras 186 el Detalle es `DEFINIDO` +
`BLOQUEADO_POR_RECURSOS` (`enums.py` ya documenta la equivalencia).

## Resultado de una reserva fallida

Simultáneamente:

```
0 reservas nuevas · 0 Ejecuciones nuevas · 0 movimientos · stock_fisico igual
```

y persisten `185 fallida · 186 · 211 [· 120]`. La Orden se construye en memoria
y se guarda **una sola vez** al final del command.

## Caso A — queda otro Detalle trabajable

| Elemento | Estado |
|---|---|
| Detalle fallido | `DEFINIDO` + `BLOQUEADO_POR_RECURSOS` |
| Otros Detalles | sin cambios |
| Ejecución / reservas / stock | ninguna / 0 / sin cambios |
| Toma | **ACTIVA** (211 no cierra con `ABIERTA_TRABAJABLE`) |
| Workflow | sin cambios |
| Situación | `ABIERTA_TRABAJABLE`; `current_process = PROC-REP-211` |
| Acciones | `INICIAR_DETALLE` (los trabajables) + `LIBERAR_ORDEN` |

El siguiente `INICIAR_DETALLE` registra `212 Sí → 181` (211 está en
`_ORIGENES_DE_LA_DECISION_212`). No hizo falta tocar `acciones_disponibles`.

## Caso B — no queda ningún Detalle trabajable

| Elemento | Estado |
|---|---|
| Detalle fallido | `DEFINIDO` + `BLOQUEADO_POR_RECURSOS` |
| Toma | **CERRADA** (BR-REP-018, `fin = fecha`) |
| Workflow | sin cambios |
| Situación | `PENDIENTE_RECURSOS` (derivada; no es `EstadoWorkflow`) |
| `current_process` | `PROC-REP-120` |
| Acciones | solo `REVALIDAR_RECURSOS` (más transversales como el pago) |

## Workflow state

El hito **no se toca** en 186/211/120 (BR-REP-012):

- primer intento tras tomar la Orden → sigue `EN_COLA` (nada empezó; solo un
  185 exitoso pasa a `EN_REPARACION`, lo que no cambia);
- con trabajo previo (`EN_REPARACION`) → se conserva.

### I-1: la Orden que llega a 120 estando `EN_COLA`

`habilitar_orden` aceptaba solo `REQUERIMIENTO`, `EN_REVISION` y
`EN_REPARACION`: una Orden `EN_COLA` en 120 no podía revalidarse (409 y
atascada). Ahora acepta también `EN_COLA`, **sin relajar el gate**:

```
A) current_process == PROC-REP-090 con último resultado Sí
B) current_process == PROC-REP-130 con override válido
```

Siguen rechazados: 100 → 140, 110 → 140, 120 → 140 y una Orden `EN_COLA`
arbitraria sin 090 Sí ni 130 válido.

Caminos combinados (ambos cubiertos E2E):

```
EXC-003 → 120 → stock vuelve → revalidar → 080 → 090 Sí → 140 → 150 → 170 → tomar → iniciar
EXC-003 → 120 → revalidar → 090 Ninguno → 100 → 110 Sí → 130 → 140 (EXC-002)
```

## API

`POST /api/orders/{orden_id}/details/{detalle_id}/start` responde:

| Caso | Respuesta |
|---|---|
| Reserva exitosa | `200 OrdenOut` (sin cambios) |
| **Reserva fallida (EXC-REP-003)** | **`200 OrdenOut`** con 185/186/211[/120] persistidos |
| Rol inválido, Detalle no trabajable, sin toma, Ejecución activa, estación incompatible | `409` (no persiste nada) |
| Orden o Detalle inexistente | `404` |

Razón: la transición ocurrió y se persistió; es un resultado funcional, no un
error. Mismo criterio que `090 Ninguno → 100` y `211 → 120`.
`RecursoNoDisponibleError` se conserva como guard defensivo de bajo nivel en
`reservar_insumos_e_iniciar_ejecucion`, ya no es la respuesta normal E2E.

## Progreso

`application/progreso.py` intercala `PROC-REP-186` tras 185 y `PROC-REP-120`
tras 211 **solo con evidencia real** en el historial (nunca por un id de
Scenario). Si 120 ya figura por el tramo 100/110/120 no se duplica.

## Una sola lógica de disponibilidad

`services.inventario.faltantes_del_detalle` calcula los faltantes (stock físico
menos reservas propias y ajenas, orden determinista). La usan la factibilidad
(PROC-REP-080), la reserva (185) y 186; ya no existe
`reparaciones._faltantes_del_detalle`.

## Limitaciones conocidas (fuera de alcance)

- Con DET-A bloqueado y DET-B todavía trabajable la Orden continúa con DET-B; no
  hay revalidación automática de DET-A mientras exista otro trabajable. No se
  inventa polling ni edges nuevos.
- PROC-REP-174 "No" (176/178/179) sigue sin implementarse.
- No se implementa EXC-REP-004 (125/126/127) ni EXC-REP-005 ni `DESPERDICIO`.
- `UAT-REP-035/036` siguen `PENDING`.

## Frontend

Sin cambios: el Detalle ya muestra su badge `BLOQUEADO_POR_RECURSOS`, las
acciones salen de `acciones_disponibles` y el progreso/historial vienen en
`OrdenOut`. No se agrega toast ni modal especial.
