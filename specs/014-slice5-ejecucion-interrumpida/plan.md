# Implementation Plan: VAR-REP-003 — Ejecución interrumpida

**Branch**: `mvp-v2-slice5-var-rep-003` | **Date**: 2026-10-01 | **Spec**: [spec.md](./spec.md)

## Summary

Agregar el resultado `Interrumpido` de PROC-REP-200 reutilizando la
infraestructura existente: mismo cierre de Ejecución, misma reconciliación
de inventario y mismo resolver de PROC-REP-211. Sin ramas por Origen ni por
Scenario; sin nuevos estados de Detalle ni de toma.

## Cambios por capa

| Capa | Cambio |
|---|---|
| `domain/models/enums.py` | `EstadoEjecucion.INTERRUMPIDO` (aditivo) |
| `services/ejecuciones.py` | `registrar_ejecucion_interrumpida`; helper privado `_registrar_fin_ejecucion` compartido con `registrar_ejecucion_completada` (funciones públicas explícitas) |
| `services/inventario.py` | `generar_movimientos_inventario` rechaza una Ejecución `EN_PROGRESO` |
| `application/taller.py` | `interrumpir_ejecucion`; helper `_cerrar_ejecucion` (190 → 200 → 210 → 211) compartido con `completar_ejecucion` |
| `application/acciones.py` | `INTERRUMPIR_EJECUCION` |
| `api` | `POST .../executions/{id}/interrupt` + `InterrumpirEjecucionIn` |
| `frontend` | `EstadoEjecucion`, `interrumpirEjecucion`, formulario reutilizado con texto de botón configurable, panel de Ejecuciones con su estado real |

`registrar_ejecucion_*` y `_cerrar_ejecucion` se parametrizan por el
resultado; no hay Strategy ni jerarquías. `resolver_situacion_orden` no se
modifica. No se guarda `scenario_id` ni `variant_id` en la Orden; no hay
nueva ruta de progreso.

## Verificación

- `tests/test_var_rep_003.py` (services: interrupción, guards, inventario
  0/parcial/total con reserva de 2, gate de 210, 211, acciones, nueva
  Ejecución, Orígenes, JSON) y `tests/test_api_var_rep_003.py` (HTTP:
  E2E, mismo técnico, otro técnico tras liberar, stock físico,
  autorización 409/404, `/complete` intacto, RT_INTERNO, garantía RMA,
  Multi-Detalle).
- `tests/test_caracterizacion_hp1.py::test_en_reparacion`: ahora incluye
  `INTERRUMPIR_EJECUCION` (cambio intencional).
- `npm run validate:all`, `tsc`, `npm run build`.
