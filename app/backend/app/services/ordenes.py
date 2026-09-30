"""Ciclo de vida de la Orden de Reparacion.

Nodos cubiertos: PROC-REP-010/030/040 (ingreso y creacion),
PROC-REP-140 (habilitar), PROC-REP-150 (prioridad), PROC-REP-170 (cola),
PROC-REP-211 (evaluar situacion), PROC-REP-240 (reparacion lista),
PROC-REP-250/260 (notificar) y PROC-REP-270 (entrega).

Features: FEAT-REP-001, FEAT-REP-003, FEAT-REP-004, FEAT-REP-006,
FEAT-REP-008.

Todos los services devuelven una Orden nueva; la recibida nunca se
modifica.
"""

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
from .exceptions import PrecondicionInvalidaError
from .inventario import hay_reservas_activas
from .resolucion import ResultadoEvaluacionOrden, resolver_situacion_orden
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

# Resultados de BR-REP-012 en los que ya no queda ningun Detalle
# trabajable ni en ejecucion: cerrar la toma activa es correcto en
# ambos (BR-REP-018). Los demas resultados (ABIERTA_TRABAJABLE,
# EN_EJECUCION, REQUIERE_REVISION, PENDIENTE_RECURSOS) preservan la
# toma: si continuar, liberarla o volver a la cola es una decision que
# PROC-REP-212/213 (ya implementados) resuelve.
_RESULTADOS_QUE_CIERRAN_LA_TOMA = (
    ResultadoEvaluacionOrden.COMPLETA,
    ResultadoEvaluacionOrden.TODO_CANCELADO,
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


def habilitar_orden(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-140: la Orden queda habilitada para trabajarse.

    Precondicion del MVP: existe al menos un Detalle y el caller ya
    confirmo la factibilidad (PROC-REP-080/090). Los caminos de
    advertencia y override (PROC-REP-100/110/130) no estan implementados.

    Nodo ACT-SYSTEM: no lo ejecuta una persona, asi que no recibe
    Usuario y el historial queda sin actor humano.
    """
    if not orden.reparaciones_detail:
        raise PrecondicionInvalidaError(
            "No se puede habilitar una Orden sin Detalles de Reparacion."
        )
    if orden.estado_workflow is not EstadoWorkflow.REQUERIMIENTO:
        raise PrecondicionInvalidaError(
            f"Solo se habilita una Orden en REQUERIMIENTO; "
            f"esta en {orden.estado_workflow.value}."
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

    El MVP de HP-REP-001 solo alcanza COMPLETA de punta a punta. Los
    demas resultados ya estan clasificados y testeados (ver
    ``tests/test_resolucion_orden.py``), pero los caminos que los
    producen -recursos insuficientes, revision, cancelacion- todavia no
    estan conectados a ningun comando de la API: llegaran con los
    Scenarios que los necesiten.

    No cambia ``estado_workflow``: REPARACION_LISTA se fija recien en
    PROC-REP-240, tras el control tecnico.
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
    """
    validar_actor(usuario, RolUsuario.RECEPCION)

    if orden.estado_workflow is not EstadoWorkflow.REPARACION_LISTA:
        raise PrecondicionInvalidaError(
            f"Solo se notifica una Orden REPARACION_LISTA; "
            f"esta en {orden.estado_workflow.value}."
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

    Exige la condicion de entrega ya superada (PROC-REP-265, saldo 0 sin
    override en V1.3), la documentacion final emitida (PROC-REP-280) y
    que no quede trabajo abierto: sin Ejecucion activa, sin toma activa
    y sin reservas pendientes.

    Al terminar, ``current_process`` avanza al evento terminal
    EVT-REP-999. Ese evento no genera entrada de historial: es el fin del
    flujo, no una accion.

    El nodo declara ``actores_alternativos: [ACT-RECEP]``: entrega
    Administracion o Recepcion. El actor NO relaja la condicion
    comercial: las precondiciones de abajo se exigen igual.
    """
    validar_alguno_de(usuario, ROLES_ENTREGA)

    if orden.estado_workflow is not EstadoWorkflow.REPARACION_LISTA:
        raise PrecondicionInvalidaError(
            f"Solo se entrega una Orden REPARACION_LISTA; "
            f"esta en {orden.estado_workflow.value}."
        )
    if orden.saldo > 0:
        raise PrecondicionInvalidaError(
            f"No se puede entregar con saldo pendiente: {orden.saldo}."
        )
    if not orden.documentos.comprobante_final.generado:
        raise PrecondicionInvalidaError(
            "Falta generar el comprobante final (PROC-REP-280)."
        )
    if not orden.documentos.garantia_reparacion.generado:
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
    if orden.estado_workflow is not EstadoWorkflow.REPARACION_LISTA:
        raise PrecondicionInvalidaError(
            f"Solo se informa a RT una Orden REPARACION_LISTA; "
            f"esta en {orden.estado_workflow.value}."
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
            "No se puede devolver el equipo con reservas de insumos "
            "activas."
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
