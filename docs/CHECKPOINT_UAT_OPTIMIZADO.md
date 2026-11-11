# Checkpoint: UAT sobre PostgreSQL, optimizado (09/11/2026)

> **Estado superado (11/11/2026).** Las secciones 1 a 3 describen el UAT del 06 al 09/11: sin autenticación, en `00017-wer` y con Órdenes ficticias. Hoy el UAT tiene autenticación y DC31 (`00020-tux`), está en cero Órdenes y tiene São Paulo listo para el corte.
>
> - **Estado vigente:** [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md).
> - **Despliegue, corte y vuelta atrás:** [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16. La vuelta atrás de la sección 2 de este documento ya no aplica: `00012-d4z` y `00017-wer` no tienen autenticación.
> - **Siguen vigentes:** las secciones 4 a 7 (pendientes, entorno local y consultas de solo lectura).

Punto de retorno para continuar en otra computadora o en una sesión nueva. Sustituye a [`CHECKPOINT_PRE_DEPLOY.md`](CHECKPOINT_PRE_DEPLOY.md). Las fuentes de verdad de cada tema siguen siendo las de la tabla de [`AGENTS.md`](../AGENTS.md); este documento resume y enlaza.

## 1. Estado técnico

| Tema | Estado |
|---|---|
| Migración a PostgreSQL | E0 a E9 completadas ([`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), sección C) |
| Esquema en Supabase | 19 de 19 migraciones aplicadas en `rt-rma-db`; `verificar_integridad()` vacío |
| Backend | FastAPI en Cloud Run con `RMA_PERSISTENCIA=postgres`. Sin modo mixto: los datos de PostgreSQL no vuelven a JSON |
| Frontend | React y Vite en Vercel, publicado por CLI |
| Fotos | Bucket privado de GCS `rt-rma-uat-fotos` (`southamerica-east1`); la base guarda la clave del objeto. No ejecutar `/photos/cleanup` con `aplicar`: el bucket conserva fotos anteriores a PostgreSQL |
| Catálogo de Ventas | Copia efímera en Cloud Run, desde Google Sheets (`RMA_CATALOGO_ORIGEN=google_sheets`). Se reconstruye con `POST /api/catalogs/equipment/sync?usuario_id=…`; la sincronización automática está pendiente |
| Autenticación | **No existe.** El login es demo y valida credenciales ficticias en el frontend. La API pública de Cloud Run acepta pedidos sin autenticar; CORS solo limita navegadores |
| Datos de UAT | Solo ficticios: Órdenes `OR-000001` a `OR-000006` y `OR-000009`, todas entregadas o canceladas. La secuencia saltó 7 y 8 por un rollback forzado. Stock de `INS-001`: 2 físico y 0 reservado |

**Límite de UAT:** sin autenticación real no se cargan datos de clientes.

## 2. Identificación del despliegue

Verificado el 06/11/2026 con `gcloud`. El 09/11 la credencial de `gcloud` estaba vencida y solo se confirmó lo público: `/health` y el frontend respondían `200`, y el bundle apuntaba al backend de abajo. Revalidar con la sección 6 antes de actuar sobre la infraestructura.

| Elemento | Valor |
|---|---|
| Rama | `feat/postgresql-esquema` (sin merge; `mvp-v2` es la rama de producción de Vercel) |
| HEAD | `git log -1`: el commit que agrega este archivo, de solo documentación |
| Backend construido desde | `3249a0a`: el código es el de `c21f289` y `750756c` |
| Cloud Run | Servicio `rt-rma-uat-api`, proyecto `rosariotecno-460217`, región `southamerica-east1`. Revisión `rt-rma-uat-api-00017-wer`, con etiqueta `commit=3249a0a` y el 100 % del tráfico (`LATEST`) |
| Escala | Instancias mínimas y máximas en 1, con CPU boost al arrancar. Una sola instancia, porque el catálogo de Ventas y el limitador por DNI son locales |
| Backend | https://rt-rma-uat-api-20178227259.southamerica-east1.run.app; también responde en `https://rt-rma-uat-api-nszqooxxla-rj.a.run.app` |
| Frontend | https://rt-rma-uat.vercel.app. Proyecto `rt-rma-uat` (equipo `ismaeldarruizbis-projects`, Root Directory `app/frontend`); despliegue de producción `rt-rma-396g7s2aq…`, construido desde `3249a0a` |
| Supabase | Proyecto `rt-rma-db` (ref `okcscsglnujnxtgobjfw`), región `us-west-2` (Oregón). La app entra con el rol `rma_api`, miembro de `rma_backend`, por el pooler en modo transacción y con TLS `verify-full` |

**Variables de Cloud Run, sin valores secretos.** `RMA_PERSISTENCIA=postgres`, `RMA_DB_REMOTO_HABILITADO=true`, `RMA_DB_POOL_MIN=1`, `RMA_DB_POOL_MAX=4`, `RMA_CORS_ALLOW_ORIGINS=["https://rt-rma-uat.vercel.app"]`, `RMA_FOTOS_BUCKET=rt-rma-uat-fotos` y `RMA_CATALOGO_*` (Google Sheets, credencial `cloud_run`).

**Secreto `RMA_DATABASE_URL`.** Sale de Secret Manager (`rma-uat-database-url`) en la versión **`:latest`**, y lo leen todas las revisiones, incluida la de rollback. Por eso, **para otra base se crea un secreto nuevo**: una versión nueva de este secreto movería también la revisión anterior. Nunca imprimir el valor; la contraseña local va en `app/backend/.env`, que está ignorado.

### Vuelta atrás segura

- **Backend:**
  - `gcloud run services update-traffic rt-rma-uat-api --region southamerica-east1 --project rosariotecno-460217 --to-revisions rt-rma-uat-api-00012-d4z=100`.
  - `00012-d4z` (commit `17bf69a`) usa la misma base y el mismo esquema: la optimización no cambió migraciones.
  - Para volver a seguir la última revisión: `--to-latest`.
  - `00010-pgz` es la revisión en JSON: no sirve como rollback, porque no ve los datos de PostgreSQL.
- **Frontend:**
  - `vercel rollback` o `vercel promote` hacia el despliegue de producción anterior, `rt-rma-38o0gmck4…`.
  - El frontend nuevo funciona con cualquiera de las dos revisiones del backend.
- Cada cambio de tráfico o de despliegue requiere una autorización explícita ([`AGENTS.md`](../AGENTS.md)).

## 3. Rendimiento (medido en UAT el 06/11/2026)

| Grupo | Antes (`00012-d4z`) | Después (`00017-wer`) |
|---|---|---|
| Lecturas (listado, Orden, Inicio, Taller, Inventario) | 4,5 a 13,5 s | **0,95 a 1,18 s** |
| Comandos (alta, pago, entrega, ingreso de stock, etc.) | 3,9 a 15,6 s | **2,4 a 4,7 s** |

- **Causa:** cada viaje de Cloud Run (São Paulo) a Supabase (Oregón) cuesta unos 177 ms, y las consultas en sí, unos 0,1 ms.
- **Optimización:** varias consultas por envío (modo pipeline de psycopg), una transacción `READ ONLY` por pantalla, bloqueo y carga de una Orden en un solo envío, y eventos insertados en lote. No cambiaron reglas, bloqueos, idempotencia ni atomicidad.
- **Frontend:** los comandos ya no recargan el listado, el buscador espera 300 ms y las pantallas muestran los últimos datos mientras se actualizan.
- **Pool:** `RMA_DB_POOL_MIN=1`, máximo 4. La primera ráfaga después de un rato sin uso espera conexiones nuevas: 2,2 s contra 0,7 s con 4.
- **Lecturas:** tardan 2 viajes más de lo esperado desde que el pool tiene varias conexiones. La causa no está confirmada.
- **Volumen:** `GET /api/orders` y el detalle de un insumo cargan todas las Órdenes, y no hay paginación. Solo se probó con 7 Órdenes.

Tabla completa por operación, viajes SQL y verificaciones: [`postgresql/integracion-pendientes.md`](postgresql/integracion-pendientes.md), «Resultado en UAT».

## 4. Pendientes prioritarios

1. **Autenticación y autorización reales** en la API y el frontend, antes de usar datos de clientes.
2. **Latencia de los comandos:** evaluar Supabase en São Paulo. El plan está en [`postgresql/integracion-pendientes.md`](postgresql/integracion-pendientes.md), «Alternativa: Supabase nuevo en São Paulo»; no se ejecutó.
3. **Secreto nuevo** para cualquier base futura. El actual, `rma-uat-database-url:latest`, no se toca.
4. **Conexiones:** decidir `RMA_DB_POOL_MIN`; con 4 se evita la espera de la primera ráfaga. Investigar los 2 viajes de más en las lecturas en lote.
5. **Sincronización automática** del catálogo de Ventas al arrancar.
6. **Paginación** de `GET /api/orders` y del detalle de un insumo; limitar las reservas a las pendientes.
7. **Frontend:** verificar pagos, entregas y fotos desde la interfaz. Hasta ahora se probaron por API; en el navegador solo se probaron alta, cancelación y navegación.
8. **Respuesta perdida:** el 06/11, en `00012-d4z`, un pago se registró (`200` en Cloud Run) pero la respuesta no llegó al cliente. La idempotencia evita duplicados si se reintenta con la misma clave. Revisar si se repite y cómo lo informa el frontend.
9. **Datos ficticios de UAT:** definir si se conservan, se marcan o se limpian, sin borrar las fotos del bucket.

## 5. Continuidad: entorno local

Requisitos: Git, Python 3.11 o posterior, Node.js. Comandos para Git Bash.

```bash
git clone https://github.com/IsmaelDarruizBI/rt-rma-mvp.git
cd rt-rma-mvp && git switch feat/postgresql-esquema
npm install                                   # tooling de business/

cd app/backend
python -m venv .venv && source .venv/Scripts/activate   # Linux/macOS: .venv/bin/activate
pip install -e ".[dev,postgres]"
cd ../frontend && npm install && cd ../..
```

**PostgreSQL 17 local,** fuera del repositorio, en el puerto 54329:

```bash
mkdir ~/pg-rma && cd ~/pg-rma && npm init -y
npm install embedded-postgres@17.10.0-beta.17
BIN=$(ls -d node_modules/@embedded-postgres/*/native/bin)
"$BIN/initdb" -D data -U postgres -A trust -E UTF8 --locale=C     # solo la primera vez
"$BIN/pg_ctl" -D data -o "-p 54329 -c listen_addresses=127.0.0.1" -l pg.log -w start
```

**Base `rma_dev`** para levantar la app: script de [`CHECKPOINT_PRE_DEPLOY.md`](CHECKPOINT_PRE_DEPLOY.md), sección 7. Crea los roles de Supabase y aplica las migraciones y la carga de desarrollo.

**Backend sobre PostgreSQL local,** desde `app/backend`:

```bash
export RMA_PERSISTENCIA=postgres
export RMA_DATABASE_URL=postgresql://postgres@127.0.0.1:54329/rma_dev
export RMA_DATA_DIR=$HOME/rma-data RMA_FOTOS_DIR=$HOME/rma-data/fotos
mkdir -p "$RMA_FOTOS_DIR"
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Frontend,** desde `app/frontend`: `npm run dev`, en http://localhost:5173. `VITE_API_BASE_URL` sale de `.env.example` (`http://localhost:8000`). Usuarios demo: `recepcion`, `tecnico`, `coordinacion` y `administracion`.

**Pruebas focalizadas** (no correr suites completas sin pedirlo):

```bash
# app/backend
ruff check .
RMA_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:54329/postgres \
  .venv/Scripts/python -m pytest tests/postgres/test_ejecutor_sql.py tests/postgres/test_consultas_postgres.py -q
# app/frontend
npm run typecheck && npm test
```

`RMA_TEST_DATABASE_URL` se rechaza si no apunta a un servidor local. Si la tarea toca `business/`, `specs/` o `traceability/`, también `npm run validate:all` desde la raíz.

## 6. Continuidad: consultar UAT (solo lectura)

Las autenticaciones las hace la persona usuaria (`gcloud auth login`, `vercel login`, `supabase login`); un agente no las ejecuta.

```bash
R="--region southamerica-east1 --project rosariotecno-460217"
gcloud run services describe rt-rma-uat-api $R --format='yaml(status.traffic,status.latestReadyRevisionName)'
gcloud run revisions list --service rt-rma-uat-api $R --limit 5 --format='table(metadata.name,metadata.labels.commit,status.conditions[0].status)'
vercel ls rt-rma-uat --scope ismaeldarruizbis-projects
curl -s https://rt-rma-uat-api-20178227259.southamerica-east1.run.app/health
```

- **Migraciones:** `npx supabase migration list --linked`, con la CLI de Supabase vinculada a `okcscsglnujnxtgobjfw`. Deben aparecer 19 de 19.
- **Integridad:** correr `rma.verificar_integridad()` con el rol de la app, en una transacción `READ ONLY`. El rol de solo lectura de la CLI no tiene `EXECUTE`.
- **Despliegues** (solo con autorización). La configuración de Cloud Run está en [`postgresql/e8-activacion-supabase.md`](postgresql/e8-activacion-supabase.md), sección 3. Los comandos probados el 06/11:
  - **Backend:** desde una exportación limpia de `HEAD:app/backend` (`git archive`, sin `.env`), `gcloud run deploy rt-rma-uat-api --source <carpeta> $R --no-traffic --tag <etiqueta> --update-labels commit=<sha> --quiet`. Después, el recorrido de humo sobre la URL de la etiqueta, `gcloud run services update-traffic rt-rma-uat-api $R --to-latest` y `--remove-tags <etiqueta>`.
  - **Frontend:** `vercel deploy --prod --yes` desde una exportación del repositorio **completo**, porque el proyecto tiene Root Directory `app/frontend`. `vercel link` crea un `.env.local` con un token: borrarlo antes de desplegar.

## 7. Cómo retomar sin exploración general

1. Leer [`AGENTS.md`](../AGENTS.md), este archivo y la sección F de [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md).
2. `git status`, `git branch --show-current`, `git log --oneline -5`.
3. Elegir un pendiente de la sección 4 y pedir la autorización explícita de su alcance. Todo push, deploy o cambio en Cloud Run, Vercel, Supabase o secretos se autoriza aparte.
