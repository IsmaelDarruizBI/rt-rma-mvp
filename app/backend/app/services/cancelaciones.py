"""Cancelacion de Detalles y de la Orden, y devolucion del equipo.

Nodos cubiertos: PROC-REP-300 (cancelar Detalle), PROC-REP-305 (cancelar
Orden / trabajos pendientes), PROC-REP-306 (cancelar una Orden sin
Detalles, V1.4) y PROC-REP-270 en su contexto de devolucion fisica de un
equipo de una Orden CANCELADA (V1.4). Regla: BR-REP-014.

Cancelar NUNCA borra: un Detalle CANCELADO conserva Tipo, precio
snapshot, Ejecuciones, movimientos e historial, y registra quien, cuando y
por que. Lo ya realizado (COMPLETO) no se cancela, y con una Ejecucion
activa no se cancela nada: primero se interrumpe o completa
(PROC-REP-200), lo que concilia sus insumos (PROC-REP-210). Que sigue
despues de cancelar Detalles lo decide el resolver (PROC-REP-211, lo
compone la capa de aplicacion): CANCELADA si todos quedan CANCELADO, o el
cierre normal si queda trabajo realizado.

Una Orden CANCELADA no es una Orden ENTREGADA. Si el equipo esta en
custodia, su devolucion fisica se registra con
``registrar_devolucion_equipo`` -sin cobro, comprobante final ni garantia-.
El proceso termina (EVT-REP-999) cuando el equipo ya no esta pendiente de
devolucion Y no queda dinero a favor del cliente: la devolucion de DINERO
de un anticipo (V1.4 PROC-REP-267/268, ``services.pagos``) puede
registrarse antes o despues de la fisica.

QUIEN puede cancelar no esta definido por negocio (V1.3 omite el actor de
300/305): el MVP lo restringe a Recepcion y Coordinacion RMA
(``ROLES_CANCELACION``), a confirmar.

El rechazo del cliente y su desistimiento posterior (PROC-REP-047,
``services.decision_cliente``) cancelan con estas mismas funciones y las
mismas protecciones: lo unico que cambia es el ``origen`` que queda en
``RegistroCancelacion`` (``RECHAZO_CLIENTE`` o ``DESISTIMIENTO_CLIENTE`` en
vez de ``INTERNA``).
"""

from collections.abc import Mapping
from datetime import datetime

from app.domain.models import (
    DevolucionEquipo,
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    OrigenCancelacion,
    RegistroCancelacion,
    RolUsuario,
    Usuario,
)

from .autorizacion import validar_alguno_de
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .inventario import reservas_activas
from .ordenes import (
    ROLES_ENTREGA,
    equipo_bajo_custodia,
    marcar_orden_cancelada,
    verificar_fin_financiero,
)
from .revisiones import finalizada_sin_reparacion, lista_para_cierre
from .tomas import hay_ejecucion_activa, toma_activa
from .workflow import registrar_paso

# Pendiente de definicion de negocio (V1.3/V1.4 no declaran actor).
ROLES_CANCELACION = (
    RolUsuario.RECEPCION,
    RolUsuario.COORDINADOR_RMA,
)


def _motivo_obligatorio(motivo: str, que: str) -> str:
    if not motivo.strip():
        raise PrecondicionInvalidaError(f"{que} exige un motivo (BR-REP-014).")
    return motivo.strip()


def exigir_orden_cancelable(orden: OrdenReparacion) -> None:
    """La Orden todavia tiene un proceso que cancelar."""
    if orden.estado_workflow is EstadoWorkflow.CANCELADA:
        raise PrecondicionInvalidaError(
            f"La Orden {orden.id} ya esta CANCELADA."
        )
    if finalizada_sin_reparacion(orden):
        raise PrecondicionInvalidaError(
            f"La Orden {orden.id} ya finalizo SIN_REPARACION: sigue el "
            "cierre (notificar y entregar el equipo)."
        )
    if lista_para_cierre(orden):
        raise PrecondicionInvalidaError(
            f"La Orden {orden.id} ya tiene la reparacion lista: no quedan "
            "trabajos pendientes que cancelar."
        )


def tiene_ejecucion_activa(orden: OrdenReparacion, detalle_id: str) -> bool:
    """El Detalle esta EN_PROGRESO o tiene una Ejecucion en curso."""
    detalle = next(
        (d for d in orden.reparaciones_detail if d.id == detalle_id), None
    )
    return (
        detalle is not None
        and detalle.estado is EstadoReparacionDetail.EN_PROGRESO
    ) or any(
        ejecucion.reparacion_detail_id == detalle_id
        and ejecucion.estado is EstadoEjecucion.EN_PROGRESO
        for ejecucion in orden.ejecuciones
    )


def tiene_reservas_sin_conciliar(
    orden: OrdenReparacion,
    detalle_id: str,
) -> bool:
    """El Detalle conserva reservas de insumos sin conciliar (PROC-REP-210)."""
    return any(
        reserva.reparacion_detail_id == detalle_id
        for reserva in reservas_activas(orden.movimientos_insumo)
    )


def _sin_reservas_activas(orden: OrdenReparacion, detalle_id: str) -> None:
    """Defensa: un Detalle nunca termina CANCELADO con reservas abiertas."""
    if tiene_reservas_sin_conciliar(orden, detalle_id):
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} tiene reservas de insumos sin "
            "conciliar: no se cancela."
        )


def _cancelar(
    orden: OrdenReparacion,
    detalle_id: str,
    *,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
    origen: OrigenCancelacion,
) -> None:
    """Pasa el Detalle a CANCELADO, sobre una Orden que ya es copia."""
    detalle = next(d for d in orden.reparaciones_detail if d.id == detalle_id)
    detalle.estado = EstadoReparacionDetail.CANCELADO
    detalle.cancelacion = RegistroCancelacion(
        usuario_id=usuario.id, fecha=fecha, motivo=motivo, origen=origen
    )


def validar_cancelacion_detalle(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    motivo: str,
) -> None:
    """Precondiciones de PROC-REP-300, sin registrar nada.

    Las comparte el registro de la decision del cliente: valida todos los
    rechazos antes de cancelar el primero, para que una operacion mixta
    no quede a medias.
    """
    validar_alguno_de(usuario, ROLES_CANCELACION)
    _motivo_obligatorio(motivo, "Cancelar un Detalle")
    exigir_orden_cancelable(orden)

    detalle = next(
        (d for d in orden.reparaciones_detail if d.id == detalle_id), None
    )
    if detalle is None:
        raise EntidadNoEncontradaError(
            f"La Orden {orden.id} no tiene el Detalle {detalle_id}."
        )
    if detalle.estado is EstadoReparacionDetail.CANCELADO:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} ya esta CANCELADO."
        )
    if detalle.estado is EstadoReparacionDetail.COMPLETO:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} esta COMPLETO: el trabajo realizado no "
            "se cancela."
        )
    if tiene_ejecucion_activa(orden, detalle_id):
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} tiene una Ejecucion activa: primero "
            "hay que interrumpirla o completarla (PROC-REP-200), para "
            "conciliar sus insumos, y recien despues se puede cancelar."
        )
    _sin_reservas_activas(orden, detalle_id)


def cancelar_detalle(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
    origen: OrigenCancelacion = OrigenCancelacion.INTERNA,
) -> OrdenReparacion:
    """PROC-REP-300: cancela UN Detalle PENDIENTE (BR-REP-014).

    Solo un Detalle DEFINIDO (la representacion de PENDIENTE), sin
    Ejecucion activa ni reservas abiertas. No cancela los demas Detalles.
    Recalcular la Orden (PROC-REP-211) es del caller. ``origen`` dice si
    lo cancela la organizacion, el rechazo o el desistimiento del cliente.
    """
    validar_cancelacion_detalle(
        orden, detalle_id=detalle_id, usuario=usuario, motivo=motivo
    )
    motivo = motivo.strip()

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-300",
        accion="CANCELAR_DETALLE",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=f"Motivo: {motivo}",
    )
    _cancelar(
        nueva_orden,
        detalle_id,
        usuario=usuario,
        motivo=motivo,
        fecha=fecha,
        origen=origen,
    )
    return nueva_orden


def cancelar_orden(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
    origen: OrigenCancelacion = OrigenCancelacion.INTERNA,
    origenes: Mapping[str, OrigenCancelacion] | None = None,
) -> OrdenReparacion:
    """PROC-REP-305 (con Detalles) o PROC-REP-306 (sin Detalles).

    Nunca con una Ejecucion activa: no se cancela nada y las reservas
    quedan como estaban hasta conciliarse.

    Con Detalles cancela todos los PENDIENTE y deja COMPLETO lo realizado;
    NO fija CANCELADA: el caller invoca el resolver (PROC-REP-211), que
    decide entre CANCELADA y el cierre normal. Sin Detalles es una
    transicion EXPLICITA a CANCELADA (V1.4 PROC-REP-306: no se infiere con
    el resolver sobre una coleccion vacia), con la custodia resuelta por
    ``marcar_orden_cancelada``. ``origen`` queda en cada Detalle cancelado,
    salvo los que ``origenes`` indique por Detalle (el desistimiento total
    del cliente mezcla rechazos de pendientes y desistimientos).
    """
    validar_alguno_de(usuario, ROLES_CANCELACION)
    motivo = _motivo_obligatorio(motivo, "Cancelar la Orden")
    exigir_orden_cancelable(orden)

    activa = next(
        (
            ejecucion
            for ejecucion in orden.ejecuciones
            if ejecucion.estado is EstadoEjecucion.EN_PROGRESO
        ),
        None,
    )
    if activa is not None:
        raise PrecondicionInvalidaError(
            f"La Orden tiene una Ejecucion activa ({activa.id}, Detalle "
            f"{activa.reparacion_detail_id}): primero hay que interrumpirla "
            "o completarla (PROC-REP-200) para conciliar sus insumos. No se "
            "cancelo nada."
        )

    if not orden.reparaciones_detail:
        nueva_orden = registrar_paso(
            orden,
            process_id="PROC-REP-306",
            accion="CANCELAR_ORDEN_SIN_DETALLES",
            fecha=fecha,
            usuario_id=usuario.id,
            observacion=f"Motivo: {motivo}",
        )
        return marcar_orden_cancelada(nueva_orden, fecha=fecha)

    pendientes = [
        detalle.id
        for detalle in orden.reparaciones_detail
        if detalle.estado is EstadoReparacionDetail.DEFINIDO
    ]
    if not pendientes:
        raise PrecondicionInvalidaError(
            "No hay trabajos pendientes que cancelar: los Detalles ya "
            "estan COMPLETO o CANCELADO."
        )
    for detalle_id in pendientes:
        _sin_reservas_activas(orden, detalle_id)

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-305",
        accion="CANCELAR_ORDEN",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=(
            f"Motivo: {motivo}. Detalles cancelados: {', '.join(pendientes)}"
        ),
    )
    for detalle_id in pendientes:
        _cancelar(
            nueva_orden,
            detalle_id,
            usuario=usuario,
            motivo=motivo,
            fecha=fecha,
            origen=(origenes or {}).get(detalle_id, origen),
        )
    return nueva_orden


def registrar_devolucion_equipo(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    recibido_por: str,
    fecha: datetime,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-270 (V1.4): devolucion fisica del equipo, Orden CANCELADA.

    Mismos actores que la entrega (``ROLES_ENTREGA``). No es una entrega
    comercial: no pasa por notificacion, cobro ni comprobante final, no
    emite garantia y la Orden sigue CANCELADA -nunca ENTREGADA-. Registra
    quien entrega, quien recibe y cuando; despues pasa por la verificacion
    financiera (PROC-REP-268): sin saldo a favor del cliente el proceso
    termina (EVT-REP-999) y la Orden queda cerrada; con saldo a favor sigue
    abierta hasta devolver el dinero. No se registra una segunda
    devolucion.
    """
    validar_alguno_de(usuario, ROLES_ENTREGA)

    if orden.estado_workflow is not EstadoWorkflow.CANCELADA:
        raise PrecondicionInvalidaError(
            "La devolucion sin reparar es de una Orden CANCELADA; esta "
            f"Orden esta {orden.estado_workflow.value}."
        )
    if not equipo_bajo_custodia(orden):
        raise PrecondicionInvalidaError(
            f"El equipo de la Orden {orden.id} no quedo en custodia: no hay "
            "nada que devolver."
        )
    if orden.devolucion is not None:
        raise PrecondicionInvalidaError(
            f"La devolucion del equipo ya se registro el "
            f"{orden.devolucion.fecha:%Y-%m-%d %H:%M}: no se registra dos "
            "veces."
        )
    if hay_ejecucion_activa(orden) or toma_activa(orden) is not None:
        raise PrecondicionInvalidaError(
            "No se devuelve el equipo con trabajo tecnico abierto."
        )
    if reservas_activas(orden.movimientos_insumo):
        raise PrecondicionInvalidaError(
            "No se devuelve el equipo con reservas de insumos activas."
        )
    if not recibido_por.strip():
        raise PrecondicionInvalidaError(
            "La devolucion exige indicar quien recibe el equipo."
        )

    observacion = f"Recibido por: {recibido_por.strip()}"
    if observaciones and observaciones.strip():
        observacion += f". Observaciones: {observaciones.strip()}"

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-270",
        accion="DEVOLVER_EQUIPO_SIN_REPARAR",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=observacion,
    )
    nueva_orden.devolucion = DevolucionEquipo(
        entregado_por=usuario.id,
        recibido_por=recibido_por.strip(),
        fecha=fecha,
        observaciones=(observaciones or "").strip() or None,
    )
    # V1.4 PROC-REP-270 -> 268: con un anticipo sin devolver, la Orden sigue
    # abierta hasta la devolucion de dinero.
    return verificar_fin_financiero(nueva_orden, fecha=fecha)
