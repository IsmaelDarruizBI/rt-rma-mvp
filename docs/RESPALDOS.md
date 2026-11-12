# Respaldos y recuperación del UAT

Respaldo mínimo, cifrado y restaurable de la base del UAT (Supabase PostgreSQL), con su procedimiento de recuperación.

**Estado (11/11/2026): operativo.**

- Respaldo diario de São Paulo (`pcdnmhzwhzymznojndrn`) a las 03:00 de Argentina, con un rol de solo lectura.
- La primera copia se generó y verificó, y la restauración completa se ensayó en la nube (sección 3).
- **Descifrado con la clave real: OK.** La persona responsable descifró en su máquina, con su clave privada, `rma.dump.age` y `auth.dump.age` de la copia `uat/20261111T193144Z`: los dos dan `PGDMP`. Borró los descifrados; la clave no se compartió.
- La primera ejecución programada es el 12/11/2026 a las 06:00 UTC. Hasta entonces, el Scheduler se probó disparado a mano.

## 1. Opciones evaluadas

| Opción | Disponible | Decisión |
|---|---|---|
| Copias administradas de Supabase (diarias y PITR) | No en plan Free: «We automatically back up all Pro, Team, and Enterprise Plan projects» ([backups](https://supabase.com/docs/guides/platform/backups)) | Descartada mientras el UAT siga en Free. Pasar a Pro las incluye, con costo |
| JSON de tablas (`reinicio_uat/00_exportar.sql`) | Sí | Útil para auditar, **no es un respaldo restaurable** por sí solo: no lleva secuencias ni Auth y no tiene restauración automatizada |
| `pg_dump` lógico, cifrado, en un Cloud Run Job programado | Sí, con la infraestructura actual (Cloud Run, Secret Manager, GCS) | **Elegida y activa:** menor complejidad y costo |

## 2. Qué se respalda

[`supabase/scripts/respaldo/respaldar.sh`](../supabase/scripts/respaldo/respaldar.sh), en `postgres:17-alpine`. Cada ejecución deja `uat/<marca UTC>/`:

| Archivo | Contenido | Protección |
|---|---|---|
| `rma.dump.age` | Datos de todo el esquema `rma`, con los valores de las secuencias (`pg_dump` custom, `--data-only`). El esquema no va: sale de las migraciones del repositorio | Cifrado con `age` |
| `auth.dump.age` | `auth.users` y `auth.identities`, con esquema y datos. Contiene los hashes de las contraseñas | Cifrado con `age` |
| `manifiesto.json` | Versión de `pg_dump`, migraciones aplicadas, conteos por tabla, secuencias, cantidad de cuentas | Sin datos de negocio ni personales |
| `SHA256SUMS` | Sumas de los tres archivos | — |

**Conexión, sin credencial de administración:**

El Job usa el rol `rma_respaldo`, creado con [`crear_secreto_respaldo.py`](../supabase/scripts/respaldo/crear_secreto_respaldo.py):

- **Permisos:** `LOGIN` y `BYPASSRLS`, miembro de `pg_read_all_data` con `INHERIT TRUE, SET FALSE`.
  - `pg_read_all_data` da lectura de tablas y secuencias y `USAGE` sobre los esquemas, incluido `auth`. No da escritura ni DDL.
  - `BYPASSRLS` hace falta porque `auth.users` y `auth.identities` tienen RLS y `pg_dump` no respalda tablas filtradas.
- **Límites:** `default_transaction_read_only = on`, 2 conexiones y `statement_timeout` de 5 minutos.
- **Verificado en una transacción revertida:** lee `rma`, `auth` y las migraciones, y la escritura es rechazada.
- **Credencial:** la contraseña se genera al azar y va directo a Secret Manager. Nadie la ve, y la base recibe solo el verificador SCRAM.
- **Conexión:** pooler en modo sesión, `aws-0-sa-east-1.pooler.supabase.com:5432` (el que admite `pg_dump`), con `sslmode=verify-full` y la CA `supabase-ca.crt` montada en el Job.

**Cifrado:**

- Con la clave **pública** de `age` (`age1zen3sqv9…yazx5`), la única que tiene el Job.
- La clave **privada** no está en GCP ni en el repositorio: la guarda la persona responsable, en su gestor de contraseñas y con una copia fuera de línea. Sin ella el respaldo no se puede leer.
- Los volcados sin cifrar solo existen en un temporal del contenedor, con `umask 077`, y se borran al terminar.

**Escritura en el bucket:**

- Los cuatro archivos se arman completos en el temporal y se copian de a uno.
- El Job relee el destino y falla si `SHA256SUMS` está vacío o no coincide.
- **Motivo:** la cuenta del Job solo crea objetos. Con streaming writes, gcsfuse puede crear un objeto vacío al abrir el archivo y después necesitar sobrescribirlo, y el error de cierre no siempre llega al shell. La primera ejecución quedó así: `SHA256SUMS` en 0 bytes y el Job con éxito igual. Se borró y se corrigió el script.

**Fuera de la base:**

- **Fotos:** `gs://rt-rma-uat-fotos`, en GCS, no en Supabase.
  - Hoy tiene borrado suave de 7 días, sin versionado, y está vacío.
  - Pendiente (P2): versionado más una regla que borre las versiones no actuales a los 30 días, antes de que haya fotos reales.
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
| Error de datos en el mismo proyecto | `restaurar.sh` `rma` sobre el proyecto (ensayo y después aplicar), con una conexión de administración. Las cuentas no se tocan |
| Proyecto perdido | Proyecto nuevo y configuración de Auth (sección 4 de la migración) → `supabase db push` → `restaurar.sh` `rma` → base de trabajo con `restaurar.sh` `auth` → `migrar_uat.py cuentas` → `rma_api`, `rma_respaldo` y sus secretos → nueva revisión de Cloud Run. Es el mismo recorrido ya ejecutado en la migración a São Paulo |
| Foto borrada | Dentro de los 7 días: `gcloud storage restore`. Con versionado: la versión anterior |

**Ensayo en la nube** ([`ensayar_restauracion.sh`](../supabase/scripts/respaldo/ensayar_restauracion.sh)): la cadena completa con datos reales y sin la clave privada.

- **Comando:**

  ```bash
  gcloud run jobs execute rt-rma-respaldo-db --region southamerica-east1 --project rosariotecno-460217 \
    --args /respaldos/_herramientas/ensayar_restauracion.sh --wait
  ```

  En Git Bash, usar PowerShell: Git Bash convierte `/respaldos/...` en una ruta de Windows.
- **Recorrido:**
  1. Respalda São Paulo con la misma conexión de solo lectura, cifrado con una clave `age` que se genera y se borra dentro del contenedor. No escribe en el bucket.
  2. Levanta un PostgreSQL temporal con las migraciones de `_herramientas/migraciones`.
  3. Restaura `rma` en ensayo y en aplicar; compara secuencias y restaura Auth en una base de trabajo.
- **Resultado del 11/11/2026, ejecución `rt-rma-respaldo-db-tjjmb`: OK.**
  - 20 migraciones aplicadas.
  - `rma`: ensayo revertido y aplicación con las 45 tablas, sus conteos e integridad sin problemas.
  - Secuencias iguales al manifiesto.
  - Auth: 4 cuentas.
- **Resultado del 12/11/2026, después de aplicar la migración 21, ejecución `rt-rma-respaldo-db-kk6k6`: OK.** 21 migraciones aplicadas; 45 tablas con sus conteos e integridad sin problemas; secuencias iguales al manifiesto; 4 cuentas. Antes de migrar se tomó la copia `uat/20261112T031447Z` (ejecución `rt-rma-respaldo-db-jsk68`).
- **Resultado del 12/11/2026, después de aplicar las migraciones 22 y 23 (macroiteración), ejecución `rt-rma-respaldo-db-8k7zh`: OK.** 23 migraciones aplicadas; 47 tablas con sus conteos e integridad sin problemas; secuencias iguales al manifiesto; 4 cuentas. Antes de migrar se tomó la copia `uat/20261112T145502Z` (`rt-rma-respaldo-db-5ncpg`) y después `uat/20261112T151635Z` (`rt-rma-respaldo-db-t2lzw`), con 23 migraciones.
- **Cada migración nueva** se agrega a `_herramientas/migraciones/` al aplicarla (un archivo nuevo no choca con la retención). Las copias anteriores se restauran con las migraciones que lista su manifiesto, que están en el historial de Git.

**Descifrado con la clave real:** lo hace solo la persona responsable, en su máquina; la clave privada no se comparte. **Resultado del 11/11/2026: OK**, los dos archivos de `uat/20261111T193144Z` dan `PGDMP`. En PowerShell, sobre una copia descargada:

```powershell
$d = "$env:USERPROFILE\respaldos-rma\nube-uat-20261111T193144Z"
age -d -i <ruta a rma-respaldo.key> -o "$env:TEMP\rma.dump" "$d\rma.dump.age"
age -d -i <ruta a rma-respaldo.key> -o "$env:TEMP\auth.dump" "$d\auth.dump.age"
[Text.Encoding]::ASCII.GetString((Get-Content "$env:TEMP\rma.dump" -Encoding Byte -TotalCount 5))   # PGDMP
[Text.Encoding]::ASCII.GetString((Get-Content "$env:TEMP\auth.dump" -Encoding Byte -TotalCount 5))  # PGDMP
Remove-Item "$env:TEMP\rma.dump", "$env:TEMP\auth.dump"
```

Las dos líneas tienen que mostrar `PGDMP`. Los descifrados contienen los hashes de las contraseñas: se borran enseguida.

**Prueba local** ([`probar_respaldo_local.sh`](../supabase/scripts/respaldo/probar_respaldo_local.sh), con Docker y la pila local de Supabase, 11/11/2026): **OK**. Los mismos controles con datos ficticios, y además el contenido de las 45 tablas idéntico al origen.

**Ensayo periódico:** una vez por mes, el ensayo en la nube. Además, cada tanto, el descifrado de la última copia con la clave real.

## 4. Recursos activos (11/11/2026)

Proyecto `rosariotecno-460217`, región `southamerica-east1`.

| Recurso | Configuración |
|---|---|
| Bucket `gs://rt-rma-uat-respaldos` | Standard, acceso uniforme, acceso público bloqueado (un pedido anónimo recibe 403). **Retención de 30 días** en todo el bucket: ningún objeto se borra ni se sobrescribe antes. Ciclo de vida: borra `uat/` a los 35 días. `_herramientas/` queda excluida: si se borrara, el Job dejaría de funcionar. Borrado suave de 7 días |
| `_herramientas/` | `respaldar.sh`, `restaurar.sh`, `ensayar_restauracion.sh`, `supabase-ca.crt` y `migraciones/` (las 23 del repositorio; la 21, la 22 y la 23 se agregaron el 12/11/2026, al aplicarlas en São Paulo) |
| Cuenta de servicio `rt-rma-respaldo` | Sin roles en el proyecto. `storage.objectCreator` y `storage.objectViewer` solo en ese bucket: crea y lee, no borra ni sobrescribe. `secretAccessor` solo en su secreto. `run.invoker` solo en su Job |
| Secreto `rma-uat-respaldo-db-url` | Versión 1. Solo la lee `rt-rma-respaldo`. Conexión de `rma_respaldo` (sección 2) |
| Rol `rma_respaldo` en São Paulo | Sección 2 |
| Cloud Run Job `rt-rma-respaldo-db` | Imagen `postgres@sha256:e5d2edd2…4700d0` (`17-alpine`, fijada por digest), 1 vCPU, 512 MiB, gen2. Bucket montado en `/respaldos`. `RMA_RESPALDO_DB_URL` desde el secreto `:1`, `RMA_RESPALDO_DESTINATARIO` con la clave pública. 600 s, 1 reintento |
| Cloud Scheduler `rt-rma-respaldo-diario` | `0 3 * * *`, `America/Argentina/Buenos_Aires`. POST a `…/jobs/rt-rma-respaldo-db:run` con OAuth de `rt-rma-respaldo`. Probado a mano: ejecución `rt-rma-respaldo-db-lm5gf`, OK |

**Primera copia:** `uat/20261111T193144Z/`.

- `SHA256SUMS` coincide, verificado en el Job y de nuevo en local.
- Los volcados están cifrados para un solo destinatario y sin cabecera `PGDMP` legible.
- El manifiesto informa `pg_dump` 17.11, 20 migraciones, 45 tablas con los conteos de São Paulo, 4 cuentas y 4 identidades.
- Además quedaron `193846Z`, `193925Z`, la primera con la retención activa, y `194141Z`, la del Scheduler.

**Costo:** cada copia pesa unos 45 KB y el Job tarda unos 12 s. Menos de US$ 0,15 por mes:

| Recurso | Costo |
|---|---|
| GCS: 35 copias, menos de 2 MB | Menos de US$ 0,01 por mes |
| Cloud Run Job | Dentro del uso gratuito |
| Secret Manager: 3 versiones activas de 6 gratuitas | US$ 0 |
| Cloud Scheduler: 3 trabajos gratis por cuenta de facturación | US$ 0, o US$ 0,10 por mes si la cuenta ya usa los 3 |

Revisar el costo al cargar datos reales.

**Cambiar las herramientas:** por la retención, un archivo de `_herramientas/` no se puede reemplazar durante 30 días desde que se subió.

1. Subir la versión nueva con otro nombre o en otra carpeta (por ejemplo `_herramientas/v2/`).
2. Actualizar el Job:
   - `--args`;
   - si cambian las migraciones, `ensayar_restauracion.sh` busca la carpeta `migraciones` **junto a sí mismo**: subirlas a la carpeta nueva.
3. Correr el ensayo en la nube.

**Rotar la credencial:** `crear_secreto_respaldo.py rotar …`. Después:

1. Actualizar el Job al secreto `:2`.
2. Correr el ensayo.
3. Deshabilitar la versión 1.

**Recrear desde cero:** los comandos están en el historial de Git de este archivo (`f304b5b`). Diferencias con lo que se ejecutó:
- desde Git Bash, el Job se crea con PowerShell (las rutas `/respaldos/...`);
- la retención se aplica después del primer respaldo válido;
- el ciclo de vida se limita a `uat/`.

## 5. Retención

| Qué | Cuánto |
|---|---|
| Respaldos diarios | 30 días, inmutables por la política del bucket; se borran a los 35 |
| Fotos borradas | 7 días de borrado suave (hoy); con versionado, 30 días |
| Copia descargada `%USERPROFILE%\respaldos-rma\nube-uat-20261111T193144Z\` | Cifrada. Ya sirvió para el descifrado con la clave real; se borra junto con los respaldos manuales previos (25/11/2026) |
| Respaldos manuales previos (`%USERPROFILE%\respaldos-rma\`) | Hasta el 25/11/2026, cuando cierra el período de vuelta atrás de la migración. Tienen datos personales `uat-reinicio-20261110` y `sp-or000001-20261111`. Esta última está en la computadora actual, con acceso solo para la cuenta de Windows de quien opera. `uat-reinicio-20261110` y `sp-pruebas-20261111` quedaron en la computadora anterior: confirmar dónde están y borrarlas en la misma fecha |

Cuando el UAT pase a datos reales, revisar la retención y considerar el plan Pro (copias físicas y PITR).
