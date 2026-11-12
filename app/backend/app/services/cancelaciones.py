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
compone la capa de aplicacion): con trabajo realizado, el cierre normal;
con todos CANCELADO, la Orden sigue ABIERTA sin trabajos vigentes
(PROC-REP-307).

DC31 (09/11/2026): cancelar la ORDEN es una accion explicita y TERMINAL
(PROC-REP-308, o 306 sin Detalles). Solo se permite sin Ejecucion activa,
sin toma, sin reservas por conciliar, sin deuda ni credito del cliente, con
la custodia resuelta (si el equipo ingreso, ya devuelto) y sin Detalles
COMPLETO; si algo falla no cambia nada. Cancela los Detalles pendientes,
fija CANCELADA y cierra la Orden (EVT-REP-999) en el mismo acto. Con la
Orden sin trabajos pendientes, la devolucion fisica se registra ANTES de
cancelar (``registrar_devolucion_equipo``). Una Orden CANCELADA y abierta
solo puede venir del circuito anterior a DC31: conserva ese circuito
(devolucion, custodia y dinero) hasta cerrarse.

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
    ReparacionDetail,
    RolUsuario,
    TipoEntrega,
    Usuario,
)

from .autorizacion import validar_alguno_de
from .custodia import (
    EstadoCustodia,
    custodia_por_definir,
    estado_custodia,
)
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .inventario import reservas_activas
from .ordenes import (
    ROLES_ENTREGA,
    equipo_bajo_custodia,
    verificar_fin_financiero,
)
from .pagos import es_cobrable
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
    exigir_rol: bool = True,
) -> None:
    """Precondiciones de PROC-REP-300, sin registrar nada.

    Las comparte el registro de la decision del cliente: valida todos los
    rechazos antes de cancelar el primero, para que una operacion mixta
    no quede a medias.
    """
    if exigir_rol:
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
    exigir_rol: bool = True,
) -> OrdenReparacion:
    """PROC-REP-300: cancela UN Detalle PENDIENTE (BR-REP-014).

    Solo un Detalle DEFINIDO (la representacion de PENDIENTE), sin
    Ejecucion activa ni reservas abiertas. No cancela los demas Detalles.
    Recalcular la Orden (PROC-REP-211) es del caller. ``origen`` dice si
    lo cancela la organizacion, el rechazo o el desistimiento del cliente.
    """
    validar_cancelacion_detalle(
        orden,
        detalle_id=detalle_id,
        usuario=usuario,
        motivo=motivo,
        exigir_rol=exigir_rol,
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


def desistimiento_pendiente(detalle: ReparacionDetail) -> bool:
    """DC07: el cliente pidio desistir y el Detalle todavia no se cancelo."""
    return (
        detalle.solicitud_desistimiento is not None
        and detalle.estado is not EstadoReparacionDetail.CANCELADO
    )


def resolver_desistimiento_solicitado(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-211 -> 300 (VAR-REP-042): cancelacion efectiva de un
    desistimiento ya solicitado, con la Ejecucion ya resuelta.

    Se registra aparte de la solicitud, con su propio usuario y fecha/hora
    (DC07): el de quien resolvio la Ejecucion. No exige el permiso de
    cancelacion: la decision la tomo el cliente y Recepcion ya la
    registro; aqui solo se aplica, con las mismas precondiciones de 300
    (sin Ejecucion activa ni reservas abiertas).
    """
    detalle = next(d for d in orden.reparaciones_detail if d.id == detalle_id)
    solicitud = detalle.solicitud_desistimiento
    if solicitud is None or not desistimiento_pendiente(detalle):
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} no tiene un desistimiento pendiente."
        )
    return cancelar_detalle(
        orden,
        detalle_id=detalle_id,
        usuario=usuario,
        # Quien y cuando lo pidio quedan en la solicitud; aca, el motivo.
        motivo=f"Desistimiento solicitado por el cliente: {solicitud.motivo}",
        fecha=fecha,
        origen=OrigenCancelacion.DESISTIMIENTO_CLIENTE,
        exigir_rol=False,
    )


def sin_trabajos_vigentes(orden: OrdenReparacion) -> bool:
    """DC31: la Orden sigue abierta pero no le queda trabajo (PROC-REP-307).

    Todos sus Detalles quedaron CANCELADO, o no tiene Detalles y el equipo
    ya se devolvio. No es un estado de workflow: se deriva. No habilita
    trabajo tecnico; solo resolver custodia, devolucion y dinero, y
    cancelar la Orden.
    """
    if orden.esta_cerrada or orden.estado_workflow is EstadoWorkflow.CANCELADA:
        return False
    if orden.reparaciones_detail:
        return all(
            detalle.estado is EstadoReparacionDetail.CANCELADO
            for detalle in orden.reparaciones_detail
        )
    return orden.devolucion is not None


def admite_devolucion_sin_reparar(orden: OrdenReparacion) -> bool:
    """DC31: la devolucion fisica se puede registrar con la Orden activa.

    Sin trabajos pendientes de ejecucion (todos los Detalles CANCELADO, o
    ninguno), con el equipo en el local, sin Ejecucion, toma ni reservas, y
    sin una devolucion previa. Corresponde finalizar sin reparar: no hay
    nada COMPLETO que entregar.

    Es la devolucion previa a cancelar: una Orden con resultado
    (``lista_para_cierre``: SIN_REPARACION por PROC-REP-069 o la reparacion
    lista) ya no se cancela (``exigir_orden_cancelable``) y devuelve el
    equipo en su propio cierre (notificar y entregar, o informar a Gestion
    RT y devolver), sin saltear esos pasos.
    """
    return (
        not orden.esta_cerrada
        and orden.estado_workflow is not EstadoWorkflow.CANCELADA
        and not lista_para_cierre(orden)
        and all(
            detalle.estado is EstadoReparacionDetail.CANCELADO
            for detalle in orden.reparaciones_detail
        )
        and orden.devolucion is None
        and equipo_bajo_custodia(orden)
        and not hay_ejecucion_activa(orden)
        and toma_activa(orden) is None
        and not reservas_activas(orden.movimientos_insumo)
    )


def _pendientes(orden: OrdenReparacion) -> list[str]:
    return [
        detalle.id
        for detalle in orden.reparaciones_detail
        if detalle.estado is EstadoReparacionDetail.DEFINIDO
    ]


def impedimentos_cancelacion(orden: OrdenReparacion) -> list[str]:
    """DC31: por que la Orden todavia no se puede cancelar (vacio: se puede).

    Evalua todas las condiciones a la vez, para decirlas juntas. El saldo
    se mide como quedaria la Orden con sus trabajos pendientes cancelados.
    """
    motivos: list[str] = []
    if hay_ejecucion_activa(orden):
        motivos.append(
            "hay una Ejecucion activa: primero hay que interrumpirla o "
            "completarla"
        )
    toma = toma_activa(orden)
    if toma is not None:
        motivos.append(
            f"la Orden esta tomada por {toma.usuario_id}: primero tiene que "
            "liberarse"
        )
    if reservas_activas(orden.movimientos_insumo):
        motivos.append("hay reservas de insumos sin conciliar")
    if any(
        detalle.estado is EstadoReparacionDetail.COMPLETO
        for detalle in orden.reparaciones_detail
    ):
        motivos.append(
            "hay trabajos COMPLETOS: siguen el cierre normal (control, cobro "
            "y entrega)"
        )
    pendientes = _pendientes(orden)
    if custodia_por_definir(orden):
        motivos.append(
            "falta definir la custodia del equipo: confirmar la recepcion o "
            "registrar que nunca ingreso"
        )
    elif estado_custodia(orden) is EstadoCustodia.EN_CUSTODIA:
        motivos.append(
            "el equipo esta en el local: "
            + (
                "cancela los trabajos pendientes, registra la devolucion "
                "del equipo y despues cancela la Orden"
                if pendientes
                else "registra su devolucion antes de cancelar"
            )
        )
    simulada = orden.model_copy(deep=True)
    for detalle in simulada.reparaciones_detail:
        if detalle.id in pendientes:
            detalle.estado = EstadoReparacionDetail.CANCELADO
    if es_cobrable(simulada) and simulada.saldo != 0:
        if simulada.saldo > 0:
            motivos.append(f"el cliente adeuda {simulada.saldo}")
        else:
            motivos.append(
                f"hay {simulada.credito_a_favor} a favor del cliente: "
                "registra la devolucion del dinero antes de cancelar"
            )
    return motivos


def cancelar_trabajos_pendientes(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
    origen: OrigenCancelacion = OrigenCancelacion.INTERNA,
    origenes: Mapping[str, OrigenCancelacion] | None = None,
) -> OrdenReparacion:
    """PROC-REP-305: cancela los Detalles PENDIENTE; NO cancela la Orden.

    Es la cascada de "Rechaza todos los trabajos" y del desistimiento total
    (DC31): lo COMPLETO y lo ya CANCELADO quedan como estan, nunca con una
    Ejecucion activa ni con reservas por conciliar. El caller invoca el
    resolver (PROC-REP-211): con trabajo realizado sigue el cierre normal y
    con todo CANCELADO la Orden queda abierta sin trabajos vigentes
    (PROC-REP-307). Cancelar la Orden es ``cancelar_orden``.
    """
    validar_alguno_de(usuario, ROLES_CANCELACION)
    motivo = _motivo_obligatorio(motivo, "Cancelar los trabajos pendientes")
    exigir_orden_cancelable(orden)
    if hay_ejecucion_activa(orden):
        raise PrecondicionInvalidaError(
            "La Orden tiene una Ejecucion activa: primero hay que "
            "interrumpirla o completarla (PROC-REP-200) para conciliar sus "
            "insumos. No se cancelo nada."
        )
    pendientes = _pendientes(orden)
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
        accion="CANCELAR_TRABAJOS_PENDIENTES",
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
    nueva_orden.updated_at = fecha
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
    """Cancelar la Orden (DC31): explicita, terminal y atomica.

    PROC-REP-308 con Detalles, PROC-REP-306 sin Detalles. Exige que
    ``impedimentos_cancelacion`` este vacio; si no, rechaza con todos los
    motivos y no cambia nada. Cancela los Detalles pendientes (DEFINIDO ->
    CANCELADO, conservando lo ya CANCELADO y todo el historial), registra
    usuario, fecha y motivo, fija CANCELADA y cierra la Orden en el mismo
    acto (PROC-REP-268 -> EVT-REP-999). ``origen`` queda en cada Detalle
    cancelado, salvo los que ``origenes`` indique por Detalle.
    """
    validar_alguno_de(usuario, ROLES_CANCELACION)
    motivo = _motivo_obligatorio(motivo, "Cancelar la Orden")
    exigir_orden_cancelable(orden)
    motivos = impedimentos_cancelacion(orden)
    if motivos:
        raise PrecondicionInvalidaError(
            f"No se puede cancelar la Orden {orden.id}: "
            + "; ".join(motivos)
            + ". No se cancelo nada."
        )
    pendientes = _pendientes(orden)
    for detalle_id in pendientes:
        _sin_reservas_activas(orden, detalle_id)
    if orden.reparaciones_detail:
        observacion = f"Motivo: {motivo}"
        if pendientes:
            observacion += f". Detalles cancelados: {', '.join(pendientes)}"
        nueva_orden = registrar_paso(
            orden,
            process_id="PROC-REP-308",
            accion="CANCELAR_ORDEN",
            fecha=fecha,
            usuario_id=usuario.id,
            observacion=observacion,
        )
    else:
        nueva_orden = registrar_paso(
            orden,
            process_id="PROC-REP-306",
            accion="CANCELAR_ORDEN_SIN_DETALLES",
            fecha=fecha,
            usuario_id=usuario.id,
            observacion=f"Motivo: {motivo}",
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
    nueva_orden.estado_workflow = EstadoWorkflow.CANCELADA
    nueva_orden.updated_at = fecha
    cerrada = verificar_fin_financiero(nueva_orden, fecha=fecha)
    if not cerrada.esta_cerrada:  # defensa: las precondiciones lo aseguran
        raise PrecondicionInvalidaError(
            f"La Orden {orden.id} no pudo cerrarse al cancelarla. No se "
            "cancelo nada."
        )
    return cerrada


def registrar_devolucion_equipo(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    recibido_por: str,
    fecha: datetime,
    observaciones: str | None = None,
    identificacion_receptor: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-270: devolucion fisica del equipo sin reparar.

    DC31: se registra con la Orden ACTIVA y sin trabajos pendientes
    (``admite_devolucion_sin_reparar``), antes de cancelarla; la Orden no se
    cierra ni cambia de estado. En una Orden CANCELADA y abierta (circuito
    anterior a DC31) sigue como antes: despues verifica el saldo y cierra.

    Mismos actores que la entrega (``ROLES_ENTREGA``). No es una entrega
    comercial: no pasa por notificacion, cobro ni comprobante final, no
    emite garantia y la Orden sigue CANCELADA -nunca ENTREGADA-. Registra
    quien entrega, quien recibe y cuando; despues pasa por la verificacion
    financiera (PROC-REP-268): sin saldo a favor del cliente el proceso
    termina (EVT-REP-999) y la Orden queda cerrada; con saldo a favor sigue
    abierta hasta devolver el dinero. No se registra una segunda
    devolucion. Exige la custodia confirmada: sin recepcion confirmada no
    hay equipo que devolver.
    """
    validar_alguno_de(usuario, ROLES_ENTREGA)

    heredada = orden.estado_workflow is EstadoWorkflow.CANCELADA
    if orden.esta_cerrada:
        raise PrecondicionInvalidaError(
            f"La Orden {orden.id} esta cerrada: no admite cambios."
        )
    if not heredada and lista_para_cierre(orden):
        raise PrecondicionInvalidaError(
            f"La Orden {orden.id} ya tiene un resultado: el equipo se "
            "devuelve en su cierre (notificar y entregar, o informar a "
            "Gestion RT y devolver), no con la devolucion previa a cancelar."
        )
    if not heredada and any(
        detalle.estado is not EstadoReparacionDetail.CANCELADO
        for detalle in orden.reparaciones_detail
    ):
        raise PrecondicionInvalidaError(
            "La devolucion sin reparar se registra cuando la Orden no tiene "
            "trabajos pendientes ni completos: primero cancela los trabajos "
            "pendientes."
        )
    if not equipo_bajo_custodia(orden):
        raise PrecondicionInvalidaError(
            f"El equipo de la Orden {orden.id} no esta en custodia "
            "confirmada: no hay nada que devolver."
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
    if identificacion_receptor and identificacion_receptor.strip():
        observacion += f" ({identificacion_receptor.strip()})"
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
        tipo=TipoEntrega.DEVOLUCION_SIN_REPARACION,
        entregado_por=usuario.id,
        recibido_por=recibido_por.strip(),
        identificacion_receptor=(identificacion_receptor or "").strip()
        or None,
        fecha=fecha,
        observaciones=(observaciones or "").strip() or None,
    )
    if not heredada:
        # DC31: la Orden sigue abierta sin trabajos vigentes (270 -> 307);
        # la cancelacion explicita la cierra.
        return nueva_orden
    # Circuito anterior (PROC-REP-270 -> 268): con un anticipo sin devolver,
    # la Orden sigue abierta hasta la devolucion de dinero.
    return verificar_fin_financiero(nueva_orden, fecha=fecha)
