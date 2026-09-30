"""Toma de la Orden y seleccion del Detalle a trabajar.

Nodos cubiertos: PROC-REP-172 (validar estacion), PROC-REP-180 (tomar
Orden), PROC-REP-181 (seleccionar Detalle) y PROC-REP-174 (compatibilidad
del Detalle seleccionado).

Reglas: BR-REP-011 (compatibilidad de estacion), BR-REP-018 (una sola
toma activa por Orden) y BR-REP-007 (una sola Ejecucion activa).
Feature: FEAT-REP-004.
"""

from collections.abc import Sequence
from datetime import datetime

from app.domain.models import (
    EstacionTrabajo,
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    OrdenReparacion,
    RolUsuario,
    TipoReparacionEstacion,
    TomaOrden,
    Usuario,
)

from .autorizacion import actor_valido, validar_actor
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .identificadores import nuevo_id
from .workflow import registrar_paso


def toma_activa(orden: OrdenReparacion) -> TomaOrden | None:
    """La toma/participacion activa de la Orden, si existe."""
    for toma in orden.tomas:
        if toma.estado is EstadoTomaOrden.ACTIVA:
            return toma
    return None


def hay_ejecucion_activa(orden: OrdenReparacion) -> bool:
    """True si la Orden tiene una Ejecucion en curso (BR-REP-007)."""
    return any(
        ejecucion.estado is EstadoEjecucion.EN_PROGRESO
        for ejecucion in orden.ejecuciones
    )


def estacion_habilitada_para(
    tipo_reparacion_id: str,
    estacion_id: str,
    compatibilidades: Sequence[TipoReparacionEstacion],
) -> bool:
    """True si esa Estacion puede realizar ese Tipo de Reparacion."""
    return any(
        compatibilidad.tipo_reparacion_id == tipo_reparacion_id
        and compatibilidad.estacion_id == estacion_id
        for compatibilidad in compatibilidades
    )


def buscar_detalle(orden: OrdenReparacion, detalle_id: str):
    """Resuelve un Detalle de la Orden o falla explicitamente."""
    for detalle in orden.reparaciones_detail:
        if detalle.id == detalle_id:
            return detalle
    raise EntidadNoEncontradaError(
        f"La Orden no tiene el Detalle {detalle_id}"
    )


def validar_estacion_trabajo(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    estacion_id: str,
    estaciones: Sequence[EstacionTrabajo],
    compatibilidades: Sequence[TipoReparacionEstacion],
    fecha: datetime,
) -> tuple[OrdenReparacion, bool]:
    """PROC-REP-172: valida sesion, estacion y compatibilidad agregada.

    BR-REP-011 (alcance A). Comprueba, en el orden conceptual del nodo:
    usuario activo y tecnico, estacion existente y operativa, que no
    exista Ejecucion activa (BR-REP-007) ni toma activa (BR-REP-018), y
    que al menos un Detalle trabajable sea compatible con la Estacion -no
    hace falta que todos lo sean-.

    El MVP no modela una entidad Sesion: ``Usuario.activo`` es la
    aproximacion a "sesion valida". No existe override a nivel Orden en
    ninguno de estos casos.
    """
    if orden.estado_workflow is not EstadoWorkflow.EN_COLA:
        motivo = f"La Orden no esta EN_COLA ({orden.estado_workflow.value})"
        return _registrar_validacion_estacion(orden, fecha, usuario, motivo)

    if not actor_valido(usuario, RolUsuario.TECNICO):
        motivo = (
            f"El usuario {usuario.id} no puede operar como ACT-TECH "
            f"(activo={usuario.activo}, rol={usuario.rol.value})"
        )
        return _registrar_validacion_estacion(orden, fecha, usuario, motivo)

    estacion = next((e for e in estaciones if e.id == estacion_id), None)
    if estacion is None:
        motivo = f"La estacion {estacion_id} no esta configurada"
        return _registrar_validacion_estacion(orden, fecha, usuario, motivo)

    if not estacion.activa:
        motivo = f"La estacion {estacion_id} no esta operativa"
        return _registrar_validacion_estacion(orden, fecha, usuario, motivo)

    if hay_ejecucion_activa(orden):
        motivo = "La Orden ya tiene una Ejecucion activa"
        return _registrar_validacion_estacion(orden, fecha, usuario, motivo)

    if toma_activa(orden) is not None:
        motivo = "La Orden ya esta tomada por otro tecnico"
        return _registrar_validacion_estacion(orden, fecha, usuario, motivo)

    trabajables = [
        detalle
        for detalle in orden.reparaciones_detail
        if detalle.estado is EstadoReparacionDetail.DEFINIDO
    ]
    if not trabajables:
        motivo = "La Orden no tiene ningun Detalle trabajable"
        return _registrar_validacion_estacion(orden, fecha, usuario, motivo)

    if not any(
        estacion_habilitada_para(
            detalle.tipo_reparacion_id, estacion_id, compatibilidades
        )
        for detalle in trabajables
    ):
        motivo = (
            f"Ningun Detalle trabajable es compatible con {estacion_id}"
        )
        return _registrar_validacion_estacion(orden, fecha, usuario, motivo)

    return _registrar_validacion_estacion(orden, fecha, usuario, None)


def _registrar_validacion_estacion(
    orden: OrdenReparacion,
    fecha: datetime,
    usuario: Usuario,
    motivo_rechazo: str | None,
) -> tuple[OrdenReparacion, bool]:
    """Registra PROC-REP-172 con su resultado y lo devuelve."""
    valida = motivo_rechazo is None
    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-172",
        accion="VALIDAR_ESTACION_TRABAJO",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion="Valida y compatible" if valida else motivo_rechazo,
    )
    return nueva_orden, valida


def tomar_orden(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    estacion_id: str,
    fecha: datetime,
    toma_id: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-180: el tecnico toma la Orden completa (BR-REP-018).

    Abre una participacion activa (Orden + tecnico + estacion + inicio).
    Como maximo UNA por Orden en simultaneo. Tomar la Orden no inicia
    ninguna Ejecucion: eso ocurre recien en PROC-REP-185.
    """
    validar_actor(usuario, RolUsuario.TECNICO)

    if orden.estado_workflow is not EstadoWorkflow.EN_COLA:
        raise PrecondicionInvalidaError(
            f"Solo se toma una Orden EN_COLA; "
            f"esta en {orden.estado_workflow.value}."
        )
    if toma_activa(orden) is not None:
        raise PrecondicionInvalidaError(
            "La Orden ya tiene una toma activa (BR-REP-018)."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-180",
        accion="TOMAR_ORDEN",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=estacion_id,
    )
    nueva_orden.tomas.append(
        TomaOrden(
            id=toma_id or nuevo_id("TOM"),
            usuario_id=usuario.id,
            estacion_id=estacion_id,
            estado=EstadoTomaOrden.ACTIVA,
            inicio=fecha,
        )
    )
    return nueva_orden


def seleccionar_detalle(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-181: el tecnico elige que Detalle trabajar ahora.

    La seleccion es una accion de workflow, no un estado: no se persiste
    ningun ``detalle_seleccionado``. El ``detalle_id`` lo usan las
    operaciones siguientes (PROC-REP-174 y PROC-REP-185).
    """
    validar_actor(usuario, RolUsuario.TECNICO)

    detalle = buscar_detalle(orden, detalle_id)
    if detalle.estado is not EstadoReparacionDetail.DEFINIDO:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} no es trabajable "
            f"(estado {detalle.estado.value})."
        )
    if toma_activa(orden) is None:
        raise PrecondicionInvalidaError(
            "Hay que tomar la Orden antes de seleccionar un Detalle."
        )

    return registrar_paso(
        orden,
        process_id="PROC-REP-181",
        accion="SELECCIONAR_DETALLE",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
    )


def liberar_orden(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-213: el tecnico libera la Orden sin terminarla.

    BR-REP-018 / PROC-REP-212 ("No"): con la toma activa todavia hay al
    menos un Detalle trabajable -si no, ``evaluar_situacion_orden`` ya la
    habria cerrado sola-, pero el tecnico elige no seguir ahora. Cierra
    la participacion activa (fecha de fin) y devuelve la Orden a
    EN_COLA, disponible para que el mismo u otro tecnico la tome de
    nuevo. Nunca se sobrescribe el historial de participaciones
    anteriores.
    """
    validar_actor(usuario, RolUsuario.TECNICO)

    toma = toma_activa(orden)
    if toma is None:
        raise PrecondicionInvalidaError(
            "La Orden no tiene una toma activa para liberar."
        )
    if hay_ejecucion_activa(orden):
        raise PrecondicionInvalidaError(
            "No se puede liberar la Orden con una Ejecucion activa."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-213",
        accion="LIBERAR_ORDEN",
        fecha=fecha,
        usuario_id=usuario.id,
    )
    for toma_de_la_orden in nueva_orden.tomas:
        if toma_de_la_orden.estado is EstadoTomaOrden.ACTIVA:
            toma_de_la_orden.estado = EstadoTomaOrden.CERRADA
            toma_de_la_orden.fin = fecha
    nueva_orden.estado_workflow = EstadoWorkflow.EN_COLA
    return nueva_orden


def validar_compatibilidad_detalle(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    compatibilidades: Sequence[TipoReparacionEstacion],
    fecha: datetime,
) -> tuple[OrdenReparacion, bool]:
    """PROC-REP-174: la Estacion sirve para el Detalle seleccionado.

    BR-REP-011. Evalua la Estacion de la toma activa contra el Tipo de
    Reparacion de ESE Detalle, no contra toda la Orden.

    Los caminos de incompatibilidad y override (PROC-REP-176/178/179) no
    estan implementados.
    """
    detalle = buscar_detalle(orden, detalle_id)
    toma = toma_activa(orden)
    if toma is None:
        raise PrecondicionInvalidaError(
            "No hay una toma activa desde la cual validar la Estacion."
        )

    compatible = estacion_habilitada_para(
        detalle.tipo_reparacion_id, toma.estacion_id, compatibilidades
    )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-174",
        accion="ESTACION_HABILITADA_PARA_DETALLE",
        fecha=fecha,
        usuario_id=toma.usuario_id,
        reparacion_detail_id=detalle_id,
        observacion="Si" if compatible else "No",
    )
    return nueva_orden, compatible
