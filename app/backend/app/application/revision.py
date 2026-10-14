"""Tramo de revision tecnica: el tecnico revisa una Orden EN_REVISION.

    realizar_revision   PROC-REP-065

Una sola intencion humana (ACT-TECH). Termina ahi a proposito: despues
vuelve a aparecer una frontera de actor -Recepcion debe definir la
reparacion (PROC-REP-068/075, ``ingreso.definir_reparacion_desde_revision``)-.

La capacidad vive en ``app.services.revisiones`` y por ahora deja su
rastro en el historial de la Orden. No es una entidad: ver ese modulo.
"""

from app.domain.models import OrdenReparacion
from app.services import registrar_revision_tecnica

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar


def realizar_revision(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    resultado: str,
) -> OrdenReparacion:
    """El tecnico realiza la revision y registra su resultado."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_revision_tecnica(
            orden, usuario=usuario, resultado=resultado, fecha=fecha
        )
        contexto.ordenes.guardar(orden)
    return orden
