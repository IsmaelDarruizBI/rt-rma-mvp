# Implementation Plan: VAR-REP-001 + VAR-REP-002

**Branch**: `mvp-v2-slice4-var-rep-001-002` | **Date**: 2026-10-01 | **Spec**: [spec.md](./spec.md)

## Summary

Conectar `EstadoWorkflow.EN_REVISION` (declarado en Slice 0) al flujo
operativo siguiendo VAR-REP-001/002. Principios: el comprobante depende
solo de `PoliticaOrigen`; los Happy Paths no cambian; la revisión es una
**capacidad** (no una entidad) con frontera reemplazable por un futuro
`OrdenRevision`.

## Cambios por capa

| Capa | Cambio |
|---|---|
| `domain/models` | `OrdenReparacion.detalles_origen_ids: list[str]` (default `[]`); docstring de `EN_REVISION` |
| `services/ordenes.py` | `marcar_orden_en_revision` (045 No → 055); `habilitar_orden` acepta `EN_REVISION` y exige venir de 090 `Si`; `crear_orden_garantia_rma` completa `detalles_origen_ids` |
| `services/revisiones.py` (nuevo) | `registrar_revision_tecnica` (065), `revision_tecnica_realizada` |
| `services/reparaciones.py` | `definir_reparacion_detail_luego_revision` (068 Sí una vez → 075); helper privado `_detalle_con_snapshot` compartido con 070; `_detalle_origen_para` |
| `application/ingreso.py` | `enviar_a_revision`, `crear_garantia_rma_en_revision`, `definir_reparacion_desde_revision`; `_finalizar_definicion` se parte en comprobante + `_validar_y_habilitar` (080 → 140) |
| `application/revision.py` (nuevo) | `realizar_revision` |
| `application/acciones.py` | `ENVIAR_A_REVISION`, `REALIZAR_REVISION`, `DEFINIR_REPARACION_DESDE_REVISION`, `GENERAR_GARANTIA_RMA_REVISION` |
| `application/progreso.py` | `_con_revision` deriva la ruta de revisión de la del Origen si hay `PROC-REP-055` |
| `api` | 4 endpoints finos; `detalles_origen_ids` en `OrdenOut` |
| `frontend` | tipos (`EN_REVISION`, `detalles_origen_ids`), cliente API, formulario de resultado de revisión, reutiliza el formulario de definición |

## Decisiones técnicas

- `_finalizar_definicion` conserva su nombre (comprobante + 080 → 140) para
  el camino de Detalles conocidos; el camino de revisión usa solo
  `_validar_y_habilitar`. Sin Strategy / Command Bus / workflow engine.
- La garantía en revisión usa la misma sección crítica y las mismas
  validaciones que HP-REP-003; la Orden origen no se guarda.
- Roles: validar_actor → `PrecondicionInvalidaError` → HTTP 409 (sin 403).
- No se agregó ningún campo `scenario_id`/`variant_id` a la Orden.

## Verificación

- `tests/test_var_rep_001_002.py` (services, acciones, progreso,
  persistencia) y `tests/test_api_var_rep_001_002.py` (HTTP E2E:
  CLIENTE_EXTERNO, RT_INTERNO, garantía RMA con cambio de catálogo,
  Multi-Detalle, autorización 409, negativos).
- `tests/test_caracterizacion_hp1.py`: una Orden recién creada ofrece
  además `ENVIAR_A_REVISION`; una entregada ofrece ambas garantías
  (cambios intencionales).
- `npm run validate:all` (incluye validador global y guard del Source of
  Truth), `tsc`, `npm run build`.
