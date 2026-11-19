"""CFG-01 (QA A, M1): un alta con codigo GENERADO que choca con uno que otra
transaccion inserto en ese instante se reintenta con otro codigo; un codigo
INFORMADO por el cliente nunca se reintenta (el choque es suyo: 409)."""

import pytest

from app.application.codigos import INTENTOS, con_reintento_de_codigo
from app.repositories import CodigoExistenteError


def _falla_veces(n: int):
    llamadas = []

    def intento():
        llamadas.append(len(llamadas) + 1)
        if len(llamadas) <= n:
            raise CodigoExistenteError("Ya existe TR-010.")
        return f"TR-0{10 + len(llamadas)}"

    return intento, llamadas


def test_generado_se_reintenta_con_otro_codigo():
    intento, llamadas = _falla_veces(1)
    assert con_reintento_de_codigo(intento, generado=True) == "TR-012"
    assert llamadas == [1, 2]


def test_informado_no_se_reintenta():
    intento, llamadas = _falla_veces(1)
    with pytest.raises(CodigoExistenteError):
        con_reintento_de_codigo(intento, generado=False)
    assert llamadas == [1]


def test_los_reintentos_tienen_un_limite():
    intento, llamadas = _falla_veces(INTENTOS + 5)
    with pytest.raises(CodigoExistenteError):
        con_reintento_de_codigo(intento, generado=True)
    assert len(llamadas) == INTENTOS


def test_otros_errores_no_se_reintentan():
    llamadas = []

    def intento():
        llamadas.append(1)
        raise ValueError("otro problema")

    with pytest.raises(ValueError):
        con_reintento_de_codigo(intento, generado=True)
    assert llamadas == [1]
