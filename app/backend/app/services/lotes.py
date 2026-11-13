"""Reglas de lotes, desperdicio y devolucion (DEC-MI-10; BR-REP-049).

- El saldo de un lote es la suma con signo de los movimientos del libro que
  lo nombran; el stock sin lote identificado es el fisico menos esos
  saldos. Nada se guarda aparte: el libro es la unica fuente.
- En un insumo controlado por lote o serie todo ingreso nombra su lote; una
  unidad serializada entra de a una y no puede estar dos veces en stock.
- Una salida (consumo, desperdicio, ajuste negativo) sale de un lote con
  saldo o del stock sin lote identificado; nunca lo deja negativo.
- Una devolucion vuelve al stock lo que se consumio de una reserva de la
  Orden, al mismo lote, sin superar lo consumido menos lo ya devuelto.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    Insumo,
    MovimientoInsumo,
    MovimientoStock,
    OrdenReparacion,
    TipoMovimientoInsumo,
    Usuario,
)
from app.domain.models.lotes import (
    ControlInsumo,
    LoteInsumo,
    SaldoLote,
    SaldosDeInsumo,
)

from . import permisos
from .autorizacion import validar_alguno_de
from .exceptions import PrecondicionInvalidaError
from .identificadores import nuevo_id

CERO = Decimal("0")
_SUMAN = {
    TipoMovimientoInsumo.INGRESO,
    TipoMovimientoInsumo.AJUSTE_POSITIVO,
    TipoMovimientoInsumo.DEVOLUCION,
}
_RESTAN = {
    TipoMovimientoInsumo.CONSUMO,
    TipoMovimientoInsumo.DESPERDICIO,
    TipoMovimientoInsumo.AJUSTE_NEGATIVO,
}


def _que(insumo: Insumo) -> str:
    return (
        "numero de serie" if insumo.control is ControlInsumo.SERIE else "lote"
    )


def signo(tipo: TipoMovimientoInsumo) -> int:
    """+1 si el movimiento suma al fisico, -1 si resta, 0 si no lo toca."""
    if tipo in _SUMAN:
        return 1
    if tipo in _RESTAN:
        return -1
    return 0


def saldos(
    insumo: Insumo,
    lotes: Sequence[LoteInsumo],
    movimientos: Iterable[MovimientoStock | MovimientoInsumo],
) -> SaldosDeInsumo:
    """Saldos de los lotes del insumo y su stock sin lote identificado."""
    por_lote = {lote.id: CERO for lote in lotes if lote.insumo_id == insumo.id}
    for movimiento in movimientos:
        if movimiento.insumo_id != insumo.id or movimiento.lote_id is None:
            continue
        por_lote[movimiento.lote_id] = (
            por_lote.get(movimiento.lote_id, CERO)
            + signo(movimiento.tipo) * movimiento.cantidad
        )
    identificados = sum(por_lote.values(), CERO)
    return SaldosDeInsumo(
        insumo_id=insumo.id,
        control=insumo.control,
        stock_fisico=insumo.stock_fisico,
        lotes=[
            SaldoLote(lote=lote, saldo=por_lote.get(lote.id, CERO))
            for lote in sorted(lotes, key=lambda lote: (lote.fecha, lote.id))
            if lote.insumo_id == insumo.id
        ],
        sin_lote_identificado=insumo.stock_fisico - identificados,
    )


def validar_salidas(
    insumo: Insumo,
    estado: SaldosDeInsumo,
    salidas: Iterable[tuple[str | None, Decimal]],
) -> None:
    """Salidas (lote, cantidad) de un insumo en una sola operacion."""
    por_lote: dict[str | None, Decimal] = {}
    for lote_id, cantidad in salidas:
        por_lote[lote_id] = por_lote.get(lote_id, CERO) + cantidad
    if insumo.control is ControlInsumo.SIN_LOTE:
        if any(lote_id is not None for lote_id in por_lote):
            raise PrecondicionInvalidaError(
                f"El insumo {insumo.id} no se controla por lote."
            )
        return
    saldos_por_lote = {s.lote.id: s.saldo for s in estado.lotes}
    for lote_id, cantidad in sorted(
        por_lote.items(), key=lambda par: par[0] or ""
    ):
        if lote_id is None:
            if cantidad > estado.sin_lote_identificado:
                raise PrecondicionInvalidaError(
                    f"El stock sin lote identificado de {insumo.id} es "
                    f"{estado.sin_lote_identificado}: elegi el lote de donde "
                    f"salen {cantidad}."
                )
            continue
        if lote_id not in saldos_por_lote:
            raise PrecondicionInvalidaError(
                f"El lote {lote_id} no es del insumo {insumo.id}."
            )
        if cantidad > saldos_por_lote[lote_id]:
            raise PrecondicionInvalidaError(
                f"El lote {lote_id} tiene {saldos_por_lote[lote_id]}: no "
                f"alcanza para {cantidad}."
            )


def validar_ingreso(
    insumo: Insumo,
    estado: SaldosDeInsumo,
    *,
    numero: str | None,
    cantidad: Decimal,
) -> None:
    """Un ingreso nombra su lote si el insumo lo exige."""
    numero = (numero or "").strip()
    if insumo.control is ControlInsumo.SIN_LOTE:
        if numero:
            raise PrecondicionInvalidaError(
                f"El insumo {insumo.id} no se controla por lote."
            )
        return
    if not numero:
        raise PrecondicionInvalidaError(
            f"El insumo {insumo.id} se controla por {_que(insumo)}: indica "
            "el numero."
        )
    if insumo.control is ControlInsumo.SERIE:
        if cantidad != 1:
            raise PrecondicionInvalidaError(
                "Una unidad serializada entra de a una: un numero de serie "
                "por unidad."
            )
        for saldo in estado.lotes:
            if saldo.lote.numero == numero and saldo.saldo > CERO:
                raise PrecondicionInvalidaError(
                    f"La unidad con serie {numero} ya esta en stock."
                )


def lote_para_ingreso(
    insumo: Insumo,
    lotes: Sequence[LoteInsumo],
    *,
    numero: str | None,
    origen,
    referencia: str | None,
    usuario: Usuario,
    fecha: datetime,
) -> tuple[LoteInsumo | None, bool]:
    """(lote, nuevo): el lote existente con ese numero o uno nuevo. Sin
    control por lote, ninguno."""
    numero = (numero or "").strip()
    if insumo.control is ControlInsumo.SIN_LOTE or not numero:
        return None, False
    for lote in lotes:
        if lote.insumo_id == insumo.id and lote.numero == numero:
            return lote, False
    return (
        LoteInsumo(
            id=nuevo_id("LOT"),
            insumo_id=insumo.id,
            numero=numero,
            serie=insumo.control is ControlInsumo.SERIE,
            origen=origen,
            referencia=referencia,
            usuario_id=usuario.id,
            fecha=fecha,
        ),
        True,
    )


def cambio_de_control(
    insumo: Insumo, nuevo: ControlInsumo, estado: SaldosDeInsumo
) -> None:
    """Transicion controlada: pasar a LOTE o SERIE deja el stock existente
    como «sin lote identificado»; volver a SIN_LOTE o cambiar entre LOTE y
    SERIE exige que no quede saldo en lotes identificados (no se pierde
    trazabilidad)."""
    if nuevo is insumo.control:
        return
    if insumo.control is ControlInsumo.SIN_LOTE:
        return
    if any(saldo.saldo != CERO for saldo in estado.lotes):
        raise PrecondicionInvalidaError(
            f"El insumo {insumo.id} tiene stock en lotes identificados: no "
            "se cambia su control hasta que esos lotes queden en cero."
        )


def registrar_devolucion(
    orden: OrdenReparacion,
    *,
    consumo_id: str,
    cantidad: Decimal,
    motivo: str,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """DEC-MI-10: el insumo utilizable vuelve al stock, al lote de donde
    salio. Referencia el CONSUMO; no supera lo consumido menos lo ya
    devuelto."""
    validar_alguno_de(usuario, permisos.DEVOLUCION_STOCK)
    motivo = (motivo or "").strip()
    if not motivo:
        raise PrecondicionInvalidaError("La devolucion exige un motivo.")
    if cantidad <= CERO:
        raise PrecondicionInvalidaError(
            "La cantidad a devolver es mayor que cero."
        )
    consumo = next(
        (
            m
            for m in orden.movimientos_insumo
            if m.id == consumo_id and m.tipo is TipoMovimientoInsumo.CONSUMO
        ),
        None,
    )
    if consumo is None:
        raise PrecondicionInvalidaError(
            f"La Orden no tiene el consumo {consumo_id}."
        )
    devuelto = sum(
        (
            m.cantidad
            for m in orden.movimientos_insumo
            if m.tipo is TipoMovimientoInsumo.DEVOLUCION
            and m.movimiento_origen_id == consumo.id
        ),
        CERO,
    )
    if devuelto + cantidad > consumo.cantidad:
        raise PrecondicionInvalidaError(
            f"Del consumo {consumo.id} quedan {consumo.cantidad - devuelto} "
            f"por devolver: no se devuelven {cantidad}."
        )
    nueva = orden.model_copy(deep=True)
    nueva.movimientos_insumo.append(
        MovimientoInsumo(
            id=nuevo_id("MOV"),
            tipo=TipoMovimientoInsumo.DEVOLUCION,
            insumo_id=consumo.insumo_id,
            reparacion_detail_id=consumo.reparacion_detail_id,
            ejecucion_id=consumo.ejecucion_id,
            cantidad=cantidad,
            movimiento_origen_id=consumo.id,
            usuario_id=usuario.id,
            fecha=fecha,
            observacion=motivo,
            lote_id=consumo.lote_id,
        )
    )
    nueva.updated_at = fecha
    return nueva
