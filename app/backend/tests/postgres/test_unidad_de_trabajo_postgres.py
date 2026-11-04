"""Unidad de trabajo PostgreSQL (E1) contra la base local descartable.

Ciclo real con psycopg 3 y psycopg-pool: BEGIN con SET LOCAL, COMMIT,
ROLLBACK, anidadas, fallos atrapados, limpieza de la conexion y del
contexto, pool agotado (503) y conexiones perdidas. Las pruebas marcadas
``postgres`` usan una tabla propia (esquema ``prueba_uow``) dentro de la
base de la sesion, que se borra al terminar.
"""

import asyncio
import contextvars
import logging
import threading
import time

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from psycopg.pq import TransactionStatus  # noqa: E402

from app.api.errores import registrar_manejadores_de_error  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.repositories.exceptions import (  # noqa: E402
    ConflictoDeEscrituraError,
    PersistenciaError,
    PersistenciaNoDisponibleError,
    TransaccionInvalidadaError,
)
from app.services import PrecondicionInvalidaError  # noqa: E402
from app.storage.postgres import (  # noqa: E402
    AjustesPostgres,
    conectar,
    configuracion_postgres,
)
from app.storage.postgres.transaccion import (  # noqa: E402
    _EN_CURSO,
    UnidadDeTrabajoPostgres,
    abrir_pool,
)

PASSWORD = "Clave-De-Prueba-No-Debe-Verse"
DATO_DE_UNA_FILA = "valor-de-la-fila-30123456"


def _configuracion(url):
    return configuracion_postgres(
        Settings(_env_file=None, persistencia="postgres", database_url=url)
    )


@pytest.fixture(scope="module")
def base(postgres_descartable):
    """Configuracion de la base de la sesion, con una tabla de prueba."""
    configuracion = _configuracion(postgres_descartable)
    with conectar(configuracion, autocommit=True) as conexion:
        conexion.execute(
            """
            create schema prueba_uow;
            create table prueba_uow.registro (
                id integer primary key,
                valor text not null
            );
            create table prueba_uow.diferida (
                id integer,
                constraint diferida_unica unique (id)
                    deferrable initially deferred
            );
            """
        )
    yield configuracion
    with conectar(configuracion, autocommit=True) as conexion:
        conexion.execute("drop schema prueba_uow cascade")


@pytest.fixture(autouse=True)
def _sin_rescates_del_pool(caplog):
    """El pool nunca recibe una transaccion abierta: si tuviera que
    revertirla el, la unidad de trabajo habria omitido su ROLLBACK."""
    caplog.set_level(logging.WARNING, logger="psycopg.pool")
    yield
    # En el teardown, ``caplog.records`` solo tiene los de esta fase.
    rescates = [
        registro.getMessage()
        for fase in ("setup", "call")
        for registro in caplog.get_records(fase)
        if "rolling back returned connection" in registro.getMessage()
    ]
    assert rescates == []


@pytest.fixture
def armar(base):
    """Arma pools y unidades de trabajo; los cierra al final."""
    pools = []
    with conectar(base, autocommit=True) as conexion:
        conexion.execute("truncate prueba_uow.registro, prueba_uow.diferida")

    def _armar(**valores):
        ajustes = AjustesPostgres(**{"pool_max": 1, **valores})
        pool = abrir_pool(base, ajustes)
        pools.append(pool)
        return UnidadDeTrabajoPostgres(pool, ajustes), pool

    yield _armar
    for pool in pools:
        pool.close()


def _ids(configuracion) -> list[int]:
    """Lo confirmado, visto desde otra conexion."""
    with conectar(configuracion, autocommit=True) as conexion:
        filas = conexion.execute(
            "select id from prueba_uow.registro order by id"
        ).fetchall()
    return [fila[0] for fila in filas]


def _insertar(unidad, id_, valor="x"):
    unidad.conexion_actual().execute(
        "insert into prueba_uow.registro (id, valor) values (%s, %s)",
        (id_, valor),
    )


def _limpio(unidad, pool):
    """Sin transaccion en el contexto y la conexion devuelta al pool."""
    assert not unidad.en_curso()
    assert _EN_CURSO.get() is None
    with pytest.raises(PersistenciaError, match="fuera de una transaccion"):
        unidad.conexion_actual()
    estadisticas = pool.get_stats()
    assert estadisticas["pool_available"] == estadisticas["pool_size"]


# --- Commit y SET LOCAL -----------------------------------------------------


@pytest.mark.postgres
def test_un_bloque_sin_errores_confirma(armar, base):
    unidad, pool = armar()
    with unidad.transaccion():
        assert unidad.en_curso()
        _insertar(unidad, 1)
        assert _ids(base) == []  # nadie ve lo que no se confirmo
    assert _ids(base) == [1]
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_begin_y_set_local_valen_solo_dentro_de_la_transaccion(armar):
    unidad, pool = armar()
    with unidad.transaccion():
        conexion = unidad.conexion_actual()
        assert conexion.info.transaction_status == TransactionStatus.INTRANS
        assert conexion.execute("show lock_timeout").fetchone() == ("5s",)
        assert conexion.execute("show statement_timeout").fetchone() == (
            "15s",
        )
        pid = conexion.execute("select pg_backend_pid()").fetchone()

    # La misma conexion fisica (pool de 1), ya fuera de la transaccion.
    with pool.connection() as conexion:
        assert conexion.execute("select pg_backend_pid()").fetchone() == pid
        assert conexion.info.transaction_status == TransactionStatus.IDLE
        assert conexion.execute("show lock_timeout").fetchone() == ("0",)
        assert conexion.execute("show statement_timeout").fetchone() == ("0",)


def _cancelar(configuracion, pid):
    with conectar(configuracion, autocommit=True) as otra:
        otra.execute("select pg_cancel_backend(%s)", (pid,))


@pytest.mark.postgres
def test_el_lock_timeout_corta_la_espera_y_es_reintentable(armar, base):
    unidad, pool = armar(lock_timeout_ms=200)
    with conectar(base) as otra:
        with otra.transaction():
            otra.execute("lock table prueba_uow.registro")
            inicio = time.monotonic()
            with pytest.raises(ConflictoDeEscrituraError) as capturado:
                with unidad.transaccion():
                    pid = (
                        unidad.conexion_actual()
                        .execute("select pg_backend_pid()")
                        .fetchone()[0]
                    )
                    # Red: si el limite no se aplicara, la prueba falla en
                    # vez de quedar esperando el bloqueo para siempre.
                    red = threading.Timer(5, _cancelar, (base, pid))
                    red.start()
                    try:
                        _insertar(unidad, 1)
                    finally:
                        red.cancel()
            demora = time.monotonic() - inicio

    assert demora < 3
    assert capturado.value.sqlstate == "55P03"
    assert capturado.value.reintentable
    assert _ids(base) == []
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_el_statement_timeout_corta_una_sentencia_lenta(armar):
    unidad, pool = armar(statement_timeout_ms=200)
    with pytest.raises(PersistenciaError) as capturado:
        with unidad.transaccion():
            unidad.conexion_actual().execute("select pg_sleep(2)")
    assert not isinstance(capturado.value, ConflictoDeEscrituraError)
    assert capturado.value.sqlstate == "57014"
    assert not capturado.value.reintentable
    _limpio(unidad, pool)
    # Una transaccion posterior no hereda el limite de 200 ms: tiene el
    # suyo, y fuera de ella no hay ninguno.
    with pool.connection() as conexion:
        assert conexion.execute("show statement_timeout").fetchone() == ("0",)


# --- Rollback ---------------------------------------------------------------


@pytest.mark.postgres
def test_un_error_de_dominio_revierte_y_sigue_igual(armar, base):
    unidad, pool = armar()
    error = PrecondicionInvalidaError("la Orden no admite esto")
    with pytest.raises(PrecondicionInvalidaError) as capturado:
        with unidad.transaccion():
            _insertar(unidad, 1)
            raise error
    assert capturado.value is error
    assert _ids(base) == []
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_un_error_de_postgres_revierte_y_se_traduce(armar, base):
    unidad, pool = armar()
    with pytest.raises(ConflictoDeEscrituraError) as capturado:
        with unidad.transaccion():
            _insertar(unidad, 1)
            _insertar(unidad, 1, DATO_DE_UNA_FILA)
    assert capturado.value.sqlstate == "23505"
    assert "registro_pkey" in str(capturado.value)
    # Sin encadenar: el DETAIL de psycopg citaria la fila.
    assert capturado.value.__cause__ is None
    assert capturado.value.__suppress_context__
    assert DATO_DE_UNA_FILA not in str(capturado.value)
    assert _ids(base) == []
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_un_commit_rechazado_por_la_base_se_traduce(armar, base):
    unidad, pool = armar()
    with pytest.raises(ConflictoDeEscrituraError) as capturado:
        with unidad.transaccion():
            _insertar(unidad, 1)
            conexion = unidad.conexion_actual()
            # Restriccion diferida: falla recien en el COMMIT.
            conexion.execute("insert into prueba_uow.diferida values (7), (7)")
    assert capturado.value.sqlstate == "23505"
    assert _ids(base) == []
    _limpio(unidad, pool)


# --- Anidadas ---------------------------------------------------------------


@pytest.mark.postgres
def test_las_anidadas_se_unen_y_solo_la_exterior_confirma(armar, base):
    unidad, pool = armar()
    consulta = "select pg_backend_pid(), pg_current_xact_id()::text"
    with unidad.transaccion():
        exterior = unidad.conexion_actual().execute(consulta).fetchone()
        _insertar(unidad, 1)
        with unidad.transaccion():
            interior = unidad.conexion_actual().execute(consulta).fetchone()
            _insertar(unidad, 2)
        assert interior == exterior  # misma conexion, misma transaccion
        assert unidad.en_curso()
        assert _ids(base) == []  # la anidada no confirmo
    assert _ids(base) == [1, 2]
    _limpio(unidad, pool)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "falla",
    [
        RuntimeError("falla interna"),
        PrecondicionInvalidaError("regla"),
    ],
)
def test_una_falla_anidada_atrapada_no_confirma_nada(armar, base, falla):
    unidad, pool = armar()
    with pytest.raises(TransaccionInvalidadaError):
        with unidad.transaccion():
            _insertar(unidad, 1)
            try:
                with unidad.transaccion():
                    _insertar(unidad, 2)
                    raise falla
            except type(falla):
                pass
            _insertar(unidad, 3)
    assert _ids(base) == []
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_un_error_sql_anidado_y_atrapado_no_confirma_nada(armar, base):
    unidad, pool = armar()
    with pytest.raises(TransaccionInvalidadaError):
        with unidad.transaccion():
            _insertar(unidad, 1)
            try:
                with unidad.transaccion():
                    _insertar(unidad, 1)
            except ConflictoDeEscrituraError:
                pass
    assert _ids(base) == []
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_un_error_sql_atrapado_en_el_mismo_nivel_no_confirma_nada(armar, base):
    """Un COMMIT sobre una transaccion abortada seria un ROLLBACK mudo."""
    unidad, pool = armar()
    with pytest.raises(TransaccionInvalidadaError, match="aborto"):
        with unidad.transaccion():
            _insertar(unidad, 1)
            try:
                _insertar(unidad, 1)
            except psycopg.errors.UniqueViolation:
                pass
    assert _ids(base) == []
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_una_anidada_de_otra_unidad_se_rechaza(armar, base):
    unidad, _ = armar()
    otra, _ = armar()
    with pytest.raises(PersistenciaError, match="otra unidad"):
        with unidad.transaccion():
            _insertar(unidad, 1)
            with otra.transaccion():
                pass
    assert _ids(base) == []


# --- Limpieza ---------------------------------------------------------------


@pytest.mark.postgres
@pytest.mark.parametrize(
    "falla",
    [
        RuntimeError("falla"),
        PrecondicionInvalidaError("regla"),
        KeyboardInterrupt(),
        "sql",
    ],
)
def test_toda_excepcion_limpia_la_conexion_y_el_contexto(armar, falla):
    unidad, pool = armar(pool_espera_s=1)
    for _ in range(3):  # con un pool de 1, una fuga trabaria la segunda
        with pytest.raises(BaseException):
            with unidad.transaccion():
                _insertar(unidad, 1)
                if falla == "sql":
                    _insertar(unidad, 1)
                raise falla
        _limpio(unidad, pool)
    with unidad.transaccion():
        _insertar(unidad, 1)
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_fuera_de_una_transaccion_no_hay_conexion(armar):
    unidad, _ = armar()
    assert not unidad.en_curso()
    with pytest.raises(PersistenciaError, match="contexto.transaccion"):
        unidad.conexion_actual()


@pytest.mark.postgres
def test_cada_hilo_tiene_su_propia_transaccion(armar):
    unidad, pool = armar(pool_max=4)
    barrera = threading.Barrier(4, timeout=10)
    vistos = []
    despues = []

    def trabajar():
        with unidad.transaccion():
            pid = (
                unidad.conexion_actual()
                .execute("select pg_backend_pid()")
                .fetchone()[0]
            )
            barrera.wait()  # las cuatro abiertas a la vez
            vistos.append(pid)
        despues.append(unidad.en_curso())

    hilos = [threading.Thread(target=trabajar) for _ in range(4)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(15)
    assert len(set(vistos)) == 4
    assert despues == [False] * 4
    _limpio(unidad, pool)


# --- Contextos copiados (revision de E1, H1) --------------------------------
#
# ``asyncio.create_task``, ``asyncio.to_thread``, ``run_in_threadpool`` y
# ``contextvars.copy_context()`` copian la ContextVar. Una copia nunca
# puede usar la transaccion: ni despues de que termine (su conexion ya
# volvio al pool) ni mientras sigue abierta en el hilo que la abrio. Si
# ya termino, ``transaccion()`` abre una propia (QA-1, mas abajo).


def _unirse_y_salir(unidad):
    transaccion = unidad.transaccion()
    transaccion.__enter__()
    transaccion.__exit__(None, None, None)


def _intentos(unidad):
    """Lo que un contexto heredado consigue hacer con la transaccion."""
    resultado = {"en_curso": unidad.en_curso()}
    for nombre, accion in (
        ("conexion", unidad.conexion_actual),
        ("unirse", lambda: _unirse_y_salir(unidad)),
    ):
        try:
            accion()
            resultado[nombre] = "permitido"
        except PersistenciaError as error:
            resultado[nombre] = str(error)
    return resultado


@pytest.mark.postgres
def test_una_tarea_no_usa_la_transaccion_despues_de_que_termina(armar, base):
    """R2: la tarea copio el contexto y corre cuando ya se confirmo."""
    unidad, pool = armar()
    vistos = {}

    async def tarea():
        vistos.update(_intentos(unidad))
        try:
            _insertar(unidad, 12)
        except PersistenciaError:
            pass

    async def caso_de_uso():
        with unidad.transaccion():
            _insertar(unidad, 11)
            pendiente = asyncio.create_task(tarea())
        await pendiente

    asyncio.run(caso_de_uso())

    assert vistos["en_curso"] is False
    assert "ya termino" in vistos["conexion"]
    # No se une a la terminada: abre la suya (QA-1), vacia.
    assert vistos["unirse"] == "permitido"
    assert _ids(base) == [11]  # 12 nunca se escribio, ni en autocommit
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_un_contexto_viejo_no_escribe_en_la_transaccion_de_otro_pedido(
    armar, base
):
    """R2b: la conexion ya es de otro pedido cuando el contexto viejo
    intenta escribir; el otro pedido confirma solo lo suyo."""
    # Pool de 1: el otro pedido recibe la misma conexion.
    unidad, pool = armar(pool_espera_s=1)
    with unidad.transaccion():
        pid_viejo = (
            unidad.conexion_actual()
            .execute("select pg_backend_pid()")
            .fetchone()[0]
        )
        viejo = contextvars.copy_context()

    adentro, soltar = threading.Event(), threading.Event()
    pid_otro = []

    def otro_pedido():
        with unidad.transaccion():
            conexion = unidad.conexion_actual()
            pid_otro.append(
                conexion.execute("select pg_backend_pid()").fetchone()[0]
            )
            _insertar(unidad, 20)
            adentro.set()
            soltar.wait(10)

    hilo = threading.Thread(target=otro_pedido)
    hilo.start()
    assert adentro.wait(10)
    vistos = viejo.run(_intentos, unidad)
    soltar.set()
    hilo.join(10)

    assert pid_otro == [pid_viejo]  # misma conexion fisica, otro pedido
    assert vistos["en_curso"] is False
    assert "ya termino" in vistos["conexion"]
    # No se une a la terminada ni toma la conexion del otro pedido: pide
    # una propia al pool (QA-1), que esta ocupado.
    assert "No hubo una conexion libre" in vistos["unirse"]
    assert _ids(base) == [20]
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_un_hilo_heredero_no_comparte_la_conexion_mientras_sigue_abierta(
    armar, base
):
    unidad, pool = armar()
    vistos = {}

    def heredero():
        vistos.update(_intentos(unidad))

    with unidad.transaccion():
        _insertar(unidad, 1)
        copia = contextvars.copy_context()
        hilo = threading.Thread(target=copia.run, args=(heredero,))
        hilo.start()
        hilo.join(10)
        assert unidad.en_curso()  # la del hilo dueno sigue intacta
        _insertar(unidad, 2)

    assert vistos["en_curso"] is False
    assert "otro hilo o tarea" in vistos["conexion"]
    assert "otro hilo o tarea" in vistos["unirse"]
    assert _ids(base) == [1, 2]
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_una_tarea_concurrente_no_comparte_la_conexion(armar, base):
    """Misma hebra, otra tarea asyncio: corre mientras la transaccion
    del caso de uso sigue abierta."""
    unidad, pool = armar()
    vistos = {}

    async def tarea():
        vistos.update(_intentos(unidad))

    async def caso_de_uso():
        with unidad.transaccion():
            _insertar(unidad, 1)
            pendiente = asyncio.create_task(tarea())
            await asyncio.sleep(0)  # la tarea corre ahora, adentro
            await pendiente
            _insertar(unidad, 2)

    asyncio.run(caso_de_uso())

    assert vistos["en_curso"] is False
    assert "otro hilo o tarea" in vistos["conexion"]
    assert _ids(base) == [1, 2]
    _limpio(unidad, pool)


# --- Contexto heredado inactivo (QA final de E1, QA-1) ----------------------
#
# Una copia hecha dentro de una transaccion que ya termino no puede usarla,
# pero si abrir la suya: otra conexion del pool, otro ``_EnCurso`` y, al
# salir, la ContextVar vuelve a la heredada (inactiva).


def _abrir_la_suya(unidad, base, heredada):
    """Lo que hace la copia cuando la transaccion del padre ya termino."""
    assert not unidad.en_curso()
    with unidad.transaccion():
        propia = _EN_CURSO.get()
        assert propia is not heredada and propia.activa
        assert unidad.en_curso()
        _insertar(unidad, 2)
        with unidad.transaccion():  # una anidada se une a la nueva
            assert _EN_CURSO.get() is propia
            _insertar(unidad, 3)
        assert _ids(base) == [1]  # lo suyo todavia no se ve afuera
    assert _EN_CURSO.get() is heredada and not heredada.activa
    assert not unidad.en_curso()
    with pytest.raises(PersistenciaError, match="ya termino"):
        unidad.conexion_actual()
    # Y otra que falla se revierte sola, sin tocar lo confirmado.
    with pytest.raises(ValueError):
        with unidad.transaccion():
            _insertar(unidad, 4)
            raise ValueError("falla de la copia")
    assert _EN_CURSO.get() is heredada


@pytest.mark.postgres
@pytest.mark.parametrize("copia", ["hilo", "tarea asyncio"])
def test_un_contexto_heredado_abre_la_suya_cuando_la_del_padre_termino(
    armar, base, copia
):
    unidad, pool = armar(pool_max=2)
    # Con la conexion inicial lista, el pool no crece en segundo plano y
    # al final ``_limpio`` cuenta solo conexiones terminadas.
    pool.wait(10)
    resultado = []

    def correr(heredada):
        try:
            _abrir_la_suya(unidad, base, heredada)
            resultado.append("ok")
        except BaseException as error:  # noqa: BLE001 (se informa abajo)
            resultado.append(repr(error))

    if copia == "hilo":
        with unidad.transaccion():
            _insertar(unidad, 1)
            heredada = _EN_CURSO.get()
            contexto = contextvars.copy_context()
        hilo = threading.Thread(target=contexto.run, args=(correr, heredada))
        hilo.start()
        hilo.join(15)
    else:

        async def caso_de_uso():
            with unidad.transaccion():
                _insertar(unidad, 1)
                heredada = _EN_CURSO.get()
                # La tarea arranca recien en el await, ya terminada esta.
                pendiente = asyncio.create_task(tarea(heredada))
            await pendiente

        async def tarea(heredada):
            correr(heredada)

        asyncio.run(caso_de_uso())

    assert resultado == ["ok"]
    assert _ids(base) == [1, 2, 3]  # el 4 se revirtio solo
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_un_contexto_heredado_no_abre_otra_mientras_la_del_padre_sigue(
    armar, base
):
    """Hay conexiones libres: el rechazo no es por el pool."""
    unidad, pool = armar(pool_max=2)
    pool.wait(10)  # sin crecimiento en segundo plano al final
    vistos = []

    def heredero():
        try:
            with unidad.transaccion():
                _insertar(unidad, 2)
            vistos.append("abrio otra")
        except PersistenciaError as error:
            vistos.append(str(error))

    with unidad.transaccion():
        _insertar(unidad, 1)
        conexion = unidad.conexion_actual()
        copia = contextvars.copy_context()
        hilo = threading.Thread(target=copia.run, args=(heredero,))
        hilo.start()
        hilo.join(10)
        assert unidad.conexion_actual() is conexion  # intacta
        _insertar(unidad, 3)

    assert len(vistos) == 1 and "otro hilo o tarea" in vistos[0]
    assert _ids(base) == [1, 3]
    _limpio(unidad, pool)


# --- Control transaccional externo (revision de E1, M1) ---------------------
#
# Solo la unidad de trabajo envia BEGIN, COMMIT y ROLLBACK. Si algo los
# envia dentro del bloque, la transaccion ya termino: lo anterior pudo
# quedar confirmado (y con autocommit, tambien lo posterior). Se detecta
# al final y el diagnostico no afirma una reversion que no se puede
# garantizar.

CONTROLES_EXTERNOS = {
    "commit()": lambda conexion: conexion.commit(),
    "COMMIT": lambda conexion: conexion.execute("COMMIT"),
    "ROLLBACK": lambda conexion: conexion.execute("ROLLBACK"),
}


@pytest.mark.postgres
@pytest.mark.parametrize("control", sorted(CONTROLES_EXTERNOS))
def test_un_control_transaccional_externo_se_detecta(armar, base, control):
    unidad, pool = armar()
    with pytest.raises(TransaccionInvalidadaError) as capturado:
        with unidad.transaccion():
            _insertar(unidad, 1)
            CONTROLES_EXTERNOS[control](unidad.conexion_actual())
            _insertar(unidad, 2)

    mensaje = str(capturado.value)
    assert "fuera de la unidad de trabajo" in mensaje
    assert "pudo quedar confirmado" in mensaje
    assert "se revirtio" not in mensaje
    # El diagnostico es cierto: 2 ya no estaba en ninguna transaccion.
    assert 2 in _ids(base)
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_un_control_externo_seguido_de_un_error_tambien_se_diagnostica(
    armar, base
):
    """El error de dominio sigue como causa, pero no se presenta como si
    todo se hubiera revertido."""
    unidad, pool = armar()
    error = PrecondicionInvalidaError("regla")
    with pytest.raises(TransaccionInvalidadaError) as capturado:
        with unidad.transaccion():
            _insertar(unidad, 1)
            unidad.conexion_actual().commit()
            raise error

    assert "pudo quedar confirmado" in str(capturado.value)
    assert capturado.value.__cause__ is error
    assert _ids(base) == [1]
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_un_control_externo_seguido_de_un_error_sql_no_cita_la_fila(
    armar, base
):
    unidad, pool = armar()
    with pytest.raises(TransaccionInvalidadaError) as capturado:
        with unidad.transaccion():
            _insertar(unidad, 1)
            unidad.conexion_actual().execute("COMMIT")
            _insertar(unidad, 1, DATO_DE_UNA_FILA)

    assert "pudo quedar confirmado" in str(capturado.value)
    assert capturado.value.__cause__ is None
    assert DATO_DE_UNA_FILA not in str(capturado.value)
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_una_interrupcion_tras_un_control_externo_se_registra(armar, caplog):
    """KeyboardInterrupt no se convierte en otro error, pero queda en el
    log que lo anterior pudo quedar confirmado."""
    unidad, pool = armar()
    with pytest.raises(KeyboardInterrupt):
        with unidad.transaccion():
            _insertar(unidad, 1)
            unidad.conexion_actual().commit()
            raise KeyboardInterrupt
    assert "pudo quedar confirmado" in caplog.text
    _limpio(unidad, pool)


@pytest.mark.postgres
def test_una_transaccion_abortada_no_afirma_mas_de_lo_que_sabe(armar, base):
    unidad, pool = armar()
    with pytest.raises(TransaccionInvalidadaError) as capturado:
        with unidad.transaccion():
            _insertar(unidad, 1)
            try:
                _insertar(unidad, 1)
            except psycopg.errors.UniqueViolation:
                pass
    assert "no se confirmo nada de ella" in str(capturado.value)
    assert "se revirtio todo" not in str(capturado.value)
    assert _ids(base) == []
    _limpio(unidad, pool)


# --- Conexiones perdidas ----------------------------------------------------


def _terminar(configuracion, pid):
    with conectar(configuracion, autocommit=True) as otra:
        otra.execute("select pg_terminate_backend(%s)", (pid,))


@pytest.mark.postgres
def test_una_conexion_perdida_en_el_medio_se_descarta(armar, base):
    unidad, pool = armar()
    with pytest.raises(PersistenciaError):
        with unidad.transaccion():
            conexion = unidad.conexion_actual()
            pid = conexion.execute("select pg_backend_pid()").fetchone()[0]
            _terminar(base, pid)
            _insertar(unidad, 1)
    assert not unidad.en_curso()
    # El pool repone la conexion: el comando siguiente funciona.
    with unidad.transaccion():
        _insertar(unidad, 2)
    assert _ids(base) == [2]


@pytest.mark.postgres
def test_una_conexion_perdida_al_confirmar_es_un_resultado_incierto(
    armar, base
):
    unidad, _ = armar()
    with pytest.raises(PersistenciaError, match="no se sabe si se guardo"):
        with unidad.transaccion():
            _insertar(unidad, 1)
            pid = (
                unidad.conexion_actual()
                .execute("select pg_backend_pid()")
                .fetchone()[0]
            )
            _terminar(base, pid)
    assert not unidad.en_curso()
    assert _ids(base) == []
    with unidad.transaccion():
        _insertar(unidad, 2)
    assert _ids(base) == [2]


# --- Pool agotado -----------------------------------------------------------


@pytest.fixture
def ocupar():
    """Retiene la unica conexion del pool en otro hilo."""
    hilos = []

    def _ocupar(unidad):
        adentro = threading.Event()
        soltar = threading.Event()

        def retener():
            with unidad.transaccion():
                adentro.set()
                soltar.wait(10)

        hilo = threading.Thread(target=retener)
        hilo.start()
        hilos.append((hilo, soltar))
        assert adentro.wait(10)
        return soltar

    yield _ocupar
    for hilo, soltar in hilos:
        soltar.set()
        hilo.join(10)


@pytest.mark.postgres
def test_el_pool_agotado_espera_lo_configurado_y_no_es_un_conflicto(
    armar, ocupar
):
    unidad, pool = armar(pool_espera_s=0.3)
    soltar = ocupar(unidad)
    inicio = time.monotonic()
    with pytest.raises(PersistenciaNoDisponibleError) as capturado:
        with unidad.transaccion():
            pass
    demora = time.monotonic() - inicio
    assert 0.25 <= demora < 2
    assert not isinstance(capturado.value, ConflictoDeEscrituraError)
    assert not unidad.en_curso()
    soltar.set()
    with unidad.transaccion():
        pass


@pytest.mark.postgres
def test_el_pool_agotado_responde_503(armar, ocupar):
    unidad, _ = armar(pool_espera_s=0.3)
    app = FastAPI()
    registrar_manejadores_de_error(app)

    @app.post("/comando")
    def comando():
        with unidad.transaccion():
            unidad.conexion_actual().execute("select 1")
        return {"ok": True}

    with TestClient(app) as cliente:
        soltar = ocupar(unidad)
        respuesta = cliente.post("/comando")
        assert respuesta.status_code == 503
        assert respuesta.json()["error"]["codigo"] == (
            "PERSISTENCIA_NO_DISPONIBLE"
        )
        soltar.set()
        time.sleep(0.1)
        assert cliente.post("/comando").status_code == 200


# --- Sin base: un servidor que no responde ----------------------------------


def test_un_pool_sin_servidor_no_expone_la_contrasena(caplog):
    caplog.set_level(logging.DEBUG)
    # Puerto local cerrado: falla en el acto, sin salir de la maquina.
    configuracion = _configuracion(
        f"postgresql://usuario:{PASSWORD}@127.0.0.1:1/postgres"
    )
    ajustes = AjustesPostgres(pool_espera_s=1)
    pool = abrir_pool(configuracion, ajustes)
    try:
        unidad = UnidadDeTrabajoPostgres(pool, ajustes)
        with pytest.raises(PersistenciaNoDisponibleError) as capturado:
            with unidad.transaccion():
                pass
    finally:
        pool.close()
    assert PASSWORD not in str(capturado.value)
    assert PASSWORD not in caplog.text
    assert not unidad.en_curso()
