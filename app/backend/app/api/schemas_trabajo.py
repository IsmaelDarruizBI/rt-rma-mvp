"""DTOs HTTP de las bandejas de trabajo y la cola de taller.

Aparte de ``schemas`` porque son vistas compuestas: cada fila reusa el
resumen del listado (``OrdenResumenOut``) y agrega por que la Orden esta en
esa bandeja. Todo es de solo lectura.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.application import (
    Bandeja,
    ItemBandeja,
    TrabajoEnBandeja,
    VistaBandejas,
)
from app.domain.models import (
    CondicionReparacionDetail,
    EstadoReparacionDetail,
    RolUsuario,
)
from app.services import credito_pendiente, ejecucion_activa, toma_activa

from .schemas import OrdenResumenOut
from .schemas_inventario import SituacionInsumoOut


class TrabajoBandejaOut(BaseModel):
    """Un trabajo vigente de la Orden (los cancelados no se listan)."""

    detalle_id: str
    nombre: str
    estado: EstadoReparacionDetail
    trabajable: bool
    pendiente_autorizacion: bool
    condicion: CondicionReparacionDetail
    en_curso: bool
    # Insumos que hoy no alcanzan, si esta bloqueado por recursos.
    faltantes: list[str]
    # Ingreso inicial: se autoriza con el comprobante de ingreso.
    pendiente_comprobante_ingreso: bool = False

    @classmethod
    def desde_aplicacion(
        cls, trabajo: TrabajoEnBandeja
    ) -> "TrabajoBandejaOut":
        return cls(
            detalle_id=trabajo.detalle_id,
            nombre=trabajo.nombre,
            estado=trabajo.estado,
            trabajable=trabajo.trabajable,
            pendiente_autorizacion=trabajo.pendiente_autorizacion,
            condicion=trabajo.condicion,
            en_curso=trabajo.en_curso,
            faltantes=list(trabajo.faltantes),
            pendiente_comprobante_ingreso=(
                trabajo.pendiente_comprobante_ingreso
            ),
        )


class EstacionBandejaOut(BaseModel):
    id: str
    nombre: str


class ItemBandejaOut(BaseModel):
    """Una Orden en una bandeja.

    ``tarea``: lo que hay que hacer en esta bandeja; ``puede_resolver``: el
    usuario elegido puede ejecutar la accion que la resuelve.
    ``condiciones``: los demas pendientes de la Orden (estados mixtos).
    ``desde``: cuando empezo la situacion o la toma, si se conoce.
    ``estaciones`` y ``puede_tomar``, solo en la cola de taller.
    """

    orden: OrdenResumenOut
    falla: str
    tarea: str | None
    responsable: str | None
    puede_resolver: bool
    desde: datetime | None
    condiciones: list[str]
    trabajos: list[TrabajoBandejaOut]
    estacion_id: str | None
    tomada_desde: datetime | None
    trabajo_en_curso: str | None
    en_curso_desde: datetime | None
    credito: Decimal
    estaciones: list[EstacionBandejaOut]
    puede_tomar: bool

    @classmethod
    def desde_aplicacion(cls, item: ItemBandeja) -> "ItemBandejaOut":
        orden = item.orden
        toma = toma_activa(orden)
        ejecucion = ejecucion_activa(orden)
        en_curso = next((t.nombre for t in item.trabajos if t.en_curso), None)
        return cls(
            orden=OrdenResumenOut.desde_dominio(
                orden, situacion=item.situacion
            ),
            falla=orden.equipo.falla_reportada,
            tarea=item.tarea,
            responsable=item.responsable,
            puede_resolver=item.puede_resolver,
            desde=item.desde,
            condiciones=list(item.condiciones),
            trabajos=[
                TrabajoBandejaOut.desde_aplicacion(trabajo)
                for trabajo in item.trabajos
            ],
            estacion_id=toma.estacion_id if toma is not None else None,
            tomada_desde=toma.inicio if toma is not None else None,
            trabajo_en_curso=en_curso,
            en_curso_desde=ejecucion.inicio if ejecucion is not None else None,
            credito=credito_pendiente(orden),
            estaciones=[
                EstacionBandejaOut(id=estacion.id, nombre=estacion.nombre)
                for estacion in item.estaciones
            ],
            puede_tomar=item.puede_tomar,
        )


class BandejaOut(BaseModel):
    """Una bandeja: ``cantidad`` es exactamente lo que lista."""

    codigo: str
    titulo: str
    descripcion: str
    tipo: str
    cantidad: int
    destino: str | None
    ordenes: list[ItemBandejaOut]
    insumos: list[SituacionInsumoOut]

    @classmethod
    def desde_aplicacion(cls, bandeja: Bandeja) -> "BandejaOut":
        return cls(
            codigo=bandeja.codigo,
            titulo=bandeja.titulo,
            descripcion=bandeja.descripcion,
            tipo=bandeja.tipo,
            cantidad=bandeja.cantidad,
            destino=bandeja.destino,
            ordenes=[
                ItemBandejaOut.desde_aplicacion(item)
                for item in bandeja.ordenes
            ],
            insumos=[
                SituacionInsumoOut.desde_servicio(insumo)
                for insumo in bandeja.insumos
            ],
        )


class BandejasOut(BaseModel):
    usuario_id: str
    rol: RolUsuario
    bandejas: list[BandejaOut]

    @classmethod
    def desde_aplicacion(cls, vista: VistaBandejas) -> "BandejasOut":
        return cls(
            usuario_id=vista.usuario.id,
            rol=vista.usuario.rol,
            bandejas=[
                BandejaOut.desde_aplicacion(bandeja)
                for bandeja in vista.bandejas
            ],
        )
