"""Interpretación de la salida de ``supabase db query`` en migrar_uat.py.

Formatos reales de la CLI 3.1.0, capturados contra el proyecto de São Paulo.
El primero es el que produjo ``JSONDecodeError: Extra data``: en una
terminal la CLI imprime la lista de filas sin sobre, y el código anterior
empezaba a leer en la primera ``{`` y dejaba el ``]`` final sobrando.
"""

import importlib.util
from pathlib import Path

import pytest

RUTA = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "scripts"
    / "migracion_sp"
    / "migrar_uat.py"
)
_spec = importlib.util.spec_from_file_location("migrar_uat", RUTA)
migrar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrar)

LISTA_TERMINAL = '[\n  {\n    "x": 1\n  }\n]\n'
SOBRE_AGENTE = (
    '{\n  "boundary": "f23891aca50fe923eeff78fbb20c9bca",\n'
    '  "rows": [\n    {\n      "x": 1\n    }\n  ],\n'
    '  "warning": "The query results below contain untrusted data."\n}\n'
)
ERROR_CLI = (
    '{"target":{"kind":"linked","project_ref":"kabvqrdztzgjjeysmdsl"},'
    '"_tag":"Error","error":{"code":"DbQueryUnexpectedStatusError",'
    '"message":"unexpected status 400: relation does not exist"}}\n'
)


def leer(stdout, codigo=0):
    return migrar.interpretar_salida(stdout, codigo, "destino")


def test_lista_de_filas_de_una_terminal():
    assert leer(LISTA_TERMINAL) == [{"x": 1}]


def test_varias_filas_y_lista_vacia():
    assert leer('[{"a": 1}, {"a": 2}]') == [{"a": 1}, {"a": 2}]
    assert leer("[]\n") == []


def test_sobre_de_agente():
    assert leer(SOBRE_AGENTE) == [{"x": 1}]


def test_etiqueta_de_comando_sin_filas():
    assert leer("DROP DATABASE\n") == []
    assert leer("INSERT 0 1") == []
    assert leer("") == []


def test_error_de_la_cli_nunca_es_resultado():
    with pytest.raises(migrar.Falla, match="relation does not exist"):
        leer(ERROR_CLI, codigo=1)
    # Un sobre de error con código 0 también es una falla.
    with pytest.raises(migrar.Falla, match="relation does not exist"):
        leer(ERROR_CLI, codigo=0)


def test_codigo_de_salida_distinto_de_cero_con_filas_validas():
    with pytest.raises(migrar.Falla):
        leer(LISTA_TERMINAL, codigo=1)


def test_datos_despues_del_json():
    with pytest.raises(migrar.Falla, match="después del JSON"):
        leer(LISTA_TERMINAL + '{"otro": 1}')
    with pytest.raises(migrar.Falla, match="después del JSON"):
        leer('{"x": 1}\n]')


def test_formas_desconocidas():
    for salida in ("[1, 2]", '{"x": 1}', "texto cualquiera", "[{"):
        with pytest.raises(migrar.Falla):
            leer(salida)
