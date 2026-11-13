"""Lotes, desperdicio y devolucion (DEC-MI-10).

- ``estado_de_lotes``: saldos de los lotes de un insumo y su stock sin lote
  identificado, calculados sobre el libro (movimientos de stock y de las
  Ordenes). Se llama dentro de la transaccion del comando, con el insumo
  bloqueado, para que dos comandos no usen el mismo saldo.
- ``validar_lotes_de_la_ejecucion``: antes de PROC-REP-210, que cada linea
  salga de un lote con saldo o del stock sin lote identificado.
- ``registrar_devolucion_insumo``: vuelve al stock lo consumido, al mismo
  lote, con la Orden abierta.
"""

from decimal import Decimal

from app.domain.models import EjecucionReparacion, Insumo, OrdenReparacion
from app.domain.models.lotes import ControlInsumo, SaldosDeInsumo
from app.services.lotes import registrar_devolucion, saldos, validar_salidas

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar


def estado_de_lotes(
    contexto: ApplicationContext, insumo: Insumo
) -> SaldosDeInsumo:
    lotes = contexto.lotes.listar(insumo.id) if contexto.lotes else []
    movimientos = [
        m
        for m in contexto.catalogos.listar_movimientos_stock()
        if m.insumo_id == insumo.id
    ]
    for orden in contexto.ordenes.listar_con_reservas([insumo.id]):
        movimientos.extend(
            m for m in orden.movimientos_insumo if m.insumo_id == insumo.id
        )
    return saldos(insumo, lotes, movimientos)


def saldos_de_insumo(
    contexto: ApplicationContext, insumo_id: str
) -> SaldosDeInsumo:
    with contexto.lectura():
        insumo = contexto.catalogos.obtener_insumo(insumo_id)
        return estado_de_lotes(contexto, insumo)


def validar_lotes_de_la_ejecucion(
    contexto: ApplicationContext, ejecucion: EjecucionReparacion
) -> None:
    """Cada linea de un insumo controlado por lote sale de un lote con
    saldo o del stock sin lote identificado; en un insumo sin control no
    se nombra lote."""
    por_insumo: dict[str, list[tuple[str | None, Decimal]]] = {}
    for linea in ejecucion.insumos_utilizados:
        por_insumo.setdefault(linea.insumo_id, []).append(
            (linea.lote_id, linea.cantidad + linea.desperdicio)
        )
    for insumo_id, salidas in sorted(por_insumo.items()):
        insumo = contexto.catalogos.obtener_insumo(insumo_id)
        nombra_lote = any(lote_id for lote_id, _ in salidas)
        if insumo.control is ControlInsumo.SIN_LOTE and not nombra_lote:
            continue
        validar_salidas(insumo, estado_de_lotes(contexto, insumo), salidas)


def registrar_devolucion_insumo(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    consumo_id: str,
    cantidad: Decimal,
    motivo: str,
    usuario_id: str,
) -> OrdenReparacion:
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with orden_para_modificar(contexto, orden_id) as orden:
        nueva = registrar_devolucion(
            orden,
            consumo_id=consumo_id,
            cantidad=cantidad,
            motivo=motivo,
            usuario=usuario,
            fecha=fecha,
        )
        devolucion = nueva.movimientos_insumo[-1]
        contexto.catalogos.bloquear_insumos([devolucion.insumo_id])
        insumo = contexto.catalogos.obtener_insumo(devolucion.insumo_id)
        anterior = insumo.stock_fisico
        contexto.catalogos.actualizar_stock_insumo(
            insumo.id, anterior + devolucion.cantidad
        )
        try:
            contexto.ordenes.guardar(nueva)
        except Exception:
            # JSON no tiene transacciones entre archivos (E4): se compensa.
            contexto.catalogos.actualizar_stock_insumo(insumo.id, anterior)
            raise
    return nueva
