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
    DatosRecepcion,
    DocumentosOrden,
    EntregaEquipo,
    Equipo,
    EstadoEjecucion,
    EstadoTomaOrden,
    EstadoWorkflow,
    OrdenReparacion,
    OrigenOrden,
    ResumenPago,
    RolUsuario,
    Usuario,
)
from app.domain.prioridad import (
    NOMBRES_DE_PRIORIDAD,
    PRIORIDAD_PREDETERMINADA,
    es_prioridad_valida,
    nombre_de_prioridad,
)

from .autorizacion import validar_actor, validar_alguno_de
from .autorizacion_cliente import (
    marcar_pendiente_autorizacion,
    situacion_de_la_orden,
)
from .custodia import (
    custodia_por_definir,
    custodia_resuelta,
    equipo_bajo_custodia,
    evidencias_de_equipo,
    recepcion_inicial,
)
from .exceptions import (
    EntidadNoEncontradaError,
    OrdenCerradaError,
    PrecondicionInvalidaError,
)
from .inventario import hay_reservas_activas
from .pagos import (
    cierre_financiero_resuelto,
    condicion_entrega_cumplida,
    credito_pendiente,
    motivo_de_entrega_bloqueada,
)
from .recursos import marcar_pendiente_recursos, override_listo_para_habilitar
from .redefinicion import marcar_pendiente_revision
from .reparaciones import control_tecnico_completo, definicion_finalizada
from .resolucion import ResultadoEvaluacionOrden
from .revisiones import finalizada_sin_reparacion, lista_para_cierre
from .tomas import toma_activa
from .workflow import registrar_accion_funcional, registrar_paso

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
# PENDIENTE_RECURSOS (PROC-REP-211 caso e), REQUIERE_REVISION (caso f) y
# PENDIENTE_AUTORIZACION (V1.4), donde ademas la Orden pasa a esperar en
# PROC-REP-120 / 125 / 129. Los demas (ABIERTA_TRABAJABLE, EN_EJECUCION)
# preservan la toma: si continuar o liberar lo resuelve PROC-REP-212/213.
_RESULTADOS_QUE_CIERRAN_LA_TOMA = (
    ResultadoEvaluacionOrden.COMPLETA,
    ResultadoEvaluacionOrden.TODO_CANCELADO,
    ResultadoEvaluacionOrden.PENDIENTE_RECURSOS,
    ResultadoEvaluacionOrden.REQUIERE_REVISION,
    ResultadoEvaluacionOrden.PENDIENTE_AUTORIZACION,
)


def exigir_orden_abierta(orden: OrdenReparacion) -> None:
    """E1: ninguna operacion modifica una Orden cerrada.

    Unica validacion de "Orden cerrada" de los comandos: la aplica la capa
    de aplicacion al cargar la Orden que va a modificar, antes de
    cualquier otra precondicion. Asi el rechazo es siempre el mismo (409
    ORDEN_CERRADA) y no depende de que cada service recuerde mirar el
    estado. Consultar la Orden o iniciar una garantia RMA desde ella no
    pasa por aqui: ninguna de las dos la modifica.
    """
    if not orden.esta_cerrada:
        return
    if orden.estado_workflow is EstadoWorkflow.ENTREGADA:
        situacion = "ya fue entregada"
    elif orden.estado_workflow is EstadoWorkflow.CANCELADA:
        situacion = "fue cancelada y su proceso termino"
    else:
        situacion = "ya fue devuelta a Gestion RT"
    raise OrdenCerradaError(
        f"La Orden {orden.id} {situacion}: esta cerrada y solo puede "
        "consultarse."
    )


def devolucion_pendiente(orden: OrdenReparacion) -> bool:
    """Orden CANCELADA cuyo equipo todavia no se devolvio (PROC-REP-270).

    Es la devolucion FISICA del equipo: la de dinero (saldo a favor, V1.4
    PROC-REP-267) es otra dimension y puede resolverse antes o despues.
    La custodia es la confirmada (``services.custodia``): el comprobante de
    recepcion no la prueba.
    """
    return (
        orden.estado_workflow is EstadoWorkflow.CANCELADA
        and not orden.esta_cerrada
        and equipo_bajo_custodia(orden)
        and orden.devolucion is None
    )


def pendientes_para_cerrar(orden: OrdenReparacion) -> list[str]:
    """Que le falta a una Orden CANCELADA abierta para cerrarse.

    Dos dimensiones independientes: el equipo (definir la custodia y, si
    esta en el local, devolverlo) y el dinero (devolver el saldo a favor).
    Vacio si la Orden no esta cancelada o ya cerro.
    """
    if (
        orden.estado_workflow is not EstadoWorkflow.CANCELADA
        or orden.esta_cerrada
    ):
        return []
    pendientes = []
    if custodia_por_definir(orden):
        if evidencias_de_equipo(orden):
            pendientes.append(
                "Falta confirmar la recepcion fisica del equipo (el historial "
                "registra trabajo sobre el) y registrar su devolucion."
            )
        else:
            pendientes.append(
                "Falta definir la custodia del equipo: confirmar la "
                "recepcion fisica (y despues registrar su devolucion) o "
                'registrar "Equipo no recibido".'
            )
    elif equipo_bajo_custodia(orden):
        pendientes.append("Falta registrar la devolucion fisica del equipo.")
    credito = credito_pendiente(orden)
    if credito > 0:
        pendientes.append(
            f"Falta devolver al cliente el saldo a favor: {credito}."
        )
    return pendientes


def cerrar_cancelada_si_corresponde(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """Una Orden CANCELADA abierta pasa por PROC-REP-268 si el equipo ya no
    condiciona el cierre (devuelto o no recibido); si no, sigue esperando.

    Nunca cierra con la custodia sin definir ni con el equipo en el local.
    """
    if (
        orden.estado_workflow is EstadoWorkflow.CANCELADA
        and not orden.esta_cerrada
        and custodia_resuelta(orden)
    ):
        return verificar_fin_financiero(orden, fecha=fecha)
    return orden


def verificar_fin_financiero(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-268 (V1.4): sin saldo a favor pendiente, la Orden termina.

    Para una Orden CANCELADA que ya no espera la devolucion fisica del
    equipo. Ninguna Orden termina (EVT-REP-999) con dinero del cliente sin
    devolver (BR-REP-038): con saldo a favor queda abierta en PROC-REP-268
    hasta registrar la devolucion de dinero; sin el, termina. Sin
    movimientos de dinero la verificacion es trivial y no deja traza, como
    el propio EVT-REP-999. ACT-SYSTEM: no recibe Usuario.
    """
    if not orden.resumen_pago.pagos:
        nueva_orden = orden.model_copy(deep=True)
        nueva_orden.current_process = "EVT-REP-999"
        nueva_orden.updated_at = fecha
        return nueva_orden
    if not cierre_financiero_resuelto(orden):
        return registrar_paso(
            orden,
            process_id="PROC-REP-268",
            accion="VERIFICAR_SALDO_A_FAVOR_PENDIENTE",
            fecha=fecha,
            observacion=(
                "Saldo a favor del cliente pendiente de devolver: "
                f"{credito_pendiente(orden)}"
            ),
        )
    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-268",
        accion="VERIFICAR_SALDO_A_FAVOR_PENDIENTE",
        fecha=fecha,
        observacion="Sin saldo a favor pendiente",
    )
    nueva_orden.current_process = "EVT-REP-999"
    return nueva_orden


def marcar_orden_cancelada(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """La Orden pasa a CANCELADA (PROC-REP-211 TODO_CANCELADO / 306).

    Fija el hito y decide como sigue, sin inventar un nodo: si el equipo
    esta en custodia, la Orden espera su devolucion fisica (PROC-REP-270,
    ``services.cancelaciones.registrar_devolucion_equipo``); si todavia no
    se decidio si el equipo se recibio, espera esa decision (nunca se
    asume que no hay equipo); solo si se registro "Equipo no recibido" pasa
    por la verificacion financiera (``verificar_fin_financiero``): termina
    aca (EVT-REP-999), o espera la devolucion de un anticipo. CANCELADA
    nunca se convierte en ENTREGADA. Nodo ACT-SYSTEM: no recibe Usuario.
    """
    nueva_orden = orden.model_copy(deep=True)
    nueva_orden.estado_workflow = EstadoWorkflow.CANCELADA
    nueva_orden.updated_at = fecha
    return cerrar_cancelada_si_corresponde(nueva_orden, fecha=fecha)


def crear_orden_cliente_externo(
    *,
    orden_id: str,
    cliente: Cliente,
    equipo: Equipo,
    usuario: Usuario,
    fecha: datetime,
    datos_recepcion: DatosRecepcion | None = None,
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
        recepcion=recepcion_inicial(
            usuario_id=usuario.id, fecha=fecha, datos=datos_recepcion
        ),
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
    datos_recepcion: DatosRecepcion | None = None,
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
        recepcion=recepcion_inicial(
            usuario_id=usuario.id, fecha=fecha, datos=datos_recepcion
        ),
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
    datos_recepcion: DatosRecepcion | None = None,
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
        recepcion=recepcion_inicial(
            usuario_id=usuario.id, fecha=fecha, datos=datos_recepcion
        ),
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


def fue_habilitada(orden: OrdenReparacion) -> bool:
    """El hito PROC-REP-140 ya ocurrio (BR-REP-037).

    Criterio unico para todos los caminos (factibilidad, revalidacion,
    override, redefinicion, autorizacion del cliente): la habilitacion
    inicial es un hito historico unico. Se deriva del historial, sin flag
    persistido.
    """
    return any(paso.process_id == "PROC-REP-140" for paso in orden.historial)


def fue_priorizada(orden: OrdenReparacion) -> bool:
    """PROC-REP-150 ya ocurrio: la Orden tiene su prioridad asignada.

    Como la habilitacion, se deriva del historial. Los regresos a la cola
    (retrabajo, redefinicion, revalidacion, autorizacion del cliente)
    conservan esa prioridad: no se vuelve a priorizar.
    """
    return any(paso.process_id == "PROC-REP-150" for paso in orden.historial)


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

    La habilitacion inicial es un hito unico (BR-REP-037): una Orden que ya
    paso por 140 se rechaza aunque cumpla el gate -una EN_REPARACION o
    EN_COLA siempre lo cumple-. Lo que sigue a su 090 "Si" o a su 130 es
    ``habilitar_o_reevaluar``.

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
    if fue_habilitada(orden):
        raise PrecondicionInvalidaError(
            "La Orden ya se habilito (PROC-REP-140): la habilitacion "
            "inicial no se repite (BR-REP-037)."
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

    Convencion de ``app.domain.prioridad``: 1 Urgente, 2 Alta, 3 Media,
    4 Normal (la predeterminada); cuanto menor, mas prioritaria. Solo se
    admiten esos valores; los historicos fuera de 1-4 se conservan, pero
    no se asignan de nuevo.

    Se asigna una sola vez: la Orden habilitada se prioriza al entrar a la
    cola y los regresos posteriores conservan su prioridad.

    El nodo declara ``actores_alternativos: [ACT-RECEP]``: la
    priorizacion la puede hacer Coordinacion o Recepcion, sin
    jerarquia entre ellas.
    """
    validar_alguno_de(usuario, ROLES_PRIORIZACION)

    if not es_prioridad_valida(prioridad):
        opciones = ", ".join(
            f"{valor} ({nombre})"
            for valor, nombre in NOMBRES_DE_PRIORIDAD.items()
        )
        raise PrecondicionInvalidaError(
            f"Prioridad invalida: {prioridad}. Valores admitidos: {opciones}."
        )
    if fue_priorizada(orden):
        raise PrecondicionInvalidaError(
            f"La Orden ya tiene prioridad {orden.prioridad} (PROC-REP-150): "
            "la priorizacion no se repite."
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


# Cambiar la prioridad de una Orden que ya esta en el taller (MVP v2):
# los tecnicos segun el diagnostico, y Coordinacion y Recepcion como antes.
ROLES_CAMBIO_PRIORIDAD = (
    RolUsuario.TECNICO,
    RolUsuario.COORDINADOR_RMA,
    RolUsuario.RECEPCION,
)
# ACC-REP-007 (hp-rep-001.yaml): "Asignar la prioridad de ejecucion de la
# Orden". La primera asignacion es PROC-REP-150 (una sola vez); los
# cambios posteriores son esta accion funcional y no repiten el nodo.
ACCION_CAMBIAR_PRIORIDAD = "ACC-REP-007"
_ESTADOS_EN_TALLER = (EstadoWorkflow.EN_COLA, EstadoWorkflow.EN_REPARACION)


def ingresar_a_cola_con_prioridad_predeterminada(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
    usuario_id: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-150 (4 - Normal) -> PROC-REP-170 sin un paso humano.

    Para el ingreso inicial de CLIENTE_EXTERNO (MVP v2): la Orden
    habilitada entra sola a la cola con la prioridad predeterminada.
    ``usuario_id`` es quien ejecuto el comando que la habilito (o ``None``
    si fue un paso del sistema). Igual que la priorizacion manual, ocurre
    una sola vez.
    """
    if fue_priorizada(orden):
        raise PrecondicionInvalidaError(
            f"La Orden ya tiene prioridad {orden.prioridad} (PROC-REP-150): "
            "la priorizacion no se repite."
        )
    if orden.estado_workflow is not EstadoWorkflow.HABILITADA:
        raise PrecondicionInvalidaError(
            f"Solo entra a la cola una Orden HABILITADA; "
            f"esta en {orden.estado_workflow.value}."
        )
    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-150",
        accion="DEFINIR_PRIORIDAD",
        fecha=fecha,
        usuario_id=usuario_id,
        observacion=f"{PRIORIDAD_PREDETERMINADA} (predeterminada)",
    )
    nueva_orden.prioridad = PRIORIDAD_PREDETERMINADA
    return ingresar_a_cola(nueva_orden, fecha=fecha)


def cambiar_prioridad(
    orden: OrdenReparacion,
    *,
    prioridad: int,
    usuario: Usuario,
    fecha: datetime,
    motivo: str | None = None,
) -> OrdenReparacion:
    """Cambia la prioridad de una Orden en el taller (ACC-REP-007).

    Distinto de entrar a la cola: la Orden ya fue priorizada (150) y esta
    en cola o en reparacion. No mueve el proceso ni la cola de lugar: la
    cola se reordena sola por prioridad. Deja en el historial quien la
    cambio, cuando, el valor anterior y el nuevo.
    """
    validar_alguno_de(usuario, ROLES_CAMBIO_PRIORIDAD)
    if not es_prioridad_valida(prioridad):
        opciones = ", ".join(
            f"{valor} ({nombre})"
            for valor, nombre in NOMBRES_DE_PRIORIDAD.items()
        )
        raise PrecondicionInvalidaError(
            f"Prioridad invalida: {prioridad}. Valores admitidos: {opciones}."
        )
    if not fue_priorizada(orden):
        raise PrecondicionInvalidaError(
            "La Orden todavia no entro a la cola: la prioridad se asigna "
            "al ingresar."
        )
    if orden.estado_workflow not in _ESTADOS_EN_TALLER:
        raise PrecondicionInvalidaError(
            "La prioridad solo cambia mientras la Orden esta en el taller "
            f"(en cola o en reparacion); esta en "
            f"{orden.estado_workflow.value}."
        )
    if prioridad == orden.prioridad:
        raise PrecondicionInvalidaError(
            f"La Orden ya tiene prioridad {prioridad}."
        )
    observacion = (
        f"{orden.prioridad} -> {prioridad} ({nombre_de_prioridad(prioridad)})"
    )
    motivo = (motivo or "").strip()
    if motivo:
        observacion += f": {motivo}"
    nueva_orden = registrar_accion_funcional(
        orden,
        accion_id=ACCION_CAMBIAR_PRIORIDAD,
        accion="CAMBIAR_PRIORIDAD",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=observacion,
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
    PROC-REP-125; con PENDIENTE_AUTORIZACION (ningun Detalle trabajable y
    alguno esperando la decision del cliente) cierra la toma y espera en
    PROC-REP-129. Los Detalles pendientes de autorizacion los deriva
    ``situacion_de_la_orden`` segun la politica del Origen.

    Se invoca tambien despues de cancelar Detalles (PROC-REP-300/305) y de
    rechazar un control (PROC-REP-235):

    - TODO_CANCELADO (caso d): la Orden pasa a CANCELADA
      (``marcar_orden_cancelada``), y espera la devolucion del equipo si
      esta en custodia.
    - ABIERTA_TRABAJABLE sin toma activa (caso b) con la Orden ya en el
      taller (EN_REPARACION): vuelve a la cola (PROC-REP-170), por
      ejemplo con un Detalle reabierto para retrabajo. En las etapas
      anteriores (definicion, habilitada, en cola) la Orden ya esta donde
      corresponde y no se mueve.

    Fuera de esos dos casos no cambia ``estado_workflow``: REPARACION_LISTA
    se fija recien en PROC-REP-240, tras el control tecnico, y la espera de
    recursos conserva el ultimo hito (por ejemplo EN_REPARACION).
    """
    resultado = situacion_de_la_orden(orden)

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
    elif (
        resultado is ResultadoEvaluacionOrden.PENDIENTE_AUTORIZACION
        and definicion_finalizada(nueva_orden)
    ):
        # PROC-REP-211 -> PROC-REP-129 (V1.4, BR-REP-028). Con la
        # definicion todavia abierta (por ejemplo, al cancelar un Detalle
        # mientras se cargan) no se le pregunto nada al cliente: la Orden
        # sigue donde estaba. Al finalizar, 129 lo registra el comando.
        nueva_orden = marcar_pendiente_autorizacion(nueva_orden, fecha=fecha)
    elif resultado is ResultadoEvaluacionOrden.TODO_CANCELADO:
        # PROC-REP-211 (d): CANCELADA [-> 270 devolucion] -> EVT-REP-999.
        nueva_orden = marcar_orden_cancelada(nueva_orden, fecha=fecha)
    elif (
        resultado is ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE
        and toma_activa(nueva_orden) is None
        and nueva_orden.estado_workflow is EstadoWorkflow.EN_REPARACION
    ):
        # PROC-REP-211 (b) -> PROC-REP-170: disponible para cualquier
        # tecnico, con su prioridad.
        nueva_orden = registrar_paso(
            nueva_orden,
            process_id="PROC-REP-170",
            accion="INGRESAR_A_COLA",
            fecha=fecha,
        )
        nueva_orden.estado_workflow = EstadoWorkflow.EN_COLA

    return nueva_orden, resultado


def habilitar_o_reevaluar(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """Lo que sigue a una factibilidad aprobada (090 "Si") o a un 130.

    Nunca habilitada: PROC-REP-140 (``habilitar_orden``), y despues la
    priorizacion de siempre. Ya habilitada: ni 140 ni la priorizacion se
    repiten (BR-REP-037); PROC-REP-211 recalcula la situacion y la devuelve
    a la cola (170) si venia del taller sin toma, o la deja donde estaba
    -en cola, habilitada o con su toma-, con su prioridad y sin tocar
    tomas ni Ejecuciones. Es la continuacion que ya usa la autorizacion
    del cliente en una Orden habilitada.
    """
    if not fue_habilitada(orden):
        return habilitar_orden(orden, fecha=fecha)
    nueva_orden, _ = evaluar_situacion_orden(orden, fecha=fecha)
    return nueva_orden


def marcar_reparacion_lista(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-240: la Orden pasa a REPARACION_LISTA.

    Depende del evento de aprobacion de Recepcion, no solo del estado de
    los Detalles: por eso exige que todos los Detalles vigentes tengan
    control APROBADO (los CANCELADO no se controlan).

    Nodo ACT-SYSTEM: no lo ejecuta una persona, asi que no recibe
    Usuario y el historial queda sin actor humano. El evento humano
    del que depende es la aprobacion de Recepcion (PROC-REP-220), ya
    registrada en cada Detalle.
    """
    if not orden.reparaciones_detail:
        raise PrecondicionInvalidaError(
            "No se puede marcar lista una Orden sin Detalles."
        )
    if not control_tecnico_completo(orden):
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
    entrega: EntregaEquipo | None = None,
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

    ``entrega`` (quien retira, su identificacion, observaciones) queda en
    ``orden.entrega``. La custodia confirmada y el receptor obligatorio los
    exige el comando de entrega (``application.cierre.entregar``) antes de
    emitir nada.
    """
    validar_alguno_de(usuario, ROLES_ENTREGA)

    if not lista_para_cierre(orden):
        raise PrecondicionInvalidaError(
            f"Solo se entrega una Orden con resultado (REPARACION_LISTA o "
            f"SIN_REPARACION); esta en {orden.estado_workflow.value}."
        )
    if not condicion_entrega_cumplida(orden):
        raise PrecondicionInvalidaError(
            f"No se puede entregar: {motivo_de_entrega_bloqueada(orden)}."
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

    observacion = None
    if entrega is not None:
        observacion = f"Retira: {entrega.recibido_por}"
        if entrega.identificacion_receptor:
            observacion += f" ({entrega.identificacion_receptor})"
    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-270",
        accion="ENTREGAR_EQUIPO",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=observacion,
    )
    nueva_orden.entrega = entrega
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
