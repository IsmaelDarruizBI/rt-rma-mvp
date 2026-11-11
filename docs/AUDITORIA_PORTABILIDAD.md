# Auditoría de portabilidad (11/11/2026)

Registro de la auditoría de solo lectura previa al cambio de computadora y de cómo se resolvió. El procedimiento para retomar está en [`CONTINUIDAD.md`](CONTINUIDAD.md); este documento no lo repite.

El registro no contiene contraseñas, tokens, claves, datos personales ni rutas de equipos.

## Veredicto

**APTO después de las acciones de este cierre.** Queda pendiente el traslado manual de la sección «Lo que no está en GitHub» de [`CONTINUIDAD.md`](CONTINUIDAD.md), sección 7. Lo crítico es la clave privada `age`.

## Hallazgos y resolución

| Hallazgo | Resolución |
|---|---|
| `rt-rma-mvp`: ¿commits, stashes o cambios solo locales? | Ninguno. Las ramas locales sin upstream y los worktrees apuntan a commits que ya están en ramas remotas |
| `rt-rma-app`: commit local `3cf273e` (rama `test`, V1.2, 15/09/2026), sin publicar | Revisado sin secretos ni datos personales. Se publicó en la rama de archivo `archivo/test-v1.2-3cf273e`; `test` y las ramas funcionales no cambiaron |
| Origen de `business/`: `ab928b6`, en `dc31/cancelacion-explicita` y no en `main` de `rt-rma-app` | La rama y la etiqueta `v1.4-baseline` están publicadas. [`CONTINUIDAD.md`](CONTINUIDAD.md) indica clonarla |
| Guía de pruebas manual del UAT, fuera de todo repositorio | Revisada: sin secretos, sin datos personales y sin llamadas de red. Versionada sin cambios en [`qa/guia-pruebas-uat.html`](qa/guia-pruebas-uat.html); su único paso desactualizado está anotado en [`CONTINUIDAD.md`](CONTINUIDAD.md), sección 8 |
| `CONTINUIDAD.md` describía el estado anterior al corte a São Paulo | Reescrito con la arquitectura vigente |
| Clave privada `age` | Está solo fuera de los repositorios. No aparece en ninguno ni en su historial; la única coincidencia del prefijo es la lista de patrones del buscador de secretos de CI. Se verificó que deriva la clave pública configurada en el Job |
| Un `.env` local del backend con una contraseña | Lo ignora Git y el código no usa sus variables. No se traslada; la contraseña, si hace falta, va al gestor |
| Copias locales de claves JSON de cuentas de servicio, fuera de los repositorios | Analizadas sin abrir su clave privada: roles, IDs y origen de uso en los registros de auditoría. **RMA no usa ninguna.** Las que pertenecen al proyecto del UAT son las que están en uso, pero por procesos externos (un Apps Script y una aplicación en otro servidor), nunca desde la computadora auditada. No se trasladan ni se revocan: revocarlas cortaría esos procesos |
| Dependencias de rutas o sesiones de la computadora | No hay en los archivos versionados. `54329` es la URL local de pruebas, configurable. Los servicios en la nube no dependen de ningún equipo |
| Primera ejecución automática del respaldo | Todavía no había ocurrido; está programada para el 12/11/2026 a las 06:00 UTC ([`CONTINUIDAD.md`](CONTINUIDAD.md), sección 9) |

## Riesgos abiertos

1. **Clave privada `age`:** si se pierde antes de trasladarla, los respaldos quedan ilegibles.
2. **Claves de cuentas de servicio con permisos excesivos,** usadas por procesos ajenos a RMA en el mismo proyecto de GCP. Conviene una tarea aparte para inventariar sus dueños, pasar a cuentas con privilegio mínimo y rotar las claves, con autorización.
3. **Copias con datos personales:** vencen el 25/11/2026. Hay una en una computadora anterior que todavía hay que ubicar ([`RESPALDOS.md`](RESPALDOS.md), sección 5).
