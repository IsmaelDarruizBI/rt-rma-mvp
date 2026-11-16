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
  --source <carpeta temporal>/app/backend --no-traffic --tag <etiqueta temporal> \
  --update-labels commit=<sha>
```

1. **La revisión hereda las variables de la plantilla**, que es la de la última revisión creada, y también su escalado: mínimo 0 desde el 16/11/2026 (sección 9). Verificar `RMA_AUTH_SUPABASE_URL`, `RMA_DATABASE_URL` (secreto y versión fijada) y `RMA_CORS_ALLOW_ORIGINS` con `gcloud run revisions describe`. No pasar `--min-instances` mayor que 0.
2. **Comprobar contra la URL de la etiqueta:**
   - `/health` 200;
   - 401 sin token y con token inválido;
   - `/docs` 404 en UAT;
   - lecturas autenticadas (`supabase/scripts/migracion_sp/medir_api.py --backend <url de la etiqueta>`).
3. **Pasar el tráfico:** `gcloud run services update-traffic rt-rma-uat-api --region southamerica-east1 --project rosariotecno-460217 --to-revisions <revisión nueva>=100`.
4. **Quitar la etiqueta temporal** al terminar las pruebas posteriores: `gcloud run services update-traffic rt-rma-uat-api --region southamerica-east1 --project rosariotecno-460217 --remove-tags <etiqueta temporal>`. No crea revisión. Las revisiones anteriores quedan para la vuelta atrás por su nombre, sin etiqueta.
5. **Control de escalado:** [`verificar_escalado_uat.py`](../supabase/scripts/validacion_uat/verificar_escalado_uat.py) `--esperada <revisión nueva>` tiene que dar `RESULTADO: OK` (sección 9).

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

**Pares vigentes (16/11/2026, 22:54 UTC).** Desde esa hora ninguna revisión tiene etiqueta: se vuelve por el nombre de la revisión (sección 9).

| Uso | Backend | Frontend | Supabase |
|---|---|---|---|
| Público (iteración de UX de Recepción) | `rt-rma-uat-api-00036-jis` (código `677dbb1`; la misma imagen que `00033-fah`, con mínimo 0) | `dpl_Agpv37uP5wG8uXM3rsUaHQLLbpxB` | São Paulo `pcdnmhzwhzymznojndrn` (37 migraciones) |
| Vuelta atrás del escalado a cero (misma versión, mínimo 1) | `rt-rma-uat-api-00033-fah` (código `677dbb1`) | el mismo | el mismo |
| Vuelta atrás de la iteración de UX (sección 8) | `rt-rma-uat-api-00031-ror` (código `9176921`) | `rt-rma-bwwdm7cvz…` (`dpl_7Zo4UDKAcsUBnHfPf63L2QtU3d3e`) | São Paulo `pcdnmhzwhzymznojndrn` (con las 37 migraciones, compatible: ensayado) |
| Vuelta atrás de la macroiteración integral (con los controles de P1-15, sección 7.8) | `rt-rma-uat-api-00029-kay` (código `5c6137e`) | `rt-rma-62sdml5sb…` (`dpl_CRXZubTCVE1ALhZmLe2wHhoZhbWR`) | São Paulo `pcdnmhzwhzymznojndrn` (con las 35 migraciones, compatible: ensayado; sobre las 37 no se probó) |
| Vuelta atrás de la macroiteración V1.4 (no probada sobre las 35 migraciones) | `rt-rma-uat-api-00027-sas` (código `14108ef`) | `rt-rma-j00dbv3fc…` (`dpl_CdRi5ttvBwRnxfADjtM4yRVjUkS2`) | São Paulo `pcdnmhzwhzymznojndrn` (con las migraciones 22 y 23, compatible) |
| Vuelta atrás de la iteración 1 | `rt-rma-uat-api-00024-top` (código `d226fd2`) | `rt-rma-pktu8ktbq…` (`dpl_6vsLwpAzxE2yS5K7RLHBMNVvETN8`) | São Paulo `pcdnmhzwhzymznojndrn` (con la migración 21, compatible; sobre la 22 y la 23 no se probó) |
| Vuelta atrás de la migración, hasta el 25/11/2026 | `rt-rma-uat-api-00020-tux` (código `61e2a14`) | `rt-rma-n49rz9qgv…` (`dpl_F1M6Msv1FUHo3ghNYPVviYQtmztb`) | Oregón `okcscsglnujnxtgobjfw` |

Hasta el 16/11/2026 esas revisiones tenían las etiquetas `ux-677dbb1`, `mi-9176921`, `v14-5c6137e`, `it1-14108ef`, `sp-d226fd2` y `auth`; los registros anteriores las nombran así.

**Vuelta atrás vigente** (iteración de UX → macroiteración integral, `00031-ror` + `dpl_7Zo4…`): sección 8.

**Histórico, vuelta atrás de la macroiteración V1.4 a la iteración 1** (coordinada, sin tocar la base: las migraciones 22 y 23 son aditivas y las pruebas `tests/postgres` de `14108ef` pasan sobre ellas, salvo las 2 que cuentan las tablas del esquema):

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

- `00020-tux` (sin etiqueta desde el 16/11/2026: se vuelve por su nombre);
- el secreto `rma-uat-database-url`;
- el despliegue `rt-rma-n49rz9qgv…`;
- el proyecto de Oregón.

## 7. Macroiteración integral: procedimiento (preparado el 15/11/2026, ejecutado el 16/11/2026)

**Resultado del 16/11/2026: publicado y validado.** Backend `00031-ror` (`9176921`), frontend `dpl_7Zo4UDKAcsUBnHfPf63L2QtU3d3e`, São Paulo con 35 migraciones. Respaldos: antes `uat/20261116T003920Z`, después `uat/20261116T014847Z`; fotos de `OR-000001` en `resguardo/OR-000001/20261116T004025Z/`. E2E V1.4 67 de 67 e integral 68 de 68, cada uno con su limpieza selectiva; `OR-000001` intacta. Detalle en [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), sección B. Lo que sigue vale como procedimiento para el próximo despliegue con migraciones.

Publica `mvp-v2` con la macroiteración integral sobre el par vigente (`00029-kay` y `dpl_CRXZ…`). **Cada paso con efecto externo necesita autorización explícita.** Ensayado completo en PostgreSQL local con [`ensayar_migracion_integral.py`](../supabase/scripts/validacion_uat/ensayar_migracion_integral.py): 56 de 56 ([`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), sección B).

**DC12 queda inactiva** (ABI-42). `RMA_TIPO_EQUIPO_CAMPO` **no se configura**: sin ella no hay Tipos de Equipo, el checklist no se ofrece ni se pide y la actualización desde Ventas responde 409 sin escribir. No impide publicar lo demás. Activarla después es configurar la variable y actualizar los tipos desde Configuración, sin rehacer el módulo.

**Configuración:** ninguna variable nueva obligatoria. La plantilla de `00029-kay` (14 variables) sirve tal cual; `RMA_CATALOGO_*` sigue como está. Frontend: las mismas 5 `VITE_*`.

### 7.1 Preflight (solo lectura)

1. `mvp-v2` en el commit a publicar, con los cinco workflows en verde y `business/` verificado (`npm run verify:functional-copy:source`).
2. Tráfico 100 % en `00029-kay`; Vercel en `dpl_CRXZ…` y desconectado (`link` vacío). En São Paulo, con [`reinicio_uat/03_verificar.sql`](../supabase/scripts/reinicio_uat/03_verificar.sql), solo lectura:
   - 23 migraciones; antes de migrar, las tablas nuevas salen como `ausente`;
   - las Órdenes existentes **identificadas**: desde el 13/11/2026 está `OR-000001` (5 fotos), que se conserva;
   - BAT-IP14 10/0 conciliado.
3. `probar_entornos.py --sin-oregon --ordenes-previas OR-000001` (sesiones de las cuatro cuentas).
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
| `probar_entornos.py --sin-oregon --ordenes-previas <previas>` | Sí (contraseñas sin eco) | No |
| `medir_api.py` | Sí | No |
| `/health`, 401 sin token, `/docs` 404, bundle | No | No |
| `probar_macro_v14.py --escribir --ordenes-previas <previas>` (regresión) | Sí, las cuatro cuentas | Sí, datos ficticios |
| `probar_macro_integral.py --escribir --ordenes-previas <previas>` | Sí, las cuatro cuentas | Sí, datos ficticios y el proveedor ficticio, que queda inactivo |
| Pasada manual en un navegador real (P2-17): Compras, Inventario por lote, Configuración (Checklist con el aviso de ABI-42, Usuarios y roles, Permisos, Proveedores) | Sí | Opcional |

**Cada E2E se limpia por separado, sin tocar lo previo.**

- **Datos previos:** `OR-000001`, sus fotos y documentos, y cualquier Orden existente. `--ordenes-previas` tiene que listarlas exactamente; si no, el E2E no escribe nada.
- **Por cada script, en orden:**
  1. [`05_linea_base_e2e.sql`](../supabase/scripts/reinicio_uat/05_linea_base_e2e.sql): copia privada del estado de `rma`.
  2. El E2E.
  3. [`06_limpiar_e2e.sql`](../supabase/scripts/reinicio_uat/06_limpiar_e2e.sql) en `ensayo`: no deja ningún efecto.
  4. `06_limpiar_e2e.sql` en `aplicar`, sobre una copia con `v_modo` cambiado.
  5. `03_verificar.sql`.

  Primero `probar_macro_v14.py` y después `probar_macro_integral.py`, cada uno con su línea de base.
- **Qué borra la limpieza:** solo las filas que no estaban en la línea de base. Aborta sin cambios si:
  - una Orden o un cliente nuevo no es del E2E («Cliente Ficticio E2E»);
  - cambió o falta una fila previa;
  - cambió un catálogo, salvo el stock y el «Proveedor Ficticio E2E», que queda inactivo.
- **Qué queda igual:** todas las tablas, verificado contra la línea de base. Al aplicar, las secuencias vuelven a su valor (la numeración sigue en `OR-000002`) y la línea de base se elimina.
- **Fotos del bucket:** la limpieza no las toca. Su resumen lista las claves de las fotos nuevas, para borrarlas por nombre; el E2E no sube ninguna. Nunca se borra por prefijo.
- **Ensayado en local** con [`ensayar_limpieza_e2e.py`](../supabase/scripts/validacion_uat/ensayar_limpieza_e2e.py): 38 de 38. Cubre los dos E2E con una Orden previa y su foto, y las guardas.
- `01_reiniciar.sql` **ya no se usa después del E2E**, porque vacía todas las Órdenes; queda solo para un reinicio total autorizado.

Al final, respaldo y ensayo de restauración en la nube.

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
| Un movimiento DESPERDICIO | No lista Órdenes ni inventario ni da altas (500): no conoce el tipo | En el UAT: la limpieza del E2E (`06_limpiar_e2e.sql`) borra los que creó la prueba. Uno creado fuera del E2E bloquea la vuelta atrás hasta corregirlo (P1-15) |
| Un usuario con varios roles | No emite documentos ni lista usuarios (500: «el MVP admite exactamente uno») | Dejarle un solo rol desde Usuarios y roles (con la versión nueva) |
| Un insumo por lote o serie | Sus ingresos fallan (500: la base exige el lote) | Volverlo a SIN_LOTE (exige sus lotes en cero) o no ingresarlo |

Todo lo demás (compras, lotes de otros insumos, devoluciones, descuentos por Detalle, comunicaciones, firmas, reclamos, identidad, permisos configurados) queda en la base y la versión anterior lo ignora. Sin datos reales, la vuelta atrás del UAT es: la limpieza de cada E2E (que conserva `OR-000001`), la consulta de arriba en cero, un rol por usuario y los dos comandos. Se ensayó así (fase 5c: lee, escribe e integridad sin problemas).

**Pares de vuelta atrás desde el 16/11/2026:** `00029-kay` + `dpl_CRXZ…` (macroiteración V1.4), ensayado sobre las 35 migraciones. Al cierre del despliegue los tres controles de la consulta de arriba daban 0. `00027-sas` y anteriores no se probaron sobre las 35 migraciones.

## 8. Iteración de UX de Recepción: procedimiento (16/11/2026)

**Resultado del 16/11/2026: publicado y validado.** Backend `00033-fah` (`677dbb1`), frontend `dpl_Agpv37uP5wG8uXM3rsUaHQLLbpxB`, São Paulo con 37 migraciones, desde las 18:54 UTC. Respaldos: antes `uat/20261116T184846Z`, después `uat/20261116T220226Z` con ensayo en la nube correcto. E2E UX 47 de 47, V1.4 67 de 67 e integral 68 de 68, cada uno con su limpieza selectiva. Detalle en [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), sección B. Desde las 22:54 UTC el tráfico está en `00036-jis`: la misma imagen y configuración, con mínimo 0 (sección 9).

**Lección:** la limpieza selectiva borra toda fila nueva desde su línea de base y solo aborta si aparece una Orden o un cliente que no son del E2E, o si cambia una fila previa; una acción manual sobre una Orden conservada que solo agrega filas (por ejemplo, un intento de WhatsApp) se borra con el E2E. Mientras corren los E2E no se opera en la pantalla del UAT.

Publica `mvp-v2` con la iteración de UX de Recepción (DEC-UX-01 a 14) sobre el par vigente `00031-ror` + `dpl_7Zo4…`. Igual que la sección 7, con estas diferencias:

- **Migraciones (2, en orden):** `20261116000100_recargos_medio_pago` (recargo por medio de pago, Transferencia 2 %, copia en el pago, entidad de auditoría `MEDIO_PAGO`) y `20261116000200_recargo_detalles_devoluciones` (reparto del recargo en el pago, recargo devuelto con su tope, marca de observaciones unificadas en la recepción). Aditivas: columnas con valor por defecto, sin tablas nuevas (69 tablas y 8 vistas). El `db push --dry-run` tiene que listar **solo esas dos**; después, 37.
- **Configuración:** ninguna variable nueva. La plantilla de `00031-ror` sirve tal cual; DC12 sigue inactiva (sin `RMA_TIPO_EQUIPO_CAMPO`).
- **E2E posteriores, cada uno con su línea de base y su limpieza (7.7):** [`probar_ux_recepcion.py`](../supabase/scripts/validacion_uat/probar_ux_recepcion.py), `probar_macro_v14.py` y `probar_macro_integral.py`. El primero cambia el recargo de Transferencia a 3 % durante la prueba y lo vuelve a 2 % al terminar, también si falla; si no quedara en 2 %, la limpieza aborta porque `medio_pago` es maestra.
- **Ensayo local:** [`ensayar_despliegue_ux.py`](../supabase/scripts/validacion_uat/ensayar_despliegue_ux.py), 48 de 48: base con las 35 migraciones y una Orden previa con foto; el backend anterior (`9176921`) sigue funcionando con las 37 (E2E V1.4 con su limpieza); el backend nuevo pasa los tres E2E con su limpieza; y el anterior lee las Órdenes que crea la versión nueva.

**Vuelta atrás:** `00031-ror` + `dpl_7Zo4UDKAcsUBnHfPf63L2QtU3d3e`, sin tocar el esquema (ensayado sobre las 37 migraciones). La versión anterior ignora los recargos, su reparto y el recargo devuelto: sus pantallas muestran los importes base. Con una Orden ingresada con el texto único (sin estado físico aparte), la versión anterior pide registrar el estado físico antes de generar el comprobante o confirmar la recepción: se completa desde la corrección del ingreso. Sin datos reales, la limpieza de cada E2E deja la base como antes.


## 9. Escalado y costo del backend del UAT (desde el 16/11/2026)

**Regla: el UAT escala a cero.** Ninguna instancia queda encendida sin uso; la primera solicitud después de un rato sin uso paga un arranque en frío: el 16/11/2026, `/health` respondió en 6,8 s con la instancia apagada y en 0,12 s después.

### 9.1 Cómo se cobra y por qué se cambió

- **Facturación por solicitud** (CPU solo durante las solicitudes). Una instancia mínima se cobra todo el día a la tarifa de inactividad, aunque no reciba solicitudes.
- **Mínimo de servicio y mínimo de revisión no son lo mismo:**
  - el **de servicio** (`gcloud run services update --min`) no crea revisión y se reparte entre las revisiones que reciben tráfico;
  - el **de revisión** (`--min-instances`, anotación `autoscaling.knative.dev/minScale`) es inmutable: cambiarlo crea una revisión nueva. Lo hereda cada revisión nueva desde la plantilla.
- **Una etiqueta mantiene el mínimo de su revisión aunque no reciba tráfico.** Hasta el 16/11/2026 todas las revisiones tenían mínimo 1 y quedaban seis referenciadas (la pública y cinco etiquetas): seis instancias inactivas todo el día, hasta 144 instancia-hora diarias; se midieron entre 96 y 104 en los días de los despliegues, porque las etiquetas se fueron sumando. La auditoría de costos de ese día lo identificó como el gasto principal del UAT.

### 9.2 Cambio aplicado el 16/11/2026

| Hora (UTC) | Acción | Revisión nueva |
|---|---|---|
| 22:44 | `update-traffic --remove-tags auth,sp-d226fd2,it1-14108ef,v14-5c6137e,mi-9176921,ux-677dbb1` | No |
| 22:45 | `services update --min=0` (mínimo de servicio) | No |
| 22:52 | Medición: las cinco revisiones viejas en 0 instancias; `00033-fah` seguía con 1 por su mínimo de revisión | — |
| 22:53 | `services update --min-instances=0 --no-traffic --tag min0-677dbb1` → `00036-jis`, 0 % | Sí, indispensable |
| 22:54 | `update-traffic --to-revisions rt-rma-uat-api-00036-jis=100` y `--remove-tags min0-677dbb1` | No |

**Por qué la revisión nueva no puso en riesgo la versión publicada:**

- la plantilla apuntaba a la imagen por digest (`sha256:dcc2f58d…`) y al secreto con la versión fijada;
- el tráfico estaba fijado a `00033-fah` por nombre, y la revisión se creó con `--no-traffic`;
- comparada con `00033-fah`: la misma imagen, las mismas 14 variables, recursos, cuenta de servicio, concurrencia y etiqueta `commit=677dbb1`. Solo cambia el mínimo;
- por su etiqueta respondió igual que la URL pública antes de recibir tráfico: `/health` 200; 401 sin token y con token inválido; `/docs`, `/redoc` y `/openapi.json` 404; CORS solo del frontend.

**Configuración efectiva después:**

- servicio sin mínimo (0) y máximo 20;
- plantilla y `00036-jis` sin mínimo (0) y máximo 1;
- tráfico 100 % en `00036-jis`, sin etiquetas;
- 22 revisiones: no se borró ninguna revisión ni imagen.

Las demás revisiones conservan su mínimo 1 (inmutable), pero sin tráfico ni etiqueta no levantan instancias.

**Medido (Cloud Monitoring, `instance_count` por revisión):**

- las cinco revisiones que tenían etiqueta quedaron en 0 desde las 22:46;
- `00033-fah` quedó en 0 desde las 22:56, al perder el tráfico;
- `00036-jis` apagó su última instancia a las 23:11, unos 15 minutos después de la última solicitud.

Después el servicio quedó sin instancias hasta la solicitud siguiente. `verificar_escalado_uat.py --esperada rt-rma-uat-api-00036-jis`: OK.

**Ahorro estimado** (precios de lista sin verificar, una instancia inactiva de 1 vCPU y 512 MiB a unos USD 0,30 a 0,45 por día; no es un dato de facturación, porque no hay exportación de facturación):

- frente a las seis instancias inactivas: unos USD 1,8 a 2,7 por día (USD 54 a 81 por mes);
- frente a una sola revisión con mínimo 1: unos USD 0,30 a 0,45 por día (USD 9 a 14 por mes).

El costo real se ve en la consola de Facturación.

**Vuelta atrás del cambio:** `update-traffic --to-revisions rt-rma-uat-api-00033-fah=100`. Vuelve a dejar una instancia inactiva.

### 9.3 En cada publicación

1. **Mínimo 0.** La revisión nueva hereda mínimo 0 de la plantilla; no pasar `--min-instances` mayor que 0 ni `--min` al servicio.
2. **Etiqueta solo temporal:** se crea con `--no-traffic --tag <etiqueta temporal>` para probar la revisión y se quita con `--remove-tags` al terminar las pruebas posteriores (sección 3, paso 4).
3. **Vuelta atrás por nombre:** las revisiones anteriores quedan sin etiqueta y sin instancias.
   - Volver a una de mínimo 1 (`00033-fah` y anteriores) vuelve a dejar una instancia inactiva mientras tenga el tráfico.
   - Si la vuelta atrás va a durar, conviene una copia con mínimo 0: `services update --min-instances=0 --no-traffic --tag <etiqueta temporal> --image <digest de esa revisión>`. Ojo: la copia toma las variables de la plantilla, que son las de la última revisión; antes de pasarle el tráfico, compararla con la revisión original (`gcloud run revisions describe`), igual que en la sección 9.2, y ajustar con `--update-env-vars` o `--update-secrets` si difieren.
4. **Control automático, al final de cada publicación:**
   - correr `python supabase/scripts/validacion_uat/verificar_escalado_uat.py --esperada <revisión publicada>` (solo lectura);
   - falla si hay mínimo de servicio o de plantilla, si el tráfico no está 100 % en la revisión esperada, si queda alguna etiqueta (salvo `--permitir-etiquetas` durante las pruebas) o si una revisión referenciada tiene mínimo;
   - el resultado se anota en el registro del despliegue.
5. **Comprobación con métricas** (opcional, tarda): en Cloud Monitoring, `run.googleapis.com/container/instance_count` por `revision_name`. Unos 15 minutos después de la última solicitud tiene que quedar en 0.
