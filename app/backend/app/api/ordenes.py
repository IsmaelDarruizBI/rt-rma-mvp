"""Endpoints de Ordenes de Reparacion.

Cada POST representa UNA intencion de una persona, no un nodo del
proceso. Una accion humana arrastra los nodos ACT-SYSTEM que la siguen
hasta la proxima frontera de actor humano; ahi se corta. Por eso no hay
un endpoint por nodo ni nada que ejecute el escenario completo de una.

El router es fino a proposito: valida la forma del request, delega en
``app.application`` y arma la respuesta. No decide nada de negocio y no
atrapa excepciones -de eso se ocupa ``errores.py``-.
"""

from fastapi import APIRouter, status

from app.application import (
    ApplicationContext,
    acciones_disponibles,
    aprobar_control,
    completar_ejecucion,
    crear_orden,
    crear_orden_rt,
    definir_reparacion,
    definir_reparacion_desde_revision,
    detalles_origen_de,
    devolver_rt,
    encolar_orden,
    entregar,
    enviar_a_revision,
    esperar_recursos,
    finalizar_definicion,
    finalizar_sin_reparacion,
    forzar_detalle_por_recursos,
    informar_rt,
    iniciar_detalle,
    iniciar_garantia_rma,
    insumos_previstos_por_detalle,
    interrumpir_ejecucion,
    liberar_orden,
    listar_ordenes,
    nombres_de_tipo_por_detalle,
    notificar,
    obtener_orden,
    progreso,
    realizar_revision,
    redefinir_detalle,
    registrar_pago_de_orden,
    requerir_redefinicion_ejecucion,
    revalidar_recursos,
    revisar_detalle,
    tomar_orden_en_estacion,
)
from app.domain.models import OrdenReparacion

from .dependencias import ContextoDep
from .schemas import (
    AprobarControlIn,
    CompletarEjecucionIn,
    CrearOrdenIn,
    CrearOrdenRtIn,
    DefinirReparacionDesdeRevisionIn,
    DefinirReparacionIn,
    DevolverRtIn,
    EncolarIn,
    EntregarIn,
    EnviarARevisionIn,
    FinalizarDefinicionIn,
    FinalizarSinReparacionIn,
    IniciarDetalleIn,
    IniciarGarantiaRmaIn,
    InterrumpirEjecucionIn,
    LiberarOrdenIn,
    NotificarIn,
    OrdenConEntregaOut,
    OrdenOut,
    OrdenResumenOut,
    OverrideRecursosIn,
    PagoIn,
    RedefinirDetalleIn,
    RequiereRedefinicionIn,
    RevisionDetalleIn,
    RevisionTecnicaIn,
    TomarIn,
)

router = APIRouter(prefix="/api/orders", tags=["ordenes"])


def _salida(orden: OrdenReparacion, contexto: ApplicationContext) -> OrdenOut:
    """Vista HTTP de la Orden: progreso, acciones e insumos previstos.

    Los insumos previstos se resuelven contra el catalogo al responder.
    Con ellos la UI puede proponer que confirmar en PROC-REP-200 sin
    conocer ningun ID de insumo. Lo mismo con los Detalles origen de una
    garantia RMA: su Tipo se lee de la Orden origen.
    """
    return OrdenOut.desde_dominio(
        orden,
        progreso=progreso(orden),
        acciones=acciones_disponibles(orden),
        insumos_previstos=insumos_previstos_por_detalle(contexto, orden),
        nombres_de_tipo=nombres_de_tipo_por_detalle(contexto, orden),
        detalles_origen=detalles_origen_de(contexto, orden),
    )


def _salida_con_entrega(
    orden: OrdenReparacion,
    contexto: ApplicationContext,
    puede_entregar: bool,
) -> OrdenConEntregaOut:
    """Idem, mas el resultado de PROC-REP-265."""
    return OrdenConEntregaOut(
        **_salida(orden, contexto).model_dump(),
        puede_entregar=puede_entregar,
    )


# --- Lectura -----------------------------------------------------------


@router.get("")
def get_ordenes(contexto: ContextoDep) -> list[OrdenResumenOut]:
    """Listado de Ordenes."""
    return [
        OrdenResumenOut.desde_dominio(orden)
        for orden in listar_ordenes(contexto)
    ]


@router.get("/{orden_id}")
def get_orden(orden_id: str, contexto: ContextoDep) -> OrdenOut:
    """Una Orden con su detalle completo."""
    return _salida(obtener_orden(contexto, orden_id), contexto)


# --- Comandos del Happy Path -------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
def post_crear_orden(
    cuerpo: CrearOrdenIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Ingreso de un equipo de cliente externo (ACT-RECEP).

    Compone PROC-REP-010 -> 030 -> 040. La Orden nace en REQUERIMIENTO,
    sin Detalles.
    """
    orden = crear_orden(
        contexto,
        usuario_id=cuerpo.usuario_id,
        cliente=cuerpo.cliente.a_dominio(),
        equipo=cuerpo.equipo.a_dominio(),
    )
    return _salida(orden, contexto)


@router.post("/rt-interno", status_code=status.HTTP_201_CREATED)
def post_crear_orden_rt(
    cuerpo: CrearOrdenRtIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Ingreso de un equipo RT_INTERNO (ACT-RECEP, HP-REP-002).

    Compone PROC-REP-010 -> 020 -> 040. Sin Cliente: el equipo es de
    Rosario Tecno.
    """
    orden = crear_orden_rt(
        contexto,
        usuario_id=cuerpo.usuario_id,
        equipo=cuerpo.equipo.a_dominio(),
        referencia_rt=cuerpo.referencia_rt,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/details")
def post_definir_reparacion(
    orden_id: str,
    cuerpo: DefinirReparacionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Agregar UN Detalle de la reparacion (ACT-RECEP).

    Compone PROC-REP-045 (Si, con el primer Detalle) -> 070. No genera el
    comprobante, no valida factibilidad ni habilita: la Orden sigue en
    REQUERIMIENTO lista para otro Detalle o para finalizar la definicion.
    """
    orden = definir_reparacion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        tipo_reparacion_id=cuerpo.tipo_reparacion_id,
        observaciones=cuerpo.observaciones,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/definition/finalize")
def post_finalizar_definicion(
    orden_id: str,
    cuerpo: FinalizarDefinicionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Finalizar la definicion de la reparacion (ACT-RECEP).

    Exige al menos un Detalle. Compone [050 -> 060, solo si el comprobante
    todavia no se evaluo] -> 080 -> 090 -> 140, o se detiene en 100 si
    ningun Detalle es trabajable. La factibilidad (080) consulta el stock
    global y NO reserva.
    """
    orden = finalizar_definicion(
        contexto, orden_id=orden_id, usuario_id=cuerpo.usuario_id
    )
    return _salida(orden, contexto)


@router.post(
    "/{orden_origen_id}/warranty-rma",
    status_code=status.HTTP_201_CREATED,
)
def post_iniciar_garantia_rma(
    orden_origen_id: str,
    cuerpo: IniciarGarantiaRmaIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Iniciar la garantia RMA de una Orden entregada (ACT-RECEP).

    HP-REP-003. Con 1..N Detalles origen compone PROC-REP-035 -> 040 ->
    045 (No) -> 055 -> 050 -> 060 y se detiene: la NUEVA Orden queda
    EN_REVISION, sin Detalles, esperando la revision tecnica. La Orden
    origen no se modifica.
    """
    orden = iniciar_garantia_rma(
        contexto,
        orden_origen_id=orden_origen_id,
        detalle_origen_ids=cuerpo.detalle_origen_ids,
        usuario_id=cuerpo.usuario_id,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/send-to-review")
def post_enviar_a_revision(
    orden_id: str,
    cuerpo: EnviarARevisionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Enviar una Orden sin diagnostico a revision (ACT-RECEP).

    Compone PROC-REP-045 (No) -> 055 -> 050 y, si la politica del Origen
    lo exige, 060 (VAR-REP-001/002). La Orden queda EN_REVISION.
    """
    orden = enviar_a_revision(
        contexto, orden_id=orden_id, usuario_id=cuerpo.usuario_id
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/technical-review")
def post_revision_tecnica(
    orden_id: str,
    cuerpo: RevisionTecnicaIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Realizar la revision tecnica y registrar su resultado (ACT-TECH).

    PROC-REP-065. No define Detalles: eso vuelve a ser de Recepcion.
    """
    orden = realizar_revision(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        resultado=cuerpo.resultado,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/review/details")
def post_definir_reparacion_desde_revision(
    orden_id: str,
    cuerpo: DefinirReparacionDesdeRevisionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Agregar UN Detalle luego de la revision (ACT-RECEP).

    Compone PROC-REP-068 (Si, con el primer Detalle) -> 075. La carga se
    cierra con ``/definition/finalize``, que no repite el comprobante.
    """
    orden = definir_reparacion_desde_revision(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        tipo_reparacion_id=cuerpo.tipo_reparacion_id,
        observaciones=cuerpo.observaciones,
        detalle_origen_id=cuerpo.detalle_origen_id,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/review/without-repair")
def post_finalizar_sin_reparacion(
    orden_id: str,
    cuerpo: FinalizarSinReparacionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Finalizar la Orden sin reparacion (ACT-RECEP, BR-REP-010).

    Compone PROC-REP-068 (No) -> 069 (SIN_REPARACION). Sin Detalles ni
    precio. El cierre sigue segun el Origen: ``/notify`` o ``/inform-rt``.
    """
    orden = finalizar_sin_reparacion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        motivo=cuerpo.motivo,
        observaciones=cuerpo.observaciones,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/details/{detalle_id}/resources/override")
def post_override_recursos(
    orden_id: str,
    detalle_id: str,
    cuerpo: OverrideRecursosIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Override de recursos de un Detalle bloqueado (ACT-COORD, BR-REP-003).

    Capacidad transversal (ACC-REP-049): registra la autorizacion sobre
    ESE Detalle sin reservar ni tocar el stock, tambien con factibilidad
    parcial (Orden habilitada, en cola o tomada), sin reiniciar el flujo.
    Solo si la Orden esta detenida en PROC-REP-100 continua 110 (Si) ->
    130 -> 140.
    """
    orden = forzar_detalle_por_recursos(
        contexto,
        orden_id=orden_id,
        detalle_id=detalle_id,
        usuario_id=cuerpo.usuario_id,
        motivo=cuerpo.motivo,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/resources/wait")
def post_esperar_recursos(
    orden_id: str,
    contexto: ContextoDep,
) -> OrdenOut:
    """La Orden espera por recursos (EXC-REP-001): PROC-REP-110 No -> 120.

    Evento de sistema: sin actor humano ni body. Solo valido desde
    PROC-REP-100.
    """
    orden = esperar_recursos(contexto, orden_id=orden_id)
    return _salida(orden, contexto)


@router.post("/{orden_id}/resources/revalidate")
def post_revalidar_recursos(
    orden_id: str,
    contexto: ContextoDep,
) -> OrdenOut:
    """Revalida la factibilidad (EXC-REP-001): PROC-REP-120 -> 080 -> 090.

    Evento de sistema: sin actor humano ni body. Solo valido desde
    PROC-REP-120; con un Detalle trabajable continua a PROC-REP-140.
    """
    orden = revalidar_recursos(contexto, orden_id=orden_id)
    return _salida(orden, contexto)


@router.post("/{orden_id}/queue")
def post_encolar(
    orden_id: str,
    cuerpo: EncolarIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Priorizar e ingresar a la cola (ACT-COORD).

    Compone PROC-REP-150 -> 170.
    """
    orden = encolar_orden(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        prioridad=cuerpo.prioridad,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/take")
def post_tomar(
    orden_id: str,
    cuerpo: TomarIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Tomar la Orden desde una Estacion (ACT-TECH).

    Compone PROC-REP-172 -> 180. Si la validacion de estacion no pasa,
    la aplicacion lo convierte en un conflicto funcional (409) con el
    motivo concreto.
    """
    orden = tomar_orden_en_estacion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        estacion_id=cuerpo.estacion_id,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/details/{detalle_id}/start")
def post_iniciar_detalle(
    orden_id: str,
    detalle_id: str,
    cuerpo: IniciarDetalleIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Iniciar el trabajo sobre un Detalle (ACT-TECH).

    Compone PROC-REP-181 -> 174 -> 185. Aqui ocurre la RESERVA REAL de
    insumos, bajo la seccion critica de inventario.
    """
    orden = iniciar_detalle(
        contexto,
        orden_id=orden_id,
        detalle_id=detalle_id,
        usuario_id=cuerpo.usuario_id,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/executions/{ejecucion_id}/complete")
def post_completar_ejecucion(
    orden_id: str,
    ejecucion_id: str,
    cuerpo: CompletarEjecucionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Completar la Ejecucion en curso (ACT-TECH propietario).

    Compone PROC-REP-190 -> 200 -> 210 -> 211: el tecnico confirma lo
    realmente utilizado, el inventario se concilia y la situacion de la
    Orden se recalcula.
    """
    orden, _ = completar_ejecucion(
        contexto,
        orden_id=orden_id,
        ejecucion_id=ejecucion_id,
        usuario_id=cuerpo.usuario_id,
        insumos_utilizados=[
            insumo.a_dominio() for insumo in cuerpo.insumos_utilizados
        ],
        observaciones=cuerpo.observaciones,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/executions/{ejecucion_id}/interrupt")
def post_interrumpir_ejecucion(
    orden_id: str,
    ejecucion_id: str,
    cuerpo: InterrumpirEjecucionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Interrumpir la Ejecucion en curso (ACT-TECH propietario, VAR-REP-003).

    Compone PROC-REP-190 -> 200 (Interrumpido) -> 210 -> 211: lo realmente
    utilizado se consume, lo reservado que no se uso se libera, el Detalle
    vuelve a DEFINIDO y la toma sigue activa.
    """
    orden, _ = interrumpir_ejecucion(
        contexto,
        orden_id=orden_id,
        ejecucion_id=ejecucion_id,
        usuario_id=cuerpo.usuario_id,
        insumos_utilizados=[
            insumo.a_dominio() for insumo in cuerpo.insumos_utilizados
        ],
        observaciones=cuerpo.observaciones,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/executions/{ejecucion_id}/requires-redefinition")
def post_requiere_redefinicion(
    orden_id: str,
    ejecucion_id: str,
    cuerpo: RequiereRedefinicionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Cerrar la Ejecucion porque el Detalle requiere redefinicion.

    ACT-TECH propietario, EXC-REP-004. Compone PROC-REP-190 -> 200
    ("Requiere redefinicion") -> 210 -> 211 [-> 125]: lo utilizado se
    consume, lo reservado sin usar se libera y el Detalle queda DEFINIDO +
    REQUIERE_DEFINICION. El motivo es obligatorio.
    """
    orden, _ = requerir_redefinicion_ejecucion(
        contexto,
        orden_id=orden_id,
        ejecucion_id=ejecucion_id,
        usuario_id=cuerpo.usuario_id,
        insumos_utilizados=[
            insumo.a_dominio() for insumo in cuerpo.insumos_utilizados
        ],
        motivo=cuerpo.motivo,
        observaciones=cuerpo.observaciones,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/details/{detalle_id}/technical-review")
def post_revisar_detalle(
    orden_id: str,
    detalle_id: str,
    cuerpo: RevisionDetalleIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Revision tecnica de un Detalle pendiente (ACT-TECH, PROC-REP-126)."""
    orden = revisar_detalle(
        contexto,
        orden_id=orden_id,
        detalle_id=detalle_id,
        usuario_id=cuerpo.usuario_id,
        resultado=cuerpo.resultado,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/details/{detalle_id}/redefine")
def post_redefinir_detalle(
    orden_id: str,
    detalle_id: str,
    cuerpo: RedefinirDetalleIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Redefinir el Detalle (ACT-RECEP, PROC-REP-127 -> 080 -> 090 ...)."""
    orden = redefinir_detalle(
        contexto,
        orden_id=orden_id,
        detalle_id=detalle_id,
        usuario_id=cuerpo.usuario_id,
        tipo_reparacion_id=cuerpo.tipo_reparacion_id,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/control/approve")
def post_aprobar_control(
    orden_id: str,
    cuerpo: AprobarControlIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Aprobar el control tecnico (ACT-RECEP).

    Compone PROC-REP-220 -> 230, y 245 -> 240 recien cuando, con
    ``detalle_id`` o sin el, todos los Detalles de la Orden quedan
    APROBADO. No notifica: avisar al cliente es otra decision de
    Recepcion.
    """
    orden = aprobar_control(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        detalle_id=cuerpo.detalle_id,
        observaciones=cuerpo.observaciones,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/release")
def post_liberar_orden(
    orden_id: str,
    cuerpo: LiberarOrdenIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Liberar la Orden sin terminarla (ACT-TECH).

    Compone PROC-REP-212 ("No") -> 213: cierra la toma activa y la
    Orden vuelve a EN_COLA. Solo tiene sentido cuando todavia queda al
    menos un Detalle trabajable -si no, ``evaluar_situacion_orden`` ya
    cerro la toma automaticamente al terminar el ultimo-.
    """
    orden = liberar_orden(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/notify")
def post_notificar(
    orden_id: str,
    cuerpo: NotificarIn,
    contexto: ContextoDep,
) -> OrdenConEntregaOut:
    """Notificar al cliente y evaluar el cobro (ACT-RECEP).

    Compone PROC-REP-250 -> 260 -> 265, y PROC-REP-266 si queda saldo.
    """
    orden, puede_entregar = notificar(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
    )
    return _salida_con_entrega(orden, contexto, puede_entregar)


@router.post("/{orden_id}/payments")
def post_registrar_pago(
    orden_id: str,
    cuerpo: PagoIn,
    contexto: ContextoDep,
) -> OrdenConEntregaOut:
    """Registrar un Pago (capacidad transversal).

    FEAT-REP-007 / BR-REP-017. No corresponde a ningun PROC-REP-* propio
    y no exige un rol: el negocio todavia no definio cual. Despues del
    pago se revalida PROC-REP-265.
    """
    orden, puede_entregar = registrar_pago_de_orden(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        monto=cuerpo.monto,
        metodo=cuerpo.metodo,
    )
    return _salida_con_entrega(orden, contexto, puede_entregar)


@router.post("/{orden_id}/deliver")
def post_entregar(
    orden_id: str,
    cuerpo: EntregarIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Entregar el equipo (ACT-ADMIN).

    Compone PROC-REP-280 -> 270 -> EVT-REP-999. La Orden queda ENTREGADA.
    """
    orden = entregar(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/inform-rt")
def post_informar_rt(
    orden_id: str,
    contexto: ContextoDep,
) -> OrdenOut:
    """Informar el resultado a Gestion RT (HP-REP-002).

    Compone PROC-REP-250 -> 290. Exclusivo de RT_INTERNO: no notifica,
    no cobra y no entrega a un cliente. PROC-REP-290 es ``actor:
    ACT-SYSTEM`` en el Business Process: no hay un actor humano que
    autorizar, asi que este endpoint no recibe body.
    """
    orden = informar_rt(contexto, orden_id=orden_id)
    return _salida(orden, contexto)


@router.post("/{orden_id}/return-rt")
def post_devolver_rt(
    orden_id: str,
    cuerpo: DevolverRtIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Devolver el equipo a Gestion RT (HP-REP-002).

    Compone PROC-REP-270 (reutilizado) -> EVT-REP-999. No es una entrega
    comercial: no depende de Saldo ni de Pagos.
    """
    orden = devolver_rt(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
    )
    return _salida(orden, contexto)
