# Implementation Plan: EXC-REP-001

**Branch**: `mvp-v2-slice6-exc-rep-001` | **Date**: 2026-10-01 | **Spec**: [spec.md](./spec.md)

## Summary

Completar BR-REP-002 (factibilidad por Detalle) y conectar el circuito de
espera de recursos (100 → 110 No → 120 → 080), reutilizando la
infraestructura existente: `CondicionReparacionDetail`, el resolver de
BR-REP-012, el gate de `habilitar_orden` y las rutas derivadas del
progreso. Sin estados de workflow nuevos ni campos persistidos nuevos.

## Cambios por capa

| Capa | Cambio |
|---|---|
| `services/reparaciones.py` | `validar_factibilidad_detalles` por Detalle (condición, 090 `Si`/`Ninguno trabajable`, 100 por Detalle bloqueado); helper `_faltantes_del_detalle` |
| `services/recursos.py` (nuevo) | `registrar_espera_recursos` (110 No → 120, valida 100 + resolver `PENDIENTE_RECURSOS`), `exigir_espera_por_recursos` |
| `services/recursos.py` / `services/ordenes.py` | `marcar_pendiente_recursos` (compartida por 110 y 211); `evaluar_situacion_orden` cierra la toma en `PENDIENTE_RECURSOS` y va directo a 120; `habilitar_orden` acepta `EN_REPARACION` con el gate de 090 `Si` |
| `application/ingreso.py` | `_validar_y_habilitar` ya no lanza `RecursoNoDisponibleError` si ninguno es trabajable: devuelve la Orden en 100 y el caller la guarda |
| `application/recursos.py` (nuevo) | `esperar_recursos`, `revalidar_recursos` (reutiliza `_validar_y_habilitar` para 080 → 140) |
| `application/acciones.py` | `ESPERAR_RECURSOS` / `REVALIDAR_RECURSOS` con prioridad en 100/120; el pago transversal se conserva |
| `application/progreso.py` | `_con_espera_de_recursos` (100/110/120 una vez, por evidencia) |
| `api` | `POST /resources/wait` y `/resources/revalidate` (sin body); `DetalleOut.condicion` |
| `frontend` | `CondicionDetalle`, `esperarRecursos`/`revalidarRecursos`, botones y etiqueta de bloqueo |

## Decisiones técnicas

- En 100/120 `acciones_disponibles` neutraliza el hito de workflow (`estado =
  None`) en lugar de hacer `return`, así los pagos transversales siguen
  evaluándose con su regla normal.
- `habilitar_orden` no cambia: el gate de 090 `Si` ya impide habilitar desde
  100.
- La factibilidad evalúa cada Detalle contra la disponibilidad actual
  (no acumulada entre Detalles), igual que antes pero sin el "todo o nada".
- `RecursoNoDisponibleError` se mantiene para 185 (reserva real).

## Verificación

- `tests/test_exc_rep_001.py` (services, 15 casos) y
  `tests/test_api_exc_rep_001.py` (HTTP, 11 casos): bloqueo, 100 por
  Detalle, esperar/revalidar y sus guards, ciclos repetidos, reservas
  externas y liberación, CLIENTE_EXTERNO / RT_INTERNO / RMA / VAR-001,
  Multi-Detalle parcial y totalmente bloqueado.
- Tests actualizados por el cambio deliberado: factibilidad fallida de
  Slice 4, `test_la_factibilidad_bloquea_cuando_el_stock_ya_esta_reservado`
  y `test_habilitar_rechaza_090_con_faltantes`.
- `npm run validate:all`, `tsc`, `npm run build`.
