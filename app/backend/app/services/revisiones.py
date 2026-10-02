"""Revision tecnica de una Orden EN_REVISION (PROC-REP-065).

Este modulo es la CAPACIDAD de revisar, no una entidad persistida. Hoy
esa capacidad vive dentro de RMA y deja su rastro en el historial de la
Orden (quien, cuando, resultado). Manana podra ser satisfecha por un
aggregate independiente (``OrdenRevision``) sin cambiar el circuito
posterior: la Orden solo necesita saber que "la revision se realizo" y
cual fue su resultado.

Deliberadamente NO decide Detalles, NO consulta el catalogo de Tipos de
Reparacion y NO habilita la Orden: eso es PROC-REP-068/075, de Recepcion.

Tambien el desenlace "No" de PROC-REP-068: PROC-REP-069, finalizacion
SIN_REPARACION (BR-REP-010). No es un estado de workflow: se deriva del
historial (``finalizada_sin_reparacion``) y, como REPARACION_LISTA, deja
la Orden lista para el cierre por Origen (``lista_para_cierre``).
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

RESULTADO_SIN_REPARACION = "SIN_REPARACION"


def revision_tecnica_realizada(orden: OrdenReparacion) -> bool:
    """True si la Orden ya paso por PROC-REP-065."""
    return any(paso.process_id == "PROC-REP-065" for paso in orden.historial)


def finalizada_sin_reparacion(orden: OrdenReparacion) -> bool:
    """True si la Orden concluyo SIN_REPARACION (paso por PROC-REP-069)."""
    return any(paso.process_id == "PROC-REP-069" for paso in orden.historial)


def lista_para_cierre(orden: OrdenReparacion) -> bool:
    """La Orden tiene un resultado y puede seguir al cierre (PROC-REP-250).

    PROC-REP-250 se alcanza desde PROC-REP-240 (REPARACION_LISTA) o desde
    PROC-REP-069 (SIN_REPARACION). Es la unica condicion que comparten
    notificar, validar la condicion de entrega, el comprobante final, la
    entrega y el informe a Gestion RT; ninguno vuelve a decidirlo por su
    cuenta.
    """
    return (
        orden.estado_workflow is EstadoWorkflow.REPARACION_LISTA
        or finalizada_sin_reparacion(orden)
    )


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


def registrar_finalizacion_sin_reparacion(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-068 ("No") -> PROC-REP-069: la Orden concluye SIN_REPARACION.

    BR-REP-010 / ACT-RECEP: tras la revision tecnica (PROC-REP-065) no se
    pudo -o no corresponde- definir ninguna reparacion. Exige la Orden
    EN_REVISION ya revisada, sin Detalles y un motivo no vacio (sin
    catalogo rigido de motivos). Registra usuario, fecha, motivo y
    observaciones en el historial.

    No crea Detalles, ni un Tipo de Reparacion ficticio, ni precio: el
    Subtotal es 0. No cambia ``estado_workflow`` (SIN_REPARACION no es un
    estado de workflow): la Orden sigue al cierre segun su Origen
    (PROC-REP-250), como despues de REPARACION_LISTA.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    if orden.estado_workflow is not EstadoWorkflow.EN_REVISION:
        raise PrecondicionInvalidaError(
            f"Solo finaliza sin reparacion una Orden EN_REVISION; esta en "
            f"{orden.estado_workflow.value}."
        )
    if not revision_tecnica_realizada(orden):
        raise PrecondicionInvalidaError(
            "Falta la revision tecnica (PROC-REP-065) antes de decidir que "
            "no hay reparacion."
        )
    if finalizada_sin_reparacion(orden):
        raise PrecondicionInvalidaError(
            "La Orden ya finalizo SIN_REPARACION (PROC-REP-069)."
        )
    if orden.reparaciones_detail:
        raise PrecondicionInvalidaError(
            "La Orden ya tiene Detalles definidos: no puede finalizar sin "
            "reparacion."
        )
    if not motivo.strip():
        raise PrecondicionInvalidaError(
            "La finalizacion sin reparacion exige un motivo (BR-REP-010)."
        )

    detalle = f"{RESULTADO_SIN_REPARACION} · Motivo: {motivo.strip()}"
    if observaciones and observaciones.strip():
        detalle += f" · Observaciones: {observaciones.strip()}"

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-068",
        accion="SE_PUDO_DEFINIR_REPARACION",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion="No",
    )
    return registrar_paso(
        nueva_orden,
        process_id="PROC-REP-069",
        accion="REGISTRAR_FINALIZACION_SIN_REPARACION",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=detalle,
    )
