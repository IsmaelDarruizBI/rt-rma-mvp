"""EXC-REP-004 (Detalle requiere revision tecnica posterior): services.

Productor: PROC-REP-200 "Requiere redefinicion" (Ejecucion INTERRUMPIDO,
Detalle DEFINIDO + REQUIERE_DEFINICION, motivo obligatorio) -> 210 -> 211.
Con otro Detalle trabajable: ABIERTA_TRABAJABLE (toma activa). Sin ninguno:
REQUIERE_REVISION -> cierre de toma -> 125 -> 126 (Tecnico) -> 127
(Recepcion, nueva definicion vigente + historica) -> 080.
"""

from decimal import Decimal

import pytest

from app.application import (
    acciones_disponibles,
    progreso,
    redefinir_detalle,
    requerir_redefinicion_ejecucion,
    revisar_detalle,
)
from app.application.contexto import ApplicationContext, construir_contexto
from app.core.config import Settings
from app.domain.models import (
    CondicionReparacionDetail,
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    InsumoUtilizado,
    OrdenReparacion,
    TipoMovimientoInsumo,
    TipoReparacion,
    TipoReparacionInsumos,
    Usuario,
)
from app.services import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    ResultadoEvaluacionOrden,
    ejecucion_activa,
    ejecutar_detalle,
    evaluar_situacion_orden,
    generar_movimientos_inventario,
    habilitar_orden,
    marcar_pendiente_revision,
    registrar_ejecucion_completada,
    registrar_ejecucion_interrumpida,
    registrar_ejecucion_requiere_redefinicion,
    registrar_espera_recursos,
    registrar_override_recursos,
    registrar_pago,
    registrar_paso,
    reservas_activas,
    revisar_detalle_pendiente,
    revision_vigente,
    tiene_override_factibilidad,
)
from app.services import (
    redefinir_detalle as redefinir_detalle_servicio,
)
from app.storage import JsonOrdenReparacionRepository
from tests.fixtures.catalogos_mvp import (
    ADMINISTRADOR,
    COORDINADOR,
    RECEPCION,
    TECNICO,
    TIPO_BATERIA,
    t,
)
from tests.test_exc_rep_001 import (
    PREVISTOS,
    TIPO_PANTALLA,
    _con_detalles,
    _ids,
    _insumos,
    _validar,
)
from tests.test_exc_rep_003 import (
    _en_toma,
    _encolar_y_tomar,
    _intentar,
    _seleccionar,
)

MOTIVO = "La placa esta danada: no alcanza con cambiar la bateria."
TIPO_PLACA = TipoReparacion(
    id="TREP-003",
    nombre="Cambio de placa",
    precio=Decimal("150000"),
    puntaje=20,
    garantia_dias=120,
)
TIPO_BARATO = TipoReparacion(
    id="TREP-004",
    nombre="Ajuste de conector",
    precio=Decimal("10000"),
    puntaje=2,
    garantia_dias=30,
)


def _en_ejecucion(*tipos, detalle_id="DET-001", previstos=PREVISTOS):
    """Detalle(s) factibles, Orden tomada y Ejecucion iniciada."""
    orden = _seleccionar(_en_toma(*tipos), detalle_id)
    orden, exitosa = _intentar(
        orden,
        _insumos(a="5", b="5", c="5"),
        detalle_id=detalle_id,
        previstos=previstos,
    )
    assert exitosa is True
    return orden


def _cerrar_200(orden, resultado, usados=(), minuto=70, **kw):
    """190 -> 200 con el resultado indicado (sin 210 ni 211)."""
    ejecucion = ejecucion_activa(orden)
    orden = ejecutar_detalle(
        orden,
        detalle_id=ejecucion.reparacion_detail_id,
        usuario=TECNICO,
        fecha=t(minuto),
    )
    return resultado(
        orden,
        ejecucion_id=ejecucion.id,
        insumos_utilizados=list(usados),
        usuario=TECNICO,
        fecha=t(minuto),
        **kw,
    ), ejecucion.id


def _requiere_redefinicion(orden, usados=(), minuto=70):
    """190 -> 200 Requiere redefinicion -> 210 -> 211 [-> 125]."""
    orden, ejecucion_id = _cerrar_200(
        orden,
        registrar_ejecucion_requiere_redefinicion,
        usados,
        minuto,
        motivo=MOTIVO,
    )
    orden = generar_movimientos_inventario(
        orden, ejecucion_id=ejecucion_id, fecha=t(minuto)
    )
    return evaluar_situacion_orden(orden, fecha=t(minuto))


def _en_125(minuto=70) -> OrdenReparacion:
    orden, resultado = _requiere_redefinicion(_en_ejecucion(), minuto=minuto)
    assert resultado is ResultadoEvaluacionOrden.REQUIERE_REVISION
    return orden


def _revisar(orden, detalle_id="DET-001", usuario=TECNICO, minuto=80):
    return revisar_detalle_pendiente(
        orden,
        detalle_id=detalle_id,
        usuario=usuario,
        resultado="Placa con corrosion",
        fecha=t(minuto),
    )


def _redefinir(
    orden, tipo=TIPO_PLACA, detalle_id="DET-001", usuario=RECEPCION, minuto=90
):
    return redefinir_detalle_servicio(
        orden,
        detalle_id=detalle_id,
        tipo_reparacion=tipo,
        usuario=usuario,
        fecha=t(minuto),
    )


def _detalle(orden, detalle_id="DET-001"):
    return next(d for d in orden.reparaciones_detail if d.id == detalle_id)


# --- 1/2. Tercer resultado de PROC-REP-200 ---


def test_requiere_redefinicion_interrumpe_y_deja_requiere_definicion():
    orden, ejecucion_id = _cerrar_200(
        _en_ejecucion(),
        registrar_ejecucion_requiere_redefinicion,
        [InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))],
        motivo=MOTIVO,
        observaciones="Se abrio el equipo",
    )

    (ejecucion,) = orden.ejecuciones
    assert ejecucion.id == ejecucion_id
    assert ejecucion.estado is EstadoEjecucion.INTERRUMPIDO
    assert ejecucion.fin == t(70)
    assert ejecucion.observaciones == "Se abrio el equipo"
    assert ejecucion.motivo_redefinicion == MOTIVO
    assert [u.insumo_id for u in ejecucion.insumos_utilizados] == ["INS-001"]
    detalle = _detalle(orden)
    assert detalle.estado is EstadoReparacionDetail.DEFINIDO
    assert detalle.condicion is CondicionReparacionDetail.REQUIERE_DEFINICION
    paso = orden.historial[-1]
    assert (paso.referencia_id, paso.observacion) == (
        "PROC-REP-200",
        "Requiere redefinicion",
    )
    assert paso.reparacion_detail_id == "DET-001"


@pytest.mark.parametrize("motivo", ["", "   "])
def test_el_motivo_es_obligatorio(motivo):
    with pytest.raises(PrecondicionInvalidaError, match="motivo"):
        _cerrar_200(
            _en_ejecucion(),
            registrar_ejecucion_requiere_redefinicion,
            motivo=motivo,
        )


def test_interrumpido_y_requiere_redefinicion_difieren_solo_en_la_condicion():
    interrumpida, _ = _cerrar_200(
        _en_ejecucion(), registrar_ejecucion_interrumpida
    )
    redefinir, _ = _cerrar_200(
        _en_ejecucion(),
        registrar_ejecucion_requiere_redefinicion,
        motivo=MOTIVO,
    )

    for orden in (interrumpida, redefinir):
        assert orden.ejecuciones[0].estado is EstadoEjecucion.INTERRUMPIDO
        assert _detalle(orden).estado is EstadoReparacionDetail.DEFINIDO
    assert _detalle(interrumpida).condicion is (
        CondicionReparacionDetail.SIN_BLOQUEO
    )
    assert _detalle(redefinir).condicion is (
        CondicionReparacionDetail.REQUIERE_DEFINICION
    )
    assert interrumpida.ejecuciones[0].motivo_redefinicion is None
    assert interrumpida.historial[-1].observacion == "Interrumpido"


def test_solo_el_tecnico_propietario_puede_cerrar():
    orden = _en_ejecucion()
    ejecucion = ejecucion_activa(orden)
    otro = Usuario(id="TECH-002", nombre="Otro", rol=TECNICO.rol)
    for usuario in (otro, RECEPCION):
        with pytest.raises(PrecondicionInvalidaError):
            registrar_ejecucion_requiere_redefinicion(
                orden,
                ejecucion_id=ejecucion.id,
                insumos_utilizados=[],
                usuario=usuario,
                fecha=t(70),
                motivo=MOTIVO,
            )


# --- 3. Inventario (PROC-REP-210) ---


def test_210_consume_lo_usado_y_libera_el_resto():
    previstos = [
        TipoReparacionInsumos(
            tipo_reparacion_id="TREP-001",
            insumo_id="INS-001",
            cantidad=Decimal("3"),
        )
    ]
    orden = _en_ejecucion(previstos=previstos)

    orden, _ = _requiere_redefinicion(
        orden,
        usados=[InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))],
    )

    por_tipo = {
        tipo: sum(
            (m.cantidad for m in orden.movimientos_insumo if m.tipo is tipo),
            Decimal("0"),
        )
        for tipo in TipoMovimientoInsumo
    }
    assert por_tipo[TipoMovimientoInsumo.RESERVA] == Decimal("3")
    assert por_tipo[TipoMovimientoInsumo.CONSUMO] == Decimal("1")
    assert por_tipo[TipoMovimientoInsumo.LIBERACION_RESERVA] == Decimal("2")
    assert reservas_activas(orden.movimientos_insumo) == []


# --- 4. Caso A: otro Detalle trabajable ---


def test_caso_a_otro_trabajable_211_abierta_trabajable_y_toma_activa():
    orden = _en_ejecucion(TIPO_BATERIA, TIPO_PANTALLA)

    orden, resultado = _requiere_redefinicion(orden)

    assert resultado is ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE
    assert orden.current_process == "PROC-REP-211"
    assert "PROC-REP-125" not in _ids(orden)
    assert [toma.estado for toma in orden.tomas] == [EstadoTomaOrden.ACTIVA]
    assert orden.estado_workflow is EstadoWorkflow.EN_REPARACION
    assert _detalle(orden, "DET-001").condicion is (
        CondicionReparacionDetail.REQUIERE_DEFINICION
    )
    assert _detalle(orden, "DET-002").condicion is (
        CondicionReparacionDetail.SIN_BLOQUEO
    )
    codigos = [
        (a.codigo, a.detalle_id)
        for a in acciones_disponibles(orden)
        if a.codigo != "REGISTRAR_PAGO"
    ]
    assert codigos == [("INICIAR_DETALLE", "DET-002"), ("LIBERAR_ORDEN", None)]

    # DET-002 se inicia normalmente (212 Si -> 181).
    seleccion = _seleccionar(orden, "DET-002")
    assert _ids(seleccion)[-3:] == [
        "PROC-REP-212",
        "PROC-REP-181",
        "PROC-REP-174",
    ]
    iniciada, exitosa = _intentar(
        seleccion, _insumos(a="5", b="5", c="5"), detalle_id="DET-002"
    )
    assert exitosa is True

    # Al completar DET-002, ya no queda trabajable: 211 -> 125.
    completada, ejecucion_id = _cerrar_200(
        iniciada,
        registrar_ejecucion_completada,
        minuto=75,
    )
    completada = generar_movimientos_inventario(
        completada, ejecucion_id=ejecucion_id, fecha=t(75)
    )
    final, resultado = evaluar_situacion_orden(completada, fecha=t(75))
    assert resultado is ResultadoEvaluacionOrden.REQUIERE_REVISION
    assert _ids(final)[-2:] == ["PROC-REP-211", "PROC-REP-125"]


# --- 5. Caso B: ninguno trabajable ---


def test_caso_b_211_requiere_revision_cierra_toma_y_va_a_125():
    orden = _en_125()

    assert _ids(orden)[-2:] == ["PROC-REP-211", "PROC-REP-125"]
    paso_211, paso_125 = orden.historial[-2:]
    assert paso_211.observacion == "REQUIERE_REVISION"
    assert paso_125.usuario_id is None
    assert orden.current_process == "PROC-REP-125"
    (toma,) = orden.tomas
    assert toma.estado is EstadoTomaOrden.CERRADA and toma.fin == t(70)
    assert orden.estado_workflow is EstadoWorkflow.EN_REPARACION
    assert "PROC-REP-120" not in _ids(orden)
    codigos = [
        (a.codigo, a.detalle_id, a.roles)
        for a in acciones_disponibles(orden)
        if a.codigo != "REGISTRAR_PAGO"
    ]
    assert codigos == [("REVISAR_DETALLE", "DET-001", (TECNICO.rol,))]


def test_125_no_modifica_detalles_ni_workflow():
    orden, ejecucion_id = _cerrar_200(
        _en_ejecucion(),
        registrar_ejecucion_requiere_redefinicion,
        motivo=MOTIVO,
    )
    orden = generar_movimientos_inventario(
        orden, ejecucion_id=ejecucion_id, fecha=t(70)
    )
    antes = orden.model_copy(deep=True)

    despues, _ = evaluar_situacion_orden(orden, fecha=t(70))

    assert despues.historial[-1].referencia_id == "PROC-REP-125"
    assert despues.reparaciones_detail == antes.reparaciones_detail
    assert despues.estado_workflow is antes.estado_workflow
    assert despues.ejecuciones == antes.ejecuciones


def test_125_solo_desde_211_con_requiere_revision():
    with pytest.raises(PrecondicionInvalidaError, match="211"):
        marcar_pendiente_revision(_en_ejecucion(), fecha=t(70))


# --- 6. Prioridad del resolver ---


def test_requiere_definicion_gana_sobre_bloqueado_por_recursos():
    orden, factible = _validar(
        _con_detalles(TIPO_BATERIA, TIPO_PANTALLA),
        _insumos(a="1", b="0", c="0"),
    )
    assert factible is True  # DET-001 trabajable, DET-002 bloqueado
    orden = _seleccionar(_encolar_y_tomar(habilitar_orden(orden, fecha=t(20))))
    orden, _ = _intentar(orden, _insumos(a="1", b="0", c="0"))

    orden, resultado = _requiere_redefinicion(orden)

    assert resultado is ResultadoEvaluacionOrden.REQUIERE_REVISION
    assert orden.current_process == "PROC-REP-125"
    assert _detalle(orden, "DET-002").condicion is (
        CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    )


# --- 7/8. PROC-REP-126 ---


def test_126_registra_la_revision_sin_tocar_la_definicion():
    orden = _en_125()
    antes = _detalle(orden).model_copy()

    revisada = _revisar(orden)

    paso = revisada.historial[-1]
    assert paso.referencia_id == "PROC-REP-126"
    assert paso.usuario_id == TECNICO.id
    assert paso.fecha == t(80)
    assert paso.reparacion_detail_id == "DET-001"
    assert paso.observacion == "Placa con corrosion"
    despues = _detalle(revisada)
    for campo in ("tipo_reparacion_id", "precio", "puntaje", "garantia_dias"):
        assert getattr(despues, campo) == getattr(antes, campo)
    assert despues.condicion is CondicionReparacionDetail.REQUIERE_DEFINICION
    assert revisada.tomas == orden.tomas  # no abre toma
    assert revision_vigente(revisada, "DET-001")
    acciones = [
        (a.codigo, a.roles)
        for a in acciones_disponibles(revisada)
        if a.codigo != "REGISTRAR_PAGO"
    ]
    assert acciones == [("REDEFINIR_DETALLE", (RECEPCION.rol,))]


@pytest.mark.parametrize("usuario", [RECEPCION, COORDINADOR, ADMINISTRADOR])
def test_126_solo_tecnico(usuario):
    with pytest.raises(PrecondicionInvalidaError):
        _revisar(_en_125(), usuario=usuario)


def test_126_resultado_obligatorio():
    with pytest.raises(PrecondicionInvalidaError, match="vacio"):
        revisar_detalle_pendiente(
            _en_125(),
            detalle_id="DET-001",
            usuario=TECNICO,
            resultado="  ",
            fecha=t(80),
        )


def test_126_fuera_del_circuito_o_con_toma_o_ejecucion():
    # En ejecucion (toma y Ejecucion activas, fuera de 125).
    with pytest.raises(PrecondicionInvalidaError):
        _revisar(_en_ejecucion())
    # Detalle que no requiere definicion.
    with pytest.raises(PrecondicionInvalidaError):
        _revisar(
            _en_125().model_copy(
                update={
                    "reparaciones_detail": [
                        _detalle(_en_125()).model_copy(
                            update={
                                "condicion": (
                                    CondicionReparacionDetail.SIN_BLOQUEO
                                )
                            }
                        )
                    ]
                }
            )
        )
    # Con toma activa aunque este en 125 (invariante defensiva).
    orden = _en_125()
    orden.tomas[0].estado = EstadoTomaOrden.ACTIVA
    with pytest.raises(PrecondicionInvalidaError, match="toma"):
        _revisar(orden)
    # Detalle inexistente.
    with pytest.raises(EntidadNoEncontradaError):
        _revisar(_en_125(), detalle_id="DET-999")


# --- 9/10/11. PROC-REP-127 e historico ---


def test_127_redefine_el_mismo_detalle_y_conserva_lo_anterior():
    orden = _revisar(_en_125())
    ejecuciones = list(orden.ejecuciones)

    redefinida = _redefinir(orden)

    detalle = _detalle(redefinida)
    assert detalle.id == "DET-001"
    assert detalle.detalle_origen_id is None
    assert redefinida.ejecuciones == ejecuciones
    assert (
        detalle.tipo_reparacion_id,
        detalle.precio,
        detalle.puntaje,
        detalle.garantia_dias,
    ) == ("TREP-003", Decimal("150000"), 20, 120)
    assert detalle.condicion is CondicionReparacionDetail.SIN_BLOQUEO
    (anterior,) = detalle.definiciones_anteriores
    assert (
        anterior.tipo_reparacion_id,
        anterior.precio,
        anterior.puntaje,
        anterior.garantia_dias,
        anterior.reemplazada_en,
        anterior.usuario_id,
    ) == ("TREP-001", Decimal("80000"), 10, 90, t(90), RECEPCION.id)
    paso = redefinida.historial[-1]
    assert paso.referencia_id == "PROC-REP-127"
    assert paso.usuario_id == RECEPCION.id
    assert paso.reparacion_detail_id == "DET-001"
    assert "TREP-001 -> TREP-003" in paso.observacion


def test_la_primera_definicion_no_genera_historico():
    assert _detalle(_en_ejecucion()).definiciones_anteriores == []


def _ciclo_completo(orden, tipo, minuto):
    """Una redefinicion completa: 200 -> 125 -> 126 -> 127 -> 080/140."""
    orden = habilitar_orden(
        _validar(
            _redefinir(
                _revisar(orden, minuto=minuto), tipo=tipo, minuto=minuto + 1
            ),
            _insumos(a="5", b="5", c="5"),
            minuto=minuto + 2,
        )[0],
        fecha=t(minuto + 3),
    )
    return orden


def test_historico_a_b_c_es_append_only():
    orden = _ciclo_completo(_en_125(), TIPO_PLACA, 80)  # A -> B
    orden = _seleccionar(_encolar_y_tomar(orden))
    orden, _ = _intentar(orden, _insumos(a="5", b="5", c="5"))
    orden, resultado = _requiere_redefinicion(orden, minuto=100)
    assert resultado is ResultadoEvaluacionOrden.REQUIERE_REVISION
    orden = _ciclo_completo(orden, TIPO_PANTALLA, 110)  # B -> C

    detalle = _detalle(orden)
    assert detalle.tipo_reparacion_id == "TREP-002"
    assert [d.tipo_reparacion_id for d in detalle.definiciones_anteriores] == [
        "TREP-001",
        "TREP-003",
    ]


def test_mismo_tipo_tambien_es_una_redefinicion_con_snapshot_nuevo():
    orden = _revisar(_en_125())
    catalogo_actual = TIPO_BATERIA.model_copy(
        update={"precio": Decimal("95000"), "garantia_dias": 120}
    )

    redefinida = _redefinir(orden, tipo=catalogo_actual)

    detalle = _detalle(redefinida)
    (anterior,) = detalle.definiciones_anteriores
    assert anterior.tipo_reparacion_id == "TREP-001"
    assert anterior.precio == Decimal("80000")
    assert detalle.tipo_reparacion_id == "TREP-001"
    assert detalle.precio == Decimal("95000")
    assert detalle.garantia_dias == 120


def test_127_exige_revision_del_mismo_detalle_en_el_ciclo_actual():
    # Sin 126.
    with pytest.raises(PrecondicionInvalidaError, match="PROC-REP-126"):
        _redefinir(_en_125())

    # 126 de DET-001 no habilita 127 de DET-002 (Multi-Detalle).
    orden = _en_ejecucion(TIPO_BATERIA, TIPO_PANTALLA)
    orden = orden.model_copy(deep=True)
    orden.reparaciones_detail[
        1
    ].condicion = CondicionReparacionDetail.REQUIERE_DEFINICION
    orden, resultado = _requiere_redefinicion(orden)
    assert resultado is ResultadoEvaluacionOrden.REQUIERE_REVISION
    revisada = _revisar(orden, "DET-001")
    with pytest.raises(PrecondicionInvalidaError, match="PROC-REP-126"):
        _redefinir(revisada, detalle_id="DET-002")
    # Se pueden revisar ambos y redefinir el segundo.
    ambas = _revisar(revisada, "DET-002", minuto=81)
    redefinida = _redefinir(ambas, detalle_id="DET-002")
    assert _detalle(redefinida, "DET-002").definiciones_anteriores


def test_una_revision_de_un_ciclo_anterior_no_habilita_127():
    orden = _ciclo_completo(_en_125(), TIPO_PLACA, 80)
    orden = _seleccionar(_encolar_y_tomar(orden))
    orden, _ = _intentar(orden, _insumos(a="5", b="5", c="5"))
    orden, _ = _requiere_redefinicion(orden, minuto=100)

    assert not revision_vigente(orden, "DET-001")
    with pytest.raises(PrecondicionInvalidaError, match="PROC-REP-126"):
        _redefinir(orden, minuto=101)


def test_127_valida_rol_y_tipo_activo():
    orden = _revisar(_en_125())
    for usuario in (TECNICO, COORDINADOR):
        with pytest.raises(PrecondicionInvalidaError):
            _redefinir(orden, usuario=usuario)
    inactivo = TIPO_PLACA.model_copy(update={"activo": False})
    with pytest.raises(PrecondicionInvalidaError, match="activo"):
        _redefinir(orden, tipo=inactivo)


# --- 12/13/14. Vigencia del override ---


def _con_override_y_ejecucion():
    orden, factible = _validar(_con_detalles(TIPO_BATERIA), _insumos(a="0"))
    assert factible is False
    orden = registrar_override_recursos(
        orden,
        detalle_id="DET-001",
        usuario=COORDINADOR,
        motivo="urgente",
        fecha=t(18),
    )
    orden = _seleccionar(_encolar_y_tomar(habilitar_orden(orden, fecha=t(19))))
    orden, exitosa = _intentar(orden, _insumos(a="0"))
    assert exitosa is True  # EXC-REP-002: reserva sin stock con override
    return orden


def test_un_127_invalida_el_override_anterior():
    orden = _con_override_y_ejecucion()
    assert tiene_override_factibilidad(orden, "DET-001")

    orden, _ = _requiere_redefinicion(orden)
    orden = _redefinir(_revisar(orden), tipo=TIPO_BATERIA)

    assert not tiene_override_factibilidad(orden, "DET-001")
    # 080 sin stock: 090 Ninguno -> 100 (EXC-REP-001/002 siguen).
    orden, factible = _validar(orden, _insumos(a="0"), minuto=95)
    assert factible is False
    assert orden.current_process == "PROC-REP-100"
    assert _detalle(orden).condicion is (
        CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    )
    assert (
        registrar_espera_recursos(orden, fecha=t(96)).current_process
        == "PROC-REP-120"
    )


def test_un_130_posterior_al_127_es_valido():
    orden = _con_override_y_ejecucion()
    orden, _ = _requiere_redefinicion(orden)
    orden = _redefinir(_revisar(orden), tipo=TIPO_BATERIA)
    orden, _ = _validar(orden, _insumos(a="0"), minuto=95)

    forzada = registrar_override_recursos(
        orden,
        detalle_id="DET-001",
        usuario=COORDINADOR,
        motivo="nueva autorizacion",
        fecha=t(96),
    )

    assert tiene_override_factibilidad(forzada, "DET-001")
    assert habilitar_orden(forzada, fecha=t(97)).estado_workflow is (
        EstadoWorkflow.HABILITADA
    )


def test_el_127_de_otro_detalle_no_invalida_el_override():
    orden = _con_detalles(TIPO_BATERIA, TIPO_PANTALLA)
    for proceso, detalle_id in (
        ("PROC-REP-130", "DET-002"),
        ("PROC-REP-127", "DET-001"),
    ):
        orden = registrar_paso(
            orden,
            process_id=proceso,
            accion="X",
            fecha=t(20),
            reparacion_detail_id=detalle_id,
        )
    assert tiene_override_factibilidad(orden, "DET-002")
    assert not tiene_override_factibilidad(orden, "DET-001")


# --- 15/16. 127 -> 080 ---


def test_127_y_080_con_stock_habilita():
    orden = _redefinir(_revisar(_en_125()))
    orden, factible = _validar(orden, _insumos(a="5"), minuto=95)

    assert factible is True
    habilitada = habilitar_orden(orden, fecha=t(96))
    assert _ids(habilitada)[-5:] == [
        "PROC-REP-126",
        "PROC-REP-127",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]
    assert habilitada.estado_workflow is EstadoWorkflow.HABILITADA


# --- 17. Precio y pagos ---


def test_el_nuevo_snapshot_cambia_total_y_saldo_incluso_negativo():
    orden = _revisar(_en_125())
    pagada = registrar_pago(
        orden,
        monto=Decimal("80000"),
        metodo="EFECTIVO",
        usuario=RECEPCION,
        fecha=t(85),
    )
    assert pagada.saldo == Decimal("0")

    mas_cara = _redefinir(pagada, tipo=TIPO_PLACA)
    assert mas_cara.total == Decimal("150000")
    assert mas_cara.saldo == Decimal("70000")

    mas_barata = _redefinir(pagada, tipo=TIPO_BARATO)
    assert mas_barata.total == Decimal("10000")
    # Pago excedente: saldo negativo, sin reembolso ni credito (pendiente).
    assert mas_barata.saldo == Decimal("-70000")
    assert len(mas_barata.resumen_pago.pagos) == 1


# --- 19. Persistencia JSON ---


def test_json_conserva_varias_definiciones_anteriores(tmp_path):
    orden = _ciclo_completo(_en_125(), TIPO_PLACA, 80)
    orden = _seleccionar(_encolar_y_tomar(orden))
    orden, _ = _intentar(orden, _insumos(a="5", b="5", c="5"))
    orden, _ = _requiere_redefinicion(orden, minuto=100)
    orden = _ciclo_completo(orden, TIPO_PANTALLA, 110)

    repo = JsonOrdenReparacionRepository(tmp_path)
    repo.guardar(orden)
    recargada = repo.obtener(orden.id)

    assert len(_detalle(recargada).definiciones_anteriores) == 2
    assert _detalle(recargada) == _detalle(orden)
    assert recargada.ejecuciones == orden.ejecuciones


def test_un_json_sin_el_campo_carga_con_historico_vacio():
    datos = _detalle(_en_ejecucion()).model_dump(mode="json")
    datos.pop("definiciones_anteriores")
    assert (
        type(_detalle(_en_ejecucion()))
        .model_validate(datos)
        .definiciones_anteriores
        == []
    )


# --- Progreso ---


def test_progreso_muestra_125_126_127_tras_211_con_evidencia():
    orden = _redefinir(_revisar(_en_125()))
    ruta = [p.process_id for p in progreso(orden)]
    alcanzados = {p.process_id for p in progreso(orden) if p.alcanzado}

    i = ruta.index("PROC-REP-211")
    assert ruta[i + 1 : i + 4] == [
        "PROC-REP-125",
        "PROC-REP-126",
        "PROC-REP-127",
    ]
    assert {"PROC-REP-125", "PROC-REP-126", "PROC-REP-127"} <= alcanzados
    assert ruta.count("PROC-REP-125") == 1

    sin_exc = [p.process_id for p in progreso(_en_ejecucion())]
    assert "PROC-REP-125" not in sin_exc


# --- 20. Atomicidad (application) ---


class _RepoEspia:
    def __init__(self, real) -> None:
        self._real = real
        self.guardados = 0

    def guardar(self, orden):
        self.guardados += 1
        return self._real.guardar(orden)

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)


def test_escrituras_de_la_orden_por_comando(tmp_path):
    """126 y 127 (con 080) guardan la Orden una sola vez.

    El cierre por "Requiere redefinicion" reutiliza el cierre comun de
    PROC-REP-200 y, con el, el contrato de PROC-REP-210
    (``aplicar_movimientos_inventario``): la Orden se guarda ANTES de
    tocar el stock del catalogo -para que un reintento sea idempotente- y
    otra vez al final con 211 [-> 125]. Son las mismas dos escrituras que
    "Interrumpido" y "Completado" (TASK-REP-092 sigue abierta). Se fija
    esa paridad en vez de una tercera mecanica.
    """
    from tests.test_api_exc_rep_004 import _hasta_en_ejecucion

    cliente, orden_id, ejecucion_id = _hasta_en_ejecucion(tmp_path)
    with cliente:
        real = construir_contexto(Settings(data_dir=tmp_path))
        espia = _RepoEspia(real.ordenes)
        contexto = ApplicationContext(ordenes=espia, catalogos=real.catalogos)

        orden, _ = requerir_redefinicion_ejecucion(
            contexto,
            orden_id=orden_id,
            ejecucion_id=ejecucion_id,
            usuario_id="TECH-001",
            insumos_utilizados=[],
            motivo=MOTIVO,
        )
        assert espia.guardados == 2  # igual que interrumpir/completar
        assert orden.current_process == "PROC-REP-125"
        assert real.ordenes.obtener(orden_id) == orden

        espia.guardados = 0
        revisar_detalle(
            contexto,
            orden_id=orden_id,
            detalle_id="DET-001",
            usuario_id="TECH-001",
            resultado="Placa",
        )
        assert espia.guardados == 1

        espia.guardados = 0
        orden = redefinir_detalle(
            contexto,
            orden_id=orden_id,
            detalle_id="DET-001",
            usuario_id="RECEP-001",
            tipo_reparacion_id="TR-002",
        )
        assert espia.guardados == 1
        assert orden.historial[-1].referencia_id == "PROC-REP-140"


def test_interrumpir_tambien_escribe_dos_veces(tmp_path):
    """Paridad: el cierre existente (VAR-REP-003) tiene el mismo contrato."""
    from app.application import interrumpir_ejecucion
    from tests.test_api_exc_rep_004 import _hasta_en_ejecucion

    cliente, orden_id, ejecucion_id = _hasta_en_ejecucion(tmp_path)
    with cliente:
        real = construir_contexto(Settings(data_dir=tmp_path))
        espia = _RepoEspia(real.ordenes)
        contexto = ApplicationContext(ordenes=espia, catalogos=real.catalogos)
        interrumpir_ejecucion(
            contexto,
            orden_id=orden_id,
            ejecucion_id=ejecucion_id,
            usuario_id="TECH-001",
            insumos_utilizados=[],
        )
        assert espia.guardados == 2
