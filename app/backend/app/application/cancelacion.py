"""Tramo de cancelacion: Detalles, Orden y devolucion del equipo.

    cancelar_detalle      PROC-REP-300 -> 211 [-> 307 sin trabajos vigentes
                          | 120 | 125 ...]: nunca cancela la Orden (DC31)
    cancelar_orden        PROC-REP-308 (o 306 sin Detalles) -> 268 ->
                          EVT-REP-999: explicita, terminal y atomica (DC31)
    registrar_devolucion  PROC-REP-270 sin reparar: con la Orden activa y sin
                          trabajos pendientes (DC31), o el circuito anterior
                          de una Orden CANCELADA abierta -> 268 -> fin
                          (+ comprobante de devolucion sin reparacion)

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
from .documentos import emitir_documentos_de_salida
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
    """Cancela la Orden (DC31): cancela lo pendiente, fija CANCELADA y la
    cierra en el mismo acto. Si alguna precondicion falla, el service
    rechaza sin cambiar nada y no se guarda nada."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = cancelar_orden_servicio(
            orden, usuario=usuario, motivo=motivo, fecha=fecha
        )
        contexto.ordenes.guardar(orden)
    return orden


def registrar_devolucion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    recibido_por: str,
    observaciones: str | None = None,
    identificacion_receptor: str | None = None,
) -> OrdenReparacion:
    """Devolucion fisica del equipo sin reparar (PROC-REP-270).

    Emite el comprobante de devolucion sin reparacion (no una entrega de
    reparacion terminada, ni garantia). Con la Orden activa sin trabajos
    pendientes, la Orden sigue abierta hasta cancelarla (DC31); en una Orden
    CANCELADA del circuito anterior, sigue CANCELADA y puede cerrarse.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_devolucion_equipo(
            orden,
            usuario=usuario,
            recibido_por=recibido_por,
            observaciones=observaciones,
            identificacion_receptor=identificacion_receptor,
            fecha=fecha,
        )
        orden = emitir_documentos_de_salida(
            contexto, orden, usuario_id=usuario.id, fecha=fecha
        )
        contexto.ordenes.guardar(orden)
    return orden
