"""Cobro de la Orden: pagos y condicion de entrega.

Nodos cubiertos: PROC-REP-265 (validar condicion de entrega) y
PROC-REP-266 (saldo pendiente). Regla: BR-REP-017. Feature: FEAT-REP-007.

BR-REP-017 distingue dos cosas que no deben confundirse:

- Registrar Pago es TRANSVERSAL: puede ocurrir en cualquier momento de
  la vida de la Orden y no tiene nodo propio en el proceso.
- Completar Cobro es SECUENCIAL: es la fase de cierre modelada en
  PROC-REP-265/266.
"""

from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    EstadoWorkflow,
    OrdenReparacion,
    Pago,
    RolUsuario,
    TipoPago,
    Usuario,
)
from app.domain.politicas import CondicionComercial, politica_de

from .autorizacion import validar_alguno_de
from .exceptions import PrecondicionInvalidaError
from .identificadores import nuevo_id
from .workflow import registrar_accion_funcional, registrar_paso

# Capacidad transversal de FEAT-REP-007 / BR-REP-017-A. Tiene ID de
# trazabilidad propio pero NO un PROC-REP-*: no es un nodo del proceso.
ACCION_REGISTRAR_PAGO = "ACC-REP-020"

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


def condicion_entrega_cumplida(orden: OrdenReparacion) -> bool:
    """La condicion comercial para entregar al cliente (BR-REP-017-B).

    Sale de la ``PoliticaOrigen``, no de un Origen hardcodeado:

        sin entrega a cliente -> no aplica (True)
        COBRABLE              -> saldo <= 0
        NO_COBRABLE           -> True, sin pagos (garantia)

    La cortesia queda fuera de alcance. El saldo nominal de una Orden
    NO_COBRABLE puede ser > 0 sin que eso sea una deuda.
    """
    politica = politica_de(orden.origen)
    if not politica.requiere_entrega_cliente:
        return True
    if politica.condicion_comercial == CondicionComercial.COBRABLE:
        return orden.saldo <= 0
    return politica.condicion_comercial == CondicionComercial.NO_COBRABLE


def descripcion_de_pago(pago: Pago) -> str:
    """Resumen legible del Pago para el historial de la Orden.

    Deja recuperables el tipo, el medio y el importe sin que el lector
    -o el frontend- tenga que ir a buscar el Pago por su ID.
    """
    return f"{pago.tipo_pago.value} · {pago.metodo} · ${pago.monto}"


def tipo_de_pago_para(orden: OrdenReparacion) -> TipoPago:
    """Deriva el tipo de Pago del estado de la Orden.

        antes de REPARACION_LISTA -> ANTICIPO
        desde REPARACION_LISTA    -> PAGO

    ENTREGADA no introduce un tercer tipo: un cobro posterior a la
    entrega sigue siendo el PAGO del cierre.
    """
    if orden.estado_workflow is EstadoWorkflow.REQUERIMIENTO:
        return TipoPago.ANTICIPO
    if orden.estado_workflow in (
        EstadoWorkflow.REPARACION_LISTA,
        EstadoWorkflow.ENTREGADA,
    ):
        return TipoPago.PAGO
    return TipoPago.ANTICIPO


def registrar_pago(
    orden: OrdenReparacion,
    *,
    monto: Decimal,
    metodo: str,
    usuario: Usuario,
    fecha: datetime,
    pago_id: str | None = None,
) -> OrdenReparacion:
    """Registra un Pago (BR-REP-017-A, FEAT-REP-007).

    Capacidad transversal: NO corresponde a ningun PROC-REP-*, asi que
    NO toca ``current_process`` -la Orden sigue parada donde estaba-.
    Si deja traza en el historial, como accion funcional ``ACC-REP-020``
    enlazada al Pago que la origino, para que el recorrido explique que
    paso entre un nodo y el siguiente.

    Despues del pago, ``orden.saldo`` y ``orden.estado_pago`` se
    recalculan solos: son campos derivados.

    El ``tipo_pago`` NO lo elige el usuario: se deriva del estado de
    la Orden. Antes de REPARACION_LISTA el cobro es un ANTICIPO;
    desde REPARACION_LISTA en adelante es el PAGO del cierre. Es una
    dimension distinta del medio (``metodo``).

    BR-REP-017: exige usuario activo y rol distinto de Tecnico
    (``ROLES_PAGO``). Antes de MVP v2 esto no se validaba -cualquier
    usuario activo, Tecnico incluido, podia registrar un Pago-; es la
    correccion obligatoria de esta iteracion.

    BR-REP-016/017: solo se cobra a un Origen ``COBRABLE``
    (``CLIENTE_EXTERNO``). ``RT_INTERNO`` (``NO_COBRABLE_AL_CLIENTE``) y
    una eventual garantia (``NO_COBRABLE``) no tienen a quien cobrarle:
    esto NO es solo una omision de UI -``acciones_disponibles`` ya no
    ofrece ``REGISTRAR_PAGO`` para esos origenes-, el service lo rechaza
    aunque se lo invoque directamente.
    """
    validar_alguno_de(usuario, ROLES_PAGO)

    if politica_de(orden.origen).condicion_comercial != (
        CondicionComercial.COBRABLE
    ):
        raise PrecondicionInvalidaError(
            f"No se puede registrar un Pago sobre una Orden "
            f"{orden.origen.value}: su condicion comercial no es "
            f"COBRABLE."
        )

    if monto <= 0:
        raise PrecondicionInvalidaError(
            f"El monto del pago debe ser positivo: {monto}."
        )

    pago = Pago(
        id=pago_id or nuevo_id("PAG"),
        monto=monto,
        tipo_pago=tipo_de_pago_para(orden),
        metodo=metodo,
        usuario_id=usuario.id,
        fecha=fecha,
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


def validar_condicion_entrega(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> tuple[OrdenReparacion, bool]:
    """PROC-REP-265: determina si la Orden puede entregarse (BR-REP-017-B).

    Para un Origen COBRABLE la condicion es saldo = 0 (V1.3 no admite
    override para entregar con deuda); para NO_COBRABLE (garantia RMA) se
    aprueba directamente por Origen, sin pagos. La cortesia total queda
    fuera del MVP.

    Se evalua antes de generar el comprobante final (PROC-REP-280), para
    que el comprobante refleje siempre el saldo definitivo.
    """
    if orden.estado_workflow is not EstadoWorkflow.REPARACION_LISTA:
        raise PrecondicionInvalidaError(
            f"La condicion de entrega se evalua sobre una Orden "
            f"REPARACION_LISTA; esta en {orden.estado_workflow.value}."
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
    transversal de siempre y revalidando PROC-REP-265.
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
