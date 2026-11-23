"""Ajustes Comerciales sobre los trabajos de una Orden (BR-REP-016).

Un ajuste (DESCUENTO o CORTESIA) es un concepto aparte de los precios: el
precio snapshot de cada Detalle no se toca y el catalogo tampoco. La Orden
guarda TODOS los registros (append-only). Por destino (la Orden o un
Detalle) rige el ultimo registro NO revertido, salvo que ese registro quite
el ajuste (``tipo`` en ``None``). Cada registro dice quien lo aplico,
cuando y por que.

DEC-AJ-10 (D-10.2 y D-10.4):

- un registro equivocado se revierte (``reversion``, una sola vez): deja de
  contar y vuelve a regir el anterior no revertido de ese destino;
- corregir es revertir y registrar el correcto en la misma operacion; el
  nuevo apunta al revertido con ``corrige_a``;
- cada registro nuevo guarda como evidencia el precio original (la base a
  la que se aplico), el importe aplicado y el precio final;
- si una redefinicion o una cancelacion cambia el importe efectivo de un
  ajuste vigente, queda un ``RecalculoAjuste`` inmutable.

    importe_de_descuento   cuanto descuenta sobre un subtotal (nunca mas
                           que el subtotal)
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from pydantic import BaseModel, Field

from .enums import ClaseAjuste, TipoDescuento

CENTAVO = Decimal("0.01")


def sin_ceros(valor: Decimal) -> Decimal:
    """El mismo importe sin ceros decimales de mas (``80000.00`` ->
    ``80000``), como lo relee PostgreSQL: la evidencia no cambia de forma
    al guardarse."""
    if valor == valor.to_integral_value():
        return valor.quantize(Decimal(1))
    return valor.normalize()


class ReversionAjuste(BaseModel):
    """Quien revirtio un Ajuste Comercial, cuando y por que (D-10.2). Una
    sola por registro; el registro se conserva."""

    usuario_id: str
    fecha: datetime
    motivo: str


class RegistroDescuento(BaseModel):
    """Un registro del Ajuste Comercial: aplicarlo, cambiarlo o quitarlo.

    ``tipo`` y ``valor`` en ``None``: se quito el ajuste. Con PORCENTAJE,
    ``valor`` es el porcentaje (0-100); con IMPORTE, pesos.
    """

    # D-10.2: identificador estable. Un JSON anterior no lo tiene: la Orden
    # le asigna uno por su posicion al cargarlo (siempre el mismo).
    id: str | None = None
    tipo: TipoDescuento | None = None
    valor: Decimal | None = Field(default=None, gt=0)
    motivo: str
    usuario_id: str
    fecha: datetime
    # DC09/DC11: DESCUENTO o CORTESIA. Default DESCUENTO: un JSON anterior
    # solo pudo registrar descuentos.
    clase: ClaseAjuste = ClaseAjuste.DESCUENTO
    # DC09, DEC-MI-03: el ajuste es de un Detalle (su id) o de la Orden
    # (``None``, como todos los anteriores). El de la Orden no se prorratea.
    detalle_id: str | None = None
    # D-10.4: evidencia al registrarlo. ``None`` en los registros
    # anteriores a DEC-AJ-10.
    precio_original: Decimal | None = None
    importe_aplicado: Decimal | None = None
    precio_final: Decimal | None = None
    # D-10.2: el registro revertido que este corrige.
    corrige_a: str | None = None
    reversion: ReversionAjuste | None = None

    @property
    def revertido(self) -> bool:
        return self.reversion is not None


class CausaRecalculo(str, Enum):
    """Por que cambio el importe efectivo de un ajuste vigente (D-10.4)."""

    REDEFINICION = "REDEFINICION"
    CANCELACION = "CANCELACION"


class RecalculoAjuste(BaseModel):
    """Evidencia inmutable de un recalculo de un ajuste vigente (D-10.4).

    La redefinicion o la cancelacion de un trabajo cambia la base a la que
    se aplica el ajuste (el precio del trabajo o lo que queda de la Orden) y
    con ella su importe efectivo. No se escribe un ajuste nuevo: queda este
    registro, con el precio y el importe anteriores y nuevos.
    """

    ajuste_id: str
    causa: CausaRecalculo
    detalle_id: str | None = None
    precio_anterior: Decimal
    precio_nuevo: Decimal
    importe_anterior: Decimal
    importe_nuevo: Decimal
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
