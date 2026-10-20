"""Detalles de Reparacion: definicion, factibilidad, control y puntaje.

Nodos cubiertos: PROC-REP-045/070 y PROC-REP-068/075 (agregar Detalles),
PROC-REP-080/090 (factibilidad), PROC-REP-220/230 (control tecnico) y
PROC-REP-245 (puntaje).

Agregar un Detalle y finalizar la definicion son intenciones distintas:
los ``definir_reparacion_detail*`` solo agregan; la definicion se cierra
con ``exigir_definicion_finalizable`` + factibilidad (``application``), y
queda cerrada desde que se valida la factibilidad (PROC-REP-080,
``definicion_finalizada``).

Features: FEAT-REP-002, FEAT-REP-003, FEAT-REP-006, FEAT-REP-007 (el
precio snapshot se registra al crear el Detalle).
"""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from app.domain.garantia import (
    GARANTIA_SIN_CHECKIN_DIAS,
    garantia_sugerida,
)
from app.domain.models import (
    NOMBRE_TIPO_REPARACION_OTROS,
    TIPO_REPARACION_OTROS,
    CondicionReparacionDetail,
    EstadoControl,
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoWorkflow,
    Insumo,
    OrdenReparacion,
    OrigenOrden,
    RegistroControlTecnico,
    ReparacionDetail,
    ResultadoControl,
    RolUsuario,
    TipoReparacion,
    TipoReparacionInsumos,
    Usuario,
)
from app.domain.politicas import politica_de

from .autorizacion import validar_actor
from .autorizacion_cliente import (
    NODO_ESPERA_AUTORIZACION,
    es_trabajable,
    pendiente_de_autorizacion,
)
from .custodia import checkin_de
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .inventario import faltantes_del_detalle
from .recursos import (
    detalles_bloqueados_por_recursos,
    tiene_override_factibilidad,
)
from .revisiones import finalizada_sin_reparacion, revision_tecnica_realizada
from .workflow import registrar_paso


def definicion_finalizada(orden: OrdenReparacion) -> bool:
    """La carga de Detalles ya se cerro: la Orden paso por PROC-REP-080.

    Vale para los dos caminos de definicion (070 y 075): en ambos la
    factibilidad es lo primero que ocurre al finalizar, salvo cuando todos
    los Detalles esperan la autorizacion del cliente (CLIENTE_EXTERNO): ahi
    la Orden pasa a esperarla (PROC-REP-129) y la factibilidad llega recien
    con la autorizacion. Derivado del historial, sin flag persistido.
    """
    return any(
        paso.process_id in ("PROC-REP-080", NODO_ESPERA_AUTORIZACION)
        for paso in orden.historial
    )


def _exigir_definicion_abierta(orden: OrdenReparacion) -> None:
    if definicion_finalizada(orden):
        raise PrecondicionInvalidaError(
            "La definicion de Detalles ya fue finalizada: no se agregan "
            "mas Detalles."
        )


def exigir_definicion_finalizable(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
) -> None:
    """Precondiciones de "Finalizar definicion" (ACT-RECEP).

    Cierra la carga de Detalles de una Orden en REQUERIMIENTO (camino
    070) o EN_REVISION ya revisada (camino 075): exige al menos un
    Detalle y que la definicion siga abierta. Lo que sigue (comprobante si
    corresponde, factibilidad, habilitacion o espera de recursos) lo
    compone la capa de aplicacion reutilizando los services existentes.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    if orden.estado_workflow not in (
        EstadoWorkflow.REQUERIMIENTO,
        EstadoWorkflow.EN_REVISION,
    ):
        raise PrecondicionInvalidaError(
            f"Solo se finaliza la definicion de una Orden en REQUERIMIENTO "
            f"o EN_REVISION; esta en {orden.estado_workflow.value}."
        )
    _exigir_definicion_abierta(orden)
    if not orden.reparaciones_detail:
        raise PrecondicionInvalidaError(
            "No se puede finalizar la definicion sin al menos un Detalle."
        )


def es_ingreso_inicial(orden: OrdenReparacion) -> bool:
    """La Orden esta en su ingreso inicial de CLIENTE_EXTERNO (MVP v2).

    REQUERIMIENTO con la definicion abierta, en un Origen que exige la
    confirmacion fisica y la autorizacion del cliente. Ahi Recepcion
    carga los trabajos y genera el comprobante de ingreso y autorizacion,
    que confirma, finaliza y autoriza en un solo paso. Una Orden enviada a
    revision (EN_REVISION) ya no lo esta.
    """
    politica = politica_de(orden.origen)
    return (
        politica.requiere_autorizacion_cliente
        and politica.requiere_confirmacion_recepcion
        and orden.estado_workflow is EstadoWorkflow.REQUERIMIENTO
        and not definicion_finalizada(orden)
    )


def exigir_fuera_del_ingreso_inicial(
    orden: OrdenReparacion, accion: str
) -> None:
    """Rechaza un paso suelto del circuito explicito en el ingreso inicial.

    En el ingreso inicial de CLIENTE_EXTERNO, confirmar la recepcion,
    finalizar la definicion y registrar la autorizacion inicial se hacen
    juntos al generar el comprobante de ingreso y autorizacion, con sus
    validaciones (estado fisico, check-in, al menos un trabajo). Por
    separado dejarian la Orden fuera de ese recorrido. Los demas Origenes
    y los demas caminos (revision, autorizaciones posteriores) no cambian.
    """
    if es_ingreso_inicial(orden):
        raise PrecondicionInvalidaError(
            f"En el ingreso inicial de Cliente Externo no se puede {accion} "
            "por separado: se hace al generar el comprobante de ingreso y "
            "autorizacion."
        )


def faltantes_para_ingreso(orden: OrdenReparacion) -> list[str]:
    """Lo que Recepcion tiene que completar antes de generar el comprobante
    de ingreso: trabajos, estado fisico y el check-in."""
    faltan = []
    if not any(
        detalle.estado is not EstadoReparacionDetail.CANCELADO
        for detalle in orden.reparaciones_detail
    ):
        faltan.append("cargar al menos un trabajo")
    datos = orden.recepcion.datos if orden.recepcion else None
    if datos is None or not datos.estado_fisico:
        faltan.append("registrar el estado fisico del equipo")
    if datos is None or datos.checkin is None:
        faltan.append("indicar si se hizo el check-in")
    return faltan


def nombre_del_trabajo(
    detalle: ReparacionDetail, nombres_de_tipo: Mapping[str, str]
) -> str:
    """Como se nombra un Detalle: el Tipo, o "Otros: <descripcion>"."""
    if detalle.es_otros:
        return f"Otros: {detalle.descripcion or 'sin descripcion'}"
    return nombres_de_tipo.get(
        detalle.tipo_reparacion_id, detalle.tipo_reparacion_id
    )


def tipo_reparacion_otros(precio: Decimal) -> TipoReparacion:
    """El tipo del sistema para una reparacion no tipificada.

    No es una fila del catalogo: lleva el precio manual que carga
    Recepcion, puntaje 0 y, sin check-in, la garantia reducida. No prevé
    insumos ni restringe estaciones.
    """
    return TipoReparacion(
        id=TIPO_REPARACION_OTROS,
        nombre=NOMBRE_TIPO_REPARACION_OTROS,
        precio=precio,
        puntaje=0,
        garantia_dias=GARANTIA_SIN_CHECKIN_DIAS,
    )


def _descripcion_para(
    tipo_reparacion: TipoReparacion, descripcion: str | None
) -> str | None:
    """La descripcion es obligatoria en "Otros" y no existe en los demas."""
    texto = (descripcion or "").strip() or None
    if tipo_reparacion.id == TIPO_REPARACION_OTROS:
        if texto is None:
            raise PrecondicionInvalidaError(
                "Una reparacion «Otros» necesita la descripcion de lo que "
                "se repara."
            )
        return texto
    if texto is not None:
        raise PrecondicionInvalidaError(
            "La descripcion manual es solo para una reparacion «Otros»."
        )
    return None


def definir_reparacion_detail(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    tipo_reparacion: TipoReparacion,
    usuario: Usuario,
    fecha: datetime,
    observaciones: str | None = None,
    descripcion: str | None = None,
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

    Cubre el camino "los Detalles se conocen desde el ingreso". Solo
    AGREGA el Detalle: no genera comprobante, no valida factibilidad ni
    habilita (eso es "Finalizar definicion"). La revision tecnica previa
    (PROC-REP-075) es ``definir_reparacion_detail_luego_revision``; la
    redefinicion de un Detalle existente (PROC-REP-127) vive en
    ``services.redefinicion``.

    Una garantia RMA nunca pasa por aqui: su revision tecnica es
    obligatoria (BR-REP-019) y define sus Detalles por PROC-REP-075.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    if orden.estado_workflow is not EstadoWorkflow.REQUERIMIENTO:
        raise PrecondicionInvalidaError(
            f"Solo se definen Detalles sobre una Orden en REQUERIMIENTO; "
            f"esta en {orden.estado_workflow.value}."
        )
    if orden.origen is OrigenOrden.RMA_GARANTIA_REPARACION:
        raise PrecondicionInvalidaError(
            "Una garantia RMA define sus Detalles luego de la revision "
            "tecnica obligatoria (PROC-REP-075, BR-REP-019)."
        )
    _exigir_definicion_abierta(orden)
    if not tipo_reparacion.activo:
        raise PrecondicionInvalidaError(
            f"El Tipo de Reparacion {tipo_reparacion.id} no esta activo."
        )
    if any(detalle.id == detalle_id for detalle in orden.reparaciones_detail):
        raise PrecondicionInvalidaError(
            f"La Orden ya tiene un Detalle con id {detalle_id}."
        )
    descripcion = _descripcion_para(tipo_reparacion, descripcion)

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
            detalle_origen_id=None,
            checkin=checkin_de(orden),
            descripcion=descripcion,
        )
    )
    return nueva_orden


def _detalle_con_snapshot(
    *,
    detalle_id: str,
    tipo_reparacion: TipoReparacion,
    observaciones: str | None,
    detalle_origen_id: str | None,
    checkin: bool | None = None,
    descripcion: str | None = None,
) -> ReparacionDetail:
    """Detalle DEFINIDO con el snapshot del Tipo (BR-REP-015).

    Compartido por PROC-REP-070 y PROC-REP-075: mismo snapshot, nodos
    funcionales distintos. La garantia es la sugerida por el check-in del
    ingreso (o la del Tipo si no hay check-in): sugerida y definitiva
    nacen iguales.
    """
    dias = garantia_sugerida(checkin, tipo_reparacion.garantia_dias)
    return ReparacionDetail(
        id=detalle_id,
        tipo_reparacion_id=tipo_reparacion.id,
        descripcion=descripcion,
        precio=tipo_reparacion.precio,
        puntaje=tipo_reparacion.puntaje,
        garantia_dias=dias,
        garantia_dias_sugerida=dias,
        estado=EstadoReparacionDetail.DEFINIDO,
        control_estado=EstadoControl.PENDIENTE,
        observaciones=observaciones,
        detalle_origen_id=detalle_origen_id,
    )


def reaplicar_garantia_sugerida(orden: OrdenReparacion) -> OrdenReparacion:
    """Tras corregir el check-in: actualiza la garantia sugerida.

    En los Detalles no cancelados. El plazo definitivo la sigue, salvo
    que tenga un ajuste manual (ese plazo lo decidio una persona). Sin
    check-in registrado no cambia nada.
    """
    checkin = checkin_de(orden)
    if checkin is None:
        return orden
    nueva_orden = orden.model_copy(deep=True)
    for detalle in nueva_orden.reparaciones_detail:
        if detalle.estado is EstadoReparacionDetail.CANCELADO:
            continue
        dias = garantia_sugerida(checkin, detalle.garantia_dias)
        detalle.garantia_dias_sugerida = dias
        if not detalle.ajustes_garantia:
            detalle.garantia_dias = dias
    return nueva_orden


def definir_reparacion_detail_luego_revision(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    tipo_reparacion: TipoReparacion,
    usuario: Usuario,
    fecha: datetime,
    observaciones: str | None = None,
    detalle_origen_id: str | None = None,
    descripcion: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-068 ("Si") -> PROC-REP-075 (VAR-REP-001/002).

    Recepcion define un Detalle usando el resultado de la revision
    tecnica de una Orden EN_REVISION. Mismo snapshot que PROC-REP-070,
    pero la traza es la del proceso real: NO registra PROC-REP-045 "Si"
    ni PROC-REP-070.

    PROC-REP-068 se registra una sola vez, con el primer Detalle; cada
    Detalle registra su propio PROC-REP-075 (Multi-Detalle). Solo AGREGA:
    la definicion se cierra con "Finalizar definicion". El camino "No"
    (PROC-REP-069, SIN_REPARACION) es
    ``services.revisiones.registrar_finalizacion_sin_reparacion``.

    En una garantia RMA cada Detalle referencia a uno de los Detalles
    origen de ``orden.detalles_origen_ids`` -nunca del historial-: con
    exactamente uno se usa ese; con mas de uno hay que indicarlo. No hay
    relacion 1:1: un Detalle origen puede originar mas de un Detalle.
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
    if finalizada_sin_reparacion(orden):
        raise PrecondicionInvalidaError(
            "La Orden ya finalizo SIN_REPARACION (PROC-REP-069)."
        )
    _exigir_definicion_abierta(orden)
    if not tipo_reparacion.activo:
        raise PrecondicionInvalidaError(
            f"El Tipo de Reparacion {tipo_reparacion.id} no esta activo."
        )
    if any(detalle.id == detalle_id for detalle in orden.reparaciones_detail):
        raise PrecondicionInvalidaError(
            f"La Orden ya tiene un Detalle con id {detalle_id}."
        )

    origen_del_detalle = _detalle_origen_para(orden, detalle_origen_id)
    descripcion = _descripcion_para(tipo_reparacion, descripcion)

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
            checkin=checkin_de(orden),
            descripcion=descripcion,
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


def _evaluable(orden: OrdenReparacion, detalle: ReparacionDetail) -> bool:
    """PROC-REP-080 evalua el Detalle: pendiente, de recursos, autorizado."""
    return (
        detalle.estado is EstadoReparacionDetail.DEFINIDO
        and detalle.condicion in _CONDICIONES_DE_RECURSOS
        and not pendiente_de_autorizacion(orden, detalle)
    )


def _faltantes_para_factibilidad(
    orden: OrdenReparacion,
    detalle: ReparacionDetail,
    insumos: Sequence[Insumo],
    insumos_previstos: Sequence[TipoReparacionInsumos],
    reservas_externas: Mapping[str, Decimal],
) -> list[str]:
    """La pregunta de PROC-REP-080 para UN Detalle: que insumos faltan hoy.

    Un override vigente (EXC-REP-002) la responde de antemano: nada, el
    override persiste (BR-REP-003).
    """
    if tiene_override_factibilidad(orden, detalle.id):
        return []
    return faltantes_del_detalle(
        detalle.tipo_reparacion_id,
        orden.movimientos_insumo,
        insumos,
        insumos_previstos,
        reservas_externas,
    )


def faltantes_de_detalles_bloqueados(
    orden: OrdenReparacion,
    *,
    insumos: Sequence[Insumo],
    insumos_previstos: Sequence[TipoReparacionInsumos],
    reservas_externas: Mapping[str, Decimal] | None = None,
) -> dict[str, list[str]]:
    """PROC-REP-080 como consulta, solo de los Detalles bloqueados.

    Por cada Detalle bloqueado por recursos, sus faltantes con el stock y
    las reservas actuales (lista vacia: ya tiene recursos). No modifica la
    Orden ni registra pasos: sirve para decidir si revalidar cambia algo.
    """
    ajenas = reservas_externas or {}
    detalles = {detalle.id: detalle for detalle in orden.reparaciones_detail}
    return {
        detalle_id: _faltantes_para_factibilidad(
            orden, detalles[detalle_id], insumos, insumos_previstos, ajenas
        )
        for detalle_id in detalles_bloqueados_por_recursos(orden)
    }


def hay_detalles_para_factibilidad(orden: OrdenReparacion) -> bool:
    """Algun Detalle puede evaluarse en PROC-REP-080.

    False cuando los unicos Detalles por evaluar esperan la autorizacion
    del cliente (BR-REP-028): no se evalua su factibilidad hasta que se
    autoricen.
    """
    return any(
        _evaluable(orden, detalle) for detalle in orden.reparaciones_detail
    )


def validar_factibilidad_detalles(
    orden: OrdenReparacion,
    *,
    insumos: Sequence[Insumo],
    insumos_previstos: Sequence[TipoReparacionInsumos],
    fecha: datetime,
    reservas_externas: Mapping[str, Decimal] | None = None,
    detalle_ids: Collection[str] | None = None,
    registrar_faltantes: bool = True,
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

    Un Detalle pendiente de autorizacion del cliente (BR-REP-028) no se
    evalua ni cuenta como trabajable. ``detalle_ids`` limita la evaluacion
    a esos Detalles -los recien autorizados-: los demas conservan su
    condicion. ``registrar_faltantes=False`` es para una Orden ya
    habilitada: 090 no lleva a 100 sino de vuelta a PROC-REP-211, que
    compone el caller (V1.4).
    """
    ajenas = reservas_externas or {}

    if not orden.reparaciones_detail:
        raise PrecondicionInvalidaError(
            "No se puede validar factibilidad sin Detalles de Reparacion."
        )

    nueva_orden = orden.model_copy(deep=True)

    faltantes_por_detalle: dict[str, list[str]] = {}
    for detalle in nueva_orden.reparaciones_detail:
        if not _evaluable(nueva_orden, detalle):
            continue
        if detalle_ids is not None and detalle.id not in detalle_ids:
            continue
        faltantes = _faltantes_para_factibilidad(
            nueva_orden, detalle, insumos, insumos_previstos, ajenas
        )
        if faltantes:
            detalle.condicion = (
                CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
            )
            faltantes_por_detalle[detalle.id] = faltantes
        else:
            detalle.condicion = CondicionReparacionDetail.SIN_BLOQUEO

    hay_trabajable = any(
        es_trabajable(nueva_orden, detalle)
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
    if hay_trabajable or not registrar_faltantes:
        return nueva_orden, hay_trabajable

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


_TERMINALES = (
    EstadoReparacionDetail.COMPLETO,
    EstadoReparacionDetail.CANCELADO,
)


def control_tecnico_completo(orden: OrdenReparacion) -> bool:
    """Todos los Detalles vigentes tienen el control APROBADO.

    Los CANCELADO no se controlan (no se hicieron). Hace falta al menos un
    Detalle aprobado: una Orden toda cancelada no llega a REPARACION_LISTA.
    """
    vigentes = [
        detalle
        for detalle in orden.reparaciones_detail
        if detalle.estado is not EstadoReparacionDetail.CANCELADO
    ]
    return bool(vigentes) and all(
        detalle.control_estado is EstadoControl.APROBADO
        for detalle in vigentes
    )


def pendiente_de_retrabajo(detalle: ReparacionDetail) -> bool:
    """El Detalle fue reabierto por un control rechazado y no se rehizo.

    Se deriva de ``controles`` (el ultimo registrado es un rechazo) y del
    estado: deja de estar pendiente cuando el retrabajo termina (COMPLETO),
    aunque su nuevo control todavia no se haya hecho.
    """
    return (
        detalle.estado
        in (
            EstadoReparacionDetail.DEFINIDO,
            EstadoReparacionDetail.EN_PROGRESO,
        )
        and bool(detalle.controles)
        and detalle.controles[-1].resultado is ResultadoControl.RECHAZADO
    )


def _exigir_orden_en_control(orden: OrdenReparacion) -> None:
    """PROC-REP-220 se alcanza con la Orden entera terminal (BR-REP-012).

    Todos sus Detalles COMPLETO o CANCELADO y al menos uno COMPLETO, sin
    Ejecucion activa: el mismo requisito que ``resolver_situacion_orden``
    exige para clasificar ``COMPLETA``. No alcanza con que el Detalle
    puntual este COMPLETO si todavia queda otro DEFINIDO o EN_PROGRESO.
    """
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
        detalle.estado not in _TERMINALES
        for detalle in orden.reparaciones_detail
    ):
        raise PrecondicionInvalidaError(
            "El control tecnico (PROC-REP-220) solo se alcanza cuando "
            "todos los Detalles de la Orden estan terminados (COMPLETO o "
            "CANCELADO)."
        )
    if not any(
        detalle.estado is EstadoReparacionDetail.COMPLETO
        for detalle in orden.reparaciones_detail
    ):
        raise PrecondicionInvalidaError(
            "No hay trabajo realizado que controlar: todos los Detalles "
            "estan CANCELADO."
        )


def _detalle_a_controlar(
    orden: OrdenReparacion,
    detalle_id: str,
) -> ReparacionDetail:
    """El Detalle existe, se realizo y su control sigue pendiente (E14)."""
    detalle = next(
        (d for d in orden.reparaciones_detail if d.id == detalle_id), None
    )
    if detalle is None:
        raise EntidadNoEncontradaError(
            f"La Orden no tiene el Detalle {detalle_id}"
        )
    if detalle.estado is EstadoReparacionDetail.CANCELADO:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} esta CANCELADO: no se controla."
        )
    if detalle.control_estado is EstadoControl.APROBADO:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} ya fue aprobado por "
            f"{detalle.control_usuario_id} el {detalle.control_fecha}: un "
            "control registrado no se vuelve a escribir."
        )
    return detalle


def _ultima_ejecucion_completada(
    orden: OrdenReparacion,
    detalle_id: str,
) -> str | None:
    """La Ejecucion cuyo resultado se controla ahora."""
    completadas = [
        ejecucion.id
        for ejecucion in orden.ejecuciones
        if ejecucion.reparacion_detail_id == detalle_id
        and ejecucion.estado is EstadoEjecucion.COMPLETADO
    ]
    return completadas[-1] if completadas else None


def aprobar_control_tecnico(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
    detalle_id: str | None = None,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-220 -> PROC-REP-230: Recepcion aprueba (BR-REP-008).

    PROC-REP-220 solo se alcanza con la Orden entera terminal
    (``_exigir_orden_en_control``), con o sin ``detalle_id``.

    Recepcion controla la Orden completa pero aprueba Detalle por
    Detalle (Multi-Detalle): con ``detalle_id`` aprueba unicamente ese
    Detalle; sin ``detalle_id`` aprueba de una vez todos los que todavia
    tienen el control PENDIENTE. El rechazo es
    ``rechazar_control_tecnico`` (PROC-REP-235).

    E14: una aprobacion registrada no se vuelve a escribir. Aprobar un
    Detalle ya APROBADO es un conflicto, y la aprobacion en bloque no toca
    los ya aprobados. Cada aprobacion agrega un registro a
    ``ReparacionDetail.controles`` -con la Ejecucion que se controlo- y
    nunca reemplaza uno anterior: aprobar despues de un retrabajo es un
    control nuevo.

    No cambia el estado tecnico del Detalle: sigue COMPLETO. La
    aprobacion es otra dimension y vive en ``control_estado``.

    PROC-REP-230 ("todos los Detalles fueron aprobados") solo se
    registra con "Si" cuando, despues de esta aprobacion, todos los
    Detalles vigentes (no CANCELADO) quedan APROBADO. Una aprobacion
    parcial no registra PROC-REP-230: la decision todavia no se tomo. El
    caller (``application.cierre.aprobar_control``) sigue el mismo
    criterio para PROC-REP-245/240.

    PROC-REP-220 es ACT-RECEP: el control lo hace Recepcion, no el
    tecnico que ejecuto el trabajo.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)
    _exigir_orden_en_control(orden)

    if detalle_id is not None:
        _detalle_a_controlar(orden, detalle_id)
        objetivo_ids = {detalle_id}
    else:
        objetivo_ids = {
            detalle.id
            for detalle in orden.reparaciones_detail
            if detalle.estado is EstadoReparacionDetail.COMPLETO
            and detalle.control_estado is EstadoControl.PENDIENTE
        }
        if not objetivo_ids:
            raise PrecondicionInvalidaError(
                "No queda ningun Detalle con el control pendiente: un "
                "control registrado no se vuelve a escribir."
            )

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
            detalle.controles.append(
                RegistroControlTecnico(
                    resultado=ResultadoControl.APROBADO,
                    usuario_id=usuario.id,
                    fecha=fecha,
                    observaciones=observaciones,
                    ejecucion_id=_ultima_ejecucion_completada(
                        nueva_orden, detalle.id
                    ),
                )
            )

    if not control_tecnico_completo(nueva_orden):
        # Todavia falta controlar otro Detalle: eso NO es PROC-REP-230 =
        # "No" -ese resultado es un rechazo (PROC-REP-235)-. No se
        # registra la decision hasta que de verdad se tome.
        return nueva_orden

    return registrar_paso(
        nueva_orden,
        process_id="PROC-REP-230",
        accion="TODOS_LOS_DETALLES_APROBADOS",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion="Si",
    )


def rechazar_control_tecnico(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-220 -> 230 ("No") -> 235: Recepcion rechaza UN Detalle.

    BR-REP-008 / ACT-RECEP. Mismas precondiciones que la aprobacion (Orden
    terminal, Detalle COMPLETO con el control pendiente) mas un motivo
    obligatorio. PROC-REP-235 identifica el Detalle a retrabajar: vuelve a
    PENDIENTE (DEFINIDO) y su control vigente vuelve a PENDIENTE; el
    rechazo queda en ``controles`` con la Ejecucion rechazada. Solo se
    reabre ESE Detalle: los aprobados siguen aprobados y los demas no se
    tocan.

    No crea una Ejecucion ni reserva insumos: el retrabajo es una
    Ejecucion NUEVA que el tecnico inicia despues (PROC-REP-185, que
    vuelve a validar el stock). Las Ejecuciones y movimientos anteriores
    se conservan. Que sigue lo decide el resolver (PROC-REP-211), que
    compone el caller (``application.cierre.rechazar_control``).
    """
    validar_actor(usuario, RolUsuario.RECEPCION)
    if not motivo.strip():
        raise PrecondicionInvalidaError(
            "El rechazo del control exige un motivo (BR-REP-008)."
        )
    _exigir_orden_en_control(orden)
    _detalle_a_controlar(orden, detalle_id)

    motivo = motivo.strip()
    ejecucion_id = _ultima_ejecucion_completada(orden, detalle_id)

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-220",
        accion="REALIZAR_CONTROL_TECNICO",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=f"Rechazado: {motivo}",
    )
    nueva_orden = registrar_paso(
        nueva_orden,
        process_id="PROC-REP-230",
        accion="TODOS_LOS_DETALLES_APROBADOS",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion="No",
    )
    nueva_orden = registrar_paso(
        nueva_orden,
        process_id="PROC-REP-235",
        accion="IDENTIFICAR_DETALLES_A_RETRABAJAR",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=f"Retrabajo: {motivo}",
    )

    detalle = next(
        d for d in nueva_orden.reparaciones_detail if d.id == detalle_id
    )
    detalle.controles.append(
        RegistroControlTecnico(
            resultado=ResultadoControl.RECHAZADO,
            usuario_id=usuario.id,
            fecha=fecha,
            observaciones=motivo,
            ejecucion_id=ejecucion_id,
        )
    )
    detalle.estado = EstadoReparacionDetail.DEFINIDO
    detalle.control_estado = EstadoControl.PENDIENTE
    detalle.control_usuario_id = None
    detalle.control_fecha = None
    detalle.control_observaciones = None
    return nueva_orden


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
