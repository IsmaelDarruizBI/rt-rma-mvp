"""HP-REP-001 ejecutado de punta a punta componiendo services.

El escenario no vive en el codigo productivo: se compone aqui, paso a
paso, con los mismos services que despues usara la API. Cada bloque
corresponde a una transicion real de
``business/scenarios/repair-management-scenarios-v1.3.yaml``.

Arranca desde cero: no usa el fixture que construye la Orden ya
terminada.
"""

from decimal import Decimal

import pytest

from app.domain.models import (
    CanalComunicacion,
    EstadoControl,
    EstadoEjecucion,
    EstadoPago,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    InsumoUtilizado,
    OrdenReparacion,
    ResultadoAutorizacion,
    TipoMovimientoInsumo,
)
from app.services import (
    DecisionDetalle,
    ResultadoEvaluacionOrden,
    aprobar_control_tecnico,
    calcular_puntaje,
    crear_orden_cliente_externo,
    definir_prioridad,
    definir_reparacion_detail,
    ejecucion_activa,
    ejecutar_detalle,
    entregar_equipo,
    evaluar_situacion_orden,
    generar_comprobante_final,
    generar_comprobante_recepcion,
    generar_movimientos_inventario,
    habilitar_orden,
    hay_reservas_activas,
    ingresar_a_cola,
    marcar_pendiente_autorizacion,
    marcar_reparacion_lista,
    notificar_cliente,
    registrar_decision_cliente,
    registrar_ejecucion_completada,
    registrar_pago,
    registrar_saldo_pendiente,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
    toma_activa,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_condicion_entrega,
    validar_estacion_trabajo,
    validar_factibilidad_detalles,
)
from tests.fixtures import flujo_mvp
from tests.fixtures.catalogos_mvp import (
    ADMINISTRADOR,
    CLIENTE,
    COMPATIBILIDADES,
    COORDINADOR,
    EQUIPO,
    ESTACION,
    ESTACIONES,
    INSUMO_BATERIA,
    INSUMOS_PREVISTOS,
    RECEPCION,
    TECNICO,
    TIPO_BATERIA,
    t,
)
from tests.fixtures.flujo_mvp import orden_entregada as construir_orden_final


def test_hp_rep_001_end_to_end():
    """Recorre HP-REP-001 completo componiendo services."""

    # EVT-REP-001 -> PROC-REP-010 -> PROC-REP-030 -> PROC-REP-040
    orden = crear_orden_cliente_externo(
        orden_id="OR-001",
        cliente=CLIENTE,
        equipo=EQUIPO,
        usuario=RECEPCION,
        fecha=t(0),
    )

    assert orden.estado_workflow is EstadoWorkflow.REQUERIMIENTO
    assert orden.reparaciones_detail == []
    assert orden.total == Decimal("0")
    assert orden.estado_pago is EstadoPago.PENDIENTE
    assert orden.current_process == "PROC-REP-040"

    # Recepcion confirma la custodia: sin ella no se ejecuta (ACC-REP-024).
    orden = flujo_mvp.con_custodia_confirmada(orden, fecha=t(0))

    # PROC-REP-045 ("Si") -> PROC-REP-070
    orden = definir_reparacion_detail(
        orden,
        detalle_id="DET-001",
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(5),
    )

    assert len(orden.reparaciones_detail) == 1
    detalle = orden.reparaciones_detail[0]
    assert detalle.estado is EstadoReparacionDetail.DEFINIDO
    assert detalle.control_estado is EstadoControl.PENDIENTE
    assert detalle.tipo_reparacion_id == "TREP-001"
    assert detalle.precio == Decimal("80000")
    assert orden.total == Decimal("80000")

    # PROC-REP-050 ("Si") -> PROC-REP-060
    orden = generar_comprobante_recepcion(
        orden,
        fecha=t(10),
    )

    assert orden.documentos.comprobante_recepcion.generado is True
    assert orden.documentos.comprobante_recepcion.fecha_generacion == t(10)

    # Finalizar la definicion: el Detalle espera la decision del cliente
    # (BR-REP-028). PROC-REP-211 -> PROC-REP-129, sin factibilidad.
    orden, resultado = evaluar_situacion_orden(orden, fecha=t(11))
    assert resultado is ResultadoEvaluacionOrden.PENDIENTE_AUTORIZACION
    orden = marcar_pendiente_autorizacion(orden, fecha=t(11))
    assert orden.current_process == "PROC-REP-129"
    _, factible_sin_autorizar = validar_factibilidad_detalles(
        orden,
        insumos=[INSUMO_BATERIA],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(11),
    )
    assert factible_sin_autorizar is False

    # PROC-REP-046 -> PROC-REP-047 ("Acepta trabajos")
    orden, autorizados = registrar_decision_cliente(
        orden,
        decisiones=[
            DecisionDetalle(
                detalle_id="DET-001",
                version_definicion=1,
                resultado=ResultadoAutorizacion.AUTORIZADO,
            )
        ],
        usuario=RECEPCION,
        canal=CanalComunicacion.PRESENCIAL,
        fecha=t(12),
    )
    assert autorizados == ("DET-001",)
    (decision,) = orden.reparaciones_detail[0].autorizaciones
    assert decision.resultado is ResultadoAutorizacion.AUTORIZADO
    assert decision.usuario_id == RECEPCION.id
    assert orden.historial[-1].observacion == "ACEPTA_TRABAJOS"

    # PROC-REP-080 -> PROC-REP-090 ("Existe Detalle trabajable")
    orden, es_factible = validar_factibilidad_detalles(
        orden,
        insumos=[INSUMO_BATERIA],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(15),
    )

    assert es_factible is True
    # La factibilidad no reserva nada.
    assert orden.movimientos_insumo == []

    # PROC-REP-140
    orden = habilitar_orden(orden, fecha=t(20))
    assert orden.estado_workflow is EstadoWorkflow.HABILITADA

    # PROC-REP-150
    orden = definir_prioridad(
        orden,
        prioridad=1,
        usuario=COORDINADOR,
        fecha=t(25),
    )
    assert orden.prioridad == 1

    # PROC-REP-170
    orden = ingresar_a_cola(orden, fecha=t(30))
    assert orden.estado_workflow is EstadoWorkflow.EN_COLA

    # PROC-REP-172 ("Valida y compatible")
    orden, estacion_valida = validar_estacion_trabajo(
        orden,
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )
    assert estacion_valida is True

    # PROC-REP-180
    orden = tomar_orden(
        orden,
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        fecha=t(60),
    )

    assert len(orden.tomas) == 1
    toma = toma_activa(orden)
    assert toma is not None
    assert toma.estado is EstadoTomaOrden.ACTIVA
    assert toma.usuario_id == "TECH-001"
    assert toma.estacion_id == "EST-001"

    # PROC-REP-181
    orden = seleccionar_detalle(
        orden,
        detalle_id="DET-001",
        usuario=TECNICO,
        fecha=t(62),
    )

    # PROC-REP-174 ("Si")
    orden, compatible = validar_compatibilidad_detalle(
        orden,
        detalle_id="DET-001",
        compatibilidades=COMPATIBILIDADES,
        fecha=t(63),
    )
    assert compatible is True

    # PROC-REP-185 ("Reserva exitosa")
    orden = reservar_insumos_e_iniciar_ejecucion(
        orden,
        detalle_id="DET-001",
        usuario=TECNICO,
        insumos=[INSUMO_BATERIA],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )

    reservas = [
        movimiento
        for movimiento in orden.movimientos_insumo
        if movimiento.tipo is TipoMovimientoInsumo.RESERVA
    ]
    assert len(reservas) == 1
    assert reservas[0].cantidad == Decimal("1")
    assert reservas[0].usuario_id is None
    assert len(orden.ejecuciones) == 1
    ejecucion = ejecucion_activa(orden)
    assert ejecucion is not None
    assert ejecucion.estado is EstadoEjecucion.EN_PROGRESO
    assert orden.reparaciones_detail[0].estado is (
        EstadoReparacionDetail.EN_PROGRESO
    )
    assert orden.estado_workflow is EstadoWorkflow.EN_REPARACION

    ejecucion_id = ejecucion.id

    # PROC-REP-190
    orden = ejecutar_detalle(
        orden, detalle_id="DET-001", usuario=TECNICO, fecha=t(70)
    )

    # PROC-REP-200 ("Completado")
    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=ejecucion_id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
        ],
        usuario=TECNICO,
        fecha=t(145),
        observaciones="Bateria reemplazada sin novedades.",
    )

    ejecucion = orden.ejecuciones[0]
    assert ejecucion.estado is EstadoEjecucion.COMPLETADO
    assert ejecucion.fin == t(145)
    assert len(ejecucion.insumos_utilizados) == 1
    assert ejecucion.insumos_utilizados[0].insumo_id == "INS-001"
    assert ejecucion.insumos_utilizados[0].cantidad == Decimal("1")
    assert orden.reparaciones_detail[0].estado is (
        EstadoReparacionDetail.COMPLETO
    )

    # PROC-REP-210
    orden = generar_movimientos_inventario(
        orden,
        ejecucion_id=ejecucion_id,
        fecha=t(146),
    )

    tipos = [movimiento.tipo for movimiento in orden.movimientos_insumo]
    assert tipos == [
        TipoMovimientoInsumo.RESERVA,
        TipoMovimientoInsumo.CONSUMO,
    ]
    reserva, consumo = orden.movimientos_insumo
    # La RESERVA original se preserva intacta.
    assert reserva.id == reservas[0].id
    assert reserva.cantidad == Decimal("1")
    assert consumo.movimiento_origen_id == reserva.id
    assert consumo.ejecucion_id == ejecucion_id
    assert consumo.usuario_id is None
    assert hay_reservas_activas(orden.movimientos_insumo) is False

    # PROC-REP-211 ("Todos terminales, existe completo")
    orden, resultado = evaluar_situacion_orden(orden, fecha=t(150))

    assert resultado is ResultadoEvaluacionOrden.COMPLETA
    assert orden.tomas[0].estado is EstadoTomaOrden.CERRADA
    assert orden.tomas[0].fin == t(150)
    assert toma_activa(orden) is None
    assert ejecucion_activa(orden) is None

    # PROC-REP-220 -> PROC-REP-230 ("Si")
    orden = aprobar_control_tecnico(
        orden,
        usuario=RECEPCION,
        fecha=t(160),
        observaciones="Equipo enciende y carga correctamente.",
    )

    detalle = orden.reparaciones_detail[0]
    assert detalle.control_estado is EstadoControl.APROBADO
    assert detalle.control_usuario_id == "RECEP-001"
    assert detalle.control_fecha == t(160)
    # El control no altera el ciclo tecnico del Detalle.
    assert detalle.estado is EstadoReparacionDetail.COMPLETO

    # PROC-REP-245
    orden = calcular_puntaje(orden, fecha=t(165))
    assert orden.puntaje_total == 10

    # PROC-REP-240
    orden = marcar_reparacion_lista(orden, fecha=t(170))
    assert orden.estado_workflow is EstadoWorkflow.REPARACION_LISTA

    # PROC-REP-250 ("Si") -> PROC-REP-260
    orden = notificar_cliente(orden, usuario=RECEPCION, fecha=t(175))

    # PROC-REP-265 ("No"): todavia hay saldo
    orden, puede_entregar = validar_condicion_entrega(orden, fecha=t(180))

    assert orden.saldo == Decimal("80000")
    assert puede_entregar is False

    # PROC-REP-266
    orden = registrar_saldo_pendiente(orden, fecha=t(181))
    process_tras_266 = orden.current_process

    # FUNCTIONAL_ACTION: Registrar pago final (FEAT-REP-007, BR-REP-017)
    orden = registrar_pago(
        orden,
        monto=Decimal("80000"),
        metodo="EFECTIVO",
        usuario=ADMINISTRADOR,
        fecha=t(185),
    )

    assert len(orden.resumen_pago.pagos) == 1
    assert orden.resumen_pago.pagado == Decimal("80000")
    assert orden.saldo == Decimal("0")
    assert orden.estado_pago is EstadoPago.PAGADO
    # Registrar Pago no es un nodo del proceso.
    assert orden.current_process == process_tras_266

    # PROC-REP-265 ("Si", revalidacion)
    orden, puede_entregar = validar_condicion_entrega(orden, fecha=t(186))
    assert puede_entregar is True

    # PROC-REP-280
    orden = generar_comprobante_final(orden, fecha=t(190))

    assert orden.documentos.comprobante_final.generado is True
    assert orden.documentos.garantia_reparacion.generado is True

    # PROC-REP-270 -> EVT-REP-999
    orden = entregar_equipo(orden, usuario=ADMINISTRADOR, fecha=t(195))

    # --- expected de HP-REP-001 -----------------------------------------
    assert resultado is ResultadoEvaluacionOrden.COMPLETA
    assert orden.estado_workflow is EstadoWorkflow.ENTREGADA
    assert orden.current_process == "EVT-REP-999"
    assert ejecucion_activa(orden) is None
    assert toma_activa(orden) is None
    assert hay_reservas_activas(orden.movimientos_insumo) is False
    assert orden.saldo == Decimal("0")
    assert orden.documentos.comprobante_final.generado is True
    assert orden.documentos.garantia_reparacion.generado is True

    # EVT-REP-999 es un evento terminal, no una accion: no va al historial.
    assert all(
        paso.process_id != "EVT-REP-999" for paso in orden.historial
    )


def test_hp_rep_001_recorre_los_nodos_del_scenario():
    """El historial cubre los nodos que HP-REP-001 atraviesa."""
    orden = construir_orden_final()

    recorridos = [paso.process_id for paso in orden.historial]

    esperados = [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-129",
        "PROC-REP-046",
        "PROC-REP-047",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
        "PROC-REP-150",
        "PROC-REP-170",
        "PROC-REP-172",
        "PROC-REP-180",
        "PROC-REP-181",
        "PROC-REP-174",
        "PROC-REP-185",
        "PROC-REP-190",
        "PROC-REP-200",
        "PROC-REP-210",
        "PROC-REP-211",
        "PROC-REP-220",
        "PROC-REP-230",
        "PROC-REP-245",
        "PROC-REP-240",
        "PROC-REP-250",
        "PROC-REP-260",
        "PROC-REP-265",
        "PROC-REP-266",
        "PROC-REP-280",
        "PROC-REP-270",
    ]

    for process_id in esperados:
        assert process_id in recorridos, f"falta {process_id}"

    # PROC-REP-265 se evalua dos veces: bloqueo y revalidacion tras el pago.
    assert recorridos.count("PROC-REP-265") == 2


def test_la_orden_final_sobrevive_el_round_trip_json():
    """El resultado de los services sigue siendo serializable."""
    orden = construir_orden_final()
    volcado = orden.model_dump(mode="json")

    reconstruida = OrdenReparacion.model_validate(volcado)

    assert reconstruida == orden
    assert volcado["current_process"] == "EVT-REP-999"
    assert volcado["estado_workflow"] == "ENTREGADA"
    assert volcado["saldo"] == "0"
    assert volcado["puntaje_total"] == 10


@pytest.fixture
def orden_entregada():
    """Orden al final de HP-REP-001, construida con services."""
    return construir_orden_final()


def test_el_estado_final_coincide_con_el_fixture_declarativo(
    orden_entregada,
    orden_hp_rep_001,
):
    """Lo que producen los services coincide con el estado esperado."""
    assert orden_entregada.estado_workflow is (
        orden_hp_rep_001.estado_workflow
    )
    assert orden_entregada.current_process == (
        orden_hp_rep_001.current_process
    )
    assert orden_entregada.total == orden_hp_rep_001.total
    assert orden_entregada.saldo == orden_hp_rep_001.saldo
    assert orden_entregada.estado_pago is orden_hp_rep_001.estado_pago
    assert orden_entregada.puntaje_total == orden_hp_rep_001.puntaje_total

    detalle_servicios = orden_entregada.reparaciones_detail[0]
    detalle_fixture = orden_hp_rep_001.reparaciones_detail[0]
    assert detalle_servicios.estado is detalle_fixture.estado
    assert detalle_servicios.control_estado is detalle_fixture.control_estado
    assert detalle_servicios.precio == detalle_fixture.precio
