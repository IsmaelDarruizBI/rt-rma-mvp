# Despliegue y vuelta atrás del UAT

Procedimiento para publicar una versión nueva del backend y del frontend del UAT, y para volver a la anterior.

- **Despliegues manuales:** se hacen por CLI con autorización explícita ([`AGENTS.md`](../AGENTS.md)). No hay despliegues automáticos.
- **Corte a São Paulo:** el procedimiento propio está en [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16.

## 1. Piezas

| Pieza | Dónde | Identificación |
|---|---|---|
| Backend | Cloud Run `rt-rma-uat-api`, proyecto `rosariotecno-460217`, región `southamerica-east1` | Revisión con etiqueta `commit=<sha>` |
| Imagen | Artifact Registry `cloud-run-source-deploy/rt-rma-uat-api` | Digest `sha256:…` |
| Base y Auth | Supabase. La revisión toma la base del secreto `RMA_DATABASE_URL`, con la versión fijada, y Auth de `RMA_AUTH_SUPABASE_URL` | Ref del proyecto |
| Frontend | Vercel `rt-rma-uat` (equipo `ismaeldarruizbis-projects`, Root Directory `app/frontend`) | Despliegue `rt-rma-<id>…`; las variables `VITE_*` se fijan al construir |

**Regla:** backend y frontend apuntan al **mismo** proyecto de Supabase, porque los tokens son de cada proyecto.

## 2. Antes de desplegar

1. **CI en verde** en la rama: `seguridad` siempre; `backend`, `frontend`, `postgres` y `funcional` según lo que cambió (sección 5).
2. **Migraciones nuevas:** se aplican antes, con autorización y `supabase db push --dry-run` primero. Deben ser aditivas, para que la revisión anterior siga funcionando durante la vuelta atrás.
3. **Revisión del [checklist de seguridad](CHECKLIST_SEGURIDAD_DESPLIEGUE.md).**

## 3. Backend

Desde una exportación limpia del commit (sin archivos locales):

```bash
git archive <sha> app/backend | tar -x -C <carpeta temporal>
gcloud run deploy rt-rma-uat-api --project rosariotecno-460217 --region southamerica-east1 \
  --source <carpeta temporal>/app/backend --no-traffic --tag prueba \
  --update-labels commit=<sha>
```

1. **La revisión hereda las variables de la plantilla**, que es la de la última revisión creada. Verificar `RMA_AUTH_SUPABASE_URL`, `RMA_DATABASE_URL` (secreto y versión fijada) y `RMA_CORS_ALLOW_ORIGINS` con `gcloud run revisions describe`.
2. **Comprobar contra la URL de la etiqueta:**
   - `/health` 200;
   - 401 sin token y con token inválido;
   - `/docs` 404 en UAT;
   - lecturas autenticadas (`supabase/scripts/migracion_sp/medir_api.py --backend <url de la etiqueta>`).
3. **Pasar el tráfico:** `gcloud run services update-traffic rt-rma-uat-api --region southamerica-east1 --project rosariotecno-460217 --to-revisions <revisión nueva>=100`.

## 4. Frontend

Desde una exportación limpia del repositorio completo, porque el Root Directory es `app/frontend`. Borrar cualquier `.env.local` que cree `vercel link`.

```bash
git archive <sha> | tar -x -C <carpeta temporal>
cd <carpeta temporal> && vercel deploy --prod --yes --scope ismaeldarruizbis-projects
```

**Para probar antes,** usar `vercel deploy` sin `--prod`, con `--build-env` apuntando a la URL de la etiqueta del backend. Ese origen tiene que estar en `RMA_CORS_ALLOW_ORIGINS` de esa revisión, y solo de esa.

**Después de publicar,** el bundle tiene que contener:

- el ref de Supabase esperado y la URL pública del backend;
- solo claves `sb_publishable_`, nunca `sb_secret_` con valor.

## 5. Integración continua (`.github/workflows/`)

| Workflow | Cuándo | Qué |
|---|---|---|
| `seguridad` | Todo push y PR | `scripts/ci/buscar_secretos.sh`; `git diff --check` en PR |
| `backend` | Cambios en `app/backend/` o en los scripts Python de `supabase/` | `ruff check`, `pytest` (2106 pruebas en modo JSON), construcción de la imagen sin publicarla |
| `postgres` | Cambios en migraciones, seeds o persistencia | Las migraciones desde cero en PostgreSQL 17 y `tests/postgres` (384 pruebas) |
| `frontend` | Cambios en `app/frontend/` | `typecheck`, pruebas y construcción |
| `funcional` | Cambios en `business/`, `specs/`, `traceability/` o sus scripts | `npm run validate:all` |

Ninguno despliega ni usa secretos. Se activan al publicar la rama en GitHub.

## 6. Vuelta atrás

| Pieza | Comando | Condición |
|---|---|---|
| Backend | `gcloud run services update-traffic … --to-revisions <revisión anterior>=100` | La anterior usa el mismo proyecto de Supabase y es compatible con el esquema (migraciones aditivas) |
| Frontend | `vercel promote <despliegue anterior> --scope ismaeldarruizbis-projects` | Construido contra el mismo proyecto de Supabase que el backend al que se vuelve |

**Pares vigentes (11/11/2026):**

| Uso | Backend | Frontend | Supabase |
|---|---|---|---|
| Público hoy | `rt-rma-uat-api-00020-tux` (etiqueta `auth`) | `rt-rma-n49rz9qgv…` | Oregón `okcscsglnujnxtgobjfw` |
| Corte preparado | `rt-rma-uat-api-00023-zus` (etiqueta `corte`) | Despliegue nuevo con las variables de São Paulo | São Paulo `pcdnmhzwhzymznojndrn` |

**Nunca como vuelta atrás:** `00017-wer`, `00012-d4z` y anteriores, porque no tienen autenticación; ni `00010-pgz` y anteriores, que trabajan en JSON.

**Conservar mientras dure el período de vuelta atrás** (14 días después del corte):

- `00020-tux` y su etiqueta;
- el secreto `rma-uat-database-url`;
- el despliegue `rt-rma-n49rz9qgv…`;
- el proyecto de Oregón.
