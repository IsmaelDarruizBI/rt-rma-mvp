# Feature Specification: Feedback de pruebas MVP v2

**Feature Branch**: `mvp-v2`

**Created**: 2026-10-02

**Status**: Implemented (ajustes sobre HP-REP-001, HP-REP-003, VAR-REP-001/002, VAR-REP-003 y EXC-REP-002)

**Source Process**: `PROC-REP` V1.3. Source of Truth alineado primero en
`rt-rma-app` (garantía con revisión obligatoria y 1..N Detalles origen,
VAR-REP-001 reclasificado, override transversal por Detalle) y portado a
`business/` solo como delta, preservando EXC-REP-001..004, VAR-REP-003 y el
circuito 180 → 212 → 181.

**Reglas**: `BR-REP-001` (definición del requerimiento), `BR-REP-003` (override
justificado: capacidad transversal, vigencia), `BR-REP-010` (SIN_REPARACION),
`BR-REP-019` (garantía RMA), `BR-REP-007` / `BR-REP-018` **sin cambios**.

> **ALCANCE.** Cambios detectados al probar el MVP v2. Arquitectura UI → API →
> Application → Services/Domain → Repositories. `acciones_disponibles` es la
> fuente de verdad de lo que el usuario puede hacer: la UI no deduce reglas.
> Sin flags booleanos, sin estados de workflow nuevos, sin `if scenario ==`,
> persistencia JSON compatible.

## 1. Agregar un Detalle ≠ finalizar la definición

`finalizar_definicion: bool` se elimina de comandos, DTOs y UI. Son dos
intenciones con dos endpoints:

| Intención | Endpoint | Efecto |
|---|---|---|
| Agregar un Detalle (070) | `POST /api/orders/{id}/details` | 045 Sí (una vez) → 070; nunca comprobante, factibilidad ni habilitación |
| Agregar un Detalle tras revisión (075) | `POST /api/orders/{id}/review/details` | 068 Sí (una vez) → 075 |
| **Finalizar la definición** | `POST /api/orders/{id}/definition/finalize` | [050 → 060 si el comprobante no se evaluó] → 080 → 090 → 140 \| 100 |

Finalizar exige ACT-RECEP, al menos un Detalle y la definición abierta
(`definicion_finalizada` se deriva de PROC-REP-080 en el historial). En el
camino de revisión no regenera el comprobante.

Acciones publicadas:

| Situación | Acciones |
|---|---|
| REQUERIMIENTO, 0 Detalles | `AGREGAR_DETALLE` + `ENVIAR_A_REVISION` |
| REQUERIMIENTO, ≥ 1 Detalle | `AGREGAR_DETALLE` + `FINALIZAR_DEFINICION` |
| EN_REVISION tras 065, 0 Detalles | `AGREGAR_DETALLE_DESDE_REVISION` + `FINALIZAR_SIN_REPARACION` |
| EN_REVISION tras 065, ≥ 1 Detalle | `AGREGAR_DETALLE_DESDE_REVISION` + `FINALIZAR_DEFINICION` |

UI: sin casilla; botón **Finalizar definición** con la lista de Detalles cargados.

## 2. PROC-REP-069 SIN_REPARACION

`POST /api/orders/{id}/review/without-repair` (ACT-RECEP), motivo obligatorio,
observaciones opcionales. Registra 068 "No" y 069. Sin Tipo ficticio, sin
Detalles, Subtotal 0, **sin `EstadoWorkflow` nuevo** (`finalizada_sin_reparacion`
y `lista_para_cierre` se derivan del historial). Cierre por Origen:

| Origen | Cierre |
|---|---|
| CLIENTE_EXTERNO | 250 → 260 → 265 → 280 (sin garantía de reparación) → 270; sin pago ofrecido |
| RMA_GARANTIA_REPARACION | igual, NO_COBRABLE |
| RT_INTERNO | 250 → 290 → 270 |

## 3. Garantía RMA canónica

Una única acción de Orden `INICIAR_GARANTIA_RMA` (RECEPCION) reemplaza las dos
acciones por Detalle. `POST /api/orders/{orden_origen_id}/warranty-rma` con
`{usuario_id, detalle_origen_ids}`:

- validaciones: lista no vacía (422), sin repetidos (409), existentes (404),
  Orden origen ENTREGADA con Cliente y actor RECEPCION (409); sin efectos;
- crea **una** Orden nueva EN_REVISION: 035 → 040 → 045 No → 055 → 050 → 060,
  y espera 065. Revisión obligatoria (BR-REP-019);
- no existe bypass: se eliminan `.../details/{id}/warranty-rma[/review]` y el
  camino 045 Sí → 070 (070 rechaza una garantía);
- después de la revisión, cada Detalle nuevo elige su `detalle_origen_id` entre
  `orden.detalles_origen_ids` (obligatorio si hay más de uno; sin relación 1:1);
- la API resuelve el nombre del Tipo de cada Detalle origen (`detalles_origen`)
  para que la UI los muestre ("DET-001 · Cambio de batería").

## 4. Override de recursos transversal por Detalle

Una sola capacidad (`ACC-REP-049`), una validación y una vigencia:

- Coordinador RMA, motivo obligatorio, Detalle `DEFINIDO` + `BLOQUEADO_POR_RECURSOS`;
- afecta solo ese Detalle y no toca el stock;
- con factibilidad parcial (Orden habilitada, en cola, tomada o en reparación)
  **no reinicia**: no vuelve a 140, conserva la toma, no toca la Ejecución en
  curso ni el workflow;
- solo con la Orden detenida en PROC-REP-100 continúa 110 Sí → 130 → 140; en 120
  queda autorizada hasta la revalidación;
- vigencia derivada del historial: un PROC-REP-127 posterior la invalida.

## 5. UX de la Ejecución

`FormularioEjecucion` recibe un `modo` explícito (`completar | interrumpir |
redefinir`): completar propone lo previsto, interrumpir propone 0, redefinir
conserva lo previsto y exige motivo. Completar | Interrumpir lado a lado en
escritorio y apiladas en mobile; Requiere redefinición sigue aparte. La grilla
de la Orden usa `minmax(0, 1fr)` y el Historial se desplaza dentro de su panel,
para que ningún contenido ancho ensanche la pantalla en mobile.

## PENDING BUSINESS DECISION — Paralelismo de Detalles / Ejecuciones

Pregunta abierta al cliente: ¿un mismo equipo puede tener varias reparaciones
trabajándose simultáneamente? Hasta tener respuesta **no se implementa**:

- se mantiene "máximo una Ejecución activa por Orden" (BR-REP-007);
- no se inician varios Detalles en paralelo;
- BR-REP-007 y BR-REP-018 no cambian.

Registrado también en `docs/discovery/README.md`.

## Fuera de alcance

Seed de Órdenes para garantía, migración a PostgreSQL, RT_GARANTIA_VENTA,
cancelaciones, cleanup no relacionado y rediseño visual. El selector de alta
no incluye RMA_GARANTIA_REPARACION.
