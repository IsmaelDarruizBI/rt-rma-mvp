# Respaldos y recuperación del UAT

Respaldo mínimo, cifrado y restaurable de la base del UAT (Supabase PostgreSQL), con su procedimiento de recuperación.

**Estado (11/11/2026):**

- Scripts preparados y probados en local con datos ficticios.
- **Sin activar en la nube:** falta autorizar los recursos de la sección 4.

## 1. Opciones evaluadas

| Opción | Disponible | Decisión |
|---|---|---|
| Copias administradas de Supabase (diarias y PITR) | No en plan Free: «We automatically back up all Pro, Team, and Enterprise Plan projects» ([backups](https://supabase.com/docs/guides/platform/backups)) | Descartada mientras el UAT siga en Free. Pasar a Pro las incluye, con costo |
| JSON de tablas (`reinicio_uat/00_exportar.sql`) | Sí | Útil para auditar, **no es un respaldo restaurable** por sí solo: no lleva secuencias ni Auth y no tiene restauración automatizada |
| `pg_dump` lógico, cifrado, en un Cloud Run Job programado | Sí, con la infraestructura actual (Cloud Run, Secret Manager, GCS) | **Elegida:** menor complejidad y costo |

## 2. Qué se respalda

[`supabase/scripts/respaldo/respaldar.sh`](../supabase/scripts/respaldo/respaldar.sh), en `postgres:17-alpine`. Cada ejecución deja `<etiqueta>/<marca UTC>/`:

| Archivo | Contenido | Protección |
|---|---|---|
| `rma.dump.age` | Datos de todo el esquema `rma`, con los valores de las secuencias (`pg_dump` custom, `--data-only`). El esquema no va: sale de las migraciones del repositorio | Cifrado con `age` |
| `auth.dump.age` | `auth.users` y `auth.identities`, con esquema y datos. Contiene los hashes de las contraseñas | Cifrado con `age` |
| `manifiesto.json` | Versión de `pg_dump`, migraciones aplicadas, conteos por tabla, secuencias, cantidad de cuentas | Sin datos de negocio ni personales |
| `SHA256SUMS` | Sumas de los tres archivos | — |

**Cifrado:**

- Con la clave **pública** de `age` (`age1…`), que viaja como variable del Job.
- La clave **privada** no está en la nube ni en el repositorio: la guarda la persona responsable, en su gestor de contraseñas y con una copia fuera de línea. Sin ella el respaldo no se puede leer.
- Los volcados sin cifrar solo existen en un temporal del contenedor, con `umask 077`, y se borran al terminar.

**Fuera de la base:**

- **Fotos:** `gs://rt-rma-uat-fotos`, en GCS, no en Supabase. Hoy tiene borrado suave de 7 días y no tiene versionado. Recomendado, con autorización: versionado más una regla de ciclo de vida que borre las versiones no actuales a los 30 días.
- **Documentos emitidos:** se generan desde la base; no hay archivos que respaldar (`archivo_clave` vacío).
- **Configuración de Auth y claves del proyecto:** no están en la base. Se documentan en [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 4, y se repiten a mano.

## 3. Restauración

[`supabase/scripts/respaldo/restaurar.sh`](../supabase/scripts/respaldo/restaurar.sh). El modo `ensayo` es el valor por defecto. Antes de descifrar verifica `SHA256SUMS`.

**Datos (`RMA_RESTAURAR_PARTE=rma`), sobre una base con las mismas migraciones** (las que lista el manifiesto). Si no coinciden, aborta. En una sola transacción:

1. `session_replication_role = replica`, para que los triggers de inmutabilidad, saldos y secuencia de eventos no se disparen y las filas vuelvan tal cual;
2. vacía todas las tablas de `rma` y carga datos y secuencias;
3. vuelve a `origin` y verifica los conteos de cada tabla contra el manifiesto y `verificar_integridad()`;
4. en `ensayo` revierte todo («ENSAYO OK»); en `aplicar` confirma.

**Cuentas (`RMA_RESTAURAR_PARTE=auth`):**

- Se cargan en una **base de trabajo**, nunca sobre el esquema `auth` de un proyecto (el script lo rechaza).
- Las cuentas del proyecto se recrean desde esa base con el método ya probado en la migración, que conserva id y contraseña:

  ```bash
  python supabase/scripts/migracion_sp/migrar_uat.py cuentas --origen <url de la base de trabajo> --destino <ref> --auth-url https://<ref>.supabase.co --aplicar
  ```

**Escenarios:**

| Caso | Pasos |
|---|---|
| Error de datos en el mismo proyecto | `restaurar.sh` `rma` sobre el proyecto (ensayo y después aplicar). Las cuentas no se tocan |
| Proyecto perdido | Proyecto nuevo y configuración de Auth (sección 4 de la migración) → `supabase db push` → `restaurar.sh` `rma` → base de trabajo local con `restaurar.sh` `auth` → `migrar_uat.py cuentas` → `rma_api` y su secreto → nueva revisión de Cloud Run. Es el mismo recorrido ya ejecutado en la migración a São Paulo |
| Foto borrada | Dentro de los 7 días: `gcloud storage restore`. Con versionado: la versión anterior |

**Prueba local** ([`probar_respaldo_local.sh`](../supabase/scripts/respaldo/probar_respaldo_local.sh), 11/11/2026): **OK**.

- Respaldo cifrado (sin cabecera `PGDMP` legible).
- Ensayo sin cambios en el destino.
- Restauración de `rma` con el contenido de las 45 tablas y las secuencias idéntico al origen, e integridad 0.
- `auth` rechazado sobre una base con `auth.users`; cargado en una base de trabajo con el mismo id, email y hash.

Datos de la prueba: 4 usuarios, 4 cuentas ficticias, catálogos y stock con su libro. Ninguna Orden: los triggers de saldos ya demuestran el modo `replica`. **Ensayo periódico:** una vez por mes, descargar el último respaldo y repetir la restauración contra la pila local.

## 4. Activación en la nube (requiere autorización: crea recursos)

**Costo estimado:**

- unos pocos MB por día en GCS;
- la ejecución del Job, dentro del uso gratuito de Cloud Run;
- Cloud Scheduler incluye 3 trabajos gratis por cuenta de facturación.

Hay que habilitar la API `cloudscheduler.googleapis.com`.

1. **Claves de age** (en la máquina de la persona responsable): `age-keygen -o rma-respaldo.key`. La línea `public key: age1…` es la clave pública; el archivo, la privada (gestor de contraseñas y copia fuera de línea).
2. **Bucket** `rt-rma-uat-respaldos` en `southamerica-east1`:
   - acceso uniforme;
   - prevención de acceso público;
   - **política de retención de 30 días**, para que nadie, ni el propio Job, borre un respaldo antes de tiempo;
   - ciclo de vida que borra a los 35 días.

   Subir a `_herramientas/` `respaldar.sh` y `app/backend/app/datos/supabase-ca.crt` (certificado público).
3. **Cuenta de servicio** `rt-rma-respaldo`, con:
   - `secretAccessor` solo sobre su secreto;
   - `storage.objectUser` solo sobre ese bucket.
4. **Secreto** `rma-uat-respaldo-db-url`: crearlo vacío con acceso solo para esa cuenta, y cargarlo con [`crear_secreto_respaldo.py`](../supabase/scripts/respaldo/crear_secreto_respaldo.py).
   - Pide sin eco la contraseña del administrador de la base.
   - Usa el pooler en **modo sesión** (5432, el que admite `pg_dump`), con `verify-full`.
   - Pendiente P1: un rol de respaldo de solo lectura, en lugar del administrador, si Supabase permite otorgarle lectura sobre `auth.users`.
5. **Job:**

   ```bash
   gcloud run jobs create rt-rma-respaldo-db --region southamerica-east1 --project rosariotecno-460217 \
     --image docker.io/library/postgres:17-alpine --service-account rt-rma-respaldo@rosariotecno-460217.iam.gserviceaccount.com \
     --add-volume name=respaldos,type=cloud-storage,bucket=rt-rma-uat-respaldos \
     --add-volume-mount volume=respaldos,mount-path=/respaldos \
     --set-secrets RMA_RESPALDO_DB_URL=rma-uat-respaldo-db-url:1 \
     --set-env-vars RMA_RESPALDO_DESTINATARIO=<age1…>,RMA_RESPALDO_DESTINO=/respaldos,RMA_RESPALDO_ETIQUETA=uat \
     --max-retries 1 --task-timeout 600s --command sh --args /respaldos/_herramientas/respaldar.sh
   ```

6. **Programación diaria** (03:00, hora de Argentina):

   ```bash
   gcloud scheduler jobs create http rt-rma-respaldo-diario --location southamerica-east1 --project rosariotecno-460217 \
     --schedule "0 3 * * *" --time-zone "America/Argentina/Buenos_Aires" \
     --uri https://run.googleapis.com/v2/projects/rosariotecno-460217/locations/southamerica-east1/jobs/rt-rma-respaldo-db:run \
     --http-method POST --oauth-service-account-email rt-rma-respaldo@rosariotecno-460217.iam.gserviceaccount.com
   ```

   La cuenta necesita `run.invoker` sobre el Job.
7. **Primera ejecución manual** (`gcloud run jobs execute … --wait`). Después, la restauración en ensayo contra la pila local (sección 3).

## 5. Retención

| Qué | Cuánto |
|---|---|
| Respaldos diarios | 30 días, inmutables por la política del bucket; se borran a los 35 |
| Fotos borradas | 7 días de borrado suave (hoy); con versionado, 30 días |
| Respaldos manuales previos (`%USERPROFILE%\respaldos-rma\`) | Hasta que se cierre el período de vuelta atrás de la migración; `uat-reinicio-20261110` contiene datos personales |

Cuando el UAT pase a datos reales, revisar la retención y considerar el plan Pro (copias físicas y PITR).
