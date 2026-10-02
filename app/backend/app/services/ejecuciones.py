"""Ejecucion de un Detalle: reserva, trabajo y registro real.

Nodos cubiertos: PROC-REP-185 (reservar insumos e iniciar Ejecucion),
PROC-REP-190 (ejecutar Detalle) y PROC-REP-200 (registrar ejecucion
real).

Reglas: BR-REP-006 (reserva real al iniciar), BR-REP-007 (una sola
Ejecucion activa por Orden) y BR-REP-004 (registro de ejecucion real).
Feature: FEAT-REP-005.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    CondicionReparacionDetail,
    EjecucionReparacion,
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoWorkflow,
    Insumo,
    InsumoUtilizado,
    MovimientoInsumo,
    OrdenReparacion,
    ReparacionDetail,
    RolUsuario,
    TipoReparacionInsumos,
    TomaOrden,
    Usuario,
)

from .autorizacion import validar_actor
from .exceptions import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    RecursoNoDisponibleError,
)
from .identificadores import nuevo_id
from .inventario import (
    crear_reserva,
    faltantes_del_detalle,
    insumos_previstos_de,
)
from .recursos import tiene_override_factibilidad
from .tomas import buscar_detalle, hay_ejecucion_activa, toma_activa
from .workflow import registrar_paso

RESULTADO_RESERVA_FALLIDA = "Reserva fallida"
RESULTADO_REQUIERE_REDEFINICION = "Requiere redefinicion"


def ejecucion_activa(orden: OrdenReparacion) -> EjecucionReparacion | None:
    """La Ejecucion en curso de la Orden, si existe (BR-REP-007)."""
    for ejecucion in orden.ejecuciones:
        if ejecucion.estado is EstadoEjecucion.EN_PROGRESO:
            return ejecucion
    return None


def reservar_insumos_e_iniciar_ejecucion(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    insumos: Sequence[Insumo],
    insumos_previstos: Sequence[TipoReparacionInsumos],
    fecha: datetime,
    reservas_externas: Mapping[str, Decimal] | None = None,
    ejecucion_id: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-185: reserva real e inicio de la Ejecucion (BR-REP-006).

    V1.3 define que este nodo hace las dos cosas. A diferencia de la
    factibilidad (PROC-REP-080), que solo consulto disponibilidad, aqui
    se reserva de verdad.

    La operacion es atomica: primero se comprueba que TODOS los insumos
    previstos alcancen y recien entonces se generan las reservas y la
    Ejecucion. Si alguno falta no queda ninguna reserva parcial.

    Las reservas se generan con ``usuario_id=None`` porque el nodo es
    ACT-SYSTEM; la trazabilidad al tecnico pasa por la Ejecucion.

    Esta funcion es el camino exitoso. La reserva fallida (PROC-REP-186,
    EXC-REP-003) la compone ``intentar_reserva_e_inicio``; aqui, sin
    override, la falta de stock solo se defiende con
    RecursoNoDisponibleError. Con override vigente de ESTE Detalle
    (ACC-REP-049, ``tiene_override_factibilidad``) reserva igual, dejando
    el disponible negativo (el stock fisico solo baja en PROC-REP-210).

    Nodo ACT-SYSTEM. El ``usuario`` recibido es el tecnico de la toma
    activa, al que se atribuye la Ejecucion que se abre aqui.

    ``reservas_externas`` (insumo_id -> cantidad) revalida contra lo
    que otras Ordenes ya reservaron: entre la factibilidad y este
    momento el insumo pudo haber sido tomado por otra Orden.
    """
    detalle, toma = _validar_precondiciones_de_la_reserva(orden, detalle_id)

    previstos = insumos_previstos_de(
        detalle.tipo_reparacion_id, insumos_previstos
    )

    # Comprobar todo antes de modificar nada. Con un override de
    # factibilidad VALIDO PARA ESTE Detalle (EXC-REP-002) la reserva se
    # genera completa aunque la disponibilidad no alcance. Sin override,
    # el camino normal de la aplicacion pasa antes por
    # ``intentar_reserva_e_inicio`` (EXC-REP-003); este error es solo la
    # defensa de bajo nivel. El override de otro Detalle no cuenta.
    if not tiene_override_factibilidad(orden, detalle_id):
        faltantes = faltantes_del_detalle(
            detalle.tipo_reparacion_id,
            orden.movimientos_insumo,
            insumos,
            insumos_previstos,
            reservas_externas,
        )
        if faltantes:
            raise RecursoNoDisponibleError(
                f"Insumos sin disponibilidad suficiente: "
                f"{', '.join(faltantes)}. No se genero ninguna reserva."
            )

    reservas: list[MovimientoInsumo] = [
        crear_reserva(
            insumo_id=previsto.insumo_id,
            reparacion_detail_id=detalle_id,
            cantidad=previsto.cantidad,
            fecha=fecha,
        )
        for previsto in previstos
    ]

    ejecucion = EjecucionReparacion(
        id=ejecucion_id or nuevo_id("EJE"),
        reparacion_detail_id=detalle_id,
        toma_orden_id=toma.id,
        usuario_id=usuario.id,
        estado=EstadoEjecucion.EN_PROGRESO,
        inicio=fecha,
    )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-185",
        accion="RESERVAR_INSUMOS_E_INICIAR_EJECUCION",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        ejecucion_id=ejecucion.id,
    )
    nueva_orden.movimientos_insumo.extend(reservas)
    nueva_orden.ejecuciones.append(ejecucion)
    buscar_detalle(
        nueva_orden, detalle_id
    ).estado = EstadoReparacionDetail.EN_PROGRESO
    nueva_orden.estado_workflow = EstadoWorkflow.EN_REPARACION

    return nueva_orden


def _validar_precondiciones_de_la_reserva(
    orden: OrdenReparacion,
    detalle_id: str,
) -> tuple[ReparacionDetail, TomaOrden]:
    """Precondiciones reales de PROC-REP-185: no son una reserva fallida.

    Un Detalle no trabajable, sin toma o con otra Ejecucion en curso es un
    error de precondicion, no el resultado "Reserva fallida".
    """
    detalle = buscar_detalle(orden, detalle_id)
    if detalle.estado is not EstadoReparacionDetail.DEFINIDO:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} no esta disponible para ejecutarse "
            f"(estado {detalle.estado.value})."
        )
    if detalle.condicion is not CondicionReparacionDetail.SIN_BLOQUEO:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} no esta disponible para ejecutarse "
            f"(condicion {detalle.condicion.value})."
        )

    toma = toma_activa(orden)
    if toma is None:
        raise PrecondicionInvalidaError(
            "Hay que tomar la Orden antes de iniciar una Ejecucion."
        )
    if hay_ejecucion_activa(orden):
        raise PrecondicionInvalidaError(
            "La Orden ya tiene una Ejecucion activa (BR-REP-007)."
        )
    return detalle, toma


def intentar_reserva_e_inicio(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    insumos: Sequence[Insumo],
    insumos_previstos: Sequence[TipoReparacionInsumos],
    fecha: datetime,
    reservas_externas: Mapping[str, Decimal] | None = None,
    ejecucion_id: str | None = None,
) -> tuple[OrdenReparacion, bool]:
    """PROC-REP-185 con sus dos resultados: exitosa o fallida (EXC-REP-003).

    Devuelve ``(orden, reserva_exitosa)``:

    - Exitosa (hay disponibilidad, o el Detalle tiene override valido,
      EXC-REP-002): delega en ``reservar_insumos_e_iniciar_ejecucion``.
    - Fallida (faltan insumos y NO hay override de ESTE Detalle): registra
      PROC-REP-185 "Reserva fallida" y PROC-REP-186. No genera reservas ni
      Ejecucion y no toca el stock; el Detalle queda DEFINIDO +
      BLOQUEADO_POR_RECURSOS. Recalcular la Orden (PROC-REP-211) es del
      caller (``evaluar_situacion_orden``).

    Las precondiciones reales (Detalle, toma, BR-REP-007) siguen lanzando
    PrecondicionInvalidaError: no se registran como reserva fallida.
    """
    detalle, _ = _validar_precondiciones_de_la_reserva(orden, detalle_id)

    faltantes: list[str] = []
    if not tiene_override_factibilidad(orden, detalle_id):
        faltantes = faltantes_del_detalle(
            detalle.tipo_reparacion_id,
            orden.movimientos_insumo,
            insumos,
            insumos_previstos,
            reservas_externas,
        )

    if not faltantes:
        nueva_orden = reservar_insumos_e_iniciar_ejecucion(
            orden,
            detalle_id=detalle_id,
            usuario=usuario,
            insumos=insumos,
            insumos_previstos=insumos_previstos,
            fecha=fecha,
            reservas_externas=reservas_externas,
            ejecucion_id=ejecucion_id,
        )
        return nueva_orden, True

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-185",
        accion="RESERVAR_INSUMOS_E_INICIAR_EJECUCION",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=RESULTADO_RESERVA_FALLIDA,
    )
    nueva_orden = registrar_reserva_fallida(
        nueva_orden, detalle_id=detalle_id, faltantes=faltantes, fecha=fecha
    )
    return nueva_orden, False


def registrar_reserva_fallida(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    faltantes: Sequence[str],
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-186: la reserva fallo, el Detalle queda bloqueado.

    BR-REP-006. Nodo ACT-SYSTEM (sin usuario). Solo se alcanza desde un
    PROC-REP-185 que ya registro "Reserva fallida" sobre ESE Detalle. El
    Detalle conserva su estado tecnico (DEFINIDO, la representacion de
    PENDIENTE) y pasa a BLOQUEADO_POR_RECURSOS. No genera movimientos, no
    crea Ejecucion, no toca el stock ni otros Detalles.
    """
    ultimo = orden.historial[-1] if orden.historial else None
    if (
        orden.current_process != "PROC-REP-185"
        or ultimo is None
        or ultimo.observacion != RESULTADO_RESERVA_FALLIDA
        or ultimo.reparacion_detail_id != detalle_id
    ):
        raise PrecondicionInvalidaError(
            "PROC-REP-186 solo se alcanza tras una reserva fallida "
            f"(PROC-REP-185) del Detalle {detalle_id}."
        )
    if not faltantes:
        raise PrecondicionInvalidaError(
            "Una reserva fallida debe indicar los insumos faltantes."
        )
    if (
        buscar_detalle(orden, detalle_id).estado
        is not EstadoReparacionDetail.DEFINIDO
    ):
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} no puede bloquearse por recursos."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-186",
        accion="REGISTRAR_RESERVA_FALLIDA",
        fecha=fecha,
        reparacion_detail_id=detalle_id,
        observacion=f"Faltantes: {', '.join(sorted(faltantes))}",
    )
    buscar_detalle(
        nueva_orden, detalle_id
    ).condicion = CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    return nueva_orden


def _validar_propiedad_de_la_ejecucion(
    orden: OrdenReparacion,
    ejecucion: EjecucionReparacion,
    usuario: Usuario,
) -> None:
    """La Ejecucion activa solo la trabaja el tecnico que la inicio.

    Comprueba las tres identidades que V1.3 mantiene unidas: la
    Ejecucion es del tecnico, la toma activa tambien, y la Ejecucion
    pertenece a esa toma.
    """
    if ejecucion.usuario_id != usuario.id:
        raise PrecondicionInvalidaError(
            f"La Ejecucion {ejecucion.id} la inicio "
            f"{ejecucion.usuario_id}: {usuario.id} no puede "
            "trabajarla. Continuarla requiere una Ejecucion nueva."
        )

    toma = toma_activa(orden)
    if toma is None:
        raise PrecondicionInvalidaError("La Orden no tiene una toma activa.")
    if toma.usuario_id != usuario.id:
        raise PrecondicionInvalidaError(
            f"La Orden esta tomada por {toma.usuario_id}, no por {usuario.id}."
        )
    if ejecucion.toma_orden_id != toma.id:
        raise PrecondicionInvalidaError(
            "La Ejecucion no pertenece a la toma activa de la Orden."
        )


def ejecutar_detalle(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-190: el tecnico trabaja sobre el Detalle.

    No crea una segunda Ejecucion: la Ejecucion ya se abrio en
    PROC-REP-185. Solo verifica que exista una activa para ese Detalle
    y deja registrado que el flujo paso por aqui.

    La Ejecucion pertenece al tecnico que la inicio: nadie mas puede
    trabajarla. Si otro tecnico continua el mismo Detalle mas adelante,
    lo hace con una Ejecucion nueva, no tomando la ajena.
    """
    validar_actor(usuario, RolUsuario.TECNICO)

    ejecucion = ejecucion_activa(orden)
    if ejecucion is None:
        raise PrecondicionInvalidaError(
            "No hay una Ejecucion activa que trabajar."
        )
    if ejecucion.reparacion_detail_id != detalle_id:
        raise PrecondicionInvalidaError(
            f"La Ejecucion activa corresponde al Detalle "
            f"{ejecucion.reparacion_detail_id}, no a {detalle_id}."
        )

    _validar_propiedad_de_la_ejecucion(orden, ejecucion, usuario)

    return registrar_paso(
        orden,
        process_id="PROC-REP-190",
        accion="EJECUTAR_DETALLE",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        ejecucion_id=ejecucion.id,
    )


def registrar_ejecucion_completada(
    orden: OrdenReparacion,
    *,
    ejecucion_id: str,
    insumos_utilizados: Sequence[InsumoUtilizado],
    usuario: Usuario,
    fecha: datetime,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-200 con resultado "Completado" (BR-REP-004).

    El tecnico confirma los trabajos realizados, los repuestos
    efectivamente utilizados y sus cantidades. La Ejecucion pasa a
    COMPLETADO y el Detalle a COMPLETO.

    ``insumos_utilizados`` es la fuente de verdad que PROC-REP-210 usa
    despues para consumir y liberar reservas.

    El resultado "Interrumpido" es ``registrar_ejecucion_interrumpida``.

    Solo puede registrarla el tecnico que inicio la Ejecucion: esta
    conserva tecnico, estacion, inicio, fin y trabajo realizado. V1.3
    admite que varios tecnicos participen del mismo Detalle en momentos
    distintos, pero cada uno con su propia Ejecucion, nunca cerrando la
    del anterior.
    """
    return _registrar_fin_ejecucion(
        orden,
        ejecucion_id=ejecucion_id,
        insumos_utilizados=insumos_utilizados,
        usuario=usuario,
        fecha=fecha,
        observaciones=observaciones,
        resultado=EstadoEjecucion.COMPLETADO,
        estado_del_detalle=EstadoReparacionDetail.COMPLETO,
        observacion_200="Completado",
    )


def registrar_ejecucion_interrumpida(
    orden: OrdenReparacion,
    *,
    ejecucion_id: str,
    insumos_utilizados: Sequence[InsumoUtilizado],
    usuario: Usuario,
    fecha: datetime,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-200 con resultado "Interrumpido" (VAR-REP-003).

    Misma validacion que ``registrar_ejecucion_completada``. La Ejecucion
    pasa a INTERRUMPIDO -terminal: conserva fin, insumos realmente
    utilizados hasta ese momento y observaciones- y el Detalle vuelve a
    DEFINIDO (la representacion tecnica de PENDIENTE), sin bloqueo.

    NO cierra la toma: el tecnico puede continuar (una Ejecucion nueva,
    con reserva nueva) o liberar la Orden con la mecanica de
    PROC-REP-212/213.
    """
    return _registrar_fin_ejecucion(
        orden,
        ejecucion_id=ejecucion_id,
        insumos_utilizados=insumos_utilizados,
        usuario=usuario,
        fecha=fecha,
        observaciones=observaciones,
        resultado=EstadoEjecucion.INTERRUMPIDO,
        estado_del_detalle=EstadoReparacionDetail.DEFINIDO,
        observacion_200="Interrumpido",
    )


def registrar_ejecucion_requiere_redefinicion(
    orden: OrdenReparacion,
    *,
    ejecucion_id: str,
    insumos_utilizados: Sequence[InsumoUtilizado],
    usuario: Usuario,
    fecha: datetime,
    motivo: str,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-200 con resultado "Requiere redefinicion" (EXC-REP-004).

    BR-REP-004: el tecnico descubre que la definicion vigente del Detalle
    ya no es valida o suficiente. Como en "Interrumpido", la Ejecucion
    pasa a INTERRUMPIDO (no hay un estado de Ejecucion nuevo) y el
    Detalle vuelve a DEFINIDO; la diferencia es la condicion:
    REQUIERE_DEFINICION en vez de SIN_BLOQUEO. Este resultado es el unico
    que ASIGNA esa condicion. El motivo es obligatorio y queda en la
    Ejecucion.

    Igual que los otros dos resultados, continua a PROC-REP-210 y 211.
    """
    if not motivo.strip():
        raise PrecondicionInvalidaError(
            "Requiere redefinicion exige un motivo (BR-REP-004)."
        )
    return _registrar_fin_ejecucion(
        orden,
        ejecucion_id=ejecucion_id,
        insumos_utilizados=insumos_utilizados,
        usuario=usuario,
        fecha=fecha,
        observaciones=observaciones,
        resultado=EstadoEjecucion.INTERRUMPIDO,
        estado_del_detalle=EstadoReparacionDetail.DEFINIDO,
        observacion_200=RESULTADO_REQUIERE_REDEFINICION,
        condicion_del_detalle=CondicionReparacionDetail.REQUIERE_DEFINICION,
        motivo_redefinicion=motivo.strip(),
    )


def _registrar_fin_ejecucion(
    orden: OrdenReparacion,
    *,
    ejecucion_id: str,
    insumos_utilizados: Sequence[InsumoUtilizado],
    usuario: Usuario,
    fecha: datetime,
    observaciones: str | None,
    resultado: EstadoEjecucion,
    estado_del_detalle: EstadoReparacionDetail,
    observacion_200: str,
    condicion_del_detalle: CondicionReparacionDetail | None = None,
    motivo_redefinicion: str | None = None,
) -> OrdenReparacion:
    """Cierre de una Ejecucion en PROC-REP-200, comun a sus tres resultados.

    ``condicion_del_detalle`` en ``None`` deja la condicion como estaba
    (Completado e Interrumpido); "Requiere redefinicion" la fija.
    """
    validar_actor(usuario, RolUsuario.TECNICO)

    ejecucion = next(
        (e for e in orden.ejecuciones if e.id == ejecucion_id),
        None,
    )
    if ejecucion is None:
        raise EntidadNoEncontradaError(
            f"La Orden no tiene la Ejecucion {ejecucion_id}"
        )
    if ejecucion.estado is not EstadoEjecucion.EN_PROGRESO:
        raise PrecondicionInvalidaError(
            f"La Ejecucion {ejecucion_id} ya esta {ejecucion.estado.value}."
        )

    _validar_propiedad_de_la_ejecucion(orden, ejecucion, usuario)

    detalle_id = ejecucion.reparacion_detail_id

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-200",
        accion="REGISTRAR_EJECUCION_REAL",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        ejecucion_id=ejecucion_id,
        observacion=observacion_200,
    )

    nueva_ejecucion = next(
        e for e in nueva_orden.ejecuciones if e.id == ejecucion_id
    )
    nueva_ejecucion.estado = resultado
    nueva_ejecucion.fin = fecha
    nueva_ejecucion.insumos_utilizados = [
        utilizado.model_copy(deep=True) for utilizado in insumos_utilizados
    ]
    nueva_ejecucion.observaciones = observaciones
    nueva_ejecucion.motivo_redefinicion = motivo_redefinicion

    detalle = buscar_detalle(nueva_orden, detalle_id)
    detalle.estado = estado_del_detalle
    if condicion_del_detalle is not None:
        detalle.condicion = condicion_del_detalle

    return nueva_orden
