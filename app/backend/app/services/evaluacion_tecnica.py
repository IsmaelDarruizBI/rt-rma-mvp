"""Evaluacion tecnica de un Detalle diagnosticado por Recepcion.

PROC-REP-182 (decision) -> PROC-REP-183 (ACT-TECH) -> PROC-REP-184, con
BR-REP-035 y BR-REP-036 (V1.4, FEAT-REP-005; HP-REP-001/002 y VAR-REP-019).

Todo Detalle cuya definicion vigente la diagnostico Recepcion exige una
evaluacion CONFIRMADO sobre esa definicion antes de su primera Ejecucion. La
hace el tecnico titular de la toma, con el Detalle seleccionado (181) y
antes de la estacion (174) y la reserva (185); no reserva ni consume nada.
Resultados, aplicados de inmediato sobre el Detalle original:

- CONFIRMADO: sigue elegible, con su autorizacion vigente;
- DESCARTADO (motivo obligatorio): se cancela (300, descarte tecnico);
- REQUIERE_REDEFINICION (motivo obligatorio): el tecnico registra en el
  mismo acto la nueva definicion (127, VAR-REP-019), validada por ese acto;
  la autorizacion anterior deja de valer.

Independientemente del resultado, el tecnico registra en el mismo acto las
reparaciones adicionales que detecto (184 -> 128 -> 184, cero o mas): cada
una es un Detalle nuevo, nunca otra evaluacion del original. Se registran
antes de que el resolver (211) recalcule la Orden, para que un descarte del
unico Detalle no la deje sin trabajos vigentes cuando hay otro por registrar.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.models import (
    EvaluacionTecnica,
    OrdenReparacion,
    OrigenCancelacion,
    OrigenDiagnostico,
    ReparacionDetail,
    ResultadoEvaluacionTecnica,
    RolUsuario,
    TipoReparacion,
    Usuario,
)

from .autorizacion import validar_actor
from .cancelaciones import cancelar_detalle
from .exceptions import PrecondicionInvalidaError
from .redefinicion import aplicar_redefinicion
from .reparaciones import agregar_detalle_adicional
from .tomas import buscar_detalle, hay_ejecucion_activa, seleccionar_detalle
from .workflow import registrar_paso

NODO_DECISION = "PROC-REP-182"
NODO_EVALUACION = "PROC-REP-183"
NODO_ADICIONALES = "PROC-REP-184"

REQUIERE = "Requiere evaluacion tecnica"
NO_REQUIERE = "No requiere evaluacion tecnica"
OTRA_ADICIONAL = "Otra reparacion adicional por registrar"


@dataclass(frozen=True)
class ReparacionAdicional:
    """Un Detalle nuevo detectado en la evaluacion (PROC-REP-128)."""

    detalle_id: str
    tipo_reparacion: TipoReparacion
    observaciones: str | None = None
    detalle_origen_id: str | None = None


def evaluacion_vigente(detalle: ReparacionDetail) -> EvaluacionTecnica | None:
    """La ultima evaluacion sobre la definicion vigente, si la hay."""
    vigentes = [
        e
        for e in detalle.evaluaciones
        if e.version_definicion == detalle.version_definicion
    ]
    return vigentes[-1] if vigentes else None


def requiere_evaluacion(detalle: ReparacionDetail) -> bool:
    """PROC-REP-182: origen RECEPCION sin CONFIRMADO sobre la vigente.

    Los Detalles del tecnico (REVISION_TECNICA) y los anteriores a la
    evaluacion (sin origen) no la exigen.
    """
    if detalle.origen_diagnostico is not OrigenDiagnostico.RECEPCION:
        return False
    vigente = evaluacion_vigente(detalle)
    return not (
        vigente is not None
        and vigente.resultado is ResultadoEvaluacionTecnica.CONFIRMADO
    )


def exigir_evaluacion_vigente(detalle: ReparacionDetail) -> None:
    """Defensa del backend: sin evaluacion vigente no se reserva ni se
    ejecuta (BR-REP-035: todo camino a 185 pasa por 182)."""
    if requiere_evaluacion(detalle):
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle.id} lo diagnostico Recepcion: requiere la "
            "evaluacion tecnica antes de iniciar su primera Ejecucion "
            "(BR-REP-035)."
        )


def registrar_no_requiere(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-182 "No requiere evaluacion tecnica" -> 174, al iniciar.

    Un Detalle anterior a la evaluacion tecnica (sin origen de diagnostico,
    plan de transicion) sigue su circuito previo: no se registra 182."""
    detalle = buscar_detalle(orden, detalle_id)
    exigir_evaluacion_vigente(detalle)
    if detalle.origen_diagnostico is None:
        return orden
    return registrar_paso(
        orden,
        process_id=NODO_DECISION,
        accion="EVALUAR_SI_REQUIERE_EVALUACION",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=NO_REQUIERE,
    )


def evaluar_detalle(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    resultado: ResultadoEvaluacionTecnica,
    observaciones: str | None,
    usuario: Usuario,
    fecha: datetime,
    tipo_reparacion: TipoReparacion | None = None,
    adicionales: Sequence[ReparacionAdicional] = (),
) -> OrdenReparacion:
    """181 -> 182 (Requiere) -> 183 -> efecto -> 184 [-> 128 -> 184]*.

    El tecnico titular de la toma, sin otra Ejecucion en curso, sobre un
    Detalle trabajable que requiere la evaluacion. Exactamente un
    resultado principal. Recalcular la Orden (211) y la factibilidad del
    Detalle redefinido (080) es del comando de aplicacion.
    """
    validar_actor(usuario, RolUsuario.TECNICO)
    if hay_ejecucion_activa(orden):
        raise PrecondicionInvalidaError(
            "La Orden tiene una Ejecucion activa: se evalua antes de "
            "iniciar otra (BR-REP-007)."
        )
    detalle = buscar_detalle(orden, detalle_id)
    if not requiere_evaluacion(detalle):
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} no requiere evaluacion tecnica: lo "
            "diagnostico el tecnico o ya tiene una evaluacion CONFIRMADO "
            "sobre su definicion vigente."
        )
    observaciones = (observaciones or "").strip() or None
    if resultado is not ResultadoEvaluacionTecnica.CONFIRMADO:
        if observaciones is None:
            raise PrecondicionInvalidaError(
                f"El resultado {resultado.value} exige el motivo "
                "(BR-REP-035/036)."
            )
    if resultado is ResultadoEvaluacionTecnica.REQUIERE_REDEFINICION:
        if tipo_reparacion is None:
            raise PrecondicionInvalidaError(
                "REQUIERE_REDEFINICION exige la nueva definicion del Detalle "
                "(Tipo de Reparacion) en el mismo acto (VAR-REP-019)."
            )
        if not tipo_reparacion.activo:
            raise PrecondicionInvalidaError(
                f"El Tipo de Reparacion {tipo_reparacion.id} no esta activo."
            )
    elif tipo_reparacion is not None:
        raise PrecondicionInvalidaError(
            "Solo REQUIERE_REDEFINICION registra una definicion nueva."
        )

    # 181: seleccion (con la toma del tecnico y el Detalle trabajable).
    nueva_orden = seleccionar_detalle(
        orden, detalle_id=detalle_id, usuario=usuario, fecha=fecha
    )
    version = detalle.version_definicion
    nueva_orden = registrar_paso(
        nueva_orden,
        process_id=NODO_DECISION,
        accion="EVALUAR_SI_REQUIERE_EVALUACION",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=REQUIERE,
    )
    nueva_orden = registrar_paso(
        nueva_orden,
        process_id=NODO_EVALUACION,
        accion="EVALUAR_DETALLE",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=(
            f"{resultado.value} (definicion v{version})"
            + (f": {observaciones}" if observaciones else "")
        ),
    )
    evaluado = next(
        d for d in nueva_orden.reparaciones_detail if d.id == detalle_id
    )
    evaluado.evaluaciones.append(
        EvaluacionTecnica(
            version_definicion=version,
            resultado=resultado,
            usuario_id=usuario.id,
            fecha=fecha,
            observaciones=observaciones,
        )
    )

    if resultado is ResultadoEvaluacionTecnica.DESCARTADO:
        nueva_orden = cancelar_detalle(
            nueva_orden,
            detalle_id=detalle_id,
            usuario=usuario,
            motivo=f"Descarte tecnico: {observaciones}",
            fecha=fecha,
            origen=OrigenCancelacion.DESCARTE_TECNICO,
            exigir_rol=False,
        )
        cierre = "Original cancelado por el descarte tecnico"
    elif resultado is ResultadoEvaluacionTecnica.REQUIERE_REDEFINICION:
        nueva_orden = aplicar_redefinicion(
            nueva_orden,
            detalle_id=detalle_id,
            tipo_reparacion=tipo_reparacion,
            usuario=usuario,
            fecha=fecha,
        )
        cierre = "Original redefinido en la evaluacion tecnica"
    else:
        cierre = "Original CONFIRMADO"

    for adicional in adicionales:
        nueva_orden = registrar_paso(
            nueva_orden,
            process_id=NODO_ADICIONALES,
            accion="REPARACIONES_ADICIONALES_POR_REGISTRAR",
            fecha=fecha,
            usuario_id=usuario.id,
            reparacion_detail_id=detalle_id,
            observacion=OTRA_ADICIONAL,
        )
        nueva_orden = agregar_detalle_adicional(
            nueva_orden,
            detalle_id=adicional.detalle_id,
            tipo_reparacion=adicional.tipo_reparacion,
            usuario=usuario,
            fecha=fecha,
            observaciones=adicional.observaciones,
            detalle_origen_id=adicional.detalle_origen_id,
            detectado_en=detalle_id,
        )

    return registrar_paso(
        nueva_orden,
        process_id=NODO_ADICIONALES,
        accion="REPARACIONES_ADICIONALES_POR_REGISTRAR",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=cierre,
    )
