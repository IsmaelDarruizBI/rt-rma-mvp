"""Tramo de Coordinacion: priorizar e ingresar a la cola.

    encolar_orden                   PROC-REP-150 -> 170
    encolar_si_ingreso_automatico   150 (4 - Normal) -> 170 sin paso humano
                                    para las Ordenes del ingreso inicial
    cambiar_prioridad_de_orden      ACC-REP-007 en una Orden ya en el taller

PROC-REP-150 es la unica decision humana (ACT-COORD); PROC-REP-170 es
ACT-SYSTEM y ocurre a continuacion sin intervencion de nadie, asi que
viaja en el mismo comando. El siguiente actor humano es el tecnico, y
ahi se corta.

MVP v2: una Orden que entro por el ingreso inicial (con su comprobante de
ingreso y autorizacion) entra sola a la cola con prioridad 4 al
habilitarse; despues un tecnico, Coordinacion o Recepcion puede cambiar
la prioridad. Los demas caminos siguen pasando por ``encolar_orden``.
"""

from datetime import datetime

from app.domain.models import EstadoWorkflow, OrdenReparacion, TipoDocumento
from app.services import (
    cambiar_prioridad,
    definir_prioridad,
    fue_priorizada,
    ingresar_a_cola,
    ingresar_a_cola_con_prioridad_predeterminada,
    ultimo_documento,
)

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar


def encolar_orden(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    prioridad: int,
) -> OrdenReparacion:
    """El Coordinador prioriza la Orden y esta queda EN_COLA."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = definir_prioridad(
            orden, prioridad=prioridad, usuario=usuario, fecha=fecha
        )
        orden = ingresar_a_cola(orden, fecha=fecha)
        contexto.ordenes.guardar(orden)
    return orden


def encolar_si_ingreso_automatico(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
    usuario_id: str | None = None,
) -> OrdenReparacion:
    """Si la Orden del ingreso inicial quedo HABILITADA por primera vez,
    entra sola a la cola con la prioridad predeterminada (4 - Normal).

    Vale cuando se habilita en el mismo ingreso o despues (por ejemplo, al
    revalidar los recursos que faltaban). Sin comprobante de ingreso, o ya
    priorizada, no hace nada: los demas caminos se encolan como siempre.
    """
    if (
        orden.estado_workflow is not EstadoWorkflow.HABILITADA
        or fue_priorizada(orden)
        or ultimo_documento(orden, TipoDocumento.COMPROBANTE_INGRESO) is None
    ):
        return orden
    return ingresar_a_cola_con_prioridad_predeterminada(
        orden, fecha=fecha, usuario_id=usuario_id
    )


def cambiar_prioridad_de_orden(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    prioridad: int,
    motivo: str | None = None,
) -> OrdenReparacion:
    """Un tecnico, Coordinacion o Recepcion cambia la prioridad (ACC-REP-007).

    No es entrar a la cola: la Orden ya esta en el taller. La cola se
    reordena sola por prioridad.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = cambiar_prioridad(
            orden,
            prioridad=prioridad,
            usuario=usuario,
            fecha=fecha,
            motivo=motivo,
        )
        contexto.ordenes.guardar(orden)
    return orden
