# Checkpoint pre-deploy (06/11/2026)

> **Sustituido** por [`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md): E8 y E9 ya se completaron. Este archivo queda como registro histórico; su sección 7 conserva el script de la base `rma_dev`.

Punto de retorno para continuar desde otra computadora con **E8** (Supabase DEV/UAT) y después **E9** (Cloud Run). Resume y enlaza; las fuentes de verdad siguen siendo [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md) y [`postgresql/`](postgresql/README.md).

## 1. Rama y commits

- Rama: `feat/postgresql-esquema` (publicada en `origin`, sin merge).
- Commits de este cierre, sobre `b84b87a` (Bloque B):
  - `fe655d7` feat(frontend): rediseño con sidebar, barra de acciones, modales y pendientes.
  - `2444773` feat(postgres): preparar E8 (conexión remota habilitable y permisos de `rma_backend`).
  - El commit de documentación que agrega este archivo es el último de la rama: `git log -1`.
- Sin migraciones remotas, sin deploy y sin cambios en Supabase, Cloud Run ni Vercel.

## 2. Estado

| Tema | Estado |
|---|---|
| E0–E3 | Completadas y con commit |
| E4–E7 (Bloques A y B) | Completadas y probadas localmente (`bd59bd3`, `b84b87a`). La app corre sobre PostgreSQL local, con los datos persistentes entre reinicios |
| Frontend | Rediseñado (`fe655d7`): layout con sidebar, barra superior con las acciones habilitadas y «Más acciones», operaciones en modales, sección «Pendientes». Sin cambios de reglas, permisos, endpoints ni idempotencia |
| Pruebas del frontend | 95 tests (`npm test`) aprobados y TypeScript (`npm run typecheck`) sin errores. Un recorrido funcional local verificado (navegación, modal, alta de un trabajo, inventario y vista de celular) |
| PostgreSQL local | Funciona (`rma_dev`, sección 7) |
| Supabase DEV/UAT | Solo el esquema inicial. **Ninguna migración nueva aplicada** |
| E8 | Preparada: procedimiento en [`postgresql/e8-activacion-supabase.md`](postgresql/e8-activacion-supabase.md) e inspección de solo lectura hecha (sección 3) |
| E9 | No iniciada; requiere su propia aprobación |

**No hay datos operativos históricos que migrar.** DEV/UAT no tiene Órdenes, clientes, pagos ni movimientos. **Los catálogos remotos existentes se conservan**: los 5 medios de pago y los 36 modelos técnicos de equipo. Nunca `db reset` ni recrear la base.

## 3. Inspección de DEV/UAT (E8, solo lectura)

Hecha el 06/11/2026 con [`supabase/scripts/inspeccionar_e3.py`](../supabase/scripts/inspeccionar_e3.py) (cada consulta en una transacción `READ ONLY`, sin datos personales ni la cadena de conexión). Proyecto GCP `rosariotecno-460217`, secreto `rma-uat-database-url`.

- **Conexión:** usuario `rma_api` por el pooler, TLS `verify-full` con la CA de Supabase incluida en la app (`app/backend/app/datos/`).
- **Rol:** `rma_api` no es superusuario, hereda (`rolinherit`), sin `BYPASSRLS`, `CREATEROLE` ni `CREATEDB`; miembro de `rma_backend`.
- **Privilegios efectivos:** `UPDATE` en `orden` y en `insumo.activo`; `INSERT` en el libro de inventario. Sin `UPDATE` de `insumo.stock_fisico`, sin `DELETE` en el libro ni en `orden`, sin `TRUNCATE` de `pago`, sin `CREATE` en el esquema. Tiene `TEMP` (pendiente «Privilegios»).
- **Datos:** `insumo` 0, `usuario` 0, `medio_pago` 5, `modelo_equipo` 36; tipos de reparación, mesas, clientes, equipos, Órdenes, pagos, fotos, movimientos y acciones en 0.
- **Esquema:** ninguna columna de E3 a E6 presente (`insumo.clave`, `usuario.orden`, `medio_pago.orden`, `recepcion_version.posicion`, `pago.operacion_id`, `movimiento_inventario.posicion`, `accion_usuario.huella`).
- `rma_api` no puede leer `supabase_migrations.schema_migrations`: confirmar la lista de migraciones aplicadas con `supabase migration list` antes de aplicar.

**Resultado:** se puede aplicar E3 con el script único transaccional. Como `medio_pago` tiene filas, la guarda de E3 (QAF-13) exige la autorización en la sesión (`set local`); al no haber insumos ni usuarios, no hay identidades de insumo previas en conflicto (QAF-12 no aplica).

## 4. Migraciones remotas pendientes (en orden)

1. `20261105000100_e3_catalogos.sql`: **procedimiento seguro de E3** ([`postgresql/integracion-pendientes.md`](postgresql/integracion-pendientes.md), «Procedimiento seguro de la migración de E3»). Un script con `psql -v ON_ERROR_STOP=1 --single-transaction` y `set local rma.migracion_e3 = 'estrategia_identidad_aprobada'`, después `supabase migration repair --status applied 20261105000100`. **Pendiente de ejecución y de autorización.**
2. `20261106000100_e4_agregado.sql`
3. `20261106000200_e4_recepcion_documentos.sql`
4. `20261106000300_e4_finanzas.sql`
5. `20261106000400_e5_reservas.sql`
6. `20261106000500_e5_movimientos.sql`
7. `20261107000100_e6_idempotencia.sql`

Condiciones previas y verificaciones de cada una: [`postgresql/e8-activacion-supabase.md`](postgresql/e8-activacion-supabase.md), sección 1.

## 5. Fotos y catálogo de Ventas

- **Fotos:** persistidas en el bucket privado de GCS (`RMA_FOTOS_BUCKET`); la base guarda la clave del objeto.
- **Catálogo de Ventas:** copia JSON efímera en Cloud Run, reconstruible desde Google Sheets con `POST /api/catalogs/equipment/sync`. **La sincronización automática al arrancar está pendiente** (cambio pequeño, a autorizar); hasta entonces, Administración sincroniza después de cada despliegue o reinicio.

## 6. Pruebas pendientes y riesgos abiertos

**Pruebas antes del deploy:** suites completas PostgreSQL y JSON del backend (no se corrieron en este cierre), `verificar_integridad()` vacío en DEV/UAT después de migrar, y el recorrido de humo de E8 (sección 5 del procedimiento).

**Riesgos abiertos** (detalle en [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), sección E):
- Procedimiento de E3 en remoto (QA-E3-6, QA-E3-7, QAF-5, QAF-13): `orden` de usuarios y medios de pago, y la carga de los catálogos que faltan en DEV/UAT.
- Privilegios heredados de `PUBLIC` (`TEMP`, funciones de sesión) sin política todavía.
- QA-E3-4: resuelto para la app (una unidad de trabajo por pool), a confirmar desde Cloud Run.
- Latencia Cloud Run (São Paulo) – Supabase (Oregón): sin medir (p50/p95 en E8).
- Catálogo de Ventas efímero sin sincronización automática.
- Frontend: los botones de «Pendientes» abren solo acciones que el usuario ya puede ejecutar; la carga real de fotos y los movimientos de inventario no se recorrieron en el navegador después del rediseño.

## 7. Levantar el entorno local en otra computadora

Requisitos: Git, Python 3.11+, Node.js. Comandos para Git Bash.

```bash
git clone https://github.com/IsmaelDarruizBI/rt-rma-mvp.git
cd rt-rma-mvp && git switch feat/postgresql-esquema
npm install

cd app/backend
python -m venv .venv && source .venv/Scripts/activate   # Linux/macOS: .venv/bin/activate
pip install -e ".[dev,postgres]"
cd ../frontend && npm install && cd ../..
```

**PostgreSQL 17 local** (fuera del repositorio, puerto 54329):

```bash
mkdir ~/pg-rma && cd ~/pg-rma && npm init -y
npm install embedded-postgres@17.10.0-beta.17
BIN=$(ls -d node_modules/@embedded-postgres/*/native/bin)
"$BIN/initdb" -D data -U postgres -A trust -E UTF8 --locale=C
"$BIN/pg_ctl" -D data -o "-p 54329 -c listen_addresses=127.0.0.1" -l pg.log -w start
```

**Base `rma_dev`** (migraciones y carga de desarrollo, con los helpers de las pruebas), desde `app/backend`:

```bash
.venv/Scripts/python - <<'EOF'
import psycopg
from psycopg import sql
from tests.postgres.base_local import ROLES_SUPABASE, archivos_sql, url_admin_local
admin = url_admin_local("postgresql://postgres@127.0.0.1:54329/postgres")
with psycopg.connect(admin, autocommit=True) as a:
    for rol in ROLES_SUPABASE:
        if not a.execute("select 1 from pg_roles where rolname=%s", (rol,)).fetchone():
            a.execute(sql.SQL("create role {} nologin").format(sql.Identifier(rol)))
    a.execute("drop database if exists rma_dev with (force)")
    a.execute("create database rma_dev")
with psycopg.connect("postgresql://postgres@127.0.0.1:54329/rma_dev", autocommit=True) as c:
    for archivo in archivos_sql():
        c.execute(archivo.read_text(encoding="utf-8"))
EOF
```

**Backend** sobre PostgreSQL local, desde `app/backend`:

```bash
export RMA_PERSISTENCIA=postgres
export RMA_DATABASE_URL=postgresql://postgres@127.0.0.1:54329/rma_dev
export RMA_DATA_DIR=$HOME/rma-data RMA_FOTOS_DIR=$HOME/rma-data/fotos
mkdir -p "$RMA_FOTOS_DIR"
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Frontend**, desde `app/frontend`: `npm run dev` (http://localhost:5173; `VITE_API_BASE_URL` según `.env.example`). Usuarios de prueba: `recepcion`, `tecnico`, `coordinacion`, `administracion`.

**Pruebas:** `npm test` y `npm run typecheck` (frontend); `pytest` y `ruff check .` (backend); la suite PostgreSQL según [`postgresql/CHECKPOINT_A4_HANDOFF.md`](postgresql/CHECKPOINT_A4_HANDOFF.md), sección 11.

## 8. Próximo paso

**E8, con autorización explícita para cada paso remoto:**
1. Confirmar con `supabase migration list` las 12 migraciones aplicadas y repetir las verificaciones de solo lectura de la sección 1 del procedimiento E8.
2. Preparar y probar en `rma_dev` (o una copia local con los mismos catálogos) el script único de E3, y aprobar por escrito la estrategia de identidad.
3. Aplicar E3 con ese script y las seis migraciones restantes en orden; `verificar_integridad()` vacío.
4. Medir latencia p50/p95 por comando desde una máquina local.

**Después, E9** (con aprobación aparte): revisión de Cloud Run sin tráfico con las variables del procedimiento E8, recorrido de humo y paso del tráfico.
