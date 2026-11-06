# E8: activación de PostgreSQL en Supabase DEV/UAT

Procedimiento para activar la persistencia PostgreSQL en DEV/UAT. **Requiere autorización explícita** para cada paso remoto. No contiene secretos: las credenciales viven en GCP Secret Manager.

Estado, decisiones y riesgos: [`ESTADO_PROYECTO.md`](../ESTADO_PROYECTO.md), [`integracion-pendientes.md`](integracion-pendientes.md) y el [diseño E4–E7](e4-e7-diseno-integrado.md).

## 1. Migraciones pendientes en Supabase

DEV/UAT tiene aplicadas las 12 primeras (`20261102000100` a `20261102001200`). Faltan siete, a aplicar en este orden:

| Migración | Contenido | Condición previa |
|---|---|---|
| `20261105000100_e3_catalogos.sql` | `insumo.clave`, `orden` de usuarios y medios de pago | **Bloqueante:** procedimiento seguro de E3 ([`integracion-pendientes.md`](integracion-pendientes.md), «Procedimiento seguro de la migración de E3»): estrategia de identidad aprobada, inventario de solo lectura de `insumo`, `usuario` y `medio_pago`, y script probado sobre una copia |
| `20261106000100_e4_agregado.sql` | A0: acción técnica, numeración, medios de pago como filas | `orden_cerrada_con_fecha` se agrega sin `NOT VALID` (QA-A2-L5): ninguna Orden cerrada sin fecha |
| `20261106000200_e4_recepcion_documentos.sql` | A4: posiciones, `plantilla_version` opcional | — |
| `20261106000300_e4_finanzas.sql` | A3: `operacion_id`, posiciones, `v_orden_saldo` | — |
| `20261106000400_e5_reservas.sql` | A6: `ejecucion_insumo.posicion NOT NULL`, triggers con `FOR NO KEY UPDATE` | Ninguna fila de `ejecucion_insumo` sin `posicion` (DEV/UAT no tienen Órdenes) |
| `20261106000500_e5_movimientos.sql` | A7: DI-8, `operacion_id` y `secuencia` del libro | Ningún `motivo_texto` vacío en `movimiento_inventario` |
| `20261107000100_e6_idempotencia.sql` | B1: `accion_usuario.huella` | — |

**Verificaciones de solo lectura antes de aplicar** (con autorización para leer):

```sql
select count(*) from rma.orden;                                   -- 0 esperado
select count(*) from rma.ejecucion_insumo;                        -- 0 esperado
select count(*) from rma.movimiento_inventario
 where motivo_texto is not null and btrim(motivo_texto) = '';     -- 0 esperado
select codigo, nombre from rma.insumo order by codigo;            -- inventario E3
select codigo, nombre from rma.usuario order by codigo;
select codigo, nombre from rma.medio_pago order by codigo;
```

Aplicación: primero la de E3 con su script único (`psql -v ON_ERROR_STOP=1 --single-transaction`) y `supabase migration repair --status applied 20261105000100`; después las seis restantes en orden, cada una en su transacción. Nunca `db reset` ni recrear la base.

## 2. Rol de la aplicación

- La API conecta con `rma_api` (rol de login, miembro de `rma_backend`), nunca con `postgres`.
- Permisos de `rma_backend` (migración `20261102001100_acceso.sql`): `SELECT` en todo `rma`; `INSERT` en las tablas operativas; `UPDATE` solo en estado actual y catálogos, y por columna en `insumo`, `documento_cliente`, `pago` y `accion_usuario`; sin `DELETE` salvo `usuario_rol`; sin `TRUNCATE`. Las migraciones posteriores no crean tablas; la secuencia nueva de A7 tiene su `GRANT`.
- Verificado localmente (`tests/postgres/test_permisos_rma_backend.py`): con un rol de login miembro de `rma_backend` corren todos los recorridos reales, con los bloqueos `FOR UPDATE`/`FOR NO KEY UPDATE`, `ON CONFLICT` e idempotencia, y se rechazan `DELETE`, `TRUNCATE` y reescribir pagos o stock.
- Antes de E8: confirmar en Supabase que `rma_api` hereda de `rma_backend`, no es superusuario ni tiene `BYPASSRLS` (pendiente «Privilegios»: `TEMP` y funciones heredadas de `PUBLIC`).

## 3. Configuración de Cloud Run

| Variable | Valor | Origen |
|---|---|---|
| `RMA_PERSISTENCIA` | `postgres` | Variable |
| `RMA_DATABASE_URL` | `postgresql://rma_api:…@<pooler>:6543/postgres?sslmode=verify-full` | **Secret Manager** (ya creado) |
| `RMA_DB_REMOTO_HABILITADO` | `true` | Variable. Sin ella la app rechaza una URL remota |
| `RMA_DB_SSLROOTCERT` | sin definir: usa la CA de Supabase incluida en la imagen | — |
| `RMA_DB_POOL_MIN` / `RMA_DB_POOL_MAX` | `1` / `4` | Variable. `instancias máximas × POOL_MAX` por debajo del límite de clientes de Supavisor |
| `RMA_DB_LOCK_TIMEOUT_MS` / `RMA_DB_STATEMENT_TIMEOUT_MS` | `5000` / `15000` | Valores por defecto |
| `RMA_FOTOS_BUCKET` | el bucket privado de fotos | Variable (ya en uso) |
| `RMA_CATALOGO_*` | origen del catálogo de Ventas | Variables (ya en uso) |

- Pool: una sola unidad de trabajo por pool, compartida por todos los repositories (QA-E3-4, verificado en `test_arranque_postgres.py`). `prepare_threshold=None` para el pooler en modo transacción.
- TLS: contra un host remoto solo se admite `sslmode=verify-full`.
- Si la base no responde al arrancar, la instancia no arranca: nunca cae a JSON.

## 4. Fotos y catálogo de Ventas

- **Fotos:** ya persistentes. En Cloud Run van al bucket privado de GCS (`RMA_FOTOS_BUCKET`); la base guarda la clave del objeto. Con clave de idempotencia, el nombre del objeto sale de ella (B2).
- **Copia del catálogo de Ventas:** es un JSON en `RMA_DATA_DIR`, efímero en Cloud Run. No guarda datos de negocio (cada Orden conserva su copia del equipo) y se reconstruye desde Google Sheets con `POST /api/catalogs/equipment/sync`. **Propuesta más simple:** sincronizarla al arrancar si falta y hay origen configurado (cambio pequeño, a autorizar). Hasta entonces, después de cada despliegue o reinicio, Administración ejecuta la sincronización; sin ella el alta sigue funcionando con modelo técnico y texto libre.

## 5. Activación, verificación y recuperación

**Activación** (cada paso con autorización):
1. Verificaciones de solo lectura (sección 1).
2. Migraciones pendientes, en orden.
3. `select * from rma.verificar_integridad();` vacío.
4. Nueva revisión de Cloud Run con las variables de la sección 3, sin tráfico; `GET /health` y `GET /api/catalogs/repair-types`.
5. Recorrido de humo en la revisión nueva: alta, Detalle, pago con `Idempotency-Key` reintentado (un solo pago), ingreso de stock; reinicio de la instancia y relectura.
6. Pasar el tráfico a la revisión nueva.

**Verificación posterior:** `verificar_integridad()` vacío, registros de error sin `PERSISTENCIA_RESULTADO_INCIERTO` sostenidos, latencia de los comandos (Cloud Run en São Paulo, Supabase en Oregón).

**Recuperación:**
- Falla la app: devolver el tráfico a la revisión anterior (JSON). No hay modo mixto: los datos creados en PostgreSQL no pasan a JSON; en DEV/UAT no hay datos operativos históricos.
- Falla una migración: cada una corre en su transacción y se revierte sola. Las migraciones son aditivas: no se deshacen, se corrigen con otra nueva.
- Nunca `db reset`, borrar la base ni ejecutar SQL a mano fuera de este procedimiento.
