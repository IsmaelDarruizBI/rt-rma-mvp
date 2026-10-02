"""HP-REP-003 (garantia de reparacion RMA) componiendo services.

La Orden de garantia nace de una Orden origen ENTREGADA (HP-REP-001
completo) y de 1..N de sus Detalles, sin PROC-REP-010/030. La revision
tecnica es obligatoria (BR-REP-019): 045 No -> 055 -> 050 -> 060 -> 065 ->
068 Si -> 075, y recien al finalizar la definicion converge con el
circuito tecnico normal. Su condicion comercial es NO_COBRABLE: nunca hay
pagos ni PROC-REP-266, y el saldo nominal > 0 no es una deuda.
"""

from decimal import Decimal

import pytest

from app.application import acciones_disponibles, progreso
from app.domain.models import (
    EstadoWorkflow,
    InsumoUtilizado,
    OrdenReparacion,
    OrigenOrden,
)
from app.services import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    aprobar_control_tecnico,
    calcular_puntaje,
    condicion_entrega_cumplida,
    crear_orden_garantia_rma,
    definir_prioridad,
    definir_reparacion_detail,
    definir_reparacion_detail_luego_revision,
    ejecutar_detalle,
    entregar_equipo,
    evaluar_situacion_orden,
    exigir_definicion_finalizable,
    generar_comprobante_final,
    generar_comprobante_recepcion,
    generar_movimientos_inventario,
    habilitar_orden,
    ingresar_a_cola,
    marcar_orden_en_revision,
    marcar_reparacion_lista,
    notificar_cliente,
    registrar_ejecucion_completada,
    registrar_pago,
    registrar_revision_tecnica,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_condicion_entrega,
    validar_estacion_trabajo,
    validar_factibilidad_detalles,
)
from tests.fixtures import flujo_mvp
from tests.fixtures import flujo_mvp_rt as flujo_rt
from tests.fixtures.catalogos_mvp import (
    ADMINISTRADOR,
    COMPATIBILIDADES,
    COORDINADOR,
    ESTACION,
    ESTACIONES,
    INSUMOS,
    INSUMOS_PREVISTOS,
    RECEPCION,
    TECNICO,
    TIPO_BATERIA,
    t,
)

ORIGEN_ID = "OR-001"
DETALLE_ORIGEN_ID = "DET-001"


def _garantia_creada(
    origen: OrdenReparacion | None = None,
    detalle_origen_ids: tuple[str, ...] = (DETALLE_ORIGEN_ID,),
):
    """Hasta PROC-REP-040: REQUERIMIENTO, sin Detalles."""
    return crear_orden_garantia_rma(
        orden_id="OR-002",
        orden_origen=origen or flujo_mvp.orden_entregada(),
        detalle_origen_ids=list(detalle_origen_ids),
        usuario=RECEPCION,
        fecha=t(300),
    )


def _garantia_revisada(
    origen: OrdenReparacion | None = None,
) -> OrdenReparacion:
    """045 No -> 055 -> 050 -> 060 -> 065: la revision es obligatoria."""
    orden = marcar_orden_en_revision(
        _garantia_creada(origen), usuario=RECEPCION, fecha=t(301)
    )
    orden = generar_comprobante_recepcion(orden, fecha=t(302))
    return registrar_revision_tecnica(
        orden, usuario=TECNICO, resultado="Falla cubierta.", fecha=t(303)
    )


def _garantia_habilitada(
    origen: OrdenReparacion | None = None,
) -> OrdenReparacion:
    """068 Si -> 075 y, al finalizar la definicion, 080 -> 090 -> 140."""
    orden = definir_reparacion_detail_luego_revision(
        _garantia_revisada(origen),
        detalle_id="DET-001",
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(304),
    )
    exigir_definicion_finalizable(orden, usuario=RECEPCION)
    orden, factible = validar_factibilidad_detalles(
        orden,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(305),
    )
    assert factible
    return habilitar_orden(orden, fecha=t(306))


def _garantia_lista_y_notificada(
    origen: OrdenReparacion | None = None,
) -> OrdenReparacion:
    """Circuito tecnico normal, hasta PROC-REP-260."""
    orden = definir_prioridad(
        _garantia_habilitada(origen),
        prioridad=1,
        usuario=COORDINADOR,
        fecha=t(307),
    )
    orden = ingresar_a_cola(orden, fecha=t(308))
    orden, _ = validar_estacion_trabajo(
        orden,
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(309),
    )
    orden = tomar_orden(
        orden, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(310)
    )
    orden = seleccionar_detalle(
        orden, detalle_id="DET-001", usuario=TECNICO, fecha=t(311)
    )
    orden, _ = validar_compatibilidad_detalle(
        orden,
        detalle_id="DET-001",
        compatibilidades=COMPATIBILIDADES,
        fecha=t(312),
    )
    orden = reservar_insumos_e_iniciar_ejecucion(
        orden,
        detalle_id="DET-001",
        usuario=TECNICO,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(313),
    )
    orden = ejecutar_detalle(
        orden, detalle_id="DET-001", usuario=TECNICO, fecha=t(314)
    )
    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
        ],
        usuario=TECNICO,
        fecha=t(315),
    )
    orden = generar_movimientos_inventario(
        orden, ejecucion_id=orden.ejecuciones[0].id, fecha=t(316)
    )
    orden, _ = evaluar_situacion_orden(orden, fecha=t(317))
    orden = aprobar_control_tecnico(orden, usuario=RECEPCION, fecha=t(318))
    orden = calcular_puntaje(orden, fecha=t(319))
    orden = marcar_reparacion_lista(orden, fecha=t(320))
    return notificar_cliente(orden, usuario=RECEPCION, fecha=t(321))


# --- Creacion ------------------------------------------------------------


def test_crea_una_orden_nueva_vinculada_a_la_origen():
    origen = flujo_mvp.orden_entregada()
    orden = _garantia_creada(origen)

    assert orden.id != origen.id
    assert orden.origen is OrigenOrden.RMA_GARANTIA_REPARACION
    assert orden.orden_origen_id == origen.id
    assert orden.estado_workflow is EstadoWorkflow.REQUERIMIENTO
    assert orden.cliente == origen.cliente
    assert orden.equipo == origen.equipo
    # Copias, no instancias compartidas.
    assert orden.cliente is not origen.cliente
    assert orden.equipo is not origen.equipo


def test_no_copia_historia_tecnica_de_la_orden_origen():
    orden = _garantia_creada()

    assert orden.tomas == []
    assert orden.ejecuciones == []
    assert orden.movimientos_insumo == []
    assert orden.resumen_pago.pagos == []
    assert not orden.documentos.comprobante_recepcion.generado
    assert not orden.documentos.comprobante_final.generado
    assert not orden.documentos.garantia_reparacion.generado
    assert orden.reparaciones_detail == []


def test_historial_inicial_es_035_y_040_sin_010_ni_030():
    orden = _garantia_creada()

    assert [(p.referencia_id, p.accion) for p in orden.historial] == [
        ("PROC-REP-035", "IDENTIFICAR_REPARACION_ORIGINAL_GARANTIA"),
        ("PROC-REP-040", "CREAR_ORDEN"),
    ]
    assert f"orden_origen_id={ORIGEN_ID}" in orden.historial[0].observacion
    assert (
        f"detalles_origen_ids={DETALLE_ORIGEN_ID}"
        in orden.historial[0].observacion
    )


def test_detalle_de_garantia_vincula_al_origen_con_snapshot_propio():
    orden = _garantia_habilitada()
    (detalle,) = orden.reparaciones_detail

    assert detalle.detalle_origen_id == DETALLE_ORIGEN_ID
    assert detalle.tipo_reparacion_id == TIPO_BATERIA.id
    assert detalle.precio == TIPO_BATERIA.precio
    assert detalle.puntaje == TIPO_BATERIA.puntaje
    assert detalle.garantia_dias == TIPO_BATERIA.garantia_dias


def test_recorrido_inicial_035_a_140_con_revision_obligatoria():
    orden = _garantia_habilitada()

    assert [p.referencia_id for p in orden.historial] == [
        "PROC-REP-035",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-055",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-065",
        "PROC-REP-068",
        "PROC-REP-075",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]
    assert orden.historial[2].observacion == "No"
    assert orden.estado_workflow is EstadoWorkflow.HABILITADA
    assert orden.documentos.comprobante_recepcion.generado


def test_la_garantia_no_admite_la_definicion_directa_070():
    """Sin bypass: el Tipo origen no se copia ni se define sin revision."""
    for orden in (_garantia_creada(), _garantia_revisada()):
        with pytest.raises(PrecondicionInvalidaError):
            definir_reparacion_detail(
                orden,
                detalle_id="DET-001",
                tipo_reparacion=TIPO_BATERIA,
                usuario=RECEPCION,
                fecha=t(304),
            )


def test_la_orden_origen_no_se_modifica():
    origen = flujo_mvp.orden_entregada()
    foto = origen.model_dump()

    orden, _ = validar_condicion_entrega(
        _garantia_lista_y_notificada(origen), fecha=t(320)
    )
    orden = generar_comprobante_final(orden, fecha=t(321))
    orden = entregar_equipo(orden, usuario=ADMINISTRADOR, fecha=t(322))
    assert orden.orden_origen_id == origen.id

    assert origen.model_dump() == foto


# --- Validaciones negativas ----------------------------------------------


def test_rechaza_orden_origen_no_entregada():
    with pytest.raises(PrecondicionInvalidaError):
        _garantia_creada(flujo_mvp.orden_reparacion_lista())


def test_rechaza_detalle_origen_inexistente():
    for seleccion in (("DET-999",), (DETALLE_ORIGEN_ID, "DET-999")):
        with pytest.raises(EntidadNoEncontradaError, match="DET-999"):
            _garantia_creada(detalle_origen_ids=seleccion)


@pytest.mark.parametrize(
    "seleccion", [(), (DETALLE_ORIGEN_ID, DETALLE_ORIGEN_ID)]
)
def test_rechaza_seleccion_vacia_o_repetida(seleccion):
    with pytest.raises(PrecondicionInvalidaError):
        _garantia_creada(detalle_origen_ids=seleccion)


@pytest.mark.parametrize("usuario", [TECNICO, ADMINISTRADOR, COORDINADOR])
def test_rechaza_usuario_que_no_es_recepcion(usuario):
    with pytest.raises(Exception) as error:
        crear_orden_garantia_rma(
            orden_id="OR-002",
            orden_origen=flujo_mvp.orden_entregada(),
            detalle_origen_ids=[DETALLE_ORIGEN_ID],
            usuario=usuario,
            fecha=t(300),
        )
    assert "RECEPCION" in str(error.value).upper()


def test_rechaza_orden_origen_sin_cliente():
    origen = flujo_mvp.orden_entregada().model_copy(update={"cliente": None})
    with pytest.raises(PrecondicionInvalidaError):
        _garantia_creada(origen)


# --- Acciones disponibles -------------------------------------------------


def test_orden_entregada_publica_una_unica_garantia_a_nivel_orden():
    acciones = acciones_disponibles(flujo_mvp.orden_entregada())

    # Una accion de Orden: la seleccion de 1..N Detalles es del formulario.
    assert [(a.codigo, a.roles, a.detalle_id) for a in acciones] == [
        ("INICIAR_GARANTIA_RMA", (RECEPCION.rol,), None),
    ]


def test_orden_no_entregada_no_publica_garantia():
    for orden in (
        flujo_mvp.orden_creada(),
        flujo_mvp.orden_reparacion_lista(),
    ):
        assert "INICIAR_GARANTIA_RMA" not in {
            a.codigo for a in acciones_disponibles(orden)
        }


# --- Comercial -------------------------------------------------------------


def test_garantia_no_ofrece_pago_y_el_service_lo_rechaza():
    orden = _garantia_lista_y_notificada()

    assert "REGISTRAR_PAGO" not in {
        a.codigo for a in acciones_disponibles(orden)
    }
    with pytest.raises(PrecondicionInvalidaError):
        registrar_pago(
            orden,
            monto=Decimal("1"),
            metodo="EFECTIVO",
            usuario=ADMINISTRADOR,
            fecha=t(320),
        )


def test_265_aprueba_por_no_cobrable_con_saldo_nominal_y_sin_266():
    orden = _garantia_lista_y_notificada()
    assert orden.saldo > 0
    assert orden.resumen_pago.pagado == 0

    orden, puede_entregar = validar_condicion_entrega(orden, fecha=t(320))

    assert puede_entregar is True
    assert orden.historial[-1].referencia_id == "PROC-REP-265"
    assert orden.historial[-1].observacion == "NO_COBRABLE_POR_ORIGEN"
    assert "PROC-REP-266" not in [p.referencia_id for p in orden.historial]
    assert orden.saldo > 0  # nominal: no se fuerza a 0 ni a PAGADO


def test_comprobante_final_y_entrega_con_saldo_nominal():
    orden, _ = validar_condicion_entrega(
        _garantia_lista_y_notificada(), fecha=t(320)
    )
    orden = generar_comprobante_final(orden, fecha=t(321))
    orden = entregar_equipo(orden, usuario=ADMINISTRADOR, fecha=t(322))

    assert orden.estado_workflow is EstadoWorkflow.ENTREGADA
    assert orden.current_process == "EVT-REP-999"
    assert orden.resumen_pago.pagos == []
    assert orden.documentos.comprobante_final.generado
    assert orden.documentos.garantia_reparacion.generado

    vistos = {p.referencia_id for p in orden.historial}
    assert vistos.isdisjoint(
        {"PROC-REP-010", "PROC-REP-030", "PROC-REP-266", "PROC-REP-290"}
    )


def test_cliente_externo_sigue_exigiendo_saldo_cero():
    # Defensa en profundidad: aun habiendo pasado por 265 (gate de
    # proceso), un Origen COBRABLE con saldo > 0 no emite el comprobante
    # final ni se entrega. No es un estado alcanzable por la API (265 No
    # salta a 266), pero el service lo protege igual.
    orden = flujo_mvp.orden_reparacion_lista().model_copy(
        update={"current_process": "PROC-REP-265"}
    )
    assert orden.origen is OrigenOrden.CLIENTE_EXTERNO
    assert orden.estado_workflow is EstadoWorkflow.REPARACION_LISTA
    assert orden.saldo > 0
    assert condicion_entrega_cumplida(orden) is False

    with pytest.raises(PrecondicionInvalidaError, match="saldo pendiente"):
        generar_comprobante_final(orden, fecha=t(190))
    with pytest.raises(PrecondicionInvalidaError, match="saldo pendiente"):
        entregar_equipo(orden, usuario=ADMINISTRADOR, fecha=t(195))


def test_comprobante_final_sin_265_informa_el_nodo_real_en_el_mensaje():
    orden = flujo_mvp.orden_reparacion_lista()
    assert orden.current_process == "PROC-REP-260"

    with pytest.raises(PrecondicionInvalidaError, match="PROC-REP-260"):
        generar_comprobante_final(orden, fecha=t(190))


# --- Progreso --------------------------------------------------------------


def test_progreso_de_garantia_refleja_hp3():
    orden, _ = validar_condicion_entrega(
        _garantia_lista_y_notificada(), fecha=t(320)
    )
    pasos = progreso(orden)
    ids = [p.process_id for p in pasos]

    assert ids[0] == "PROC-REP-035"
    assert ids[-1] == "EVT-REP-999"
    assert ids.index("PROC-REP-212") == ids.index("PROC-REP-180") + 1
    assert ids.index("PROC-REP-181") == ids.index("PROC-REP-212") + 1
    assert not {
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-266",
        "PROC-REP-290",
    } & set(ids)
    alcanzados = [p.process_id for p in pasos if p.alcanzado]
    assert alcanzados[-1] == "PROC-REP-265"
    assert len(alcanzados) == len(ids) - 3  # faltan 280, 270 y EVT-REP-999


def test_rt_interno_terminado_no_ofrece_garantia_rma():
    orden = flujo_rt.orden_rt_devuelta()

    assert orden.current_process == "EVT-REP-999"
    assert orden.estado_workflow is not EstadoWorkflow.ENTREGADA
    assert acciones_disponibles(orden) == []


def test_comprobante_final_exige_venir_de_265():
    # Notificada (260) pero sin haber pasado por PROC-REP-265.
    orden = _garantia_lista_y_notificada()
    assert orden.current_process == "PROC-REP-260"
    with pytest.raises(PrecondicionInvalidaError):
        generar_comprobante_final(orden, fecha=t(321))
