"""Tramo de Coordinacion: priorizar e ingresar a la cola.

    encolar_orden   PROC-REP-150 -> 170

PROC-REP-150 es la unica decision humana (ACT-COORD); PROC-REP-170 es
ACT-SYSTEM y ocurre a continuacion sin intervencion de nadie, asi que
viaja en el mismo comando. El siguiente actor humano es el tecnico, y
ahi se corta.
"""

from app.domain.models import OrdenReparacion
from app.services import definir_prioridad, ingresar_a_cola

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
