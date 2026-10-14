"""Tramo de cancelacion: Detalles, Orden y devolucion del equipo.

    cancelar_detalle      PROC-REP-300 -> 211 [-> CANCELADA | 120 | 125 ...]
    cancelar_orden        PROC-REP-305 -> 211, o PROC-REP-306 sin Detalles
    registrar_devolucion  PROC-REP-270 (Orden CANCELADA) -> EVT-REP-999

Como el resto de los comandos, cargan la Orden por
``orden_para_modificar`` (seccion critica y Orden cerrada) y la guardan una
sola vez. Despues de cancelar Detalles, el desenlace lo decide el resolver
de siempre (``evaluar_situacion_orden``): no hay una segunda maquina de
estados para la cancelacion.
"""

from app.domain.models import OrdenReparacion
from app.services import cancelar_detalle as cancelar_detalle_servicio
from app.services import cancelar_orden as cancelar_orden_servicio
from app.services import (
    evaluar_situacion_orden,
    registrar_devolucion_equipo,
)

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar


def cancelar_detalle(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
    usuario_id: str,
    motivo: str,
) -> OrdenReparacion:
    """Cancela UN Detalle pendiente y reevalua la Orden (300 -> 211)."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = cancelar_detalle_servicio(
            orden,
            detalle_id=detalle_id,
            usuario=usuario,
            motivo=motivo,
            fecha=fecha,
        )
        orden, _ = evaluar_situacion_orden(orden, fecha=fecha)
        contexto.ordenes.guardar(orden)
    return orden


def cancelar_orden(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    motivo: str,
) -> OrdenReparacion:
    """Cancela los trabajos pendientes de la Orden (305 -> 211 | 306).

    Sin Detalles, PROC-REP-306 ya deja la Orden CANCELADA: no hay nada que
    reevaluar.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        con_detalles = bool(orden.reparaciones_detail)
        orden = cancelar_orden_servicio(
            orden, usuario=usuario, motivo=motivo, fecha=fecha
        )
        if con_detalles:
            orden, _ = evaluar_situacion_orden(orden, fecha=fecha)
        contexto.ordenes.guardar(orden)
    return orden


def registrar_devolucion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    recibido_por: str,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """Devolucion fisica del equipo de una Orden CANCELADA (270 -> fin)."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_devolucion_equipo(
            orden,
            usuario=usuario,
            recibido_por=recibido_por,
            observaciones=observaciones,
            fecha=fecha,
        )
        contexto.ordenes.guardar(orden)
    return orden
