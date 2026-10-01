# Implementation Plan: HP-REP-003 — Garantía de reparación RMA

**Branch**: `mvp-v2-slice3-hp-rep-003` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

## Summary

Conectar el origen `RMA_GARANTIA_REPARACION` (ya declarado en el dominio y
en `domain.politicas`) al flujo operativo, siguiendo
`business/scenarios/repair-management-scenarios-v1.3.yaml` (HP-REP-003).
El comportamiento por Origen sigue decidiéndose solo por `PoliticaOrigen`;
el circuito técnico (priorizar → entregar) se reutiliza sin versiones
`*_garantia`.

## Cambios por capa

| Capa | Cambio |
|---|---|
| `domain/models` | `OrdenReparacion.orden_origen_id`, `ReparacionDetail.detalle_origen_id` (default `None`) |
| `services/ordenes.py` | `crear_orden_garantia_rma` (PROC-REP-035 → 040) |
| `services/reparaciones.py` | `definir_reparacion_detail(..., detalle_origen_id=None)` |
| `services/pagos.py` | `condicion_entrega_cumplida`; `validar_condicion_entrega` generalizada (observación `NO_COBRABLE_POR_ORIGEN`) |
| `services/documentos.py`, `services/ordenes.py::entregar_equipo`, `application/cierre.py::entregar` | usan `condicion_entrega_cumplida` |
| `application/ingreso.py` | `crear_garantia_rma`; helper privado `_finalizar_definicion` compartido con `definir_reparacion` |
| `application/acciones.py` | `GENERAR_GARANTIA_RMA` por Detalle de Orden `ENTREGADA` con Cliente |
| `application/progreso.py` | `_RUTA_RMA_GARANTIA_REPARACION` |
| `api` | `POST /api/orders/{id}/details/{detalle_id}/warranty-rma` (201); `orden_origen_id` / `detalle_origen_id` en los DTOs |
| `frontend` | tipos, `generarGarantiaRma`, acción `GENERAR_GARANTIA_RMA`, referencias de origen |

## Decisiones técnicas

- Un único comando de aplicación dentro de `seccion_critica_inventario`
  (numeración de Orden y factibilidad consistentes). Si algo falla no se
  persiste nada; la Orden origen solo se lee y nunca se guarda.
- `crear_orden_garantia_rma` copia Cliente y Equipo con `model_copy(deep=True)`
  y no comparte instancias con la Orden origen.
- `acciones_disponibles` conserva `[]` para `ENTREGADA` sin Cliente y para
  fin de proceso; solo una Orden `ENTREGADA` con Cliente publica la garantía.
- No se agregan validaciones temporales de garantía (BR-REP-019 las deja
  pendientes).

## Verificación

- `tests/test_hp_rep_003.py` (services), `tests/test_api_hp_rep_003.py`
  (HTTP E2E, compatibilidad JSON, negativos).
- `tests/test_caracterizacion_hp1.py::test_entregada` cambia de `[]` a
  `GENERAR_GARANTIA_RMA` por Detalle (cambio intencional de este slice).
- `npm run validate:all` (incluye validador global y guard de Source of
  Truth), `tsc`, `npm run build`.
