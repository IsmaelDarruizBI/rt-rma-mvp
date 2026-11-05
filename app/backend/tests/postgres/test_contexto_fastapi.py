"""La ContextVar de la unidad de trabajo bajo un servidor FastAPI real.

uvicorn en un puerto local efimero, el threadpool de FastAPI y la unidad
de trabajo PostgreSQL contra la base descartable. 400 pedidos desde 40
hilos, mitad a un endpoint sincronico y mitad a uno async que delega con
``run_in_threadpool`` (como ``post_agregar_foto``); uno de cada cinco
falla con un error de dominio. Se verifica, sin presumirlo:

- que cada pedido arranca sin transaccion y ve solo la suya;
- que la anidada se une a la exterior (misma conexion y transaccion);
- que una excepcion deja el contexto limpio, aunque el hilo se reuse;
- que hubo transacciones simultaneas y conexiones reusadas;
- que al final todas las conexiones volvieron al pool.
"""

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("psycopg_pool")

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402

from app.api.errores import registrar_manejadores_de_error  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.services import PrecondicionInvalidaError  # noqa: E402
from app.storage.postgres import (  # noqa: E402
    AjustesPostgres,
    configuracion_postgres,
)
from app.storage.postgres.transaccion import (  # noqa: E402
    _EN_CURSO,
    UnidadDeTrabajoPostgres,
    abrir_pool,
)

PEDIDOS = 400
CLIENTES = 40
CONSULTA = "select pg_backend_pid(), pg_current_xact_id()::text"

pytestmark = pytest.mark.postgres


class Servidor:
    """La app de prueba, su unidad de trabajo y lo que observo adentro."""

    def __init__(self, unidad: UnidadDeTrabajoPostgres):
        self.unidad = unidad
        self.tras_excepcion: list[bool] = []
        self.simultaneas = Counter()
        self._lock = threading.Lock()
        self.app = FastAPI()
        registrar_manejadores_de_error(self.app)
        self.app.get("/sync/{n}")(self.endpoint_sync)
        self.app.get("/async/{n}")(self.endpoint_async)

    def caso_de_uso(self, n: int, falla: bool) -> dict:
        unidad = self.unidad
        antes = unidad.en_curso()
        try:
            with unidad.transaccion():
                self._contar(+1)
                try:
                    conexion = unidad._conexion_actual()
                    exterior = conexion.execute(CONSULTA).fetchone()
                    time.sleep(0.01)
                    with unidad.transaccion():
                        anidada = (
                            unidad._conexion_actual()
                            .execute(CONSULTA)
                            .fetchone()
                        )
                    if falla:
                        raise PrecondicionInvalidaError(f"falla {n}")
                    final = conexion.execute(CONSULTA).fetchone()
                finally:
                    self._contar(-1)
        except PrecondicionInvalidaError:
            with self._lock:
                self.tras_excepcion.append(
                    unidad.en_curso() or _EN_CURSO.get() is not None
                )
            raise
        return {
            "antes": antes,
            "exterior": list(exterior),
            "anidada": list(anidada),
            "final": list(final),
            "despues": unidad.en_curso() or _EN_CURSO.get() is not None,
            "hilo": threading.get_ident(),
        }

    def endpoint_sync(self, n: int, falla: bool = False):
        return self.caso_de_uso(n, falla)

    async def endpoint_async(self, n: int, falla: bool = False):
        return await run_in_threadpool(self.caso_de_uso, n, falla)

    def _contar(self, delta: int) -> None:
        with self._lock:
            self.simultaneas["ahora"] += delta
            self.simultaneas["maximo"] = max(
                self.simultaneas["maximo"], self.simultaneas["ahora"]
            )


@pytest.fixture(scope="module")
def carga(postgres_descartable):
    """Levanta uvicorn, dispara los pedidos y devuelve lo observado."""
    configuracion = configuracion_postgres(
        Settings(
            _env_file=None,
            persistencia="postgres",
            database_url=postgres_descartable,
        )
    )
    ajustes = AjustesPostgres(pool_min=2, pool_max=8, pool_espera_s=30)
    pool = abrir_pool(configuracion, ajustes)
    servidor = Servidor(UnidadDeTrabajoPostgres(pool, ajustes))
    uvicorn_server = uvicorn.Server(
        uvicorn.Config(
            servidor.app, host="127.0.0.1", port=0, log_level="warning"
        )
    )
    hilo = threading.Thread(target=uvicorn_server.run, daemon=True)
    hilo.start()
    limite = time.monotonic() + 15
    while not uvicorn_server.started:
        assert time.monotonic() < limite, "uvicorn no arranco"
        time.sleep(0.05)
    puerto = uvicorn_server.servers[0].sockets[0].getsockname()[1]

    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{puerto}", timeout=60
        ) as cliente:

            def pedir(n):
                ruta = "sync" if n % 2 else "async"
                falla = n % 5 == 0
                respuesta = cliente.get(
                    f"/{ruta}/{n}", params={"falla": falla}
                )
                return n, falla, respuesta.status_code, respuesta.json()

            with ThreadPoolExecutor(max_workers=CLIENTES) as ejecutor:
                respuestas = list(ejecutor.map(pedir, range(PEDIDOS)))
        estadisticas = pool.get_stats()
        yield respuestas, servidor, estadisticas
    finally:
        uvicorn_server.should_exit = True
        hilo.join(10)
        pool.close()


def _exitosos(respuestas):
    return [r for r in respuestas if not r[1]]


def test_todos_los_pedidos_se_atendieron(carga):
    respuestas, _, _ = carga
    estados = Counter(r[2] for r in respuestas)
    assert estados == {200: PEDIDOS * 4 // 5, 409: PEDIDOS // 5}


def test_cada_pedido_arranca_sin_transaccion(carga):
    respuestas, _, _ = carga
    assert all(r[3]["antes"] is False for r in _exitosos(respuestas))


def test_cada_pedido_ve_solo_su_transaccion(carga):
    respuestas, _, _ = carga
    exitosos = _exitosos(respuestas)
    for _, _, _, cuerpo in exitosos:
        # Misma conexion y misma transaccion de punta a punta.
        assert cuerpo["exterior"] == cuerpo["final"]
    transacciones = {cuerpo["exterior"][1] for *_, cuerpo in exitosos}
    assert len(transacciones) == len(exitosos)


def test_la_anidada_se_une_a_la_exterior(carga):
    respuestas, _, _ = carga
    assert all(
        cuerpo["anidada"] == cuerpo["exterior"]
        for *_, cuerpo in _exitosos(respuestas)
    )


def test_al_terminar_el_contexto_queda_limpio(carga):
    respuestas, _, _ = carga
    assert all(
        cuerpo["despues"] is False for *_, cuerpo in _exitosos(respuestas)
    )


def test_una_excepcion_limpia_el_contexto(carga):
    respuestas, servidor, _ = carga
    fallidos = [r for r in respuestas if r[1]]
    assert all(r[3]["error"]["codigo"] for r in fallidos)
    assert servidor.tras_excepcion == [False] * len(fallidos)


def test_hubo_concurrencia_real_y_reuso(carga):
    respuestas, servidor, _ = carga
    exitosos = _exitosos(respuestas)
    hilos = {cuerpo["hilo"] for *_, cuerpo in exitosos}
    conexiones = {cuerpo["exterior"][0] for *_, cuerpo in exitosos}
    assert servidor.simultaneas["maximo"] > 1
    assert len(hilos) < len(exitosos)  # el threadpool reusa hilos
    assert len(conexiones) <= 8  # y el pool, conexiones


def test_todas_las_conexiones_volvieron_al_pool(carga):
    _, servidor, estadisticas = carga
    assert servidor.simultaneas["ahora"] == 0
    assert estadisticas["pool_available"] == estadisticas["pool_size"]
    assert estadisticas.get("requests_errors", 0) == 0
