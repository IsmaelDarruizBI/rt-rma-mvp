"""Espera de recursos (EXC-REP-001): PROC-REP-120.

Dos caminos llevan a PROC-REP-120 (V1.3): desde el ingreso
(100 -> 110 "No" -> 120) y, directo, desde PROC-REP-211 con resultado
``PENDIENTE_RECURSOS`` (sin 100 ni 110). Ambos usan
``marcar_pendiente_recursos``.

Cuando ningun Detalle es trabajable (PROC-REP-090 "Ninguno trabajable") la
Orden queda detenida en PROC-REP-100. Sin override (EXC-REP-002, otro
Slice) se decide no forzar y la Orden pasa a PROC-REP-120 esperando una
revalidacion que dispare de nuevo PROC-REP-080.

``PENDIENTE_RECURSOS`` NO es un ``EstadoWorkflow``: es el agregado derivado
por ``resolver_situacion_orden`` a partir de la condicion de los Detalles.
Aqui solo se verifica; nunca se persiste.
"""

from datetime import datetime

from app.domain.models import OrdenReparacion

from .exceptions import PrecondicionInvalidaError
from .resolucion import ResultadoEvaluacionOrden, resolver_situacion_orden
from .workflow import registrar_paso

NODO_ADVERTENCIA = "PROC-REP-100"
NODO_ESPERA = "PROC-REP-120"
_NODOS_QUE_LLEVAN_A_120 = ("PROC-REP-110", "PROC-REP-211")


def marcar_pendiente_recursos(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-120: la Orden queda pendiente de recursos.

    Solo desde PROC-REP-110 (ingreso) o PROC-REP-211 (reevaluacion) y solo
    si el resolver confirma ``PENDIENTE_RECURSOS``. No registra 100 ni 110:
    eso es de quien la invoca. PROC-REP-120 es ACT-SYSTEM (sin usuario) y
    no cambia ``estado_workflow``.
    """
    if orden.current_process not in _NODOS_QUE_LLEVAN_A_120:
        raise PrecondicionInvalidaError(
            f"PROC-REP-120 se alcanza desde PROC-REP-110 o PROC-REP-211; "
            f"la Orden esta en {orden.current_process}."
        )
    situacion = resolver_situacion_orden(orden.reparaciones_detail)
    if situacion is not ResultadoEvaluacionOrden.PENDIENTE_RECURSOS:
        raise PrecondicionInvalidaError(
            f"La Orden no esta pendiente de recursos ({situacion.value})."
        )
    return registrar_paso(
        orden,
        process_id=NODO_ESPERA,
        accion="DETALLES_PENDIENTES_POR_RECURSOS",
        fecha=fecha,
        observacion=ResultadoEvaluacionOrden.PENDIENTE_RECURSOS.value,
    )


def registrar_espera_recursos(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-110 ("No") -> PROC-REP-120.

    PROC-REP-110 no declara actor para la rama No y PROC-REP-120 es
    ACT-SYSTEM: ninguno recibe Usuario. No modifica ``estado_workflow``.
    """
    if orden.current_process != NODO_ADVERTENCIA:
        raise PrecondicionInvalidaError(
            f"Solo se espera por recursos desde {NODO_ADVERTENCIA}; la "
            f"Orden esta en {orden.current_process}."
        )
    situacion = resolver_situacion_orden(orden.reparaciones_detail)
    if situacion is not ResultadoEvaluacionOrden.PENDIENTE_RECURSOS:
        raise PrecondicionInvalidaError(
            f"La Orden no esta pendiente de recursos ({situacion.value})."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-110",
        accion="FORZAR_DETALLE_BLOQUEADO",
        fecha=fecha,
        observacion="No",
    )
    return marcar_pendiente_recursos(nueva_orden, fecha=fecha)


def exigir_espera_por_recursos(orden: OrdenReparacion) -> None:
    """La revalidacion solo se dispara desde PROC-REP-120."""
    if orden.current_process != NODO_ESPERA:
        raise PrecondicionInvalidaError(
            f"Solo se revalida una Orden en {NODO_ESPERA}; esta en "
            f"{orden.current_process}."
        )
