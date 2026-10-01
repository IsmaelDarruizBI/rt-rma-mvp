"""EXC-REP-001 (recursos insuficientes, en espera de revalidacion) en services.

PROC-REP-080 evalua cada Detalle por separado (BR-REP-002): un Detalle sin
recursos queda ``BLOQUEADO_POR_RECURSOS`` sin bloquear a los demas. Sin
ningun Detalle trabajable: 090 "Ninguno trabajable" -> 100 por Detalle, y la
Orden queda detenida en PROC-REP-100. Esperar (110 No -> 120) y revalidar
(120 -> 080) son eventos de sistema. ``PENDIENTE_RECURSOS`` es el agregado
derivado por el resolver, nunca un ``EstadoWorkflow``.
"""

from decimal import Decimal

import pytest

from app.application import acciones_disponibles, progreso
from app.application.acciones import detalles_trabajables
from app.domain.models import (
    CondicionReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    Insumo,
    InsumoUtilizado,
    OrdenReparacion,
    TipoReparacion,
    TipoReparacionInsumos,
)
from app.services import (
    PrecondicionInvalidaError,
    ResultadoEvaluacionOrden,
    definir_prioridad,
    definir_reparacion_detail,
    ejecutar_detalle,
    evaluar_situacion_orden,
    exigir_espera_por_recursos,
    generar_comprobante_recepcion,
    generar_movimientos_inventario,
    habilitar_orden,
    ingresar_a_cola,
    marcar_orden_en_revision,
    marcar_pendiente_recursos,
    registrar_ejecucion_completada,
    registrar_espera_recursos,
    reservar_insumos_e_iniciar_ejecucion,
    resolver_situacion_orden,
    seleccionar_detalle,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_estacion_trabajo,
    validar_factibilidad_detalles,
)
from tests.fixtures import flujo_mvp
from tests.fixtures import flujo_mvp_rt as flujo_rt
from tests.fixtures.catalogos_mvp import (
    COMPATIBILIDADES,
    COORDINADOR,
    ESTACION,
    ESTACIONES,
    RECEPCION,
    TECNICO,
    TIPO_BATERIA,
    t,
)

TIPO_PANTALLA = TipoReparacion(
    id="TREP-002",
    nombre="Cambio de pantalla",
    precio=Decimal("50000"),
    puntaje=5,
    garantia_dias=60,
)
PREVISTOS = [
    TipoReparacionInsumos(
        tipo_reparacion_id="TREP-001",
        insumo_id="INS-001",
        cantidad=Decimal("1"),
    ),
    TipoReparacionInsumos(
        tipo_reparacion_id="TREP-002",
        insumo_id="INS-002",
        cantidad=Decimal("1"),
    ),
    TipoReparacionInsumos(
        tipo_reparacion_id="TREP-002",
        insumo_id="INS-003",
        cantidad=Decimal("1"),
    ),
]


def _insumos(a="1", b="1", c="1") -> list[Insumo]:
    return [
        Insumo(id="INS-001", codigo="A", nombre="A", stock_fisico=Decimal(a)),
        Insumo(id="INS-002", codigo="B", nombre="B", stock_fisico=Decimal(b)),
        Insumo(id="INS-003", codigo="C", nombre="C", stock_fisico=Decimal(c)),
    ]


def _con_detalles(*tipos, base=None) -> OrdenReparacion:
    """Orden con los Detalles definidos y el comprobante emitido (060)."""
    orden = base or flujo_mvp.orden_creada()
    for indice, tipo in enumerate(tipos, start=1):
        orden = definir_reparacion_detail(
            orden,
            detalle_id=f"DET-{indice:03d}",
            tipo_reparacion=tipo,
            usuario=RECEPCION,
            fecha=t(5),
        )
    return generar_comprobante_recepcion(orden, fecha=t(10))


def _validar(orden, insumos, externas=None, minuto=15):
    return validar_factibilidad_detalles(
        orden,
        insumos=insumos,
        insumos_previstos=PREVISTOS,
        fecha=t(minuto),
        reservas_externas=externas,
    )


def _ids(orden) -> list[str]:
    return [p.referencia_id for p in orden.historial]


def _bloqueada() -> OrdenReparacion:
    """Un Detalle sin stock: detenida en PROC-REP-100."""
    orden, factible = _validar(_con_detalles(TIPO_BATERIA), _insumos(a="0"))
    assert factible is False
    return orden


def _en_espera() -> OrdenReparacion:
    return registrar_espera_recursos(_bloqueada(), fecha=t(20))


# --- Un Detalle sin recursos ---


def test_un_detalle_sin_stock_queda_bloqueado_y_la_orden_en_100():
    orden = _bloqueada()

    (detalle,) = orden.reparaciones_detail
    assert (
        detalle.condicion is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    )
    assert (
        resolver_situacion_orden(orden.reparaciones_detail)
        is ResultadoEvaluacionOrden.PENDIENTE_RECURSOS
    )
    assert orden.current_process == "PROC-REP-100"
    assert _ids(orden)[-3:] == ["PROC-REP-080", "PROC-REP-090", "PROC-REP-100"]
    paso_090 = next(
        p for p in orden.historial if p.referencia_id == "PROC-REP-090"
    )
    assert paso_090.observacion == "Ninguno trabajable"
    # PENDIENTE_RECURSOS no es un hito de workflow.
    assert orden.estado_workflow is EstadoWorkflow.REQUERIMIENTO
    assert "PROC-REP-140" not in _ids(orden)


def test_100_identifica_el_detalle_y_sus_faltantes_sin_mezclarlos():
    orden, _ = _validar(
        _con_detalles(TIPO_BATERIA, TIPO_PANTALLA),
        _insumos(a="0", b="0", c="0"),
    )

    advertencias = [
        (p.reparacion_detail_id, p.observacion)
        for p in orden.historial
        if p.referencia_id == "PROC-REP-100"
    ]
    assert advertencias == [
        ("DET-001", "Faltantes: INS-001"),
        ("DET-002", "Faltantes: INS-002, INS-003"),
    ]
    assert all(
        d.condicion is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
        for d in orden.reparaciones_detail
    )
    assert (
        resolver_situacion_orden(orden.reparaciones_detail)
        is ResultadoEvaluacionOrden.PENDIENTE_RECURSOS
    )


def test_la_factibilidad_no_reserva_no_mueve_stock_ni_muta_la_entrada():
    original = _con_detalles(TIPO_BATERIA)
    insumos = _insumos(a="0")
    foto = original.model_dump()

    orden, _ = _validar(original, insumos)

    assert original.model_dump() == foto  # los services no mutan la entrada
    assert orden.movimientos_insumo == []
    assert [i.stock_fisico for i in insumos] == [
        Decimal("0"),
        Decimal("1"),
        Decimal("1"),
    ]


def test_las_reservas_externas_cuentan_en_la_disponibilidad():
    orden, factible = _validar(
        _con_detalles(TIPO_BATERIA),
        _insumos(a="1"),
        externas={"INS-001": Decimal("1")},
    )

    assert factible is False
    assert (
        orden.reparaciones_detail[0].condicion
        is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    )

    sin_reserva, factible = _validar(
        _con_detalles(TIPO_BATERIA), _insumos(a="1")
    )
    assert factible is True
    assert (
        sin_reserva.reparaciones_detail[0].condicion
        is CondicionReparacionDetail.SIN_BLOQUEO
    )


# --- Multi-Detalle: factibilidad por Detalle --------------------------------


def test_factibilidad_parcial_un_detalle_bloqueado_no_bloquea_a_los_demas():
    orden, factible = _validar(
        _con_detalles(TIPO_BATERIA, TIPO_PANTALLA), _insumos(a="1", b="0")
    )

    assert factible is True  # "al menos un Detalle trabajable"
    a, b = orden.reparaciones_detail
    assert a.condicion is CondicionReparacionDetail.SIN_BLOQUEO
    assert b.condicion is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    assert (
        resolver_situacion_orden(orden.reparaciones_detail)
        is ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE
    )
    assert orden.historial[-1].referencia_id == "PROC-REP-090"
    assert orden.historial[-1].observacion == "Si"
    assert "PROC-REP-100" not in _ids(orden)
    assert detalles_trabajables(orden) == ["DET-001"]

    habilitada = habilitar_orden(orden, fecha=t(20))
    assert habilitada.estado_workflow is EstadoWorkflow.HABILITADA
    assert detalles_trabajables(habilitada) == ["DET-001"]
    # El Detalle bloqueado sigue bloqueado.
    assert (
        habilitada.reparaciones_detail[1].condicion
        is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    )


def test_otra_causa_de_bloqueo_no_se_pisa():
    """REQUIERE_DEFINICION (EXC-REP-004) no se convierte en SIN_BLOQUEO."""
    orden = _con_detalles(TIPO_BATERIA, TIPO_PANTALLA)
    orden.reparaciones_detail[
        0
    ].condicion = CondicionReparacionDetail.REQUIERE_DEFINICION

    orden, factible = _validar(orden, _insumos())

    assert (
        orden.reparaciones_detail[0].condicion
        is CondicionReparacionDetail.REQUIERE_DEFINICION
    )
    assert (
        orden.reparaciones_detail[1].condicion
        is CondicionReparacionDetail.SIN_BLOQUEO
    )
    assert factible is True


# --- Esperar y revalidar ---


def test_esperar_registra_110_no_y_120_sin_usuario_ni_cambiar_el_workflow():
    orden = _en_espera()

    assert _ids(orden)[-2:] == ["PROC-REP-110", "PROC-REP-120"]
    paso_110, paso_120 = orden.historial[-2:]
    assert paso_110.observacion == "No"
    assert paso_120.observacion == "PENDIENTE_RECURSOS"
    assert paso_110.usuario_id is None and paso_120.usuario_id is None
    assert orden.current_process == "PROC-REP-120"
    assert orden.estado_workflow is EstadoWorkflow.REQUERIMIENTO


def test_esperar_solo_vale_desde_100():
    with pytest.raises(PrecondicionInvalidaError, match="PROC-REP-100"):
        registrar_espera_recursos(_en_espera(), fecha=t(30))  # ya en 120
    with pytest.raises(PrecondicionInvalidaError):
        registrar_espera_recursos(
            flujo_mvp.orden_con_factibilidad(), fecha=t(30)
        )


def test_revalidar_solo_vale_desde_120():
    with pytest.raises(PrecondicionInvalidaError, match="PROC-REP-120"):
        exigir_espera_por_recursos(_bloqueada())  # en 100
    with pytest.raises(PrecondicionInvalidaError):
        exigir_espera_por_recursos(flujo_mvp.orden_creada())
    exigir_espera_por_recursos(_en_espera())


def test_revalidar_sin_stock_vuelve_a_100_y_conserva_cada_ciclo():
    orden = _en_espera()

    orden, factible = _validar(orden, _insumos(a="0"), minuto=30)
    assert factible is False
    assert orden.current_process == "PROC-REP-100"
    orden = registrar_espera_recursos(orden, fecha=t(35))

    assert orden.current_process == "PROC-REP-120"
    assert _ids(orden)[-10:] == [
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-100",
        "PROC-REP-110",
        "PROC-REP-120",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-100",
        "PROC-REP-110",
        "PROC-REP-120",
    ]


def test_revalidar_con_stock_habilita_y_desbloquea_el_detalle():
    orden = _en_espera()

    orden, factible = _validar(orden, _insumos(a="1"), minuto=30)
    assert factible is True
    assert orden.historial[-1].observacion == "Si"
    orden = habilitar_orden(orden, fecha=t(31))

    assert orden.estado_workflow is EstadoWorkflow.HABILITADA
    assert orden.current_process == "PROC-REP-140"
    assert (
        orden.reparaciones_detail[0].condicion
        is CondicionReparacionDetail.SIN_BLOQUEO
    )
    ids = _ids(orden)
    assert (
        ids.count("PROC-REP-070") == 1
    )  # sin Detalles ni comprobantes nuevos
    assert ids.count("PROC-REP-060") == 1


# --- Acciones y progreso ---


def _codigos(orden) -> list[str]:
    return [a.codigo for a in acciones_disponibles(orden)]


def test_acciones_en_100_y_120_priorizan_el_circuito_de_recursos():
    en_100 = _bloqueada()
    assert _codigos(en_100) == [
        "ESPERAR_RECURSOS",
        "OVERRIDE_RECURSOS",
        "REGISTRAR_PAGO",
    ]
    esperar = acciones_disponibles(en_100)[0]
    assert esperar.requiere_actor is False and esperar.roles == ()

    en_120 = _en_espera()
    assert _codigos(en_120) == ["REVALIDAR_RECURSOS", "REGISTRAR_PAGO"]
    assert acciones_disponibles(en_120)[0].requiere_actor is False

    habilitada = habilitar_orden(
        _validar(en_120, _insumos(a="1"), minuto=30)[0], fecha=t(31)
    )
    assert _codigos(habilitada)[0] == "ENCOLAR"


def test_acciones_en_recursos_para_rt_interno_sin_pago():
    orden, _ = _validar(
        _con_detalles(TIPO_BATERIA, base=flujo_rt.orden_rt_creada()),
        _insumos(a="0"),
    )
    assert orden.current_process == "PROC-REP-100"
    assert _codigos(orden) == ["ESPERAR_RECURSOS", "OVERRIDE_RECURSOS"]


def test_en_revision_con_recursos_pendientes_no_ofrece_definir():
    orden = marcar_orden_en_revision(
        flujo_mvp.orden_creada(), usuario=RECEPCION, fecha=t(1)
    )
    assert orden.estado_workflow is EstadoWorkflow.EN_REVISION
    assert orden.current_process == "PROC-REP-055"
    en_100, _ = _validar(
        orden.model_copy(
            update={
                "reparaciones_detail": _con_detalles(
                    TIPO_BATERIA
                ).reparaciones_detail
            }
        ),
        _insumos(a="0"),
    )

    assert en_100.estado_workflow is EstadoWorkflow.EN_REVISION
    assert "DEFINIR_REPARACION_DESDE_REVISION" not in _codigos(en_100)
    assert "ESPERAR_RECURSOS" in _codigos(en_100)


def test_progreso_muestra_100_110_120_una_sola_vez_y_combina_con_la_revision():
    orden, _ = _validar(_con_detalles(TIPO_BATERIA), _insumos(a="0"))
    orden = registrar_espera_recursos(orden, fecha=t(20))
    orden, _ = _validar(orden, _insumos(a="0"), minuto=30)
    orden = registrar_espera_recursos(orden, fecha=t(35))

    ruta = [p.process_id for p in progreso(orden)]
    assert ruta.count("PROC-REP-080") == 1 and ruta.count("PROC-REP-100") == 1
    i = ruta.index("PROC-REP-090")
    assert ruta[i : i + 4] == [
        "PROC-REP-090",
        "PROC-REP-100",
        "PROC-REP-110",
        "PROC-REP-120",
    ]
    alcanzados = [p.process_id for p in progreso(orden) if p.alcanzado]
    assert alcanzados[-1] == "PROC-REP-120"

    sin_exc = [p.process_id for p in progreso(flujo_mvp.orden_creada())]
    assert "PROC-REP-100" not in sin_exc  # la ruta normal no cambia


# --- B-1: PROC-REP-211 PENDIENTE_RECURSOS -> PROC-REP-120 ---


def _hasta_211_con_un_detalle_bloqueado():
    """A trabajable y B bloqueado: se completa A y se evalua PROC-REP-211."""
    insumos = _insumos(a="1", b="0")
    orden, _ = _validar(_con_detalles(TIPO_BATERIA, TIPO_PANTALLA), insumos)
    orden = habilitar_orden(orden, fecha=t(20))
    orden = definir_prioridad(
        orden, prioridad=1, usuario=COORDINADOR, fecha=t(25)
    )
    orden = ingresar_a_cola(orden, fecha=t(30))
    orden, _ = validar_estacion_trabajo(
        orden,
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )
    orden = tomar_orden(
        orden, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )
    orden = seleccionar_detalle(
        orden, detalle_id="DET-001", usuario=TECNICO, fecha=t(62)
    )
    orden, _ = validar_compatibilidad_detalle(
        orden,
        detalle_id="DET-001",
        compatibilidades=COMPATIBILIDADES,
        fecha=t(63),
    )
    orden = reservar_insumos_e_iniciar_ejecucion(
        orden,
        detalle_id="DET-001",
        usuario=TECNICO,
        insumos=insumos,
        insumos_previstos=PREVISTOS,
        fecha=t(65),
    )
    orden = ejecutar_detalle(
        orden, detalle_id="DET-001", usuario=TECNICO, fecha=t(70)
    )
    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
        ],
        usuario=TECNICO,
        fecha=t(145),
    )
    orden = generar_movimientos_inventario(
        orden, ejecucion_id=orden.ejecuciones[0].id, fecha=t(146)
    )
    return orden


def test_211_pendiente_de_recursos_cierra_la_toma_y_va_directo_a_120():
    previa = _hasta_211_con_un_detalle_bloqueado()
    assert previa.tomas[0].estado is EstadoTomaOrden.ACTIVA

    orden, resultado = evaluar_situacion_orden(previa, fecha=t(150))

    assert resultado is ResultadoEvaluacionOrden.PENDIENTE_RECURSOS
    assert _ids(orden)[-2:] == ["PROC-REP-211", "PROC-REP-120"]
    assert orden.historial[-2].observacion == "PENDIENTE_RECURSOS"
    assert orden.historial[-1].usuario_id is None
    assert (
        "PROC-REP-100" not in _ids(orden)[_ids(orden).index("PROC-REP-211") :]
    )
    assert orden.current_process == "PROC-REP-120"
    assert orden.estado_workflow is EstadoWorkflow.EN_REPARACION
    (toma,) = orden.tomas
    assert toma.estado is EstadoTomaOrden.CERRADA
    assert toma.fin == t(150)
    assert _codigos(orden)[0] == "REVALIDAR_RECURSOS"
    assert "LIBERAR_ORDEN" not in _codigos(orden)


def test_marcar_pendiente_recursos_solo_desde_110_o_211_y_con_el_resolver():
    en_100 = _bloqueada()  # current 100: no alcanza 120 sin pasar por 110
    with pytest.raises(PrecondicionInvalidaError, match="PROC-REP-110"):
        marcar_pendiente_recursos(en_100, fecha=t(30))

    # Desde 211 pero sin ser PENDIENTE_RECURSOS (hay un Detalle trabajable).
    trabajable, _ = evaluar_situacion_orden(
        flujo_mvp.orden_con_inventario_conciliado(), fecha=t(150)
    )
    falso = trabajable.model_copy(update={"current_process": "PROC-REP-211"})
    with pytest.raises(PrecondicionInvalidaError, match="pendiente"):
        marcar_pendiente_recursos(falso, fecha=t(160))


# --- Gate de PROC-REP-140 desde EN_REPARACION ---


def _en_reparacion_en_120_y_revalidada(stock_b):
    orden, _ = evaluar_situacion_orden(
        _hasta_211_con_un_detalle_bloqueado(), fecha=t(150)
    )
    return _validar(orden, _insumos(a="1", b=stock_b), minuto=200)


def test_en_reparacion_alcanza_140_solo_tras_090_si():
    orden, factible = _en_reparacion_en_120_y_revalidada("1")
    assert factible is True
    assert orden.estado_workflow is EstadoWorkflow.EN_REPARACION
    assert orden.current_process == "PROC-REP-090"

    habilitada = habilitar_orden(orden, fecha=t(201))

    assert habilitada.estado_workflow is EstadoWorkflow.HABILITADA
    assert habilitada.historial[-1].referencia_id == "PROC-REP-140"


def test_en_reparacion_con_090_ninguno_o_fuera_de_090_no_habilita():
    orden, factible = _en_reparacion_en_120_y_revalidada("0")
    assert factible is False  # queda en 100
    with pytest.raises(PrecondicionInvalidaError, match="factibilidad"):
        habilitar_orden(orden, fecha=t(201))
    en_090 = orden.model_copy(update={"current_process": "PROC-REP-090"})
    with pytest.raises(PrecondicionInvalidaError, match="no fue aprobada"):
        habilitar_orden(en_090, fecha=t(201))

    sin_pasar_por_090, _ = evaluar_situacion_orden(
        _hasta_211_con_un_detalle_bloqueado(), fecha=t(150)
    )
    assert sin_pasar_por_090.current_process == "PROC-REP-120"
    with pytest.raises(PrecondicionInvalidaError, match="factibilidad"):
        habilitar_orden(sin_pasar_por_090, fecha=t(201))


def test_otros_estados_siguen_sin_poder_habilitarse():
    for estado in (
        EstadoWorkflow.EN_COLA,
        EstadoWorkflow.REPARACION_LISTA,
        EstadoWorkflow.ENTREGADA,
    ):
        orden = flujo_mvp.orden_con_factibilidad().model_copy(
            update={"estado_workflow": estado}
        )
        with pytest.raises(
            PrecondicionInvalidaError, match="Solo se habilita"
        ):
            habilitar_orden(orden, fecha=t(30))
