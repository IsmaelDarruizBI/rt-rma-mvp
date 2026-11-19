"""Altas con codigo generado por la base (Configuracion v2, CFG-01).

``rma.siguiente_codigo`` saltea los codigos ya confirmados, pero no ve los
que otra transaccion esta insertando en ese instante (un cliente anterior
que informa el codigo, o una carga a mano). Si el alta choca con uno de
esos, la base la rechaza (``CodigoExistenteError``) y la transaccion se
revierte entera: se reintenta con un codigo nuevo. Un codigo INFORMADO por
el cliente nunca se reintenta: el choque es suyo y responde 409.
"""

from collections.abc import Callable
from typing import TypeVar

from app.repositories import CodigoExistenteError

T = TypeVar("T")

INTENTOS = 3


def con_reintento_de_codigo(intento: Callable[[], T], *, generado: bool) -> T:
    """Ejecuta ``intento`` (una transaccion completa que reserva su codigo);
    si el codigo era generado y choco, lo repite con otro."""
    for numero in range(1, INTENTOS + 1):
        try:
            return intento()
        except CodigoExistenteError:
            if not generado or numero == INTENTOS:
                raise
    raise AssertionError("inalcanzable")
