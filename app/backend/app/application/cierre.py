"""Tramo de cierre: control, aviso, cobro y entrega.

    aprobar_control    PROC-REP-220 -> 230 -> 245 -> 240
    rechazar_control   PROC-REP-220 -> 230 (No) -> 235 -> 211 [-> 170]
    notificar          PROC-REP-250 -> 260 -> 265 [-> 266] (opcional)
    registrar_pago_de_orden   (capacidad transversal) [-> 265 [-> 266]]
    registrar_checkin  verificacion de funciones basicas antes de entregar
                       (MVP v2, UAT-009): define la garantia por Detalle;
                       tambien se registra dentro de la entrega
    entregar           [250 ->] [269 ->] [265 ->] 280 -> 270 -> EVT-REP-999
                       (+ Comprobante de entrega y garantia)

La condicion de entrega exige saldo exactamente cero (V1.4, BR-REP-038):
una deuda se cobra y un saldo a favor se devuelve
(``application.finanzas``) antes de entregar.

DEC-AJ-03 (23/11/2026): avisar al cliente (PROC-REP-260) es opcional. Con
aviso, PROC-REP-265 se evalua al avisar y despues de cada Pago, como en
HP-REP-001, y ``entregar`` no lo repite. Sin aviso, ``entregar`` registra
250 y evalua 265 en la misma operacion, antes de PROC-REP-280.

DEC-AJ-04 (23/11/2026): el check-in que falta se registra en la misma
confirmacion de la entrega (269, y se revalida 265) y se emite un solo
documento, el Comprobante de entrega y garantia.
"""

from decimal import Decimal

from app.domain.models import OrdenReparacion
from app.services import (
    DatosRetiro,
    aprobar_control_tecnico,
    aviso_registrable,
    calcular_puntaje,
    control_tecnico_completo,
    devolver_equipo_rt,
    entregar_al_cliente,
    evaluar_situacion_orden,
    informar_resultado_rt,
    marcar_reparacion_lista,
    notificar_cliente,
    rechazar_control_tecnico,
    registrar_aviso_listo,
    registrar_checkin_de_entrega,
    registrar_pago,
    registrar_saldo_pendiente,
    validar_condicion_entrega,
)

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


def _evaluar_tras_aviso(
    orden: OrdenReparacion,
    *,
    fecha,
) -> tuple[OrdenReparacion, bool]:
    """Despues del aviso (260) se evalua la condicion de entrega (265).

    Si queda saldo, PROC-REP-266 deja constancia del bloqueo y la entrega
    espera a que se registre el Pago. Con saldo a favor del cliente no hay
    266: la entrega espera la devolucion de dinero.
    """
    orden, puede_entregar = validar_condicion_entrega(orden, fecha=fecha)
    # 266 solo por deuda real: no por un saldo a favor ni por el saldo
    # nominal de un Origen NO_COBRABLE (garantia).
    if not puede_entregar and orden.saldo > 0:
        orden = registrar_saldo_pendiente(orden, fecha=fecha)
    return orden, puede_entregar


def registrar_aviso_por_comunicacion(
    orden: OrdenReparacion,
    *,
    usuario_id: str,
    fecha,
    comunicacion_id: str,
) -> OrdenReparacion:
    """DEC-AJ-03: un WhatsApp de equipo listo confirmado como enviado es el
    aviso al cliente. Registra PROC-REP-260 una sola vez, con la Orden lista
    para retirar y sin entregar; si ya hubo aviso, no agrega otro.

    El permiso ya lo valido la confirmacion del envio (COMUNICACION_ENVIAR).
    """
    if not aviso_registrable(orden):
        return orden
    orden = registrar_aviso_listo(
        orden,
        usuario_id=usuario_id,
        fecha=fecha,
        observacion=f"WhatsApp {comunicacion_id}",
    )
    orden, _ = _evaluar_tras_aviso(orden, fecha=fecha)
    return orden


def notificar(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
) -> tuple[OrdenReparacion, bool]:
    """Recepcion avisa al cliente y se evalua la condicion de entrega.

    PROC-REP-250 -> 260 (aviso) y PROC-REP-265 (condicion), con 266 si
    queda deuda. DEC-AJ-03: el aviso es opcional; la entrega no lo exige.

    Devuelve tambien si la Orden ya puede entregarse.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = notificar_cliente(orden, usuario=usuario, fecha=fecha)
        orden, puede_entregar = _evaluar_tras_aviso(orden, fecha=fecha)
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
    motivo: str | None = None,
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
            orden,
            realizado=realizado,
            usuario=usuario,
            fecha=fecha,
            motivo=motivo,
        )
        contexto.ordenes.guardar(orden)
    return orden


def entregar(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    retiro: DatosRetiro,
    checkin: bool | None = None,
    checkin_motivo: str | None = None,
) -> OrdenReparacion:
    """Recepcion o Administracion entregan el equipo al cliente.

    Una sola confirmacion (DEC-AJ-04): ``entregar_al_cliente`` controla una
    vez el rol, el resultado, la cuenta (saldo exactamente 0), la custodia
    confirmada, el trabajo abierto, quien retira y el check-in, registra el
    check-in que falte (269) y la condicion de entrega si todavia no se
    evaluo (DEC-AJ-03: sin aviso, 250 y 265), y despues 280 y 270. En la
    misma transaccion se emite el Comprobante de entrega y garantia, con la
    garantia que empieza con esta entrega. Si algo falla no se guarda nada.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = entregar_al_cliente(
            orden,
            usuario=usuario,
            fecha=fecha,
            retiro=retiro,
            checkin=checkin,
            checkin_motivo=checkin_motivo,
            zona_horaria=contexto.zona_horaria,
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
