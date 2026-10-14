"""Cobro y devolucion de dinero: pagos, anulaciones, devoluciones y cierre.

Nodos cubiertos: PROC-REP-265 (validar condicion de entrega) y
PROC-REP-266 (saldo pendiente); de V1.4, la devolucion de dinero
(PROC-REP-267) como capacidad transversal y el criterio de PROC-REP-268
(ninguna Orden termina con saldo a favor sin devolver, ver
``services.ordenes.verificar_fin_financiero``). Reglas: BR-REP-017 y
BR-REP-038. Feature: FEAT-REP-007.

BR-REP-017 distingue dos cosas que no deben confundirse:

- Registrar Pago es TRANSVERSAL: puede ocurrir en cualquier momento de
  la vida de la Orden y no tiene nodo propio en el proceso.
- Completar Cobro es SECUENCIAL: es la fase de cierre modelada en
  PROC-REP-265/266.

Movimientos (append-only, nada se borra ni se reescribe):

    Pago        dinero recibido (ANTICIPO, PARCIAL o FINAL)
    Anulacion   correccion administrativa de un Pago mal registrado
    Devolucion  dinero efectivamente devuelto al cliente, desde un Pago

Saldo = Total - Pagado valido + Devuelto (``OrdenReparacion.saldo``).
Positivo: el cliente debe; cero: cuenta saldada; negativo: credito a favor
del cliente, que se resuelve devolviendo dinero -nunca con un pago
negativo-.

Los IDs de accion de la anulacion y de la devolucion (ACC-REP-021/022)
son del MVP, como ACC-REP-020 y ACC-REP-049: la SoT todavia no los asigna.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    MEDIOS_PAGO_PREDETERMINADOS,
    AnulacionPago,
    DevolucionDinero,
    EstadoWorkflow,
    MedioPago,
    OrdenReparacion,
    Pago,
    RolUsuario,
    TipoPago,
    Usuario,
)
from app.domain.politicas import CondicionComercial, politica_de

from .autorizacion import validar_alguno_de
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .identificadores import nuevo_id
from .revisiones import finalizada_sin_reparacion, lista_para_cierre
from .workflow import registrar_accion_funcional, registrar_paso

# Capacidad transversal de FEAT-REP-007 / BR-REP-017-A. Tiene ID de
# trazabilidad propio pero NO un PROC-REP-*: no es un nodo del proceso.
ACCION_REGISTRAR_PAGO = "ACC-REP-020"
# Correccion administrativa de un Pago (MVP, sin ID en la SoT).
ACCION_ANULAR_PAGO = "ACC-REP-021"
# Devolucion de dinero (MVP; equivale a V1.4 PROC-REP-267, aqui como
# capacidad transversal para no mover ``current_process``).
ACCION_DEVOLVER_DINERO = "ACC-REP-022"

# BR-REP-017: "usuario ACTIVO AND rol != TECNICO -> puede registrar
# Pago". Fuente unica de los roles autorizados para Registrar Pago: la
# consume tanto ``registrar_pago`` (autorizacion en backend) como
# ``app.application.acciones`` (lo que se publica en
# ``AccionDisponible.roles``). Un Tecnico nunca puede registrar un Pago.
ROLES_PAGO = (
    RolUsuario.ADMINISTRADOR,
    RolUsuario.RECEPCION,
    RolUsuario.COORDINADOR_RMA,
)
# Corregir un Pago mal registrado es administrativo.
ROLES_ANULACION_PAGO = (RolUsuario.ADMINISTRADOR,)
# V1.4 deja pendiente quien devuelve dinero: el MVP sigue los permisos
# financieros existentes de cobro en mostrador, a confirmar por negocio.
ROLES_DEVOLUCION_DINERO = (
    RolUsuario.ADMINISTRADOR,
    RolUsuario.RECEPCION,
)

_CENTAVO = Decimal("0.01")
CERO = Decimal("0")


# --- Situacion financiera ----------------------------------------------------


def es_cobrable(orden: OrdenReparacion) -> bool:
    """El Origen tiene circuito comercial con el cliente (BR-REP-016)."""
    return (
        politica_de(orden.origen).condicion_comercial
        == CondicionComercial.COBRABLE
    )


def credito_pendiente(orden: OrdenReparacion) -> Decimal:
    """Dinero a favor del cliente que todavia hay que devolver."""
    return orden.credito_a_favor if es_cobrable(orden) else CERO


def cierre_financiero_resuelto(orden: OrdenReparacion) -> bool:
    """No queda ninguna obligacion de dinero abierta (BR-REP-038).

    Sin circuito comercial no hay nada que resolver. Con circuito
    comercial, el saldo tiene que ser exactamente cero: ni deuda del
    cliente ni credito a su favor sin devolver.
    """
    return not es_cobrable(orden) or orden.saldo == 0


def _sin_total_definido(orden: OrdenReparacion) -> bool:
    """Todavia no hay Detalles ni resultado: el total aun no se conoce."""
    return (
        not orden.reparaciones_detail
        and not lista_para_cierre(orden)
        and not finalizada_sin_reparacion(orden)
    )


def admite_pago(orden: OrdenReparacion) -> bool:
    """Se puede registrar un cobro ordinario o un anticipo ahora.

    Origen cobrable, Orden abierta y no CANCELADA, y saldo pendiente de
    cobro. Excepcion: una seña antes de definir los Detalles, cuando el
    total todavia no se conoce (si despues no se realiza nada, queda como
    credito a devolver).
    """
    return (
        es_cobrable(orden)
        and not orden.esta_cerrada
        and orden.estado_workflow is not EstadoWorkflow.CANCELADA
        and (orden.saldo > 0 or _sin_total_definido(orden))
    )


# --- Validaciones comunes ----------------------------------------------------


def validar_importe(monto: Decimal, que: str) -> Decimal:
    """Importe positivo, finito y con a lo sumo dos decimales.

    Se valida sobre ``Decimal`` (nunca ``float``) y no se redondea: un
    importe con mas precision se rechaza en vez de alterarse.
    """
    if not monto.is_finite() or monto <= 0:
        raise PrecondicionInvalidaError(
            f"El importe {que} debe ser mayor a cero: {monto}."
        )
    if monto != monto.quantize(_CENTAVO):
        raise PrecondicionInvalidaError(
            f"El importe {que} admite como maximo dos decimales: {monto}."
        )
    return monto


def _medio_valido(
    medio_id: str,
    medios: Sequence[MedioPago] | None,
    *,
    para_devolucion: bool = False,
) -> MedioPago:
    catalogo = MEDIOS_PAGO_PREDETERMINADOS if medios is None else medios
    medio = next((m for m in catalogo if m.id == medio_id), None)
    if medio is None:
        disponibles = ", ".join(m.id for m in catalogo if m.activo)
        raise PrecondicionInvalidaError(
            f"El medio de pago {medio_id!r} no existe en el catalogo "
            f"(disponibles: {disponibles})."
        )
    if not medio.activo:
        raise PrecondicionInvalidaError(
            f"El medio de pago {medio.id} no esta activo."
        )
    if para_devolucion and not medio.admite_devolucion:
        raise PrecondicionInvalidaError(
            f"El medio {medio.id} no admite devoluciones de dinero."
        )
    return medio


def _texto(valor: str | None) -> str | None:
    return (valor or "").strip() or None


def _motivo_obligatorio(motivo: str, que: str) -> str:
    if not motivo.strip():
        raise PrecondicionInvalidaError(f"{que} exige un motivo.")
    return motivo.strip()


def _exigir_abierta(orden: OrdenReparacion) -> None:
    # Defensa para invocaciones directas: los comandos ya cargan la Orden
    # con ``orden_para_modificar`` (E1).
    if orden.esta_cerrada:
        raise PrecondicionInvalidaError(
            f"La Orden {orden.id} esta cerrada: no admite movimientos de "
            "dinero."
        )


def _exigir_cobrable(orden: OrdenReparacion, que: str) -> None:
    if not es_cobrable(orden):
        raise PrecondicionInvalidaError(
            f"No se puede {que} en una Orden {orden.origen.value}: su "
            "condicion comercial no es COBRABLE."
        )


def _buscar_pago(orden: OrdenReparacion, pago_id: str) -> Pago:
    pago = next((p for p in orden.resumen_pago.pagos if p.id == pago_id), None)
    if pago is None:
        raise EntidadNoEncontradaError(
            f"La Orden {orden.id} no tiene el Pago {pago_id}."
        )
    return pago


# --- Pagos -------------------------------------------------------------------


def descripcion_de_pago(pago: Pago) -> str:
    """Resumen legible del Pago para el historial de la Orden.

    Deja recuperables el tipo, el medio y el importe sin que el lector
    -o el frontend- tenga que ir a buscar el Pago por su ID.
    """
    descripcion = f"{pago.tipo_pago.value} · {pago.metodo} · ${pago.monto}"
    if pago.referencia:
        descripcion += f" · ref. {pago.referencia}"
    return descripcion


def tipo_de_pago_para(
    orden: OrdenReparacion,
    monto: Decimal | None = None,
) -> TipoPago:
    """Deriva el tipo de Pago del estado de la Orden.

        sin resultado todavia (antes de REPARACION_LISTA) -> ANTICIPO
        con resultado, sin saldar la cuenta              -> PARCIAL
        con resultado, saldando la cuenta                -> FINAL

    "Con resultado" es REPARACION_LISTA o SIN_REPARACION
    (``lista_para_cierre``). Sin ``monto`` se asume que salda la cuenta.
    """
    if not lista_para_cierre(orden):
        return TipoPago.ANTICIPO
    if monto is not None and monto < orden.saldo:
        return TipoPago.PARCIAL
    return TipoPago.FINAL


def _exigir_operacion_nueva(
    orden: OrdenReparacion,
    *,
    operacion_id: str | None,
    referencia: str | None,
) -> None:
    """Un reintento no duplica un Pago (BR-REP-038: no se computa dos veces).

    ``operacion_id`` identifica el envio (cualquier Pago, aun anulado);
    ``referencia`` identifica la operacion real (transferencia, cupon)
    entre los Pagos vigentes.
    """
    for pago in orden.resumen_pago.pagos:
        if operacion_id and pago.operacion_id == operacion_id:
            raise PrecondicionInvalidaError(
                f"Esa operacion ya se registro como el Pago {pago.id}: no se "
                "duplica."
            )
        if (
            referencia
            and pago.vigente
            and (pago.referencia or "").casefold() == referencia.casefold()
        ):
            raise PrecondicionInvalidaError(
                f"Ya hay un Pago vigente con la referencia "
                f"{pago.referencia!r} ({pago.id}): no se registra dos veces."
            )


def registrar_pago(
    orden: OrdenReparacion,
    *,
    monto: Decimal,
    metodo: str,
    usuario: Usuario,
    fecha: datetime,
    medios: Sequence[MedioPago] | None = None,
    referencia: str | None = None,
    operacion_id: str | None = None,
    pago_id: str | None = None,
) -> OrdenReparacion:
    """Registra un Pago (BR-REP-017-A, FEAT-REP-007).

    Capacidad transversal: NO corresponde a ningun PROC-REP-*, asi que
    NO toca ``current_process`` -la Orden sigue parada donde estaba-.
    Si deja traza en el historial, como accion funcional ``ACC-REP-020``
    enlazada al Pago que la origino.

    Validaciones: rol de ``ROLES_PAGO`` (nunca un Tecnico), Origen
    ``COBRABLE``, Orden abierta y no CANCELADA, importe positivo con a lo
    sumo dos decimales, medio del catalogo (``medios``; sin catalogo, los
    predeterminados), sin duplicar la operacion y sin superar el saldo
    pendiente: con saldo cero o a favor no hay cobro posible. Unica
    excepcion al tope: una seña antes de definir los Detalles, cuando el
    total todavia no se conoce.

    El ``tipo_pago`` NO lo elige el usuario: ``tipo_de_pago_para``.
    """
    validar_alguno_de(usuario, ROLES_PAGO)
    _exigir_cobrable(orden, "registrar un Pago")
    if orden.estado_workflow is EstadoWorkflow.CANCELADA:
        # BR-REP-014: cancelar no genera un cobro; lo pagado se devuelve.
        raise PrecondicionInvalidaError(
            f"La Orden {orden.id} esta CANCELADA: no se registran pagos."
        )
    _exigir_abierta(orden)
    validar_importe(monto, "del pago")
    medio = _medio_valido(metodo, medios)
    referencia = _texto(referencia)
    _exigir_operacion_nueva(
        orden, operacion_id=operacion_id, referencia=referencia
    )
    if not _sin_total_definido(orden):
        if orden.saldo <= 0:
            situacion = (
                "con saldo a favor del cliente corresponde devolverlo"
                if orden.saldo < 0
                else "la cuenta esta saldada"
            )
            raise PrecondicionInvalidaError(
                f"No hay saldo pendiente de cobro ({orden.saldo}): "
                f"{situacion}."
            )
        if monto > orden.saldo:
            raise PrecondicionInvalidaError(
                f"El pago de {monto} supera el saldo pendiente "
                f"({orden.saldo}): no se cobra de mas."
            )

    pago = Pago(
        id=pago_id or nuevo_id("PAG"),
        monto=monto,
        tipo_pago=tipo_de_pago_para(orden, monto),
        metodo=medio.id,
        usuario_id=usuario.id,
        fecha=fecha,
        referencia=referencia,
        operacion_id=operacion_id,
    )

    nueva_orden = registrar_accion_funcional(
        orden,
        accion_id=ACCION_REGISTRAR_PAGO,
        accion="REGISTRAR_PAGO",
        fecha=fecha,
        usuario_id=usuario.id,
        pago_id=pago.id,
        observacion=descripcion_de_pago(pago),
    )
    nueva_orden.resumen_pago.pagos.append(pago)
    return nueva_orden


# --- Anulacion ---------------------------------------------------------------


def anulable(orden: OrdenReparacion, pago: Pago) -> bool:
    """El Pago puede anularse: vigente y sin devoluciones asociadas."""
    return (
        pago.vigente
        and orden.resumen_pago.devuelto_de(pago.id) == 0
        and not orden.esta_cerrada
    )


def anular_pago(
    orden: OrdenReparacion,
    *,
    pago_id: str,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
) -> OrdenReparacion:
    """Anula un Pago registrado por error (correccion administrativa).

    Solo un Administrador, con motivo. El Pago se conserva con su importe
    original y la anulacion (quien, cuando, por que); deja de contar como
    pagado. No se anula dos veces, ni un Pago del que ya se devolvio dinero
    (la devolucion fue una salida real: se corrige con otro movimiento, no
    borrando el origen), ni en una Orden cerrada.

    No es una devolucion: no registra ninguna salida de dinero.
    """
    validar_alguno_de(usuario, ROLES_ANULACION_PAGO)
    motivo = _motivo_obligatorio(motivo, "Anular un Pago")
    _exigir_abierta(orden)
    pago = _buscar_pago(orden, pago_id)
    if not pago.vigente:
        raise PrecondicionInvalidaError(
            f"El Pago {pago.id} ya fue anulado por "
            f"{pago.anulacion.usuario_id} el "
            f"{pago.anulacion.fecha:%Y-%m-%d %H:%M}: no se anula dos veces."
        )
    devuelto = orden.resumen_pago.devuelto_de(pago.id)
    if devuelto > 0:
        raise PrecondicionInvalidaError(
            f"Del Pago {pago.id} ya se devolvieron {devuelto}: no se anula "
            "un Pago con devoluciones registradas."
        )

    nueva_orden = registrar_accion_funcional(
        orden,
        accion_id=ACCION_ANULAR_PAGO,
        accion="ANULAR_PAGO",
        fecha=fecha,
        usuario_id=usuario.id,
        pago_id=pago.id,
        observacion=f"Anula {descripcion_de_pago(pago)}. Motivo: {motivo}",
    )
    _buscar_pago(nueva_orden, pago.id).anulacion = AnulacionPago(
        usuario_id=usuario.id, fecha=fecha, motivo=motivo
    )
    return nueva_orden


# --- Devolucion de dinero ----------------------------------------------------


def devolvible_de(orden: OrdenReparacion, pago: Pago) -> Decimal:
    """Lo que todavia puede devolverse desde ESE Pago."""
    if not pago.vigente:
        return CERO
    return pago.monto - orden.resumen_pago.devuelto_de(pago.id)


def _exigir_devolucion_nueva(
    orden: OrdenReparacion,
    *,
    operacion_id: str | None,
    referencia: str | None,
) -> None:
    for devolucion in orden.resumen_pago.devoluciones:
        if operacion_id and devolucion.operacion_id == operacion_id:
            raise PrecondicionInvalidaError(
                f"Esa operacion ya se registro como la devolucion "
                f"{devolucion.id}: no se duplica."
            )
        if referencia and (
            (devolucion.referencia or "").casefold() == referencia.casefold()
        ):
            raise PrecondicionInvalidaError(
                f"Ya hay una devolucion con la referencia "
                f"{devolucion.referencia!r} ({devolucion.id}): no se registra "
                "dos veces."
            )


def registrar_devolucion_dinero(
    orden: OrdenReparacion,
    *,
    pago_id: str,
    monto: Decimal,
    medio: str,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
    medios: Sequence[MedioPago] | None = None,
    referencia: str | None = None,
    operacion_id: str | None = None,
    devolucion_id: str | None = None,
) -> OrdenReparacion:
    """Devuelve dinero al cliente desde un Pago (V1.4 PROC-REP-267).

    BR-REP-038: solo con saldo a favor del cliente (Saldo < 0) y sin
    superarlo; desde un Pago vigente y sin superar lo que queda por
    devolver de ese Pago. Importe positivo, medio del catalogo que admita
    devoluciones, motivo obligatorio y sin duplicar la operacion. Roles:
    ``ROLES_DEVOLUCION_DINERO`` (a confirmar por negocio).

    Es un movimiento propio, no un Pago negativo: los Pagos no cambian y el
    saldo sube por ``Devuelto``. Capacidad transversal (accion
    ``ACC-REP-022``): no mueve ``current_process``; que sigue (revalidar la
    entrega o cerrar una Orden CANCELADA) lo compone la aplicacion. No toca
    el inventario.
    """
    validar_alguno_de(usuario, ROLES_DEVOLUCION_DINERO)
    _exigir_cobrable(orden, "devolver dinero")
    _exigir_abierta(orden)
    motivo = _motivo_obligatorio(motivo, "Devolver dinero")
    validar_importe(monto, "de la devolucion")
    medio_devolucion = _medio_valido(medio, medios, para_devolucion=True)
    referencia = _texto(referencia)
    _exigir_devolucion_nueva(
        orden, operacion_id=operacion_id, referencia=referencia
    )
    pago = _buscar_pago(orden, pago_id)
    if not pago.vigente:
        raise PrecondicionInvalidaError(
            f"El Pago {pago.id} esta anulado: no hubo dinero que devolver."
        )
    credito = credito_pendiente(orden)
    if credito <= 0:
        raise PrecondicionInvalidaError(
            f"La Orden no tiene saldo a favor del cliente (saldo "
            f"{orden.saldo}): no hay dinero que devolver."
        )
    if monto > credito:
        raise PrecondicionInvalidaError(
            f"La devolucion de {monto} supera el saldo a favor pendiente "
            f"({credito})."
        )
    disponible = devolvible_de(orden, pago)
    if monto > disponible:
        raise PrecondicionInvalidaError(
            f"La devolucion de {monto} supera lo que queda por devolver del "
            f"Pago {pago.id} ({disponible})."
        )

    devolucion = DevolucionDinero(
        id=devolucion_id or nuevo_id("DEV"),
        pago_id=pago.id,
        monto=monto,
        medio=medio_devolucion.id,
        usuario_id=usuario.id,
        fecha=fecha,
        motivo=motivo,
        referencia=referencia,
        operacion_id=operacion_id,
    )
    observacion = (
        f"Devuelve ${monto} · {medio_devolucion.id} · desde {pago.id}"
        f"{f' · ref. {referencia}' if referencia else ''}. Motivo: {motivo}"
    )
    nueva_orden = registrar_accion_funcional(
        orden,
        accion_id=ACCION_DEVOLVER_DINERO,
        accion="REGISTRAR_DEVOLUCION_DINERO",
        fecha=fecha,
        usuario_id=usuario.id,
        pago_id=pago.id,
        observacion=observacion,
    )
    nueva_orden.resumen_pago.devoluciones.append(devolucion)
    return nueva_orden


# --- Condicion de entrega (PROC-REP-265/266) ---------------------------------


def condicion_entrega_cumplida(orden: OrdenReparacion) -> bool:
    """La condicion comercial para entregar al cliente (BR-REP-017-B/038).

    Sale de la ``PoliticaOrigen``, no de un Origen hardcodeado:

        sin entrega a cliente -> no aplica (True)
        COBRABLE              -> saldo == 0 (ni deuda ni credito a favor)
        NO_COBRABLE           -> True, sin pagos (garantia)

    V1.4: un saldo a favor tampoco permite entregar; primero se devuelve
    el dinero. La cortesia queda fuera de alcance. El saldo nominal de una
    Orden NO_COBRABLE puede ser > 0 sin que eso sea una deuda.
    """
    politica = politica_de(orden.origen)
    if not politica.requiere_entrega_cliente:
        return True
    if politica.condicion_comercial == CondicionComercial.COBRABLE:
        return orden.saldo == 0
    return politica.condicion_comercial == CondicionComercial.NO_COBRABLE


def motivo_de_entrega_bloqueada(orden: OrdenReparacion) -> str:
    """Por que la condicion comercial no permite entregar todavia."""
    if orden.saldo > 0:
        return f"saldo pendiente de cobro: {orden.saldo}"
    return (
        f"saldo a favor del cliente: {orden.credito_a_favor} pendiente de "
        "devolver"
    )


def validar_condicion_entrega(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> tuple[OrdenReparacion, bool]:
    """PROC-REP-265: determina si la Orden puede entregarse (BR-REP-017-B).

    V1.4 (BR-REP-038), tres resultados para un Origen COBRABLE: saldo 0 ->
    se entrega; saldo > 0 -> cobro pendiente (PROC-REP-266); saldo < 0 ->
    saldo a favor del cliente, que primero se devuelve. Para NO_COBRABLE
    (garantia RMA) se aprueba directamente por Origen, sin pagos. La
    cortesia total queda fuera del MVP.

    Se evalua antes de generar el comprobante final (PROC-REP-280), para
    que el comprobante refleje siempre el saldo definitivo.
    """
    if not lista_para_cierre(orden):
        raise PrecondicionInvalidaError(
            f"La condicion de entrega se evalua sobre una Orden con "
            f"resultado (REPARACION_LISTA o SIN_REPARACION); esta en "
            f"{orden.estado_workflow.value}."
        )
    politica = politica_de(orden.origen)
    if not politica.requiere_entrega_cliente:
        raise PrecondicionInvalidaError(
            f"{orden.origen.value} no tiene entrega a cliente: no recorre "
            f"PROC-REP-265."
        )

    puede_entregar = condicion_entrega_cumplida(orden)

    if politica.condicion_comercial == CondicionComercial.NO_COBRABLE:
        observacion = "NO_COBRABLE_POR_ORIGEN"
    elif orden.saldo < 0:
        observacion = f"Saldo {orden.saldo}: a favor del cliente"
    else:
        observacion = f"Saldo {orden.saldo}"

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-265",
        accion="VALIDAR_CONDICION_ENTREGA",
        fecha=fecha,
        observacion=observacion,
    )
    return nueva_orden, puede_entregar


def registrar_saldo_pendiente(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-266: la entrega queda bloqueada por saldo pendiente.

    Solo deja constancia del bloqueo en el workflow: no agrega ningun
    estado de Orden. Se destraba registrando uno o mas Pagos por la via
    transversal de siempre y revalidando PROC-REP-265. Un saldo a favor
    del cliente NO pasa por aqui (V1.4): se resuelve devolviendo dinero.
    """
    if orden.saldo <= 0:
        raise PrecondicionInvalidaError(
            "No hay saldo pendiente que bloquee la entrega."
        )

    return registrar_paso(
        orden,
        process_id="PROC-REP-266",
        accion="SALDO_PENDIENTE_ENTREGA_BLOQUEADA",
        fecha=fecha,
        observacion=f"Saldo {orden.saldo}",
    )
