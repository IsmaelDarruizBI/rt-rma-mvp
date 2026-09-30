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
    devolver_rt,
    encolar_orden,
    entregar,
    informar_rt,
    iniciar_detalle,
    insumos_previstos_por_detalle,
    liberar_orden,
    listar_ordenes,
    nombres_de_tipo_por_detalle,
    notificar,
    obtener_orden,
    progreso,
    registrar_pago_de_orden,
    tomar_orden_en_estacion,
)
from app.domain.models import OrdenReparacion

from .dependencias import ContextoDep
from .schemas import (
    AprobarControlIn,
    CompletarEjecucionIn,
    CrearOrdenIn,
    CrearOrdenRtIn,
    DefinirReparacionIn,
    DevolverRtIn,
    EncolarIn,
    EntregarIn,
    IniciarDetalleIn,
    LiberarOrdenIn,
    NotificarIn,
    OrdenConEntregaOut,
    OrdenOut,
    OrdenResumenOut,
    PagoIn,
    TomarIn,
)

router = APIRouter(prefix="/api/orders", tags=["ordenes"])


def _salida(orden: OrdenReparacion, contexto: ApplicationContext) -> OrdenOut:
    """Vista HTTP de la Orden: progreso, acciones e insumos previstos.

    Los insumos previstos se resuelven contra el catalogo al responder.
    Con ellos la UI puede proponer que confirmar en PROC-REP-200 sin
    conocer ningun ID de insumo.
    """
    return OrdenOut.desde_dominio(
        orden,
        progreso=progreso(orden),
        acciones=acciones_disponibles(orden),
        insumos_previstos=insumos_previstos_por_detalle(contexto, orden),
        nombres_de_tipo=nombres_de_tipo_por_detalle(contexto, orden),
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
    """Definir la reparacion requerida (ACT-RECEP).

    Compone PROC-REP-045 -> 070 y, si ``finalizar_definicion`` es
    verdadero (default), tambien 050 -> 060 -> 080 -> 090 -> 140:
    despues de definir el Detalle, todo lo que sigue hasta HABILITADA es
    automatico y no cruza otra decision humana. La factibilidad (080)
    consulta el stock global y NO reserva.

    Con ``finalizar_definicion=False`` (Multi-Detalle) la Orden sigue en
    REQUERIMIENTO, lista para recibir otro Detalle con una nueva llamada
    a este mismo endpoint.
    """
    orden = definir_reparacion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        tipo_reparacion_id=cuerpo.tipo_reparacion_id,
        observaciones=cuerpo.observaciones,
        finalizar_definicion=cuerpo.finalizar_definicion,
    )
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
