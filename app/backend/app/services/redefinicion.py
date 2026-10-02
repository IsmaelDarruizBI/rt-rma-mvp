"""Revision tecnica posterior de un Detalle existente (EXC-REP-004).

    PROC-REP-211 REQUIERE_REVISION -> 125 -> 126 -> 127 -> 080

``REQUIERE_DEFINICION`` la asigna PROC-REP-200 "Requiere redefinicion"
(``services.ejecuciones``); este modulo la resuelve sobre el MISMO
Detalle:

- PROC-REP-125 (ACT-SYSTEM): la Orden queda esperando la revision. Lo
  compone ``evaluar_situacion_orden``; no toca workflow ni Detalles.
- PROC-REP-126 (ACT-TECH): el tecnico revisa UN Detalle pendiente y deja
  el resultado en el historial. No cambia Tipo ni snapshots y no abre
  una toma (no pasa por 170/172/180).
- PROC-REP-127 (ACT-RECEP): Recepcion redefine ese Detalle con una nueva
  definicion vigente; la anterior pasa a ``definiciones_anteriores``
  (BR-REP-015), tambien si se confirma el mismo Tipo. Quita la condicion
  (SIN_BLOQUEO); PROC-REP-080 decide despues si hay recursos. Un 127
  invalida los overrides anteriores del Detalle (BR-REP-003, ver
  ``services.recursos.tiene_override_factibilidad``).

El ciclo de redefinicion de un Detalle empieza en su ultimo PROC-REP-200
"Requiere redefinicion": solo un 126 posterior habilita el 127. Todo se
deriva del historial, sin flags persistidos.
"""

from datetime import datetime

from app.domain.models import (
    CondicionReparacionDetail,
    DefinicionAnteriorDetalle,
    EstadoReparacionDetail,
    OrdenReparacion,
    ReparacionDetail,
    RolUsuario,
    TipoReparacion,
    Usuario,
)

from .autorizacion import validar_actor
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .resolucion import ResultadoEvaluacionOrden, resolver_situacion_orden
from .tomas import hay_ejecucion_activa, toma_activa
from .workflow import registrar_paso

NODO_ESPERA_REVISION = "PROC-REP-125"
NODO_REVISION_DETALLE = "PROC-REP-126"
NODO_REDEFINICION = "PROC-REP-127"
# Desde donde se puede revisar o redefinir: la espera (125) o despues de
# revisar otro Detalle pendiente (126).
_NODOS_DEL_CIRCUITO = (NODO_ESPERA_REVISION, NODO_REVISION_DETALLE)
_RESULTADO_REQUIERE_REDEFINICION = "Requiere redefinicion"


def requiere_definicion(detalle: ReparacionDetail) -> bool:
    """El Detalle espera revision posterior: DEFINIDO + REQUIERE_DEFINICION."""
    return (
        detalle.estado is EstadoReparacionDetail.DEFINIDO
        and detalle.condicion is CondicionReparacionDetail.REQUIERE_DEFINICION
    )


def revision_vigente(orden: OrdenReparacion, detalle_id: str) -> bool:
    """Hay un PROC-REP-126 de ESE Detalle en su ciclo actual.

    El ciclo empieza en el ultimo PROC-REP-200 "Requiere redefinicion"
    del Detalle: una revision de un ciclo anterior (o de otro Detalle) no
    habilita PROC-REP-127.
    """
    inicio_del_ciclo = -1
    for indice, paso in enumerate(orden.historial):
        if (
            paso.process_id == "PROC-REP-200"
            and paso.reparacion_detail_id == detalle_id
            and paso.observacion == _RESULTADO_REQUIERE_REDEFINICION
        ):
            inicio_del_ciclo = indice
    return any(
        paso.process_id == NODO_REVISION_DETALLE
        and paso.reparacion_detail_id == detalle_id
        for paso in orden.historial[inicio_del_ciclo + 1 :]
    )


def marcar_pendiente_revision(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-125: Detalle(s) pendientes de revision tecnica.

    Solo desde PROC-REP-211 y solo si el resolver confirma
    ``REQUIERE_REVISION``. ACT-SYSTEM (sin usuario): no cambia
    ``estado_workflow``, no modifica Detalles y no crea ninguna revision,
    toma ni Ejecucion.
    """
    if orden.current_process != "PROC-REP-211":
        raise PrecondicionInvalidaError(
            f"PROC-REP-125 se alcanza desde PROC-REP-211; la Orden esta en "
            f"{orden.current_process}."
        )
    situacion = resolver_situacion_orden(orden.reparaciones_detail)
    if situacion is not ResultadoEvaluacionOrden.REQUIERE_REVISION:
        raise PrecondicionInvalidaError(
            f"La Orden no requiere revision ({situacion.value})."
        )
    return registrar_paso(
        orden,
        process_id=NODO_ESPERA_REVISION,
        accion="DETALLES_PENDIENTES_DE_REVISION",
        fecha=fecha,
        observacion=ResultadoEvaluacionOrden.REQUIERE_REVISION.value,
    )


def _detalle_pendiente(
    orden: OrdenReparacion,
    detalle_id: str,
) -> ReparacionDetail:
    detalle = next(
        (d for d in orden.reparaciones_detail if d.id == detalle_id), None
    )
    if detalle is None:
        raise EntidadNoEncontradaError(
            f"La Orden {orden.id} no tiene el Detalle {detalle_id}."
        )
    if not requiere_definicion(detalle):
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} no requiere redefinicion "
            f"({detalle.estado.value} / {detalle.condicion.value})."
        )
    return detalle


def _exigir_circuito_de_revision(orden: OrdenReparacion) -> None:
    if orden.current_process not in _NODOS_DEL_CIRCUITO:
        raise PrecondicionInvalidaError(
            f"La revision posterior se hace desde {NODO_ESPERA_REVISION}; "
            f"la Orden esta en {orden.current_process}."
        )


def revisar_detalle_pendiente(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    resultado: str,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-126: el tecnico revisa UN Detalle pendiente.

    Exige la Orden en el circuito de revision (125, o 126 de otro
    Detalle), el Detalle DEFINIDO + REQUIERE_DEFINICION, ninguna toma ni
    Ejecucion activa y un resultado no vacio. Registra usuario, fecha,
    Detalle y resultado; no modifica Tipo, snapshots ni condicion.
    """
    validar_actor(usuario, RolUsuario.TECNICO)
    _exigir_circuito_de_revision(orden)
    _detalle_pendiente(orden, detalle_id)
    if toma_activa(orden) is not None:
        raise PrecondicionInvalidaError(
            "La Orden tiene una toma activa: la revision posterior se "
            "hace sin toma."
        )
    if hay_ejecucion_activa(orden):
        raise PrecondicionInvalidaError("La Orden tiene una Ejecucion activa.")
    if not resultado.strip():
        raise PrecondicionInvalidaError(
            "El resultado de la revision tecnica no puede estar vacio."
        )

    return registrar_paso(
        orden,
        process_id=NODO_REVISION_DETALLE,
        accion="REVISAR_DETALLE_PENDIENTE",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=resultado.strip(),
    )


def redefinir_detalle(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    tipo_reparacion: TipoReparacion,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-127: Recepcion redefine el MISMO Detalle.

    Exige un PROC-REP-126 de ese Detalle en su ciclo actual
    (``revision_vigente``), un Tipo activo y la Orden en el circuito de
    revision. Conserva ``id``, ``detalle_origen_id``, Ejecuciones e
    historial; pasa la definicion vigente a ``definiciones_anteriores`` y
    toma el snapshot del Tipo elegido (BR-REP-015), aunque sea el mismo.
    Deja la condicion en SIN_BLOQUEO: PROC-REP-080 la reevalua. No
    encadena 080: eso es del comando de aplicacion.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)
    _exigir_circuito_de_revision(orden)
    detalle = _detalle_pendiente(orden, detalle_id)
    if not revision_vigente(orden, detalle_id):
        raise PrecondicionInvalidaError(
            f"Falta la revision tecnica (PROC-REP-126) del Detalle "
            f"{detalle_id} en su ciclo de redefinicion actual."
        )
    if not tipo_reparacion.activo:
        raise PrecondicionInvalidaError(
            f"El Tipo de Reparacion {tipo_reparacion.id} no esta activo."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id=NODO_REDEFINICION,
        accion="REDEFINIR_DETALLE",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=(
            f"Tipo {detalle.tipo_reparacion_id} -> {tipo_reparacion.id}; "
            f"precio {detalle.precio} -> {tipo_reparacion.precio}"
        ),
    )
    redefinido = next(
        d for d in nueva_orden.reparaciones_detail if d.id == detalle_id
    )
    redefinido.definiciones_anteriores.append(
        DefinicionAnteriorDetalle(
            tipo_reparacion_id=redefinido.tipo_reparacion_id,
            precio=redefinido.precio,
            puntaje=redefinido.puntaje,
            garantia_dias=redefinido.garantia_dias,
            reemplazada_en=fecha,
            usuario_id=usuario.id,
        )
    )
    redefinido.tipo_reparacion_id = tipo_reparacion.id
    redefinido.precio = tipo_reparacion.precio
    redefinido.puntaje = tipo_reparacion.puntaje
    redefinido.garantia_dias = tipo_reparacion.garantia_dias
    redefinido.condicion = CondicionReparacionDetail.SIN_BLOQUEO
    return nueva_orden
