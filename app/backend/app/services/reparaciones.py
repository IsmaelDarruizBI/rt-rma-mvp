"""Detalles de Reparacion: definicion, factibilidad, control y puntaje.

Nodos cubiertos: PROC-REP-045/070 (definir Detalles), PROC-REP-080/090
(factibilidad), PROC-REP-220/230 (control tecnico) y PROC-REP-245
(puntaje).

Features: FEAT-REP-002, FEAT-REP-003, FEAT-REP-006, FEAT-REP-007 (el
precio snapshot se registra al crear el Detalle).
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    CondicionReparacionDetail,
    EstadoControl,
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoWorkflow,
    Insumo,
    OrdenReparacion,
    OrigenOrden,
    ReparacionDetail,
    RolUsuario,
    TipoReparacion,
    TipoReparacionInsumos,
    Usuario,
)

from .autorizacion import validar_actor
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .inventario import faltantes_del_detalle
from .recursos import tiene_override_factibilidad
from .revisiones import revision_tecnica_realizada
from .workflow import registrar_paso


def definir_reparacion_detail(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    tipo_reparacion: TipoReparacion,
    usuario: Usuario,
    fecha: datetime,
    observaciones: str | None = None,
    detalle_origen_id: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-045 ("Si") -> PROC-REP-070 (FEAT-REP-002 / FEAT-REP-007).

    Crea un Detalle tomando de ``TipoReparacion`` un snapshot de precio,
    puntaje y garantia (BR-REP-015): el Detalle guarda solo el ID del
    tipo, nunca el objeto, para que un cambio posterior de catalogo no
    reescriba una Orden ya registrada.

    ``detalle_origen_id`` (HP-REP-003, BR-REP-019) deja vinculado el
    Detalle de garantia con el Detalle de la Orden origen; el snapshot se
    toma igual del TipoReparacion, nunca del Detalle viejo.

    El Detalle nace DEFINIDO con control PENDIENTE. La decision
    PROC-REP-045 se registra una sola vez, al definir el primer Detalle.

    El MVP cubre unicamente el camino "los Detalles se conocen desde el
    ingreso": PROC-REP-055/065/075 (revision tecnica previa) y
    PROC-REP-126/127 no estan implementados.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    if orden.estado_workflow is not EstadoWorkflow.REQUERIMIENTO:
        raise PrecondicionInvalidaError(
            f"Solo se definen Detalles sobre una Orden en REQUERIMIENTO; "
            f"esta en {orden.estado_workflow.value}."
        )
    if not tipo_reparacion.activo:
        raise PrecondicionInvalidaError(
            f"El Tipo de Reparacion {tipo_reparacion.id} no esta activo."
        )
    if any(detalle.id == detalle_id for detalle in orden.reparaciones_detail):
        raise PrecondicionInvalidaError(
            f"La Orden ya tiene un Detalle con id {detalle_id}."
        )

    nueva_orden = orden
    if not orden.reparaciones_detail:
        nueva_orden = registrar_paso(
            nueva_orden,
            process_id="PROC-REP-045",
            accion="DETALLES_CONOCIDOS",
            fecha=fecha,
            usuario_id=usuario.id,
            observacion="Si",
        )

    nueva_orden = registrar_paso(
        nueva_orden,
        process_id="PROC-REP-070",
        accion="DEFINIR_DETALLES",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
    )
    nueva_orden.reparaciones_detail.append(
        _detalle_con_snapshot(
            detalle_id=detalle_id,
            tipo_reparacion=tipo_reparacion,
            observaciones=observaciones,
            detalle_origen_id=detalle_origen_id,
        )
    )
    return nueva_orden


def _detalle_con_snapshot(
    *,
    detalle_id: str,
    tipo_reparacion: TipoReparacion,
    observaciones: str | None,
    detalle_origen_id: str | None,
) -> ReparacionDetail:
    """Detalle DEFINIDO con el snapshot del Tipo (BR-REP-015).

    Compartido por PROC-REP-070 y PROC-REP-075: mismo snapshot, nodos
    funcionales distintos.
    """
    return ReparacionDetail(
        id=detalle_id,
        tipo_reparacion_id=tipo_reparacion.id,
        precio=tipo_reparacion.precio,
        puntaje=tipo_reparacion.puntaje,
        garantia_dias=tipo_reparacion.garantia_dias,
        estado=EstadoReparacionDetail.DEFINIDO,
        control_estado=EstadoControl.PENDIENTE,
        observaciones=observaciones,
        detalle_origen_id=detalle_origen_id,
    )


def definir_reparacion_detail_luego_revision(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    tipo_reparacion: TipoReparacion,
    usuario: Usuario,
    fecha: datetime,
    observaciones: str | None = None,
    detalle_origen_id: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-068 ("Si") -> PROC-REP-075 (VAR-REP-001/002).

    Recepcion define un Detalle usando el resultado de la revision
    tecnica de una Orden EN_REVISION. Mismo snapshot que PROC-REP-070,
    pero la traza es la del proceso real: NO registra PROC-REP-045 "Si"
    ni PROC-REP-070.

    PROC-REP-068 se registra una sola vez, con el primer Detalle; cada
    Detalle registra su propio PROC-REP-075 (Multi-Detalle). El camino
    "No" (PROC-REP-069, SIN_REPARACION) no esta implementado.

    En una garantia RMA cada Detalle referencia a su Detalle origen
    tomado de ``orden.detalles_origen_ids`` -nunca del historial-: con
    exactamente uno se usa ese; con mas de uno hay que indicarlo.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    if orden.estado_workflow is not EstadoWorkflow.EN_REVISION:
        raise PrecondicionInvalidaError(
            f"Solo se definen Detalles luego de revision sobre una Orden "
            f"EN_REVISION; esta en {orden.estado_workflow.value}."
        )
    if not revision_tecnica_realizada(orden):
        raise PrecondicionInvalidaError(
            "Falta la revision tecnica (PROC-REP-065) antes de definir "
            "los Detalles."
        )
    if not tipo_reparacion.activo:
        raise PrecondicionInvalidaError(
            f"El Tipo de Reparacion {tipo_reparacion.id} no esta activo."
        )
    if any(detalle.id == detalle_id for detalle in orden.reparaciones_detail):
        raise PrecondicionInvalidaError(
            f"La Orden ya tiene un Detalle con id {detalle_id}."
        )

    origen_del_detalle = _detalle_origen_para(orden, detalle_origen_id)

    nueva_orden = orden
    if not orden.reparaciones_detail:
        nueva_orden = registrar_paso(
            nueva_orden,
            process_id="PROC-REP-068",
            accion="SE_PUDO_DEFINIR_REPARACION",
            fecha=fecha,
            usuario_id=usuario.id,
            observacion="Si",
        )

    nueva_orden = registrar_paso(
        nueva_orden,
        process_id="PROC-REP-075",
        accion="DEFINIR_DETALLES_LUEGO_DE_REVISION",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
    )
    nueva_orden.reparaciones_detail.append(
        _detalle_con_snapshot(
            detalle_id=detalle_id,
            tipo_reparacion=tipo_reparacion,
            observaciones=observaciones,
            detalle_origen_id=origen_del_detalle,
        )
    )
    return nueva_orden


def _detalle_origen_para(
    orden: OrdenReparacion,
    detalle_origen_id: str | None,
) -> str | None:
    """Detalle origen que corresponde a un Detalle nuevo (BR-REP-019)."""
    if orden.origen is not OrigenOrden.RMA_GARANTIA_REPARACION:
        if detalle_origen_id is not None:
            raise PrecondicionInvalidaError(
                f"Un Detalle de una Orden {orden.origen.value} no tiene "
                f"Detalle origen."
            )
        return None

    posibles = orden.detalles_origen_ids
    if detalle_origen_id is not None:
        if detalle_origen_id not in posibles:
            raise PrecondicionInvalidaError(
                f"{detalle_origen_id} no es un Detalle origen identificado "
                f"para la Orden {orden.id}."
            )
        return detalle_origen_id
    if len(posibles) != 1:
        raise PrecondicionInvalidaError(
            f"La Orden {orden.id} tiene {len(posibles)} Detalles origen: "
            f"hay que indicar a cual corresponde el Detalle nuevo."
        )
    return posibles[0]


# Condiciones del circuito de recursos: son las unicas que PROC-REP-080
# reevalua. Otra causa de bloqueo (REQUIERE_DEFINICION, EXC-REP-004) no se
# pisa.
_CONDICIONES_DE_RECURSOS = (
    CondicionReparacionDetail.SIN_BLOQUEO,
    CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS,
)


def validar_factibilidad_detalles(
    orden: OrdenReparacion,
    *,
    insumos: Sequence[Insumo],
    insumos_previstos: Sequence[TipoReparacionInsumos],
    fecha: datetime,
    reservas_externas: Mapping[str, Decimal] | None = None,
) -> tuple[OrdenReparacion, bool]:
    """PROC-REP-080 -> 090 [-> 100 por Detalle]: factibilidad POR Detalle.

    BR-REP-002: cada Detalle DEFINIDO se evalua por separado contra la
    disponibilidad actual (``stock_fisico`` menos reservas propias y
    ajenas) y su ``condicion`` pasa a ``SIN_BLOQUEO`` o a
    ``BLOQUEADO_POR_RECURSOS`` -en cada ejecucion, asi que un Detalle
    bloqueado puede volver a desbloquearse-. Un Detalle sin recursos NO
    bloquea a los demas.

    El ``bool`` devuelto significa **hay al menos un Detalle trabajable**
    (PROC-REP-090), no "todos son factibles". Con uno trabajable 090 es
    "Si" y la Orden puede habilitarse aunque otros sigan bloqueados. Con
    ninguno, 090 es "Ninguno trabajable" y se registra PROC-REP-100 por
    cada Detalle bloqueado con SUS faltantes; la Orden queda en
    PROC-REP-100 (frontera de EXC-REP-001/002): no se encadena 110/120.

    Solo CONSULTA: no reserva, no genera movimientos y no toca el stock.
    La reserva real ocurre recien en PROC-REP-185 (BR-REP-006).
    """
    ajenas = reservas_externas or {}

    if not orden.reparaciones_detail:
        raise PrecondicionInvalidaError(
            "No se puede validar factibilidad sin Detalles de Reparacion."
        )

    nueva_orden = orden.model_copy(deep=True)

    faltantes_por_detalle: dict[str, list[str]] = {}
    for detalle in nueva_orden.reparaciones_detail:
        if (
            detalle.estado is not EstadoReparacionDetail.DEFINIDO
            or detalle.condicion not in _CONDICIONES_DE_RECURSOS
        ):
            continue
        if tiene_override_factibilidad(nueva_orden, detalle.id):
            # EXC-REP-002: el override autorizado persiste (BR-REP-003).
            detalle.condicion = CondicionReparacionDetail.SIN_BLOQUEO
            continue
        faltantes = faltantes_del_detalle(
            detalle.tipo_reparacion_id,
            nueva_orden.movimientos_insumo,
            insumos,
            insumos_previstos,
            ajenas,
        )
        if faltantes:
            detalle.condicion = (
                CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
            )
            faltantes_por_detalle[detalle.id] = faltantes
        else:
            detalle.condicion = CondicionReparacionDetail.SIN_BLOQUEO

    hay_trabajable = any(
        detalle.estado is EstadoReparacionDetail.DEFINIDO
        and detalle.condicion is CondicionReparacionDetail.SIN_BLOQUEO
        for detalle in nueva_orden.reparaciones_detail
    )

    bloqueados = (
        "; ".join(
            f"{detalle_id} [{', '.join(faltantes)}]"
            for detalle_id, faltantes in faltantes_por_detalle.items()
        )
        or None
    )
    nueva_orden = registrar_paso(
        nueva_orden,
        process_id="PROC-REP-080",
        accion="VALIDAR_FACTIBILIDAD",
        fecha=fecha,
        observacion=f"Bloqueados: {bloqueados}" if bloqueados else None,
    )
    nueva_orden = registrar_paso(
        nueva_orden,
        process_id="PROC-REP-090",
        accion="EXISTE_DETALLE_TRABAJABLE",
        fecha=fecha,
        observacion="Si" if hay_trabajable else "Ninguno trabajable",
    )
    if hay_trabajable:
        return nueva_orden, True

    for detalle_id, faltantes in faltantes_por_detalle.items():
        nueva_orden = registrar_paso(
            nueva_orden,
            process_id="PROC-REP-100",
            accion="REGISTRAR_ADVERTENCIA_DE_FALTANTE",
            fecha=fecha,
            reparacion_detail_id=detalle_id,
            observacion=f"Faltantes: {', '.join(faltantes)}",
        )
    return nueva_orden, False


def aprobar_control_tecnico(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
    detalle_id: str | None = None,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-220 -> PROC-REP-230: Recepcion aprueba (BR-REP-008).

    PROC-REP-220 solo se alcanza cuando la Orden entera es terminal
    (todos sus Detalles COMPLETO): es el mismo requisito que
    ``resolver_situacion_orden`` exige para clasificar ``COMPLETA``
    (BR-REP-012). Por eso esta precondicion se exige siempre, con o sin
    ``detalle_id`` -no alcanza con que el Detalle puntual este COMPLETO
    si todavia queda otro DEFINIDO o EN_PROGRESO-.

    Recepcion controla la Orden completa pero aprueba Detalle por
    Detalle (Multi-Detalle): con ``detalle_id`` aprueba unicamente ese
    Detalle; sin ``detalle_id`` preserva el comportamiento anterior
    (aprueba todos los Detalles de una vez). El MVP implementa solo la
    aprobacion: el rechazo y el retrabajo (PROC-REP-235) no estan
    implementados.

    No cambia el estado tecnico del Detalle: sigue COMPLETO. La
    aprobacion es otra dimension y vive en ``control_estado``.

    PROC-REP-230 ("todos los Detalles fueron aprobados") solo se
    registra cuando, despues de esta aprobacion, TODOS los Detalles de
    la Orden quedan APROBADO -en ese caso, siempre con observacion
    "Si": "No" significaria que un Detalle fue RECHAZADO, y el rechazo
    esta fuera de scope (EXC-REP-005). Una aprobacion parcial (todavia
    queda otro Detalle PENDIENTE) NO registra PROC-REP-230: eso no es
    "No", es simplemente que la decision todavia no se tomo. El caller
    (``application.cierre.aprobar_control``) sigue el mismo criterio
    para PROC-REP-245/240.

    PROC-REP-220 es ACT-RECEP: el control lo hace Recepcion, no el
    tecnico que ejecuto el trabajo.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    if not orden.reparaciones_detail:
        raise PrecondicionInvalidaError("No hay Detalles que controlar.")
    if any(
        ejecucion.estado is EstadoEjecucion.EN_PROGRESO
        for ejecucion in orden.ejecuciones
    ):
        raise PrecondicionInvalidaError(
            "No se puede controlar con una Ejecucion activa."
        )
    if any(
        detalle.estado is not EstadoReparacionDetail.COMPLETO
        for detalle in orden.reparaciones_detail
    ):
        raise PrecondicionInvalidaError(
            "El control tecnico (PROC-REP-220) solo se alcanza cuando "
            "todos los Detalles de la Orden estan COMPLETO."
        )

    if detalle_id is not None:
        detalle_objetivo = next(
            (
                detalle
                for detalle in orden.reparaciones_detail
                if detalle.id == detalle_id
            ),
            None,
        )
        if detalle_objetivo is None:
            raise EntidadNoEncontradaError(
                f"La Orden no tiene el Detalle {detalle_id}"
            )
        objetivo_ids = {detalle_id}
    else:
        objetivo_ids = {detalle.id for detalle in orden.reparaciones_detail}

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-220",
        accion="REALIZAR_CONTROL_TECNICO",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=observaciones,
    )
    for detalle in nueva_orden.reparaciones_detail:
        if detalle.id in objetivo_ids:
            detalle.control_estado = EstadoControl.APROBADO
            detalle.control_usuario_id = usuario.id
            detalle.control_fecha = fecha
            detalle.control_observaciones = observaciones

    todos_aprobados = all(
        detalle.control_estado is EstadoControl.APROBADO
        for detalle in nueva_orden.reparaciones_detail
    )
    if not todos_aprobados:
        # Todavia falta aprobar otro Detalle: eso NO es PROC-REP-230 =
        # "No" -ese resultado significa que un Detalle fue RECHAZADO
        # (fuera de scope, EXC-REP-005), no "falta controlar otro". No
        # se registra la decision hasta que de verdad se tome.
        return nueva_orden

    return registrar_paso(
        nueva_orden,
        process_id="PROC-REP-230",
        accion="TODOS_LOS_DETALLES_APROBADOS",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion="Si",
    )


def calcular_puntaje(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-245: consolida el puntaje total de la Orden.

    NO acredita el puntaje de cada Detalle por primera vez: ese puntaje
    ya existe desde que ESE Detalle fue aprobado en el control tecnico
    (PROC-REP-220, BR-REP-009), y ``OrdenReparacion.puntaje_total`` ya
    lo refleja -es un computed field que suma los Detalles con control
    APROBADO, incluso antes de que la Orden entera complete su
    control-. Este
    service solo registra que la consolidacion final ocurrio, llamado
    unicamente cuando el control tecnico completo de la Orden ya
    termino (``application.cierre.aprobar_control``), justo antes de
    ``marcar_reparacion_lista``. No persiste ningun total propio.

    La distribucion del puntaje entre varios tecnicos sigue pendiente en
    V1.3 y no se asume aqui.
    """
    aprobados = [
        detalle
        for detalle in orden.reparaciones_detail
        if detalle.control_estado is EstadoControl.APROBADO
    ]
    if not aprobados:
        raise PrecondicionInvalidaError(
            "No hay Detalles aprobados a los que calcular puntaje."
        )

    return registrar_paso(
        orden,
        process_id="PROC-REP-245",
        accion="CONSOLIDAR_PUNTAJE",
        fecha=fecha,
        observacion=str(orden.puntaje_total),
    )
