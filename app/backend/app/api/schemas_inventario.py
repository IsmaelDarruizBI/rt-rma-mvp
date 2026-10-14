"""DTOs HTTP del inventario operativo.

Aparte de ``schemas`` para no mezclar la Orden con el stock. Igual que
alli: los ``Decimal`` viajan como string y las cantidades derivadas
(reservado, disponible) se calculan al leer, nunca se persisten.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.application import (
    DetalleInsumo,
    ResultadoMovimientoStock,
    ResultadoRevalidacionMasiva,
)
from app.domain.models import TipoMovimientoInsumo
from app.services import (
    EvidenciaFaltante,
    MovimientoHistorial,
    ReservaVigente,
    SituacionInsumo,
)

# --- Entrada -----------------------------------------------------------------


class IngresoStockIn(BaseModel):
    """``POST /api/inventory/{insumo_id}/receipts``: entrada de stock.

    ``operacion_id`` (generado por quien envia) evita aplicar dos veces un
    reintento.
    """

    usuario_id: str = Field(min_length=1)
    cantidad: Decimal = Field(gt=0)
    motivo: str = Field(min_length=1)
    referencia: str | None = None
    operacion_id: str | None = None


class AjusteStockIn(BaseModel):
    """``POST /api/inventory/{insumo_id}/adjustments``.

    ``diferencia`` en unidades: positiva suma, negativa resta. Todo ajuste
    negativo exige ``confirmado: true`` (409 CONFIRMACION_REQUERIDA, con el
    impacto en el mensaje).
    """

    usuario_id: str = Field(min_length=1)
    diferencia: Decimal
    motivo: str = Field(min_length=1)
    referencia: str | None = None
    operacion_id: str | None = None
    confirmado: bool = False


class RevalidacionIn(BaseModel):
    """``POST /api/inventory/revalidate-orders`` (Administracion o
    Coordinacion)."""

    usuario_id: str = Field(min_length=1)


# --- Salida ------------------------------------------------------------------


class ReservaVigenteOut(BaseModel):
    orden_id: str
    detalle_id: str
    movimiento_id: str
    ejecucion_id: str | None = None
    cantidad: Decimal
    fecha: datetime

    @classmethod
    def desde_servicio(cls, reserva: ReservaVigente) -> "ReservaVigenteOut":
        return cls(**reserva.__dict__)


class SituacionInsumoOut(BaseModel):
    """Un insumo con sus tres cantidades.

    ``disponible = stock_fisico - reservado``; puede ser negativo (override
    o faltante): ``faltante`` lo marca, igual que un fisico negativo.
    """

    id: str
    codigo: str
    nombre: str
    unidad: str | None = None
    activo: bool
    stock_fisico: Decimal
    reservado: Decimal
    disponible: Decimal
    faltante: bool
    disponible_negativo: bool
    fisico_negativo: bool
    ordenes_con_reserva: int
    detalles_con_reserva: int

    @classmethod
    def desde_servicio(
        cls, situacion: SituacionInsumo
    ) -> "SituacionInsumoOut":
        insumo = situacion.insumo
        return cls(
            id=insumo.id,
            codigo=insumo.codigo,
            nombre=insumo.nombre,
            unidad=insumo.unidad,
            activo=insumo.activo,
            stock_fisico=insumo.stock_fisico,
            reservado=situacion.reservado,
            disponible=situacion.disponible,
            faltante=situacion.faltante,
            disponible_negativo=situacion.disponible < 0,
            fisico_negativo=insumo.stock_fisico < 0,
            ordenes_con_reserva=situacion.ordenes_con_reserva,
            detalles_con_reserva=situacion.detalles_con_reserva,
        )


class MovimientoInventarioOut(BaseModel):
    """Un movimiento tal como se registro.

    ``origen``: ORDEN (trazado a un Detalle) o INVENTARIO (ingreso o
    ajuste). ``usuario_id`` en ``null`` es un paso de sistema (185/210):
    la trazabilidad al tecnico sigue por la Ejecucion.
    """

    id: str
    origen: str
    tipo: TipoMovimientoInsumo
    insumo_id: str
    cantidad: Decimal
    fecha: datetime
    usuario_id: str | None = None
    orden_id: str | None = None
    detalle_id: str | None = None
    ejecucion_id: str | None = None
    movimiento_origen_id: str | None = None
    observacion: str | None = None
    referencia: str | None = None
    stock_anterior: Decimal | None = None
    stock_resultante: Decimal | None = None
    disponible_resultante: Decimal | None = None

    @classmethod
    def desde_servicio(
        cls, movimiento: MovimientoHistorial
    ) -> "MovimientoInventarioOut":
        return cls(**movimiento.__dict__)


class EvidenciaFaltanteOut(BaseModel):
    fecha: datetime
    origen: str
    descripcion: str
    orden_id: str | None = None
    movimiento_id: str | None = None

    @classmethod
    def desde_servicio(
        cls, evidencia: EvidenciaFaltante
    ) -> "EvidenciaFaltanteOut":
        return cls(**evidencia.__dict__)


class DetalleInsumoOut(BaseModel):
    """``GET /api/inventory/{insumo_id}``."""

    insumo: SituacionInsumoOut
    reservas: list[ReservaVigenteOut]
    movimientos: list[MovimientoInventarioOut]
    faltantes: list[EvidenciaFaltanteOut]

    @classmethod
    def desde_aplicacion(cls, detalle: DetalleInsumo) -> "DetalleInsumoOut":
        return cls(
            insumo=SituacionInsumoOut.desde_servicio(detalle.situacion),
            reservas=[
                ReservaVigenteOut.desde_servicio(reserva)
                for reserva in detalle.situacion.reservas
            ],
            movimientos=[
                MovimientoInventarioOut.desde_servicio(movimiento)
                for movimiento in detalle.movimientos
            ],
            faltantes=[
                EvidenciaFaltanteOut.desde_servicio(evidencia)
                for evidencia in detalle.faltantes
            ],
        )


class MovimientoStockOut(BaseModel):
    """Resultado de un ingreso o ajuste: el movimiento y el insumo."""

    movimiento: MovimientoInventarioOut
    insumo: SituacionInsumoOut

    @classmethod
    def desde_aplicacion(
        cls, resultado: ResultadoMovimientoStock
    ) -> "MovimientoStockOut":
        movimiento = resultado.movimiento
        return cls(
            movimiento=MovimientoInventarioOut(
                id=movimiento.id,
                origen="INVENTARIO",
                tipo=movimiento.tipo,
                insumo_id=movimiento.insumo_id,
                cantidad=movimiento.cantidad,
                fecha=movimiento.fecha,
                usuario_id=movimiento.usuario_id,
                observacion=movimiento.motivo,
                referencia=movimiento.referencia,
                stock_anterior=movimiento.stock_anterior,
                stock_resultante=movimiento.stock_resultante,
                disponible_resultante=movimiento.disponible_resultante,
            ),
            insumo=SituacionInsumoOut.desde_servicio(resultado.situacion),
        )


class RevalidacionOrdenOut(BaseModel):
    orden_id: str
    resultado: str
    detalle: str
    current_process: str | None = None
    estado_workflow: str | None = None
    detalles_revalidados: list[str] = []


class RevalidacionOut(BaseModel):
    """Resumen de la revalidacion masiva, con una fila por Orden."""

    usuario_id: str
    fecha: datetime
    evaluadas: int
    trabajables: int
    siguen_esperando: int
    otra_intervencion: int
    sin_cambios: int
    errores: int
    ordenes: list[RevalidacionOrdenOut]

    @classmethod
    def desde_aplicacion(
        cls, resultado: ResultadoRevalidacionMasiva
    ) -> "RevalidacionOut":
        return cls(
            usuario_id=resultado.usuario_id,
            fecha=resultado.fecha,
            evaluadas=resultado.evaluadas,
            trabajables=resultado.trabajables,
            siguen_esperando=resultado.siguen_esperando,
            otra_intervencion=resultado.otra_intervencion,
            sin_cambios=resultado.sin_cambios,
            errores=resultado.errores,
            ordenes=[
                RevalidacionOrdenOut(**orden.__dict__)
                for orden in resultado.ordenes
            ],
        )
