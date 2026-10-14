"""Autorizacion del cliente por Detalle: services, resolver y politica.

Complementa ``test_autorizacion_cliente.py`` (HTTP) con lo que la API no
alcanza a mostrar: la politica centralizada por Origen, la prioridad del
resolver, la defensa de la reserva (test 6), la factibilidad limitada a los
autorizados y la carga de datos anteriores.
"""

from decimal import Decimal

import pytest

from app.application import (
    SituacionAutorizacion,
    acciones_de_autorizacion,
    acciones_disponibles,
    situacion_autorizacion,
)
from app.domain.models import (
    CanalComunicacion,
    CondicionReparacionDetail,
    DefinicionAnteriorDetalle,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    OrigenOrden,
    ReparacionDetail,
    ResultadoAutorizacion,
)
from app.domain.politicas import politica_de
from app.services import (
    DecisionDetalle,
    EstadoAutorizacion,
    PrecondicionInvalidaError,
    ResultadoEvaluacionOrden,
    definir_prioridad,
    definir_reparacion_detail,
    estado_autorizacion,
    evaluar_situacion_orden,
    exigir_autorizacion_vigente,
    generar_comprobante_recepcion,
    habilitar_orden,
    ingresar_a_cola,
    intentar_reserva_e_inicio,
    pendiente_de_autorizacion,
    registrar_decision_cliente,
    reservar_insumos_e_iniciar_ejecucion,
    resolver_situacion_orden,
    seleccionar_detalle,
    tomar_orden,
    validar_estacion_trabajo,
    validar_factibilidad_detalles,
    validar_override_recursos,
)
from tests.fixtures import flujo_mvp
from tests.fixtures import flujo_mvp_rt as flujo_rt
from tests.fixtures.catalogos_mvp import (
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


def _decidir(orden, decisiones, minuto=12, usuario=RECEPCION):
    return registrar_decision_cliente(
        orden,
        decisiones=[
            DecisionDetalle(
                detalle_id=detalle_id,
                version_definicion=1,
                resultado=ResultadoAutorizacion(resultado),
            )
            for detalle_id, resultado in decisiones.items()
        ],
        usuario=usuario,
        canal=CanalComunicacion.PRESENCIAL,
        fecha=t(minuto),
    )


def _con_dos_detalles() -> OrdenReparacion:
    """CE con DET-001 y DET-002 definidos y la Orden esperando (129)."""
    orden = flujo_mvp.orden_creada()
    for detalle_id in ("DET-001", "DET-002"):
        orden = definir_reparacion_detail(
            orden,
            detalle_id=detalle_id,
            tipo_reparacion=TIPO_BATERIA,
            usuario=RECEPCION,
            fecha=t(5),
        )
    orden = generar_comprobante_recepcion(orden, fecha=t(10))
    return flujo_mvp.finalizar_esperando_autorizacion(orden, minuto=11)


def _tomada_con_det_002_pendiente() -> OrdenReparacion:
    """DET-001 autorizado, factible, habilitada y tomada; DET-002 no."""
    orden, autorizados = _decidir(
        _con_dos_detalles(), {"DET-001": "AUTORIZADO"}
    )
    orden, factible = validar_factibilidad_detalles(
        orden,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(15),
        detalle_ids=autorizados,
    )
    assert factible
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
    return tomar_orden(
        orden, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )


def _detalle(orden, detalle_id) -> ReparacionDetail:
    return next(d for d in orden.reparaciones_detail if d.id == detalle_id)


# --- Politica por Origen (centralizada) --------------------------------------


def test_solo_cliente_externo_exige_la_autorizacion():
    assert {
        origen: politica_de(origen).requiere_autorizacion_cliente
        for origen in OrigenOrden
    } == {
        OrigenOrden.CLIENTE_EXTERNO: True,
        OrigenOrden.RT_INTERNO: False,
        OrigenOrden.RMA_GARANTIA_REPARACION: False,
    }


def test_rt_interno_no_tiene_estado_de_autorizacion():
    orden = flujo_rt.orden_rt_en_cola()
    (detalle,) = orden.reparaciones_detail
    assert (
        estado_autorizacion(orden, detalle) is EstadoAutorizacion.NO_REQUERIDA
    )
    assert situacion_autorizacion(orden, detalle) is (
        SituacionAutorizacion.NO_REQUERIDA
    )
    assert acciones_de_autorizacion(orden) == []
    with pytest.raises(PrecondicionInvalidaError, match="no requiere"):
        _decidir(orden, {"DET-001": "AUTORIZADO"})


# --- Resolver (BR-REP-012 V1.4) ----------------------------------------------


def _d(detalle_id, estado="DEFINIDO", condicion="SIN_BLOQUEO"):
    return ReparacionDetail(
        id=detalle_id,
        tipo_reparacion_id="TREP-001",
        precio=Decimal("1"),
        puntaje=1,
        garantia_dias=1,
        estado=EstadoReparacionDetail(estado),
        condicion=CondicionReparacionDetail(condicion),
    )


@pytest.mark.parametrize(
    ("detalles", "pendientes", "esperado"),
    [
        # A) autorizado y ejecutable + pendiente: se trabaja el autorizado.
        ([_d("A"), _d("B")], {"B"}, "ABIERTA_TRABAJABLE"),
        # B) todos pendientes.
        ([_d("A"), _d("B")], {"A", "B"}, "PENDIENTE_AUTORIZACION"),
        # C) COMPLETO + pendiente: no hay control final.
        ([_d("A", "COMPLETO"), _d("B")], {"B"}, "PENDIENTE_AUTORIZACION"),
        # F) bloqueado por recursos + pendiente: primero el cliente.
        (
            [_d("A", condicion="BLOQUEADO_POR_RECURSOS"), _d("B")],
            {"B"},
            "PENDIENTE_AUTORIZACION",
        ),
        # G) requiere revision + pendiente: primero la revision.
        (
            [_d("A", condicion="REQUIERE_DEFINICION"), _d("B")],
            {"B"},
            "REQUIERE_REVISION",
        ),
        # H) uno en ejecucion + pendiente: la ejecucion sigue.
        ([_d("A", "EN_PROGRESO"), _d("B")], {"B"}, "EN_EJECUCION"),
        # Lo cancelado no espera nada.
        ([_d("A", "CANCELADO"), _d("B", "COMPLETO")], set(), "COMPLETA"),
    ],
)
def test_resolver_con_detalles_pendientes(detalles, pendientes, esperado):
    assert resolver_situacion_orden(
        detalles, pendientes_autorizacion=pendientes
    ) is ResultadoEvaluacionOrden(esperado)


def test_sin_pendientes_el_resolver_es_el_de_siempre():
    detalles = [_d("A", condicion="BLOQUEADO_POR_RECURSOS")]
    assert resolver_situacion_orden(detalles) is (
        ResultadoEvaluacionOrden.PENDIENTE_RECURSOS
    )


# --- 6. Sin autorizacion no se reserva ---------------------------------------


def test_6_no_se_reserva_ni_selecciona_un_detalle_pendiente():
    orden = _tomada_con_det_002_pendiente()
    assert pendiente_de_autorizacion(orden, _detalle(orden, "DET-002"))

    for intento in (
        reservar_insumos_e_iniciar_ejecucion,
        intentar_reserva_e_inicio,
    ):
        with pytest.raises(PrecondicionInvalidaError, match="autorizacion"):
            intento(
                orden,
                detalle_id="DET-002",
                usuario=TECNICO,
                insumos=INSUMOS,
                insumos_previstos=INSUMOS_PREVISTOS,
                fecha=t(65),
            )
    with pytest.raises(PrecondicionInvalidaError, match="autorizacion"):
        seleccionar_detalle(
            orden, detalle_id="DET-002", usuario=TECNICO, fecha=t(62)
        )
    # No quedo ninguna reserva, Ejecucion ni paso del intento.
    assert orden.movimientos_insumo == []
    assert orden.ejecuciones == []
    # El autorizado si se reserva.
    iniciada = reservar_insumos_e_iniciar_ejecucion(
        orden,
        detalle_id="DET-001",
        usuario=TECNICO,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )
    assert [m.reparacion_detail_id for m in iniciada.movimientos_insumo] == [
        "DET-001"
    ]


def test_la_toma_no_cuenta_un_detalle_pendiente_como_trabajable():
    # JSON anterior: una Orden EN_COLA cuyos Detalles nunca se autorizaron.
    en_cola = _con_dos_detalles().model_copy(
        update={"estado_workflow": EstadoWorkflow.EN_COLA}
    )

    validada, valida = validar_estacion_trabajo(
        en_cola,
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )

    assert valida is False
    assert validada.historial[-1].observacion == (
        "La Orden no tiene ningun Detalle trabajable"
    )


def test_el_override_no_salta_la_autorizacion():
    orden = _con_dos_detalles().model_copy(deep=True)
    # JSON anterior: un Detalle pendiente que quedo bloqueado por recursos.
    _detalle(
        orden, "DET-001"
    ).condicion = CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    with pytest.raises(PrecondicionInvalidaError, match="autorizacion"):
        validar_override_recursos(
            orden,
            detalle_id="DET-001",
            usuario=COORDINADOR,
            motivo="urgente",
        )


# --- Factibilidad ------------------------------------------------------------


def test_la_factibilidad_no_evalua_los_pendientes():
    orden = _con_dos_detalles()
    sin_stock = [
        i.model_copy(update={"stock_fisico": Decimal("0")}) for i in INSUMOS
    ]

    evaluada, factible = validar_factibilidad_detalles(
        orden,
        insumos=sin_stock,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(15),
    )

    assert factible is False
    # Ninguno se marco bloqueado: no se evaluaron.
    assert {d.condicion for d in evaluada.reparaciones_detail} == {
        CondicionReparacionDetail.SIN_BLOQUEO
    }


def test_la_factibilidad_se_limita_a_los_recien_autorizados():
    orden, _ = _decidir(
        _con_dos_detalles(), {"DET-001": "AUTORIZADO", "DET-002": "AUTORIZADO"}
    )
    sin_stock = [
        i.model_copy(update={"stock_fisico": Decimal("0")}) for i in INSUMOS
    ]

    evaluada, factible = validar_factibilidad_detalles(
        orden,
        insumos=sin_stock,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(15),
        detalle_ids=("DET-002",),
        registrar_faltantes=False,
    )

    # DET-001 conserva su condicion (y sigue trabajable): 090 "Si".
    assert _detalle(evaluada, "DET-001").condicion is (
        CondicionReparacionDetail.SIN_BLOQUEO
    )
    assert _detalle(evaluada, "DET-002").condicion is (
        CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    )
    assert factible is True
    assert "PROC-REP-100" not in [p.referencia_id for p in evaluada.historial]


# --- Registro de la decision (service) ---------------------------------------


def test_la_decision_exige_la_definicion_finalizada():
    abierta = flujo_mvp.orden_con_detalle()
    assert pendiente_de_autorizacion(abierta, abierta.reparaciones_detail[0])
    with pytest.raises(PrecondicionInvalidaError, match="finalizar"):
        _decidir(abierta, {"DET-001": "AUTORIZADO"})
    with pytest.raises(
        PrecondicionInvalidaError, match="sin Detalles|no tiene"
    ):
        _decidir(flujo_mvp.orden_creada(), {"DET-001": "AUTORIZADO"})


def test_la_decision_no_modifica_la_orden_recibida():
    orden = _con_dos_detalles()
    copia = orden.model_copy(deep=True)

    nueva, autorizados = _decidir(
        orden, {"DET-001": "AUTORIZADO", "DET-002": "RECHAZADO"}
    )

    assert orden == copia
    assert autorizados == ("DET-001",)
    assert (
        _detalle(nueva, "DET-002").estado is EstadoReparacionDetail.CANCELADO
    )


def test_un_detalle_que_ya_no_espera_decision_no_se_decide():
    """JSON anterior: lo ejecutado sin decision queda SIN_DECISION."""
    orden = flujo_mvp.orden_esperando_autorizacion().model_copy(deep=True)
    (detalle,) = orden.reparaciones_detail
    for estado, texto in (
        (EstadoReparacionDetail.COMPLETO, "COMPLETO"),
        (EstadoReparacionDetail.EN_PROGRESO, "Ejecucion activa"),
    ):
        detalle.estado = estado
        assert estado_autorizacion(orden, detalle) is (
            EstadoAutorizacion.SIN_DECISION
        )
        with pytest.raises(PrecondicionInvalidaError, match=texto):
            _decidir(orden, {"DET-001": "RECHAZADO"})


def test_211_con_la_definicion_abierta_no_la_cierra():
    """Cancelar un Detalle mientras se cargan: no se espera al cliente."""
    orden = flujo_mvp.orden_con_detalle()

    evaluada, resultado = evaluar_situacion_orden(orden, fecha=t(11))

    assert resultado is ResultadoEvaluacionOrden.PENDIENTE_AUTORIZACION
    assert evaluada.current_process == "PROC-REP-211"
    assert "FINALIZAR_DEFINICION" in [
        a.codigo for a in acciones_disponibles(evaluada)
    ]


def test_exigir_autorizacion_avisa_que_la_decision_es_de_otra_version():
    orden, _ = _decidir(_con_dos_detalles(), {"DET-001": "AUTORIZADO"})
    redefinido = orden.model_copy(deep=True)
    detalle = _detalle(redefinido, "DET-001")
    exigir_autorizacion_vigente(redefinido, detalle)  # v1 autorizada
    # Una redefinicion (127) agrega la definicion reemplazada: v2.
    detalle.definiciones_anteriores.append(
        DefinicionAnteriorDetalle(
            tipo_reparacion_id=detalle.tipo_reparacion_id,
            precio=detalle.precio,
            puntaje=detalle.puntaje,
            garantia_dias=detalle.garantia_dias,
            reemplazada_en=t(30),
            usuario_id=RECEPCION.id,
        )
    )

    with pytest.raises(PrecondicionInvalidaError, match="v1, anterior"):
        exigir_autorizacion_vigente(redefinido, detalle)


# --- 19. Datos anteriores ----------------------------------------------------


def test_19_un_detalle_json_anterior_carga_sin_autorizaciones():
    datos = flujo_mvp.orden_en_cola().model_dump(mode="json")
    for detalle in datos["reparaciones_detail"]:
        detalle.pop("autorizaciones")

    legado = OrdenReparacion.model_validate(datos)

    (detalle,) = legado.reparaciones_detail
    assert detalle.autorizaciones == []
    assert detalle.version_definicion == 1
    # No se presume ninguna autorizacion: queda pendiente y no se toma.
    assert estado_autorizacion(legado, detalle) is EstadoAutorizacion.PENDIENTE
    assert "TOMAR" not in [a.codigo for a in acciones_disponibles(legado)]
    assert [a.codigo for a in acciones_de_autorizacion(legado)] == [
        "REGISTRAR_DECISION_CLIENTE"
    ]
    # La version derivada no se persiste.
    assert (
        "version_definicion"
        not in legado.model_dump()["reparaciones_detail"][0]
    )
