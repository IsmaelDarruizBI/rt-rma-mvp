"""Lotes y numeros de serie de los insumos (DEC-MI-10; BR-REP-049).

- Cada insumo configura su control: SIN_LOTE (como hasta ahora), LOTE o
  SERIE. Lo configura Administracion.
- Un lote (o una unidad serializada) se identifica por su numero dentro del
  insumo y por su origen: una recepcion de compra o un ingreso manual.
- El saldo de un lote no se guarda: es la suma de los movimientos del libro
  que lo nombran (ingresos, ajustes, consumos, desperdicios y
  devoluciones). El libro sigue siendo la unica fuente.
- STOCK SIN LOTE IDENTIFICADO: el stock fisico menos los saldos de los
  lotes identificados. Es la categoria tecnica del stock que existia antes
  de controlar el insumo por lote (no se inventan numeros historicos) y
  de lo que entre sin lote en un insumo que no lo exige.
- La disponibilidad sigue siendo una sola por insumo (fisico menos
  reservado): los lotes desagregan el fisico, no lo duplican.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class ControlInsumo(str, Enum):
    SIN_LOTE = "SIN_LOTE"
    LOTE = "LOTE"
    SERIE = "SERIE"


class OrigenLote(str, Enum):
    COMPRA = "COMPRA"
    INGRESO_MANUAL = "INGRESO_MANUAL"


#: Nombre visible del stock sin lote identificado (no es un lote).
SIN_LOTE_IDENTIFICADO = "Stock sin lote identificado"


class LoteInsumo(BaseModel):
    """Un lote o una unidad serializada de un insumo. Inmutable."""

    id: str
    insumo_id: str
    numero: str = Field(min_length=1)
    serie: bool = False
    origen: OrigenLote
    referencia: str | None = None
    usuario_id: str
    fecha: datetime


class SaldoLote(BaseModel):
    """El saldo de un lote, calculado sobre el libro."""

    lote: LoteInsumo
    saldo: Decimal


class SaldosDeInsumo(BaseModel):
    """Lotes con su saldo y el stock sin lote identificado."""

    insumo_id: str
    control: ControlInsumo
    stock_fisico: Decimal
    lotes: list[SaldoLote]
    sin_lote_identificado: Decimal
