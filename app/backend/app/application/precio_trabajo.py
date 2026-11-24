"""Precio de un trabajo (DEC-AJ-12): definir un precio pendiente y volver a
determinarlo cuando cambia el modelo del equipo.

    definir_precio_trabajo   «Definir precio»: el de catalogo o un precio
                             manual autorizado (PRECIO_MANUAL)
    redeterminar_precios     tras corregir el modelo del equipo, antes de
                             la autorizacion del cliente (D-12.6)

Las reglas viven en ``services.precio_trabajo``.
"""

from datetime import datetime
from decimal import Decimal

from app.domain.models import OrdenReparacion, Usuario
from app.services.precio_trabajo import (
    ORIGENES_POR_MODELO,
    definir_precio,
    redeterminar_por_cambio_de_modelo,
)

from .contexto import ApplicationContext
from .ingreso import precio_manual_de
from .modificacion import orden_para_modificar


def definir_precio_trabajo(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
    usuario_id: str,
    precio: Decimal | None = None,
    motivo: str | None = None,
) -> OrdenReparacion:
    """Sin ``precio``, toma el precio de catalogo que ahora existe para el
    modelo de la Orden; con ``precio`` y ``motivo``, un precio manual."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    manual = precio_manual_de(precio, motivo)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        detalle = next(
            (d for d in orden.reparaciones_detail if d.id == detalle_id), None
        )
        tipo = (
            contexto.catalogos.obtener_tipo_reparacion(
                detalle.tipo_reparacion_id
            )
            if detalle is not None and not detalle.es_otros
            else None
        )
        orden = definir_precio(
            orden,
            detalle_id=detalle_id,
            tipo=tipo,
            usuario=usuario,
            fecha=fecha,
            manual=manual,
        )
        contexto.ordenes.guardar(orden)
    return orden


def redeterminar_precios(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
    *,
    modelo_anterior: str | None,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """D-12.6: si el modelo tecnico del equipo cambio, vuelve a determinar
    el precio de los trabajos que dependen del modelo y todavia esperan la
    autorizacion del cliente. Dentro de la transaccion del comando."""
    if orden.equipo.modelo_tecnico_id == modelo_anterior:
        return orden
    ids = {
        detalle.tipo_reparacion_id
        for detalle in orden.reparaciones_detail
        if detalle.origen_precio in ORIGENES_POR_MODELO
    }
    if not ids:
        return orden
    tipos = {
        tipo.id: tipo
        for tipo in contexto.catalogos.listar_tipos_reparacion()
        if tipo.id in ids
    }
    return redeterminar_por_cambio_de_modelo(
        orden, tipos=tipos, usuario=usuario, fecha=fecha
    )
