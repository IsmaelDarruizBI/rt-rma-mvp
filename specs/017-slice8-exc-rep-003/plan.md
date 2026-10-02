# Implementation Plan: EXC-REP-003

**Branch**: `mvp-v2-slice8-exc-rep-003` | **Date**: 2026-10-01 | **Spec**: [spec.md](./spec.md)

## Summary

Convertir la reserva insuficiente de PROC-REP-185 en un resultado funcional
persistido (185 "Reserva fallida" → 186 → 211 [→ 120]) en lugar de un error
técnico, reutilizando el resolver, el cierre de toma y el tramo 211 → 120 de
EXC-REP-001 y respetando el override de EXC-REP-002.

## Cambios por capa

| Capa | Cambio |
|---|---|
| `business/` | ninguno (el Scenario ya define 185 → 186 → 211) |
| `services/inventario.py` | `faltantes_del_detalle`: única lógica de disponibilidad por Detalle |
| `services/reparaciones.py` | PROC-REP-080 usa el helper; se elimina `_faltantes_del_detalle` |
| `services/ejecuciones.py` | `intentar_reserva_e_inicio` → `(Orden, bool)`; `registrar_reserva_fallida` (186); precondiciones comunes; 185 exitoso intacto |
| `services/ordenes.py` | `habilitar_orden` acepta `EN_COLA` (gate intacto) |
| `services/tomas.py` | solo el comentario de `_ORIGENES_DE_LA_DECISION_212` (186 → 211 → 212 → 181) |
| `application/taller.py` | `iniciar_detalle`: 181 → 174 → intento de 185 → [211] → guardar una vez, en la sección crítica |
| `application/progreso.py` | 186 tras 185 y 120 tras 211 por evidencia |
| `api` / `frontend` | sin cambios de código (el 200 ya devuelve `OrdenOut`) |

## Decisiones técnicas

- **`reservar_insumos_e_iniciar_ejecucion` no cambia de firma**: sigue siendo el
  camino exitoso y conserva `RecursoNoDisponibleError` como defensa. La
  composición nueva es `intentar_reserva_e_inicio`.
- **Las precondiciones no son "reserva fallida"**: Detalle, toma y BR-REP-007 se
  validan primero y siguen lanzando `PrecondicionInvalidaError` (409).
- **Sin `if scenario == …` ni flags**: el resultado sale de los faltantes y de
  `tiene_override_factibilidad`; el estado, del historial y la condición.
- **211 lo evalúa `evaluar_situacion_orden`**; no se duplica el resolver ni el
  cierre de toma.
- **Una sola escritura y una sola sección crítica**: la decisión de fallar y
  la de 211 salen del mismo snapshot de inventario.
- **186 no cambia `estado_workflow`** (no inventa `EN_REPARACION`).

## Impacto en otros Slices

- **EXC-REP-001**: sin cambios de lógica; 211 → 120 y el cierre de toma se
  reutilizan tal cual.
- **EXC-REP-002**: el override se evalúa **antes** del chequeo de faltantes; sin
  override el 409 de `test_sin_override_iniciar_con_stock_insuficiente…` pasa a
  200 + 186 (test actualizado).
- **HP-REP-001**: el test que fijaba 409 por stock insuficiente al iniciar
  (`test_stock_insuficiente_al_iniciar…`, y el de concurrencia) pasa a 200 +
  186; la caracterización del Happy Path no cambia.
- **VAR-REP-003**: un Detalle interrumpido vuelve a `DEFINIDO`; un reintento sin
  stock entra en EXC-REP-003.

## Verificación

- `tests/test_exc_rep_003.py` (services): Caso A/B, atomicidad, faltantes,
  concurrencia entre Órdenes, override propio/ajeno, precondiciones, 186,
  habilitar desde `EN_COLA`, progreso, una sola escritura (repo espía).
- `tests/test_api_exc_rep_003.py` (HTTP): Caso A/B E2E, 212 Sí posterior,
  liberar, I-1 (revalidar y continuar), 003 → 120 → 100 → override → 140,
  override propio/ajeno, dos Órdenes, precondiciones 409, RT_INTERNO, garantía
  RMA, VAR-REP-003.
- `npm run validate:all`, `tsc`, `npm run build`.
