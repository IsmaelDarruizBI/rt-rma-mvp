# Implementation Plan: Feedback de pruebas MVP v2

**Branch**: `mvp-v2` | **Date**: 2026-10-02 | **Spec**: [spec.md](./spec.md)

**Estado**: implementado.

## Summary

Separar agregar Detalle de finalizar la definición, implementar
SIN_REPARACION (068 No → 069) con cierre por Origen, unificar la garantía RMA
en un único inicio con revisión obligatoria para 1..N Detalles origen,
convertir el override en una capacidad transversal por Detalle y ajustar la
UX de la Ejecución. Todo derivado del historial: sin flags, sin estados nuevos,
sin ramas por Scenario.

## Cambios por capa

| Capa | Cambio |
|---|---|
| `services/reparaciones.py` | `definicion_finalizada` (080 en el historial), `exigir_definicion_finalizable`; `definir_reparacion_detail` rechaza RMA y una definición cerrada; `definir_reparacion_detail_luego_revision` rechaza SIN_REPARACION y definición cerrada |
| `services/revisiones.py` | `registrar_finalizacion_sin_reparacion` (068 No → 069), `finalizada_sin_reparacion`, `lista_para_cierre` |
| `services/ordenes.py`, `pagos.py`, `documentos.py`, `application/cierre.py` | gates de cierre con `lista_para_cierre`; comprobante final sin garantía para SIN_REPARACION; `crear_orden_garantia_rma` con `detalle_origen_ids` (1..N) |
| `services/recursos.py` | `autorizar_override_recursos` (acción funcional ACC-REP-049, sin mover `current_process`), `continuar_por_override` (110 Sí → 130, solo desde 100); vigencia por ACC-REP-049 posterior al último 127 |
| `application/ingreso.py` | `definir_reparacion` / `definir_reparacion_desde_revision` solo agregan; `finalizar_definicion`; `finalizar_sin_reparacion`; `iniciar_garantia_rma` (reemplaza `crear_garantia_rma` y `crear_garantia_rma_en_revision`) |
| `application/recursos.py` | `forzar_detalle_por_recursos`: autoriza siempre; continúa y habilita solo en 100 |
| `application/acciones.py` | acciones de definición, `FINALIZAR_SIN_REPARACION`, `INICIAR_GARANTIA_RMA` de Orden; `_overrides_de_recursos` (en 100/120 junto al circuito de recursos, con factibilidad parcial después del taller) |
| `application/progreso.py` | ruta RMA con 055/065/068/075; `_con_revision` idempotente; `_sin_reparacion` (068 → 069 → 250) |
| `application/consultas.py` | `detalles_origen_de` (nombre del Tipo de cada Detalle origen) |
| `api/schemas.py`, `api/ordenes.py` | sin `finalizar_definicion`; `FinalizarDefinicionIn`, `FinalizarSinReparacionIn`, `IniciarGarantiaRmaIn`, `DetalleOrigenOut`; `OrdenOut.detalles_origen` y `finalizada_sin_reparacion`; endpoints `definition/finalize`, `review/without-repair`, `warranty-rma`; se eliminan los endpoints de garantía por Detalle |
| `frontend` | formularios por intención (agregar, finalizar, sin reparación, garantía con casillas, origen por nombre); `FormularioEjecucion` con `modo`; Completar \| Interrumpir responsivo |

## Decisiones tomadas al implementar

- **Override en 120**: la misma validación aplica (Detalle bloqueado), así que
  se ofrece también en 120; autoriza el Detalle y la revalidación existente
  (120 → 080 → 090) lo encuentra trabajable. No se recorre 110/130 fuera del
  circuito de 100.
- **Orden de acciones**: en 100/120 el override va junto a esperar/revalidar
  (las ramas de 110); con factibilidad parcial va después de las acciones del
  taller, para no desplazar Iniciar/Liberar/Completar.
- **Comprobante en el camino de revisión**: finalizar no lo regenera si
  PROC-REP-050 ya está en el historial (dato, no flag).
- **Mobile**: el Historial (preexistente) ensanchaba la pantalla a ~715 px en
  un teléfono, lo que impedía apilar Completar | Interrumpir. Se corrigió con
  `minmax(0, 1fr)` en la grilla de la Orden y desplazamiento horizontal del
  Historial dentro de su panel.
