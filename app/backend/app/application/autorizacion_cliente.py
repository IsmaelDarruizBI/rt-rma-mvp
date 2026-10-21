"""Tramo de autorizacion del cliente por Detalle (BR-REP-028, V1.4).

    registrar_decision_cliente
        046 (por Detalle) -> 047 [-> 300 por rechazado | -> 305]
        con autorizados:  -> 080 -> 090 [-> 140 | -> 100]   (sin habilitar)
                          -> 080 -> 090 -> 211              (ya habilitada)
        sin autorizados:  -> 211 [-> 129 | CANCELADA | ...]
    registrar_desistimiento
        046 (rechazo de lo pendiente | desistimiento de lo autorizado)
        -> 047 -> 300 | 305 -> 211 [-> CANCELADA | cierre de lo realizado]
    autorizaciones_de_orden     lectura: decision por Detalle
    pendientes_de_autorizacion  lectura: Detalles que esperan decision

Un comando = una intencion de Recepcion: registrar lo que respondio el
cliente, para uno o varios Detalles. Los nodos de sistema que siguen se
encadenan en la misma operacion y la Orden se guarda una sola vez.

La factibilidad corre solo sobre los Detalles recien autorizados: los
demas conservan su condicion. Si la Orden ya fue habilitada (PROC-REP-140
en el historial), no se vuelve a habilitar ni a priorizar: 090 vuelve a
PROC-REP-211, que preserva la toma activa y la Ejecucion en curso, o
devuelve la Orden a la cola con su prioridad (BR-REP-034/037).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.domain.models import (
    CanalComunicacion,
    CondicionReparacionDetail,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    OrigenCancelacion,
    RegistroAutorizacionCliente,
    ReparacionDetail,
    Usuario,
)
from app.services import (
    DecisionDetalle,
    EstadoAutorizacion,
    analizar_desistimiento,
    cargar_reservas_externas,
    decision_vigente,
    definicion_finalizada,
    estado_autorizacion,
    evaluar_situacion_orden,
    exigir_fuera_del_ingreso_inicial,
    finalizada_sin_reparacion,
    fue_habilitada,
    habilitar_orden,
    lista_para_cierre,
    pendiente_de_autorizacion,
    requiere_autorizacion_cliente,
    validar_factibilidad_detalles,
)
from app.services import (
    registrar_decision_cliente as registrar_decision_cliente_servicio,
)
from app.services import (
    registrar_desistimiento_cliente as registrar_desistimiento_servicio,
)

from .cola import encolar_si_ingreso_automatico
from .concurrencia import seccion_critica_inventario
from .consultas import nombres_de_tipo_por_detalle
from .contexto import ApplicationContext
from .modificacion import orden_para_modificar


class SituacionAutorizacion(str, Enum):
    """Donde esta cada Detalle respecto de la decision del cliente.

    Presentacion derivada (no se persiste): combina la autorizacion con el
    estado y la condicion del Detalle para distinguir lo que la UI tiene
    que mostrar. Solo ``AUTORIZADO_FACTIBLE`` puede iniciarse.
    """

    NO_REQUERIDA = "NO_REQUERIDA"
    PENDIENTE_AUTORIZACION = "PENDIENTE_AUTORIZACION"
    AUTORIZADO_FACTIBLE = "AUTORIZADO_FACTIBLE"
    AUTORIZADO_SIN_STOCK = "AUTORIZADO_SIN_STOCK"
    REQUIERE_REDEFINICION = "REQUIERE_REDEFINICION"
    EN_EJECUCION = "EN_EJECUCION"
    COMPLETO = "COMPLETO"
    CANCELADO_POR_RECHAZO = "CANCELADO_POR_RECHAZO"
    CANCELADO_POR_DESISTIMIENTO = "CANCELADO_POR_DESISTIMIENTO"
    CANCELADO = "CANCELADO"


def situacion_autorizacion(
    orden: OrdenReparacion,
    detalle: ReparacionDetail,
) -> SituacionAutorizacion:
    """La situacion del Detalle frente a la autorizacion del cliente."""
    if not requiere_autorizacion_cliente(orden):
        return SituacionAutorizacion.NO_REQUERIDA
    if detalle.estado is EstadoReparacionDetail.CANCELADO:
        origen = (
            detalle.cancelacion.origen
            if detalle.cancelacion is not None
            else OrigenCancelacion.INTERNA
        )
        if origen is OrigenCancelacion.RECHAZO_CLIENTE:
            return SituacionAutorizacion.CANCELADO_POR_RECHAZO
        if origen is OrigenCancelacion.DESISTIMIENTO_CLIENTE:
            return SituacionAutorizacion.CANCELADO_POR_DESISTIMIENTO
        return SituacionAutorizacion.CANCELADO
    if detalle.estado is EstadoReparacionDetail.COMPLETO:
        return SituacionAutorizacion.COMPLETO
    if detalle.estado is EstadoReparacionDetail.EN_PROGRESO:
        return SituacionAutorizacion.EN_EJECUCION
    if detalle.condicion is CondicionReparacionDetail.REQUIERE_DEFINICION:
        return SituacionAutorizacion.REQUIERE_REDEFINICION
    if pendiente_de_autorizacion(orden, detalle):
        return SituacionAutorizacion.PENDIENTE_AUTORIZACION
    if detalle.condicion is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS:
        return SituacionAutorizacion.AUTORIZADO_SIN_STOCK
    return SituacionAutorizacion.AUTORIZADO_FACTIBLE


def decision_registrable(orden: OrdenReparacion) -> bool:
    """Recepcion puede registrar ahora la decision del cliente.

    El Origen la exige, la definicion ya se finalizo, la Orden sigue
    abierta y no esta CANCELADA, y algun Detalle la espera.
    """
    return (
        requiere_autorizacion_cliente(orden)
        and definicion_finalizada(orden)
        and not orden.esta_cerrada
        and orden.estado_workflow is not EstadoWorkflow.CANCELADA
        and any(
            pendiente_de_autorizacion(orden, detalle)
            for detalle in orden.reparaciones_detail
        )
    )


def _admite_cancelaciones_del_cliente(orden: OrdenReparacion) -> bool:
    return (
        requiere_autorizacion_cliente(orden)
        and definicion_finalizada(orden)
        and not orden.esta_cerrada
        and orden.estado_workflow is not EstadoWorkflow.CANCELADA
        and not lista_para_cierre(orden)
        and not finalizada_sin_reparacion(orden)
    )


def desistimiento_total_ofrecible(orden: OrdenReparacion) -> bool:
    """Corresponde ofrecer "el cliente desiste de todos los trabajos".

    Cuando queda trabajo YA autorizado sin terminar (con lo solo pendiente
    alcanza con el rechazo). Se ofrece aunque algo lo impida: la UI muestra
    los bloqueantes (analizar_desistimiento) y el backend lo rechaza.
    """
    return _admite_cancelaciones_del_cliente(orden) and any(
        detalle.estado
        in (
            EstadoReparacionDetail.DEFINIDO,
            EstadoReparacionDetail.EN_PROGRESO,
        )
        and estado_autorizacion(orden, detalle)
        in (EstadoAutorizacion.AUTORIZADO, EstadoAutorizacion.SIN_DECISION)
        for detalle in orden.reparaciones_detail
    )


def detalles_desistibles(orden: OrdenReparacion) -> tuple[str, ...]:
    """Detalles autorizados de los que el cliente puede desistir ahora."""
    if not _admite_cancelaciones_del_cliente(orden):
        return ()
    return analizar_desistimiento(orden).desistibles


@dataclass(frozen=True)
class AutorizacionDetalle:
    """La autorizacion de UN Detalle, tal como la consulta Recepcion."""

    detalle_id: str
    tipo_reparacion_id: str
    tipo_reparacion_nombre: str
    precio: Decimal
    version_definicion: int
    estado: EstadoAutorizacion
    situacion: SituacionAutorizacion
    decision_vigente: RegistroAutorizacionCliente | None
    historial: tuple[RegistroAutorizacionCliente, ...]
    decidible: bool


@dataclass(frozen=True)
class AutorizacionesOrden:
    """``GET /api/orders/{id}/authorizations``."""

    orden_id: str
    requerida: bool
    registrable: bool
    detalles: tuple[AutorizacionDetalle, ...]


def _autorizacion_del_detalle(
    orden: OrdenReparacion,
    detalle: ReparacionDetail,
    nombre_tipo: str,
    registrable: bool,
) -> AutorizacionDetalle:
    estado = estado_autorizacion(orden, detalle)
    return AutorizacionDetalle(
        detalle_id=detalle.id,
        tipo_reparacion_id=detalle.tipo_reparacion_id,
        tipo_reparacion_nombre=nombre_tipo,
        precio=detalle.precio,
        version_definicion=detalle.version_definicion,
        estado=estado,
        situacion=situacion_autorizacion(orden, detalle),
        decision_vigente=decision_vigente(detalle),
        historial=tuple(detalle.autorizaciones),
        decidible=registrable and estado is EstadoAutorizacion.PENDIENTE,
    )


def autorizaciones_de_orden(
    contexto: ApplicationContext,
    orden_id: str,
) -> AutorizacionesOrden:
    """La decision del cliente de cada Detalle de la Orden. Solo lee."""
    orden = contexto.ordenes.obtener(orden_id)
    nombres = nombres_de_tipo_por_detalle(contexto, orden)
    registrable = decision_registrable(orden)
    return AutorizacionesOrden(
        orden_id=orden.id,
        requerida=requiere_autorizacion_cliente(orden),
        registrable=registrable,
        detalles=tuple(
            _autorizacion_del_detalle(
                orden,
                detalle,
                nombres.get(detalle.id, detalle.tipo_reparacion_id),
                registrable,
            )
            for detalle in orden.reparaciones_detail
        ),
    )


@dataclass(frozen=True)
class PendienteAutorizacion:
    """Un Detalle que espera la decision del cliente, en cualquier Orden."""

    orden_id: str
    cliente_nombre: str
    equipo: str
    detalle_id: str
    tipo_reparacion_nombre: str
    precio: Decimal
    version_definicion: int


def pendientes_de_autorizacion(
    contexto: ApplicationContext,
) -> list[PendienteAutorizacion]:
    """Detalles cuya decision Recepcion puede registrar ahora. Solo lee.

    Solo Ordenes donde la decision es registrable: un Detalle de una
    definicion todavia abierta no se le presento al cliente.
    """
    pendientes: list[PendienteAutorizacion] = []
    ordenes = sorted(contexto.ordenes.listar(), key=lambda orden: orden.id)
    for orden in ordenes:
        if not decision_registrable(orden):
            continue
        nombres = nombres_de_tipo_por_detalle(contexto, orden)
        for detalle in orden.reparaciones_detail:
            if not pendiente_de_autorizacion(orden, detalle):
                continue
            pendientes.append(
                PendienteAutorizacion(
                    orden_id=orden.id,
                    cliente_nombre=(
                        orden.cliente.nombre_apellido
                        if orden.cliente
                        else orden.id
                    ),
                    equipo=f"{orden.equipo.marca} {orden.equipo.modelo}",
                    detalle_id=detalle.id,
                    tipo_reparacion_nombre=nombres.get(
                        detalle.id, detalle.tipo_reparacion_id
                    ),
                    precio=detalle.precio,
                    version_definicion=detalle.version_definicion,
                )
            )
    return pendientes


def registrar_decision_cliente(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    canal: CanalComunicacion,
    decisiones: Sequence[DecisionDetalle],
    observaciones: str | None = None,
) -> OrdenReparacion:
    """Recepcion registra la respuesta del cliente sobre uno o mas Detalles.

    Autorizados: factibilidad de esos Detalles (080 -> 090). Una Orden que
    nunca se habilito se habilita (140) si alguno quedo trabajable, o se
    detiene en 100 si no hay recursos (EXC-REP-001); una ya habilitada
    vuelve a PROC-REP-211. Sin autorizados (solo rechazos), PROC-REP-211
    decide: esperar al cliente (129), CANCELADA si ya no queda nada, o el
    cierre de lo realizado.

    Corre en la seccion critica de inventario porque la factibilidad lee
    el stock y las reservas de las demas Ordenes. En el ingreso inicial de
    CLIENTE_EXTERNO la autorizacion se registra con el comprobante de
    ingreso, no por separado.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with (
        seccion_critica_inventario(),
        orden_para_modificar(contexto, orden_id) as orden,
    ):
        exigir_fuera_del_ingreso_inicial(
            orden, "registrar la autorizacion inicial"
        )
        orden = aplicar_decision_cliente(
            contexto,
            orden,
            usuario=usuario,
            canal=canal,
            decisiones=decisiones,
            observaciones=observaciones,
            fecha=fecha,
        )
        contexto.ordenes.guardar(orden)
    return orden


def aplicar_decision_cliente(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    canal: CanalComunicacion,
    decisiones: Sequence[DecisionDetalle],
    observaciones: str | None,
    fecha: datetime,
) -> OrdenReparacion:
    """La decision y lo que sigue (factibilidad, 140 o 211), en memoria.

    El caller ya esta dentro de la seccion critica de inventario y
    persiste: lo usan el registro explicito de la decision y el ingreso
    inicial, que la compone con la recepcion y la definicion.
    """
    ya_habilitada = fue_habilitada(orden)
    orden, autorizados = registrar_decision_cliente_servicio(
        orden,
        decisiones=decisiones,
        usuario=usuario,
        canal=canal,
        fecha=fecha,
        observaciones=observaciones,
    )
    if not autorizados:
        orden, _ = evaluar_situacion_orden(orden, fecha=fecha)
        return orden
    orden, factible = validar_factibilidad_detalles(
        orden,
        insumos=contexto.catalogos.listar_insumos(),
        insumos_previstos=contexto.catalogos.listar_tipo_reparacion_insumos(),
        fecha=fecha,
        reservas_externas=cargar_reservas_externas(orden.id, contexto.ordenes),
        detalle_ids=autorizados,
        registrar_faltantes=not ya_habilitada,
    )
    if ya_habilitada:
        orden, _ = evaluar_situacion_orden(orden, fecha=fecha)
    elif factible:
        orden = habilitar_orden(orden, fecha=fecha)
        orden = encolar_si_ingreso_automatico(
            orden, fecha=fecha, usuario_id=usuario.id
        )
    return orden


def registrar_desistimiento(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    canal: CanalComunicacion,
    motivo: str,
    detalle_id: str | None = None,
) -> OrdenReparacion:
    """Recepcion registra que el cliente desiste (de un Detalle o de todo).

    Sin detalle_id, de todos los trabajos cancelables. Todo se valida
    antes de cancelar: si algo lo impide no cambia nada. Despues, el
    resolver de siempre (PROC-REP-211): CANCELADA -con devolucion si el
    equipo esta en custodia- o el cierre de lo ya realizado.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_desistimiento_servicio(
            orden,
            usuario=usuario,
            canal=canal,
            motivo=motivo,
            fecha=fecha,
            detalle_id=detalle_id,
        )
        orden, _ = evaluar_situacion_orden(orden, fecha=fecha)
        contexto.ordenes.guardar(orden)
    return orden
