# Feature Specification: EXC-REP-001 — Recursos insuficientes, en espera de revalidación

**Feature Branch**: `mvp-v2-slice6-exc-rep-001`

**Created**: 2026-10-01

**Status**: Implemented (Scenario EXC-REP-001, Exception)

**Business Feature involucrada**: `FEAT-REP-003`

**Source Process**: `PROC-REP` V1.3

**Implemented Scenario**: `EXC-REP-001`
(`business/scenarios/repair-management-scenarios-v1.3.yaml`); aplica a
`HP-REP-001`, `HP-REP-002` y `HP-REP-003`, y también cuando esos caminos
llegan a la factibilidad después de `VAR-REP-001/002` (mismo mecanismo, sin
duplicar).

**Reglas**: `BR-REP-002`, `BR-REP-006`, `BR-REP-012`.

> **ALCANCE.** Cuando ningún Detalle puede trabajarse por falta de recursos,
> la Orden se **persiste** detenida en `PROC-REP-100`, espera
> (`110 No → 120`) y se revalida (`120 → 080`) tantas veces como haga falta.
> El override (`110 Sí → 130`, EXC-REP-002) queda para otro Slice.

## Decisiones centrales

- **`PENDIENTE_RECURSOS` NO es un `EstadoWorkflow`.** Es un agregado derivado
  por `resolver_situacion_orden` a partir de la `condicion` de los Detalles;
  no se persiste en la Orden ni se agrega un estado de workflow. Mientras
  espera, `estado_workflow` conserva su último hito (`REQUERIMIENTO` o
  `EN_REVISION`).
- **El bloqueo vive en `Detalle.condicion`.** El `estado` sigue `DEFINIDO`;
  `condicion` pasa de `SIN_BLOQUEO` a `BLOQUEADO_POR_RECURSOS` (valor que ya
  existía en el dominio y el JSON). No hay flags ni estados nuevos.
- **Factibilidad POR Detalle (BR-REP-002).** `validar_factibilidad_detalles`
  evalúa cada Detalle contra `stock_fisico − reservas activas globales`. El
  `bool` devuelto significa **hay al menos un Detalle trabajable**, no "todos
  son factibles". Un Detalle sin recursos no bloquea a los demás.
- **No pisa otras causas de bloqueo.** PROC-REP-080 solo reevalúa Detalles
  `DEFINIDO` con `SIN_BLOQUEO` o `BLOQUEADO_POR_RECURSOS`; un
  `REQUIERE_DEFINICION` (EXC-REP-004) se respeta.
- **`PROC-REP-100` es la frontera para el Slice 7.** Con ninguno trabajable la
  factibilidad se detiene en 100; no encadena 110/120. Allí podrán existir las
  dos salidas: esperar (este Slice) o forzar un Detalle (EXC-REP-002).
- **`RecursoNoDisponibleError` no se elimina.** Sigue vigente en la reserva
  real (PROC-REP-185) hasta que EXC-REP-003 implemente PROC-REP-186. Solo
  deja de ser la respuesta a la factibilidad inicial.
- **Sin reservas ni movimientos.** Factibilidad y revalidación solo
  consultan: no reservan, consumen ni liberan, y no tocan el stock físico.

## PROC-REP-211 con `PENDIENTE_RECURSOS` (factibilidad parcial)

La factibilidad parcial hace alcanzable que, tras completar el único Detalle
trabajable, solo queden Detalles bloqueados. PROC-REP-211 (caso e) lo resuelve
con un edge directo a `PROC-REP-120`:

```
… 200 → 210 → 211 [PENDIENTE_RECURSOS] → 120      (sin 100 ni 110)
```

- `evaluar_situacion_orden` cierra la toma activa (BR-REP-018) —
  `PENDIENTE_RECURSOS` está en `_RESULTADOS_QUE_CIERRAN_LA_TOMA`— y continúa
  directo a 120 con `marcar_pendiente_recursos` (compartida con `110 No → 120`;
  valida el resolver y solo acepta venir de 110 o 211).
- La Orden conserva `estado_workflow = EN_REPARACION` mientras espera y se
  publica `REVALIDAR_RECURSOS`.
- `habilitar_orden` acepta ahora `EN_REPARACION` para poder alcanzar 140 al
  revalidar, **sin relajar** el gate (`current_process == PROC-REP-090` con el
  último 090 en `Si`). `EN_COLA`, `REPARACION_LISTA` y `ENTREGADA` siguen
  rechazados.
- Revalidar con stock: `120 → 080 → 090 Sí → 140 → ENCOLAR → 150 → 170 → …`
  (reencolar, tomar, completar el Detalle restante, 211 `COMPLETA` y control).
  Sin stock: `120 → 080 → 090 Ninguno → 100 → (ESPERAR_RECURSOS) → 110 No → 120`.
- `REQUIERE_REVISION → 125` (que también cerraría la toma) pertenece a otro Slice.

## Flujo

```
080 → 090 [Ninguno trabajable] → 100 (uno por Detalle bloqueado) ── frontera
ESPERAR_RECURSOS:    110 (No) → 120
REVALIDAR_RECURSOS:  120 → 080 → 090 Sí → 140           (HABILITADA)
                          └──→ 090 Ninguno → 100 → …     (otro ciclo)
```

Cada ciclo conserva su historial (`080/090/100/110/120/080/090/…`): nada se
sobrescribe. Revalidar no crea Detalles ni repite 045/050/060/065/068/070/075.

`PROC-REP-100` registra una entrada **por Detalle bloqueado**, con
`reparacion_detail_id` y `observacion = "Faltantes: INS-A, INS-C"` (los
faltantes de *ese* Detalle). Con 090 Sí y Detalles bloqueados (factibilidad
parcial) no se registra 100; `PROC-REP-080` anota los bloqueados en su
observación.

`habilitar_orden` conserva el gate de Slice 4: exige `current_process ==
PROC-REP-090` con resultado `Si`; `090 Ninguno trabajable → 140` sigue
bloqueado por invocación directa.

## Acciones, endpoints y UI

| Acción | Cuándo | Endpoint | Actor |
|---|---|---|---|
| `ESPERAR_RECURSOS` | `current_process == PROC-REP-100` | `POST /api/orders/{id}/resources/wait` | ninguno (`requiere_actor=false`) |
| `REVALIDAR_RECURSOS` | `current_process == PROC-REP-120` | `POST /api/orders/{id}/resources/revalidate` | ninguno |

Los endpoints no reciben `usuario_id` (PROC-REP-110 rama No no declara actor;
PROC-REP-120 es ACT-SYSTEM). `409` fuera del nodo correspondiente; `404` si la
Orden no existe; respuesta `200 OrdenOut`.

En 100/120 el circuito de recursos tiene **prioridad** sobre el hito de
workflow: no se ofrecen `DEFINIR_REPARACION`, `DEFINIR_REPARACION_DESDE_REVISION`,
`ENCOLAR`, `TOMAR` ni `INICIAR_DETALLE`. Las capacidades transversales (pago,
según la política del Origen) siguen publicándose.

`REVALIDAR_RECURSOS` es el botón que dispara a mano el evento de sistema que V1.3
describe ("cambio de disponibilidad de insumos → volver a 080"); no hay
notificación automática cuando entra stock.

`DetalleOut` ahora expone `condicion` (ya existía en dominio/JSON) y la UI muestra
"Bloqueado por recursos" a partir de ese dato, sin inferirlo del stock.
`REQUIERE_DEFINICION` se visualiza pero su flujo no está implementado.

`progreso` intercala `100/110/120` (una sola vez, aunque haya varios ciclos)
después de 090 cuando hay evidencia de `PROC-REP-100` en el historial, y se
combina con la ruta de revisión (evidencia de `PROC-REP-055`). No se guarda
ningún id de Scenario.

## Multi-Detalle

- *A trabajable + B bloqueado*: 090 Sí → 140 (`HABILITADA`). `INICIAR_DETALLE`
  solo se ofrece para A; iniciar B por llamada directa da 409 (guard de
  `DEFINIDO + SIN_BLOQUEO`).
- *A y B bloqueados*: `PENDIENTE_RECURSOS`, un 100 por Detalle con sus faltantes
  propios, luego `ESPERAR_RECURSOS`.

## Cambio deliberado respecto de Slices anteriores

Slice 4 caracterizaba "factibilidad fallida luego de revisión → 409 y nada
persistido". Queda **obsoleto a propósito**: ahora se persiste el Detalle
bloqueado y la Orden queda en 100. Lo mismo ocurre con
`test_la_factibilidad_bloquea_cuando_el_stock_ya_esta_reservado` (HP-REP-001):
antes 409, ahora 200 con la Orden en 100. No son regresiones: es la excepción
que faltaba.

## Fuera de alcance

`EXC-REP-002` (override, PROC-REP-130), `EXC-REP-003` (reserva fallida, 186),
`EXC-REP-004` (125/126/127), `EXC-REP-005`, `DESPERDICIO`, `OrdenRevision`,
`RT_GARANTIA_VENTA`, `SIN_REPARACION`, cancelación, PostgreSQL, notificaciones
automáticas de stock. `PROC-REP-120` desde `PROC-REP-211` tampoco se conecta
aquí.

UAT (`UAT-REP-029..031`) siguen `PENDING`.
