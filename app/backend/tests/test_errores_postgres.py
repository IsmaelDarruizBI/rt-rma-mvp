"""Traduccion de errores de PostgreSQL, sin base: errores simulados.

Los errores reales se prueban en ``tests/postgres/test_base_local.py``.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errores import registrar_manejadores_de_error
from app.repositories.exceptions import (
    ConflictoDeEscrituraError,
    DatosInvalidosError,
    PersistenciaError,
    RestriccionDeIntegridadError,
)
from app.storage.postgres import es_reintentable, traducir_error

DATO_DE_UNA_FILA = "documento 30123456"


class ErrorSimulado(Exception):
    """Lo que importa de un ``psycopg.Error``: SQLSTATE y diagnostico."""

    def __init__(self, sqlstate, restriccion=None):
        super().__init__(f"Key (documento)=({DATO_DE_UNA_FILA}) existe")
        self.sqlstate = sqlstate
        self.diag = SimpleNamespace(constraint_name=restriccion)


@pytest.mark.parametrize(
    ("codigo", "restriccion"),
    [
        ("23514", "insumo_stock_valido"),
        ("23503", "orden_equipo_id_fkey"),
        ("23502", None),
        ("23001", None),
        ("23505", "ejecucion_insumo_pkey"),
    ],
)
def test_una_restriccion_violada_no_es_un_conflicto(codigo, restriccion):
    """L-3: un CHECK o una clave primaria no dicen que otro comando haya
    cambiado los datos, y repetir la operacion daria lo mismo."""
    error = ErrorSimulado(codigo, restriccion)
    traducido = traducir_error(error)
    assert isinstance(traducido, RestriccionDeIntegridadError)
    assert isinstance(traducido, PersistenciaError)
    assert not isinstance(traducido, ConflictoDeEscrituraError)
    assert not es_reintentable(error)
    assert codigo in str(traducido)
    assert restriccion is None or restriccion in str(traducido)
    assert "cambiaron" not in str(traducido)


@pytest.mark.parametrize(
    "restriccion", ["orden_codigo_key", "documento_cliente_numero_unico", None]
)
def test_una_clave_unica_de_negocio_es_un_conflicto(restriccion):
    """Otra operacion la creo primero. Sin nombre: la de un trigger."""
    error = ErrorSimulado("23505", restriccion)
    traducido = traducir_error(error)
    assert isinstance(traducido, ConflictoDeEscrituraError)
    assert not es_reintentable(error)
    assert "Ya existe" in str(traducido)
    assert "cambiaron" not in str(traducido)
    assert traducido.restriccion == restriccion


@pytest.mark.parametrize("codigo", ["22001", "22003", "22007", "22P02"])
def test_un_valor_invalido_es_un_dato_invalido(codigo):
    error = ErrorSimulado(codigo)
    traducido = traducir_error(error)
    assert isinstance(traducido, DatosInvalidosError)
    assert isinstance(traducido, PersistenciaError)
    assert not es_reintentable(error)
    assert codigo in str(traducido)


def test_un_bloqueo_agotado_no_dice_que_los_datos_cambiaron():
    traducido = traducir_error(ErrorSimulado("55P03"))
    assert isinstance(traducido, ConflictoDeEscrituraError)
    assert traducido.reintentable
    assert "Otra operacion esta usando" in str(traducido)
    assert "cambiaron" not in str(traducido)


@pytest.mark.parametrize("codigo", ["40001", "40P01"])
def test_la_concurrencia_dice_que_los_datos_cambiaron(codigo):
    assert "cambiaron" in str(traducir_error(ErrorSimulado(codigo)))


@pytest.mark.parametrize("codigo", ["40001", "40P01", "55P03"])
def test_la_concurrencia_es_un_conflicto_reintentable(codigo):
    error = ErrorSimulado(codigo)
    assert es_reintentable(error)
    assert isinstance(traducir_error(error), ConflictoDeEscrituraError)


@pytest.mark.parametrize(
    ("codigo", "reintentable"),
    [
        ("40001", True),
        ("40P01", True),
        ("55P03", True),
        ("23505", False),
        ("57014", False),
        ("08006", False),
        (None, False),
    ],
)
def test_el_traducido_conserva_sqlstate_y_reintentabilidad(
    codigo, reintentable
):
    # El original no se encadena: el traducido es lo que queda.
    traducido = traducir_error(ErrorSimulado(codigo))
    assert traducido.sqlstate == codigo
    assert traducido.reintentable is reintentable


def test_un_timeout_es_un_fallo_de_persistencia():
    traducido = traducir_error(ErrorSimulado("57014"))
    assert isinstance(traducido, PersistenciaError)
    assert "no respondio a tiempo" in str(traducido)


@pytest.mark.parametrize("codigo", ["08006", "42501", "53300", "P0001", None])
def test_lo_demas_es_un_fallo_de_persistencia(codigo):
    error = ErrorSimulado(codigo)
    traducido = traducir_error(error)
    assert isinstance(traducido, PersistenciaError)
    assert not es_reintentable(error)


def test_un_error_sin_sqlstate_ni_diagnostico_se_traduce():
    traducido = traducir_error(RuntimeError("sin datos"))
    assert isinstance(traducido, PersistenciaError)
    assert "desconocido" in str(traducido)


@pytest.mark.parametrize("codigo", ["23505", "40P01", "57014", "08006"])
def test_el_mensaje_no_cita_datos_de_las_filas(codigo):
    assert DATO_DE_UNA_FILA not in str(traducir_error(ErrorSimulado(codigo)))


def _cliente_http():
    app = FastAPI()
    registrar_manejadores_de_error(app)

    @app.get("/{codigo}/{restriccion}")
    def fallar(codigo: str, restriccion: str):
        raise traducir_error(ErrorSimulado(codigo, restriccion))

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("codigo", "restriccion"),
    [
        ("40P01", "x"),
        ("55P03", "x"),
        ("23505", "orden_codigo_key"),
    ],
)
def test_lo_concurrente_sigue_siendo_409(codigo, restriccion):
    respuesta = _cliente_http().get(f"/{codigo}/{restriccion}")
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["codigo"] == "CONFLICTO_CONCURRENTE"
    # El mensaje llega al cliente: nada del esquema ni de SQL.
    assert restriccion not in respuesta.text
    assert codigo not in respuesta.text
    assert "SQLSTATE" not in respuesta.text


def test_un_conflicto_deja_el_detalle_para_el_log(caplog):
    error = ErrorSimulado("23505", "orden_codigo_key")
    with caplog.at_level("WARNING"):
        traducido = traducir_error(error)
    assert traducido.sqlstate == "23505"
    assert traducido.restriccion == "orden_codigo_key"
    assert "orden_codigo_key" in caplog.text
    assert DATO_DE_UNA_FILA not in caplog.text


@pytest.mark.parametrize(
    ("codigo", "restriccion"),
    [
        ("23514", "orden_cerrada_con_fecha"),
        ("23505", "ejecucion_insumo_pkey"),
        ("22003", "x"),
    ],
)
def test_una_restriccion_es_el_500_generico_de_siempre(codigo, restriccion):
    """Sin codigos ni formas nuevas, y sin nombres del esquema."""
    respuesta = _cliente_http().get(f"/{codigo}/{restriccion}")
    assert respuesta.status_code == 500
    assert restriccion not in respuesta.text
    assert codigo not in respuesta.text
