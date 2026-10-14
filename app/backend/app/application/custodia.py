"""Recepcion fisica del equipo: datos del ingreso y custodia.

    registrar_recepcion            registra o corrige los datos del ingreso
                                   (antes de confirmar; regulariza una Orden
                                   anterior)
    confirmar_recepcion            el equipo quedo en el local (custodia)
    registrar_no_recepcion         el equipo nunca ingreso (Orden cancelada)
    agregar_observacion_recepcion  observacion complementaria

Acciones transversales (``ACC-REP-023/024/025/027``): no mueven
``current_process`` por si mismas. Las reglas viven en
``services.custodia``.
"""

from app.domain.models import DatosRecepcion, Equipo, OrdenReparacion
from app.services import (
    agregar_nota_recepcion,
    cerrar_cancelada_si_corresponde,
    confirmar_recepcion_fisica,
    registrar_datos_recepcion,
    registrar_equipo_no_recibido,
)

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar


def registrar_recepcion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    datos: DatosRecepcion,
    equipo: Equipo | None = None,
) -> OrdenReparacion:
    """Recepcion registra o corrige los datos del ingreso."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_datos_recepcion(
            orden, usuario=usuario, fecha=fecha, datos=datos, equipo=equipo
        )
        contexto.ordenes.guardar(orden)
    return orden


def confirmar_recepcion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """Recepcion confirma que el equipo quedo fisicamente en el local."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = confirmar_recepcion_fisica(
            orden, usuario=usuario, fecha=fecha, observaciones=observaciones
        )
        contexto.ordenes.guardar(orden)
    return orden


def registrar_no_recepcion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    motivo: str,
) -> OrdenReparacion:
    """Registra "Equipo no recibido" en una Orden cancelada.

    Sin equipo que devolver, la Orden pasa por la verificacion financiera
    (PROC-REP-268): cierra, o espera la devolucion del saldo a favor.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_equipo_no_recibido(
            orden, usuario=usuario, fecha=fecha, motivo=motivo
        )
        orden = cerrar_cancelada_si_corresponde(orden, fecha=fecha)
        contexto.ordenes.guardar(orden)
    return orden


def agregar_observacion_recepcion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    texto: str,
) -> OrdenReparacion:
    """Agrega una observacion complementaria del ingreso."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = agregar_nota_recepcion(
            orden, usuario=usuario, fecha=fecha, texto=texto
        )
        contexto.ordenes.guardar(orden)
    return orden
