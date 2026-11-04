"""Traduccion de errores de PostgreSQL, sin base: errores simulados.

Los errores reales se prueban en ``tests/postgres/test_base_local.py``.
"""

from types import SimpleNamespace

import pytest

from app.repositories.exceptions import (
    ConflictoDeEscrituraError,
    PersistenciaError,
)
from app.storage.postgres import es_reintentable, traducir_error

DATO_DE_UNA_FILA = "documento 30123456"


class ErrorSimulado(Exception):
    """Lo que importa de un ``psycopg.Error``: SQLSTATE y diagnostico."""

    def __init__(self, sqlstate, restriccion=None):
        super().__init__(f"Key (documento)=({DATO_DE_UNA_FILA}) existe")
        self.sqlstate = sqlstate
        self.diag = SimpleNamespace(constraint_name=restriccion)


@pytest.mark.parametrize("codigo", ["23505", "23514", "23503", "23001"])
def test_una_restriccion_violada_es_un_conflicto(codigo):
    error = ErrorSimulado(codigo, "insumo_stock_valido")
    traducido = traducir_error(error)
    assert isinstance(traducido, ConflictoDeEscrituraError)
    assert not es_reintentable(error)
    assert codigo in str(traducido)
    assert "insumo_stock_valido" in str(traducido)


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
