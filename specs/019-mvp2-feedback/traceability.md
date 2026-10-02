# Traceability: Feedback MVP v2

Vista narrativa. La fuente machine-readable son los archivos existentes de
`traceability/` (no se creó un archivo nuevo: cada cambio pertenece a una
unidad de implementación ya trazada). Validado con
`npm run validate:traceability` (archivos y global).

## Dónde vive cada cambio

| Cambio | Archivo | Items |
|---|---|---|
| Agregar Detalle ≠ finalizar | `hp-rep-001.yaml` | FR-REP-138, TR-REP-065 (actualizado), TR-REP-136..137, TASK-REP-209, CODE-REP-230..234, TEST-REP-511..520, UAT-REP-040 |
| SIN_REPARACION (068 No → 069) | `var-rep-001-002.yaml` | US-REP-038, ACC-REP-059, FR-REP-139..140, TR-REP-138..140, TASK-REP-028 y 138 (reutilizadas), TASK-REP-210, CODE-REP-235..240, TEST-REP-521..531, UAT-REP-041 |
| Garantía canónica (1..N, revisión obligatoria) | `hp-rep-003.yaml` | FR-REP-080/081/085/086 (extendidos), FR-REP-141..143, TR-REP-080..086 (actualizados), TR-REP-141..142, TASK-REP-211..212, CODE-REP-147/149/150/153/155 (evolucionados), CODE-REP-241..243, TEST-REP-532..537, UAT-REP-042 |
| VAR-REP-001 reclasificado | `var-rep-001-002.yaml` | encabezado, US-REP-026, ACC-REP-038..040, FR-REP-090..092, TR-REP-087/092..094 (actualizados) |
| Override transversal | `exc-rep-002.yaml` | ACC-REP-049/050, FR-REP-112/113/119, TR-REP-112/113/117/118 (extendidos), FR-REP-144, TASK-REP-213, CODE-REP-195 (evolucionado), CODE-REP-244..245, TEST-REP-538..541, UAT-REP-043 |
| UX de la Ejecución | `var-rep-003.yaml` | FR-REP-099 y TR-REP-102 (extendidos), TASK-REP-214, CODE-REP-246..247, UAT-REP-044 |

## Numeración (sin renumerar)

Nuevos: `US-REP-038`, `ACC-REP-059`, `FR-REP-138..144`, `TR-REP-136..142`,
`TASK-REP-209..214` (más `TASK-REP-028` y `TASK-REP-138` reutilizadas),
`CODE-REP-230..247`, `TEST-REP-511..541`, `UAT-REP-040..044` (`PENDING`).

Los artefactos que evolucionaron conservan su ID y actualizan `name`/`source`
(p. ej. `CODE-REP-147` → `iniciar_garantia_rma`, `CODE-REP-195` →
`autorizar_override_recursos`, `TEST-REP-266/272/302/311/312/397/412`).

Los eliminados quedan `status: SUPERSEDED` con `note` hacia su reemplazo:
`CODE-REP-148` (`_finalizar_definicion`), `CODE-REP-165`
(`crear_garantia_rma_en_revision`), `TEST-REP-317/321/322` (garantía por
Detalle y camino directo).

## Evidencia de UI (smoke, fuera del repo)

Smoke headless (Chrome DevTools Protocol) sobre una copia temporal de los
datos demo: 38/38 checks — alta sin RMA, agregar/finalizar, Completar |
Interrumpir lado a lado y apiladas en 390 px, SIN_REPARACION de punta a punta,
garantía de 2 Detalles (una Orden, origen por nombre) y override con
factibilidad parcial y Orden tomada. Los UAT siguen `PENDING`.
