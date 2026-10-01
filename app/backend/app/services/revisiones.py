"""Revision tecnica de una Orden EN_REVISION (PROC-REP-065).

Este modulo es la CAPACIDAD de revisar, no una entidad persistida. Hoy
esa capacidad vive dentro de RMA y deja su rastro en el historial de la
Orden (quien, cuando, resultado). Manana podra ser satisfecha por un
aggregate independiente (``OrdenRevision``) sin cambiar el circuito
posterior: la Orden solo necesita saber que "la revision se realizo" y
cual fue su resultado.

Deliberadamente NO decide Detalles, NO consulta el catalogo de Tipos de
Reparacion y NO habilita la Orden: eso es PROC-REP-068/075, de Recepcion.
"""

from datetime import datetime

from app.domain.models import (
    EstadoWorkflow,
    OrdenReparacion,
    RolUsuario,
    Usuario,
)

from .autorizacion import validar_actor
from .exceptions import PrecondicionInvalidaError
from .workflow import registrar_paso


def revision_tecnica_realizada(orden: OrdenReparacion) -> bool:
    """True si la Orden ya paso por PROC-REP-065."""
    return any(paso.process_id == "PROC-REP-065" for paso in orden.historial)


def registrar_revision_tecnica(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    resultado: str,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-065: el tecnico revisa y registra el resultado.

    El resultado es texto libre no vacio (no hay catalogo rigido de
    resultados) y queda en ``HistorialWorkflow.observacion`` junto con el
    tecnico y la fecha.
    """
    validar_actor(usuario, RolUsuario.TECNICO)

    if orden.estado_workflow is not EstadoWorkflow.EN_REVISION:
        raise PrecondicionInvalidaError(
            f"Solo se revisa una Orden EN_REVISION; esta en "
            f"{orden.estado_workflow.value}."
        )
    if orden.reparaciones_detail:
        raise PrecondicionInvalidaError(
            "La Orden ya tiene Detalles definidos: la revision inicial "
            "ya no corresponde."
        )
    if revision_tecnica_realizada(orden):
        raise PrecondicionInvalidaError(
            "La revision tecnica (PROC-REP-065) ya fue registrada."
        )
    if not resultado.strip():
        raise PrecondicionInvalidaError(
            "El resultado de la revision tecnica no puede estar vacio."
        )

    return registrar_paso(
        orden,
        process_id="PROC-REP-065",
        accion="REALIZAR_REVISION_TECNICA",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=resultado.strip(),
    )
