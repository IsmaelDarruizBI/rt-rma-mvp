# Esquema PostgreSQL de Rosario Tecno RMA

Esquema físico de la persistencia en Supabase PostgreSQL. Implementa el diseño lógico aprobado (`docs/postgresql/diseno-logico.md`). El informe técnico está en `docs/postgresql/diseno-fisico.md`. El backend todavía no lo usa: la aplicación sigue sobre JSON hasta su adaptación.

## Contenido

| Ruta | Qué es |
|---|---|
| `migrations/` | 12 migraciones SQL, en orden de dependencias. Crean el esquema `rma`, sus 45 tablas comentadas, vistas, triggers, permisos y datos de referencia |
| `seeds/referencia_operativa/` | Datos operativos iniciales válidos para producción: medios de pago, empresa, Términos y Condiciones v1, catálogo técnico de modelos y motivos de ajuste aprobados |
| `seeds/desarrollo/` | Datos **ficticios** de desarrollo. **Nunca se cargan en producción** |
| `tests/` | Pruebas SQL. Cada archivo de prueba corre en una transacción que se descarta |
| `scripts/generar_datos_referencia.cjs` | Regenera `migrations/20261102001200_datos_referencia.sql` |
| `scripts/generar_datos_iniciales.cjs` | Regenera `seeds/` desde los catálogos JSON del backend y el texto de Términos y Condiciones del frontend |
| `scripts/probar_concurrencia.cjs` | Pruebas con conexiones simultáneas reales; requiere el paquete `pg` |
| `config.toml` | Configuración de Supabase CLI. El esquema `rma` no se expone por la API de datos |

Todas las cargas iniciales son reproducibles: aplicarlas otra vez no duplica ni cambia nada.

## Requisitos

- Node.js, para `npx supabase` y los scripts.
- Un cliente SQL: `psql` o el editor SQL del panel de Supabase.
- Docker, solo para la base local (`supabase start`).

## Base local de desarrollo

```bash
npx supabase start          # Postgres 17 y servicios locales
npx supabase db reset       # aplica migrations/ y carga seeds/referencia_operativa y seeds/desarrollo
npx supabase status         # muestra la DB URL local
```

Pruebas:

```bash
for f in supabase/tests/*.sql; do psql "$DB_URL" -v ON_ERROR_STOP=1 -f "$f" || break; done
RMA_DB_URL="$DB_URL" node supabase/scripts/probar_concurrencia.cjs
```

Una prueba que falla aborta con un mensaje que dice qué regla no se cumplió. `select * from rma.verificar_integridad();` debe devolver cero filas.

## Proyecto de prueba en Supabase

Primero en un proyecto de **prueba**, nunca directamente en producción. Desde la raíz de `rt-rma-mvp`:

```bash
# 1. Autenticación de la CLI (token personal; queda fuera del repositorio)
npx supabase login

# 2. Vincular el proyecto (pide la contraseña de la base; no se guarda en Git)
npx supabase link --project-ref <ref-del-proyecto>

# 3. Ver qué se aplicaría
npx supabase migration list --remote
npx supabase db push --dry-run --remote

# 4. Aplicar las migraciones
npx supabase db push --remote
```

Con Supabase CLI 3, `migration list`, `db push` y `db query` apuntan por defecto a la base **local**: contra el proyecto vinculado hay que pasar `--remote`. La primera línea de cada comando indica el destino («Target: project …»); conviene revisarla antes de confirmar.

`db push` no carga seeds.

Consultas de solo lectura contra el proyecto, sin la contraseña de la base:

```bash
npx supabase db query --remote --read-only --file <consulta.sql>
```

### Después de aplicar

Con la CLI vinculada, sin la contraseña de la base:

1. **Versión:** `select version();` debe ser PostgreSQL 15 o posterior (con `db query --remote --read-only`).
2. **Cargas operativas:** los archivos de `seeds/referencia_operativa/`, en orden, con `npx supabase db query --remote --yes --file <archivo>`. Son reproducibles.
3. **Pruebas, sin dejar datos:**
   - armar un único script envuelto en una transacción que termina en ROLLBACK:

     ```bash
     node supabase/scripts/armar_pruebas_remotas.cjs <destino.sql>
     npx supabase db query --remote --yes --file <destino.sql>
     ```

   - Una regla incumplida aborta todo con un error.
   - Después, verificar con `--read-only` que las tablas operativas siguen vacías y que no existe el esquema `rma_pruebas`.
   - Las secuencias no son transaccionales: la numeración de Órdenes avanza con las pruebas. En un proyecto sin Órdenes reales se restaura con `select setval('rma.orden_numero_seq', 1, false);`.
   - **Nunca correr las pruebas en producción.**
4. **Acceso:** `select has_schema_privilege('anon', 'rma', 'usage');` debe dar falso, igual para `authenticated` y `service_role`.
5. **Asesores:** `npx supabase db advisors --remote --level info`. Sin problemas de seguridad; los avisos informativos de claves foráneas sin índice y de índices sin uso son esperados (ver el informe).

## Usuario de conexión de FastAPI

Las migraciones crean `rma_backend`, un rol **sin inicio de sesión** con los permisos del backend. El usuario de conexión `rma_api` se crea por entorno y hereda esos permisos por ser miembro de `rma_backend`.

### Crear o rotar la credencial

`scripts/generar_credencial_rma_api.cjs` hace todo sin mostrar ni escribir en disco la contraseña, la cadena de conexión ni el verificador SCRAM:

1. Genera una contraseña aleatoria (32 bytes).
2. Guarda la cadena completa del Transaction Pooler, con `sslmode=verify-full`, como versión nueva de un secreto de GCP Secret Manager, por la entrada estándar de `gcloud`.
3. Crea el rol en el proyecto Supabase vinculado, por la entrada estándar de `supabase db query`, con el verificador SCRAM-SHA-256.

Requisitos:
- `gcloud` autenticado y el secreto ya creado;
- el proyecto Supabase vinculado.

Funciona igual en PowerShell y en bash:

```bash
node supabase/scripts/generar_credencial_rma_api.cjs crear --proyecto-gcp <proyecto> --secreto <secreto> --project-ref <ref> --pooler-host <host-del-pooler>
```

`crear` se niega si el secreto ya tiene versiones activas. `rotar` aplica un `ALTER ROLE` con un verificador nuevo; después de verificar, se deshabilita la versión anterior del secreto.

El rol queda con:
- 20 conexiones como máximo;
- sentencias de hasta 30 segundos;
- transacciones inactivas de hasta 60 segundos;
- sin atributos de superusuario, creación de roles o bases, ni bypass de RLS.

### TLS

Supabase firma sus certificados con su propia autoridad raíz, que los sistemas no reconocen. `certs/supabase-ca.crt` es esa raíz pública, la **Supabase Root 2021 CA**:
- vigente hasta el 26/04/2031;
- SHA-256 `80:70:25:AD:50:D4:ED:21:9D:2C:9C:7D:29:9C:00:4F:82:4E:B0:0C:F7:F6:5A:FE:F6:07:D0:7B:72:E6:CA:FA`.

Los clientes validan con ella la cadena y el nombre del host:
- con libpq, `sslmode=verify-full` y `sslrootcert=supabase/certs/supabase-ca.crt`;
- con node-postgres, `ssl: { rejectUnauthorized: true, ca }`.

Nunca se desactiva la verificación.

### Verificar la conexión

```bash
node supabase/scripts/verificar_conexion_rma_api.cjs --proyecto-gcp <proyecto> --secreto <secreto> --ca supabase/certs/supabase-ca.crt
```

Lee la cadena del secreto sin mostrarla y comprueba:
- TLS con certificado validado;
- autenticación como `rma_api`;
- lectura de catálogos;
- escritura revertida con ROLLBACK;
- siete operaciones denegadas;
- bloqueo de fila entre dos conexiones.

No deja datos ni consume la secuencia de Órdenes. Requiere el paquete `pg`.

`probar_concurrencia.cjs` deja datos: solo se corre en bases descartables, nunca en DEV/UAT ni en producción.

### Entorno DEV/UAT

| Dato | Valor |
|---|---|
| Proyecto Supabase | `rt-rma-db` (`okcscsglnujnxtgobjfw`) |
| Proyecto GCP | `rosariotecno-460217` |
| Secreto | `rma-uat-database-url`. Versión 2 activa, con `sslmode=verify-full`; la versión 1, igual pero con `sslmode=require`, deshabilitada |
| Pooler | Transaction Pooler, puerto 6543 |

Cloud Run todavía no usa este secreto.

## Producción

- Arranca **sin datos de UAT**: migraciones y `seeds/referencia_operativa/`.
- Los catálogos reales (tipos de reparación, insumos con su stock inicial como INGRESO, Mesas y compatibilidades) y los usuarios reales, vinculados a Supabase Auth, se cargan aparte.
- `seeds/desarrollo/` nunca se carga.

## Reglas para quien escribe SQL contra este esquema

El esquema no puede garantizarlas solo. El backend las cumple dentro de la transacción de cada operación:

- **Bloqueos:** con `select ... for update`, siempre en el orden Cliente, Orden e insumos de menor a mayor id.
- **Acción de usuario:** insertarla al comienzo, con su clave de idempotencia; completar `respuesta` y `orden_id` al final (una sola vez).
- **Rechazos:** si una operación se rechaza, revertirla y registrar la acción `RECHAZADA` en una transacción aparte.
- **Libro de inventario:** **nunca usar `INSERT ... ON CONFLICT`**. Aplica los saldos antes de resolver el conflicto, así que un código repetido se rechaza.
- **Cierre:** la actualización que cierra la Orden es la última de la transacción.
- **Pooler en modo transacción:**
  - sin sentencias preparadas del lado del servidor;
  - sin `SET` de sesión;
  - sin bloqueos asesores de sesión;
  - sin tablas temporales que sobrevivan a la transacción.
- **Migraciones nuevas:** cada una revisa que el esquema siga sin acceso para `anon`, `authenticated` y `service_role`. La prueba `10_esquema.sql` lo verifica.
