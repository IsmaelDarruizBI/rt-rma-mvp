"""Descuentos comerciales sobre los trabajos de una Orden (MVP v2).

Un descuento es un ajuste aparte de los precios: el precio snapshot de cada
Detalle no se toca y el catalogo tampoco. La Orden guarda TODOS los
registros (append-only): el vigente es el ultimo, salvo que ese ultimo
quite el descuento (``tipo`` en ``None``). Cada registro dice quien lo
aplico, cuando y por que.

    importe_de_descuento   cuanto descuenta sobre un subtotal (nunca mas
                           que el subtotal)
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field

from .enums import TipoDescuento

CENTAVO = Decimal("0.01")


class RegistroDescuento(BaseModel):
    """Un cambio del descuento de la Orden: aplicarlo, cambiarlo o quitarlo.

    ``tipo`` y ``valor`` en ``None``: se quito el descuento. Con
    PORCENTAJE, ``valor`` es el porcentaje (0-100); con IMPORTE, pesos.
    """

    tipo: TipoDescuento | None = None
    valor: Decimal | None = Field(default=None, gt=0)
    motivo: str
    usuario_id: str
    fecha: datetime


def importe_de_descuento(
    subtotal: Decimal, registro: RegistroDescuento | None
) -> Decimal:
    """Lo que descuenta ese registro sobre ``subtotal``, redondeado al
    centavo y nunca mayor que el subtotal (el total no queda negativo)."""
    if registro is None or registro.tipo is None or subtotal <= 0:
        return Decimal("0")
    if registro.tipo is TipoDescuento.PORCENTAJE:
        importe = (subtotal * registro.valor / Decimal("100")).quantize(
            CENTAVO, rounding=ROUND_HALF_UP
        )
    else:
        importe = registro.valor
    return min(importe, subtotal)
