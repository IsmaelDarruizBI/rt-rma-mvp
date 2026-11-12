# Sincronización de la copia funcional (DC02)

`rt-rma-app` es la fuente única de la definición funcional. En este repositorio, `business/` es una **copia generada** de un commit exacto de esa fuente. No se edita a mano.

| Ítem | Valor |
|---|---|
| Fuente | `rt-rma-app`, rama `spec/macro-v14` (V1.4 con DC31, las decisiones DEC-IT1-01 a 05 y el estado de implementación de la macroiteración, sobre `spec/iteracion-1-decisiones` y la etiqueta `v1.4-baseline`) |
| Commit de origen | `420feb97fd71fb85f62a722e3033db8cefd45e40` |
| Contenido funcional aprobado | `b6cc3a5` (DC01, 24/10/2026) |
| Manifiesto | `business/FUNCTIONAL_SOURCE.json`: repositorio, commit, etiqueta y SHA-256 de cada archivo |
| Sincronizado | 12/11/2026 (macroiteración: estado de implementación); antes, 11/11/2026 (iteración 1: DEC-IT1-01 a 05), 10/11/2026 (DC31, `ab928b6`) y 24/10/2026, rama `sync/functional-v1.4` |

## Qué contiene `business/`

- **V1.4**, la baseline vigente: proceso, reglas, Features, Scenarios y el registro de decisiones (`decisions/decision-log-v1.4.yaml`).
- **V1.3**, como histórico. Es el V1.3 original de la fuente, sin los cambios que el MVP le había hecho. Esos cambios están en V1.4:
  - responsables alternativos en 150 y 270;
  - 180 → 212;
  - nombres de 212 y 245;
  - textos de BR-REP-009 y BR-REP-018.
- **V1.2**, la baseline histórica aprobada; actores y schemas.

## Reglas

1. No editar `business/`. Un cambio funcional se hace en `rt-rma-app`, se revisa allí y se vuelve a generar la copia.
2. `npm run verify:functional-copy` falla si un archivo no coincide con su hash o si hay un archivo que el manifiesto no lista.
3. `.gitattributes` fija `business/** text eol=lf`. Así la copia coincide byte a byte con la fuente aunque `core.autocrlf` esté activo; el verificador normaliza igual los finales de línea.
4. Las diferencias entre la baseline y el producto se registran en `traceability/discrepancias-baseline-v1.4.md`. No se tratan como fallas de la copia.

## Volver a sincronizar

Con `rt-rma-app` clonado al lado (`../rt-rma-app`) y limpio:

```bash
# desde rt-rma-app: exporta business/ del commit indicado, nunca del working tree
npm run export:functional-copy -- --to ../rt-rma-mvp --commit <etiqueta o commit>

# desde rt-rma-mvp
npm run verify:functional-copy
node scripts/verify-functional-copy.mjs . --source-repo ../rt-rma-app --expect-commit <sha completo>
npm run validate:all
```

El exportador reemplaza `business/` y elimina los archivos que no están en el commit.

Después de exportar:

- actualizar el commit esperado en `verify:functional-copy:source` (`package.json`) y en esta página;
- revisar `traceability/discrepancias-baseline-v1.4.md`: `npm run validate:discrepancies` exige que cite el commit nuevo.

Hasta que `consolidacion/v1.4` y la etiqueta se publiquen en el remoto de `rt-rma-app`, la verificación contra la fuente solo funciona con el clon local.

## Herramientas de validación

Para no mantener implementaciones divergentes, los scripts compartidos son copias **idénticas** de `rt-rma-app` en `v1.4-baseline`:

- **Validadores:** `validate-process`, `validate-features`, `validate-references` y `validate-scenarios`.
- **Pruebas:** `test-scenarios`, `test-feature-scenario-mapping`, `test-commercial-closure`, `test-customer-decision` y `test-discover-scenario-candidates`.
- **Generadores:** `generate-mermaid`, `generate-process-viewer` y `discover-scenario-candidates`.
- **Verificador:** `verify-functional-copy.mjs`.
- **Librerías de `scripts/lib/`:** `process-model`, `process-core`, `feature-model`, `scenario-model`, `feature-scenario-mapping`, `scenario-discovery`, `origin-filter` y `detail-states`.

Si cambian en la fuente, se vuelven a copiar sin editarlas.

Propios de este repositorio:

| Script | Qué controla |
|---|---|
| `validate-traceability*.ts`, `test-traceability-global.ts`, `lib/traceability-global.ts` | Los grafos de `traceability/`; las identidades de negocio se comparan contra V1.4 |
| `test-end-events.ts` | V1.4 tiene dos fines: EVT-REP-999 (fin de una Orden, solo desde 268) y EVT-REP-998 (ingreso en garantía no admitido, solo desde 036). Los tres Happy Paths terminan en EVT-REP-999 y solo VAR-REP-038 termina en EVT-REP-998. El validador compartido acepta cualquier fin; esta prueba mantiene la garantía de los Happy Paths |
| `validate-baseline-discrepancies.ts` | Toda decisión con implementación pendiente y toda incorporación de UAT sin confirmar figura en la lista de discrepancias |

`test-consolidation.ts` y `validate-decisions.ts` no se copian. Validan el registro contra la documentación de consolidación de la fuente, que no se sincroniza. Su resultado lo garantiza el commit de origen, verificado por hash.

## Vistas generadas

- **V1.4:** `generated/mermaid` y `generated/viewer` (`repair-management-v1.4` y la vista de CLIENTE_EXTERNO). Son idénticas a las de la fuente.
- **V1.3:** se regeneraron desde el V1.3 original y se conservan como histórico.
- **V1.2:** sin cambios.
