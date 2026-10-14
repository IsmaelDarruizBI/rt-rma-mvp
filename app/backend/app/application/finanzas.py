"""Tramo financiero: anulacion de pagos, devolucion de dinero y consultas.

    anular_pago_de_orden            correccion administrativa (ACC-REP-021)
    registrar_devolucion_de_dinero  devolucion de dinero (ACC-REP-022, V1.4
                                    PROC-REP-267)
    movimientos_financieros         lectura: pagos, anulaciones y
                                    devoluciones en orden cronologico
    listar_medios_pago              lectura: catalogo de medios

Registrar un Pago sigue en ``application.cierre`` (capacidad transversal
de siempre). Los tres movimientos comparten ``reevaluar_tras_movimiento``:
si la Orden ya esta en la condicion de entrega (PROC-REP-265/266) se
revalida, y si es una Orden CANCELADA que ya no espera la devolucion
fisica del equipo se verifica si puede terminar (PROC-REP-268). Ningun
movimiento cierra ni reabre una Orden por fuera de esos puntos.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.domain.models import (
    EstadoWorkflow,
    MedioPago,
    OrdenReparacion,
)
from app.services import (
    anular_pago,
    devolucion_pendiente,
    es_cobrable,
    registrar_devolucion_dinero,
    registrar_saldo_pendiente,
    validar_condicion_entrega,
    verificar_fin_financiero,
)

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar

# Nodos en los que la Orden ya esta en Completar Cobro (BR-REP-017-B).
NODOS_DE_CONDICION_DE_ENTREGA = frozenset({"PROC-REP-265", "PROC-REP-266"})


def reevaluar_tras_movimiento(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> tuple[OrdenReparacion, bool]:
    """Que sigue despues de un movimiento de dinero real.

    - En la condicion de entrega (265/266): se revalida PROC-REP-265 y, si
      todavia hay saldo pendiente, PROC-REP-266. Devuelve si ya puede
      entregarse.
    - Orden CANCELADA sin devolucion fisica pendiente: PROC-REP-268 (sin
      saldo a favor, termina).
    - En cualquier otro punto el movimiento no mueve el proceso.

    Solo se invoca tras un movimiento real (Pago, anulacion o devolucion):
    no hay revalidaciones sin accion financiera (BR-REP-038).
    """
    if orden.current_process in NODOS_DE_CONDICION_DE_ENTREGA:
        orden, puede_entregar = validar_condicion_entrega(orden, fecha=fecha)
        if not puede_entregar and orden.saldo > 0:
            orden = registrar_saldo_pendiente(orden, fecha=fecha)
        return orden, puede_entregar
    if (
        orden.estado_workflow is EstadoWorkflow.CANCELADA
        and not orden.esta_cerrada
        and not devolucion_pendiente(orden)
    ):
        orden = verificar_fin_financiero(orden, fecha=fecha)
    return orden, False


def anular_pago_de_orden(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    pago_id: str,
    usuario_id: str,
    motivo: str,
) -> tuple[OrdenReparacion, bool]:
    """Un Administrador anula un Pago registrado por error.

    El Pago se conserva con su anulacion; deja de contar como pagado. No
    reabre nada: una Orden cerrada no admite la anulacion (E1).
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = anular_pago(
            orden,
            pago_id=pago_id,
            usuario=usuario,
            motivo=motivo,
            fecha=fecha,
        )
        orden, puede_entregar = reevaluar_tras_movimiento(orden, fecha=fecha)
        contexto.ordenes.guardar(orden)
    return orden, puede_entregar


def registrar_devolucion_de_dinero(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    pago_id: str,
    usuario_id: str,
    monto: Decimal,
    medio: str,
    motivo: str,
    referencia: str | None = None,
    operacion_id: str | None = None,
) -> tuple[OrdenReparacion, bool]:
    """Recepcion o Administracion devuelve dinero al cliente desde un Pago.

    Con la devolucion total del saldo a favor: en el cierre comercial se
    revalida la entrega (PROC-REP-265); en una Orden CANCELADA cuyo equipo
    ya se devolvio (o no quedo en custodia), la Orden termina
    (PROC-REP-268 -> EVT-REP-999).
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_devolucion_dinero(
            orden,
            pago_id=pago_id,
            monto=monto,
            medio=medio,
            usuario=usuario,
            motivo=motivo,
            fecha=fecha,
            medios=contexto.catalogos.listar_medios_pago(),
            referencia=referencia,
            operacion_id=operacion_id,
        )
        orden, puede_entregar = reevaluar_tras_movimiento(orden, fecha=fecha)
        contexto.ordenes.guardar(orden)
    return orden, puede_entregar


def listar_medios_pago(contexto: ApplicationContext) -> list[MedioPago]:
    """Catalogo de medios de pago (los configurados o los predeterminados)."""
    return contexto.catalogos.listar_medios_pago()


class SituacionFinanciera(str, Enum):
    """Lectura de la cuenta de la Orden para la UI (derivada).

    ``NO_COBRABLE``: sin circuito comercial (RT_INTERNO, garantia).
    ``SALDO_PENDIENTE``: el cliente debe. ``SALDO_A_FAVOR``: hay que
    devolverle dinero (devolucion pendiente). ``SALDADA``: hubo importes y
    la cuenta da cero. ``SIN_MOVIMIENTOS``: todavia no hay nada que cobrar
    ni cobrado.
    """

    NO_COBRABLE = "NO_COBRABLE"
    SALDO_PENDIENTE = "SALDO_PENDIENTE"
    SALDO_A_FAVOR = "SALDO_A_FAVOR"
    SALDADA = "SALDADA"
    SIN_MOVIMIENTOS = "SIN_MOVIMIENTOS"


def situacion_financiera(orden: OrdenReparacion) -> SituacionFinanciera:
    """La situacion de la cuenta de la Orden."""
    if not es_cobrable(orden):
        return SituacionFinanciera.NO_COBRABLE
    if orden.saldo > 0:
        return SituacionFinanciera.SALDO_PENDIENTE
    if orden.saldo < 0:
        return SituacionFinanciera.SALDO_A_FAVOR
    if orden.total > 0 or orden.resumen_pago.pagos:
        return SituacionFinanciera.SALDADA
    return SituacionFinanciera.SIN_MOVIMIENTOS


class TipoMovimiento(str, Enum):
    PAGO = "PAGO"
    ANULACION = "ANULACION"
    DEVOLUCION = "DEVOLUCION"


@dataclass(frozen=True)
class MovimientoFinanciero:
    """Un movimiento de dinero, para la lista cronologica (solo lectura).

    ``efecto`` es como mueve el saldo: un Pago lo baja, su anulacion lo
    vuelve a subir y una devolucion lo sube (sale dinero hacia el
    cliente).
    """

    fecha: datetime
    tipo: TipoMovimiento
    id: str
    pago_id: str
    monto: Decimal
    efecto: Decimal
    medio: str | None
    usuario_id: str
    detalle: str


def movimientos_financieros(
    orden: OrdenReparacion,
) -> list[MovimientoFinanciero]:
    """Pagos, anulaciones y devoluciones de la Orden, del mas antiguo al
    mas reciente."""
    movimientos: list[MovimientoFinanciero] = []
    for pago in orden.resumen_pago.pagos:
        detalle = pago.tipo_pago.value
        if pago.referencia:
            detalle += f" · ref. {pago.referencia}"
        movimientos.append(
            MovimientoFinanciero(
                fecha=pago.fecha,
                tipo=TipoMovimiento.PAGO,
                id=pago.id,
                pago_id=pago.id,
                monto=pago.monto,
                efecto=-pago.monto,
                medio=pago.metodo,
                usuario_id=pago.usuario_id,
                detalle=detalle,
            )
        )
        if pago.anulacion is not None:
            movimientos.append(
                MovimientoFinanciero(
                    fecha=pago.anulacion.fecha,
                    tipo=TipoMovimiento.ANULACION,
                    id=f"{pago.id}-ANULACION",
                    pago_id=pago.id,
                    monto=pago.monto,
                    efecto=pago.monto,
                    medio=None,
                    usuario_id=pago.anulacion.usuario_id,
                    detalle=pago.anulacion.motivo,
                )
            )
    for devolucion in orden.resumen_pago.devoluciones:
        detalle = devolucion.motivo
        if devolucion.referencia:
            detalle += f" · ref. {devolucion.referencia}"
        movimientos.append(
            MovimientoFinanciero(
                fecha=devolucion.fecha,
                tipo=TipoMovimiento.DEVOLUCION,
                id=devolucion.id,
                pago_id=devolucion.pago_id,
                monto=devolucion.monto,
                efecto=devolucion.monto,
                medio=devolucion.medio,
                usuario_id=devolucion.usuario_id,
                detalle=detalle,
            )
        )
    return sorted(movimientos, key=lambda movimiento: movimiento.fecha)
