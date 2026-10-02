# Feature Specification: EXC-REP-004 — Detalle requiere revisión técnica posterior

**Feature Branch**: `mvp-v2-slice9-exc-rep-004`

**Created**: 2026-10-01

**Status**: Implemented (Scenario EXC-REP-004, Exception)

**Business Feature**: `FEAT-REP-002` (resuelve `REQUIERE_DEFINICION`), con
dependencia de `FEAT-REP-005` (la produce al cerrar una Ejecución).

**Source Process**: `PROC-REP` V1.3. Source of Truth sincronizado desde
`rt-rma-app@3728d9b` ("docs: define EXC-REP-004 redefinition flow"), portando
solo el delta `a341cc1..3728d9b`.

**Implemented Scenario (objetivo)**: `EXC-REP-004`; aplica a `HP-REP-001`,
`HP-REP-002` y `HP-REP-003`.

**Reglas**: `BR-REP-003` (vigencia del override), `BR-REP-004` (tres resultados
de 200), `BR-REP-012` (REQUIERE_REVISION), `BR-REP-015` (definición histórica),
`BR-REP-018` (cierre de toma); `BR-REP-001`, `BR-REP-019` (garantía).

> **ALCANCE.** Un Detalle YA EXISTENTE resulta mal definido durante el trabajo
> técnico. El técnico lo declara al cerrar la Ejecución (PROC-REP-200
> "Requiere redefinicion"); cuando no queda otro Detalle trabajable, la Orden
> entra al circuito 125 → 126 → 127 → 080. Cierra `TASK-REP-030`.

## Productor de `REQUIERE_DEFINICION`

```
190 → 200 "Requiere redefinicion" → 210 → 211
```

Resultado de PROC-REP-200 "Requiere redefinicion":

| Elemento | Valor |
|---|---|
| Ejecución | `INTERRUMPIDO` (no hay `EstadoEjecucion` nuevo) — conserva técnico, estación (toma), inicio, fin, trabajo, observaciones e insumos utilizados |
| Detalle | `DEFINIDO` (representación técnica de PENDIENTE) + `REQUIERE_DEFINICION` |
| Motivo | **obligatorio** |
| Historial | `PROC-REP-200` con `observacion = "Requiere redefinicion"` y el motivo |

### Diferencia con `Interrumpido` (VAR-REP-003)

| Resultado de 200 | Ejecución | Detalle | Significado |
|---|---|---|---|
| Completado | `COMPLETADO` | `COMPLETO` | terminado |
| Interrumpido | `INTERRUMPIDO` | `DEFINIDO` + `SIN_BLOQUEO` | la definición sigue válida |
| **Requiere redefinicion** | `INTERRUMPIDO` | `DEFINIDO` + **`REQUIERE_DEFINICION`** | la definición dejó de ser válida |

La diferencia vive en la `condicion` del Detalle y en el historial de 200, no
en el estado de la Ejecución.

## Inventario (PROC-REP-210)

Igual que los otros dos resultados: lo utilizado → `CONSUMO`; lo reservado y no
utilizado → `LIBERACION_RESERVA`. No queda ninguna reserva activa de la
Ejecución cerrada. Con override vigente del Detalle (EXC-REP-002) el consumo
puede dejar stock negativo como hoy.

## Caso A — Multi-Detalle

```
DET-A en ejecución, DET-B DEFINIDO + SIN_BLOQUEO
200 "Requiere redefinicion" (A) → 210 → 211 ABIERTA_TRABAJABLE
```

- DET-A queda `DEFINIDO` + `REQUIERE_DEFINICION` (pendiente de revisión);
- DET-B sigue trabajable; la **toma sigue ACTIVA**;
- el técnico puede iniciar DET-B (`212 Sí → 181`) o liberar.

No se llega a 125 mientras exista otro trabajable (prioridad 4 > 5 de
BR-REP-012). Cuando deje de existir (por ejemplo, DET-B completado):
`211 = REQUIERE_REVISION → cierre de toma → 125`.

Si el otro Detalle está `BLOQUEADO_POR_RECURSOS`, gana `REQUIERE_REVISION`
(prioridad 5 > 6).

## Caso B — ningún otro trabajable

```
200 "Requiere redefinicion" → 210 → 211 REQUIERE_REVISION → cierre de toma → 125
→ 126 (Técnico) → 127 (Recepción) → 080 → 090 Sí → 140   |   090 Ninguno → 100
```

`estado_workflow` se conserva (normalmente `EN_REPARACION`; el productor solo
existe después de un 185 exitoso). No existe `EstadoWorkflow.REQUIERE_REVISION`:
es la situación derivada del resolver.

## PROC-REP-125 (ACT-SYSTEM)

- Solo desde 211 con `REQUIERE_REVISION`; lo compone `evaluar_situacion_orden`
  (211 → cierre de toma → 125), análogo a `211 PENDIENTE_RECURSOS → 120`.
- Registra 125; no toca el workflow ni los Detalles; no crea una revisión.

## PROC-REP-126 (ACT-TECH)

Precondiciones: Orden en el circuito de revisión (`current_process` 125, o 126
de otro Detalle pendiente); Detalle `DEFINIDO` + `REQUIERE_DEFINICION`; sin
Ejecución activa; sin toma activa; usuario TECNICO activo.

Registra usuario, fecha, Detalle y el resultado/observaciones técnicas
(obligatorio). No crea `TomaOrden` (no pasa por 170/172/180). No modifica Tipo
ni snapshot.

## PROC-REP-127 (ACT-RECEP)

Precondiciones: Detalle `DEFINIDO` + `REQUIERE_DEFINICION`; un 126 de ESE
Detalle en su ciclo actual (posterior a su último 200 "Requiere
redefinicion"); Orden en el circuito (125/126); `TipoReparacion` activo; usuario
RECEPCION activo. Un 126 de otro Detalle o de un ciclo anterior no habilita.

Efectos:

- mismo `detalle_id`, `detalle_origen_id` y Ejecuciones históricas;
- la definición vigente pasa al histórico (tipo, precio, puntaje, garantía,
  fecha de reemplazo, usuario) — **también si se confirma el mismo Tipo**;
- nueva definición vigente: `tipo_reparacion_id` y snapshots del Tipo elegido;
- `condicion = SIN_BLOQUEO`;
- registra 127 y encadena 080 → 090 (Sí → 140 / Ninguno → 100).

## Override previo (BR-REP-003, vigencia)

Un override (PROC-REP-130) es válido solo si ocurrió **después del último
PROC-REP-127 del mismo Detalle**. Cualquier 127 invalida los anteriores, incluso
con el mismo Tipo. Si tras 127 falta stock, hace falta un override nuevo. La
semántica de EXC-REP-002 (reserva y consumo con disponibilidad/stock negativos
para un override vigente) no cambia.

## Precio y pagos

`total = Σ snapshots vigentes`, `saldo = total − pagado` (comportamiento actual).
Un precio mayor genera saldo pendiente; uno menor puede dejar saldo negativo
(pago excedente). El tratamiento del excedente y la aceptación del cliente ante
un aumento quedan **pendientes** en el Source of Truth y no bloquean el Slice.

## Garantía RMA (HP-REP-003)

127 no modifica `detalle_origen_id` ni `orden_origen_id`; no se crea un Detalle
nuevo.

## Fuera de alcance

EXC-REP-005 (PROC-REP-235), cancelaciones, `DESPERDICIO`, override de estación
(176/178/179), el caso "126/127 no logra definir el Detalle" (pendiente del
SoT), tratamiento comercial del excedente, PostgreSQL.

## Implementación (Slice 9)

| Pieza | Dónde |
|---|---|
| Tercer resultado de 200 | `services/ejecuciones.py::registrar_ejecucion_requiere_redefinicion` (núcleo común `_registrar_fin_ejecucion` + `condicion_del_detalle`); motivo en `EjecucionReparacion.motivo_redefinicion` |
| Comando | `application/taller.py::requerir_redefinicion_ejecucion` (reutiliza `_cerrar_ejecucion`, sección crítica) |
| 211 → 125 | `services/ordenes.py::evaluar_situacion_orden` + `services/redefinicion.py::marcar_pendiente_revision` |
| 126 / 127 | `services/redefinicion.py` + `application/redefinicion.py` (127 encadena `_validar_y_habilitar`) |
| Histórico | `ReparacionDetail.definiciones_anteriores: list[DefinicionAnteriorDetalle]` (default `[]`) |
| Override | `services/recursos.py::tiene_override_factibilidad` (130 posterior al último 127) |
| API | `POST …/executions/{id}/requires-redefinition`, `POST …/details/{id}/technical-review`, `POST …/details/{id}/redefine` → `200 OrdenOut`; 404/409/422 |
| Acciones | `REQUIERE_REDEFINICION`, `REVISAR_DETALLE`, `REDEFINIR_DETALLE` |
| Progreso | 125 → 126 → 127 tras 211 (y tras 120 si existe), por evidencia |

**Escrituras.** 126 y 127 (con 080) guardan la Orden una vez. El cierre
"Requiere redefinicion" reutiliza el cierre común de 200 y el contrato de
PROC-REP-210 (`aplicar_movimientos_inventario` guarda la Orden antes de mover el
stock del catálogo, para que un reintento sea idempotente) más la escritura
final con 211 [→ 125]: dos escrituras, igual que Completado e Interrumpido
(`TASK-REP-092` sigue abierta).

