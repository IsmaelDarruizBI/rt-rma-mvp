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
| Público (macroiteración V1.4, desde el 12/11/2026 a las 15:14 UTC) | `rt-rma-uat-api-00029-kay` (etiqueta `v14-5c6137e`, código `5c6137e`) | `rt-rma-62sdml5sb…` (`dpl_CRXZubTCVE1ALhZmLe2wHhoZhbWR`) | São Paulo `pcdnmhzwhzymznojndrn` (23 migraciones) |
| Vuelta atrás de la macroiteración | `rt-rma-uat-api-00027-sas` (etiqueta `it1-14108ef`, código `14108ef`) | `rt-rma-j00dbv3fc…` (`dpl_CdRi5ttvBwRnxfADjtM4yRVjUkS2`) | São Paulo `pcdnmhzwhzymznojndrn` (con las migraciones 22 y 23, compatible) |
| Vuelta atrás de la iteración 1 | `rt-rma-uat-api-00024-top` (etiqueta `sp-d226fd2`, código `d226fd2`) | `rt-rma-pktu8ktbq…` (`dpl_6vsLwpAzxE2yS5K7RLHBMNVvETN8`) | São Paulo `pcdnmhzwhzymznojndrn` (con la migración 21, compatible; sobre la 22 y la 23 no se probó) |
| Vuelta atrás de la migración, hasta el 25/11/2026 | `rt-rma-uat-api-00020-tux` (etiqueta `auth`, código `61e2a14`) | `rt-rma-n49rz9qgv…` (`dpl_F1M6Msv1FUHo3ghNYPVviYQtmztb`) | Oregón `okcscsglnujnxtgobjfw` |

**Vuelta atrás de la macroiteración** (coordinada, sin tocar la base: las migraciones 22 y 23 son aditivas y las pruebas `tests/postgres` de `14108ef` pasan sobre ellas, salvo las 2 que cuentan las tablas del esquema):

```bash
gcloud run services update-traffic rt-rma-uat-api --region southamerica-east1 --project rosariotecno-460217 --to-revisions rt-rma-uat-api-00027-sas=100
vercel promote dpl_CdRi5ttvBwRnxfADjtM4yRVjUkS2 --scope ismaeldarruizbis-projects
```

No se revierten columnas ni se borran tablas o datos. Lo que la macroiteración haya escrito queda en la base y la versión anterior lo ignora, con dos efectos que hay que conocer antes de volver:

- un Detalle cancelado por descarte técnico conserva `DESCARTE_TECNICO`, valor que el enum `OrigenCancelacion` de `14108ef` no tiene: con la versión anterior esa Orden no se puede leer. Antes de volver, buscar `select count(*) from rma.detalle where cancelacion_origen = 'DESCARTE_TECNICO'`; si hay filas, la vuelta atrás deja esas Órdenes inaccesibles hasta volver a la macroiteración;
- un Detalle que esperaba la evaluación técnica puede ejecutarse sin ella con la versión anterior.

Con 0 Órdenes en UAT (12/11/2026, 15:16 UTC), hoy ninguno de los dos aplica.

**Vuelta atrás de la iteración 1** (`00024-top` y `dpl_6vsL…`): mismos comandos con esos identificadores.

**Despliegue de producción sin dominio:** `vercel deploy --prod --skip-domain` construye el despliegue de producción sin publicarlo; `vercel promote <id>` lo publica. Así el corte con el backend dura segundos (12/11/2026: 12 s).

Los comandos de la vuelta atrás coordinada están en [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16.

**Nunca como vuelta atrás:** `00017-wer`, `00012-d4z` y anteriores, porque no tienen autenticación; ni `00010-pgz` y anteriores, que trabajan en JSON.

**Conservar mientras dure el período de vuelta atrás** (14 días después del corte):

- `00020-tux` y su etiqueta;
- el secreto `rma-uat-database-url`;
- el despliegue `rt-rma-n49rz9qgv…`;
- el proyecto de Oregón.

## 7. Macroiteración integral: procedimiento preparado (15/11/2026, sin ejecutar)

Publica `mvp-v2` con la macroiteración integral sobre el par vigente (`00029-kay` y `dpl_CRXZ…`). **Cada paso con efecto externo necesita autorización explícita.** Ensayado completo en PostgreSQL local con [`ensayar_migracion_integral.py`](../supabase/scripts/validacion_uat/ensayar_migracion_integral.py): 56 de 56 ([`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), sección B).

**DC12 queda inactiva** (ABI-42). `RMA_TIPO_EQUIPO_CAMPO` **no se configura**: sin ella no hay Tipos de Equipo, el checklist no se ofrece ni se pide y la actualización desde Ventas responde 409 sin escribir. No impide publicar lo demás. Activarla después es configurar la variable y actualizar los tipos desde Configuración, sin rehacer el módulo.

**Configuración:** ninguna variable nueva obligatoria. La plantilla de `00029-kay` (14 variables) sirve tal cual; `RMA_CATALOGO_*` sigue como está. Frontend: las mismas 5 `VITE_*`.

### 7.1 Preflight (solo lectura)

1. `mvp-v2` en el commit a publicar, con los cinco workflows en verde y `business/` verificado (`npm run verify:functional-copy:source`).
2. Tráfico 100 % en `00029-kay`; Vercel en `dpl_CRXZ…` y desconectado (`link` vacío); São Paulo con 23 migraciones; 0 Órdenes y BAT-IP14 10/0 (`reinicio_uat/03_verificar.sql`, solo lectura).
3. `probar_entornos.py --api-sao-paulo --sin-oregon` (sesiones de las cuatro cuentas).
4. [Checklist de seguridad](CHECKLIST_SEGURIDAD_DESPLIEGUE.md).

### 7.2 Respaldo previo

`gcloud run jobs execute rt-rma-respaldo-db … --wait` (desde PowerShell) y anotar la copia `uat/<marca>`, con 23 migraciones en su manifiesto.

### 7.3 Migraciones (12, en orden)

```bash
npx -y supabase@3.1.0 db push --dry-run --remote=pcdnmhzwhzymznojndrn   # tiene que listar SOLO 20261113000100 … 20261115000100
npx -y supabase@3.1.0 db push --remote=pcdnmhzwhzymznojndrn             # la CLI pide la contraseña sin eco
```

| # | Migración | Qué hace | Depende de |
|---|---|---|---|
| 1 | `20261113000100_roles_permisos` | `permiso`; amplía el CHECK de entidades auditadas | — |
| 2 | `20261113000200_ajuste_por_detalle` | `descuento.detalle_id`; `v_orden_saldo` con ajustes por Detalle (mismas columnas) | — |
| 3 | `20261113000300_politica_garantia` | Plazos y política por Tipo y Detalle; `checkin.motivo` | — |
| 4 | `20261113000400_reclamos_garantia` | `reclamo_garantia`; equivalencias | — |
| 5 | `20261113000500_motivos_parametros_retiro` | Motivos, `PLAZO_RETIRO_DIAS = 30`, seguimientos del retiro | — |
| 6 | `20261113000600_comunicaciones` | Plantillas, intentos, confirmaciones y consentimientos | — |
| 7 | `20261113000700_firmas_documentos` | `firma_documento` | — |
| 8 | `20261113000800_identidad_equipo` | Correcciones de la vinculación del Equipo | — |
| 9 | `20261113000900_lotes_inventario` | `insumo.control` (SIN_LOTE para todos) y `precio`; `lote_insumo`; `lote_id` en el libro; DESPERDICIO y DEVOLUCION; trigger del libro con lotes; `verificar_integridad()` | — |
| 10 | `20261113001000_compras` | Proveedores, solicitudes, órdenes de compra y recepciones | 9 (ingresos con lote) |
| 11 | `20261113001100_checklist_recepcion` | Tipos de Equipo, preguntas, checklists y confirmaciones de faltantes | 1 (entidad CHECKLIST) |
| 12 | `20261115000100_tipo_equipo_catalogo_ventas` | `tipo_equipo` como copia del catálogo de Ventas | 11 |

Todas aditivas: tablas nuevas, columnas que admiten vacío o tienen valor por defecto, restricciones ampliadas, vistas y funciones con las mismas columnas. No mueven datos: el stock existente queda **sin lote identificado**, las reservas abiertas siguen abiertas y el libro no cambia. `rma_backend` recibe permisos solo sobre lo nuevo (sin DELETE ni TRUNCATE); `anon`, `authenticated` y `service_role` siguen sin acceso; no cambian roles.

**Después (solo lectura):** 35 migraciones, 69 tablas y 8 vistas; `verificar_integridad()` vacío (con la sesión administrativa); BAT-IP14 10/0 SIN_LOTE; 0 lotes y 0 Tipos de Equipo. Ensayo de restauración en la nube con las 12 migraciones subidas a `_herramientas/migraciones/` ([`RESPALDOS.md`](RESPALDOS.md), sección 6).

### 7.4 Backend sin tráfico

```bash
git archive <sha> app/backend | tar -x -C <carpeta temporal>
gcloud run deploy rt-rma-uat-api --project rosariotecno-460217 --region southamerica-east1 \
  --source <carpeta temporal>/app/backend --no-traffic --tag mi-<sha corto> \
  --update-labels commit=<sha>
```

Por la URL de la etiqueta: la plantilla heredada sin `RMA_TIPO_EQUIPO_CAMPO`; `/health` 200; 401 sin token y con token inválido (también en `/api/purchases/*`, `/api/admin/*` y `/api/inventory/*/lots`); `/docs` 404; `probar_entornos.py` y `medir_api.py --backend <etiqueta>` (con sesión, solo lectura); registros sin 5xx ni credenciales.

### 7.5 Frontend sin publicar

```bash
git archive <sha> | tar -x -C <carpeta temporal>
cd <carpeta temporal> && vercel deploy --prod --skip-domain --yes --scope ismaeldarruizbis-projects
```

El bundle: ref de São Paulo, URL pública de la API, solo `sb_publishable_`. Para probarlo antes contra la etiqueta: una vista previa con `--build-env VITE_API_BASE_URL=<etiqueta>`, con ese origen en el CORS de esa revisión.

### 7.6 Publicación coordinada

```bash
gcloud run services update-traffic rt-rma-uat-api --region southamerica-east1 --project rosariotecno-460217 --to-revisions <revisión nueva>=100
vercel promote <despliegue nuevo> --scope ismaeldarruizbis-projects
```

Uno detrás del otro: el frontend nuevo necesita el backend nuevo, y el anterior funciona con los dos (ninguna ruta ni campo de la API anterior desaparece: 89 rutas → 146).

### 7.7 Pruebas posteriores

| Prueba | Sesión | Escribe |
|---|---|---|
| `probar_entornos.py --api-sao-paulo --sin-oregon` | Sí (contraseñas sin eco) | No |
| `medir_api.py` | Sí | No |
| `/health`, 401 sin token, `/docs` 404, bundle | No | No |
| `probar_macro_v14.py --escribir` (regresión; exige 0 Órdenes: va primero) | Sí, las cuatro cuentas | Sí, datos ficticios |
| `probar_macro_integral.py --escribir` | Sí, las cuatro cuentas | Sí, datos ficticios y el proveedor ficticio, que queda inactivo |
| Pasada manual en un navegador real (P2-17): Compras, Inventario por lote, Configuración (Checklist con el aviso de ABI-42, Usuarios y roles, Permisos, Proveedores) | Sí | Opcional |

Después: identificar lo creado y limpiar con [`reinicio_uat/`](../supabase/scripts/reinicio_uat/) (ensayo → respaldo → aplicar → `03_verificar.sql`), ya preparado para las tablas nuevas. Al final, respaldo y ensayo de restauración en la nube.

### 7.8 Vuelta atrás

```bash
gcloud run services update-traffic rt-rma-uat-api --region southamerica-east1 --project rosariotecno-460217 --to-revisions rt-rma-uat-api-00029-kay=100
vercel promote dpl_CRXZubTCVE1ALhZmLe2wHhoZhbWR --scope ismaeldarruizbis-projects
```

Sin tocar el esquema: `00029-kay` funciona sobre las 35 migraciones (ensayado: lee y escribe). **Pero no tolera tres datos que solo crea la versión nueva.** Antes de volver, con la sesión administrativa:

```sql
select (select count(*) from rma.movimiento_inventario where tipo = 'DESPERDICIO') as desperdicios,
       (select count(*) from (select usuario_id from rma.usuario_rol group by usuario_id having count(*) > 1) x) as usuarios_con_varios_roles,
       (select count(*) from rma.insumo where control <> 'SIN_LOTE') as insumos_por_lote;
```

| Dato | Efecto en `00029-kay` | Antes de volver |
|---|---|---|
| Un movimiento DESPERDICIO | No lista Órdenes ni inventario ni da altas (500): no conoce el tipo | En el UAT (datos ficticios): el reinicio, que vacía el libro |
| Un usuario con varios roles | No emite documentos ni lista usuarios (500: «el MVP admite exactamente uno») | Dejarle un solo rol desde Usuarios y roles (con la versión nueva) |
| Un insumo por lote o serie | Sus ingresos fallan (500: la base exige el lote) | Volverlo a SIN_LOTE (exige sus lotes en cero) o no ingresarlo |

Todo lo demás (compras, lotes de otros insumos, devoluciones, descuentos por Detalle, comunicaciones, firmas, reclamos, identidad, permisos configurados) queda en la base y la versión anterior lo ignora. Con 0 Órdenes y sin datos reales, la vuelta atrás del UAT es: reinicio (si hubo E2E), un rol por usuario y los dos comandos. Se ensayó así (fase 5c: lee, escribe e integridad sin problemas).

**Pares de vuelta atrás después de publicar:** `00029-kay` + `dpl_CRXZ…` (macroiteración V1.4). `00027-sas` y anteriores no se probaron sobre las 35 migraciones.
