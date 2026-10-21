"""Tramo de cierre: control, notificacion, cobro y entrega.

    aprobar_control    PROC-REP-220 -> 230 -> 245 -> 240
    rechazar_control   PROC-REP-220 -> 230 (No) -> 235 -> 211 [-> 170]
    notificar          PROC-REP-250 -> 260 -> 265 [-> 266]
    registrar_pago_de_orden   (capacidad transversal) [-> 265 [-> 266]]
    registrar_checkin  verificacion de funciones basicas antes de entregar
                       (MVP v2, UAT-009): define la garantia por Detalle
    entregar           PROC-REP-280 -> 270 -> EVT-REP-999 (+ comprobante
                       final y garantia emitidos)

La condicion de entrega exige saldo exactamente cero (V1.4, BR-REP-038):
una deuda se cobra y un saldo a favor se devuelve
(``application.finanzas``) antes de entregar.

PROC-REP-265 se evalua exactamente dos veces en HP-REP-001: una al
notificar (resultado "No", hay saldo) y otra despues del pago (resultado
"Si"). ``entregar`` NO lo vuelve a evaluar: comprueba la condicion como
precondicion del comando y va derecho a PROC-REP-280.
"""

from decimal import Decimal

from app.domain.models import OrdenReparacion
from app.services import (
    PrecondicionInvalidaError,
    aprobar_control_tecnico,
    armar_entrega,
    calcular_puntaje,
    condicion_entrega_cumplida,
    control_tecnico_completo,
    devolver_equipo_rt,
    entregar_equipo,
    evaluar_situacion_orden,
    exigir_checkin_para_entrega,
    exigir_equipo_en_custodia,
    generar_comprobante_final,
    informar_resultado_rt,
    lista_para_cierre,
    marcar_reparacion_lista,
    notificar_cliente,
    rechazar_control_tecnico,
    registrar_checkin_de_entrega,
    registrar_pago,
    registrar_saldo_pendiente,
    validar_alguno_de,
    validar_condicion_entrega,
)
from app.services.ordenes import ROLES_ENTREGA
from app.services.pagos import motivo_de_entrega_bloqueada

from .contexto import ApplicationContext
from .documentos import emitir_documentos_de_salida
from .finanzas import reevaluar_tras_movimiento
from .modificacion import orden_para_modificar

CERO = Decimal("0")


def aprobar_control(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    detalle_id: str | None = None,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """Recepcion aprueba el control -de un Detalle o de la Orden entera.

    Siempre registra PROC-REP-220. Solo cuando, despues de esa
    aprobacion, TODOS los Detalles de la Orden quedan con control
    APROBADO -con Multi-Detalle eso puede requerir varias llamadas, una
    por Detalle- se encadena PROC-REP-230 ("Si"), PROC-REP-245
    (puntaje, BR-REP-009) y PROC-REP-240 (REPARACION_LISTA). Una
    aprobacion parcial NO registra ninguno de esos tres: la Orden sigue
    EN_REPARACION esperando el resto.

    ``OrdenReparacion.puntaje_total`` es un computed field que ya suma
    los Detalles con control APROBADO (Slice 0): una aprobacion parcial
    muestra su puntaje parcial igual, sin necesidad de registrar
    PROC-REP-245 por adelantado.

    No notifica: eso es otra accion humana y otro endpoint.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = aprobar_control_tecnico(
            orden,
            usuario=usuario,
            fecha=fecha,
            detalle_id=detalle_id,
            observaciones=observaciones,
        )

        # Los Detalles CANCELADO no se controlan: alcanza con que todos
        # los vigentes esten APROBADO.
        if control_tecnico_completo(orden):
            orden = calcular_puntaje(orden, fecha=fecha)
            orden = marcar_reparacion_lista(orden, fecha=fecha)

        contexto.ordenes.guardar(orden)
    return orden


def rechazar_control(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    detalle_id: str,
    motivo: str,
) -> OrdenReparacion:
    """Recepcion rechaza el control de UN Detalle (220 -> 230 No -> 235).

    El Detalle se reabre para retrabajo y el resolver (PROC-REP-211)
    decide que sigue: con la toma ya cerrada, la Orden vuelve a la cola
    (PROC-REP-170) para una Ejecucion nueva. No llega a REPARACION_LISTA
    hasta que el retrabajo se apruebe.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = rechazar_control_tecnico(
            orden,
            detalle_id=detalle_id,
            usuario=usuario,
            motivo=motivo,
            fecha=fecha,
        )
        orden, _ = evaluar_situacion_orden(orden, fecha=fecha)
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
    a que se registre el Pago. Con saldo a favor del cliente no hay 266:
    la entrega espera la devolucion de dinero.

    Devuelve tambien si la Orden ya puede entregarse.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = notificar_cliente(orden, usuario=usuario, fecha=fecha)
        orden, puede_entregar = validar_condicion_entrega(orden, fecha=fecha)
        # 266 solo por deuda real: no por un saldo a favor ni por el saldo
        # nominal de un Origen NO_COBRABLE (garantia).
        if not puede_entregar and orden.saldo > 0:
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
    referencia: str | None = None,
    operacion_id: str | None = None,
) -> tuple[OrdenReparacion, bool]:
    """Registra un Pago (FEAT-REP-007, BR-REP-017-A).

    Capacidad TRANSVERSAL: no corresponde a ningun ``PROC-REP-*`` y
    puede ocurrir en cualquier momento de la vida de la Orden. Por eso
    el rol se valida contra ``ROLES_PAGO`` (ADMINISTRADOR, RECEPCION y
    COORDINADOR_RMA); TECNICO no puede registrar Pagos.

    Si la Orden ya esta en Completar Cobro (current_process 265 o 266),
    el pago puede destrabar la entrega, asi que se revalida PROC-REP-265
    y, si todavia queda saldo, vuelve PROC-REP-266 (pago parcial). Si el
    cierre todavia no empezo (por ejemplo en PROC-REP-240), el Pago se
    registra igual y no se evalua nada: 265 pertenece a la fase de
    cierre (BR-REP-017-B) y evaluarlo antes seria inventar un paso que
    el proceso no da.

    NO genera el comprobante final: eso es PROC-REP-280 y ocurre en la
    entrega. El medio se valida contra el catalogo de medios de pago;
    ``operacion_id`` evita duplicar el Pago ante un reintento.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_pago(
            orden,
            monto=monto,
            metodo=metodo,
            usuario=usuario,
            fecha=fecha,
            medios=contexto.catalogos.listar_medios_pago(),
            referencia=referencia,
            operacion_id=operacion_id,
        )

        # PROC-REP-265 es de la fase SECUENCIAL de cierre: solo se
        # revalida si la Orden ya llego a ella (tras 250 -> 260 -> 265).
        # Un Pago anterior solo baja el saldo; el Pago es transversal y no
        # mueve el proceso.
        orden, puede_entregar = reevaluar_tras_movimiento(orden, fecha=fecha)

        contexto.ordenes.guardar(orden)
    return orden, puede_entregar


def registrar_checkin(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    realizado: bool,
) -> OrdenReparacion:
    """Recepcion (o Administracion) registra el check-in antes de entregar.

    Con la reparacion lista: si se pudieron verificar las funciones
    basicas del equipo. Reasigna la garantia de cada Detalle (90 o 30
    dias) sin pisar los ajustes manuales. No mueve el proceso ni toca la
    notificacion ni el cobro.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_checkin_de_entrega(
            orden, realizado=realizado, usuario=usuario, fecha=fecha
        )
        contexto.ordenes.guardar(orden)
    return orden


def entregar(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    recibido_por: str | None = None,
    identificacion_receptor: str | None = None,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """El Administrador entrega el equipo (280 -> 270 -> EVT-REP-999).

    La condicion de entrega se comprueba como PRECONDICION del comando,
    no volviendo a recorrer PROC-REP-265: ese nodo ya se evaluo en la
    notificacion y despues del pago. Reejecutarlo aqui agregaria al
    historial un paso que HP-REP-001 no da.

    El rol se valida antes de generar nada: ``entregar_equipo`` tambien
    lo valida, pero para entonces PROC-REP-280 ya habria emitido el
    comprobante final.

    Despues de la condicion comercial exige el check-in si hay trabajos
    con garantia (Cliente Externo), el equipo en custodia confirmada (el
    comprobante de recepcion no alcanza) y quien lo retira.
    La entrega queda registrada (``orden.entrega``) y, en la misma
    operacion, se emiten el comprobante final y la garantia, que empieza
    con esta entrega.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, ROLES_ENTREGA)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        if not lista_para_cierre(orden):
            raise PrecondicionInvalidaError(
                f"Solo se entrega una Orden con resultado "
                f"(REPARACION_LISTA o SIN_REPARACION); esta en "
                f"{orden.estado_workflow.value}."
            )
        if orden.current_process != "PROC-REP-265":
            raise PrecondicionInvalidaError(
                "Falta validar la condicion de entrega (PROC-REP-265) "
                "antes de entregar; la Orden esta en "
                f"{orden.current_process}."
            )
        if not condicion_entrega_cumplida(orden):
            raise PrecondicionInvalidaError(
                f"No se puede entregar: {motivo_de_entrega_bloqueada(orden)}. "
                "Resolve la cuenta (cobro o devolucion) y volve a intentarlo."
            )
        exigir_checkin_para_entrega(orden)
        exigir_equipo_en_custodia(orden, operacion="entregar el equipo")
        entrega = armar_entrega(
            orden,
            usuario=usuario,
            fecha=fecha,
            recibido_por=recibido_por,
            identificacion_receptor=identificacion_receptor,
            observaciones=observaciones,
        )

        orden = generar_comprobante_final(orden, fecha=fecha)
        orden = entregar_equipo(
            orden, usuario=usuario, fecha=fecha, entrega=entrega
        )
        orden = emitir_documentos_de_salida(
            contexto, orden, usuario_id=usuario.id, fecha=fecha
        )

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

    with orden_para_modificar(contexto, orden_id) as orden:
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

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = devolver_equipo_rt(orden, usuario=usuario, fecha=fecha)
        contexto.ordenes.guardar(orden)
    return orden
