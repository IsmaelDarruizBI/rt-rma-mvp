# Migración de Supabase a São Paulo (UAT)

Plan para mover la base y la autenticación de `rt-rma-db` (Oregón, `us-west-2`) a un proyecto nuevo en São Paulo (`sa-east-1`), junto a Cloud Run y al bucket de fotos (`southamerica-east1`).

**Estado (11/11/2026):** São Paulo migrado, validado y en cero Órdenes; revisión de corte `00023-zus` sin tráfico. **Falta el corte** (sección 16), que requiere autorización explícita. El UAT público sigue en Oregón.

Antecedentes y mediciones: [`postgresql/integracion-pendientes.md`](postgresql/integracion-pendientes.md) («Resultado en UAT» y «Alternativa: Supabase nuevo en São Paulo»). Activación original: [`postgresql/e8-activacion-supabase.md`](postgresql/e8-activacion-supabase.md). Autenticación: [`autenticacion.md`](autenticacion.md).

## 1. Motivo

Cada viaje de Cloud Run (São Paulo) a PostgreSQL (Oregón) cuesta unos 177 ms y las consultas, unos 0,1 ms. Con 61e2a14:

- una lectura hace 3 a 6 viajes: 0,6 a 1,2 s;
- un comando hace 13 a 27 viajes: 2,4 a 4,7 s.

Con la base en la misma región, el viaje debería bajar a pocos milisegundos. Se mide antes y después (sección 8).

## 2. Punto de partida (10/11/2026)

| Elemento | Estado |
|---|---|
| Origen | `rt-rma-db` (`okcscsglnujnxtgobjfw`), PostgreSQL 17, organización `RosarioTecno`. Sin copias administradas ni PITR (plan Free; confirmarlo en el panel) |
| Datos | Reiniciados ([`supabase/scripts/reinicio_uat/`](../supabase/scripts/reinicio_uat/)): cero Órdenes, BAT-IP14 10/0, un movimiento `MST-INICIAL-BAT-IP14`, próxima Orden OR-000001. Esquema `rma_respaldo_reinicio` presente; respaldo externo fuera del repositorio |
| Migraciones | 20 registradas (`20261102000100` a `20261110000100`) |
| Auth | 4 cuentas `<usuario>@usuarios.rma.invalid`, confirmadas, con hash bcrypt, identidad `email` (`provider_id` = id) y sin MFA; versión del esquema `auth` `20260831180000`. Vinculadas a `ADMIN-001`, `COORD-001`, `RECEP-001`, `TECH-001` |
| Backend | `rt-rma-uat-api-00020-tux` (61e2a14), 100 %. Secreto `rma-uat-database-url` (`:latest`) y `RMA_AUTH_SUPABASE_URL` de Oregón |
| Frontend | `rt-rma-uat.vercel.app`, despliegue `rt-rma-n49rz9qgv…`, construido con la URL y la clave publicable de Oregón |
| Fotos | `rt-rma-uat-fotos` vacío; no depende de Supabase |
| Cuota | La cuenta ve un solo proyecto (`projects list`). El plan Free admite **2 proyectos activos por persona**, sumando todas las organizaciones donde es Owner o Administrator; los pausados no cuentan ([facturación](https://supabase.com/docs/guides/platform/billing-on-supabase)). São Paulo cabe en la cuota y la deja completa |

## 3. Método

### Descartado: restaurar o clonar el proyecto

Según la [documentación](https://supabase.com/docs/guides/platform/clone-project):

- es solo para planes pagos con copias físicas;
- «the data will remain in the same region as the source project», así que no cambia de región;
- no copia la configuración de Auth, las claves de la API ni los objetos de Storage.

Ningún proyecto cambia de región.

### Elegido: proyecto nuevo, esquema por migraciones y datos seleccionados

| Pieza | Cómo |
|---|---|
| Esquema `rma` (funciones, triggers, restricciones, índices, vistas), `rma_backend` y sus permisos, historial de migraciones | Las 20 migraciones del repositorio con `supabase db push` |
| Datos de referencia (`rol`, `tipo_documento`, `tipo_evento`, `equivalencia_historial`, medios de pago predeterminados) | Los crean esas migraciones; se comparan con Oregón por código |
| Datos maestros, usuarios de RMA y stock inicial | `migrar_uat.py maestros` (sección 5) |
| Cuentas de Auth | `migrar_uat.py cuentas`, con el mismo id y la misma contraseña (sección 4) |
| `rma_api` | [`generar_credencial_rma_api.cjs`](../supabase/scripts/generar_credencial_rma_api.cjs) `crear`, con un secreto nuevo |

**Comprobado sin tocar Oregón:**

- **Las migraciones se aplican de cero:** las 20 corren sobre una base vacía, incluida la de E3, sin el procedimiento especial ([`supabase/README.md`](../supabase/README.md)).
- **El resultado es igual a Oregón:** `migrar_uat.py comparar`, con Oregón en solo lectura contra esa base local, da iguales en todo lo estructural:
  - columnas, funciones, triggers, restricciones, índices, vistas y secuencias;
  - permisos de tablas, columnas y funciones, y el bloqueo de `anon`, `authenticated` y `service_role` sobre `rma`;
  - las 20 migraciones y los datos de referencia.

  No hay deriva: reconstruir por migraciones reproduce Oregón.

**`rma_respaldo_reinicio` no viaja:** ni las migraciones ni la copia lo incluyen. Queda en Oregón, sin tocarlo, y no hace falta ejecutar `04_eliminar_respaldo.sql` antes de migrar.

## 4. Autenticación

### Método definitivo: cuentas con el mismo id y el mismo hash, por la API de administración

**Base oficial.** La [guía de migración desde Auth0](https://supabase.com/docs/guides/platform/migrating-to-supabase/auth0) importa cuentas con `auth.admin.createUser`:

- usa `password_hash` (bcrypt) y `email_confirm: true`;
- dice «Supabase supports bcrypt and Argon2 password hashes»;
- permite indicar el `id` para conservar el UUID.

El código de Supabase Auth acepta esos campos (`AdminUserParams`, en `internal/api/admin.go`) y valida el hash bcrypt (`NewUserWithPasswordHash`, en `internal/models/user.go`).

**Alternativa oficial descartada.** La [guía de problemas](https://supabase.com/docs/guides/troubleshooting/migrating-auth-users-between-projects) propone volcar y restaurar el esquema `auth` completo, pero:

- aclara que no hay un script oficial para migrar solo `auth`;
- la documentación advierte que las tablas que administra Supabase «may change at any time».

La API, en cambio, crea también la identidad `email` y absorbe las diferencias de versión del esquema `auth`.

**Procedimiento** (`migrar_uat.py cuentas`):

1. Lee de Oregón, en solo lectura y en memoria, las cuentas vinculadas a usuarios de RMA activos: `id`, `email` y hash.
2. Valida, antes de crear nada, que cada cuenta:
   - tenga un hash bcrypt;
   - esté confirmada;
   - no esté bloqueada;
   - tenga identidad `email`.

   La consulta de solo lectura ya comprobó que el rol de solo lectura de Oregón ve la columna: 4 de 4 hashes con formato bcrypt, contados sin extraerlos.
3. Crea en el destino cada cuenta que falte, con `id`, `email`, `password_hash` y `email_confirm: true`. La clave secreta del destino se pide sin eco.
4. Relee el destino y compara en memoria: mismo id, email y hash, con su identidad `email`. Solo imprime el código del usuario y «creada», «ya existe, iguales», «CONFLICTO» o «OK».

**Repetible e idempotente:**

- una cuenta que ya existe con el mismo id, email y hash no se toca;
- un email existente con otro id es un conflicto y no se crea nada para esa cuenta;
- los hashes nunca se imprimen, no se escriben en disco (el SQL de esta etapa no los lleva) y no viajan en el texto de una consulta: van solo en el cuerpo HTTPS hacia la API de Auth.

**Probado en local** (`probar_en_local.py`, sección 9) con Supabase Auth real y cuentas ficticias:

- las 4 cuentas se crearon con el id y el hash originales;
- la repetición no cambió nada;
- las 4 iniciaron sesión con su contraseña original, con `sub` igual al id original;
- una contraseña incorrecta se rechazó.

**Impacto para las personas:** la misma contraseña. Las sesiones abiertas no sirven en el proyecto nuevo, porque tiene otras claves de firma, así que cada persona inicia sesión de nuevo una vez después del corte.

**Condición previa en São Paulo (etapa 3):** repetir la prueba con una cuenta descartable: hash bcrypt de una contraseña aleatoria generada en memoria, inicio de sesión y token con `sub` igual al id; después se borra la cuenta. Si falla, se usa la alternativa.

### Alternativa: contraseñas nuevas y revinculación

Si la prueba de la etapa 3 falla o alguna validación lo impide:

1. Crear las cuentas con [`cuentas_rma.py`](../supabase/scripts/cuentas_rma.py) `crear --generar`.
2. Cargar `rma.usuario` con `auth_user_id` vacío (`maestros`, con el vínculo omitido).
3. Vincular con [`vincular_usuarios_auth.sql`](../supabase/scripts/vincular_usuarios_auth.sql).

Impacto: las cuatro personas reciben una contraseña nueva, entregada en persona; los nombres de usuario no cambian.

### Configuración que se repite a mano

Va en el proyecto nuevo y, según las decisiones aprobadas, también en Oregón:

| Pantalla | Valor | Oregón | São Paulo |
|---|---|---|---|
| *Sign In / Providers → Email* | habilitado; «Allow new users to sign up» **desactivado** | confirmar | configurar |
| *Password* | largo mínimo **10** | pasar de 6 a 10 (pendiente) | configurar |
| *URL Configuration* | Site URL `https://rt-rma-uat.vercel.app`, sin redirecciones adicionales | confirmar | configurar |
| *Rate Limits* | inicios de sesión por IP según [`autenticacion.md`](autenticacion.md), sección 4 | confirmar | igual que Oregón |
| *JWT Keys* | clave asimétrica **ES256** activa (el backend solo acepta ES256 por JWKS) | confirmar | confirmar |
| *Data API* | `rma` no expuesto | — | lo verifica `migrar_uat.py verificar` |

El dominio interno `usuarios.rma.invalid` no es una configuración de Supabase: lo fijan el frontend (`VITE_AUTH_DOMINIO_USUARIOS`, por defecto) y los scripts. No cambia.

## 5. Datos que se migran

Los copia `migrar_uat.py maestros` en un único bloque `DO` contra el destino.

| Tabla | Cómo | Clave |
|---|---|---|
| `rol`, `tipo_documento`, `tipo_evento`, `equivalencia_historial` | Migraciones | Comparados por código: diferencia = NO-GO |
| `medio_pago` | Migración E4 + copia | Por `codigo`: actualiza las predeterminadas y agrega las que falten |
| `usuario`, `empresa`, `texto_legal`, `motivo_ajuste`, `modelo_equipo`, `tipo_reparacion`, `insumo`, `mesa_trabajo`, `mesa_tipo_reparacion`, `tipo_reparacion_insumo` | Copia | Mismo id; `usuario` con su `auth_user_id` |
| `usuario_rol` | Copia | `rol_id` por el código del rol (los UUID de `rol` cambian entre proyectos) |
| `accion_usuario` + `movimiento_inventario` | Ingreso inicial con el mismo código y cantidad | El trigger del libro recalcula el stock: `insumo` nace en cero y queda conciliado |
| Secuencias | Sin `setval` | `orden_numero_seq` sin usar (OR-000001); la del libro queda en 1 |
| Resto de las operativas | Vacías | — |

**Guardas:**

- **En el origen**, aborta si Oregón tiene Órdenes o movimientos además del ingreso inicial.
- **En el destino**, aborta sin cambios en estos casos:
  - el destino tiene Órdenes o movimientos ajenos;
  - un código choca con otro id;
  - falta un rol;
  - `verificar_integridad()` no queda vacío.

**Repetible:** usa `ON CONFLICT … DO NOTHING` por clave primaria y crea el ingreso solo si falta. Probado: la segunda carga no cambió ninguna huella.

**Sin datos sensibles:** el SQL generado lleva solo catálogos y los 4 usuarios internos. Pasa por un archivo temporal privado que se borra enseguida.

## 6. Cloud Run y Vercel

### Backend

No se tocan `00020-tux` ni `rma-uat-database-url`.

1. Crear el secreto vacío `rma-uat-sp-database-url`. Cargarle la credencial con `generar_credencial_rma_api.cjs crear --secreto rma-uat-sp-database-url --project-ref <nuevo> --pooler-host <host del diálogo Connect>`:
   - pooler en modo transacción, puerto 6543;
   - usuario `rma_api.<nuevo ref>`;
   - el host se toma de `supabase link --project-ref <nuevo>` (`supabase/.temp/pooler-url`, que no lleva contraseña);
   - `sslmode=verify-full`.

   El host lleva un índice de clúster (`aws-N-sa-east-1`) que no se deduce: se copia del panel.
2. **Certificado:** comparar la huella SHA-256 del certificado de la base nueva (*Database Settings → SSL*) con `app/backend/app/datos/supabase-ca.crt`, el que trae la imagen. Si difiere es NO-GO, hasta incluirlo con un cambio de código autorizado. Nunca se baja `sslmode`.
3. **Revisión de prueba**, sin tráfico, con la etiqueta `saopaulo`:
   - imagen de 61e2a14;
   - `RMA_DATABASE_URL` desde `rma-uat-sp-database-url:1` (versión fijada, no `:latest`);
   - `RMA_AUTH_SUPABASE_URL=https://<nuevo ref>.supabase.co`;
   - `RMA_CORS_ALLOW_ORIGINS` con el origen de producción y además la URL de la vista previa de Vercel;
   - el resto, igual que `00020-tux`.

   Si TLS o la conexión fallan, la revisión no arranca y no afecta al tráfico.
4. **Revisión de corte:** la misma imagen y las mismas variables, pero `RMA_CORS_ALLOW_ORIGINS` solo con el origen de producción. Sin tráfico hasta el corte.

### Frontend: vista previa antes del cambio público (decisión 7)

1. `vercel deploy` (vista previa, **sin** `--prod`) desde una exportación limpia de 61e2a14, con:
   - `--build-env VITE_SUPABASE_URL=<nueva>` y `VITE_SUPABASE_PUBLISHABLE_KEY=<nueva publicable>`;
   - `VITE_API_BASE_URL=<URL de la etiqueta saopaulo>`;
   - `VITE_AUTH_MODO=supabase`.

   La vista previa queda protegida por la autenticación de Vercel.
2. Prueba de interfaz en la vista previa: inicio de sesión de los 4, permisos, catálogos, inventario, Inicio y Taller.
3. Para el corte:
   - registrar los valores de producción actuales de las variables;
   - reemplazar `VITE_SUPABASE_URL` y `VITE_SUPABASE_PUBLISHABLE_KEY`, que se fijan al construir: el despliegue publicado no cambia hasta el próximo `--prod`;
   - `vercel deploy --prod`.

   `VITE_API_BASE_URL` y `VITE_AUTH_DOMINIO_USUARIOS` no cambian.

## 7. Etapas de ejecución

Las etiquetas de Cloud Run tienen al menos 3 caracteres: la de prueba es `saopaulo` (`sp` se rechaza).

Cada etapa se autoriza por separado. Ninguna modifica Oregón, salvo la configuración de Auth decidida (largo mínimo 10).

| # | Etapa | Quién | Resultado |
|---|---|---|---|
| 0 | Herramientas y prueba local | Agente | **Hecho** (sección 9) |
| 1 | Medición de referencia en Oregón: `medir_api.py` contra `00020-tux` y viaje directo a PostgreSQL con un Cloud Run Job descartable (sección 8) | Persona usuaria (contraseña) y agente (Job, con autorización) | **Hecho** (11/11/2026): viaje 178,9 ms; lecturas de 1,08 s en el servidor |
| 2 | Configuración de Auth de Oregón: largo mínimo 10, registro deshabilitado confirmado | Persona usuaria (panel) | Oregón alineado |
| 3 | Crear el proyecto `sa-east-1` (Free, organización `RosarioTecno`), con su contraseña de base en un gestor de contraseñas. Configuración de Auth (sección 4). Prueba de `password_hash` con una cuenta descartable | Persona usuaria (panel) y agente (prueba) | **Hecho** (11/11/2026): `db-rt-rma` en `sa-east-1`; prueba de `password_hash` COMPATIBLE |
| 4 | `supabase db push --remote=<nuevo>`: la CLI pide la contraseña de la base sin eco. Después, `migrar_uat.py comparar --origen okcscsglnujnxtgobjfw --destino <nuevo>` | Agente | **Hecho** (11/11/2026): 20/20 aplicadas en `pcdnmhzwhzymznojndrn`; `comparar` igual a Oregón en esquema, permisos, migraciones y referencia; `verificar_integridad()` vacío |
| 5 | `migrar_uat.py maestros --aplicar` y `cuentas --aplicar`, primero sin `--aplicar` | Agente | **Hecho** (11/11/2026). Maestros, usuarios, roles y el ingreso `MST-INICIAL-BAT-IP14` (0 → 10) cargados por el agente. Las 4 cuentas, cargadas por la persona usuaria con `cuentas --aplicar`: mismo id, email y hash que Oregón, identidad `email`. `verificar`: OK (sin `rma_api`, que es de la etapa 6). `comparar`: 32 de 32 iguales. São Paulo: 4 cuentas, sin ficticias ni cuentas sin usuario de RMA |
| 6 | `rma_api` y el secreto nuevo; verificación del certificado; `migrar_uat.py verificar --destino <nuevo>` | Agente | **Hecho** (11/11/2026). `rma_api` creado con `generar_credencial_rma_api.cjs`: atributos iguales a Oregón, solo miembro de `rma_backend`. Secreto `rma-uat-sp-database-url` versión **1**, con acceso solo de la cuenta de la API. Pooler `aws-0-sa-east-1.pooler.supabase.com:6543` (modo transacción), tomado de `supabase link`. TLS validado con la CA incluida en la imagen (Supabase Root 2021). Conexión real desde un Job: permisos efectivos de `rma_backend`, escritura revertida, `DELETE`, `TRUNCATE` y `CREATE` rechazados, integridad 0, BAT-IP14 10/0 |
| 7 | Revisión de prueba `saopaulo` y vista previa de Vercel. Salud, 401, login de los 4, 403, recorrido DC31 con `verificar_uat.py` y medición | Agente y persona usuaria | **Hecho** (11/11/2026). `00022-vab` (`saopaulo`, 0 %) y vista previa `rt-rma-k1qeeu33d`. Aislamiento de tokens, lecturas (`medir_api.py`) y `probar_recorridos.py`: TODO OK. Pendiente manual: la pantalla de acceso en la vista previa |
| 8 | Devolver São Paulo a cero Órdenes: `01_reiniciar.sql` con la lista de Órdenes de la prueba, y `04_eliminar_respaldo.sql` en São Paulo. Después, `verificar` de nuevo | Agente | **Hecho** (11/11/2026). Ensayo con huella idéntica, reinicio aplicado, respaldo en la base eliminado. `verificar` 9/9 y `comparar` 32/32 |
| 9 | Revisión de corte (sin el origen de la vista previa), sin tráfico | Agente | **Hecho** (11/11/2026). `rt-rma-uat-api-00023-zus`, etiqueta `corte`, 0 %, CORS solo producción (sección 16) |
| 10 | Corte coordinado: confirmar que Oregón sigue sin Órdenes, tráfico a la revisión de corte y enseguida `vercel deploy --prod` | Agente | UAT en São Paulo |
| 11 | Verificación posterior: login de los 4 en la interfaz, Inicio y Taller vacíos, inventario 10, registros sin errores, medición | Agente y persona usuaria | OPERATIVO |
| 12 | Período de vuelta atrás de **14 días**: Oregón intacto y con actividad semanal (sección 11). Al cerrarlo, decidir pausa o eliminación de Oregón y de los respaldos | Persona usuaria | Decisión registrada |

Entre las etapas 10 y 11 nadie opera en UAT. Entre el corte y el nuevo inicio de sesión, las sesiones abiertas reciben 401 y vuelven a la pantalla de acceso.

## 8. Rendimiento

**API:** [`medir_api.py`](../supabase/scripts/migracion_sp/medir_api.py).

- Solo hace GET: no crea Órdenes.
- Inicia sesión una vez, con la contraseña pedida sin eco.
- Mide: sesión, usuarios, tipos de reparación, estaciones, listar Órdenes, Inicio, Taller, Inventario y detalle de insumo.
- Cada lectura se repite 10 veces con pausas de 3 s, descartando la primera; informa mediana, p90 y mínimo.
- Se corre contra la URL de la etiqueta de cada revisión: `auth---…` en Oregón y `saopaulo---…` en São Paulo, una detrás de la otra y con el mismo usuario.

**PostgreSQL directo:** un Cloud Run Job descartable en `southamerica-east1`, con la misma red y región que la API.

- Imagen `docker.io/library/postgres:17-alpine` y la cuenta de servicio de la API (`rt-rma-uat-api@…`).
- La cadena de conexión sale del secreto existente de cada base, montado sin modificarlo; nunca se imprime. Es la credencial de `rma_api`: `select 1` no usa privilegios de tabla, y crear un rol de solo lectura exigiría modificar la base.
- El certificado público de Supabase (`app/backend/app/datos/supabase-ca.crt`, el mismo que trae la imagen; SHA-256 `700723…F3B7`) va en un secreto temporal montado como archivo, con `verify-full`.
- Una sola sesión de `psql` ejecuta `\timing on` y 21 veces `select 1`. La primera se descarta y quedan 20 muestras; el tiempo de cada una es un viaje.
- Solo se escriben en los registros las líneas `Time:` (prefijo `LATENCIA`) y los errores.

Comandos exactos (bash). Para São Paulo se cambia solo `<secreto>`: `rma-uat-database-url` en Oregón, `rma-uat-sp-database-url:1` en São Paulo.

```bash
P=rosariotecno-460217; SA=rt-rma-uat-api@rosariotecno-460217.iam.gserviceaccount.com
gcloud secrets create rt-rma-latencia-ca --project $P --replication-policy automatic \
  --labels proposito=medicion-latencia --data-file app/backend/app/datos/supabase-ca.crt
gcloud secrets add-iam-policy-binding rt-rma-latencia-ca --project $P \
  --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor
SCRIPT='(echo "\\timing on"; for i in $(seq 1 21); do echo "select 1;"; done) | psql "$RMA_DATABASE_URL&sslrootcert=/ca/supabase-ca.crt" -X -q -v ON_ERROR_STOP=1 2>&1 | grep -E "^(Time|psql|FATAL|ERROR)" | sed "s/^/LATENCIA /"'
gcloud run jobs create rt-rma-latencia-db --project $P --region southamerica-east1 \
  --image docker.io/library/postgres:17-alpine --service-account $SA \
  --labels proposito=medicion-latencia --max-retries 0 --task-timeout 120s \
  --set-secrets "RMA_DATABASE_URL=<secreto>,/ca/supabase-ca.crt=rt-rma-latencia-ca:1" \
  --command sh --args="^@^-c@$SCRIPT"
gcloud run jobs execute rt-rma-latencia-db --project $P --region southamerica-east1 --wait
# Registros: textPayload:"LATENCIA" de la ejecución; descartar la primera muestra.
gcloud run jobs delete rt-rma-latencia-db --project $P --region southamerica-east1 --quiet
gcloud secrets delete rt-rma-latencia-ca --project $P --quiet
```

El delimitador `^@^` de `--args` es necesario: con `^|^` gcloud corta el script en cada `|`, y solo se ejecuta el `echo`.

### Línea base de Oregón (11/11/2026)

**PostgreSQL directo:** Job en `southamerica-east1` contra el pooler de Oregón, con `verify-full`.

| Muestras | Mediana | p90 | Mínimo | Máximo | Descartada |
|---|---|---|---|---|---|
| 20 | 178,9 ms | 179,1 ms | 178,7 ms | 190,0 ms | 219,7 ms (primera) |

Recursos temporales eliminados: el Job `rt-rma-latencia-db` con sus ejecuciones, y el secreto `rt-rma-latencia-ca` con su permiso.

**API:** `medir_api.py` contra `auth---rt-rma-uat-api-nszqooxxla-rj.a.run.app` (`00020-tux`), usuario `administracion`, 10 repeticiones más una descartada, pausas de 3 s, cero Órdenes. Todas las respuestas, HTTP 200.

- **Cliente:** ejecutado por la persona usuaria desde su máquina.
- **Servidor:** `httpRequest.latency` de Cloud Run para las mismas peticiones.

| Lectura | Cliente: mediana / p90 | Servidor: mediana / p90 |
|---|---|---|
| `/api/me` | 0,749 / 0,787 s | 0,543 / 0,547 s |
| Usuarios | 1,301 / 1,401 s | 1,081 / 1,081 s |
| Tipos de reparación | 1,277 / 1,359 s | 1,080 / 1,083 s |
| Estaciones | 1,297 / 1,326 s | 1,080 / 1,081 s |
| Listar Órdenes | 1,272 / 1,300 s | 1,080 / 1,082 s |
| Inicio | 1,285 / 1,301 s | 1,083 / 1,087 s |
| Taller | 1,299 / 1,342 s | 1,083 / 1,087 s |
| Inventario | 1,301 / 1,561 s | 1,083 / 1,462 s |
| Detalle de insumo | 1,248 / 1,261 s | 1,085 / 1,087 s |

**Lectura de los números:**

- En el servidor, cada lectura tarda unos 1,08 s, unos 6 viajes de 179 ms, y `/api/me` 0,54 s, unos 3 viajes. Casi todo es distancia a la base.
- La diferencia con el cliente, unos 0,2 s, es la red entre la persona usuaria y Cloud Run; no cambia con la migración.
- Con un viaje de pocos milisegundos en São Paulo, el tiempo del servidor debería bajar a decenas de milisegundos.

**Etapa 1 cerrada (11/11/2026). Veredicto: GO para preparar la creación del proyecto de São Paulo.**

### São Paulo: viaje directo (11/11/2026, etapa 6)

Mismo método que la línea base de Oregón: Job en `southamerica-east1`, `verify-full`, 20 `select 1` con la primera descartada. Secreto `rma-uat-sp-database-url:1`, credencial de `rma_api`.

| Ejecución | Mediana | p90 | Mínimo | Máximo |
|---|---|---|---|---|
| 1 | 3,96 ms | 4,25 ms | 3,83 ms | 6,70 ms |
| 2 | 2,88 ms | 2,99 ms | 2,78 ms | 3,03 ms |
| Oregón (referencia) | 178,9 ms | 179,1 ms | 178,7 ms | 190,0 ms |

El viaje baja unas 45 a 60 veces.

### São Paulo: lecturas de la API (11/11/2026, etapa 7)

`medir_api.py` contra `saopaulo---rt-rma-uat-api-nszqooxxla-rj.a.run.app` (`00022-vab`), con las mismas condiciones que Oregón: usuario `administracion`, 10 repeticiones más una descartada, pausas de 3 s, cero Órdenes. Las 9 lecturas devolvieron HTTP 200.

| Lectura | Cliente, Oregón → São Paulo | Servidor, Oregón → São Paulo |
|---|---|---|
| `/api/me` | 0,749 → 0,190 s | 0,543 → 0,032 s |
| Usuarios | 1,301 → 0,211 s | 1,081 → 0,058 s |
| Tipos de reparación | 1,277 → 0,219 s | 1,080 → 0,058 s |
| Estaciones | 1,297 → 0,217 s | 1,080 → 0,057 s |
| Listar Órdenes | 1,272 → 0,205 s | 1,080 → 0,057 s |
| Inicio | 1,285 → 0,216 s | 1,083 → 0,062 s |
| Taller | 1,299 → 0,216 s | 1,083 → 0,062 s |
| Inventario | 1,301 → 0,209 s | 1,083 → 0,061 s |
| Detalle de insumo | 1,248 → 0,225 s | 1,085 → 0,062 s |

Valores en mediana:

- **Cliente:** la reducción promedio es de 82,7 %. Lo que queda, unos 0,15 a 0,2 s, es la red entre la persona usuaria y Cloud Run.
- **Servidor:** cada lectura baja de unos 1,08 s a unos 0,06 s, alrededor de 95 %. Se cumple el objetivo de lecturas por debajo de 0,3 s.

**Comandos (escritura):**

- en Oregón no se crean Órdenes; su referencia es la tabla medida sobre `00017-wer` (alta 3,07 s, agregar trabajo 3,26 s, pago 2,38 s, ingreso de stock 3,08 s, cancelar 2,89 s);
- en São Paulo, el recorrido DC31 de la etapa 7 da los tiempos equivalentes, y la etapa 8 borra esas Órdenes.

**Condiciones equivalentes:**

- misma imagen y mismo pool;
- plan Free (Nano) en ambos;
- mismos datos;
- primera petición descartada;
- mismas pausas;
- una instancia caliente.

**Esperado:**

- viaje directo de pocos milisegundos;
- lecturas por debajo de 0,3 s;
- comandos por debajo de 0,5 s.

Un viaje mayor a 30 ms obliga a revisar el host del pooler antes del corte.

## 9. Herramientas y pruebas

Están en [`supabase/scripts/migracion_sp/`](../supabase/scripts/migracion_sp/) y no tienen credenciales embebidas.

| Archivo | Uso |
|---|---|
| `migrar_uat.py` | `comparar` (solo lectura), `maestros`, `cuentas` y `verificar`. Sin `--aplicar` no escribe. Destinos: `local`, un project ref o una URL de PostgreSQL |
| `probar_en_local.py` | Prueba de punta a punta con la pila local (`supabase start`) y datos ficticios. Simula Oregón como otra base del clúster local, con 4 cuentas cuyo hash bcrypt sale de contraseñas aleatorias en memoria; el destino es la base local reiniciada solo con migraciones y el Auth real |
| `medir_api.py` | Tiempos de lectura de la API (sección 8) |
| `probar_recorridos.py` | Recorridos funcionales con escritura sobre São Paulo: permisos, HP-REP-001, DC31 e ingreso de stock, con tiempos por comando (sección 15) |
| `probar_entornos.py` | Aislamiento de tokens entre Oregón y São Paulo, y lecturas autenticadas en São Paulo: cero Órdenes y stock. Solo GET |
| `probar_auth_destino.py` | Compatibilidad del Auth del proyecto nuevo, con una cuenta ficticia que siempre se borra (sección 14). Probado contra la pila local: COMPATIBLE |

**Resultados (10/11/2026):**

- **Prueba local completa: OK.**
  - Esquema y referencia iguales.
  - Maestros iguales y segunda carga sin cambios.
  - Cuentas creadas con el mismo id y hash, y su repetición sin cambios.
  - Inicio de sesión de las 4 con la contraseña original y `sub` igual al id.
  - Contraseña incorrecta rechazada.
  - Verificación final OK.
- **`comparar` Oregón (solo lectura) contra la base local:** todo lo estructural igual (sección 3).
- **`ruff check` y `ruff format --check`:** sin hallazgos.

Las líneas largas de SQL están exceptuadas por archivo.

## 10. Criterios GO/NO-GO

**GO para el corte** solo si se cumple todo:

1. **Migraciones:** `verificar` informa las 20 versiones, iguales a las del repositorio.
2. **Comparación con Oregón:** `comparar` da iguales el esquema, los permisos (tablas, columnas, funciones, sin acceso de la API a `rma`) y los datos de referencia.
3. **Datos maestros y stock:** `comparar` da iguales los maestros, el stock y el ingreso inicial. BAT-IP14 10/0 conciliado.
4. **Integridad:** `verificar_integridad()` vacío; cero datos operativos salvo el ingreso; próxima Orden OR-000001; sin `rma_respaldo_reinicio`.
5. **Usuarios:** los 4 activos, con su rol y vinculados a una cuenta del proyecto nuevo con el mismo email.
6. **`rma_api`:** miembro de `rma_backend`, sin superusuario ni `BYPASSRLS`; certificado verificado.
7. **Auth:** configuración igual a la tabla de la sección 4; token ES256.
8. **Acceso:** login de los 4 en la vista previa y por API, `/api/me` correcto, 401 sin token, 403 por suplantación y por rol.
9. **DC31:** el recorrido completo sobre la revisión `saopaulo`.
10. **Rendimiento:** mejora demostrada (sección 8).
11. **Infraestructura:** registros sin errores; `00020-tux` y el secreto de Oregón sin cambios.
12. **Reinicio de São Paulo** completo (etapa 8).

**NO-GO:** cualquier diferencia de esquema o permisos, una cuenta que no inicia sesión, un certificado distinto o una mejora no demostrada.

## 11. Vuelta atrás coordinada

**Antes del corte:** no hace falta nada. Oregón sigue atendiendo; la revisión `saopaulo` no tiene tráfico y el proyecto nuevo se puede eliminar.

**Después del corte** (hasta 14 días), las dos piezas juntas, en este orden:

1. Backend:

   ```bash
   gcloud run services update-traffic rt-rma-uat-api --region southamerica-east1 \
     --project rosariotecno-460217 --to-revisions rt-rma-uat-api-00020-tux=100
   ```

2. Frontend:

   ```bash
   vercel promote rt-rma-n49rz9qgv-ismaeldarruizbis-projects.vercel.app \
     --scope ismaeldarruizbis-projects
   ```

   Ese despliegue se construyó con la URL y la clave de Oregón. Las variables de producción se devuelven a los valores de Oregón registrados, para que un despliegue futuro no mezcle proyectos.
3. Verificar: 401 sin token, login de los 4 en la interfaz publicada y registros sin errores.

**Reglas:**

- **Sin API abierta:** nunca se vuelve a una revisión sin autenticación (`00017-wer`).
- **Ambas piezas a la vez:** los tokens son de cada proyecto, así que backend y frontend tienen que apuntar al mismo.
- **Datos:** lo creado en São Paulo después del corte no está en Oregón. Antes de volver, se decide si se acepta perderlo o se copia.
- **Contraseñas:** un restablecimiento hecho en un proyecto no llega al otro. Durante los 14 días, restablecer en ambos o en ninguno.
- **Oregón no debe pausarse:** sin tráfico, un proyecto Free se pausa a los 7 días ([pausa de proyectos](https://supabase.com/docs/guides/platform/project-pausing)). Se reanuda desde el panel (hasta un año después), pero eso demora la vuelta atrás.
  - Mitigación: una consulta semanal de solo lectura (`migrar_uat.py comparar`) y una visita al panel.
  - Si aun así se pausa, la vuelta atrás empieza por reanudarlo.

## 12. Riesgos

| Riesgo | Mitigación |
|---|---|
| Credenciales | Contraseñas y claves solo sin eco o en memoria; secreto nuevo con versión fijada; hashes solo en memoria y en el cuerpo HTTPS hacia Auth; nada en el repositorio, los registros ni el disco |
| Formato de hash no aceptado en el proyecto nuevo | Prueba con cuenta descartable en la etapa 3; si falla, la alternativa de contraseñas nuevas |
| Divergencia de datos entre proyectos | Corte con cero Órdenes en Oregón comprobado en el momento; nadie opera durante la ventana; guardas de `maestros` y del reinicio |
| Configuración de Auth distinta | Tabla de la sección 4, revisada pantalla por pantalla, y token ES256 verificado |
| Supavisor | Host del diálogo Connect; usuario `rma_api.<ref>`; `prepare_threshold=None` ya configurado; `instancias × RMA_DB_POOL_MAX` por debajo del límite del plan |
| Certificado distinto del incluido en la imagen | Comparación de huella antes de la revisión |
| Cuota y pausa del plan Free | São Paulo completa la cuota de 2. Oregón se pausa a los 7 días sin actividad: actividad semanal durante el período |
| Costos | Plan Free en ambos: sin costo de Supabase. El Job de medición y el secreto del certificado son descartables |
| Vista previa y CORS | El origen de la vista previa vive solo en la revisión de prueba; el corte usa otra revisión |
| Herramientas probadas solo en local | El primer uso remoto de cada subcomando es sin `--aplicar`, y `comparar` antes y después |

## 13. Decisiones

**Aprobadas (10/11/2026):**

1. Conservar los 4 usuarios, UUID y contraseñas. Método: API de administración con `id` y `password_hash`, verificado en local y sujeto a la prueba de la etapa 3. Si no se puede garantizar, contraseñas nuevas y revinculación.
2. Supabase Free, con la cuota verificada (sección 2).
3. Oregón como vuelta atrás durante 14 días después del corte.
4. Largo mínimo de contraseña 10 y registro público deshabilitado en ambos proyectos.
5. Vista previa de Vercel antes del cambio público.
6. Medición directa de PostgreSQL y de la API.
7. Respaldos conservados hasta terminar la validación.
8. `rma_respaldo_reinicio` no se traslada.

**Pendientes:**

- Confirmar en el panel que la organización está en plan Free.
- Autorizar el Cloud Run Job y el secreto del certificado para la medición directa.
- Al cerrar los 14 días: qué hacer con Oregón, con `rma_respaldo_reinicio` y con la carpeta externa (`uat-reinicio-20261110`, con datos personales).

## 14. Creación del proyecto de São Paulo (etapa 3)

La crea la persona usuaria desde el panel de Supabase. El agente no crea el proyecto ni pide secretos por chat.

### Parámetros

| Campo | Valor |
|---|---|
| Organización | `RosarioTecno` (la de `rt-rma-db`) |
| Plan | Free. Confirmar en *Organization → Billing* que la organización está en Free antes de crear (no se pudo leer por la CLI) |
| Nombre | `db-rt-rma` (ref `pcdnmhzwhzymznojndrn`, `sa-east-1`, creado el 11/11/2026) |
| Contraseña de la base | La genera el panel («Generate a password»). Se guarda solo en el gestor de contraseñas; se usa una vez, para `db push`, y la CLI la pide sin eco |
| Región | **South America (São Paulo), `sa-east-1`**. Es una región específica: elegirla explícitamente, no una región general |
| Cómputo | Nano (el único del plan Free; el mismo que Oregón) |
| Opciones de seguridad | Las mismas que tiene Oregón. Data API con sus valores por defecto: el backend no la usa, `rma` no se expone y `verificar` lo comprueba. Sin habilitar extensiones ni integraciones adicionales |

**Hallazgo (11/11/2026):** el primer proyecto creado, `rt-rma-db-sp` (`kabvqrdztzgjjeysmdsl`), quedó en **`us-east-1`**, no en `sa-east-1`. Es la región general «Americas», que corresponde a Virginia del Norte. Se detuvo la etapa 4 antes de aplicar migraciones; ese proyecto no tiene esquema `rma` ni cuentas. Antes de crear el proyecto, confirmar en el resumen del panel que dice «South America (São Paulo)». Después de crearlo, confirmar con `supabase projects list` que la región es `sa-east-1`.

**Cuota:** con `rt-rma-db` activo, este proyecto completa los 2 permitidos. Si el panel no deja crearlo, no pausar Oregón: avisar.

### Configuración inicial de Auth (antes de cualquier prueba)

1. *Authentication → Sign In / Providers → Email*: habilitado. **«Allow new users to sign up»: desactivado.** «Confirm email»: indistinto, porque las cuentas se crean confirmadas.
2. *Authentication → Password* (o *Policies*): **largo mínimo 10**. El resto de los requisitos, como en Oregón.
3. *Authentication → URL Configuration*: Site URL `https://rt-rma-uat.vercel.app`, sin Redirect URLs adicionales.
4. *Authentication → Rate Limits*: inicios de sesión por IP, igual que Oregón (comparar las dos pantallas).
5. *Project Settings → JWT Keys*: confirmar que la clave de firma vigente es asimétrica **ES256**. La prueba de compatibilidad también lo verifica por JWKS.
6. *Project Settings → API Keys*: ubicar la **clave publicable** (`sb_publishable_…`) y la **clave secreta** (`sb_secret_…`). No copiarlas a archivos, chats ni documentos.

Registrar en el informe de la etapa el *project ref* (es un identificador, no un secreto) y que las seis pantallas coinciden con Oregón.

### Prueba de compatibilidad de Auth

Con el proyecto creado y configurado, y después de autorizarla, la ejecuta la persona usuaria en su terminal, porque la clave secreta no se comparte:

```powershell
# desde la raíz del repositorio
$env:SUPABASE_PUBLISHABLE_KEY_DESTINO = "<clave publicable del proyecto nuevo>"
app\backend\.venv\Scripts\python supabase\scripts\migracion_sp\probar_auth_destino.py --ref <ref nuevo>
```

- Pide la clave secreta sin eco.
- Crea una sola cuenta ficticia (`prueba-hash-<aleatorio>@usuarios.rma.invalid`) y siempre la borra.
- Lee el hash generado por el propio proyecto, en memoria y por la CLI de solo lectura (la sesión de la CLI ya tiene acceso a la organización).
- Recrea la cuenta con otro `id` y ese `password_hash`, inicia sesión con la contraseña original y verifica el token (ES256, `sub` igual al id elegido).

Resultado esperado: «RESULTADO: COMPATIBLE». Si no, se pasa a la alternativa de contraseñas nuevas (sección 4).

### Credenciales y accesos de las etapas siguientes

| Etapa | Necesita | Quién la usa | Cómo |
|---|---|---|---|
| 3 | Clave secreta del proyecto nuevo | Persona usuaria | `getpass` en su terminal |
| 3 y siguientes | Clave publicable del proyecto nuevo | Persona usuaria y agente | Variable de la sesión; no es secreta, pero no se repite en documentos |
| 4 | Contraseña de la base nueva | Persona usuaria | La CLI la pide sin eco en `db push` |
| 4 a 6 | Sesión de la CLI de Supabase (ya iniciada) | Agente | `comparar`, `maestros`, `verificar` y lecturas de solo lectura |
| 5 | Clave secreta del proyecto nuevo, para `cuentas --aplicar` | Persona usuaria | `getpass` en su terminal; el agente prepara el comando |
| 6 | `gcloud` (Secret Manager) y la sesión de la CLI de Supabase | Agente | `generar_credencial_rma_api.cjs`: la contraseña de `rma_api` nunca se muestra |
| 7 a 10 | `gcloud` (Cloud Run) y `vercel` (sesiones ya iniciadas) | Agente | Revisión sin tráfico, vista previa y corte, cada uno con autorización |
| 7 y 11 | Contraseñas de los 4 usuarios (las mismas de hoy) | Persona usuaria | `verificar_uat.py` y `medir_api.py` en su terminal |

## 15. Validación funcional de São Paulo y vuelta a cero Órdenes

Se ejecuta antes del corte, con autorización, solo sobre la revisión `saopaulo---` y el proyecto `pcdnmhzwhzymznojndrn`. El tráfico público sigue en Oregón.

### Recorridos

[`probar_recorridos.py`](../supabase/scripts/migracion_sp/probar_recorridos.py):

- Rechaza cualquier otro destino.
- Exige partir de cero Órdenes y BAT-IP14 10/0.
- Pide las cuatro contraseñas sin eco.

| Recorrido | Qué verifica | Escribe |
|---|---|---|
| A. Permisos | Suplantación por consulta y por cuerpo (403); técnico sin permiso de stock (403); mantenimiento solo Administración (403) | No: los rechazos no dejan rastro |
| B. Reparación completa (HP-REP-001) | Alta con clave de idempotencia y su reintento (misma Orden), recepción, Detalle, comprobante de ingreso, prioridad, toma, inicio con reserva (10/1), cierre con consumo (9/0), control, aviso, pago con clave (reintento sin duplicar y clave reutilizada → 422), check-in, entrega con comprobante final y garantía | Una Orden ENTREGADA; stock 9/0 |
| C. DC31 | Cancelar un Detalle sin cancelar la Orden; cancelación rechazada con el equipo en el local y sin cambios; último Detalle → `SIN_TRABAJOS_VIGENTES`; devolución; cancelación explícita por Coordinación; Orden cerrada sin acciones, rechaza comandos y queda fuera de Inicio y Taller | Una Orden CANCELADA |
| D. Ingreso de stock | Ingreso con clave y su reintento: un solo movimiento; stock vuelve a 10/0 | Un movimiento |

Además informa el tiempo de cada comando, para compararlo con la tabla de `00017-wer`: alta, reintento idempotente, agregar trabajo, comprobante de ingreso, iniciar trabajo, cerrar ejecución, pago, entrega, cancelar e ingreso de stock. Al final lista las Órdenes creadas.

```powershell
# desde la raíz del repositorio
$env:SUPABASE_PUBLISHABLE_KEY_DESTINO = "<clave publicable de São Paulo>"
app\backend\.venv\Scripts\python supabase\scripts\migracion_sp\probar_recorridos.py
```

Esperado: «RESULTADO: TODO OK» y dos Órdenes (`OR-000001` y `OR-000002`).

**Interfaz (opcional), en la vista previa** (`rt-rma-k1qeeu33d-…vercel.app`): inicio de sesión de los 4, Inicio, Taller, Órdenes, Inventario y catálogos. Cualquier Orden creada desde la interfaz se suma a la lista del reinicio. Una foto subida desde la vista previa queda en `gs://rt-rma-uat-fotos/ordenes/<Orden>/`: el bucket es el mismo de Oregón.

### Verificaciones después de los recorridos

Todas son de solo lectura:

- `migrar_uat.py verificar --destino pcdnmhzwhzymznojndrn --sin-rma-api --stock BAT-IP14=10` y `comparar`. Fallan en «cero datos operativos» y en las huellas de stock: es esperado mientras existan las Órdenes de prueba.
- Registros de `00022-vab` sin `ERROR` ni credenciales.
- `00020-tux` con el 100 % del tráfico.

### Vuelta a cero Órdenes en São Paulo

Cada paso se autoriza y se ejecuta solo con `--remote=pcdnmhzwhzymznojndrn`.

1. **Inventario:** listar las Órdenes de São Paulo (solo lectura) y los objetos `gs://rt-rma-uat-fotos/ordenes/OR-*` creados después del inicio de las pruebas.
2. **Guardas de `01_reiniciar.sql`:** poner en `v_ordenes` exactamente esas Órdenes. `v_stock` queda en BAT-IP14 10. Si el esquema `rma_respaldo_reinicio` existe en São Paulo, primero se elimina con `04_eliminar_respaldo.sql`.
3. **Ensayo:** `01_reiniciar.sql` en modo `ensayo` debe terminar en «ENSAYO OK».
4. **Aplicación:** `01_reiniciar.sql` en modo `aplicar`.
   - Respalda las Órdenes de prueba en `rma_respaldo_reinicio`.
   - Vacía las 29 tablas operativas.
   - Reinicia la numeración en OR-000001.
   - Registra de nuevo el ingreso `MST-INICIAL-BAT-IP14` de 10.
   - Verifica la integridad antes de confirmar.
5. **Respaldo:** `04_eliminar_respaldo.sql` en São Paulo, con `v_confirmar = true`. Desde el 11/11 el script es seguro por defecto: sin confirmar solo informa qué eliminaría. El respaldo de las pruebas no se conserva, porque São Paulo no debe tener ese esquema (lo exige `verificar`).
6. **Fotos de prueba:** borrar solo los objetos de las Órdenes de prueba, por nombre explícito y después de inventariarlos.
7. **Comprobación:**
   - `migrar_uat.py verificar` debe dar OK: cero Órdenes, BAT-IP14 10/0, OR-000001, integridad y usuarios.
   - `comparar` contra Oregón debe dar 32 de 32 iguales.
   - `accion_usuario` y `movimiento_inventario` quedan con una fila cada una.

**Qué no cambia:** las cuentas de Auth y los usuarios de RMA no se tocan; el reinicio solo vacía las tablas operativas. La revisión `00022-vab` sigue igual y no hace falta reiniciarla, porque no guarda datos en memoria.

### Resultado de los recorridos (11/11/2026)

`probar_recorridos.py` contra `saopaulo---…` (`00022-vab`): **TODO OK** (informado por la persona usuaria).

- **Recorridos:**
  - las cuatro sesiones;
  - permisos y suplantación;
  - HP-REP-001 completo, con idempotencia de alta y pago, reserva, consumo y reposición de stock, y entrega con garantía;
  - DC31.
- **Tiempos de los comandos:** entre 0,239 y 0,499 s en el cliente. En Oregón, sobre `00017-wer`, fueron de 2,38 a 4,74 s.
- **Órdenes creadas:** `OR-000001` (ENTREGADA, cerrada) y `OR-000002` (CANCELADA, cerrada).

**Estado de São Paulo después de las pruebas** (solo lectura):

- **Integridad y stock:** `verificar_integridad()` vacío; BAT-IP14 10/0, conciliado.
- **Libro de stock:** 4 movimientos, en este orden:
  1. el ingreso inicial de 10;
  2. la reserva de `OR-000001` (10/1);
  3. su consumo (9/0);
  4. el ingreso de prueba de 1 (10/0).
- **Datos operativos:** 129 filas en 19 tablas (entre ellas 70 eventos, 23 acciones, 5 documentos, 2 clientes, 2 equipos, 1 pago y 0 fotos). Secuencia de Órdenes en 2.
- **Usuarios:** los 4, con sus roles y vínculos sin cambios. Auth: 4 cuentas y 6 sesiones de las pruebas, que no se tocan y vencen solas.
- **Registros de `00022-vab`:**
  - sin `ERROR`, sin 5xx, sin credenciales y sin `PERSISTENCIA_RESULTADO_INCIERTO`;
  - los 403, 409 y 422 son los rechazos que el script verifica;
  - el único 400 es una prueba de CORS con un origen ajeno.
- **Fuera de la base:** el bucket de fotos está vacío, así que no hay archivos que borrar. Oregón sigue con cero Órdenes.
- **Respaldo externo de las pruebas:** `%USERPROFILE%\respaldos-rma\sp-pruebas-20261111\` (fuera del repositorio), con 30 tablas, 130 filas y SHA-256. Solo datos ficticios.

### Reinicio de São Paulo preparado (pendiente de aprobación)

`01_reiniciar.sql` tiene `v_ordenes = ['OR-000001', 'OR-000002']` y sigue en modo `ensayo`. Contra Oregón aborta, porque allí no hay Órdenes.

Todos los pasos van con `--remote=pcdnmhzwhzymznojndrn`:

1. **Huella previa** (solo lectura): contenido de las 45 tablas, secuencias, esquemas, Auth y migraciones.
2. **Ensayo:**

   ```bash
   npx -y supabase@3.1.0 db query --yes --remote=pcdnmhzwhzymznojndrn --file supabase/scripts/reinicio_uat/01_reiniciar.sql
   ```

   Debe terminar en «ENSAYO OK (se revierte todo)», y la huella posterior tiene que ser igual a la previa.
3. **Aplicación:** cambiar `v_modo` a `'aplicar'`, ejecutar el mismo comando y volver a dejar `'ensayo'`. Esperado: 0 Órdenes, BAT-IP14 10/0 y numeración 1 (próxima).
4. **Respaldo dentro de la base:** `04_eliminar_respaldo.sql`, con el mismo `--remote`. São Paulo no debe conservar ese esquema; la copia de las pruebas queda en la carpeta externa.
5. **Fotos:** no hay objetos que borrar.
6. **Comprobación:**
   - `migrar_uat.py verificar --destino pcdnmhzwhzymznojndrn` da OK, ya con el chequeo de `rma_api`, que existe desde la etapa 6;
   - `comparar --origen okcscsglnujnxtgobjfw --destino pcdnmhzwhzymznojndrn` da 32 de 32 iguales;
   - `accion_usuario` y `movimiento_inventario` quedan con 1 fila cada una, y la secuencia de Órdenes en 1 sin usar.

**Vuelta atrás:** `02_restaurar.sql`, mientras exista el respaldo en la base, o el JSON externo.

### Reinicio de São Paulo ejecutado (11/11/2026)

1. **Inventario:** igual al de las pruebas: `OR-000001` y `OR-000002`, y 129 filas en 19 tablas.
2. **Huella previa:** 50 elementos (45 tablas, 2 secuencias, esquemas, Auth y migraciones).
3. **Ensayo:** «ENSAYO OK (se revierte todo)»; la huella posterior fue idéntica.
4. **Aplicación:** 0 Órdenes, 0 clientes, BAT-IP14 10/0 conciliado, próxima Orden OR-000001, 4 usuarios activos y vinculados, `verificar_integridad()` vacío. Quedaron 1 acción y 1 movimiento (el ingreso inicial).
5. **Respaldo dentro de la base:** `04_eliminar_respaldo.sql` en São Paulo; quedan 0 esquemas de respaldo. El respaldo externo (`sp-pruebas-20261111`) se conserva.
6. `01_reiniciar.sql` volvió al modo `ensayo`.

**Equivalencia final:**

- `verificar` con `rma_api`: **9/9 OK**.
- `comparar` contra Oregón: **32/32 iguales**.
- **Auth:** 4 cuentas, mismo id y email que Oregón, confirmadas y con identidad `email`; ninguna ficticia.

## 16. Corte coordinado y vuelta atrás

### Estado listo para el corte (11/11/2026)

| Pieza | Oregón (público hoy) | São Paulo (preparado) |
|---|---|---|
| Base y Auth | `okcscsglnujnxtgobjfw` | `pcdnmhzwhzymznojndrn`, equivalente 32/32, cero Órdenes, BAT-IP14 10/0 |
| Cloud Run | `rt-rma-uat-api-00020-tux`, etiqueta `auth`, **100 %** | **`rt-rma-uat-api-00023-zus`**, etiqueta `corte`, 0 % |
| Frontend | `rt-rma-n49rz9qgv…` (producción) | Variables de producción por cambiar en el corte |

**Revisión definitiva `00023-zus`:**

- misma imagen que `00020-tux` (`sha256:71e47d…`, código `61e2a14`);
- `RMA_DATABASE_URL` desde `rma-uat-sp-database-url:1`, `RMA_AUTH_SUPABASE_URL=https://pcdnmhzwhzymznojndrn.supabase.co`, `verify-full` con la CA de la imagen;
- `RMA_CORS_ALLOW_ORIGINS=["https://rt-rma-uat.vercel.app"]`: sin el origen de la vista previa;
- sin referencias a Oregón;
- salud 200 y 401 sin token o con token inválido; CORS solo para producción;
- arranque limpio.

**De prueba:**

- `00022-vab` (etiqueta `saopaulo`): admite además el origen de la vista previa. No es la revisión del corte.
- Vista previa `rt-rma-k1qeeu33d-…vercel.app`, construida contra `saopaulo---`:
  - carga;
  - configuración exclusiva de São Paulo;
  - sin claves secretas;
  - CORS aceptado desde su origen.

  **Pendiente de validación manual:** la pantalla de acceso, porque la vista previa exige la sesión de Vercel. Servida localmente, la app arranca y consulta `saopaulo---…/health`, que desde `localhost` rechaza CORS, como corresponde.

**Hallazgo (11/11/2026, después del reinicio):** São Paulo tiene una Orden, `OR-000001`.

- **Qué es:** abierta, sin Detalles, cliente sin la marca «PRUEBA». La creó `RECEP-001` a las 03:57:41 UTC, desde la vista previa (`00022-vab`), 40 s después de iniciar sesión.
- **Cómo se interpreta:** es la validación manual de la vista previa, que además confirma que allí funciona el acceso.
- **Pendiente:** antes del corte, decidir si se conserva o se repite el reinicio, con `v_ordenes = ['OR-000001']`.

### Antes del corte (solo lectura)

1. `migrar_uat.py verificar --destino pcdnmhzwhzymznojndrn` OK y `comparar` 32/32.
2. Oregón con cero Órdenes. Si hubiera Órdenes nuevas, decidir antes si se pierden o se trasladan.
3. Tráfico: `00020-tux` 100 %.
4. Ventana anunciada; nadie opera en UAT.

### Corte (cada paso con autorización, en este orden)

1. **Variables de producción de Vercel** (no cambian el despliegue publicado):
   - registrar los valores actuales;
   - reemplazar `VITE_SUPABASE_URL` por `https://pcdnmhzwhzymznojndrn.supabase.co`;
   - reemplazar `VITE_SUPABASE_PUBLISHABLE_KEY` por la clave publicable de São Paulo, tomada de `supabase projects api-keys`, tipo `publishable`.

   `VITE_API_BASE_URL`, `VITE_AUTH_MODO` y `VITE_AUTH_DOMINIO_USUARIOS` no cambian.

   ```bash
   vercel env rm VITE_SUPABASE_URL production --yes --scope ismaeldarruizbis-projects
   vercel env add VITE_SUPABASE_URL production --scope ismaeldarruizbis-projects < <archivo temporal>
   # igual para VITE_SUPABASE_PUBLISHABLE_KEY
   ```

   En Windows la tubería falla: el valor va en un archivo temporal del directorio de la sesión, que se borra enseguida.
2. **Tráfico del backend:**

   ```bash
   gcloud run services update-traffic rt-rma-uat-api --region southamerica-east1 \
     --project rosariotecno-460217 --to-revisions rt-rma-uat-api-00023-zus=100
   ```

3. **Enseguida, frontend**, desde una exportación limpia de `61e2a14`, sin `.env.local` (Root Directory `app/frontend`):

   ```bash
   vercel deploy --prod --yes --scope ismaeldarruizbis-projects
   ```

   Entre los pasos 2 y 3 el frontend publicado todavía envía tokens de Oregón y recibe 401: las sesiones vuelven a la pantalla de acceso.

### Después del corte

- API pública: salud 200; 401 sin token y con token de Oregón; 200 con token de São Paulo (`probar_entornos.py` adaptado a la URL pública, o `medir_api.py`).
- Bundle de producción con `pcdnmhzwhzymznojndrn` y sin `okcscsglnujnxtgobjfw`.
- Inicio de sesión de los 4 en `rt-rma-uat.vercel.app`: la misma contraseña, una sola vez.
- Inicio y Taller vacíos; Inventario 10.
- Registros de `00023-zus` sin errores.

### Vuelta atrás a Oregón (hasta 14 días después del corte)

Backend y frontend juntos: los tokens son de cada proyecto.

```bash
gcloud run services update-traffic rt-rma-uat-api --region southamerica-east1 \
  --project rosariotecno-460217 --to-revisions rt-rma-uat-api-00020-tux=100
vercel promote rt-rma-n49rz9qgv-ismaeldarruizbis-projects.vercel.app --scope ismaeldarruizbis-projects
```

Después, devolver las dos variables de producción de Vercel a los valores de Oregón registrados.

- **Sin API abierta:** nunca se usa `00017-wer`.
- **Datos:** lo creado en São Paulo después del corte no está en Oregón.
- **Contraseñas:** restablecer en ambos proyectos o en ninguno.

### Pendientes del corte

1. Validación manual de la pantalla de acceso en la vista previa, o directamente en producción después del corte.
2. **Durante los 14 días:**
   - actividad semanal de solo lectura en Oregón y una visita al panel, para que el plan Free no lo pause;
   - conservar la etiqueta `auth` de `00020-tux`.
3. **Después del corte:**
   - quitar la etiqueta `saopaulo` (`00022-vab`, que admite el origen de la vista previa) con `update-traffic --remove-tags saopaulo`;
   - borrar la vista previa `rt-rma-k1qeeu33d`;
   - revisar el costo de las revisiones sin tráfico con mínimo 1 instancia.
4. **Al cerrar los 14 días:** decidir sobre Oregón (pausa o eliminación), `rma_respaldo_reinicio` en Oregón y las carpetas externas. `uat-reinicio-20261110` contiene datos personales; `sp-pruebas-20261111`, solo datos ficticios.
5. Commit de los scripts, los tests y la documentación (sin commit, por indicación).
