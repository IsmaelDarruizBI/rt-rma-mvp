"""Ciclo de vida de la Orden de Reparacion.

Nodos cubiertos: PROC-REP-010/030/035/040 (ingreso y creacion),
PROC-REP-140 (habilitar), PROC-REP-150 (prioridad), PROC-REP-170 (cola),
PROC-REP-211 (evaluar situacion), PROC-REP-240 (reparacion lista),
PROC-REP-250/260 (notificar) y PROC-REP-270 (entrega).

Features: FEAT-REP-001, FEAT-REP-003, FEAT-REP-004, FEAT-REP-006,
FEAT-REP-008.

Todos los services devuelven una Orden nueva; la recibida nunca se
modifica.
"""

from collections.abc import Sequence
from datetime import datetime

from app.domain.models import (
    Cliente,
    DocumentosOrden,
    Equipo,
    EstadoControl,
    EstadoEjecucion,
    EstadoTomaOrden,
    EstadoWorkflow,
    OrdenReparacion,
    OrigenOrden,
    ResumenPago,
    RolUsuario,
    Usuario,
)

from .autorizacion import validar_actor, validar_alguno_de
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .inventario import hay_reservas_activas
from .pagos import condicion_entrega_cumplida
from .recursos import marcar_pendiente_recursos, override_listo_para_habilitar
from .redefinicion import marcar_pendiente_revision
from .resolucion import ResultadoEvaluacionOrden, resolver_situacion_orden
from .revisiones import finalizada_sin_reparacion, lista_para_cierre
from .workflow import registrar_paso

# Nodos que PROC-REP V1.3 declara con ``actores_alternativos``:
# actores equivalentes, sin jerarquia entre ellos.
ROLES_PRIORIZACION = (
    RolUsuario.COORDINADOR_RMA,
    RolUsuario.RECEPCION,
)

ROLES_ENTREGA = (
    RolUsuario.ADMINISTRADOR,
    RolUsuario.RECEPCION,
)

# Resultados de BR-REP-012 que cierran la toma activa (BR-REP-018): no queda
# ningun Detalle trabajable ni en ejecucion. COMPLETA y TODO_CANCELADO; y
# PENDIENTE_RECURSOS (PROC-REP-211 caso e) y REQUIERE_REVISION (caso f),
# donde ademas la Orden pasa a esperar en PROC-REP-120 / PROC-REP-125. Los
# demas (ABIERTA_TRABAJABLE, EN_EJECUCION) preservan la toma: si continuar
# o liberar lo resuelve PROC-REP-212/213.
_RESULTADOS_QUE_CIERRAN_LA_TOMA = (
    ResultadoEvaluacionOrden.COMPLETA,
    ResultadoEvaluacionOrden.TODO_CANCELADO,
    ResultadoEvaluacionOrden.PENDIENTE_RECURSOS,
    ResultadoEvaluacionOrden.REQUIERE_REVISION,
)


def crear_orden_cliente_externo(
    *,
    orden_id: str,
    cliente: Cliente,
    equipo: Equipo,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-010 -> PROC-REP-030 -> PROC-REP-040 (FEAT-REP-001).

    La Orden nace en REQUERIMIENTO con cero Detalles (BR-REP-013): el
    estado inicial es un hito de workflow fijado por este evento, no
    algo que decida el resolver tecnico.

    EVT-REP-001 es el evento que dispara el proceso, no una accion: no
    se registra en el historial.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    orden = OrdenReparacion(
        id=orden_id,
        origen=OrigenOrden.CLIENTE_EXTERNO,
        estado_workflow=EstadoWorkflow.REQUERIMIENTO,
        current_process="PROC-REP-010",
        cliente=cliente,
        equipo=equipo,
        resumen_pago=ResumenPago(),
        documentos=DocumentosOrden(),
        created_at=fecha,
        updated_at=fecha,
    )

    orden = registrar_paso(
        orden,
        process_id="PROC-REP-010",
        accion="IDENTIFICAR_ORIGEN",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=OrigenOrden.CLIENTE_EXTERNO.value,
    )
    orden = registrar_paso(
        orden,
        process_id="PROC-REP-030",
        accion="REGISTRAR_CLIENTE_Y_EQUIPO",
        fecha=fecha,
        usuario_id=usuario.id,
    )
    return registrar_paso(
        orden,
        process_id="PROC-REP-040",
        accion="CREAR_ORDEN",
        fecha=fecha,
        usuario_id=usuario.id,
    )


def crear_orden_rt_interno(
    *,
    orden_id: str,
    equipo: Equipo,
    referencia_rt: str,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-010 -> PROC-REP-020 -> PROC-REP-040 (HP-REP-002).

    Origen RT_INTERNO: no hay Cliente (BR-REP-016 / politica RT), el
    equipo es de Rosario Tecno. PROC-REP-020 sustituye a PROC-REP-030
    -no se registra un cliente, se recibe el contexto del equipo desde
    Gestion RT-; ``referencia_rt`` es ese contexto minimo.

    PROC-REP-020 es ACT-SYSTEM: no lo ejecuta una persona, asi que no
    recibe Usuario y el historial queda sin actor humano.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    orden = OrdenReparacion(
        id=orden_id,
        origen=OrigenOrden.RT_INTERNO,
        estado_workflow=EstadoWorkflow.REQUERIMIENTO,
        current_process="PROC-REP-010",
        cliente=None,
        equipo=equipo,
        referencia_rt=referencia_rt,
        resumen_pago=ResumenPago(),
        documentos=DocumentosOrden(),
        created_at=fecha,
        updated_at=fecha,
    )

    orden = registrar_paso(
        orden,
        process_id="PROC-REP-010",
        accion="IDENTIFICAR_ORIGEN",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=OrigenOrden.RT_INTERNO.value,
    )
    orden = registrar_paso(
        orden,
        process_id="PROC-REP-020",
        accion="RECIBIR_REFERENCIA_CONTEXTO_RT",
        fecha=fecha,
        observacion=referencia_rt,
    )
    return registrar_paso(
        orden,
        process_id="PROC-REP-040",
        accion="CREAR_ORDEN",
        fecha=fecha,
        usuario_id=usuario.id,
    )


def crear_orden_garantia_rma(
    *,
    orden_id: str,
    orden_origen: OrdenReparacion,
    detalle_origen_ids: Sequence[str],
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-035 -> PROC-REP-040 (HP-REP-003, BR-REP-019).

    Crea UNA NUEVA Orden de garantia RMA a partir de una Orden origen
    ENTREGADA y de uno o mas de sus Detalles (1..N): no una Orden por
    Detalle. La Orden origen no se reabre ni se modifica: solo se leen su
    Cliente y su Equipo (copiados en profundidad, sin compartir
    instancias); la Orden nueva guarda ``orden_origen_id`` y
    ``detalles_origen_ids``. No se copia historia tecnica (tomas,
    ejecuciones, movimientos, pagos, documentos, historial) ni ningun
    Tipo de Reparacion: la revision tecnica es obligatoria y los Detalles
    nuevos se definen despues (PROC-REP-075).

    No registra PROC-REP-010 ni PROC-REP-030: no es un alta nueva.

    Fuera de alcance (BR-REP-019 los deja pendientes): vigencia de la
    garantia, motivo valido, cantidad maxima de garantias.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    if orden_origen.estado_workflow is not EstadoWorkflow.ENTREGADA:
        raise PrecondicionInvalidaError(
            f"La garantia nace de una Orden ENTREGADA; "
            f"{orden_origen.id} esta en "
            f"{orden_origen.estado_workflow.value}."
        )
    if orden_origen.cliente is None:
        raise PrecondicionInvalidaError(
            f"La Orden origen {orden_origen.id} no tiene Cliente: no hay "
            f"a quien otorgarle la garantia."
        )
    if not detalle_origen_ids:
        raise PrecondicionInvalidaError(
            "La garantia exige al menos un Detalle origen."
        )
    if len(set(detalle_origen_ids)) != len(detalle_origen_ids):
        raise PrecondicionInvalidaError(
            "Los Detalles origen de la garantia no pueden repetirse."
        )
    existentes = {detalle.id for detalle in orden_origen.reparaciones_detail}
    ajenos = [d for d in detalle_origen_ids if d not in existentes]
    if ajenos:
        raise EntidadNoEncontradaError(
            f"La Orden {orden_origen.id} no tiene los Detalles "
            f"{', '.join(ajenos)}."
        )

    orden = OrdenReparacion(
        id=orden_id,
        origen=OrigenOrden.RMA_GARANTIA_REPARACION,
        estado_workflow=EstadoWorkflow.REQUERIMIENTO,
        current_process="PROC-REP-035",
        cliente=orden_origen.cliente.model_copy(deep=True),
        equipo=orden_origen.equipo.model_copy(deep=True),
        orden_origen_id=orden_origen.id,
        detalles_origen_ids=list(detalle_origen_ids),
        resumen_pago=ResumenPago(),
        documentos=DocumentosOrden(),
        created_at=fecha,
        updated_at=fecha,
    )

    orden = registrar_paso(
        orden,
        process_id="PROC-REP-035",
        accion="IDENTIFICAR_REPARACION_ORIGINAL_GARANTIA",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=(
            f"orden_origen_id={orden_origen.id}; "
            f"detalles_origen_ids={','.join(detalle_origen_ids)}"
        ),
    )
    return registrar_paso(
        orden,
        process_id="PROC-REP-040",
        accion="CREAR_ORDEN",
        fecha=fecha,
        usuario_id=usuario.id,
    )


def marcar_orden_en_revision(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-045 ("No") -> PROC-REP-055 (VAR-REP-001/002, HP-REP-003).

    En una garantia RMA es siempre el camino (revision obligatoria,
    BR-REP-019); en los demas Origenes, cuando no se trae diagnostico.
    Todavia no se conocen los Detalles: la Orden pasa a EN_REVISION, un
    hito de workflow que significa "espera o atraviesa una revision
    tecnica antes de poder definir sus Detalles". NO implica que la
    revision viva dentro de la Orden.

    Exige Orden en REQUERIMIENTO, recien creada (PROC-REP-040) y sin
    Detalles. No genera el comprobante (PROC-REP-050/060): eso lo
    compone la capa de aplicacion segun ``PoliticaOrigen``.

    PROC-REP-055 es ACT-SYSTEM: queda sin actor humano. La intencion que
    lo dispara es de Recepcion.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    if orden.estado_workflow is not EstadoWorkflow.REQUERIMIENTO:
        raise PrecondicionInvalidaError(
            f"Solo se envia a revision una Orden en REQUERIMIENTO; "
            f"esta en {orden.estado_workflow.value}."
        )
    if orden.reparaciones_detail:
        raise PrecondicionInvalidaError(
            "No se envia a revision una Orden que ya tiene Detalles."
        )
    if orden.current_process != "PROC-REP-040":
        raise PrecondicionInvalidaError(
            f"Solo se envia a revision una Orden recien creada "
            f"(PROC-REP-040); esta en {orden.current_process}."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-045",
        accion="DETALLES_CONOCIDOS",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion="No",
    )
    nueva_orden = registrar_paso(
        nueva_orden,
        process_id="PROC-REP-055",
        accion="MARCAR_ORDEN_EN_REVISION",
        fecha=fecha,
    )
    nueva_orden.estado_workflow = EstadoWorkflow.EN_REVISION
    return nueva_orden


def habilitar_orden(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-140: la Orden queda habilitada para trabajarse.

    Precondiciones del MVP: existe al menos un Detalle y la Orden viene,
    A) de PROC-REP-090 con resultado "Si" (``current_process`` es el nodo
    actual; el resultado se busca en la ultima evaluacion de 090), o
    B) de PROC-REP-130 con un override valido de un Detalle que quedo
    SIN_BLOQUEO (EXC-REP-002; no se fabrica un 090 "Si"). Es del nodo 140,
    no del Scenario: protege HP-REP-001/002/003 y VAR-REP-001/002 contra
    una invocacion directa que saltee 080/090; 100 y 110 no habilitan.
    Acepta REQUERIMIENTO, EN_REVISION, EN_REPARACION y EN_COLA (las dos
    ultimas al revalidar recursos tras PROC-REP-211 -> 120: EN_COLA si la
    reserva fallo en el primer intento tras tomar la Orden, EXC-REP-003,
    y ninguna Ejecucion llego a empezar). Aceptar el hito no relaja el
    gate: sin 090 "Si" ni 130 valido, 100/110/120 siguen sin habilitar y
    una Orden EN_COLA arbitraria tampoco. PROC-REP-100 y la rama
    "No" de PROC-REP-110 / PROC-REP-120 (EXC-REP-001) estan implementados
    fuera de esta funcion, y tambien el override (PROC-REP-110 "Si" ->
    PROC-REP-130, EXC-REP-002).

    Nodo ACT-SYSTEM: no lo ejecuta una persona, asi que no recibe
    Usuario y el historial queda sin actor humano.
    """
    if not orden.reparaciones_detail:
        raise PrecondicionInvalidaError(
            "No se puede habilitar una Orden sin Detalles de Reparacion."
        )
    if orden.estado_workflow not in (
        EstadoWorkflow.REQUERIMIENTO,
        EstadoWorkflow.EN_REVISION,
        EstadoWorkflow.EN_REPARACION,
        EstadoWorkflow.EN_COLA,
    ):
        raise PrecondicionInvalidaError(
            f"Solo se habilita una Orden en REQUERIMIENTO, EN_REVISION, "
            f"EN_REPARACION o EN_COLA (las dos ultimas al revalidar "
            f"recursos desde PROC-REP-211 -> 120); "
            f"esta en {orden.estado_workflow.value}."
        )
    if override_listo_para_habilitar(orden):
        # B) PROC-REP-130 -> 140 (EXC-REP-002): un Coordinador forzo un
        # Detalle bloqueado. No hay un 090 "Si": el historial real es
        # 090 Ninguno -> 100 -> 110 Si -> 130 -> 140.
        pass
    elif orden.current_process != "PROC-REP-090":
        raise PrecondicionInvalidaError(
            "La Orden debe superar la validacion de factibilidad "
            "(PROC-REP-080/090) o tener un override valido (PROC-REP-130) "
            "antes de habilitarse; esta en "
            f"{orden.current_process}."
        )
    else:
        # A) PROC-REP-090 con resultado "Si".
        evaluacion_090 = next(
            paso
            for paso in reversed(orden.historial)
            if paso.process_id == "PROC-REP-090"
        )
        if evaluacion_090.observacion != "Si":
            raise PrecondicionInvalidaError(
                "La Orden no puede habilitarse porque la validacion de "
                "factibilidad (PROC-REP-090) no fue aprobada: "
                f"{evaluacion_090.observacion}."
            )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-140",
        accion="HABILITAR_ORDEN",
        fecha=fecha,
    )
    nueva_orden.estado_workflow = EstadoWorkflow.HABILITADA
    return nueva_orden


def definir_prioridad(
    orden: OrdenReparacion,
    *,
    prioridad: int,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-150: se asigna la prioridad de la Orden.

    El catalogo definitivo de prioridades sigue pendiente en V1.3: aqui
    solo se valida que sea un entero no negativo.

    El nodo declara ``actores_alternativos: [ACT-RECEP]``: la
    priorizacion la puede hacer Coordinacion o Recepcion, sin
    jerarquia entre ellas.
    """
    validar_alguno_de(usuario, ROLES_PRIORIZACION)

    if prioridad < 0:
        raise PrecondicionInvalidaError(
            f"La prioridad no puede ser negativa: {prioridad}."
        )
    if orden.estado_workflow is not EstadoWorkflow.HABILITADA:
        raise PrecondicionInvalidaError(
            f"Solo se prioriza una Orden HABILITADA; "
            f"esta en {orden.estado_workflow.value}."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-150",
        accion="DEFINIR_PRIORIDAD",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=str(prioridad),
    )
    nueva_orden.prioridad = prioridad
    return nueva_orden


def ingresar_a_cola(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-170: la Orden queda disponible para ser tomada.

    Nodo ACT-SYSTEM: no lo ejecuta una persona, asi que no recibe
    Usuario y el historial queda sin actor humano.
    """
    if orden.estado_workflow is not EstadoWorkflow.HABILITADA:
        raise PrecondicionInvalidaError(
            f"Solo ingresa a la cola una Orden HABILITADA; "
            f"esta en {orden.estado_workflow.value}."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-170",
        accion="INGRESAR_A_COLA",
        fecha=fecha,
    )
    nueva_orden.estado_workflow = EstadoWorkflow.EN_COLA
    return nueva_orden


def evaluar_situacion_orden(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> tuple[OrdenReparacion, ResultadoEvaluacionOrden]:
    """PROC-REP-211: recalcula la situacion de la Orden (BR-REP-012).

    Separa clasificacion de efectos: la clasificacion la hace
    ``resolver_situacion_orden`` (funcion pura, sin excepciones para
    ningun resultado de negocio legitimo); este service solo aplica lo
    que ese resultado implica sobre la Orden -registrar el paso y, si ya
    no queda nada trabajable ni en ejecucion, cerrar la toma activa
    (BR-REP-018)-.

    Todos los resultados estan clasificados y testeados (ver
    ``tests/test_resolucion_orden.py``). Con PENDIENTE_RECURSOS (EXC-REP-001)
    cierra la toma y continua directo a PROC-REP-120 (sin 100 ni 110); con
    REQUIERE_REVISION (EXC-REP-004) cierra la toma y continua a
    PROC-REP-125. La cancelacion todavia no esta conectada.

    No cambia ``estado_workflow``: REPARACION_LISTA se fija recien en
    PROC-REP-240, tras el control tecnico, y la espera de recursos conserva
    el ultimo hito (por ejemplo EN_REPARACION).
    """
    resultado = resolver_situacion_orden(orden.reparaciones_detail)

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-211",
        accion="EVALUAR_SITUACION_ORDEN",
        fecha=fecha,
        observacion=resultado.value,
    )

    if resultado in _RESULTADOS_QUE_CIERRAN_LA_TOMA:
        for toma in nueva_orden.tomas:
            if toma.estado is EstadoTomaOrden.ACTIVA:
                toma.estado = EstadoTomaOrden.CERRADA
                toma.fin = fecha

    if resultado is ResultadoEvaluacionOrden.PENDIENTE_RECURSOS:
        # PROC-REP-211 -> PROC-REP-120 directo (sin 100 ni 110).
        nueva_orden = marcar_pendiente_recursos(nueva_orden, fecha=fecha)
    elif resultado is ResultadoEvaluacionOrden.REQUIERE_REVISION:
        # PROC-REP-211 -> PROC-REP-125 (EXC-REP-004).
        nueva_orden = marcar_pendiente_revision(nueva_orden, fecha=fecha)

    return nueva_orden, resultado


def marcar_reparacion_lista(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-240: la Orden pasa a REPARACION_LISTA.

    Depende del evento de aprobacion de Recepcion, no solo del estado de
    los Detalles: por eso exige que todos tengan control APROBADO.

    Nodo ACT-SYSTEM: no lo ejecuta una persona, asi que no recibe
    Usuario y el historial queda sin actor humano. El evento humano
    del que depende es la aprobacion de Recepcion (PROC-REP-220), ya
    registrada en cada Detalle.
    """
    if not orden.reparaciones_detail:
        raise PrecondicionInvalidaError(
            "No se puede marcar lista una Orden sin Detalles."
        )
    if any(
        detalle.control_estado is not EstadoControl.APROBADO
        for detalle in orden.reparaciones_detail
    ):
        raise PrecondicionInvalidaError(
            "Todos los Detalles deben tener control APROBADO antes de "
            "REPARACION_LISTA."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-240",
        accion="MARCAR_REPARACION_LISTA",
        fecha=fecha,
    )
    nueva_orden.estado_workflow = EstadoWorkflow.REPARACION_LISTA
    return nueva_orden


def notificar_cliente(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-250 -> PROC-REP-260: se avisa al cliente.

    Solo queda registrada la accion: el MVP no modela una entidad
    Notificacion ni integra ningun canal de mensajeria.

    PROC-REP-250 es una decision sin actor; PROC-REP-260 es ACT-RECEP.
    Se alcanza tanto con la reparacion lista (240) como con una Orden
    finalizada SIN_REPARACION (069): ``lista_para_cierre``.
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    if not lista_para_cierre(orden):
        raise PrecondicionInvalidaError(
            f"Solo se notifica una Orden con resultado (REPARACION_LISTA o "
            f"SIN_REPARACION); esta en {orden.estado_workflow.value}."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-250",
        accion="REQUIERE_ENTREGA_A_CLIENTE",
        fecha=fecha,
        observacion=orden.origen.value,
    )
    return registrar_paso(
        nueva_orden,
        process_id="PROC-REP-260",
        accion="NOTIFICAR_CLIENTE",
        fecha=fecha,
        usuario_id=usuario.id,
    )


def entregar_equipo(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-270: se entrega el equipo y la Orden pasa a ENTREGADA.

    Exige la condicion de entrega ya superada (PROC-REP-265: saldo 0 sin
    override en V1.3 si es COBRABLE; sin pagos si es NO_COBRABLE), la
    documentacion final emitida (PROC-REP-280) y que no quede trabajo
    abierto: sin Ejecucion activa, sin toma activa y sin reservas
    pendientes.

    Al terminar, ``current_process`` avanza al evento terminal
    EVT-REP-999. Ese evento no genera entrada de historial: es el fin del
    flujo, no una accion.

    El nodo declara ``actores_alternativos: [ACT-RECEP]``: entrega
    Administracion o Recepcion. El actor NO relaja la condicion
    comercial: las precondiciones de abajo se exigen igual.
    """
    validar_alguno_de(usuario, ROLES_ENTREGA)

    if not lista_para_cierre(orden):
        raise PrecondicionInvalidaError(
            f"Solo se entrega una Orden con resultado (REPARACION_LISTA o "
            f"SIN_REPARACION); esta en {orden.estado_workflow.value}."
        )
    if not condicion_entrega_cumplida(orden):
        raise PrecondicionInvalidaError(
            f"No se puede entregar con saldo pendiente: {orden.saldo}."
        )
    if not orden.documentos.comprobante_final.generado:
        raise PrecondicionInvalidaError(
            "Falta generar el comprobante final (PROC-REP-280)."
        )
    # Una Orden SIN_REPARACION no emite garantia de reparacion (PROC-REP-280).
    if (
        not finalizada_sin_reparacion(orden)
        and not orden.documentos.garantia_reparacion.generado
    ):
        raise PrecondicionInvalidaError(
            "Falta generar la garantia de reparacion (PROC-REP-280)."
        )
    if any(
        ejecucion.estado is EstadoEjecucion.EN_PROGRESO
        for ejecucion in orden.ejecuciones
    ):
        raise PrecondicionInvalidaError(
            "No se puede entregar con una Ejecucion activa."
        )
    if any(toma.estado is EstadoTomaOrden.ACTIVA for toma in orden.tomas):
        raise PrecondicionInvalidaError(
            "No se puede entregar con una toma de Orden activa."
        )
    if hay_reservas_activas(orden.movimientos_insumo):
        raise PrecondicionInvalidaError(
            "No se puede entregar con reservas de insumos activas."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-270",
        accion="ENTREGAR_EQUIPO",
        fecha=fecha,
        usuario_id=usuario.id,
    )
    nueva_orden.estado_workflow = EstadoWorkflow.ENTREGADA
    nueva_orden.current_process = "EVT-REP-999"
    return nueva_orden


def informar_resultado_rt(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-250 ("No") -> PROC-REP-290: se informa el resultado a RT.

    RT_INTERNO no requiere entrega a cliente (politica), asi que
    PROC-REP-250 resuelve "No" y sigue directo a informar el resultado a
    Gestion RT, en vez de notificar/cobrar/entregar a un cliente.

    PROC-REP-290 es ``actor: ACT-SYSTEM`` en el Business Process V1.3: no
    hay una persona que lo dispare, asi que este service NO recibe
    ``Usuario`` ni valida ningun actor -igual que PROC-REP-060/140/170,
    los demas nodos ACT-SYSTEM del dominio-. El historial queda con
    ``usuario_id=None``. El MVP lo expone como paso demostrable (ver
    ``application.cierre.informar_rt``), pero conceptualmente es una
    System Action, no una accion humana con rol pendiente de definir.
    """
    if orden.origen is not OrigenOrden.RT_INTERNO:
        raise PrecondicionInvalidaError(
            f"Informar a Gestion RT es exclusivo de RT_INTERNO, no de "
            f"{orden.origen.value}."
        )
    if not lista_para_cierre(orden):
        raise PrecondicionInvalidaError(
            f"Solo se informa a RT una Orden con resultado (REPARACION_LISTA "
            f"o SIN_REPARACION); esta en {orden.estado_workflow.value}."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-250",
        accion="REQUIERE_ENTREGA_A_CLIENTE",
        fecha=fecha,
        observacion="No",
    )
    return registrar_paso(
        nueva_orden,
        process_id="PROC-REP-290",
        accion="INFORMAR_RESULTADO_RT",
        fecha=fecha,
    )


def devolver_equipo_rt(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-270 (reutilizado): devolucion del equipo a Gestion RT.

    Mismo nodo que ``entregar_equipo``, pero NO es una entrega comercial:
    no pasa por PROC-REP-265/266/280, no depende de Saldo ni de Pagos
    (HP-REP-002, ``skipped_nodes``). El estado terminal definitivo de una
    Orden RT_INTERNO sigue pendiente de definicion funcional en V1.3, asi
    que ``estado_workflow`` NO pasa a ENTREGADA -eso afirmaria una
    resolucion que el negocio todavia no tomo-: la Orden queda evidenciada
    como terminada unicamente en ``current_process`` (EVT-REP-999), igual
    que documenta el Business Process para este origen.

    Comparte los mismos actores que la entrega comercial
    (``ROLES_ENTREGA``): el nodo PROC-REP-270 es el mismo para ambos
    caminos.
    """
    validar_alguno_de(usuario, ROLES_ENTREGA)

    if orden.origen is not OrigenOrden.RT_INTERNO:
        raise PrecondicionInvalidaError(
            f"La devolucion a Gestion RT es exclusiva de RT_INTERNO, no "
            f"de {orden.origen.value}."
        )
    if orden.current_process != "PROC-REP-290":
        raise PrecondicionInvalidaError(
            "Falta informar el resultado a Gestion RT (PROC-REP-290) "
            "antes de devolver el equipo."
        )
    if any(
        ejecucion.estado is EstadoEjecucion.EN_PROGRESO
        for ejecucion in orden.ejecuciones
    ):
        raise PrecondicionInvalidaError(
            "No se puede devolver el equipo con una Ejecucion activa."
        )
    if any(toma.estado is EstadoTomaOrden.ACTIVA for toma in orden.tomas):
        raise PrecondicionInvalidaError(
            "No se puede devolver el equipo con una toma de Orden activa."
        )
    if hay_reservas_activas(orden.movimientos_insumo):
        raise PrecondicionInvalidaError(
            "No se puede devolver el equipo con reservas de insumos activas."
        )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-270",
        accion="DEVOLVER_EQUIPO_RT",
        fecha=fecha,
        usuario_id=usuario.id,
    )
    nueva_orden.current_process = "EVT-REP-999"
    return nueva_orden
