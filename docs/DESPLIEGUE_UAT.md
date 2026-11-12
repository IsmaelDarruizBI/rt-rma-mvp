# Despliegue y vuelta atrás del UAT

Procedimiento para publicar una versión nueva del backend y del frontend del UAT, y para volver a la anterior.

- **Integrar no es publicar.** El código se integra por Git y CI: push a la rama, workflows en verde (sección 5) y avance rápido de `mvp-v2`. Ningún push despliega.
- **Publicar en el UAT es una operación aparte y explícita,** por CLI y con autorización ([`AGENTS.md`](../AGENTS.md)): el backend con `gcloud run deploy` (sección 3) y el frontend con `vercel deploy --prod` (sección 4).
- **No hay despliegues automáticos (desde el 11/11/2026).** El proyecto Vercel `rt-rma-uat` está desconectado del repositorio (`vercel git disconnect`): ningún push crea despliegues, ni de producción ni vistas previas. Ningún otro proyecto del equipo está conectado a `rt-rma-mvp` y el repositorio no tiene webhooks. Para verificarlo: `vercel api "/v9/projects/rt-rma-uat?teamId=team_G7XTlKAQ4rGyOrfcvOqgZm24"` tiene que devolver `link` vacío. Reconectarlo (`vercel git connect`) vuelve a desplegar en cada push y necesita autorización.
  - `gitProviderOptions.createDeployments: disabled` **no alcanza**: solo deja de crear los *GitHub Deployments*, y Vercel igual despliega. Se probó el 11/11: el push de `4ad6bff` creó la vista previa `dpl_2gEp3LnWNbYshjpRmjZALbXvHjks`. Se dejó en su valor original (`enabled`).
- **Backend y frontend se publican coordinados** cuando el cambio toca a los dos: el contrato de la API, la autenticación o el proyecto de Supabase. Primero el backend sin tráfico, después la prueba del frontend contra su etiqueta y, recién entonces, el tráfico del backend y `vercel deploy --prod` del mismo commit. Un cambio que toca una sola pieza se publica solo.
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

Ninguno despliega ni usa secretos. Se activan al publicar la rama en GitHub. Como Vercel tampoco despliega desde Git, el push que integra en `mvp-v2` solo dispara estos workflows.

## 6. Vuelta atrás

| Pieza | Comando | Condición |
|---|---|---|
| Backend | `gcloud run services update-traffic … --to-revisions <revisión anterior>=100` | La anterior usa el mismo proyecto de Supabase y es compatible con el esquema (migraciones aditivas) |
| Frontend | `vercel promote <despliegue anterior> --scope ismaeldarruizbis-projects` | Construido contra el mismo proyecto de Supabase que el backend al que se vuelve |

**Pares vigentes (12/11/2026):**

| Uso | Backend | Frontend | Supabase |
|---|---|---|---|
| Público (iteración 1, desde el 12/11/2026) | `rt-rma-uat-api-00027-sas` (etiqueta `it1-14108ef`, código `14108ef`) | `rt-rma-j00dbv3fc…` (`dpl_CdRi5ttvBwRnxfADjtM4yRVjUkS2`) | São Paulo `pcdnmhzwhzymznojndrn` |
| Vuelta atrás de la iteración 1 | `rt-rma-uat-api-00024-top` (etiqueta `sp-d226fd2`, código `d226fd2`) | `rt-rma-pktu8ktbq…` (`dpl_6vsLwpAzxE2yS5K7RLHBMNVvETN8`) | São Paulo `pcdnmhzwhzymznojndrn` (con la migración 21, compatible) |
| Vuelta atrás de la migración, hasta el 25/11/2026 | `rt-rma-uat-api-00020-tux` (etiqueta `auth`, código `61e2a14`) | `rt-rma-n49rz9qgv…` (`dpl_F1M6Msv1FUHo3ghNYPVviYQtmztb`) | Oregón `okcscsglnujnxtgobjfw` |

**Vuelta atrás de la iteración 1** (coordinada, sin tocar la base: la migración 21 es aditiva y `d226fd2` funciona sobre ella, 383 de 384 pruebas; la que falla solo cuenta los tipos de evento):

```bash
gcloud run services update-traffic rt-rma-uat-api --region southamerica-east1 --project rosariotecno-460217 --to-revisions rt-rma-uat-api-00024-top=100
vercel promote dpl_6vsLwpAzxE2yS5K7RLHBMNVvETN8 --scope ismaeldarruizbis-projects
```

No se revierten columnas ni se borran datos. Los datos que la iteración 1 haya escrito en las columnas nuevas quedan en la base y la versión anterior los ignora.

**Despliegue de producción sin dominio:** `vercel deploy --prod --skip-domain` construye el despliegue de producción sin publicarlo; `vercel promote <id>` lo publica. Así el corte con el backend dura segundos (12/11/2026: 12 s).

Los comandos de la vuelta atrás coordinada están en [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16.

**Nunca como vuelta atrás:** `00017-wer`, `00012-d4z` y anteriores, porque no tienen autenticación; ni `00010-pgz` y anteriores, que trabajan en JSON.

**Conservar mientras dure el período de vuelta atrás** (14 días después del corte):

- `00020-tux` y su etiqueta;
- el secreto `rma-uat-database-url`;
- el despliegue `rt-rma-n49rz9qgv…`;
- el proyecto de Oregón.
