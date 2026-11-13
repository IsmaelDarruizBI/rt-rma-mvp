"""Movimientos de inventario trazados al Detalle que los origino."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import TipoMovimientoInsumo


class InsumoUtilizado(BaseModel):
    """Insumo realmente usado en una Ejecucion, con su cantidad.

    Es lo que el tecnico confirma en PROC-REP-200, y la fuente de verdad
    a partir de la cual PROC-REP-210 genera los movimientos.

    DEC-MI-10: ``desperdicio`` es el material inutilizado (sale del stock
    como DESPERDICIO, no como CONSUMO); ``lote_id`` el lote o la unidad
    serializada de donde sale (sin lote: el stock sin lote identificado).
    Una linea por insumo y lote.
    """

    insumo_id: str
    cantidad: Decimal = Field(ge=0)
    desperdicio: Decimal = Field(default=Decimal("0"), ge=0)
    lote_id: str | None = None

    @model_validator(mode="after")
    def _algo_salio(self) -> "InsumoUtilizado":
        if self.cantidad + self.desperdicio <= 0:
            raise ValueError(
                "Indica lo utilizado o lo desperdiciado (mayor que cero)."
            )
        return self


class MovimientoInsumo(BaseModel):
    """Movimiento de inventario. No existe una entidad Reserva aparte.

    Una reserva es un movimiento de tipo RESERVA. Cuando se consume o se
    libera NO se modifica el movimiento original: se crea uno nuevo que
    lo referencia mediante ``movimiento_origen_id``.

        MOV-001 RESERVA -> MOV-002 CONSUMO (origen = MOV-001)

    El modelo es ``frozen`` porque los movimientos son conceptualmente
    inmutables: ambos registros se conservan siempre.

    ``usuario_id`` es opcional porque los movimientos de PROC-REP-185 y
    PROC-REP-210 los genera el sistema (ACT-SYSTEM), sin un usuario que
    los ejecute. En esos casos la trazabilidad hacia el tecnico sigue
    disponible por ``ejecucion_id -> EjecucionReparacion.usuario_id``.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    tipo: TipoMovimientoInsumo

    insumo_id: str
    reparacion_detail_id: str
    ejecucion_id: str | None = None

    cantidad: Decimal = Field(gt=0)

    movimiento_origen_id: str | None = None

    usuario_id: str | None = None
    fecha: datetime
    observacion: str | None = None
    # DEC-MI-10: lote o unidad serializada; sin lote, el stock sin lote
    # identificado.
    lote_id: str | None = None


class MovimientoStock(BaseModel):
    """Movimiento operativo del stock fisico, fuera de una Orden.

    Ingreso de existencias o ajuste manual (positivo o negativo). Es el
    registro historico de cada cambio manual del ``stock_fisico`` del
    catalogo, que sigue siendo la unica fuente del fisico: guarda el valor
    anterior y el resultante para poder reconstruir y auditar el cambio.

    Nunca toca reservas: ``reservado`` y ``disponible_resultante`` son la
    foto de las reservas de todas las Ordenes al registrarlo, para dejar
    evidencia de un faltante que el ajuste haya provocado. Inmutable: una
    correccion es otro movimiento.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    tipo: TipoMovimientoInsumo
    insumo_id: str
    cantidad: Decimal = Field(gt=0)
    stock_anterior: Decimal
    stock_resultante: Decimal
    reservado: Decimal = Decimal("0")
    disponible_resultante: Decimal
    usuario_id: str
    fecha: datetime
    motivo: str
    referencia: str | None = None
    operacion_id: str | None = None
    # DEC-MI-10: lote o unidad serializada del ingreso o ajuste.
    lote_id: str | None = None
