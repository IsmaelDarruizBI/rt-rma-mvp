# Implementation Plan: EXC-REP-004

**Branch**: `mvp-v2-slice9-exc-rep-004` | **Date**: 2026-10-01 | **Spec**: [spec.md](./spec.md)

**Estado**: implementado (Slice 9). Ver la sección final para las decisiones tomadas al implementar.

## Summary

Agregar el tercer resultado de PROC-REP-200 como productor de
`REQUIERE_DEFINICION`, conectar `211 REQUIERE_REVISION → 125`, implementar
126/127 sobre el mismo Detalle con definición histórica append-only, y acotar la
vigencia del override al último 127. Todo derivado del historial y de la
condición del Detalle, sin flags de Scenario.

## Cambios previstos por capa

| Capa | Cambio previsto |
|---|---|
| `domain/models/reparacion.py` | `ReparacionDetail.definiciones_anteriores: list[<DefinicionAnterior>]` (append-only, default vacío → JSON existente sigue cargando): `tipo_reparacion_id`, `precio`, `puntaje`, `garantia_dias`, `reemplazada_en`, `usuario_id`. Nombre final a decidir en implementación |
| `services/ejecuciones.py` | `_registrar_fin_ejecucion` gana `condicion_del_detalle` (default: no cambiar). Nuevo `registrar_ejecucion_requiere_redefinicion` (resultado `INTERRUMPIDO`, Detalle `DEFINIDO` + `REQUIERE_DEFINICION`, motivo obligatorio, `observacion_200 = "Requiere redefinicion"`) |
| `services/ordenes.py` | `REQUIERE_REVISION` entra en `_RESULTADOS_QUE_CIERRAN_LA_TOMA`; `evaluar_situacion_orden` compone 211 → 125 |
| `services/revisiones.py` (o módulo nuevo) | `registrar_detalle_pendiente_revision` (125), `revisar_detalle` (126), `redefinir_detalle` (127) |
| `services/reparaciones.py` | reutilizar `_detalle_con_snapshot` para la nueva definición; `validar_factibilidad_detalles` ya no pisa `REQUIERE_DEFINICION` |
| `services/recursos.py` | `tiene_override_factibilidad`: solo cuenta un 130 posterior al último 127 del Detalle (sin boolean nuevo) |
| `application/taller.py` | tercer comando paralelo a `completar_ejecucion`/`interrumpir_ejecucion` reutilizando `_cerrar_ejecucion` (190 → 200 → 210 → 211 [→ 125]) dentro de `seccion_critica_inventario` |
| `application/` (revisión) | comandos 126 y 127; 127 encadena `_validar_y_habilitar` (080 → 090 → 140 / 100), una sola escritura |
| `application/acciones.py` | `REQUIERE_REDEFINICION` junto a completar/interrumpir; `REVISAR_DETALLE` (TECNICO) en 125 por Detalle `REQUIERE_DEFINICION`; `REDEFINIR_DETALLE` (RECEPCION) en 126; neutralizar el hito en 125/126 como en 100/120 |
| `application/progreso.py` | 200 "Requiere redefinicion", 125, 126 y 127 por evidencia del historial |
| `api/ordenes.py`, `api/schemas.py` | `POST …/executions/{id}/requires-redefinition`, `POST …/details/{id}/review`, `POST …/details/{id}/redefine` (nombres finales según convención) |
| `frontend` | formularios: motivo (200), resultado (126), Tipo (127; selector existente) |

## Decisiones técnicas

- **Sin nuevo `EstadoEjecucion`**: la Ejecución queda `INTERRUMPIDO`; la causa es
  la `condicion` del Detalle + historial.
- **Sin duplicar el cierre**: los tres resultados comparten
  `_registrar_fin_ejecucion` y `_cerrar_ejecucion`; 210 no cambia (ya concilia
  cualquier Ejecución terminal).
- **211 → 125 compuesto** en `evaluar_situacion_orden`: 125 es ACT-SYSTEM sin
  decisión propia.
- **126 sin `TomaOrden`**: el autor queda en `usuario_id` del historial, como
  PROC-REP-065.
- **Definición histórica append-only dentro del agregado**: sin event sourcing;
  serializa a JSON y migra a una tabla hija en PostgreSQL.
- **Override acotado temporalmente** derivándolo del historial (130 después del
  último 127).
- **127 → 080 en el mismo comando**, como `definir_reparacion` y
  `revalidar_recursos`.

## Riesgos / regresiones a vigilar

- EXC-REP-002: override vigente sigue permitiendo reserva/consumo negativos.
- EXC-REP-003: 185 → 186 y `habilitar_orden` con `EN_COLA` intactos.
- VAR-REP-003: "Interrumpido" sigue dejando `SIN_BLOQUEO`.
- EXC-REP-001: 211 → 120 sigue igual; prioridad del resolver sin cambios.

## Verificación prevista

Tests de services y API para: Caso A/B, 210 (consumo + liberación), 125
compuesto y cierre de toma, precondiciones 126/127, definición histórica
(incluido mismo Tipo), override invalidado por 127, 127 → 080 (140 y 100),
prioridad mixta con `BLOQUEADO_POR_RECURSOS`, precio/saldo, RT_INTERNO y garantía
RMA, una sola escritura por comando, regresión HP/EXC/VAR.

## Decisiones tomadas al implementar

- Modelo: `DefinicionAnteriorDetalle` (tipo, precio, puntaje, garantía,
  `reemplazada_en`, `usuario_id`) en `ReparacionDetail.definiciones_anteriores`,
  default `[]`: el JSON existente carga sin migración.
- Motivo del 200 "Requiere redefinicion": `EjecucionReparacion.motivo_redefinicion`
  (estructurado); el historial conserva `observacion = "Requiere redefinicion"`.
- Ciclo de redefinición de un Detalle: empieza en su último 200 "Requiere
  redefinicion"; solo un 126 posterior de ESE Detalle habilita 127
  (`revision_vigente`). 126/127 se aceptan desde 125 o 126 para poder revisar
  varios Detalles pendientes.
- `REQUIERE_REDEFINICION` se publica con rol TECNICO, igual que completar e
  interrumpir; la propiedad de la Ejecución la valida el service.
- 127 → 080 corre en la sección crítica de inventario (la factibilidad lee stock
  y reservas ajenas).
- Escrituras del cierre: se conserva el contrato de PROC-REP-210 (dos
  escrituras, como Completado/Interrumpido); 126 y 127 escriben una vez.
- Tests existentes ajustados: `test_caracterizacion_hp1.py::test_en_reparacion`
  (la lista de acciones con Ejecución activa suma `REQUIERE_REDEFINICION`).

