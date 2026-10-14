"""Autorizacion del cliente por Detalle: estado derivado (BR-REP-028).

La autorizacion es una dimension propia del Detalle, distinta de su
estado tecnico y de su condicion de bloqueo. Lo unico persistido es la
historia de decisiones (``ReparacionDetail.autorizaciones``, append-only):
todo lo demas se deriva aqui, sin flags.

- La politica del Origen decide si se exige
  (``PoliticaOrigen.requiere_autorizacion_cliente``: solo CLIENTE_EXTERNO).
  Ningun otro modulo pregunta por el Origen.
- Una decision vale para la definicion vigente del Detalle
  (``ReparacionDetail.version_definicion``): una redefinicion (PROC-REP-127)
  abre una version nueva, y la decision anterior queda en la historia sin
  autorizar la nueva (BR-REP-029).
- PENDIENTE no se registra: es la falta de decision sobre la version
  vigente de un Detalle que todavia espera una. Un Detalle pendiente no es
  trabajable, no se evalua su factibilidad ni reserva insumos, pero no
  bloquea a los demas (BR-REP-037).

Compatibilidad con JSON anterior (sin ``autorizaciones``): en
CLIENTE_EXTERNO un Detalle DEFINIDO queda PENDIENTE -no se presume una
autorizacion que nadie registro, asi que no se ejecuta en silencio-; lo ya
ejecutado, completado o cancelado se conserva tal cual y figura
SIN_DECISION.

Este modulo solo consulta: no importa ningun service de comandos, para que
toma, ejecucion, recursos y resolucion puedan usarlo sin ciclos. Registrar
la decision es ``services.decision_cliente``.
"""

from datetime import datetime
from enum import Enum

from app.domain.models import (
    CondicionReparacionDetail,
    EstadoReparacionDetail,
    OrdenReparacion,
    RegistroAutorizacionCliente,
    ReparacionDetail,
)
from app.domain.politicas import politica_de

from .exceptions import PrecondicionInvalidaError
from .resolucion import ResultadoEvaluacionOrden, resolver_situacion_orden
from .workflow import registrar_paso

NODO_ESPERA_AUTORIZACION = "PROC-REP-129"


class EstadoAutorizacion(str, Enum):
    """Autorizacion del cliente de UN Detalle, derivada (no se persiste).

    ``NO_REQUERIDA``: el Origen no la exige. ``PENDIENTE``: el Detalle
    espera la decision sobre su definicion vigente. ``AUTORIZADO`` /
    ``RECHAZADO``: la decision registrada sobre esa definicion.
    ``SIN_DECISION``: no hay decision sobre la definicion vigente, pero el
    Detalle ya no la espera (cancelado internamente, o ejecutado antes de
    que existiera la autorizacion: JSON anterior).
    """

    NO_REQUERIDA = "NO_REQUERIDA"
    PENDIENTE = "PENDIENTE"
    AUTORIZADO = "AUTORIZADO"
    RECHAZADO = "RECHAZADO"
    SIN_DECISION = "SIN_DECISION"


def requiere_autorizacion_cliente(orden: OrdenReparacion) -> bool:
    """La politica del Origen exige la decision del cliente por Detalle."""
    return politica_de(orden.origen).requiere_autorizacion_cliente


def decision_vigente(
    detalle: ReparacionDetail,
) -> RegistroAutorizacionCliente | None:
    """La decision registrada sobre la definicion vigente, si la hay."""
    version = detalle.version_definicion
    for registro in reversed(detalle.autorizaciones):
        if registro.version_definicion == version:
            return registro
    return None


def _espera_decision(detalle: ReparacionDetail) -> bool:
    """El Detalle todavia puede ejecutarse y su definicion es valida.

    Un Detalle que requiere redefinicion (EXC-REP-004) no espera decision:
    primero se redefine, y la nueva definicion pide la suya.
    """
    return (
        detalle.estado is EstadoReparacionDetail.DEFINIDO
        and detalle.condicion
        is not CondicionReparacionDetail.REQUIERE_DEFINICION
    )


def estado_autorizacion(
    orden: OrdenReparacion,
    detalle: ReparacionDetail,
) -> EstadoAutorizacion:
    """Estado de la autorizacion del cliente de ese Detalle."""
    if not requiere_autorizacion_cliente(orden):
        return EstadoAutorizacion.NO_REQUERIDA
    vigente = decision_vigente(detalle)
    if vigente is not None:
        return EstadoAutorizacion(vigente.resultado.value)
    if _espera_decision(detalle):
        return EstadoAutorizacion.PENDIENTE
    return EstadoAutorizacion.SIN_DECISION


def pendiente_de_autorizacion(
    orden: OrdenReparacion,
    detalle: ReparacionDetail,
) -> bool:
    """El Detalle espera la decision del cliente y no puede avanzar."""
    return estado_autorizacion(orden, detalle) is EstadoAutorizacion.PENDIENTE


def detalles_pendientes_de_autorizacion(
    orden: OrdenReparacion,
) -> frozenset[str]:
    """IDs de los Detalles de la Orden pendientes de autorizacion."""
    return frozenset(
        detalle.id
        for detalle in orden.reparaciones_detail
        if pendiente_de_autorizacion(orden, detalle)
    )


def situacion_de_la_orden(orden: OrdenReparacion) -> ResultadoEvaluacionOrden:
    """BR-REP-012 sobre la Orden, con la autorizacion ya derivada.

    Es la unica forma en que los services consultan el resolver: asi la
    condicion "pendiente de autorizacion" no se recalcula en cada caller.
    """
    return resolver_situacion_orden(
        orden.reparaciones_detail,
        pendientes_autorizacion=detalles_pendientes_de_autorizacion(orden),
    )


def es_trabajable(orden: OrdenReparacion, detalle: ReparacionDetail) -> bool:
    """DEFINIDO, SIN_BLOQUEO y, si el Origen la exige, autorizado.

    La misma definicion que usa el resolver (``_es_trabajable``), para la
    toma, la seleccion, la reserva y las acciones disponibles.
    """
    return (
        detalle.estado is EstadoReparacionDetail.DEFINIDO
        and detalle.condicion is CondicionReparacionDetail.SIN_BLOQUEO
        and not pendiente_de_autorizacion(orden, detalle)
    )


def exigir_autorizacion_vigente(
    orden: OrdenReparacion,
    detalle: ReparacionDetail,
) -> None:
    """Defensa del backend: sin autorizacion vigente no se ejecuta nada.

    La aplican la seleccion (PROC-REP-181) y la reserva (PROC-REP-185),
    aunque la UI no ofrezca la accion. Una decision sobre una definicion
    anterior no cuenta (BR-REP-029).
    """
    estado = estado_autorizacion(orden, detalle)
    if estado is EstadoAutorizacion.PENDIENTE:
        version = detalle.version_definicion
        anteriores = sorted(
            {
                registro.version_definicion
                for registro in detalle.autorizaciones
            }
        )
        detalle_anterior = (
            f" La decision registrada es de la definicion "
            f"v{anteriores[-1]}, anterior a la vigente."
            if anteriores
            else ""
        )
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle.id} no tiene la autorizacion del cliente "
            f"para su definicion vigente (v{version}): no se ejecuta ni "
            f"reserva insumos (BR-REP-028).{detalle_anterior}"
        )
    if estado is EstadoAutorizacion.RECHAZADO:
        raise PrecondicionInvalidaError(
            f"El cliente rechazo el Detalle {detalle.id}: no se ejecuta."
        )


def marcar_pendiente_autorizacion(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-129: la Orden espera la decision del cliente (V1.4).

    Analogo a PROC-REP-120 / 125. Solo desde PROC-REP-211 y solo si el
    resolver confirma ``PENDIENTE_AUTORIZACION`` (ningun Detalle
    trabajable y alguno pendiente). ACT-SYSTEM: no cambia el estado de
    workflow ni los Detalles; la espera termina cuando Recepcion registra
    la decision (PROC-REP-046/047).
    """
    if orden.current_process != "PROC-REP-211":
        raise PrecondicionInvalidaError(
            f"{NODO_ESPERA_AUTORIZACION} se alcanza desde PROC-REP-211; la "
            f"Orden esta en {orden.current_process}."
        )
    situacion = situacion_de_la_orden(orden)
    if situacion is not ResultadoEvaluacionOrden.PENDIENTE_AUTORIZACION:
        raise PrecondicionInvalidaError(
            f"La Orden no esta pendiente de autorizacion ({situacion.value})."
        )
    pendientes = sorted(detalles_pendientes_de_autorizacion(orden))
    return registrar_paso(
        orden,
        process_id=NODO_ESPERA_AUTORIZACION,
        accion="DETALLES_PENDIENTES_DE_AUTORIZACION",
        fecha=fecha,
        observacion=f"Pendientes: {', '.join(pendientes)}",
    )
