# Guía para agentes de desarrollo

Vale para cualquier agente (Claude, Codex u otros) y para cualquier persona que retome el trabajo. Es corta a propósito: el contenido está en los documentos que enlaza.

## Antes de empezar una tarea

1. Leer [`docs/ESTADO_PROYECTO.md`](docs/ESTADO_PROYECTO.md): etapa actual, decisiones vigentes, riesgos y próximo paso.
2. Consultar las especificaciones y decisiones del tema:
   - Comportamiento funcional: `business/`. Es una copia generada; no se edita a mano.
   - Especificación y trazabilidad: [`.specify/memory/constitution.md`](.specify/memory/constitution.md). Prevalece en esa materia.
   - Persistencia PostgreSQL: [`docs/postgresql/`](docs/postgresql/README.md).
3. Verificar la rama y el estado de Git: `git status`, `git branch --show-current` y `git log --oneline -5`.
4. Identificar la etapa y el alcance autorizado. Si la tarea no tiene autorización explícita, preguntar antes de implementar.
5. No modificar funcionalidades fuera de ese alcance ni cambiar expectativas de tests existentes sin aprobación.

## Mientras se trabaja

- **Credenciales:** ninguna en el repositorio, el frontend ni los logs. El repositorio es público.
- **Acciones con efecto externo:** push, merge, deploy y cambios en Cloud Run, Vercel o Supabase remoto se hacen solo con autorización explícita para esa acción.
- **Pruebas:** `pytest` y `ruff check .` desde `app/backend/`. Si la tarea toca persistencia, también `tests/postgres` contra PostgreSQL local. Si toca `business/`, `specs/` o `traceability/`, también `npm run validate:all`.
- **Resultados:** informarlos tal como salieron. No se afirma que una prueba pasó si no se ejecutó.

## Al terminar una etapa relevante

1. Actualizar `docs/ESTADO_PROYECTO.md`: tabla de etapas, últimos avances y próximo paso.
2. Registrar las decisiones técnicas y los riesgos en el documento que corresponde (tabla de abajo).
3. Vincular los commits y documentos relevantes.
4. Indicar qué quedó terminado.
5. Indicar qué falta desarrollar.
6. Proponer el siguiente paso concreto.

## Una fuente de verdad por tema

No repetir información entre documentos: enlazar.

| Tema | Fuente |
|---|---|
| Estado del proyecto, etapas y próximo paso | `docs/ESTADO_PROYECTO.md` |
| Comportamiento funcional | `business/` (se sincroniza con `docs/sincronizacion-funcional.md`) |
| Reglas de especificación y trazabilidad | `.specify/memory/constitution.md` |
| Diferencias entre la baseline V1.4 y el producto | `traceability/discrepancias-baseline-v1.4.md` |
| Backlog de producto y notas técnicas del UAT | `docs/pendientes-producto.md` |
| Diseño de la base | `docs/postgresql/diseno-logico.md` y `diseno-fisico.md` |
| Pendientes y riesgos de la integración con PostgreSQL | `docs/postgresql/integracion-pendientes.md` |
| Instalación, configuración y pruebas del backend | `app/backend/README.md` |
