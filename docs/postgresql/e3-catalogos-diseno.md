# E3. Catálogos PostgreSQL: discovery técnico y diseño

**Estado:** implementada el 05/11/2026 y corregida dos veces: después de la QA independiente (APPROVED WITH OBSERVATIONS, sección 12) y después de la QA final (NOT APPROVED por QAF-1, sección 13). Sin commit, pendiente de una verificación final focalizada. La implementación está en la sección 11. El diseño (secciones 1 a 10) se aprobó con las decisiones DE3-1 a DE3-4. Aplica las decisiones aprobadas DA-E3-1 (alcance), DA-E3-2 (sin modo mixto operativo) y DA-E3-3 (M3 de solo lectura).

**Base:** rama `feat/postgresql-esquema`, commit `d08d743` (E2), un commit adelante de `origin`.

**Evidencia:**
- lectura del código, del esquema (`supabase/migrations`) y de las cargas (`supabase/seeds`);
- comprobaciones contra PostgreSQL 17 local;
- el script de M3, probado en local.

M3 contra Supavisor no se pudo ejecutar durante el discovery (sección 5.5). Se ejecutó al implementar (sección 11.2).

## 1. Resumen ejecutivo

E3 tiene dos partes. **E3-A** es la infraestructura: el ejecutor SQL restringido, la lectura con transacción breve y el ciclo de vida del pool. **E3-B** son los repositories PostgreSQL de los catálogos de solo lectura (`CatalogosRepository`, salvo el stock, y `ModelosEquipoRepository`), con pruebas de contrato compartidas con JSON. La aplicación sigue en JSON.

**Hallazgos que condicionan el diseño** (todos verificados en el código o en la base local):

1. **Identificador del insumo (bloqueante).** El dominio tiene dos identificadores, `Insumo.id` (`INS-001`) y `Insumo.codigo` (`BAT-IP14`). La tabla `rma.insumo` solo guarda `codigo`, y la carga generada desde el JSON pierde `INS-001`. Ese `id` es el que referencian los insumos previstos, los movimientos y las Órdenes.
2. **Orden de las listas.** JSON devuelve el orden del archivo, que no siempre es alfabético: usuarios `RECEP, COORD, TECH, ADMIN`; medios de pago `EFECTIVO, TRANSFERENCIA, TARJETA_DEBITO, TARJETA_CREDITO, OTRO`. El esquema no tiene una columna de orden y el frontend no reordena, así que ordenar por código cambiaría lo que se ve.
3. **Escala numérica.** `numeric(14,2)` devuelve `Decimal('80000.00')` y JSON tiene `80000`. Son iguales en Python, pero la API los serializa distinto (`80000` contra `80000.00`).
4. **Lecturas fuera de transacción.** Las 49 llamadas a `obtener_usuario` y varios listados de catálogo ocurren antes de abrir la transacción del comando. E1 exige una transacción para cualquier acceso, y el plan aprobado (§2.1) preveía lecturas breves fuera de ella.
5. **`TR-OTROS`** es virtual en la aplicación (`tipo_reparacion_otros(precio)`) y una fila real en la base, porque la necesita la clave foránea de `detalle`. Hay que excluirlo de los listados del catálogo.
6. **Stock.** `CatalogosRepository` incluye escrituras y movimientos de stock, que son de E5. Además, `rma_backend` no puede actualizar `insumo.stock_fisico`, que solo cambia por el libro de inventario.
7. **Roles.** El dominio tiene un rol por usuario; la base, varios (DC27A, no implementado).
8. **M3 no ejecutada.** La sesión de `gcloud` venció y la reautenticación es interactiva. El script está listo y probado en local.

**Recomendación:** GO para implementar E3, condicionado a resolver DE3-1 a DE3-4 (sección 8). M3 se ejecuta al empezar E3-A, en cuanto se renueve la sesión de `gcloud`.

## 2. Alcance exacto de E3

| Incluido | Excluido |
|---|---|
| **E3-A.** Ejecutor SQL restringido (QA-2, QA-3, F-04) | Órdenes (E4) |
| **E3-A.** Lectura con transacción breve de solo lectura, fuera de un comando (DE3-4) | Escrituras y movimientos de stock: `actualizar_stock_insumo`, `registrar_movimiento_stock` y `listar_movimientos_stock` (E5) |
| **E3-A.** Ciclo de vida del pool: apertura, cierre, conexiones ociosas cortadas (M2), conexión fallida frente a pool agotado (L2), topes de ajustes (L1) y cierre (L8) | `motivo_ajuste` (E5) |
| **E3-A.** `conexion_actual()` pasa a ser privado | Acciones e idempotencia (E6) |
| **E3-B.** `PostgresCatalogosRepository`: 13 métodos de lectura | Catálogo de Ventas (`CatalogoEquiposRepository`): sigue en JSON según el plan |
| **E3-B.** `PostgresModelosEquipoRepository`: 2 métodos | Activar PostgreSQL en la aplicación (DA-E3-2) |
| **E3-B.** Mapeo tabla ↔ dominio y pruebas de contrato parametrizadas JSON/PostgreSQL | Cambios al dominio, a la API o al frontend |
| M3: prueba de solo lectura contra Supavisor DEV/UAT (DA-E3-3) | Migraciones remotas |

## 3. Diseño del ejecutor SQL restringido (E3-A)

Parte del diseño de E2 (sección D de `e2-consultas-dedicadas.md`), con lo que aprendimos en la QA de E2 y en esta revisión.

### 3.1 API

```python
# app/storage/postgres/consultas.py
Consulta = NewType("Consulta", ...)  # objeto registrado, no un str

def consulta(nombre: str, sql: LiteralString) -> Consulta:
    """Registra una consulta estatica al importar el modulo.

    Valida el primer token y la lista de funciones prohibidas; si falla,
    el modulo no carga. El registro permite revisar todo el SQL en una
    prueba estatica.
    """

# app/storage/postgres/ejecutor.py
class EjecutorSql(Protocol):
    def filas(self, consulta: Consulta, parametros: Parametros = ()) -> list[Fila]: ...
    def fila(self, consulta: Consulta, parametros: Parametros = ()) -> Fila | None: ...
    def ejecutar(self, consulta: Consulta, parametros: Parametros = ()) -> int: ...
    def ejecutar_lote(self, consulta: Consulta, lotes: Iterable[Parametros]) -> None: ...

# app/storage/postgres/transaccion.py (UnidadDeTrabajoPostgres)
def ejecutor(self) -> EjecutorSql:
    """El de la transaccion en curso. Fuera de una transaccion: PersistenciaError."""

@contextmanager
def lectura(self) -> Iterator[EjecutorSql]:
    """Para leer: el de la transaccion en curso o, si no hay ninguna, una
    transaccion breve READ ONLY (BEGIN READ ONLY y los SET LOCAL),
    terminada con ROLLBACK (DE3-4)."""
```

- **`Parametros`** es una tupla o un diccionario. **`Fila`** es una tupla con nombre, materializada.
- **Nunca** se devuelve un cursor, porque `cursor.connection` expondría la conexión.
- **Solo acepta consultas registradas.** Un `str` o un `psycopg.sql.SQL` armado al vuelo lanza `TypeError`.
- **Repositories:**
  - los de lectura usan `lectura()`, que funciona dentro y fuera de un comando;
  - los que escriben (E4 y E5) usan `ejecutor()`, que exige la transacción del comando.

### 3.2 Controles en cada operación (QA-3)

1. Hay una transacción, y el `_EnCurso` vigente de la `ContextVar` es **el mismo objeto** al que se ató el ejecutor. Si no, es un ejecutor guardado de otra transacción y se rechaza.
2. `estado.activa` y `estado.problema() is None`: vigencia y dueño (hilo y tarea), como en E1.
3. Una conexión `INERROR` o un `estado.invalidada` lanzan `TransaccionInvalidadaError` sin ir al servidor.
4. Un error en la operación marca `estado.invalidada = True` y se traduce con `traducir_error`, sin datos de filas. Aunque se atrape, la unidad de trabajo revierte.
5. Si después de una operación la conexión quedó `IDLE` (alguien terminó la transacción), se marca para **descartarla**: se cierra en lugar de volver al pool (QA-2).

### 3.3 Restricción del SQL (QA-2 y F-04): capas y límites

| Capa | Qué impide | Qué **no** impide |
|---|---|---|
| **SQL estático registrado** (`consulta(...)` al importar) | SQL armado con datos o en tiempo de ejecución; inyección | Lo que el propio texto registrado haga |
| **Lista permitida del primer token**, al registrar: `SELECT`, `WITH`, `INSERT`, `UPDATE`, `DELETE` | `BEGIN`, `START`, `COMMIT`, `END`, `ROLLBACK`, `ABORT`, `SAVEPOINT`, `RELEASE`, `PREPARE`, `SET` (con o sin `SESSION`, `LOCAL` o `TRANSACTION`), `RESET`, `DISCARD`, `LOCK`, `CALL`, `DO`, `COPY`, `LISTEN`, `NOTIFY`, `VACUUM`, DDL | Funciones con efectos dentro de un `SELECT` |
| **Funciones prohibidas en el texto**, al registrar: `set_config`, `pg_advisory_*`, `dblink*`, `lo_*`, `pg_sleep*`, `pg_terminate_backend`, `pg_cancel_backend`, `pg_reload_conf` | Los efectos de sesión conocidos (verificado: `set_config(…, false)` sobrevive al `COMMIT`) | Una lista nunca es completa: es una red, no una barrera |
| **Protocolo extendido** (`binary=True`) en toda ejecución | Más de una sentencia por envío: lo rechaza el **servidor** (verificado en local) | **No** impide efectos dentro de una sentencia permitida. No es una protección integral |
| **Parámetros** siempre como `%s` o `%(nombre)s` | Interpolar valores | — |
| **`prepare_threshold=None`** (E0) | Sentencias preparadas en el servidor, que Supavisor en modo transacción no admite | — |
| **Privilegios mínimos** del rol `rma_backend` (ya vigentes) | DDL; `UPDATE` de `insumo.stock_fisico` y de otras columnas no habilitadas | `SET` y `set_config` de parámetros de usuario; funciones de `pg_catalog` ejecutables por `PUBLIC` |
| **Descarte de la conexión** ante una violación detectada | Que el estado dudoso vuelva al pool | Una violación no detectada |
| **Pruebas estáticas** | `conexion_actual`, `commit`, `rollback` y `_conexion` fuera de `transaccion.py`; `psycopg` importado en los repositories | Código que use atributos privados a propósito |

**Límite.** El ejecutor es una barrera contra **errores de programación**, no contra código malicioso: en Python siempre se puede acceder a atributos privados. Las barreras reales son el rol de la base, el SQL registrado y la revisión de código.

### 3.4 Pruebas de aceptación (E3-A)

1. Registrar una consulta con cualquier sentencia de control o de sesión falla al importar: mayúsculas o minúsculas, comentarios `/* */` y `--` delante, paréntesis, espacios y saltos de línea.
2. Registrar una consulta con una función prohibida falla, también con espacios o comillas en el nombre (`"set_config"`).
3. Un `str` o un `sql.SQL` no registrado se rechaza con `TypeError`.
4. `SELECT 1; SELECT 2` registrado como texto falla en el registro. Enviado a la fuerza, lo rechaza el servidor y la transacción queda invalidada.
5. Fuera de una transacción, `ejecutor()` lanza `PersistenciaError`; `lectura()` abre y cierra su transacción `READ ONLY`.
6. Un ejecutor guardado después del cierre, en un contexto copiado (hilo o tarea) o de una transacción anterior del mismo flujo: se rechaza.
7. Después de un error SQL atrapado, la operación siguiente lanza `TransaccionInvalidadaError` sin ir al servidor, y la unidad revierte todo.
8. Ningún resultado expone la conexión: no hay cursores ni atributos públicos que la devuelvan.
9. Prueba estática: fuera de `transaccion.py`, ningún módulo de `storage/postgres` usa `conexion_actual`, `commit`, `rollback` ni `_conexion`.
10. Los tipos en binario coinciden con los del protocolo de texto: `int`, `Decimal`, `datetime`, `text`, `bool`, `uuid` y `text[]`.
11. Regresión: R1, R2, R2b y QA-1 de E1 siguen pasando; R1 (un `COMMIT` del repository) es imposible a través del ejecutor.
12. Una transacción de `lectura()` no deja la conexión en otro estado: el `SHOW` de los `SET LOCAL` vuelve al de la sesión.

## 4. Inventario y contratos de catálogos (E3-B)

**Reglas comunes de mapeo** (sujetas a DE3-1 a DE3-3):
- **Identificador:** el `id` del dominio es la columna `codigo`; el `uuid` no sale del repository. Un helper `uuid_de(tabla, codigo)` queda para E4 a E6.
- **No encontrado:** `obtener_*` lanza `EntidadPersistidaNoEncontradaError` con el mismo texto que JSON (`No existe el <etiqueta> <id>`).
- **Fuera de una transacción**, cada llamada es su propia lectura `READ ONLY`; dentro de un comando, usa la transacción del comando.
- **Columnas sin equivalente** en el dominio (`creado_en`, `modificado_en`, `email`, `auth_user_id`, `stock_reservado`): no se leen.

| Catálogo | Dominio | Tablas | Métodos (E3) | Transformación | Nulos | Orden JSON | Orden PostgreSQL | Sin registros | Riesgo de equivalencia |
|---|---|---|---|---|---|---|---|---|---|
| Tipos de reparación | `TipoReparacion` | `tipo_reparacion` | `listar_tipos_reparacion`, `obtener_tipo_reparacion` | `codigo`→`id`; `precio` según DE3-3; **excluir `TR-OTROS`** | Ninguno | Archivo (`TR-001`, `TR-002`) | DE3-2 | `[]` / no encontrado | `TR-OTROS`; escala del precio |
| Insumos | `Insumo` | `insumo` | `listar_insumos`, `obtener_insumo` | **DE3-1** (`id` frente a `codigo`); `stock_fisico` según DE3-3 | `unidad` | Archivo | DE3-2 | `[]` / no encontrado | **Bloqueante:** el `id` del dominio no existe en la base |
| Insumos previstos | `TipoReparacionInsumos` | `tipo_reparacion_insumo` ⋈ `tipo_reparacion`, `insumo` | `listar_tipo_reparacion_insumos` | Códigos de los dos extremos; `cantidad` numeric(12,3) | Ninguno | Archivo | DE3-2 | `[]` | Depende de DE3-1. La clave foránea impide filas huérfanas que JSON sí admite (diferencia admisible) |
| Estaciones | `EstacionTrabajo` | `mesa_trabajo` | `listar_estaciones`, `obtener_estacion` | `codigo`→`id` | Ninguno | Archivo | DE3-2 | `[]` / no encontrado | — |
| Compatibilidades | `TipoReparacionEstacion` | `mesa_tipo_reparacion` ⋈ `mesa_trabajo`, `tipo_reparacion` | `listar_tipo_reparacion_estaciones` | Códigos | Ninguno | Archivo | DE3-2 | `[]` | — |
| Usuarios | `Usuario` | `usuario` ⋈ `usuario_rol` ⋈ `rol` | `listar_usuarios`, `obtener_usuario` | Rol: **exactamente uno** (DE3-6) | Sin rol: error | Archivo (**no** alfabético) | DE3-2 | `[]` / no encontrado | Orden del selector; usuarios con varios roles |
| Medios de pago | `MedioPago` | `medio_pago` | `listar_medios_pago`, `obtener_medio_pago` | `codigo`→`id` | Ninguno | Archivo, o predeterminados si falta el archivo (**no** alfabético) | DE3-2 | DE3-7 | Orden del selector |
| Empresa | `DatosEmpresa` | `empresa` (fila única) | `obtener_datos_empresa` | Columnas a campos | Opcionales | — | — | Predeterminados (como JSON) | — |
| Modelos de equipo | `ModeloEquipo` | `modelo_equipo` | `listar_modelos`, `obtener_modelo` | `codigo`→`id`; `numeros_modelo` `text[]`→`tuple` | `variante` | Por id (los 36 modelos) | `codigo COLLATE "C"`, que es el mismo | `[]` / `None` | Ninguno |
| Stock y movimientos | — | `insumo`, `movimiento_inventario` | — | **E5** | — | — | — | — | El rol no puede actualizar `stock_fisico` |

**Consistencia.** Son lecturas sin bloqueos. Dentro de un comando, ven el mismo momento que el resto de la transacción. Fuera de un comando, cada llamada es un momento propio, como hoy con JSON, que relee el archivo en cada consulta.

**Cargas.** `supabase/scripts/generar_datos_iniciales.cjs` genera la carga de desarrollo desde `app/backend/data/catalogs/*.json`. Es la fuente de verdad para las pruebas de equivalencia, con tres diferencias conocidas:
- agrega `TR-OTROS`;
- pierde el `id` del insumo (DE3-1);
- carga el stock con un `INGRESO` en el libro, así que el `stock_fisico` resultante coincide.

Los modelos de equipo se generan desde `app/backend/app/datos/modelos_equipo.json`: los mismos 36, en el mismo orden.

**Pruebas actuales reutilizables.** `tests/test_repositories_json.py` (catálogos JSON) y los tests de dominio que usan los catálogos de demostración. Las de contrato se escriben nuevas y parametrizadas (sección 6).

## 5. Pool y conectividad (E3-A)

### 5.1 Ciclo de vida

- **Apertura:** `abrir_pool(configuracion, ajustes)` (E1), con `open(wait=False)`. Si la base no responde, lo informa el primer comando.
- **Cierre:** nuevo `cerrar_pool(pool, espera_s)`, pensado para el `lifespan` de FastAPI (L8). En E3 no se engancha a la aplicación, porque `RMA_PERSISTENCIA=postgres` sigue deteniendo el arranque (DA-E3-2). Se prueba por separado y se conecta en E7 o E9.

### 5.2 Valores iniciales

| Ajuste | Valor | Fuente |
|---|---|---|
| `RMA_DB_POOL_MIN` / `RMA_DB_POOL_MAX` | 1 / 4 | E1 |
| `RMA_DB_POOL_ESPERA_S` | 5 | E1 |
| `RMA_DB_POOL_MAX_IDLE_S` (nuevo) | 300, provisional | Por debajo de cortes típicos de red y pooler. Se mide en E8; no se fija por la latencia local |
| `RMA_DB_POOL_VERIFICAR` (nuevo) | `false` | Verificar cada conexión cuesta una ida y vuelta por comando (São Paulo ↔ Oregón). Se activa solo si E8 muestra cortes frecuentes |
| Topes (L1) | `lock_timeout` y `statement_timeout` ≤ 2147483647; `espera_s` finito y positivo | Hoy un valor fuera de rango pasa la validación y rompe cada transacción |

### 5.3 Conexiones ociosas cortadas (M2)

Si el `BEGIN` falla por un error de **conexión** (SQLSTATE de clase `08` o `57P01`, o la conexión quedó cerrada), **antes de ejecutar cualquier sentencia del comando**, la conexión se descarta y se toma **otra, una sola vez**.
- No es un reintento de la transacción: no se ejecutó nada.
- Cualquier otro error, o un error de conexión después del `BEGIN`, sigue como hoy, sin reintento.
- Prueba local: `pg_terminate_backend` de la conexión ociosa del pool, y el comando siguiente funciona sin 500 (hoy da 500, R3).

### 5.4 Conexión fallida frente a pool agotado (L2)

Hoy, una contraseña incorrecta aparece como 503 «ocupado» cuando vence la espera del pool. Propuesta: registrar los fallos de conexión con el callback `reconnect_failed` del pool y con las estadísticas (`connections_errors`). Cuando vence la espera:
- si el pool no tiene conexiones y hubo fallos recientes, se lanza `PersistenciaError` «no se pudo conectar a PostgreSQL» (sin datos de conexión), y la API responde 500;
- si las conexiones existen pero están ocupadas, sigue el 503 `PERSISTENCIA_NO_DISPONIBLE`.

Si este caso se distingue con otro código HTTP es la decisión DE3-8.

### 5.5 M3: prueba contra Supavisor DEV/UAT

- **Resultado en el discovery:** **no ejecutada.** Se ejecutó al implementar E3, con 14 de 14 verificaciones (sección 11.2). `gcloud` pide reautenticación interactiva («Reauthentication failed. cannot prompt during non-interactive execution»), y la credencial de `rma_api` solo existe en Secret Manager. No se buscó otra credencial: M3 tiene que probar la misma ruta que usará la aplicación.
- **Entorno identificado:** el proyecto Supabase vinculado localmente es `rt-rma-db` (DEV/UAT). El script exige que el usuario de la conexión sea `rma_api.<ref de ese proyecto>`, `verify-full` y TLS en uso.
- **El script** (fuera del repositorio hasta aprobar su versión definitiva) hace todo dentro de `BEGIN READ ONLY` y siempre termina en `ROLLBACK`. Verifica:
  - `BEGIN` y los `SET LOCAL` en un solo envío;
  - `SHOW` de `lock_timeout`, `statement_timeout` y `transaction_read_only`;
  - una lectura de un catálogo;
  - `pg_prepared_statements = 0`;
  - que los `SET LOCAL` no pasen a la transacción siguiente;
  - el protocolo extendido con `binary=True`, y que el servidor rechace dos sentencias en un envío;
  - la latencia, solo como dato informativo.

  Contra PostgreSQL 17 local dio 11 de 11.
- **Para ejecutarla:** renovar la sesión con `gcloud auth login` y después correr el script con la cadena del secreto en el entorno del proceso, sin mostrarla.

### 5.6 Mediciones futuras (E8 y E9)

Desde Cloud Run, no desde la máquina local:
- p50 y p95 por comando;
- frecuencia de conexiones cortadas por inactividad;
- tiempo de espera del pool bajo carga, para decidir `max_idle`, `check`, `max_waiting` (L7) y el tamaño del pool.

## 6. Plan de pruebas

**Infraestructura (E3-A, PostgreSQL local):**
- las 12 de aceptación del ejecutor (3.4);
- `lectura()`: dentro de un comando usa su transacción; fuera, una transacción `READ ONLY` que termina limpia;
- pool: apertura y cierre sin fugas, conexión ociosa terminada (M2), contraseña incorrecta frente a pool agotado (L2) y topes de ajustes (L1).

**Contrato de catálogos (E3-B)**, en `tests/test_contrato_catalogos.py`, parametrizado como `test_contrato_ordenes.py`:
- **Implementaciones:** `json` lee los catálogos de demostración copiados a un directorio temporal. `postgres` usa la base local descartable con las mismas cargas; se saltea sin `RMA_TEST_DATABASE_URL`.
- **Casos:**
  - listar todo, `obtener` encontrado y no encontrado (mismo mensaje);
  - nulos (`unidad`, `variante`, campos de empresa), `numeros_modelo`, roles;
  - exclusión de `TR-OTROS`;
  - el orden según DE3-2 y la representación numérica según DE3-3;
  - catálogos vacíos: en PostgreSQL, una base sin las cargas de desarrollo; medios de pago y empresa según DE3-7.
- **Diferencias admisibles, documentadas en las pruebas:**
  - PostgreSQL rechaza filas huérfanas que JSON admite;
  - `uuid` y fechas técnicas no se exponen;
  - las que resulten de DE3-2 y DE3-3 si se aceptan como diferencias.
- **Concurrencia:** las lecturas no toman bloqueos. Una prueba lee catálogos mientras otra transacción tiene filas bloqueadas, y la lectura no espera.

**Lo que no se prueba en E3:** ningún caso de uso con los catálogos en PostgreSQL y las Órdenes en JSON, porque sería un modo mixto (DA-E3-2). La equivalencia de punta a punta es E7.

**Pruebas estáticas:** el registro de consultas (todo el SQL de `storage/postgres` pasa por `consulta(...)`) y las importaciones de los repositories.

**Regresión:** la suite JSON completa sin cambios de expectativas, `tests/postgres`, `ruff check` y `npm run validate:all`.

## 7. Dependencias con E4 a E9

| Etapa | Qué recibe de E3 | Qué E3 tiene que dejar resuelto |
|---|---|---|
| E4 (Orden) | El ejecutor (`ejecutor()` para escribir), `lectura()`, las reglas de mapeo y el helper de `uuid` por código | DE3-1, porque `detalle` y los movimientos referencian insumos; DE3-2 y DE3-3, para que la API no cambie |
| E5 (Inventario) | Los repositories de catálogo y el registro de consultas | Las escrituras de stock (`CatalogosRepository`) y `motivo_ajuste` quedan para E5. QA-E2-10 (`DESPERDICIO`) |
| E6 (Acciones) | El mapeo de `Usuario` a su `uuid` para `accion_usuario` | DE3-6 (roles) |
| E7 (Equivalencia) | Las pruebas de contrato parametrizadas y las reglas de normalización | Que las diferencias admisibles estén escritas |
| E8 (DEV/UAT) | El resultado de M3 y los ajustes del pool | Ejecutar M3 |
| E9 (Cloud Run) | `cerrar_pool` y los ajustes para el `lifespan` | — |

**Antes de implementar E3** hay que resolver DE3-1, DE3-2, DE3-3 y DE3-4. **Pueden esperar:** DE3-5 (forma del contrato de stock, para E5), DE3-6 (para E6), DE3-7 y DE3-8.

## 8. Riesgos y decisiones pendientes

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| **DE3-1** | Identificador del insumo en PostgreSQL | (a) Una columna nueva en `rma.insumo` para el `id` del dominio, por migración local y regenerando la carga. (b) Que el `id` del dominio sea el `codigo` de la base: cambia `INS-001` por `BAT-IP14` en los datos JSON existentes, un cambio de datos. (c) Usar el `uuid` como `id`: rompe las referencias y su lectura humana | **(a)**. Conserva el dominio y los datos; es una migración aditiva que se aplica en local y llega a DEV/UAT recién en E8 |
| **DE3-2** | Orden de los listados | (a) Una columna `orden` en los catálogos que lo necesitan, cargada con el orden actual de JSON. (b) Ordenar por código en PostgreSQL y aceptar que cambien los selectores. (c) Ordenar también JSON por código: cambia el comportamiento JSON, no permitido | **(a)** para usuarios y medios de pago, o donde el orden sea visible; `codigo COLLATE "C"` donde ya coincide (modelos, tipos, estaciones) |
| **DE3-3** | Escala numérica | (a) El mapeador devuelve el número sin ceros de más (`80000.00` → `80000`; `2.000` → `2`), sin notación exponencial. (b) Aceptar la diferencia en la API | **(a)**: la API no cambia. Es una regla del mapeador, no del dominio |
| **DE3-4** | Lecturas fuera de transacción | (a) `lectura()` abre una transacción breve `READ ONLY` si no hay ninguna, como preveía el plan (§2.1). (b) Exigir transacción en todas las lecturas: cambia 49 llamadas y más casos de uso | **(a)**. Ajusta el contrato de E1: las lecturas ya no exigen la transacción del comando; las escrituras, sí |
| DE3-5 | Stock en `CatalogosRepository` | (a) El repository PostgreSQL de E3 lanza `PersistenciaError` («disponible en E5») en los 3 métodos de stock. (b) Separar el Protocol | (a) en E3; separar se evalúa en E5 |
| DE3-6 | Usuarios con varios roles | Exigir exactamente uno, o tomar uno por prioridad | Exigir uno (`PersistenciaError` si no) hasta implementar DC27A |
| DE3-7 | Medios de pago sin filas | Predeterminados, como JSON sin archivo, o lista vacía | Predeterminados; la carga de referencia siempre los inserta |
| DE3-8 | Código HTTP de «no se pudo conectar» | 500 genérico, o 503 con otro `codigo` | 500 (es un fallo de infraestructura, no una saturación). Revisar en E8 |
| M3 | Renovar `gcloud` | — | `gcloud auth login` por el usuario. Después, M3 al empezar E3-A |

**Riesgos:**
- **Migraciones aditivas** (DE3-1 y DE3-2, si se aprueban): se escriben y prueban en local y se aplican en DEV/UAT recién en E8, con autorización.
- **Supavisor sin validar** (M3): el diseño del ejecutor depende de que `binary=True` y `BEGIN`+`SET LOCAL` funcionen igual a través del pooler.
- **Normalización numérica** (DE3-3): se aplica en el mapeador y lo verifica una prueba de contrato.
- **Datos de demostración y cargas**: `generar_datos_iniciales.cjs` tiene que regenerarse con cada decisión. Hay que verificar que la carga sea idempotente en la base local.

## 9. Archivos previstos

**Nuevos:**
- `app/backend/app/storage/postgres/consultas.py`: registro de SQL estático y validación al registrar.
- `app/backend/app/storage/postgres/ejecutor.py`: `EjecutorSql` y sus controles.
- `app/backend/app/storage/postgres/catalogos.py`: `PostgresCatalogosRepository`.
- `app/backend/app/storage/postgres/modelos_equipo.py`: `PostgresModelosEquipoRepository`.
- `app/backend/app/storage/postgres/mapeo.py`: identificadores, escala numérica y exclusiones.
- `app/backend/tests/postgres/test_ejecutor_sql.py`, `tests/postgres/test_pool.py`, `tests/test_contrato_catalogos.py` (con la parametrización para PostgreSQL) y la prueba estática del registro.
- Un script de M3 en `app/backend/scripts/`, si se decide versionarlo.
- Si se aprueban DE3-1 o DE3-2: una migración aditiva en `supabase/migrations/` y la regeneración de las cargas con `generar_datos_iniciales.cjs`.

**Modificados:**
- `storage/postgres/transaccion.py`: `ejecutor()`, `lectura()`, M2, L2 y `conexion_actual` privado.
- `storage/postgres/ajustes.py`: L1, `max_idle` y verificación.
- `storage/postgres/__init__.py` y `core/config.py`: los dos ajustes nuevos.
- Documentación: este documento, `integracion-pendientes.md` y `ESTADO_PROYECTO.md` al cerrar.

**No se modifican:** dominio, services, `application/`, API, frontend, `storage/json` ni el arranque de la aplicación.

## 10. Criterios de aceptación de E3

1. El ejecutor pasa sus 12 pruebas de aceptación. Ningún repository recibe una conexión psycopg, y una prueba estática lo verifica.
2. `lectura()` funciona dentro y fuera de un comando, y sus transacciones `READ ONLY` terminan limpias.
3. Pool: M2 resuelto con un único reemplazo antes de ejecutar nada; L2 distingue la conexión fallida; topes de ajustes (L1); `cerrar_pool` sin fugas.
4. M3 ejecutada contra DEV/UAT, de solo lectura, con todas sus verificaciones en OK y su resultado registrado (sin datos sensibles).
5. `PostgresCatalogosRepository` (13 lecturas) y `PostgresModelosEquipoRepository` pasan las mismas pruebas de contrato que JSON contra la base local, con las diferencias admisibles escritas. DE3-1 a DE3-3 aplicados.
6. Los métodos de stock lanzan el error previsto (DE3-5) y una prueba lo verifica.
7. La aplicación sigue en JSON: `RMA_PERSISTENCIA=postgres` detiene el arranque y no hay modo mixto.
8. La suite JSON pasa sin cambios de expectativas, junto con `tests/postgres`, `ruff check` y `npm run validate:all`.
9. Sin credenciales en el repositorio, los logs ni los mensajes de error.
10. Revisión independiente de E3: APPROVED o APPROVED WITH OBSERVATIONS.

## 11. Implementación y pruebas

Implementado el 05/11/2026 sobre `d08d743`, sin commit. La aplicación sigue en JSON: `RMA_PERSISTENCIA=postgres` sigue deteniendo el arranque y no hay modo mixto. No se tocaron Cloud Run, Vercel ni producción, y no se aplicó ninguna migración en Supabase remoto.

### 11.1 Qué se implementó

**E3-A, infraestructura:**
- **Registro de consultas** (`storage/postgres/consultas.py`). `consulta(nombre, sql, modo=...)` valida al importar el módulo:
  - una sola sentencia que empieza con `SELECT`, `WITH`, `INSERT`, `UPDATE` o `DELETE`;
  - sin `;`, comentarios, `$` ni `U&`;
  - `INTO` solo en `INSERT INTO`, y sin `pg_settings` (QA-E3-1);
  - sin funciones conocidas de sesión, de bloqueo advisory (también las `pg_try_advisory_*`), de objetos grandes o de archivos, ni las que ejecutan SQL recibido como texto (`query_to_xml` y similares, `ts_stat`, `ts_rewrite`), ni los esquemas de extensiones con efectos fuera de la base (`net`, `cron`, `vault`, `pgsodium`);
  - una clasificación explícita y obligatoria: `LECTURA` (empieza con `SELECT` o `WITH` y no escribe, no bloquea filas ni usa `nextval`) o `ESCRITURA` (QA-E3-3);
  - nombre único.

  El ejecutor solo acepta objetos `Consulta` registrados. Esas reglas son la primera capa, y no son un analizador de SQL ni una barrera de seguridad completa. La segunda es el protocolo extendido (`binary=True`): el servidor rechaza dos sentencias en un envío aunque una consulta eluda el registro. La tercera son los permisos del rol (sección 12.3). Una prueba estática recorre el código de `storage/postgres` y confirma que todo el SQL de los repositories pasa por `consulta(...)` y que los catálogos solo registran lecturas.
- **Lector y ejecutor** (`ejecutor.py` define el contrato; `transaccion.py`, la implementación):
  - `lectura()` y `ejecutor()` devuelven objetos atados a la transacción, que nunca exponen la conexión ni un cursor. Las filas son tuplas con nombre materializadas.
  - En cada operación se verifica:
    - que la transacción siga vigente y no invalidada;
    - que la use el flujo que la abrió;
    - que el objeto sea de esta transacción y no de una anterior;
    - que la conexión siga dentro de la transacción.
  - El lector solo ejecuta consultas `LECTURA`. Una `ESCRITURA` se rechaza sin enviarla e invalida la transacción, también dentro de un comando que escribe (QA-E3-3).
  - Un error SQL invalida la transacción. Lo que siga se rechaza sin ir al servidor.
  - Un `COMMIT` o `ROLLBACK` enviado por fuera invalida la transacción y descarta la conexión.
  - Una conexión que no queda fuera de toda transacción (`IDLE`) al devolverla se cierra en lugar de volver al pool.
- **`lectura()` (DE3-4):**
  - Dentro de un comando usa su transacción y no cambia su carácter.
  - Fuera de un comando abre `BEGIN READ ONLY` con los mismos `SET LOCAL` y termina con `ROLLBACK`.
  - Dentro de una lectura no se abre una transacción de escritura ni se pide `ejecutor()`.
  - `conexion_actual()` pasó a ser privado (`_conexion_actual`).
- **Pool:**
  - M2: si el `BEGIN` falla por un error de conexión (sqlstate `08*` o `57P01` a `57P03`, o la conexión cerrada), la conexión se descarta y se toma otra una sola vez. Si la segunda también está cortada: `PersistenciaSinConexionError` (503), sin más intentos (QA-E3-2). No se reintenta ninguna transacción. Un error del `BEGIN` que no es de conexión no se reintenta.
  - Una interrupción (`KeyboardInterrupt`) durante el `BEGIN` cierra esa conexión y deja el contador en orden.
  - L2: `PersistenciaSinConexionError` (503, código `PERSISTENCIA_SIN_CONEXION`) se distingue del pool agotado (503, `PERSISTENCIA_NO_DISPONIBLE`) con un contador de conexiones en uso por unidad de trabajo.
  - L1: topes en los ajustes (milisegundos ≤ 2147483647, `pool_max` ≤ 20, esperas finitas y positivas).
  - `max_idle` 300 s (`RMA_DB_POOL_MAX_IDLE_S`): cierra las conexiones que superan `pool_min` y llevan más de ese tiempo ociosas, de a una por intervalo. Las `pool_min` conexiones nunca se renuevan por inactividad: si las cortan, las cubre el reemplazo de M2.
  - `cerrar_pool()`: cierra enseguida las conexiones ociosas y deja de entregar conexiones. Su espera es la de los hilos internos del pool, no la de las conexiones en uso: una transacción en curso sigue y su conexión se cierra al devolverla. El apagado tiene que dejar terminar los pedidos antes de llamarla.

**E3-B, catálogos:**
- `PostgresCatalogosRepository`: las 13 lecturas. Los 3 métodos de stock lanzan `PersistenciaError` («llegan en E5»), según DE3-5.
- `PostgresModelosEquipoRepository`: `listar_modelos` y `obtener_modelo`, con los 36 modelos ordenados por código.
- Mapeo (`mapeo.py` y los repositories):
  - el `id` del dominio es el código; el del insumo es `clave` (DE3-1);
  - `TR-OTROS` queda excluido;
  - cada usuario tiene exactamente un rol; si no, `PersistenciaError` (DE3-6);
  - medios de pago y empresa sin filas toman los predeterminados de JSON (DE3-7);
  - los números se devuelven sin ceros de más ni notación exponencial (DE3-3, `decimal_sin_ceros`);
  - todo se ordena con `ORDER BY` explícito: `codigo COLLATE "C"`, y en usuarios y medios de pago `orden, codigo` (DE3-2).
  - El mensaje de «no existe» es el mismo que en JSON.

### 11.2 M3 contra Supavisor

Prueba de solo lectura contra DEV/UAT (`rt-rma-db`, autorizada por DA-E3-3), el 05/11/2026: **14 de 14 verificaciones en OK**.
- El destino se verificó antes de conectar: usuario `rma_api` del proyecto, pooler en el puerto 6543, TLS `verify-full` en uso.
- `BEGIN READ ONLY` con los `SET LOCAL` en un solo envío: aplicados, y no pasan a la transacción siguiente.
- `pg_prepared_statements` = 0.
- El protocolo extendido en binario funciona, y el servidor rechaza dos sentencias en un envío también a través del pooler.

La latencia de alrededor de 230 ms se midió desde la máquina local y es solo un dato informativo; la medición que vale es la de E8 desde Cloud Run. No se escribió nada, no se mostró ninguna credencial y el script quedó fuera del repositorio.

**Alcance real (precisado por la QA).** M3 valida el protocolo y la sesión a través de Supavisor, que es lo acordado. No prueba más que eso:
- **Sentencias preparadas:** `pg_prepared_statements = 0` se midió antes de cualquier consulta repetida, así que por sí sola no demuestra nada. La prueba es la del cliente: `prepare_threshold` es `None`.
- **Rechazo de dos sentencias:** el script acepta cualquier error de psycopg y no registró el SQLSTATE ni qué componente lo rechazó. En local es 42601.
- **Ajustes que pasan a la transacción siguiente:** solo se verificó `lock_timeout`, no `statement_timeout`.
- **Camino de la aplicación:** usó una conexión directa con `execute`, no el pool, `lectura()`, el ejecutor ni el reemplazo de M2. Ese camino se prueba en local.
- **Datos remotos:** no revisó los insumos. El esquema remoto todavía no tiene la migración de E3.

Esos puntos se repiten en E8, desde Cloud Run y con el código de la aplicación.

### 11.3 Migración local

`supabase/migrations/20261105000100_e3_catalogos.sql`, aditiva y sin borrar datos:
- **`rma.insumo.clave` (DE3-1):**
  - las filas anteriores toman su `codigo`, que es único, así que no hay colisiones;
  - después se agregan `NOT NULL`, `UNIQUE` y un `CHECK` de no vacía;
  - el trigger `insumo_clave_por_defecto` completa la clave con el código en un alta que no la informa, como un insumo creado fuera de la aplicación o los datos de las pruebas SQL. Su función no tiene `EXECUTE` para PUBLIC ni para los roles de Supabase, como las demás del esquema. El trigger es un riesgo registrado para E8 (QA-E3-6);
  - las relaciones siguen usando el `uuid`, así que ninguna referencia cambia;
  - el `UPDATE` que completa la clave dispara el trigger de modificación: cambia `modificado_en` de todos los insumos anteriores a E3. Es aceptable en local y se tiene en cuenta en E8.
- **`rma.usuario.orden` y `rma.medio_pago.orden` (DE3-2):** `integer not null default 0`.
- **Cargas:** `generar_datos_iniciales.cjs` fija la `clave` y el `orden` desde JSON, y las cargas de `supabase/seeds` se regeneraron. Después de la QA (QA-E3-5):
  - el generador valida las referencias antes de generar: una que no se resuelve, un id repetido o un id de insumo igual al código de otro detienen la generación con el detalle;
  - la carga solo completa una clave provisoria (`clave = codigo`) y nunca pisa una identidad ya asignada;
  - los insumos previstos se asocian por clave **y** código;
  - una verificación al final de la carga confirma que cada usuario, relación e insumo de las fuentes quedó en la base con su identidad. Si no, la carga falla con el detalle.

  La carga es idempotente: una segunda aplicación no cambia filas ni `modificado_en`. Se aplica entera o nada (`psql -v ON_ERROR_STOP=1 --single-transaction`).

Pruebas de la migración y las cargas (`tests/postgres/test_cargas_iniciales.py` y `test_contrato_catalogos.py`):
- **Base nueva:** cada identidad y cada relación de las fuentes, e idempotencia.
- **Base anterior a E3,** con insumos, relaciones, un movimiento y un insumo ajeno a las fuentes:
  - se conservan las mismas filas (mismo `uuid`), las relaciones y el saldo;
  - la clave toma el código;
  - la carga fija la clave del dominio y el orden;
  - repetirla no cambia nada.
- **Una identidad existente distinta** de la de las fuentes no se pisa, y la carga falla con el detalle.
- **Un insumo ajeno** cuyo código es el id del dominio de otro no recibe ninguna relación, aun aplicando la carga sentencia por sentencia, y la verificación lo informa.

### 11.4 Pruebas

Resultados al cierre, después de las correcciones de las secciones 12 y 13:

| Conjunto | Resultado |
|---|---|
| `tests/postgres/test_ejecutor_sql.py` (E3-A) | 38 pruebas (24 antes de la QA, 33 antes de la QA final): `lectura()` dentro y fuera de un comando, consultas no registradas, ejecutor guardado, hilo y tarea herederos, error SQL, varias sentencias forzadas, conexión no expuesta, tipos en binario, control externo, M2 (un único reemplazo y 503 en el segundo corte), L2, interrupción en el `BEGIN`, `cerrar_pool`, permisos de `rma_backend` y las regresiones de QA-E3-1, QA-E3-3 y E3-2 |
| `tests/test_e3_sql_y_ajustes.py` (sin base) | 190 pruebas (81 y 141 en las rondas anteriores): rechazos y aceptaciones del registro, ataques de sesión, comillas pegadas, `insert` como alias, esperas, clasificación de lectura y escritura, prueba estática de las 14 consultas, topes de ajustes y representación numérica |
| `tests/postgres/test_contrato_catalogos.py` (E3-B) | 35 pruebas con PostgreSQL (10 solo de JSON sin la base): equivalencia JSON/PostgreSQL de cada listado, empresa y modelos, contrato de cada implementación, stock en E5, base sin filas, números enteros, decimales, nulos y límites, roles, integridad, migración sobre datos anteriores, y que la lectura no espera filas bloqueadas ni ve lo no confirmado |
| `tests/postgres/test_cargas_iniciales.py` | 9 pruebas: escenarios A y B, identidad existente que no se pisa, insumo ajeno sin relaciones, idempotencia, stock sobre otra identidad (QAF-8), la guarda de la migración con datos (tres casos) y la base vacía sin autorización (QAF-13) |
| `tests/test_generador_cargas.py` (Node, sin base) | 9 pruebas: carga versionada igual a la generada, siete referencias inválidas que detienen la generación y cada relación en la carga |
| Conjunto PostgreSQL (E1, E2, E3) | 460 pruebas, 2 corridas sin fallos al cierre, de unos 62 s cada una (319 antes de la QA y 401 antes de la QA final) |
| Suite JSON completa | 1639 pasan y 121 se saltean (las de PostgreSQL, sin la base) |
| Pruebas SQL (`supabase/tests`) | todas OK, con la migración de E3 |
| `ruff check`, `ruff format --check` y `npm run validate:all` | sin errores |

Las pruebas de E1 solo cambiaron en dos puntos:
- `conexion_actual` pasó a llamarse `_conexion_actual`;
- el helper `_limpio` espera, con un límite, a que el pool reponga las conexiones descartadas (la reposición es asíncrona). Una fuga sigue haciendo fallar la prueba.

**Mutaciones de la implementación:** se detectaron 12 de 13. Las 14 de las correcciones están en la sección 12.2.

| Grupo | Mutaciones detectadas |
|---|---|
| Ejecutor | protocolo simple, sin atar a la transacción, sin exigir registro |
| Pool | reemplazo sin límite, sin distinguir «sin conexión» |
| Lectura | lectura de escritura |
| Catálogos | `TR-OTROS` incluido, id del insumo igual al código, precio con la escala de la base, usuarios por código, varios roles aceptados, medios de pago sin predeterminados |

La que no se detectaba era que la lectura termine con `COMMIT` en lugar de `ROLLBACK`. Se la consideró indistinguible en `READ ONLY`, pero no lo es (E3-2, sección 11.7). Ahora la detecta `test_la_lectura_breve_termina_con_rollback`.

### 11.5 Diferencias admisibles entre JSON y PostgreSQL

Con los catálogos de demostración actuales, los 15 métodos dan el mismo resultado y el mismo JSON de la API, y las pruebas de contrato lo verifican. La equivalencia depende de dos condiciones de las fuentes, que hoy se cumplen:
- **Orden.** JSON devuelve las filas en el orden del archivo. PostgreSQL ordena por el id del dominio, con `COLLATE "C"`. En tipos, estaciones y modelos, ese id es el código de la tabla. En insumos e insumos previstos es la `clave` (`INS-001`), no el código comercial `Insumo.codigo` (`BAT-IP14`). Usuarios y medios de pago usan su columna `orden` (DE3-2). Si un archivo no estuviera ordenado por ese id, o tuviera ids de distinto largo (`INS-1000` queda antes que `INS-200`), tipos, insumos, insumos previstos y estaciones saldrían en otro orden. El orden de los insumos previstos importa: define el de las reservas.
- **Números.** PostgreSQL devuelve los números sin ceros de más (DE3-3). Una fuente JSON con ceros de más (`"1.50"`) serializa distinto (`"1.5"`). JSON puede tenerlos si los escribe la aplicación.

Esas dos condiciones se verifican o se resuelven antes de E7 o E8. Las opciones son exigir fuentes ordenadas por id del dominio y normalizadas al cargar, o agregar `orden` a esos catálogos.

Otra divergencia posible: si las fuentes JSON incluyeran `TR-OTROS`, JSON lo listaría y PostgreSQL no (QAF-9). Hoy no lo incluyen.

Diferencias aceptadas:
- PostgreSQL rechaza datos que JSON admite. La base rechaza una clave de insumo repetida o vacía. La carga inicial rechaza referencias que no se resuelven en lugar de descartarlas (QA-E3-5). El repository rechaza, con `PersistenciaError`, un usuario sin rol o con varios, y entonces falla todo el listado de usuarios (DE3-6, hasta DC27A).
- Con `medios_pago.json` vacío, JSON devuelve `[]`; con la tabla vacía, PostgreSQL devuelve los predeterminados (DE3-7).
- Un dato inválido en la base (por ejemplo `numeros_modelo` con un nulo) lanza `ValidationError`, mientras que JSON lo envuelve en `PersistenciaError`.
- El `uuid` y las fechas técnicas no se exponen.
- `TR-OTROS` existe como fila técnica en la base, pero no forma parte del catálogo.
- Un insumo dado de alta sin clave toma su código, por el trigger (QA-E3-6).

### 11.6 Resolución de DE3-5 a DE3-8

- **DE3-5:** opción (a). El stock queda para E5.
- **DE3-6:** se exige exactamente un rol.
- **DE3-7:** predeterminados.
- **DE3-8:** distinto de la recomendación de la sección 8. «Sin conexión» es 503 con su propio código (`PERSISTENCIA_SIN_CONEXION`), subclase de `PersistenciaNoDisponibleError`, en lugar de 500. Así sigue valiendo el contrato de E1, que espera `PersistenciaNoDisponibleError` cuando no hay servidor, y la diferencia queda en el código. El código HTTP definitivo se revisa en E8.

### 11.7 Riesgos residuales

Registrados en [`integracion-pendientes.md`](integracion-pendientes.md):
- **E3-1, QA-E3-6 y QA-E3-7:** la migración y las cargas en DEV/UAT (E8) necesitan un paso de identidad verificado para `clave` y para `orden`. Está prohibido aplicar la migración en un entorno remoto sin ese paso (sección 12.4).
- **E3-2 (corregido el diagnóstico):** el cierre de la lectura con `COMMIT` en lugar de `ROLLBACK` sí se distingue. Un ajuste de sesión (`set_config` con `is_local = false`) sobrevive a un `COMMIT` y se revierte con el `ROLLBACK`, aun en `READ ONLY`. Una prueba lo verifica. El `ROLLBACK` no libera los bloqueos advisory de sesión: eso lo impide el registro.
- **E3-3 / QA-E3-4:** el contador de L2 es por unidad de trabajo. Hay que resolverlo antes de conectar el pool a la aplicación (sección 12.4).
- **Límites del registro (QA-E3-1):** el registro es una red contra errores de programación, no un analizador de SQL ni una barrera completa. Una función definida por el usuario puede escribir o cambiar la sesión sin que el texto lo muestre, y la clasificación de `LECTURA` es por texto. Las otras barreras son el SQL estático revisado, la transacción `READ ONLY` de las lecturas fuera de un comando y los privilegios del rol (sección 12.3). No confundir con L8 de `integracion-pendientes.md` (`cerrar_pool` y `lifespan`).
- **M2:** `max_idle` y `check_connection` se ajustan con las mediciones de E8.

## 12. Correcciones posteriores a la QA independiente

La QA independiente de E3 (05/11/2026) concluyó **APPROVED WITH OBSERVATIONS**, sin hallazgos BLOCKER ni HIGH. La revisión de arquitectura pidió cerrar antes del commit QA-E3-1, QA-E3-2, QA-E3-3 y QA-E3-5, más los ajustes menores. Las correcciones no cambian reglas funcionales, la API, el frontend ni el comportamiento JSON.

Cada defecto se reprodujo antes de corregirlo con un script fuera del repositorio, contra la base local, y se repitió después.

### 12.1 Correcciones

| # | Defecto | Corrección | Antes | Después |
|---|---|---|---|---|
| QA-E3-1 | SQL que pasaba el registro cambiaba el estado de la sesión y contaminaba la conexión del pool | El registro rechaza `pg_settings`, `INTO` fuera de `INSERT INTO`, las funciones que ejecutan SQL recibido como texto (`query_to_xml` y familia, `ts_stat`, `ts_rewrite`), `pg_try_advisory_*`, `loread`/`lowrite`, `setval` y los esquemas `net`, `cron`, `vault` y `pgsodium`. `_devolver` cierra toda conexión que no quedó en `IDLE` | `UPDATE pg_settings` dejó en `READ ONLY` la transacción siguiente de la misma conexión; `query_to_xml` (con el nombre partido) y `pg_try_advisory_lock` dejaron 2 bloqueos advisory vivos | Los cuatro ataques no se registran, y la conexión queda sin bloqueos, tablas temporales ni ajustes de sesión |
| QA-E3-2 | Con dos conexiones ociosas cortadas, 500 genérico | Si el reemplazo también está cortado: `PersistenciaSinConexionError` (503), sin más intentos | `PersistenciaError` (500) | 503 `PERSISTENCIA_SIN_CONEXION`; el comando siguiente funciona con conexiones nuevas |
| QA-E3-3 | El lector podía escribir | `consulta(..., modo=LECTURA \| ESCRITURA)`, obligatoria. `LECTURA` no admite `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `RETURNING`, bloqueos de filas ni `nextval`, tampoco dentro de un `WITH`. El lector rechaza una `ESCRITURA` sin enviarla e invalida la transacción | Un `UPDATE … RETURNING` y un `WITH` con `INSERT`, ejecutados por el lector dentro de un comando, quedaron confirmados | El lector lanza `TypeError` sin ir al servidor y el comando se revierte; el `WITH` con `INSERT` no se registra como `LECTURA` |
| QA-E3-5 | El generador descartaba en silencio un insumo previsto con un id inexistente; la relación se buscaba solo por `clave` y la carga pisaba cualquier clave | El generador valida las referencias y se detiene con el detalle. La carga asocia por clave y código, solo completa claves provisorias y verifica al final cada fila de las fuentes | `node` terminó con 0 y generó la carga con la referencia huérfana | `node` termina con 1 y el mensaje «insumo previsto 2: no existe el insumo INS-404»; la verificación de la carga falla con el detalle |
| Ajuste | Un `KeyboardInterrupt` durante el `BEGIN` dejaba la conexión prestada y el contador desfasado | Una `BaseException` durante el `BEGIN` cierra la conexión y devuelve el contador. La limpieza de un `BEGIN` fallido no quedaba cubierta; se corrigió en la sección 13 (QAF-3) | `_en_uso = 1`, pool con 0 conexiones disponibles | `_en_uso = 0`, pool completo |
| Ajuste | La función del trigger tenía `EXECUTE` para PUBLIC | `revoke` para PUBLIC y para los roles de Supabase, como en la migración 1100 | `proacl` nulo (PUBLIC) | `{postgres=X/postgres}`; el trigger funciona igual |
| Ajuste | Documentación | Docstrings de `cerrar_pool` y `max_idle`; secciones 11.2 (alcance de M3), 11.5, 11.7 (E3-2 y la confusión con L8) y los conteos de 11.4 | — | — |

### 12.2 Pruebas nuevas y mutaciones

Pruebas de regresión:
- **`tests/test_e3_sql_y_ajustes.py`:**
  - los ataques confirmados y sus variantes (36 casos);
  - las escrituras legítimas;
  - la clasificación: una `LECTURA` no puede escribir (14 casos), las lecturas legítimas se registran y el modo es obligatorio.
- **`tests/postgres/test_ejecutor_sql.py`:**
  - el lector rechaza escrituras dentro de un comando y en una lectura breve;
  - fuera de un comando, la transacción `READ ONLY` frena lo que el registro no ve;
  - las lecturas y escrituras autorizadas funcionan;
  - un error SQL del lector invalida el comando;
  - E3-2: la lectura termina con `ROLLBACK`;
  - los ataques confirmados no se registran y los catálogos dejan la sesión limpia;
  - control del control: forzados, los mismos ataques sí contaminan la conexión, y la verificación lo ve;
  - el segundo corte da 503 y el pool se recupera;
  - la interrupción en el `BEGIN`;
  - la función del trigger sin `EXECUTE` para el rol de la aplicación.
- **`tests/test_generador_cargas.py` (Node, sin base):**
  - la carga versionada es la que genera el script;
  - siete referencias o identidades inválidas detienen la generación;
  - cada insumo previsto de las fuentes queda en la carga.
- **`tests/postgres/test_cargas_iniciales.py`:** escenarios A y B, una identidad existente que no se pisa, un insumo ajeno que no recibe relaciones aun aplicando la carga sentencia por sentencia, e idempotencia.

**Mutaciones:** se reintrodujo cada defecto, de a uno, y alguna prueba nueva falló en los 14 casos. Los archivos se restauraron y se verificó su hash.
- Registro: `pg_settings`, `SELECT INTO`, `query_to_xml`, `pg_try_advisory` y la clasificación.
- Unidad de trabajo:
  - segundo corte con 500;
  - lector que acepta escrituras;
  - interrupción sin descartar;
  - lectura con `COMMIT`.
- Cargas:
  - generador sin validar;
  - carga que pisa identidades;
  - relación solo por clave;
  - carga sin verificación.
- Migración: función con `EXECUTE` para PUBLIC.

El cierre de una conexión que no quedó en `IDLE` (`_devolver`) no tiene una prueba que lo aísle. El pool también revierte esas conexiones, así que no hay un escenario observable que lo distinga.

### 12.3 Privilegios efectivos y política mínima antes de E8

Medido en local (PostgreSQL 17.10) con un usuario de inicio de sesión miembro de `rma_backend`, es decir, con lo que hereda de PUBLIC:

| Privilegio | Efectivo |
|---|---|
| `TEMP` en la base | sí (PUBLIC) |
| `CREATE` en la base o en `public` | no |
| `UPDATE` sobre `pg_settings` | sí (PUBLIC) |
| `EXECUTE` de `set_config`, `query_to_xml`, `ts_stat`, `pg_advisory_lock`, `lo_from_bytea`, `pg_notify`, `pg_sleep` | sí (PUBLIC) |
| `pg_terminate_backend` | sí, sobre los procesos de su mismo rol |
| `lo_import` del servidor, `pg_read_file` | no |
| `EXECUTE` de las funciones de `rma` (salvo `verificar_integridad`) | no |

Los privilegios de `rma_backend` no impiden ninguno de los ataques de QA-E3-1: los permite PUBLIC. En Supabase, revocar privilegios de `pg_catalog` requiere un superusuario que el proyecto no tiene. Además, con Supavisor en modo transacción, el estado de sesión quedaría en una conexión del servidor que comparten otros clientes. Por eso la defensa es la prevención: registro, SQL estático y revisión.

**Política mínima propuesta para E8** (a decidir con autorización; no se aplica nada remoto en E3):
1. El usuario de conexión (`rma_api`) solo es miembro de `rma_backend`, sin `CREATE` en ningún esquema ni en la base. Verificarlo en DEV/UAT con la misma consulta de `has_*_privilege` usada aquí.
2. Evaluar `REVOKE TEMPORARY ON DATABASE … FROM PUBLIC`, concediéndolo de nuevo a los roles de Supabase que lo usen. Si afecta a servicios de Supabase, se acepta el riesgo con el registro como barrera.
3. `pg_settings` y las funciones de `pg_catalog` quedan como están: no son modificables sin superusuario. La barrera es el registro.
4. Mantener los `SET LOCAL` de cada transacción como tope de tiempos. Evaluar además `idle_in_transaction_session_timeout` para el rol.

### 12.4 Registrados sin implementar

- **QA-E3-4 (contador de L2 por unidad de trabajo).** Hoy no es un defecto: la aplicación no crea ningún pool ni ninguna `UnidadDeTrabajoPostgres`, y `RMA_PERSISTENCIA=postgres` detiene el arranque. Con dos unidades sobre el mismo pool, la clasificación se confunde: la QA lo reprodujo. **Debe resolverse antes de conectar los repositories a un pool compartido.** Eso pasa al cablear PostgreSQL en la aplicación (`lifespan`, E7 o E9), o antes si otro componente usa el mismo pool. Opciones:
  - clasificar con el estado del propio pool;
  - imponer, y verificar con una prueba, una sola unidad por pool.
- **QA-E3-6 (el trigger de `clave` acepta cargas que no la informan).** Una carga que omita `clave` deja el código como identidad del dominio sin fallar; el error aparece recién al usar el insumo. **Está prohibido aplicar la migración de E3 en un entorno remoto sin una estrategia de identidad verificada.** La estrategia debe incluir:
  - un inventario previo de `rma.insumo` remoto, buscando códigos que choquen con ids del dominio de otro insumo;
  - asignar la clave desde las fuentes, emparejando por código y solo donde `clave = codigo`;
  - verificar conjuntos y cantidades de `(clave, codigo)` y de los insumos previstos;
  - decidir antes de la carga si el trigger se quita o pasa a fallar;
  - aplicarlo todo en una transacción con `ON_ERROR_STOP`.
- **QA-E3-7 (orden en DEV/UAT).** `db push` no ejecuta las cargas: las filas remotas quedarían con `orden = 0` y los usuarios y medios de pago saldrían en orden alfabético. El paso de datos de E8 completa `orden` desde las fuentes y lo verifica.

## 13. QA final y última ronda de correcciones

La QA final de E3, con dos revisores independientes, concluyó **NOT APPROVED** por QAF-1:
- QA-E3-2 y QA-E3-5 quedaron confirmados como corregidos;
- QA-E3-1 y QA-E3-3 solo en parte, porque una variante con comillas esquivaba el registro.

Esta ronda corrige QAF-1 a QAF-4 y QAF-8, protege la migración (QAF-13), corrige la documentación (QAF-10) y registra el resto. Cada defecto se reprodujo antes y después con un script fuera del repositorio, contra la base local.

### 13.1 Correcciones

| # | Defecto | Corrección | Antes | Después |
|---|---|---|---|---|
| QAF-1 | Al quitar las comillas dobles, la palabra anterior quedaba pegada al nombre (`ALL"set_config"` se leía `ALLset_config`), y ninguna regla la reconocía, ni las de sesión ni las de escritura | Las comillas pasan a ser un espacio | `ALL"set_config"`, `NOT"pg_try_advisory_lock"`, `ALL"query_to_xml"`, `ALL"pg_terminate_backend"`, `ALL"setval"`, `ALL"lo_from_bytea"`, `UPDATE ONLY"pg_settings"` y `AS "x"INTO TEMP` se registraban en los dos modos; `ALL"nextval"` y `FOR"update"` como `LECTURA` | Todas rechazadas; `nextval` y `FOR UPDATE` solo se admiten como `ESCRITURA` |
| QAF-2 | `insert` usado como alias habilitaba `INTO` (`SELECT 1 AS insert INTO TEMP t`) | `INTO` solo tras un `INSERT` en posición de sentencia (al principio o tras un paréntesis). `INTO TEMP`, `TEMPORARY`, `UNLOGGED` o `TABLE` se rechazan siempre, igual que `pg_temp` | Se registraban | Se rechazan |
| QAF-3 | Una `BaseException` durante el `ROLLBACK` de un `BEGIN` fallido dejaba la conexión prestada: después, todo daba 503 «pool agotado» | Se revisó todo el ciclo. La interrupción en esa limpieza, entre el `BEGIN` y el bloque, o al contar la conexión entregada cierra la conexión o la devuelve, y el contador vuelve atrás | `_en_uso = 1`, 0 conexiones disponibles, el comando siguiente da 503 | `_en_uso = 0`, pool completo, el comando siguiente funciona |
| QAF-4 | `pg_sleep_for` y `pg_sleep_until` pasaban | `pg_sleep` pasa a ser un prefijo | Se registraban | Se rechazan |
| QAF-8 | El bloque de stock de la carga de desarrollo buscaba el insumo solo por código. Aplicada la carga sentencia por sentencia, registraba el ingreso sobre otra identidad | Antes de tocar el stock, el bloque confirma la clave y el código de cada insumo de las fuentes; si alguno no coincide, falla sin registrar nada. Además cruza por clave y código | 1 movimiento sobre la fila `INS-777` | 0 movimientos, con el error «stock inicial sin registrar, insumos sin su clave y su código: INS-001 / BAT-IP14» |
| QAF-13 | La migración de E3 se aplicaría con un `db push` genérico a DEV/UAT | Guarda al principio de la migración (13.3) | Se aplicaba sobre una base con datos | Falla sin cambiar nada, salvo con la autorización explícita del paso de E8 |
| QAF-10 | Documentación | Encabezado de tabla huérfano en 11.4. La condición de orden de QA-E3-8 es por id del dominio (en insumos, la `clave`), no por código. `ESTADO_PROYECTO.md` sigue en «Pendiente» hasta el cierre: no se modifica | — | — |

Los riesgos, con su estado, están en [`integracion-pendientes.md`](integracion-pendientes.md):
- QAF-5: las cargas son inicializadores, no sincronizaciones (13.2);
- QAF-6: con fuentes vacías, el SQL es inválido y falla al aplicar;
- QAF-7: no se validan `activo` ni la precisión monetaria;
- QAF-9: `TR-OTROS` en las fuentes;
- QAF-11: `orden` por defecto en filas nuevas;
- QAF-12: un código vacío antes de migrar.

**Pruebas nuevas:**
- **Registro:** comillas pegadas (15 casos en los dos modos y 6 de escrituras como `LECTURA`), `insert` como alias (8), las cuatro esperas, y las consultas legítimas con comillas o `INSERT` tras un `WITH`, que se siguen registrando.
- **Contra la base:**
  - las variantes con comillas ya no se registran;
  - forzadas, sí contaminan la conexión (control del control);
  - tres interrupciones de QAF-3;
  - el stock sobre otra identidad (QAF-8);
  - la guarda de la migración con datos de insumo, usuario o medio de pago, con un valor de autorización inválido y con el válido;
  - la base vacía, que no necesita autorización.

**Mutaciones:** se reintrodujo cada defecto, de a uno, con las 14 de la ronda anterior y 12 nuevas. Se detectaron 25 de 26. La restante (QAF-8: cruzar el stock solo por código, sin quitar la confirmación previa) es equivalente: el código es único y la confirmación ya exige que esa fila tenga la clave esperada. Quitar la confirmación sí se detecta. Los archivos se restauraron y se verificó su hash.

### 13.2 Cargas iniciales y sincronización (QAF-5)

`supabase/seeds` son **inicializadores**:
- crean lo que falta;
- solo completan dos cosas de lo existente: la clave provisoria de un insumo (`clave = codigo`) y el `orden` de usuarios y medios de pago;
- verifican que cada fila de las fuentes quedó con su identidad.

No son una sincronización:
- no aplican cambios de nombre, precio, estado ni stock;
- no quitan relaciones ni roles que ya no estén en las fuentes;
- volver a aplicarlas después de cambiar las fuentes puede pasar la verificación con la base distinta de las fuentes. Por ejemplo, un usuario puede quedar con dos roles, y entonces `listar_usuarios` falla.

Una sincronización de catálogos no se implementa en E3. Antes del paso de datos de E8, hay dos caminos:
- una verificación exacta: un rol por usuario, sin relaciones de más y atributos iguales;
- un procedimiento de una sola carga sobre una base sin esos datos.

### 13.3 Guarda de la migración y procedimiento seguro (QAF-13, QA-E3-6, QA-E3-7)

**Guarda.** La migración `20261105000100_e3_catalogos.sql` empieza con un bloque que falla si se cumplen las dos condiciones:
- ya hay filas en `rma.insumo`, `rma.usuario` o `rma.medio_pago`;
- la sesión no tiene `rma.migracion_e3 = 'estrategia_identidad_aprobada'`.

**Alcance y límites** (verificados en la QA focalizada):
- **Es una protección operativa contra un error, no un control de autorización.** La variable de sesión no prueba que alguien haya aprobado nada. Cualquiera que la configure la satisface:
  - un `SET` en la sesión;
  - `PGOPTIONS` u `options=-c …` en la conexión;
  - un `ALTER DATABASE … SET` o un `ALTER ROLE … SET`.

  Las dos últimas formas la dejan satisfecha en silencio para todas las sesiones siguientes.
- **No reemplaza la aprobación humana** del procedimiento de E8, que sigue siendo la condición de desbloqueo.
- **Depende de ejecutar el archivo en una única transacción.** Así la falla ocurre antes de cambiar nada y no quedan columnas, trigger ni restricciones a medias. Lo garantizan `supabase db push` (cada archivo es un lote transaccional), una única consulta, o `psql` con `-v ON_ERROR_STOP=1 --single-transaction`.
- **No protege al SQL ejecutado a mano fuera del procedimiento controlado.** Con un `psql -f` sin `ON_ERROR_STOP` ni `--single-transaction`, el error de la guarda no detiene las sentencias siguientes: la migración se aplica igual. Una falla posterior, como la de un código vacío (QAF-12), deja además cambios parciales.

Se mantiene la prohibición: la migración no se aplica en ningún entorno remoto antes de aprobar y verificar la estrategia de identidad.

Con la guarda, un `supabase db push` remoto falla sobre DEV/UAT si tiene datos. Si no los tiene, se aplica, y entonces no hay identidades que corregir y las cargas fijan la clave y el orden. Una base local, las pruebas o un entorno nuevo empiezan vacíos y no necesitan la autorización. No se modificó ninguna migración anterior ni ningún esquema remoto.

**Procedimiento seguro en E8,** con autorización y nunca con `db push` sobre una base con datos:
1. Inventario de solo lectura de `rma.insumo`, `rma.usuario` y `rma.medio_pago`. Buscar:
   - códigos vacíos (QAF-12);
   - códigos que coincidan con el id del dominio de otro insumo;
   - filas que no estén en las fuentes.
2. Preparar un único script, revisado, que en una sola transacción:
   - ejecute `set local rma.migracion_e3 = 'estrategia_identidad_aprobada'`;
   - aplique el contenido de la migración;
   - asigne `clave` desde las fuentes, emparejando por código y solo donde `clave = codigo`;
   - complete `orden` (QA-E3-7);
   - decida el trigger de `clave`: quitarlo o hacerlo fallar (QA-E3-6);
   - verifique conjuntos y cantidades de `(clave, codigo)`, de los insumos previstos y de `orden`, y falle si algo no coincide.
3. Ejecutarlo con `psql -v ON_ERROR_STOP=1 --single-transaction`.
4. Registrar la migración como aplicada con `supabase migration repair --status applied 20261105000100`. Comprobar antes que la guarda no impida ese registro.

**Condición de desbloqueo:** en E8, con la estrategia de identidad aprobada por escrito, el inventario revisado y el script anterior probado sobre una copia o una base local con los mismos datos. Hasta entonces la migración no se aplica en ningún entorno remoto. La autorización se pone solo con `set local` dentro de ese script, nunca a nivel de base o de rol.

### 13.4 Verificación focalizada y cierre

La verificación final focalizada, hecha por un revisor independiente, concluyó **APPROVED WITH OBSERVATIONS** y **GO para el commit local**:
- verificó QAF-1, QAF-3, QAF-4 y QAF-8;
- verificó QAF-13 como guarda operativa;
- verificó QAF-2 en el caso reportado.

Encontró una variante de QAF-2, de severidad baja: `SELECT (1) insert INTO LOCAL TEMP t` se registraba, y forzada contra la base dejaba una tabla temporal en la conexión del pool. Se corrigió antes del commit:
- `INTO LOCAL` e `INTO GLOBAL` con `TEMP`, `TEMPORARY`, `UNLOGGED` o `TABLE` se rechazan siempre;
- un `INSERT` después de `)` solo cuenta como sentencia si la consulta empieza con `WITH`.

Las formas `INSERT INTO` y `WITH … INSERT` legítimas, y las 14 consultas registradas, siguen siendo válidas. Hay pruebas de regresión: en el registro, y contra la base, donde la variante no llega al servidor y, forzada, contamina la conexión. Reintroducir cada mitad de la corrección hace fallar las pruebas nuevas.

También se precisó el alcance de la guarda (13.3) y se registraron como condiciones de entrada de E4 los medios de pago predeterminados sin fila en la base y QAF-14 (`integracion-pendientes.md`).
