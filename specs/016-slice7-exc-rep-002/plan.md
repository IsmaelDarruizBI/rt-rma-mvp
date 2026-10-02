# Implementation Plan: EXC-REP-002

**Branch**: `mvp-v2-slice7-exc-rep-002` | **Date**: 2026-10-01 | **Spec**: [spec.md](./spec.md)

## Summary

Completar la decisión de PROC-REP-110 (`Sí → 130 → 140`) reutilizando el
historial como fuente de verdad y el circuito de recursos de EXC-REP-001. El
override registra la autorización; la reserva y el consumo siguen en 185 y
210, donde la autorización habilita disponible/stock negativo solo para el
Detalle forzado.

## Cambios por capa

| Capa | Cambio |
|---|---|
| `business/` | aclaración de `BR-REP-003` y de la descripción de `EXC-REP-002` (stock negativo con override); sin cambiar IDs ni Process Graph |
| `domain/models/catalogos.py` | `Insumo.stock_fisico` admite negativos (sin `ge=0`) |
| `services/recursos.py` | `registrar_override_recursos`, `tiene_override_factibilidad` (único lugar), `override_listo_para_habilitar` |
| `services/reparaciones.py` | PROC-REP-080 no rebloquea un Detalle con override |
| `services/ordenes.py` | `habilitar_orden`: gate A) 090 Sí o B) 130 con override válido |
| `services/ejecuciones.py` | PROC-REP-185 omite la comprobación de disponibilidad solo con override del Detalle (atómico) |
| `services/inventario_global.py` | PROC-REP-210 admite stock negativo solo con override del Detalle |
| `application/recursos.py` | `forzar_detalle_por_recursos` (110 Sí → 130 → 140, persiste una vez) |
| `application/acciones.py` / `progreso.py` | `OVERRIDE_RECURSOS` por Detalle bloqueado en 100; nodo 130 por evidencia |
| `api` | `POST /details/{id}/resources/override` + `OverrideRecursosIn` |
| `frontend` | `overrideRecursos`, formulario de motivo obligatorio |

## Decisiones técnicas

- **Sin flag en el Detalle**: el override se deriva del historial con un único
  helper, consultado por factibilidad, 185 y 210.
- **No se fabrica 090 Sí**: el gate B acepta 130 → 140 con evidencia válida.
- **No hay `if scenario == …`**: el comportamiento sale del Detalle, el
  historial, el rol, `current_process` y el stock.
- La comprobación de reserva sin override se conserva intacta
  (`RecursoNoDisponibleError`); desde el Slice 8 la reserva fallida sin override
  se registra como EXC-REP-003 (PROC-REP-186, `specs/017-slice8-exc-rep-003`).

## Verificación

- `tests/test_exc_rep_002.py` (services: flujo, rol, motivo, trazabilidad,
  Detalle objetivo, gate, 185/210 con y sin override, stock negativo, acciones,
  progreso) y `tests/test_api_exc_rep_002.py` (HTTP: E2E, roles, 404/409/422,
  Multi-Detalle, stock negativo por HTTP, RT_INTERNO, garantía RMA).
- Se actualizaron las listas de acciones de EXC-REP-001 en 100 (ahora incluyen
  `OVERRIDE_RECURSOS`); la lógica de EXC-REP-001 no cambió.
- `npm run validate:all`, `tsc`, `npm run build`.
