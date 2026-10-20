"""Endpoints de Ordenes de Reparacion.

Cada POST representa UNA intencion de una persona, no un nodo del
proceso. Una accion humana arrastra los nodos ACT-SYSTEM que la siguen
hasta la proxima frontera de actor humano; ahi se corta. Por eso no hay
un endpoint por nodo ni nada que ejecute el escenario completo de una.

El router es fino a proposito: valida la forma del request, delega en
``app.application`` y arma la respuesta. No decide nada de negocio y no
atrapa excepciones -de eso se ocupa ``errores.py``-.
"""

from fastapi import APIRouter, Response, status

from app.application import (
    ApplicationContext,
    acciones_complementarias,
    acciones_de_autorizacion,
    acciones_de_cancelacion,
    acciones_de_custodia,
    acciones_disponibles,
    acciones_financieras,
    agregar_observacion_recepcion,
    ajustar_garantia,
    anular_pago_de_orden,
    aplicar_descuento_de_orden,
    aprobar_control,
    autorizaciones_de_orden,
    cambiar_prioridad_de_orden,
    cancelar_detalle,
    cancelar_orden,
    completar_ejecucion,
    confirmar_recepcion,
    crear_orden,
    crear_orden_rt,
    definir_reparacion,
    definir_reparacion_desde_revision,
    detalles_origen_de,
    devolver_rt,
    documento_de_orden,
    documentos_de_orden,
    emitir_comprobante_autorizacion,
    emitir_comprobante_recepcion,
    encolar_orden,
    entregar,
    enviar_a_revision,
    esperar_recursos,
    finalizar_definicion,
    finalizar_sin_reparacion,
    forzar_detalle_por_recursos,
    generar_comprobante_ingreso,
    impacto_override,
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
    pdf_documento_de_orden,
    pendientes_de_autorizacion,
    progreso,
    realizar_revision,
    rechazar_control,
    redefinir_detalle,
    registrar_decision_cliente,
    registrar_desistimiento,
    registrar_devolucion,
    registrar_devolucion_de_dinero,
    registrar_no_recepcion,
    registrar_pago_de_orden,
    registrar_recepcion,
    requerir_redefinicion_ejecucion,
    revalidar_recursos,
    revisar_detalle,
    situacion_de_orden,
    situacion_operativa,
    tomar_orden_en_estacion,
    vista_previa_documento,
)
from app.domain.models import OrdenReparacion, TipoDocumento
from app.domain.prioridad import clave_de_prioridad
from app.services import DecisionDetalle

from .dependencias import ContextoDep
from .schemas import (
    AjustarGarantiaIn,
    AnularPagoIn,
    AprobarControlIn,
    AutorizacionesOrdenOut,
    CambiarPrioridadIn,
    CancelarDetalleIn,
    CancelarOrdenIn,
    CompletarEjecucionIn,
    ConfirmarRecepcionIn,
    CrearOrdenIn,
    CrearOrdenRtIn,
    CustodiaOut,
    DefinirReparacionDesdeRevisionIn,
    DefinirReparacionIn,
    DescuentoIn,
    DesistimientoIn,
    DevolucionDineroIn,
    DevolverRtIn,
    DocumentoEmitidoOut,
    DocumentosOrdenOut,
    DocumentosOut,
    EmitirComprobanteAutorizacionIn,
    EmitirDocumentoIn,
    EncolarIn,
    EntregarIn,
    EnviarARevisionIn,
    EquipoNoRecibidoIn,
    FinalizarDefinicionIn,
    FinalizarSinReparacionIn,
    FinanzasOrdenOut,
    GenerarComprobanteIngresoIn,
    ImpactoOverrideOut,
    IniciarDetalleIn,
    IniciarGarantiaRmaIn,
    InterrumpirEjecucionIn,
    LiberarOrdenIn,
    NotificarIn,
    ObservacionRecepcionIn,
    OrdenConEntregaOut,
    OrdenOut,
    OrdenResumenOut,
    OverrideRecursosIn,
    PagoIn,
    PendienteAutorizacionOut,
    RecepcionOut,
    RechazarControlIn,
    RedefinirDetalleIn,
    RegistrarDecisionClienteIn,
    RegistrarDevolucionIn,
    RegistrarRecepcionIn,
    RequiereRedefinicionIn,
    RevisionDetalleIn,
    RevisionTecnicaIn,
    TomarIn,
    VistaPreviaDocumentoOut,
)

router = APIRouter(prefix="/api/orders", tags=["ordenes"])


def _salida(orden: OrdenReparacion, contexto: ApplicationContext) -> OrdenOut:
    """Vista HTTP de la Orden: progreso, acciones e insumos previstos.

    Los insumos previstos se resuelven contra el catalogo al responder.
    Con ellos la UI puede proponer que confirmar en PROC-REP-200 sin
    conocer ningun ID de insumo. Lo mismo con los Detalles origen de una
    garantia RMA: su Tipo se lee de la Orden origen.
    """
    acciones = acciones_disponibles(orden)
    nombres = nombres_de_tipo_por_detalle(contexto, orden)
    autorizacion = acciones_de_autorizacion(orden)
    financieras = acciones_financieras(orden)
    custodia = acciones_de_custodia(orden)
    return OrdenOut.desde_dominio(
        orden,
        progreso=progreso(orden),
        acciones=acciones,
        insumos_previstos=insumos_previstos_por_detalle(contexto, orden),
        nombres_de_tipo=nombres,
        detalles_origen=detalles_origen_de(contexto, orden),
        acciones_cancelacion=acciones_de_cancelacion(orden),
        acciones_autorizacion=autorizacion,
        acciones_financieras=financieras,
        acciones_custodia=custodia,
        acciones_complementarias=acciones_complementarias(orden),
        situacion=situacion_operativa(
            orden,
            acciones=acciones,
            acciones_autorizacion=autorizacion,
            acciones_financieras=financieras,
            acciones_custodia=custodia,
            nombres_de_detalle=nombres,
        ),
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


# --- Lectura -----------------------------------------------------------------


@router.get("")
def get_ordenes(contexto: ContextoDep) -> list[OrdenResumenOut]:
    """Listado de Ordenes, con la situacion operativa de cada una.

    Cada fila trae tambien su lugar en el orden por prioridad
    (``clave_de_prioridad``). Solo lectura: calcular la situacion o la
    prioridad no modifica ninguna Orden.
    """
    ordenes = listar_ordenes(contexto)
    posiciones = {
        orden.id: posicion
        for posicion, orden in enumerate(
            sorted(ordenes, key=clave_de_prioridad)
        )
    }
    return [
        OrdenResumenOut.desde_dominio(
            orden,
            situacion=situacion_de_orden(orden),
            posicion_por_prioridad=posiciones[orden.id],
        )
        for orden in ordenes
    ]


@router.get("/authorizations/pending")
def get_pendientes_de_autorizacion(
    contexto: ContextoDep,
) -> list[PendienteAutorizacionOut]:
    """Detalles que esperan la decision del cliente, de todas las Ordenes.

    Solo los que Recepcion puede decidir ahora (definicion finalizada,
    Orden abierta). Solo lectura.
    """
    return [
        PendienteAutorizacionOut.desde_aplicacion(pendiente)
        for pendiente in pendientes_de_autorizacion(contexto)
    ]


@router.get("/{orden_id}")
def get_orden(orden_id: str, contexto: ContextoDep) -> OrdenOut:
    """Una Orden con su detalle completo."""
    return _salida(obtener_orden(contexto, orden_id), contexto)


@router.get("/{orden_id}/finances")
def get_finanzas(orden_id: str, contexto: ContextoDep) -> FinanzasOrdenOut:
    """Saldo, credito a favor y movimientos de dinero, en orden cronologico.

    Pagos, anulaciones y devoluciones. Solo lectura.
    """
    return FinanzasOrdenOut.desde_dominio(obtener_orden(contexto, orden_id))


@router.get("/{orden_id}/custody")
def get_custodia(orden_id: str, contexto: ContextoDep) -> dict:
    """Custodia del equipo y datos del ingreso. Solo lectura.

    La custodia es independiente del comprobante de recepcion: se informa
    aparte si el comprobante se emitio.
    """
    orden = obtener_orden(contexto, orden_id)
    return {
        "orden_id": orden.id,
        "custodia": CustodiaOut.desde_dominio(orden),
        "recepcion": (
            RecepcionOut.desde_dominio(orden.recepcion)
            if orden.recepcion is not None
            else None
        ),
    }


@router.get("/{orden_id}/documents")
def get_documentos(orden_id: str, contexto: ContextoDep) -> DocumentosOrdenOut:
    """Documentos emitidos de la Orden, con su contenido. Solo lectura.

    Tambien de una Orden cerrada: un documento emitido se puede volver a
    ver e imprimir, sin modificar la Orden.
    """
    documentos = documentos_de_orden(contexto, orden_id)
    orden = documentos.orden
    vigentes = {
        documento.tipo: documento.id for documento in documentos.emitidos
    }
    return DocumentosOrdenOut(
        orden_id=orden.id,
        cerrada=orden.esta_cerrada,
        emitidos=[
            DocumentoEmitidoOut.desde_dominio(
                documento, vigente=vigentes[documento.tipo] == documento.id
            )
            for documento in documentos.emitidos
        ],
        marcas=DocumentosOut(**orden.documentos.model_dump()),
        previsualizables=documentos.previsualizables,
    )


@router.get("/{orden_id}/documents/preview/{tipo}")
def get_vista_previa_documento(
    orden_id: str,
    tipo: TipoDocumento,
    contexto: ContextoDep,
) -> VistaPreviaDocumentoOut:
    """Vista previa con los datos vigentes. NO emite ni guarda nada."""
    return VistaPreviaDocumentoOut(
        orden_id=orden_id,
        tipo=tipo,
        contenido=vista_previa_documento(contexto, orden_id, tipo),
    )


@router.get(
    "/{orden_id}/documents/{documento_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_documento_pdf(
    orden_id: str,
    documento_id: str,
    contexto: ContextoDep,
) -> Response:
    """El PDF de un documento emitido (ingreso o autorizacion).

    Se arma del snapshot cada vez: la misma version da el mismo PDF. Solo
    lectura: descargarlo o compartirlo no registra que el cliente lo
    recibio.
    """
    nombre, contenido = pdf_documento_de_orden(
        contexto, orden_id, documento_id
    )
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get("/{orden_id}/documents/{documento_id}")
def get_documento(
    orden_id: str,
    documento_id: str,
    contexto: ContextoDep,
) -> DocumentoEmitidoOut:
    """Un documento emitido, tal como se entrego al cliente."""
    documento = documento_de_orden(contexto, orden_id, documento_id)
    orden = obtener_orden(contexto, orden_id)
    ultimo = [
        emitido.id
        for emitido in orden.documentos.emitidos
        if emitido.tipo is documento.tipo
    ][-1]
    return DocumentoEmitidoOut.desde_dominio(
        documento, vigente=ultimo == documento.id
    )


@router.get("/{orden_id}/authorizations")
def get_autorizaciones(
    orden_id: str,
    contexto: ContextoDep,
) -> AutorizacionesOrdenOut:
    """Autorizacion del cliente de cada Detalle (BR-REP-028).

    Estado y situacion de la definicion vigente, la decision vigente y la
    historia completa de decisiones. Solo lectura.
    """
    return AutorizacionesOrdenOut.desde_aplicacion(
        autorizaciones_de_orden(contexto, orden_id)
    )


@router.get("/{orden_id}/details/{detalle_id}/resources/override-preview")
def get_impacto_override(
    orden_id: str,
    detalle_id: str,
    contexto: ContextoDep,
) -> ImpactoOverrideOut:
    """Impacto en el stock de forzar el Detalle (E3, solo lectura).

    Stock fisico, reservado por otras Ordenes y por esta, disponible,
    requerido y disponible resultante de cada insumo previsto. Es lo que
    el Coordinador confirma con ``confirmado: true`` en el override.
    """
    return ImpactoOverrideOut.desde_aplicacion(
        impacto_override(contexto, orden_id=orden_id, detalle_id=detalle_id)
    )


# --- Comandos del Happy Path -------------------------------------------------


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
        datos_recepcion=(
            cuerpo.recepcion.a_dominio() if cuerpo.recepcion else None
        ),
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
        datos_recepcion=(
            cuerpo.recepcion.a_dominio() if cuerpo.recepcion else None
        ),
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
        descripcion=cuerpo.descripcion,
        precio=cuerpo.precio,
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
        datos_recepcion=(
            cuerpo.recepcion.a_dominio() if cuerpo.recepcion else None
        ),
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
        descripcion=cuerpo.descripcion,
        precio=cuerpo.precio,
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
    130 -> 140. Exige ``confirmado: true`` (E3): sin confirmacion
    explicita del impacto responde 409 CONFIRMACION_REQUERIDA.
    """
    orden = forzar_detalle_por_recursos(
        contexto,
        orden_id=orden_id,
        detalle_id=detalle_id,
        usuario_id=cuerpo.usuario_id,
        motivo=cuerpo.motivo,
        confirmado=cuerpo.confirmado,
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
    PROC-REP-120; con un Detalle trabajable continua a PROC-REP-140, o a
    PROC-REP-211 (cola) si la Orden ya se habilito: 140 no se repite.
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
    vuelve a DEFINIDO y la toma sigue activa. El motivo es obligatorio.
    """
    orden, _ = interrumpir_ejecucion(
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


@router.post("/{orden_id}/control/reject")
def post_rechazar_control(
    orden_id: str,
    cuerpo: RechazarControlIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Rechazar el control de UN Detalle (ACT-RECEP).

    Compone PROC-REP-220 -> 230 ("No") -> 235 -> 211: el Detalle se
    reabre para retrabajo -una Ejecucion nueva- y la Orden vuelve a la
    cola. El motivo es obligatorio.
    """
    orden = rechazar_control(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        detalle_id=cuerpo.detalle_id,
        motivo=cuerpo.motivo,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/details/{detalle_id}/cancel")
def post_cancelar_detalle(
    orden_id: str,
    detalle_id: str,
    cuerpo: CancelarDetalleIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Cancelar UN Detalle pendiente (PROC-REP-300 -> 211, BR-REP-014).

    Nunca uno COMPLETO ni con una Ejecucion activa. Motivo obligatorio.
    """
    orden = cancelar_detalle(
        contexto,
        orden_id=orden_id,
        detalle_id=detalle_id,
        usuario_id=cuerpo.usuario_id,
        motivo=cuerpo.motivo,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/cancel")
def post_cancelar_orden(
    orden_id: str,
    cuerpo: CancelarOrdenIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Cancelar la Orden / sus trabajos pendientes (PROC-REP-305 / 306).

    Cancela los Detalles pendientes; lo realizado sigue al cierre. Sin
    trabajo realizado la Orden queda CANCELADA. Con una Ejecucion activa
    no se cancela nada (409). Motivo obligatorio.
    """
    orden = cancelar_orden(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        motivo=cuerpo.motivo,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/authorizations")
def post_registrar_decision_cliente(
    orden_id: str,
    cuerpo: RegistrarDecisionClienteIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Registrar la decision del cliente por Detalle (ACT-RECEP).

    Compone PROC-REP-046 (por Detalle) -> 047 -> 300/305 para los
    rechazados, y la factibilidad de los autorizados (080 -> 090 -> 140 |
    100 | 211). Un Detalle sin respuesta no se incluye y sigue pendiente.
    Respuestas duplicadas, de una definicion anterior o sobre Detalles que
    ya no esperan decision: 409, sin aplicar nada.
    """
    orden = registrar_decision_cliente(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        canal=cuerpo.canal,
        observaciones=cuerpo.observaciones,
        decisiones=[
            DecisionDetalle(
                detalle_id=decision.detalle_id,
                version_definicion=decision.version_definicion,
                resultado=decision.resultado,
            )
            for decision in cuerpo.decisiones
        ],
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/withdrawal")
def post_desistir_de_todo(
    orden_id: str,
    cuerpo: DesistimientoIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """El cliente desiste de TODOS los trabajos cancelables (ACT-RECEP).

    Los pendientes se rechazan y los autorizados se cancelan por
    desistimiento (046 -> 047 -> 305 -> 211); lo COMPLETO se conserva. Con
    una Ejecucion activa o reservas sin conciliar no se cancela nada (409,
    con los Detalles que lo impiden). Motivo obligatorio.
    """
    orden = registrar_desistimiento(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        canal=cuerpo.canal,
        motivo=cuerpo.motivo,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/details/{detalle_id}/withdrawal")
def post_desistir_de_detalle(
    orden_id: str,
    detalle_id: str,
    cuerpo: DesistimientoIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """El cliente desiste de UN trabajo que habia autorizado (ACT-RECEP).

    046 -> 047 -> 300 -> 211. La autorizacion anterior queda en la
    historia. Un Detalle pendiente se rechaza (``.../authorizations``), no
    se desiste. Motivo obligatorio.
    """
    orden = registrar_desistimiento(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        canal=cuerpo.canal,
        motivo=cuerpo.motivo,
        detalle_id=detalle_id,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/return-equipment")
def post_registrar_devolucion(
    orden_id: str,
    cuerpo: RegistrarDevolucionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Devolver el equipo de una Orden CANCELADA (PROC-REP-270 -> fin).

    Exige la custodia confirmada. Sin cobro ni garantia: emite el
    comprobante de devolucion sin reparacion. La Orden sigue CANCELADA y
    queda cerrada (o espera la devolucion de dinero pendiente).
    """
    orden = registrar_devolucion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        recibido_por=cuerpo.recibido_por,
        observaciones=cuerpo.observaciones,
        identificacion_receptor=cuerpo.identificacion_receptor,
    )
    return _salida(orden, contexto)


# --- Recepcion fisica y custodia ---------------------------------------------


@router.put("/{orden_id}/reception")
def put_recepcion(
    orden_id: str,
    cuerpo: RegistrarRecepcionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Registrar o corregir los datos del ingreso (ACT-RECEP).

    Solo antes de confirmar la recepcion; conserva la version anterior. En
    una Orden anterior al registro de recepcion, es la regularizacion.
    """
    orden = registrar_recepcion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        datos=cuerpo.datos(),
        equipo=cuerpo.equipo.a_dominio() if cuerpo.equipo else None,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/reception/confirm")
def post_confirmar_recepcion(
    orden_id: str,
    cuerpo: ConfirmarRecepcionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Confirmar que el equipo quedo fisicamente en el local (custodia)."""
    orden = confirmar_recepcion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        observaciones=cuerpo.observaciones,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/reception/not-received")
def post_equipo_no_recibido(
    orden_id: str,
    cuerpo: EquipoNoRecibidoIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Confirmar que el equipo nunca ingreso (Orden cancelada, con motivo).

    Alternativa explicita a confirmar la recepcion: sin equipo que
    devolver, la Orden pasa por la verificacion financiera y cierra, o
    espera la devolucion del saldo a favor. Se rechaza si algo en la Orden
    prueba que el equipo estuvo en el local.
    """
    orden = registrar_no_recepcion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        motivo=cuerpo.motivo,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/reception/notes")
def post_observacion_recepcion(
    orden_id: str,
    cuerpo: ObservacionRecepcionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Agregar una observacion complementaria del ingreso (o interna)."""
    orden = agregar_observacion_recepcion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        texto=cuerpo.texto,
        interna=cuerpo.interna,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/documents/reception-receipt")
def post_emitir_comprobante_recepcion(
    orden_id: str,
    cuerpo: EmitirDocumentoIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Emitir una version nueva del comprobante de recepcion (ACT-RECEP).

    La primera la emite el proceso (PROC-REP-060). Una version nueva exige
    motivo y conserva la anterior; un reintento no la duplica.
    """
    orden = emitir_comprobante_recepcion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        motivo=cuerpo.motivo,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/documents/intake-receipt")
def post_generar_comprobante_ingreso(
    orden_id: str,
    cuerpo: GenerarComprobanteIngresoIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Generar el comprobante de ingreso y autorizacion (ACT-RECEP).

    Ingreso inicial de CLIENTE_EXTERNO, en una sola operacion: confirma la
    recepcion fisica, finaliza la definicion (PROC-REP-050/060),
    factibilidad y habilitacion, registra la autorizacion de los trabajos
    cargados (046/047) y emite el comprobante; la Orden entra a la cola
    con prioridad 4. Un reintento no duplica nada. Generarlo no registra
    que el cliente lo recibio.
    """
    orden = generar_comprobante_ingreso(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        canal=cuerpo.canal,
        checkin=cuerpo.checkin,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/documents/authorization-receipt")
def post_emitir_comprobante_autorizacion(
    orden_id: str,
    cuerpo: EmitirComprobanteAutorizacionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Emitir el comprobante de los trabajos autorizados (ACT-RECEP).

    Solo a pedido. Lista los Detalles con autorizacion vigente, sin los
    pendientes, rechazados ni cancelados. Si lo autorizado no cambio desde
    la ultima version, no se duplica; si cambio, se emite la version
    siguiente y la anterior se conserva.
    """
    orden = emitir_comprobante_autorizacion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
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

    Otro tecnico (o Coordinacion) puede liberar la de su titular con
    motivo y confirmacion; una reparacion en curso se interrumpe antes.
    """
    orden = liberar_orden(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        motivo=cuerpo.motivo,
        confirmado=cuerpo.confirmado,
        insumos_utilizados=[
            insumo.a_dominio() for insumo in cuerpo.insumos_utilizados
        ],
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/priority")
def post_cambiar_prioridad(
    orden_id: str,
    cuerpo: CambiarPrioridadIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Cambiar la prioridad de una Orden en el taller (ACC-REP-007).

    Tecnico, Coordinacion o Recepcion; en cola o en reparacion. La cola se
    reordena sola. No es ingresarla a la cola: eso ya ocurrio.
    """
    orden = cambiar_prioridad_de_orden(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        prioridad=cuerpo.prioridad,
        motivo=cuerpo.motivo,
    )
    return _salida(orden, contexto)


@router.post("/{orden_id}/discount")
def post_aplicar_descuento(
    orden_id: str,
    cuerpo: DescuentoIn,
    contexto: ContextoDep,
) -> OrdenConEntregaOut:
    """Aplicar, cambiar o quitar el descuento comercial (Recepcion).

    Porcentaje o importe fijo, con motivo. No toca el precio de ningun
    trabajo ni los Pagos; se rechaza si deja el total por debajo de lo ya
    pagado. En el cierre comercial se revalida PROC-REP-265.
    """
    orden, puede_entregar = aplicar_descuento_de_orden(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        tipo=cuerpo.tipo,
        valor=cuerpo.valor,
        motivo=cuerpo.motivo,
    )
    return _salida_con_entrega(orden, contexto, puede_entregar)


@router.post("/{orden_id}/details/{detalle_id}/warranty")
def post_ajustar_garantia(
    orden_id: str,
    detalle_id: str,
    cuerpo: AjustarGarantiaIn,
    contexto: ContextoDep,
) -> OrdenOut:
    """Ajustar el plazo de garantia de un trabajo (Recepcion o Coordinacion).

    Antes de la entrega, con motivo. Se conservan la sugerida y cada
    ajuste; el plazo corre desde la entrega.
    """
    orden = ajustar_garantia(
        contexto,
        orden_id=orden_id,
        detalle_id=detalle_id,
        usuario_id=cuerpo.usuario_id,
        dias=cuerpo.dias,
        motivo=cuerpo.motivo,
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

    FEAT-REP-007 / BR-REP-017. No corresponde a ningun PROC-REP-* propio.
    Roles: Administracion, Recepcion o Coordinacion (nunca un Tecnico).
    Medio del catalogo, importe positivo con dos decimales como maximo y
    sin superar el saldo pendiente; ``operacion_id`` evita duplicarlo.
    En el cierre comercial se revalida PROC-REP-265.
    """
    orden, puede_entregar = registrar_pago_de_orden(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        monto=cuerpo.monto,
        metodo=cuerpo.metodo,
        referencia=cuerpo.referencia,
        operacion_id=cuerpo.operacion_id,
    )
    return _salida_con_entrega(orden, contexto, puede_entregar)


@router.post("/{orden_id}/payments/{pago_id}/void")
def post_anular_pago(
    orden_id: str,
    pago_id: str,
    cuerpo: AnularPagoIn,
    contexto: ContextoDep,
) -> OrdenConEntregaOut:
    """Anular un Pago registrado por error (Administracion, con motivo).

    El Pago se conserva con su anulacion y deja de contar como pagado. No
    se anula dos veces ni con devoluciones registradas.
    """
    orden, puede_entregar = anular_pago_de_orden(
        contexto,
        orden_id=orden_id,
        pago_id=pago_id,
        usuario_id=cuerpo.usuario_id,
        motivo=cuerpo.motivo,
    )
    return _salida_con_entrega(orden, contexto, puede_entregar)


@router.post("/{orden_id}/refunds")
def post_devolver_dinero(
    orden_id: str,
    cuerpo: DevolucionDineroIn,
    contexto: ContextoDep,
) -> OrdenConEntregaOut:
    """Devolver dinero al cliente desde un Pago (V1.4 PROC-REP-267).

    Solo con saldo a favor del cliente y sin superarlo, ni superar lo que
    queda por devolver del Pago. Administracion o Recepcion, con motivo.
    Revalida la entrega o, en una Orden CANCELADA, su cierre.
    """
    orden, puede_entregar = registrar_devolucion_de_dinero(
        contexto,
        orden_id=orden_id,
        pago_id=cuerpo.pago_id,
        usuario_id=cuerpo.usuario_id,
        monto=cuerpo.monto,
        medio=cuerpo.medio,
        motivo=cuerpo.motivo,
        referencia=cuerpo.referencia,
        operacion_id=cuerpo.operacion_id,
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
    Exige la custodia confirmada y quien retira; emite el comprobante final
    y la garantia, que empieza con esta entrega.
    """
    orden = entregar(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        recibido_por=cuerpo.recibido_por,
        identificacion_receptor=cuerpo.identificacion_receptor,
        observaciones=cuerpo.observaciones,
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
