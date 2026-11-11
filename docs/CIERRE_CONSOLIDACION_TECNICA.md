# Cierre de la consolidación técnica (11/11/2026)

Resumen para empezar la etapa de desarrollo funcional y UX. El detalle de cada tema está en el documento enlazado.

## 1. Arquitectura actual

| Capa | Tecnología | Dónde |
|---|---|---|
| Frontend | React y Vite; sesión con `@supabase/auth-js` | Vercel `rt-rma-uat` |
| Backend | Python 3.11, FastAPI y Pydantic v2 (`api → application → services → repositories ← storage`) | Cloud Run `rt-rma-uat-api`, `southamerica-east1`, una instancia |
| Base | PostgreSQL 17 en Supabase, esquema `rma` (45 tablas, 20 migraciones), rol `rma_api` → `rma_backend`, pooler en modo transacción y `verify-full` | Oregón (público) y São Paulo (preparado) |
| Autenticación | Supabase Auth (usuario y contraseña, sin registro); JWT ES256 verificado en el backend; rol y estado desde PostgreSQL | Mismo proyecto que la base |
| Archivos | Fotos en GCS `rt-rma-uat-fotos`; documentos generados desde la base | `southamerica-east1` |
| Secretos | Secret Manager, uno por base, con la versión fijada en cada revisión | `rosariotecno-460217` |

Fuente funcional: `business/` ([`sincronizacion-funcional.md`](sincronizacion-funcional.md)). Decisiones vigentes: [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), sección D.

## 2. Estado real de la infraestructura (verificado el 11/11/2026)

- **Tráfico público:** `rt-rma-uat-api-00020-tux` (100 %), contra Supabase **Oregón** `okcscsglnujnxtgobjfw`. Producción de Vercel: `rt-rma-n49rz9qgv…`, construido contra el mismo proyecto.
- **El corte a São Paulo no se ejecutó.** `rt-rma-uat-api-00023-zus` (etiqueta `corte`, 0 %) está lista contra `pcdnmhzwhzymznojndrn`.
- **Datos:**
  - Oregón: cero Órdenes, BAT-IP14 10/0, integridad 0, 4 usuarios vinculados, 20 migraciones.
  - São Paulo: lo mismo, más **una Orden abierta** (`OR-000001`) creada después del reinicio desde la vista previa por `RECEP-001`. Es la prueba manual, que también confirma que el acceso funciona allí.
- **Seguridad:**
  - endpoints operativos con 401 sin token;
  - registro deshabilitado y ES256 en los dos proyectos;
  - CORS solo para producción;
  - secretos con acceso solo de la cuenta de la API.
- **Para la vuelta atrás se conservan:** `00020-tux` (etiqueta `auth`), `rma-uat-database-url`, `rt-rma-n49rz9qgv…` y el proyecto de Oregón.
- **Nunca como vuelta atrás:** `00017-wer` y anteriores, que no tienen autenticación.

## 3. Qué quedó consolidado (commits locales, sin push)

| Commit | Contenido |
|---|---|
| `53c7cef` | `.gitignore`: capturas locales de Playwright |
| `6903691` | `supabase/scripts/reinicio_uat/`: reinicio transaccional con guardas, ensayo por defecto y eliminación del respaldo con confirmación explícita |
| `0724fca` | `supabase/scripts/migracion_sp/`: comparar, maestros, cuentas (mismo id y hash), verificar, pruebas de Auth, entornos, recorridos y medición; test del formato real de la CLI |
| `1c06be5` | Documentación de la migración y estado del UAT |
| `4af9854` | **Seguridad:** `/docs`, `/redoc` y `/openapi.json` ya no se publican con autenticación real; test incluido |
| `bea870a` | `supabase/scripts/respaldo/`: respaldo cifrado (age) y restauración probada de punta a punta |
| (este cierre) | CI, checklist de seguridad, despliegue, deuda técnica y estado |

## 4. Qué quedó automatizado

- **CI** (`.github/workflows/`), validada con `actionlint`. Corre al publicar la rama y no despliega ni usa secretos:
  - `seguridad`: búsqueda de credenciales y `git diff --check`;
  - `backend`: `ruff` y 2106 pruebas, más la construcción de la imagen;
  - `postgres`: migraciones desde cero y 384 pruebas;
  - `frontend`: tipos, pruebas y construcción;
  - `funcional`: `validate:all`.

  Detalle en [`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md), sección 5.
- **Herramientas reutilizables, con modo seguro por defecto:**
  - reinicio de datos, migración entre proyectos y verificación de equivalencia;
  - respaldo y restauración, y búsqueda de secretos.

## 5. Qué requiere activación o autorización

| Acción | Documento |
|---|---|
| Publicar la rama (6 commits locales más este cierre) e integrarla en `mvp-v2` (avance rápido, 30 commits) | — |
| Decidir qué hacer con `OR-000001` en São Paulo y ejecutar el corte | [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16 |
| Activar el respaldo: API de Cloud Scheduler, bucket con retención, cuenta de servicio, secreto, Job y programación | [`RESPALDOS.md`](RESPALDOS.md), sección 4 |
| Versionado del bucket de fotos | [`RESPALDOS.md`](RESPALDOS.md), sección 2 |
| Desplegar `4af9854` (cierre de `/docs`) | [`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md) |
| Confirmar el largo mínimo 10 en los dos proyectos de Auth | [`CHECKLIST_SEGURIDAD_DESPLIEGUE.md`](CHECKLIST_SEGURIDAD_DESPLIEGUE.md) |

## 6. Deuda técnica

[`DEUDA_TECNICA.md`](DEUDA_TECNICA.md):

- **P0:** respaldo automático, integración de la rama y corte a São Paulo.
- **P1:** configuración por API, catálogo de Ventas persistido y varias instancias, paginación, salida de mensajes para WhatsApp, modelo de garantía de venta, equipos internos, reporting de solo lectura, privilegios de `PUBLIC`, rol de respaldo, despliegue del cierre de `/docs` y largo mínimo de contraseña.
- **P2:** formato, fotos huérfanas, JSON, revisiones sin tráfico, respuesta perdida, viajes de más y plan Pro.

## 7. Criterios para empezar el desarrollo funcional

1. **Rama integrada** en `mvp-v2` y CI en verde en GitHub. Cada módulo nuevo sale de una rama propia, con PR y los workflows de su área.
2. **Una sola base de UAT:** corte a São Paulo hecho o descartado. No desarrollar contra dos proyectos.
3. **Respaldo diario activo y una restauración ensayada** antes de cargar datos reales.
4. **Cambios funcionales primero en `business/`**, en `rt-rma-app`, sincronizados y con `validate:all` en verde. Después, código y pruebas.
5. **Esquema:** solo migraciones aditivas, probadas por el workflow `postgres` y aplicadas con `--dry-run` primero.
6. **Cada despliegue con el [checklist de seguridad](CHECKLIST_SEGURIDAD_DESPLIEGUE.md)** y con un par de vuelta atrás identificado.
7. **Los P1 que toca cada módulo,** resueltos dentro de ese módulo. Por ejemplo, ABM de configuración antes de garantías o compras, y salida de mensajes antes de WhatsApp.
