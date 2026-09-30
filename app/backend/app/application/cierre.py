"""Tramo de cierre: control, notificacion, cobro y entrega.

    aprobar_control    PROC-REP-220 -> 230 -> 245 -> 240
    notificar          PROC-REP-250 -> 260 -> 265 [-> 266]
    registrar_pago_de_orden   (capacidad transversal) [-> 265]
    entregar           PROC-REP-280 -> 270 -> EVT-REP-999

PROC-REP-265 se evalua exactamente dos veces en HP-REP-001: una al
notificar (resultado "No", hay saldo) y otra despues del pago (resultado
"Si"). ``entregar`` NO lo vuelve a evaluar: comprueba la condicion como
precondicion del comando y va derecho a PROC-REP-280.
"""

from decimal import Decimal

from app.domain.models import EstadoWorkflow, OrdenReparacion
from app.services import (
    PrecondicionInvalidaError,
    aprobar_control_tecnico,
    calcular_puntaje,
    devolver_equipo_rt,
    entregar_equipo,
    generar_comprobante_final,
    informar_resultado_rt,
    marcar_reparacion_lista,
    notificar_cliente,
    registrar_pago,
    registrar_saldo_pendiente,
    validar_alguno_de,
    validar_condicion_entrega,
)
from app.services.ordenes import ROLES_ENTREGA

from .contexto import ApplicationContext

CERO = Decimal("0")


def aprobar_control(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """Recepcion aprueba el control y la Orden queda lista.

    Encadena PROC-REP-220 -> 230 (aprobacion, BR-REP-008),
    PROC-REP-245 (puntaje, BR-REP-009) y PROC-REP-240 (ACT-SYSTEM).
    No notifica: eso es otra accion humana y otro endpoint.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    orden = aprobar_control_tecnico(
        orden, usuario=usuario, fecha=fecha, observaciones=observaciones
    )
    orden = calcular_puntaje(orden, fecha=fecha)
    orden = marcar_reparacion_lista(orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden


def notificar(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
) -> tuple[OrdenReparacion, bool]:
    """Recepcion avisa al cliente y se evalua la condicion de entrega.

    PROC-REP-250 -> 260 (aviso) y PROC-REP-265 (condicion). Si queda
    saldo, PROC-REP-266 deja constancia del bloqueo y la entrega espera
    a que se registre el Pago.

    Devuelve tambien si la Orden ya puede entregarse.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    orden = notificar_cliente(orden, usuario=usuario, fecha=fecha)
    orden, puede_entregar = validar_condicion_entrega(orden, fecha=fecha)
    if not puede_entregar:
        orden = registrar_saldo_pendiente(orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden, puede_entregar


def registrar_pago_de_orden(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    monto: Decimal,
    metodo: str,
) -> tuple[OrdenReparacion, bool]:
    """Registra un Pago (FEAT-REP-007, BR-REP-017-A).

    Capacidad TRANSVERSAL: no corresponde a ningun ``PROC-REP-*`` y
    puede ocurrir en cualquier momento de la vida de la Orden. Por eso
    no se exige ningun rol -BR-REP-017 no lo define todavia-, solo que
    el usuario este activo.

    Si la Orden ya esta REPARACION_LISTA, el pago puede destrabar la
    entrega, asi que se revalida PROC-REP-265. Si todavia no lo esta, el
    Pago se registra igual y no se evalua nada: 265 pertenece a la fase
    de cierre (BR-REP-017-B) y evaluarlo antes seria inventar un paso
    que el proceso no da.

    NO genera el comprobante final: eso es PROC-REP-280 y ocurre en la
    entrega.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    orden = registrar_pago(
        orden, monto=monto, metodo=metodo, usuario=usuario, fecha=fecha
    )

    puede_entregar = False
    if orden.estado_workflow is EstadoWorkflow.REPARACION_LISTA:
        orden, puede_entregar = validar_condicion_entrega(orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden, puede_entregar


def entregar(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
) -> OrdenReparacion:
    """El Administrador entrega el equipo (280 -> 270 -> EVT-REP-999).

    La condicion de entrega se comprueba como PRECONDICION del comando,
    no volviendo a recorrer PROC-REP-265: ese nodo ya se evaluo en la
    notificacion y despues del pago. Reejecutarlo aqui agregaria al
    historial un paso que HP-REP-001 no da.

    El rol se valida antes de generar nada: ``entregar_equipo`` tambien
    lo valida, pero para entonces PROC-REP-280 ya habria emitido el
    comprobante final.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, ROLES_ENTREGA)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)

    if orden.estado_workflow is not EstadoWorkflow.REPARACION_LISTA:
        raise PrecondicionInvalidaError(
            f"Solo se entrega una Orden REPARACION_LISTA; esta en "
            f"{orden.estado_workflow.value}."
        )
    if orden.saldo > CERO:
        raise PrecondicionInvalidaError(
            f"No se puede entregar con saldo pendiente: {orden.saldo}. "
            "Registra el Pago y volve a intentarlo."
        )

    orden = generar_comprobante_final(orden, fecha=fecha)
    orden = entregar_equipo(orden, usuario=usuario, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden


def informar_rt(
    contexto: ApplicationContext,
    *,
    orden_id: str,
) -> OrdenReparacion:
    """Se informa el resultado a Gestion RT (PROC-REP-250 -> 290).

    Exclusivo de RT_INTERNO (HP-REP-002): no pasa por notificar, cobrar
    ni entregar a un cliente. PROC-REP-290 es ``actor: ACT-SYSTEM`` en el
    Business Process V1.3 -no una accion humana con rol pendiente de
    definir-, asi que este comando no recibe ``usuario_id``: no hay
    ningun actor que autorizar.
    """
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    orden = informar_resultado_rt(orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden


def devolver_rt(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
) -> OrdenReparacion:
    """Devuelve el equipo a Gestion RT (PROC-REP-270 reutilizado).

    Compone lo mismo que ``entregar`` en el nodo, pero sin la condicion
    comercial: RT_INTERNO no pasa por PROC-REP-265/266/280 (HP-REP-002).
    El rol lo valida ``devolver_equipo_rt``, como el resto de los
    comandos de este modulo.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    orden = devolver_equipo_rt(orden, usuario=usuario, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden
