"""Espera de recursos (EXC-REP-001): PROC-REP-120.

Tambien el override de recursos (EXC-REP-002, BR-REP-003): una capacidad
TRANSVERSAL por Detalle (``autorizar_override_recursos``), disponible para
cualquier Detalle bloqueado por recursos -con la Orden detenida en
PROC-REP-100 o con factibilidad parcial-. Solo en el circuito de
PROC-REP-100 la Orden continua 110 "Si" -> 130 -> 140
(``continuar_por_override``). El override solo REGISTRA la autorizacion: no
reserva ni descuenta stock (eso es PROC-REP-185 / 210). Su fuente de verdad
es el historial (``tiene_override_factibilidad``).

Dos caminos llevan a PROC-REP-120 (V1.3): desde el ingreso
(100 -> 110 "No" -> 120) y, directo, desde PROC-REP-211 con resultado
``PENDIENTE_RECURSOS`` (sin 100 ni 110). Ambos usan
``marcar_pendiente_recursos``.

Cuando ningun Detalle es trabajable (PROC-REP-090 "Ninguno trabajable") la
Orden queda detenida en PROC-REP-100. Sin override se decide no forzar y la
Orden pasa a PROC-REP-120 esperando una revalidacion que dispare de nuevo
PROC-REP-080.

``PENDIENTE_RECURSOS`` NO es un ``EstadoWorkflow``: es el agregado derivado
por ``resolver_situacion_orden`` a partir de la condicion de los Detalles.
Aqui solo se verifica; nunca se persiste.
"""

from datetime import datetime

from app.domain.models import (
    CondicionReparacionDetail,
    EstadoReparacionDetail,
    OrdenReparacion,
    RolUsuario,
    Usuario,
)

from .autorizacion import validar_actor
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .resolucion import ResultadoEvaluacionOrden, resolver_situacion_orden
from .workflow import registrar_accion_funcional, registrar_paso

NODO_ADVERTENCIA = "PROC-REP-100"
NODO_ESPERA = "PROC-REP-120"
NODO_OVERRIDE = "PROC-REP-130"
NODO_REDEFINICION = "PROC-REP-127"
# Capacidad transversal de autorizacion de override (BR-REP-003): ID real
# de la trazabilidad, como ACC-REP-020 para Registrar Pago.
ACCION_AUTORIZAR_OVERRIDE = "ACC-REP-049"
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


def tiene_override_factibilidad(
    orden: OrdenReparacion,
    detalle_id: str,
) -> bool:
    """True si el Detalle tiene un override de factibilidad VIGENTE.

    Se deriva del historial -sin flag en el Detalle-: existe una
    autorizacion de override (``ACCION_AUTORIZAR_OVERRIDE``) registrada
    para ESE Detalle DESPUES de su ultimo PROC-REP-127 (BR-REP-003,
    vigencia): una redefinicion invalida las autorizaciones anteriores,
    aunque se confirme el mismo Tipo. Es el unico lugar donde se busca;
    lo consultan la factibilidad (no lo rebloquea), la reserva real
    (PROC-REP-185) y el consumo (PROC-REP-210). Un override jamas alcanza
    a otro Detalle, y el 127 de otro Detalle no lo invalida.
    """
    vigente = False
    for paso in orden.historial:
        if paso.reparacion_detail_id != detalle_id:
            continue
        if (
            paso.es_accion_funcional
            and paso.referencia_id == ACCION_AUTORIZAR_OVERRIDE
        ):
            vigente = True
        elif paso.process_id == NODO_REDEFINICION:
            vigente = False
    return vigente


def autorizar_override_recursos(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
) -> OrdenReparacion:
    """Capacidad transversal: autorizar UN Detalle bloqueado por recursos.

    BR-REP-003: un Coordinador RMA autoriza un Detalle PENDIENTE (DEFINIDO)
    con condicion BLOQUEADO_POR_RECURSOS y deja usuario, fecha, Detalle,
    validacion ignorada y motivo. Es la UNICA forma de registrar un
    override, cualquiera sea el momento: con la Orden detenida en
    PROC-REP-100 o con factibilidad parcial (otros Detalles trabajables,
    Orden habilitada, en cola, tomada o en reparacion).

    Igual que Registrar Pago, es una accion funcional: queda en el
    historial sin mover ``current_process`` ni el estado de workflow, sin
    tocar tomas ni Ejecuciones. El Detalle pasa a SIN_BLOQUEO; los demas
    siguen como estaban. No reserva ni toca el stock (eso es
    PROC-REP-185 / 210). Continuar el circuito de PROC-REP-100 es
    ``continuar_por_override``.
    """
    validar_actor(usuario, RolUsuario.COORDINADOR_RMA)

    detalle = next(
        (d for d in orden.reparaciones_detail if d.id == detalle_id), None
    )
    if detalle is None:
        raise EntidadNoEncontradaError(
            f"La Orden {orden.id} no tiene el Detalle {detalle_id}."
        )
    if (
        detalle.estado is not EstadoReparacionDetail.DEFINIDO
        or detalle.condicion
        is not CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    ):
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} no esta bloqueado por recursos "
            f"({detalle.estado.value} / {detalle.condicion.value})."
        )
    if not motivo.strip():
        raise PrecondicionInvalidaError(
            "El override exige un motivo (BR-REP-003)."
        )

    nueva_orden = registrar_accion_funcional(
        orden,
        accion_id=ACCION_AUTORIZAR_OVERRIDE,
        accion="AUTORIZAR_OVERRIDE_RECURSOS",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=(
            "Validacion ignorada: factibilidad por recursos "
            f"(PROC-REP-080/090). Motivo: {motivo.strip()}"
        ),
    )
    for d in nueva_orden.reparaciones_detail:
        if d.id == detalle_id:
            d.condicion = CondicionReparacionDetail.SIN_BLOQUEO
    return nueva_orden


def continuar_por_override(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-110 ("Si") -> PROC-REP-130 en el circuito de PROC-REP-100.

    Solo con la Orden detenida en PROC-REP-100 ("ningun Detalle
    trabajable") y con una autorizacion vigente de ESE Detalle: la
    decision 110 resulta "Si" y 130 registra que la Orden continua hacia
    la habilitacion (140, ``habilitar_orden``). La autorizacion en si ya
    quedo registrada por ``autorizar_override_recursos``.
    """
    validar_actor(usuario, RolUsuario.COORDINADOR_RMA)

    if orden.current_process != NODO_ADVERTENCIA:
        raise PrecondicionInvalidaError(
            f"El circuito de override continua desde {NODO_ADVERTENCIA}; "
            f"la Orden esta en {orden.current_process}."
        )
    if not tiene_override_factibilidad(orden, detalle_id):
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} no tiene una autorizacion de override "
            "vigente (BR-REP-003)."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-110",
        accion="FORZAR_DETALLE_BLOQUEADO",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion="Si",
    )
    return registrar_paso(
        nueva_orden,
        process_id=NODO_OVERRIDE,
        accion="REGISTRAR_OVERRIDE",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=(
            f"Continua por el override autorizado del Detalle {detalle_id} "
            "(BR-REP-003)"
        ),
    )


def override_listo_para_habilitar(orden: OrdenReparacion) -> bool:
    """La Orden viene de PROC-REP-130 con un override valido.

    ``current_process`` es PROC-REP-130, el PROC-REP-130 vigente es el
    ultimo paso y su Detalle existe, sigue DEFINIDO y quedo SIN_BLOQUEO.
    No se fabrica ningun PROC-REP-090 "Si".
    """
    if orden.current_process != NODO_OVERRIDE:
        return False
    ultimo = next(
        (
            p
            for p in reversed(orden.historial)
            if p.process_id == NODO_OVERRIDE
        ),
        None,
    )
    if ultimo is None or ultimo.reparacion_detail_id is None:
        return False
    return any(
        d.id == ultimo.reparacion_detail_id
        and d.estado is EstadoReparacionDetail.DEFINIDO
        and d.condicion is CondicionReparacionDetail.SIN_BLOQUEO
        for d in orden.reparaciones_detail
    )


def exigir_espera_por_recursos(orden: OrdenReparacion) -> None:
    """La revalidacion solo se dispara desde PROC-REP-120."""
    if orden.current_process != NODO_ESPERA:
        raise PrecondicionInvalidaError(
            f"Solo se revalida una Orden en {NODO_ESPERA}; esta en "
            f"{orden.current_process}."
        )
