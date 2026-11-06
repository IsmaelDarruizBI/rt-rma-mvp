"""Ejecutor SQL restringido, lectura breve y pool (E3-A).

Contra la base local descartable. Diseno:
``docs/postgresql/e3-catalogos-diseno.md`` (secciones 3 y 5).
"""

import asyncio
import contextvars
import logging
import threading
import time
import uuid
from datetime import datetime
from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.repositories.exceptions import (  # noqa: E402
    PersistenciaError,
    PersistenciaNoDisponibleError,
    PersistenciaSinConexionError,
    TransaccionInvalidadaError,
)
from app.storage.postgres import (  # noqa: E402
    AjustesPostgres,
    conectar,
    configuracion_postgres,
)
from app.storage.postgres import consultas as registro  # noqa: E402
from app.storage.postgres.consultas import (  # noqa: E402
    ESCRITURA,
    LECTURA,
    Consulta,
    consulta,
)
from app.storage.postgres.transaccion import (  # noqa: E402
    _EN_CURSO,
    UnidadDeTrabajoPostgres,
    abrir_pool,
    cerrar_pool,
)

_INSERTAR = consulta(
    "prueba_ejecutor.insertar",
    "INSERT INTO prueba_ejecutor.registro (id, valor) VALUES (%s, %s)",
    modo=ESCRITURA,
)
_INSERTAR_VARIOS = consulta(
    "prueba_ejecutor.insertar_varios",
    "INSERT INTO prueba_ejecutor.registro (id, valor) VALUES (%s, %s)",
    modo=ESCRITURA,
)
_TODOS = consulta(
    "prueba_ejecutor.todos",
    "SELECT id, valor FROM prueba_ejecutor.registro ORDER BY id",
    modo=LECTURA,
)
_UNO = consulta(
    "prueba_ejecutor.uno",
    "SELECT id, valor FROM prueba_ejecutor.registro WHERE id = %(id)s",
    modo=LECTURA,
)
_ACTUALIZAR = consulta(
    "prueba_ejecutor.actualizar",
    "UPDATE prueba_ejecutor.registro SET valor = %s RETURNING id",
    modo=ESCRITURA,
)
_PID = consulta(
    "prueba_ejecutor.pid", "SELECT pg_backend_pid() AS pid", modo=LECTURA
)
_AJUSTE = consulta(
    "prueba_ejecutor.ajuste",
    "SELECT current_setting(%s) AS valor",
    modo=LECTURA,
)
_DIVISION = consulta(
    "prueba_ejecutor.division", "SELECT 1 / 0 AS nada", modo=LECTURA
)
_TIPOS = consulta(
    "prueba_ejecutor.tipos",
    """
    SELECT 7::integer AS entero, 1.50::numeric(5, 2) AS decimal,
           '2026-11-05 12:00:00+00'::timestamptz AS instante,
           'texto'::text AS texto, true AS logico,
           'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'::uuid AS uuid,
           '{a,b}'::text[] AS lista
    """,
    modo=LECTURA,
)


@pytest.fixture(scope="module")
def base(postgres_descartable):
    configuracion = configuracion_postgres(
        Settings(
            _env_file=None,
            persistencia="postgres",
            database_url=postgres_descartable,
        )
    )
    with conectar(configuracion, autocommit=True) as conexion:
        conexion.execute(
            "create schema prueba_ejecutor; create table "
            "prueba_ejecutor.registro (id integer primary key, valor text)"
        )
    yield configuracion
    with conectar(configuracion, autocommit=True) as conexion:
        conexion.execute("drop schema prueba_ejecutor cascade")


@pytest.fixture
def armar(base):
    pools = []
    with conectar(base, autocommit=True) as conexion:
        conexion.execute("truncate prueba_ejecutor.registro")

    def _armar(**valores):
        ajustes = AjustesPostgres(**{"pool_max": 1, **valores})
        pool = abrir_pool(base, ajustes)
        pool.wait(10)
        pools.append(pool)
        return UnidadDeTrabajoPostgres(pool, ajustes), pool

    yield _armar
    for pool in pools:
        pool.close()


def _ids(base) -> list[int]:
    with conectar(base, autocommit=True) as conexion:
        filas = conexion.execute(
            "select id from prueba_ejecutor.registro order by id"
        ).fetchall()
    return [fila[0] for fila in filas]


def _estable(pool):
    """El pool sin conexiones prestadas (espera reposiciones)."""
    for _ in range(100):
        estadisticas = pool.get_stats()
        if estadisticas["pool_available"] == estadisticas["pool_size"]:
            return True
        time.sleep(0.05)
    return False


# --- Lectura breve (DE3-4) ---------------------------------------------------


def test_fuera_de_un_comando_la_lectura_es_breve_y_de_solo_lectura(
    armar,
):
    unidad, pool = armar()
    with unidad.lectura() as lector:
        assert unidad.en_curso()
        solo = lector.fila(_AJUSTE, ("transaction_read_only",)).valor
        bloqueo = lector.fila(_AJUSTE, ("lock_timeout",)).valor
        # Las consultas de un agregado ven el mismo instante (DA-4).
        aislamiento = lector.fila(_AJUSTE, ("transaction_isolation",)).valor
        assert not hasattr(lector, "ejecutar")
        with pytest.raises(PersistenciaError, match="solo lectura"):
            unidad.ejecutor()
        with pytest.raises(PersistenciaError, match="dentro de una lectura"):
            with unidad.transaccion():
                pass
    assert (solo, bloqueo) == ("on", "5s")
    assert aislamiento == "repeatable read"
    assert not unidad.en_curso() and _EN_CURSO.get() is None
    assert _estable(pool)
    # Los SET LOCAL no pasan a la conexion.
    with pool.connection() as conexion:
        assert conexion.execute("show lock_timeout").fetchone()[0] == "0"
        assert conexion.info.transaction_status.name == "IDLE"


def test_dentro_de_un_comando_la_lectura_usa_su_transaccion(armar, base):
    unidad, pool = armar()
    with unidad.transaccion():
        unidad.ejecutor().ejecutar(_INSERTAR, (1, "uno"))
        pid = unidad.ejecutor().fila(_PID).pid
        with unidad.lectura() as lector:
            assert lector.fila(_PID).pid == pid
            assert lector.fila(_UNO, {"id": 1}).valor == "uno"
            solo = lector.fila(_AJUSTE, ("transaction_read_only",)).valor
        # La transaccion sigue siendo de escritura.
        unidad.ejecutor().ejecutar(_INSERTAR, (2, "dos"))
    assert solo == "off"
    assert _ids(base) == [1, 2]


def test_una_excepcion_en_la_lectura_libera_todo(armar):
    unidad, pool = armar()
    with pytest.raises(LookupError):
        with unidad.lectura():
            raise LookupError("del repository")
    assert _EN_CURSO.get() is None and _estable(pool)


# --- Ejecutor: consultas, vigencia y propiedad (QA-2, QA-3) ------------------


def test_fuera_de_una_transaccion_no_hay_ejecutor(armar):
    unidad, _ = armar()
    with pytest.raises(PersistenciaError, match="fuera de una transaccion"):
        unidad.ejecutor()


@pytest.mark.parametrize(
    "no_registrada",
    [
        "SELECT 1",
        sql.SQL("SELECT 1"),
        Consulta(nombre="prueba_ejecutor.todos", sql="SELECT 1", modo=LECTURA),
    ],
    ids=["str", "sql.SQL", "Consulta suelta"],
)
def test_solo_se_ejecutan_consultas_registradas(armar, no_registrada):
    unidad, _ = armar()
    with unidad.transaccion():
        with pytest.raises(TypeError, match="registradas"):
            unidad.ejecutor().filas(no_registrada)


def test_ejecutar_y_lote_dentro_de_un_comando(armar, base):
    unidad, _ = armar()
    with unidad.transaccion():
        ejecutor = unidad.ejecutor()
        assert ejecutor.ejecutar(_INSERTAR, (1, "uno")) == 1
        ejecutor.ejecutar_lote(_INSERTAR_VARIOS, [(2, "dos"), (3, None)])
        filas = ejecutor.filas(_TODOS)
    assert [tuple(f) for f in filas] == [(1, "uno"), (2, "dos"), (3, None)]
    assert _ids(base) == [1, 2, 3]


def test_un_ejecutor_guardado_no_sirve_despues_del_cierre(armar, base):
    unidad, _ = armar()
    with unidad.transaccion():
        ejecutor = unidad.ejecutor()
    with unidad.lectura() as lector:
        guardado_lector = lector
    for viejo in (ejecutor, guardado_lector):
        with pytest.raises(PersistenciaError, match="otra transaccion"):
            viejo.filas(_TODOS)
    # Ni dentro de una transaccion nueva del mismo flujo.
    with unidad.transaccion():
        with pytest.raises(PersistenciaError, match="otra transaccion"):
            ejecutor.ejecutar(_INSERTAR, (9, "no"))
    assert _ids(base) == []


def test_un_hilo_heredero_no_usa_el_ejecutor(armar, base):
    unidad, _ = armar()
    vistos = []
    with unidad.transaccion():
        ejecutor = unidad.ejecutor()
        copia = contextvars.copy_context()

        def heredero():
            try:
                ejecutor.ejecutar(_INSERTAR, (5, "ajeno"))
                vistos.append("escribio")
            except PersistenciaError as error:
                vistos.append(str(error))

        hilo = threading.Thread(target=copia.run, args=(heredero,))
        hilo.start()
        hilo.join(10)
        ejecutor.ejecutar(_INSERTAR, (1, "propio"))
    assert len(vistos) == 1 and "otro hilo o tarea" in vistos[0]
    assert _ids(base) == [1]


def test_una_tarea_concurrente_no_usa_el_lector(armar):
    unidad, _ = armar()
    vistos = []

    async def tarea(lector):
        try:
            lector.filas(_TODOS)
            vistos.append("leyo")
        except PersistenciaError as error:
            vistos.append(str(error))

    async def caso_de_uso():
        with unidad.lectura() as lector:
            pendiente = asyncio.create_task(tarea(lector))
            await asyncio.sleep(0)
            await pendiente

    asyncio.run(caso_de_uso())
    assert len(vistos) == 1 and "otro hilo o tarea" in vistos[0]


def test_tras_un_error_sql_no_se_ejecuta_nada_mas(armar, base, monkeypatch):
    unidad, _ = armar()
    enviados = []
    with pytest.raises(TransaccionInvalidadaError):
        with unidad.transaccion():
            ejecutor = unidad.ejecutor()
            ejecutor.ejecutar(_INSERTAR, (1, "uno"))
            with pytest.raises(PersistenciaError):
                ejecutor.fila(_DIVISION)
            conexion = unidad._conexion_actual()
            monkeypatch.setattr(
                conexion, "cursor", lambda *a, **k: enviados.append(a)
            )
            with pytest.raises(TransaccionInvalidadaError, match="ya fallo"):
                ejecutor.ejecutar(_INSERTAR, (2, "dos"))
    assert enviados == []  # no fue al servidor
    assert _ids(base) == []  # y no se confirmo nada


def test_varias_sentencias_forzadas_las_rechaza_el_servidor(armar, base):
    """Ni el registro las admite; a la fuerza, el protocolo extendido."""
    unidad, _ = armar()
    forzada = Consulta(
        nombre=f"prueba_ejecutor.forzada_{uuid.uuid4().hex}",
        sql="INSERT INTO prueba_ejecutor.registro VALUES (7, 'x'); COMMIT",
        modo=ESCRITURA,
    )
    registro._REGISTRO[forzada.nombre] = forzada  # salteando la validacion
    try:
        with pytest.raises(TransaccionInvalidadaError):
            with unidad.transaccion():
                with pytest.raises(PersistenciaError):
                    unidad.ejecutor().ejecutar(forzada)
    finally:
        del registro._REGISTRO[forzada.nombre]
    assert _ids(base) == []


def test_los_resultados_no_exponen_la_conexion(armar):
    unidad, _ = armar()
    with unidad.lectura() as lector:
        fila = lector.fila(_TIPOS)
        filas = lector.filas(_TIPOS)
    assert isinstance(fila, tuple) and isinstance(filas, list)
    publicos = {n for n in dir(lector) if not n.startswith("_")}
    assert publicos == {"filas", "fila"}
    publicos_ejecutor = set()
    with unidad.transaccion():
        publicos_ejecutor = {
            n for n in dir(unidad.ejecutor()) if not n.startswith("_")
        }
    assert publicos_ejecutor == {"filas", "fila", "ejecutar", "ejecutar_lote"}
    assert not hasattr(unidad, "conexion_actual")


def test_los_tipos_en_binario_son_los_del_protocolo_de_texto(armar, base):
    unidad, _ = armar()
    with unidad.lectura() as lector:
        binario = tuple(lector.fila(_TIPOS))
    with conectar(base, autocommit=True) as conexion:
        texto = conexion.execute(_TIPOS.sql).fetchone()
    assert binario == texto
    assert [type(v) for v in binario] == [
        int,
        Decimal,
        datetime,
        str,
        bool,
        uuid.UUID,
        list,
    ]


# --- QA-E3-3: el lector solo lee ---------------------------------------------


def _forzada(sql_, modo):
    """Una consulta en el registro SIN pasar su validacion (solo pruebas)."""
    forzada = Consulta(
        nombre=f"prueba_ejecutor.forzada_{uuid.uuid4().hex}",
        sql=sql_,
        modo=modo,
    )
    registro._REGISTRO[forzada.nombre] = forzada
    return forzada


def test_el_lector_rechaza_escrituras_dentro_de_un_comando(
    armar, base, monkeypatch
):
    """Aun dentro de una transaccion que escribe: el lector rechaza una
    consulta de ESCRITURA sin enviarla, y el comando ya no se confirma."""
    unidad, _ = armar()
    enviados = []
    with pytest.raises(TransaccionInvalidadaError):
        with unidad.transaccion():
            unidad.ejecutor().ejecutar(_INSERTAR, (1, "uno"))
            conexion = unidad._conexion_actual()
            with unidad.lectura() as lector:
                monkeypatch.setattr(
                    conexion, "cursor", lambda *a, **k: enviados.append(a)
                )
                for escritura in (_ACTUALIZAR, _INSERTAR):
                    with pytest.raises(TypeError, match="LECTURA"):
                        lector.filas(escritura, ("x",))
                monkeypatch.undo()
    assert enviados == []  # no fue al servidor
    assert _ids(base) == []  # y el comando se revirtio entero


def test_el_lector_rechaza_escrituras_en_una_lectura_breve(armar, base):
    unidad, pool = armar()
    with pytest.raises(TypeError, match="LECTURA"):
        with unidad.lectura() as lector:
            lector.fila(_INSERTAR, (1, "uno"))
    assert _ids(base) == [] and unidad._en_uso == 0 and _estable(pool)


def test_lo_que_el_registro_no_ve_lo_frena_la_lectura_read_only(armar, base):
    """Limite de la clasificacion: una escritura escondida (aca, forzada
    en el registro) no la detecta el texto. Fuera de un comando la frena
    la transaccion READ ONLY; dentro, solo la revision del SQL."""
    unidad, _ = armar()
    with conectar(base, autocommit=True) as conexion:
        conexion.execute(
            "insert into prueba_ejecutor.registro values (1, 'uno')"
        )
    escondida = _forzada(
        "UPDATE prueba_ejecutor.registro SET valor = 'cambiado' RETURNING id",
        LECTURA,
    )
    try:
        with pytest.raises(PersistenciaError) as capturado:
            with unidad.lectura() as lector:
                lector.filas(escondida)
    finally:
        del registro._REGISTRO[escondida.nombre]
    assert capturado.value.sqlstate == "25006"  # read_only_sql_transaction
    with unidad.lectura() as lector:
        assert [tuple(f) for f in lector.filas(_TODOS)] == [(1, "uno")]


def test_la_lectura_breve_termina_con_rollback(armar):
    """E3-2 si se distingue: un ajuste de sesion (set_config con
    is_local=false, forzado en el registro) sobrevive a un COMMIT y se
    revierte con el ROLLBACK, aun en una transaccion READ ONLY."""
    unidad, _ = armar()  # una sola conexion
    ajuste = _forzada(
        "SELECT set_config('application_name', 'qa_e3_2', false) AS v",
        LECTURA,
    )
    try:
        with unidad.lectura() as lector:
            assert lector.fila(ajuste).v == "qa_e3_2"
    finally:
        del registro._REGISTRO[ajuste.nombre]
    with unidad.lectura() as lector:
        assert lector.fila(_AJUSTE, ("application_name",)).valor != "qa_e3_2"


def test_lecturas_y_escrituras_autorizadas_siguen_funcionando(armar, base):
    unidad, _ = armar()
    with unidad.transaccion():
        ejecutor = unidad.ejecutor()
        ejecutor.ejecutar(_INSERTAR, (1, "uno"))
        assert [f.id for f in ejecutor.filas(_ACTUALIZAR, ("dos",))] == [1]
        assert ejecutor.fila(_UNO, {"id": 1}).valor == "dos"
        with unidad.lectura() as lector:
            assert lector.fila(_UNO, {"id": 1}).valor == "dos"
    with unidad.lectura() as lector:
        assert [tuple(f) for f in lector.filas(_TODOS)] == [(1, "dos")]


def test_un_error_sql_del_lector_invalida_el_comando(armar, base):
    unidad, _ = armar()
    with pytest.raises(TransaccionInvalidadaError):
        with unidad.transaccion():
            unidad.ejecutor().ejecutar(_INSERTAR, (1, "uno"))
            with unidad.lectura() as lector:
                with pytest.raises(PersistenciaError):
                    lector.fila(_DIVISION)
    assert _ids(base) == []


# --- QA-E3-1: estado de sesion -----------------------------------------------

# Sin pasar por el registro (que ya no admite pg_settings): solo pruebas.
_SQL_SESION = """
    SELECT
      (SELECT count(*) FROM pg_locks
        WHERE pid = pg_backend_pid() AND locktype = 'advisory') AS advisory,
      (SELECT count(*) FROM pg_class
        WHERE relnamespace = pg_my_temp_schema()) AS temporales,
      (SELECT array_agg(name ORDER BY name) FROM pg_settings
        WHERE source = 'session'
          AND name NOT IN ('lock_timeout', 'statement_timeout')) AS ajustes
"""


def _sesion(unidad):
    """Lo que la conexion (unica) del pool arrastra de usos anteriores."""
    with unidad.transaccion():
        return tuple(unidad._conexion_actual().execute(_SQL_SESION).fetchone())


ATAQUES_CONFIRMADOS = (
    ("SELECT 1 AS x INTO TEMP qa_tmp", ()),
    (
        "SELECT query_to_xml('select pg_advis'||'ory_lock(42)', "
        "true, false, '') AS x",
        (),
    ),
    ("SELECT pg_try_advisory_lock(43) AS x", ()),
    (
        "UPDATE pg_settings SET setting = %s WHERE name = %s",
        ("on", "default_transaction_read_only"),
    ),
)


# Los de la QA final (QAF-1): las mismas funciones con comillas pegadas.
ATAQUES_CON_COMILLAS = (
    # En este orden: despues del set_config la sesion queda READ ONLY.
    ('SELECT 1 AS "x"INTO TEMP qa_tmp', ()),
    ('SELECT NOT"pg_try_advisory_lock"(42) AS x', ()),
    (
        "SELECT ALL\"query_to_xml\"('select pg_advis'||'ory_lock(43)', "
        "true, false, '') AS x",
        (),
    ),
    (
        "SELECT ALL\"set_config\"('default_transaction_read_only', 'on', "
        "false) AS x",
        (),
    ),
    ('SELECT ALL"nextval"(%s) AS x', ("rma.secuencia",)),
)


def test_sin_el_registro_las_comillas_pegadas_contaminarian(armar):
    """Control del control de QAF-1: forzadas, las variantes con comillas
    pegadas si dejan estado en la conexion. El registro las rechaza."""
    unidad, _ = armar()
    forzadas = [
        (_forzada(texto, ESCRITURA), parametros)
        for texto, parametros in ATAQUES_CON_COMILLAS[:4]
    ]
    try:
        for ataque, parametros in forzadas:
            with unidad.transaccion():
                unidad.ejecutor().ejecutar(ataque, parametros)
    finally:
        for ataque, _ in forzadas:
            del registro._REGISTRO[ataque.nombre]
    advisory, temporales, ajustes = _sesion(unidad)
    assert advisory == 2 and temporales == 1
    assert "default_transaction_read_only" in ajustes


INSERT_COMO_ALIAS = "SELECT (1) insert INTO LOCAL TEMP qa_alias"


def test_insert_como_alias_tras_un_parentesis_no_llega_al_servidor(armar):
    """QAF-2, verificacion focalizada: el registro rechaza la variante en
    los dos modos y la sesion queda limpia. Forzada, si crea una tabla
    temporal que sobrevive en la conexion del pool (control del control)."""
    for modo in (LECTURA, ESCRITURA):
        with pytest.raises(ValueError, match="INTO solo en INSERT INTO"):
            consulta(
                f"prueba_ejecutor.{uuid.uuid4().hex}",
                INSERT_COMO_ALIAS,
                modo=modo,
            )
    unidad, _ = armar()
    assert _sesion(unidad) == (0, 0, None)
    forzada = _forzada(INSERT_COMO_ALIAS, ESCRITURA)
    try:
        with unidad.transaccion():
            unidad.ejecutor().ejecutar(forzada)
    finally:
        del registro._REGISTRO[forzada.nombre]
    assert _sesion(unidad)[1] == 1


def test_los_ataques_confirmados_ya_no_se_registran_y_la_sesion_queda_limpia(
    armar,
):
    from app.storage.postgres.catalogos import PostgresCatalogosRepository

    for texto, _ in ATAQUES_CONFIRMADOS + ATAQUES_CON_COMILLAS[:4]:
        for modo in (LECTURA, ESCRITURA):
            with pytest.raises(ValueError, match="no se registra"):
                consulta(
                    f"prueba_ejecutor.{uuid.uuid4().hex}", texto, modo=modo
                )
    # nextval es legitimo en ESCRITURA; como LECTURA, no se registra.
    with pytest.raises(ValueError, match="lectura"):
        consulta(
            f"prueba_ejecutor.{uuid.uuid4().hex}",
            ATAQUES_CON_COMILLAS[4][0],
            modo=LECTURA,
        )
    unidad, _ = armar()  # una sola conexion: todo pasa por ella
    catalogos = PostgresCatalogosRepository(unidad)
    for metodo in (
        "listar_tipos_reparacion",
        "listar_insumos",
        "listar_tipo_reparacion_insumos",
        "listar_estaciones",
        "listar_tipo_reparacion_estaciones",
        "listar_usuarios",
        "listar_medios_pago",
        "obtener_datos_empresa",
    ):
        getattr(catalogos, metodo)()
    with unidad.transaccion():
        catalogos.listar_insumos()  # tambien dentro de un comando
    assert _sesion(unidad) == (0, 0, None)


def test_sin_el_registro_los_ataques_contaminarian_la_conexion(armar):
    """Control del control: forzados en el registro, los mismos ataques
    dejan estado en la conexion del pool, y ``_sesion`` lo ve. Es lo que
    el registro impide (y lo que el ROLLBACK no deshace)."""
    unidad, _ = armar()
    forzadas = [
        (_forzada(texto, ESCRITURA), parametros)
        for texto, parametros in ATAQUES_CONFIRMADOS
    ]
    try:
        for ataque, parametros in forzadas:
            with unidad.transaccion():
                unidad.ejecutor().ejecutar(ataque, parametros)
    finally:
        for ataque, _ in forzadas:
            del registro._REGISTRO[ataque.nombre]
    advisory, temporales, ajustes = _sesion(unidad)
    assert advisory == 2 and temporales == 1
    assert "default_transaction_read_only" in ajustes


# --- Estado dudoso: control externo y descarte de la conexion ----------------


def test_un_control_externo_descarta_la_conexion(armar, base):
    unidad, pool = armar()
    with pytest.raises(TransaccionInvalidadaError, match="pudo quedar"):
        with unidad.transaccion():
            pid = unidad.ejecutor().fila(_PID).pid
            # Lo que el ejecutor impide; aca, con la conexion interna.
            unidad._conexion_actual().execute("COMMIT")
    assert _estable(pool)
    with unidad.lectura() as lector:
        assert lector.fila(_PID).pid != pid  # otra conexion


def test_un_control_externo_lo_detecta_el_ejecutor(armar):
    unidad, _ = armar()
    with pytest.raises(TransaccionInvalidadaError):
        with unidad.transaccion():
            unidad._conexion_actual().execute("ROLLBACK")
            with pytest.raises(TransaccionInvalidadaError, match="ya no"):
                unidad.ejecutor().filas(_TODOS)


# --- Pool: M2, L2 y cierre ---------------------------------------------------


def _cortar(base, pid):
    with conectar(base, autocommit=True) as conexion:
        conexion.execute("select pg_terminate_backend(%s)", (pid,))
    time.sleep(0.2)


def test_una_conexion_ociosa_cortada_se_reemplaza_una_vez(armar, base, caplog):
    caplog.set_level(logging.WARNING)
    unidad, pool = armar()
    with unidad.lectura() as lector:
        pid = lector.fila(_PID).pid
    _cortar(base, pid)
    with unidad.transaccion():  # hoy da 500 (R3); con M2, funciona
        unidad.ejecutor().ejecutar(_INSERTAR, (1, "uno"))
        nuevo = unidad.ejecutor().fila(_PID).pid
    assert nuevo != pid and _ids(base) == [1]
    assert "estaba cortada" in caplog.text


def test_el_reemplazo_es_uno_solo(armar, base):
    """Las dos conexiones del pool estan cortadas: se reemplaza la primera
    una vez, la segunda tambien falla y sale un 503 (QA-E3-2), sin mas
    intentos. Despues el pool se recupera solo."""
    unidad, pool = armar(pool_min=2, pool_max=2)
    primera, segunda = pool.getconn(), pool.getconn()
    pids = [primera.info.backend_pid, segunda.info.backend_pid]
    pool.putconn(primera)
    pool.putconn(segunda)
    for pid in pids:
        _cortar(base, pid)
    tomadas = []
    original = unidad._tomar_conexion

    def contar():
        tomadas.append(1)
        return original()

    unidad._tomar_conexion = contar
    with pytest.raises(PersistenciaSinConexionError) as capturado:
        with unidad.transaccion():
            pytest.fail("no se ejecuta nada del comando")
    assert len(tomadas) == 2  # la original y un solo reemplazo
    assert capturado.value.codigo == "PERSISTENCIA_SIN_CONEXION"
    assert unidad._en_uso == 0
    assert _estable(pool)
    # El pool repuso las descartadas: el siguiente comando funciona.
    with unidad.transaccion():
        unidad.ejecutor().ejecutar(_INSERTAR, (1, "uno"))
        assert unidad.ejecutor().fila(_PID).pid not in pids
    assert _ids(base) == [1]


def test_una_interrupcion_en_el_begin_no_pierde_la_conexion(
    armar, monkeypatch
):
    """KeyboardInterrupt en pleno BEGIN: la conexion se descarta y el
    contador vuelve a cero (antes quedaba prestada para siempre)."""
    unidad, pool = armar(pool_max=2)
    original = psycopg.Connection.execute
    interrumpidas = []

    def interrumpir(self, *args, **kwargs):
        if not interrumpidas:
            interrumpidas.append(self.info.backend_pid)
            raise KeyboardInterrupt
        return original(self, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", interrumpir)
    with pytest.raises(KeyboardInterrupt):
        with unidad.transaccion():
            pytest.fail("no se abre la transaccion")
    monkeypatch.undo()
    assert interrumpidas and unidad._en_uso == 0
    assert _estable(pool)
    # Las dos conexiones del pool sirven: dos comandos a la vez.
    adentro = threading.Barrier(2, timeout=10)
    errores = []

    def comando():
        try:
            with unidad.transaccion():
                assert unidad.ejecutor().fila(_PID).pid != interrumpidas[0]
                adentro.wait()
        except Exception as error:  # noqa: BLE001
            errores.append(error)

    hilos = [threading.Thread(target=comando) for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(15)
    assert errores == []


# --- QAF-3: interrupciones en la limpieza y entre el BEGIN y el bloque -------


def _sigue_sirviendo(unidad, pool):
    assert unidad._en_uso == 0
    assert _estable(pool)
    with unidad.transaccion():
        unidad.ejecutor().ejecutar(_INSERTAR, (1, "uno"))


def test_una_interrupcion_al_revertir_un_begin_fallido(armar, monkeypatch):
    """El BEGIN falla (no por la conexion) y el ROLLBACK de la limpieza se
    interrumpe: antes la conexion quedaba prestada para siempre y todo lo
    siguiente daba 503 «pool agotado»."""
    unidad, pool = armar(pool_espera_s=1)
    inicio = unidad._inicio
    unidad._inicio = "BEGIN; SET LOCAL lock_timeout = 'no es un numero'"

    def interrumpir(conexion):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        UnidadDeTrabajoPostgres, "_revertir", staticmethod(interrumpir)
    )
    with pytest.raises(KeyboardInterrupt):
        with unidad.transaccion():
            pytest.fail("no se abre la transaccion")
    monkeypatch.undo()
    unidad._inicio = inicio
    _sigue_sirviendo(unidad, pool)


def test_una_interrupcion_entre_el_begin_y_el_bloque(armar, monkeypatch):
    from app.storage.postgres import transaccion

    unidad, pool = armar(pool_espera_s=1)

    def interrumpir(**_):
        raise KeyboardInterrupt

    monkeypatch.setattr(transaccion, "_EnCurso", interrumpir)
    with pytest.raises(KeyboardInterrupt):
        with unidad.transaccion():
            pytest.fail("no se abre la transaccion")
    monkeypatch.undo()
    _sigue_sirviendo(unidad, pool)


def test_una_interrupcion_al_contar_la_conexion(armar):
    unidad, pool = armar(pool_espera_s=1)
    candado = unidad._candado

    class Interrumpe:
        """El primer ``with`` (el del conteo) se interrumpe."""

        usos = 0

        def __enter__(self):
            Interrumpe.usos += 1
            if Interrumpe.usos == 1:
                raise KeyboardInterrupt
            return candado.__enter__()

        def __exit__(self, *datos):
            return candado.__exit__(*datos)

    unidad._candado = Interrumpe()
    with pytest.raises(KeyboardInterrupt):
        with unidad.transaccion():
            pytest.fail("no se abre la transaccion")
    unidad._candado = candado
    _sigue_sirviendo(unidad, pool)


def test_un_error_del_begin_que_no_es_de_conexion_no_se_reintenta(armar):
    unidad, pool = armar()
    unidad._inicio = "BEGIN; SET LOCAL lock_timeout = 'no es un numero'"
    tomadas = []
    original = unidad._tomar_conexion

    def contar():
        tomadas.append(1)
        return original()

    unidad._tomar_conexion = contar
    with pytest.raises(PersistenciaError):
        with unidad.transaccion():
            pass
    assert tomadas == [1] and _estable(pool)


def test_sin_conexion_no_es_pool_agotado(armar):
    configuracion = configuracion_postgres(
        Settings(
            _env_file=None,
            persistencia="postgres",
            database_url="postgresql://u:x@127.0.0.1:1/postgres",
        )
    )
    ajustes = AjustesPostgres(pool_espera_s=1)
    pool = abrir_pool(configuracion, ajustes)
    try:
        unidad = UnidadDeTrabajoPostgres(pool, ajustes)
        with pytest.raises(PersistenciaSinConexionError) as capturado:
            with unidad.transaccion():
                pass
    finally:
        pool.close()
    assert capturado.value.codigo == "PERSISTENCIA_SIN_CONEXION"
    assert isinstance(capturado.value, PersistenciaNoDisponibleError)


def test_el_pool_agotado_no_es_sin_conexion(armar):
    unidad, _ = armar(pool_espera_s=0.5)
    adentro, soltar = threading.Event(), threading.Event()

    def retener():
        with unidad.transaccion():
            adentro.set()
            soltar.wait(10)

    hilo = threading.Thread(target=retener)
    hilo.start()
    assert adentro.wait(10)
    try:
        with pytest.raises(PersistenciaNoDisponibleError) as capturado:
            with unidad.lectura():
                pass
    finally:
        soltar.set()
        hilo.join(10)
    assert not isinstance(capturado.value, PersistenciaSinConexionError)


def test_cerrar_pool_cierra_las_conexiones(base):
    ajustes = AjustesPostgres(pool_min=2, pool_max=2)
    pool = abrir_pool(base, ajustes)
    pool.wait(10)
    unidad = UnidadDeTrabajoPostgres(pool, ajustes)
    with unidad.lectura() as lector:
        pid = lector.fila(_PID).pid
    cerrar_pool(pool, espera_s=2)
    with conectar(base, autocommit=True) as conexion:
        sigue = conexion.execute(
            "select count(*) from pg_stat_activity where pid = %s", (pid,)
        ).fetchone()[0]
    assert sigue == 0
    with pytest.raises(PersistenciaError, match="cerrado"):
        with unidad.lectura():
            pass


# --- Privilegios minimos del rol de la aplicacion ----------------------------


def test_el_rol_de_la_aplicacion_lee_pero_no_cambia_ni_define(
    base, postgres_descartable
):
    rol = f"rma_prueba_{uuid.uuid4().hex[:8]}"
    with conectar(base, autocommit=True) as admin:
        admin.execute(
            sql.SQL("create role {} login in role rma_backend").format(
                sql.Identifier(rol)
            )
        )
    try:
        url = postgres_descartable.replace("postgres@", f"{rol}@", 1)
        with psycopg.connect(url, autocommit=True) as conexion:
            conexion.execute("select codigo, clave from rma.insumo").fetchall()
            # La funcion del trigger de E3, sin EXECUTE heredado de PUBLIC.
            assert conexion.execute(
                "select has_function_privilege("
                "'rma.insumo_clave_por_defecto()', 'EXECUTE')"
            ).fetchone() == (False,)
            for prohibida in (
                "update rma.insumo set clave = 'X'",
                "update rma.insumo set stock_fisico = 99",
                "create table rma.intrusa (id int)",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conexion.execute(prohibida)
    finally:
        with conectar(base, autocommit=True) as admin:
            admin.execute(sql.SQL("drop role {}").format(sql.Identifier(rol)))
