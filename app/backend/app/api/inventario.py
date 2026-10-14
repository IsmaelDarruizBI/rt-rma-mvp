"""Endpoints del inventario operativo.

Consulta abierta a todos los roles (el MVP no autentica lecturas). Los
ingresos, ajustes y la revalidacion masiva validan el rol en el dominio
(Administracion o Coordinacion, provisorio). El router no calcula stock:
delega en ``app.application``.
"""

from fastapi import APIRouter

from app.application import (
    consultar_inventario,
    detalle_de_insumo,
    movimientos_de_inventario,
    registrar_ajuste_stock,
    registrar_ingreso_stock,
    revalidar_ordenes_pendientes,
)
from app.domain.models import TipoMovimientoInsumo

from .dependencias import ContextoDep
from .schemas_inventario import (
    AjusteStockIn,
    DetalleInsumoOut,
    IngresoStockIn,
    MovimientoInventarioOut,
    MovimientoStockOut,
    RevalidacionIn,
    RevalidacionOut,
    SituacionInsumoOut,
)

router = APIRouter(prefix="/api/inventory", tags=["inventario"])


@router.get("")
def get_inventario(
    contexto: ContextoDep,
    buscar: str | None = None,
    solo_faltantes: bool = False,
) -> list[SituacionInsumoOut]:
    """Insumos con stock fisico, reservado y disponible.

    ``buscar`` filtra por codigo o nombre; ``solo_faltantes`` deja los que
    tienen disponible o fisico negativo.
    """
    return [
        SituacionInsumoOut.desde_servicio(situacion)
        for situacion in consultar_inventario(
            contexto, buscar=buscar, solo_faltantes=solo_faltantes
        )
    ]


@router.get("/movements")
def get_movimientos(
    contexto: ContextoDep,
    insumo_id: str | None = None,
    tipo: TipoMovimientoInsumo | None = None,
) -> list[MovimientoInventarioOut]:
    """Historial de movimientos (de las Ordenes y operativos), por fecha."""
    return [
        MovimientoInventarioOut.desde_servicio(movimiento)
        for movimiento in movimientos_de_inventario(
            contexto, insumo_id=insumo_id, tipo=tipo
        )
    ]


@router.post("/revalidate-orders")
def post_revalidar_ordenes(
    cuerpo: RevalidacionIn,
    contexto: ContextoDep,
) -> RevalidacionOut:
    """Revalida las Ordenes que esperan recursos con el stock actual.

    Aplica las transiciones existentes (110 No -> 120 -> 080 -> 090 ->
    140 | 100) Orden por Orden, sin reservar stock ni tocar prioridades, y
    devuelve el resultado de cada una.
    """
    return RevalidacionOut.desde_aplicacion(
        revalidar_ordenes_pendientes(contexto, usuario_id=cuerpo.usuario_id)
    )


@router.get("/{insumo_id}")
def get_insumo(insumo_id: str, contexto: ContextoDep) -> DetalleInsumoOut:
    """Un insumo: reservas vigentes, movimientos y faltantes registrados."""
    return DetalleInsumoOut.desde_aplicacion(
        detalle_de_insumo(contexto, insumo_id)
    )


@router.post("/{insumo_id}/receipts")
def post_ingreso(
    insumo_id: str,
    cuerpo: IngresoStockIn,
    contexto: ContextoDep,
) -> MovimientoStockOut:
    """Ingreso de stock: suma al fisico; las reservas no cambian."""
    return MovimientoStockOut.desde_aplicacion(
        registrar_ingreso_stock(
            contexto,
            insumo_id=insumo_id,
            usuario_id=cuerpo.usuario_id,
            cantidad=cuerpo.cantidad,
            motivo=cuerpo.motivo,
            referencia=cuerpo.referencia,
            operacion_id=cuerpo.operacion_id,
        )
    )


@router.post("/{insumo_id}/adjustments")
def post_ajuste(
    insumo_id: str,
    cuerpo: AjusteStockIn,
    contexto: ContextoDep,
) -> MovimientoStockOut:
    """Ajuste manual (+/- unidades) con motivo; nunca toca reservas."""
    return MovimientoStockOut.desde_aplicacion(
        registrar_ajuste_stock(
            contexto,
            insumo_id=insumo_id,
            usuario_id=cuerpo.usuario_id,
            diferencia=cuerpo.diferencia,
            motivo=cuerpo.motivo,
            referencia=cuerpo.referencia,
            operacion_id=cuerpo.operacion_id,
            confirmado=cuerpo.confirmado,
        )
    )
