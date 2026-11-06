"""E3 sin base: registro de SQL, control estatico y topes de ajustes.

Diseno: ``docs/postgresql/e3-catalogos-diseno.md`` (secciones 3.3, 3.4 y
5.2).
"""

import ast
import math
import uuid
from pathlib import Path

import pytest

from app.core.config import Settings
from app.storage.postgres import (
    AjustesPostgres,
    ConfiguracionPersistenciaError,
    ajustes_postgres,
)
from app.storage.postgres.ajustes import MAXIMO_MS, MAXIMO_POOL
from app.storage.postgres.consultas import (
    ESCRITURA,
    LECTURA,
    PRIMERAS_PALABRAS,
    consulta,
    problema_de,
    registradas,
)
from app.storage.postgres.mapeo import decimal_sin_ceros

RAIZ_POSTGRES = Path(__file__).resolve().parents[1] / "app/storage/postgres"


def _nombre() -> str:
    return f"prueba_registro.{uuid.uuid4().hex}"


# --- Registro de consultas (QA-2, F-04) --------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "BEGIN",
        "begin",
        "START TRANSACTION",
        "COMMIT",
        "END",
        "ROLLBACK",
        "ABORT",
        "SAVEPOINT s",
        "RELEASE SAVEPOINT s",
        "PREPARE TRANSACTION 'x'",
        "SET search_path = public",
        "SET SESSION statement_timeout = 0",
        "SET LOCAL lock_timeout = 0",
        "SET TRANSACTION READ WRITE",
        "RESET ALL",
        "DISCARD ALL",
        "LOCK TABLE rma.insumo",
        "CALL rma.algo()",
        "DO 'select 1'",
        "COPY rma.insumo TO STDOUT",
        "LISTEN canal",
        "NOTIFY canal",
        "VACUUM",
        "CREATE TABLE x (id int)",
        "DROP TABLE rma.insumo",
        "TRUNCATE rma.insumo",
        "  (  commit  )",
        '"COMMIT"',
        "\n\tROLLBACK",
    ],
)
def test_el_registro_rechaza_control_transaccional_y_de_sesion(sql):
    for modo in (LECTURA, ESCRITURA):
        with pytest.raises(ValueError, match="no se registra"):
            consulta(_nombre(), sql, modo=modo)


@pytest.mark.parametrize(
    "sql",
    [
        "/* x */ COMMIT",
        "-- x\nCOMMIT",
        "SELECT 1 -- y COMMIT",
        "SELECT 1; COMMIT",
        "SELECT 1;",
        "SELECT $$x$$",
        "SELECT U&'\\0041'",
        "SELECT set_config('search_path', 'x', false)",
        "SELECT \"set_config\"('a', 'b', false)",
        "SELECT pg_catalog.set_config('a', 'b', false)",
        "SELECT pg_advisory_lock(1)",
        "SELECT pg_advisory_xact_lock(1)",
        "SELECT pg_sleep(10)",
        "SELECT dblink('x', 'y')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT pg_terminate_backend(1)",
        "SELECT pg_notify('c', 'p')",
        "WITH x AS (SELECT 1) SELECT set_config('a', 'b', false)",
    ],
)
def test_el_registro_rechaza_formas_de_esconder_sentencias_o_efectos(sql):
    for modo in (LECTURA, ESCRITURA):
        with pytest.raises(ValueError, match="no se registra"):
            consulta(_nombre(), sql, modo=modo)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT codigo FROM rma.insumo WHERE clave = %s",
        "  (SELECT 1)",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "INSERT INTO t (a) VALUES (%(a)s)",
        "UPDATE t SET a = %s WHERE id = %s",
        "DELETE FROM t WHERE id = %s",
        "SELECT id FROM rma.orden WHERE id = %s FOR UPDATE",
        "SELECT modelo_equipo FROM x",  # contiene 'lo_' sin ser lo_*
        "SELECT current_setting('lock_timeout')",
    ],
)
def test_el_registro_admite_las_consultas_validas(sql):
    registrada = consulta(_nombre(), sql, modo=ESCRITURA)
    assert registradas()[registrada.nombre] is registrada


def test_un_nombre_no_se_registra_dos_veces():
    nombre = _nombre()
    consulta(nombre, "SELECT 1", modo=LECTURA)
    with pytest.raises(ValueError, match="Ya hay"):
        consulta(nombre, "SELECT 2", modo=LECTURA)


# --- QA-E3-1: estado de sesion -----------------------------------------------
# Los ataques que confirmo la QA de E3 (se registraban y dejaban estado en la
# conexion del pool) y sus variantes. Contra la base, ver
# tests/postgres/test_ejecutor_sql.py.


@pytest.mark.parametrize(
    "sql",
    [
        # pg_settings: su UPDATE es set_config(..., false).
        "UPDATE pg_settings SET setting = %s WHERE name = %s",
        "UPDATE pg_catalog.pg_settings SET setting = %s WHERE name = %s",
        'UPDATE "pg_settings" SET setting = %s WHERE name = %s',
        "UPDATE PG_SETTINGS SET setting = %s WHERE name = %s",
        "SELECT name FROM pg_settings",
        "WITH x AS (UPDATE pg_settings SET setting = 'on' "
        "WHERE name = 'x' RETURNING name) SELECT * FROM x",
        # SELECT INTO: crea una tabla que sobrevive a la transaccion.
        "SELECT 1 AS x INTO TEMP qa_tmp",
        "SELECT 1 AS x INTO TEMPORARY qa_tmp",
        "SELECT 1 AS x INTO qa_tabla",
        "SELECT * INTO UNLOGGED qa_t FROM rma.insumo",
        "WITH x AS (SELECT 1 AS a) SELECT a INTO TEMP qa_t FROM x",
        "SELECT 1 AS x into temp qa_tmp",
        # SQL como texto: la concatenacion esquiva cualquier lista.
        "SELECT query_to_xml('select set_'||'config(''a'',''b'',false)', "
        "true, false, '')",
        "SELECT query_to_xml('select pg_advis'||'ory_lock(42)', "
        "true, false, '')",
        "SELECT query_to_xml('select lo_from'||'_bytea(0, ''x'')', "
        "true, false, '')",
        "SELECT pg_catalog.query_to_xml('select 1', true, false, '')",
        "SELECT query_to_xmlschema('select 1', true, false, '')",
        "SELECT query_to_xml_and_xmlschema('select 1', true, false, '')",
        "SELECT cursor_to_xml('c', 1, true, false, '')",
        "SELECT table_to_xml('rma.insumo', true, false, '')",
        "SELECT schema_to_xml('rma', true, false, '')",
        "SELECT database_to_xml(true, false, '')",
        "SELECT * FROM ts_stat('select 1')",
        "SELECT ts_rewrite('a'::tsquery, 'select 1')",
        # Bloqueos advisory de sesion, tambien los try.
        "SELECT pg_try_advisory_lock(43)",
        "SELECT pg_catalog.pg_try_advisory_xact_lock(1)",
        "SELECT pg_advisory_unlock_all()",
        # Objetos grandes.
        "SELECT lo_from_bytea(0, 'x')",
        "SELECT lo_creat(-1)",
        "SELECT loread(0, 1)",
        "SELECT lowrite(0, 'x')",
        # Fuera de la transaccion o fuera de la base.
        "SELECT setval('rma.secuencia', 1)",
        # Valor de la sesion, que en el pool es de otro comando (QAF-14).
        "SELECT currval('rma.orden_numero_seq')",
        "SELECT lastval()",
        "SELECT net.http_post('x')",
        "SELECT cron.schedule('x', 'y')",
        "SELECT vault.create_secret('x')",
        "SELECT http_get('x')",
    ],
)
def test_el_registro_rechaza_los_ataques_de_sesion(sql):
    for modo in (LECTURA, ESCRITURA):
        assert problema_de(sql, modo) is not None
        with pytest.raises(ValueError, match="no se registra"):
            consulta(_nombre(), sql, modo=modo)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t (a) SELECT a FROM u",
        "INSERT INTO t (a) VALUES (%s) RETURNING a",
        "WITH x AS (INSERT INTO t VALUES (1) RETURNING id) SELECT id FROM x",
        "SELECT nextval('rma.secuencia')",
        "SELECT setting_x FROM tabla_settings",  # no es pg_settings
        # INSERT en posicion de sentencia (QAF-2), tambien tras un WITH.
        "WITH a AS (SELECT 1 AS v) INSERT INTO t SELECT v FROM a",
        "(INSERT INTO t VALUES (1))",
        "WITH x AS (INSERT INTO t VALUES (1) RETURNING id) "
        "INSERT INTO u SELECT id FROM x",
        "WITH RECURSIVE a (v) AS (SELECT 1) INSERT INTO t SELECT v FROM a",
        # Comillas legitimas (QAF-1): identificadores y collation.
        'SELECT "codigo" FROM rma.insumo ORDER BY codigo COLLATE "C"',
        'SELECT x FROM "insert_log"',
        'INSERT INTO "t" ("a") VALUES (%s)',
    ],
)
def test_las_escrituras_legitimas_se_registran(sql):
    assert consulta(_nombre(), sql, modo=ESCRITURA).modo is ESCRITURA


# --- QAF-1: comillas dobles pegadas a una palabra ----------------------------
# Antes, quitar las comillas pegaba la palabra anterior al nombre
# (ALL"set_config" -> ALLset_config) y ninguna regla lo reconocia.


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT ALL"set_config"(%s, %s, false)',
        'SELECT NOT"pg_try_advisory_lock"(42)',
        'SELECT ALL"pg_advisory_lock"(42)',
        "SELECT ALL\"query_to_xml\"('select 1', true, false, '')",
        'SELECT ALL"pg_terminate_backend"(1)',
        'SELECT ALL"pg_cancel_backend"(1)',
        'UPDATE ONLY"pg_settings"SET setting = %s WHERE name = %s',
        'SELECT ALL"setval"(%s, 1)',
        'SELECT ALL"lo_from_bytea"(0, %s)',
        'SELECT ALL"pg_sleep"(1)',
        'SELECT ALL"pg_notify"(%s, %s)',
        'SELECT x FROM"pg_temp".t',
        'SELECT 1 AS "x"INTO TEMP t',
        'SELECT 1 AS"x"INTO"t"',
        'SELECT ALL"net".http_post(%s)',
    ],
)
def test_las_comillas_pegadas_no_esconden_nombres(sql):
    for modo in (LECTURA, ESCRITURA):
        assert problema_de(sql, modo) is not None, (modo, sql)
        with pytest.raises(ValueError, match="no se registra"):
            consulta(_nombre(), sql, modo=modo)


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT ALL"nextval"(%s)',
        'SELECT * FROM t FOR"update"',
        'SELECT * FROM t FOR"share"',
        'WITH x AS (SELECT 1)"insert" INTO t VALUES (1)',
        'SELECT 1 FROM"t"RETURNING"a"',
        'WITH x AS (UPDATE"t"SET a = 1 RETURNING a) SELECT a FROM x',
    ],
)
def test_las_comillas_pegadas_no_esconden_escrituras(sql):
    with pytest.raises(ValueError, match="no se registra"):
        consulta(_nombre(), sql, modo=LECTURA)


# --- QAF-2 y QAF-4 -----------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 AS insert INTO TEMP t",
        "SELECT 1 AS insert INTO t",
        "SELECT 1 insert INTO t",
        "SELECT 1 AS x, 2 AS insert INTO t FROM u",
        "SELECT (1) insert INTO TEMP t",
        "SELECT (1) insert INTO pg_temp.t",
        'SELECT x."insert" INTO t FROM x',
        "INSERT INTO t SELECT 1 AS insert INTO TEMP u",
        # Verificacion focalizada: tras ')' y con LOCAL o GLOBAL.
        "SELECT (1) insert INTO LOCAL TEMP t",
        'SELECT (1)"insert"INTO LOCAL TEMP t',
        "SELECT (1) insert INTO GLOBAL TEMPORARY t",
        "SELECT (1) insert INTO LOCAL TEMPORARY t",
        "SELECT (1) insert INTO t",
        "SELECT * FROM (SELECT 1 AS a) s insert INTO t",
        "WITH x AS (SELECT 1) SELECT (1) insert INTO LOCAL TEMP t",
        "SELECT 1 INTO GLOBAL TEMP t",
        "SELECT 1 into local temp t",
    ],
)
def test_insert_como_alias_no_autoriza_into(sql):
    with pytest.raises(ValueError, match="no se registra"):
        consulta(_nombre(), sql, modo=ESCRITURA)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(1)",
        "SELECT pg_sleep_for(%s)",
        "SELECT pg_sleep_until(%s)",
        "SELECT pg_catalog.pg_sleep_for('1 second')",
    ],
)
def test_todas_las_esperas_se_rechazan(sql):
    for modo in (LECTURA, ESCRITURA):
        with pytest.raises(ValueError, match="pg_sleep"):
            consulta(_nombre(), sql, modo=modo)


# --- QA-E3-3: clasificacion de lectura y escritura ---------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        "DELETE FROM t",
        "UPDATE t SET a = 1 RETURNING a",
        "WITH x AS (INSERT INTO t VALUES (1) RETURNING id) SELECT id FROM x",
        "WITH x AS (UPDATE t SET a = 1 RETURNING a) SELECT a FROM x",
        "WITH x AS (DELETE FROM t RETURNING a) SELECT * FROM x",
        "with x as (insert into t values (1) returning id) select id from x",
        "SELECT * FROM t FOR UPDATE",
        "SELECT * FROM t FOR NO KEY UPDATE",
        "SELECT * FROM t FOR SHARE",
        "SELECT * FROM t FOR KEY SHARE",
        "SELECT * FROM t\nFOR\nUPDATE SKIP LOCKED",
        "SELECT nextval('rma.secuencia')",
    ],
)
def test_una_lectura_no_puede_escribir(sql):
    with pytest.raises(ValueError, match="lectura"):
        consulta(_nombre(), sql, modo=LECTURA)
    assert consulta(_nombre(), sql, modo=ESCRITURA).modo is ESCRITURA


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT codigo FROM rma.insumo WHERE clave = %s",
        "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
        "SELECT modificado_en, insert_total, fecha_update FROM x",
        "SELECT array_agg(r.codigo) FILTER (WHERE r.codigo IS NOT NULL) "
        "FROM r",
    ],
)
def test_las_lecturas_legitimas_se_registran(sql):
    assert consulta(_nombre(), sql, modo=LECTURA).modo is LECTURA


def test_la_clasificacion_es_explicita():
    with pytest.raises(TypeError):
        consulta(_nombre(), "SELECT 1")  # sin modo
    with pytest.raises(ValueError, match="LECTURA o ESCRITURA"):
        consulta(_nombre(), "SELECT 1", modo="lectura")


def test_la_lista_permitida_es_solo_dml():
    assert PRIMERAS_PALABRAS == {
        "SELECT",
        "WITH",
        "INSERT",
        "UPDATE",
        "DELETE",
    }


# --- Control estatico (QA-2, QA-3) -------------------------------------------


def _modulos_postgres():
    return sorted(RAIZ_POSTGRES.glob("*.py"))


def test_todo_el_sql_registrado_de_los_repositories_es_valido():
    """Importar los repositories registra su SQL: todo pasa la validacion
    y queda enumerable."""
    pytest.importorskip("psycopg_pool")
    import app.storage.postgres.catalogos  # noqa: F401
    import app.storage.postgres.modelos_equipo  # noqa: F401

    propias = {
        nombre: c
        for nombre, c in registradas().items()
        if nombre.split(".")[0] in ("catalogos", "modelos_equipo")
    }
    assert all(problema_de(c.sql, c.modo) is None for c in propias.values())
    # Los catalogos solo leen (QA-E3-3), salvo el stock, que E5 escribe en
    # el libro: bloquear insumos (A6) y registrar ingresos y ajustes (A7).
    del_stock = {
        "catalogos.bloquear_insumos",
        "catalogos.stock_de",
        "catalogos.insertar_movimiento_stock",
        "catalogos.usuario_id",
    }
    assert {
        n for n, c in propias.items() if c.modo is not LECTURA
    } == del_stock
    # 12 de catalogos, el historial de stock (A7), 2 de modelos y el stock.
    assert len(propias) == 15 + len(del_stock)


def test_solo_la_unidad_de_trabajo_toca_la_conexion_y_la_transaccion():
    """Fuera de ``transaccion.py`` ningun modulo de storage/postgres usa la
    conexion interna ni controla la transaccion; los repositories no
    importan psycopg."""
    prohibidos = {"_conexion_actual", "commit", "rollback", "conexion"}
    repositories = {
        "catalogos.py",
        "modelos_equipo.py",
        "ordenes.py",
        "ordenes_lectura.py",
        "acciones.py",
    }
    hallazgos = []
    for archivo in _modulos_postgres():
        if archivo.name == "transaccion.py":
            continue
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Attribute) and nodo.attr in prohibidos:
                if archivo.name in repositories or nodo.attr != "conexion":
                    hallazgos.append((archivo.name, nodo.attr))
            if archivo.name in repositories and isinstance(
                nodo, ast.Import | ast.ImportFrom
            ):
                modulos = (
                    [a.name for a in nodo.names]
                    if isinstance(nodo, ast.Import)
                    else [nodo.module or ""]
                )
                if any(m.split(".")[0] == "psycopg" for m in modulos):
                    hallazgos.append((archivo.name, "import psycopg"))
    assert hallazgos == []


def test_los_repositories_solo_ejecutan_consultas_registradas():
    """Cada llamada a filas/fila en un repository recibe una constante de
    modulo creada con consulta(...)."""
    for nombre in (
        "catalogos.py",
        "modelos_equipo.py",
        "ordenes.py",
        "ordenes_lectura.py",
        "acciones.py",
    ):
        arbol = ast.parse((RAIZ_POSTGRES / nombre).read_text(encoding="utf-8"))
        registradas_ = {
            objetivo.id
            for nodo in arbol.body
            if isinstance(nodo, ast.Assign)
            and isinstance(nodo.value, ast.Call)
            and getattr(nodo.value.func, "id", None) == "consulta"
            for objetivo in nodo.targets
        }
        assert registradas_, nombre
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.Call)
                and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr in ("filas", "fila", "_filas", "_fila")
                and nodo.args
                and isinstance(nodo.args[0], ast.Name)
                and nodo.args[0].id != "consulta_"
            ):
                assert nodo.args[0].id in registradas_, (nombre, nodo.lineno)


# --- Topes de ajustes (L1) y max_idle ----------------------------------------


@pytest.mark.parametrize(
    "valores",
    [
        {"lock_timeout_ms": MAXIMO_MS + 1},
        {"statement_timeout_ms": MAXIMO_MS + 1},
        {"pool_max": MAXIMO_POOL + 1},
        {"pool_espera_s": math.inf},
        {"pool_espera_s": math.nan},
        {"pool_max_idle_s": 0},
        {"pool_max_idle_s": math.inf},
    ],
)
def test_un_ajuste_fuera_de_rango_detiene_el_arranque(valores):
    ajustes = AjustesPostgres(**valores)
    from app.storage.postgres.ajustes import validar_ajustes

    with pytest.raises(ConfiguracionPersistenciaError):
        validar_ajustes(ajustes)


def test_los_topes_se_aceptan_justo_en_el_limite():
    from app.storage.postgres.ajustes import validar_ajustes

    validar_ajustes(
        AjustesPostgres(
            pool_max=MAXIMO_POOL,
            lock_timeout_ms=MAXIMO_MS,
            statement_timeout_ms=MAXIMO_MS,
        )
    )


def test_max_idle_se_lee_del_entorno(monkeypatch):
    monkeypatch.setenv("RMA_DB_POOL_MAX_IDLE_S", "120")
    assert ajustes_postgres(Settings(_env_file=None)).pool_max_idle_s == 120
    assert AjustesPostgres().pool_max_idle_s == 300


# --- Representacion numerica (DE3-3) -----------------------------------------


@pytest.mark.parametrize(
    ("de_la_base", "esperado"),
    [
        ("80000.00", "80000"),
        ("0.00", "0"),
        ("2.000", "2"),
        ("1.500", "1.5"),
        ("12345.50", "12345.5"),
        ("0.250", "0.25"),
        ("999999999999.99", "999999999999.99"),
        ("999999999.999", "999999999.999"),
        ("100000000000.00", "100000000000"),
        ("-3.10", "-3.1"),
    ],
)
def test_los_numeros_salen_sin_ceros_de_mas_ni_exponente(de_la_base, esperado):
    from decimal import Decimal

    valor = decimal_sin_ceros(Decimal(de_la_base))
    assert str(valor) == esperado
    assert valor == Decimal(de_la_base)


def test_un_numero_no_finito_o_no_decimal_se_rechaza():
    from decimal import Decimal

    with pytest.raises(ValueError):
        decimal_sin_ceros(Decimal("NaN"))
    with pytest.raises(TypeError):
        decimal_sin_ceros(1.5)
