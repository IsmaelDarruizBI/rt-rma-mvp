"""Autorizacion del cliente por Detalle (BR-REP-028/029/037) por HTTP.

    POST /api/orders/{id}/authorizations           046 -> 047 [-> 300|305]
    GET  /api/orders/{id}/authorizations           decision por Detalle
    GET  /api/orders/authorizations/pending        pendientes de decidir

En CLIENTE_EXTERNO, finalizar la definicion deja los Detalles pendientes de
autorizacion (PROC-REP-129). Recepcion registra lo que el cliente respondio
por Detalle: AUTORIZADO pasa a factibilidad, RECHAZADO se cancela (origen
RECHAZO_CLIENTE) y lo no respondido sigue pendiente sin bloquear a los
demas. Nada pendiente se ejecuta ni reserva, y la Orden no llega al control
mientras quede algo pendiente.

Catalogos propios en ``tmp_path`` (``tests.fixtures.api_salidas``).
"""

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import OrdenReparacion
from app.main import create_app
from app.storage.json.base import escribir_json_atomico
from tests.fixtures.api_definicion import definir_y_finalizar
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    COORDINADOR,
    INSUMO_BATERIA,
    INSUMO_PANTALLA,
    PANTALLA,
    RECEPCION,
    TECNICO,
    aprobar,
    archivo,
    cancelar_detalle,
    cerrar_ejecucion,
    cliente_http,
    codigos,
    conflicto,
    decidir,
    definida,
    detalle,
    devolver,
    ejecutar,
    ids,
    iniciar,
    notificar_pagar_entregar,
    ok,
    repo_ordenes,
    stock,
    tomada,
    tomar,
)
from tests.test_api_hp_rep_002 import TIPO, _crear_orden_rt, _sembrar_catalogos
from tests.test_api_hp_rep_003 import _garantia_definida, _orden_entregada


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def _finalizada(cliente, *tipos) -> str:
    """Definicion finalizada: los Detalles esperan la decision (129)."""
    return definida(cliente, *tipos, autorizar=False)


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _situaciones(orden: dict) -> dict[str, str]:
    return {
        d["id"]: d["situacion_autorizacion"]
        for d in orden["reparaciones_detail"]
    }


def _decisiones_ofrecidas(orden: dict) -> list[tuple[str, str | None]]:
    return [
        (a["codigo"], a["detalle_id"]) for a in orden["acciones_autorizacion"]
    ]


def _fijar_stock(directorio, insumo_id: str, valor: str) -> None:
    ruta = directorio / "catalogs" / "insumos.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    for insumo in datos:
        if insumo["id"] == insumo_id:
            insumo["stock_fisico"] = valor
    escribir_json_atomico(ruta, datos)


def _hasta_125(cliente, orden_id) -> None:
    """DET-001 autorizado, tomado, y su ejecucion pide redefinicion."""
    ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    tomada(cliente, orden_id)
    ejecucion_id = iniciar(cliente, orden_id)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion_id}"
            "/requires-redefinition",
            json={
                "usuario_id": TECNICO,
                "insumos_utilizados": [],
                "motivo": "La pantalla tambien esta rota.",
            },
        )
    )


def _redefinido(cliente, orden_id) -> dict:
    """125 -> 126 -> 127: DET-001 pasa a una definicion nueva (v2)."""
    _hasta_125(cliente, orden_id)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/technical-review",
            json={"usuario_id": TECNICO, "resultado": "Display partido"},
        )
    )
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/redefine",
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": PANTALLA},
        )
    )


# --- 1. Autorizar todo -------------------------------------------------------


def test_1_autorizar_todo_pasa_a_factibilidad_y_habilita(cliente):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA)
    orden = _orden(cliente, orden_id)
    assert orden["current_process"] == "PROC-REP-129"
    assert orden["estado_workflow"] == "REQUERIMIENTO"
    assert "PROC-REP-080" not in ids(orden)
    assert {
        d["estado_autorizacion"] for d in orden["reparaciones_detail"]
    } == {"PENDIENTE"}
    assert [a["codigo"] for a in orden["acciones_autorizacion"]] == [
        "REGISTRAR_DECISION_CLIENTE"
    ]

    orden = ok(
        decidir(
            cliente,
            orden_id,
            {"DET-001": "AUTORIZADO", "DET-002": "AUTORIZADO"},
            observaciones="Acepta el presupuesto.",
        )
    )

    assert ids(orden)[-6:] == [
        "PROC-REP-046",
        "PROC-REP-046",
        "PROC-REP-047",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]
    assert orden["historial"][-4]["observacion"] == "ACEPTA_TRABAJOS"
    paso_046 = orden["historial"][-6]
    assert paso_046["usuario_id"] == RECEPCION
    assert paso_046["reparacion_detail_id"] == "DET-001"
    assert "AUTORIZADO" in paso_046["observacion"]
    assert "v1" in paso_046["observacion"]
    assert "WHATSAPP" in paso_046["observacion"]
    assert orden["estado_workflow"] == "HABILITADA"
    for d in orden["reparaciones_detail"]:
        assert d["estado_autorizacion"] == "AUTORIZADO"
        assert d["situacion_autorizacion"] == "AUTORIZADO_FACTIBLE"
        (registro,) = d["autorizaciones"]
        assert registro["version_definicion"] == 1
        assert registro["resultado"] == "AUTORIZADO"
        assert registro["usuario_id"] == RECEPCION
        assert registro["canal"] == "WHATSAPP"
        assert registro["observaciones"] == "Acepta el presupuesto."
        assert registro["fecha"] is not None
    # Nada pendiente: queda solo desistir de lo autorizado.
    assert _decisiones_ofrecidas(orden) == [
        ("DESISTIR_DETALLE", "DET-001"),
        ("DESISTIR_DETALLE", "DET-002"),
        ("DESISTIR_TODO", None),
    ]
    assert "ENCOLAR" in codigos(orden)


# --- 2. Autorizar algunos y rechazar otros -----------------------------------


def test_2_autorizar_algunos_y_rechazar_otros(cliente):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA)

    orden = ok(
        decidir(
            cliente,
            orden_id,
            {"DET-001": "AUTORIZADO", "DET-002": "RECHAZADO"},
            observaciones="No quiere cambiar la pantalla.",
        )
    )

    assert ids(orden)[-7:] == [
        "PROC-REP-046",
        "PROC-REP-046",
        "PROC-REP-047",
        "PROC-REP-300",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]
    assert orden["historial"][-5]["observacion"] == "RECHAZA_ALGUNOS_DETALLES"
    rechazado = detalle(orden, "DET-002")
    assert rechazado["estado"] == "CANCELADO"
    assert rechazado["estado_autorizacion"] == "RECHAZADO"
    assert rechazado["situacion_autorizacion"] == "CANCELADO_POR_RECHAZO"
    assert rechazado["cancelacion"]["origen"] == "RECHAZO_CLIENTE"
    assert rechazado["cancelacion"]["motivo"] == (
        "Rechazo del cliente (WHATSAPP): No quiere cambiar la pantalla."
    )
    # Cancelar no borra: conserva Tipo, precio snapshot y la decision.
    assert rechazado["precio"] == "50000"
    assert [r["resultado"] for r in rechazado["autorizaciones"]] == [
        "RECHAZADO"
    ]
    autorizado = detalle(orden, "DET-001")
    assert autorizado["situacion_autorizacion"] == "AUTORIZADO_FACTIBLE"
    assert orden["estado_workflow"] == "HABILITADA"
    assert Decimal(orden["resumen"]["total"]) == Decimal("80000")


# --- 3. Rechazar todo --------------------------------------------------------


def test_3_rechazar_todo_cancela_y_espera_la_devolucion(cliente):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA)

    orden = ok(
        decidir(
            cliente,
            orden_id,
            {"DET-001": "RECHAZADO", "DET-002": "RECHAZADO"},
            canal="PRESENCIAL",
        )
    )

    assert ids(orden)[-5:] == [
        "PROC-REP-046",
        "PROC-REP-046",
        "PROC-REP-047",
        "PROC-REP-305",
        "PROC-REP-211",
    ]
    assert orden["historial"][-3]["observacion"] == (
        "RECHAZA_TODOS_LOS_TRABAJOS"
    )
    assert orden["historial"][-1]["observacion"] == "TODO_CANCELADO"
    assert orden["estado_workflow"] == "CANCELADA"
    assert {
        d["cancelacion"]["origen"] for d in orden["reparaciones_detail"]
    } == {"RECHAZO_CLIENTE"}
    assert Decimal(orden["resumen"]["total"]) == Decimal("0")
    # El comprobante se emitio: el equipo esta en custodia y se devuelve.
    assert orden["devolucion_pendiente"] is True
    assert codigos(orden) == ["REGISTRAR_DEVOLUCION"]
    assert orden["acciones_autorizacion"] == []

    cerrada = ok(devolver(cliente, orden_id, recibido_por="Cliente"))
    assert cerrada["cerrada"] is True
    assert cerrada["estado_workflow"] == "CANCELADA"


# --- 4. Pendiente sin respuesta ----------------------------------------------


def test_4_sin_respuesta_no_registra_nada_ni_bloquea_a_los_demas(
    cliente, tmp_path
):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA)
    antes = archivo(tmp_path, orden_id)

    # "Sin respuesta" no es una decision: una operacion vacia no aplica.
    mensaje = conflicto(decidir(cliente, orden_id, {}))
    assert "no se registra nada" in mensaje
    assert archivo(tmp_path, orden_id) == antes

    orden = ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))

    pendiente = detalle(orden, "DET-002")
    assert pendiente["estado"] == "DEFINIDO"
    assert pendiente["estado_autorizacion"] == "PENDIENTE"
    assert pendiente["situacion_autorizacion"] == "PENDIENTE_AUTORIZACION"
    assert pendiente["autorizaciones"] == []
    # El pendiente no bloquea al autorizado: la Orden se habilita igual.
    assert orden["estado_workflow"] == "HABILITADA"
    assert orden["historial"][-4]["observacion"] == "ACEPTA_TRABAJOS"
    assert _decisiones_ofrecidas(orden) == [
        ("REGISTRAR_DECISION_CLIENTE", None),
        ("DESISTIR_DETALLE", "DET-001"),
        ("DESISTIR_TODO", None),
    ]
    pendientes = ok(cliente.get("/api/orders/authorizations/pending"))
    assert [(p["orden_id"], p["detalle_id"]) for p in pendientes] == [
        (orden_id, "DET-002")
    ]
    assert pendientes[0]["precio"] == "50000"
    assert pendientes[0]["version_definicion"] == 1


# --- 5. Sin autorizacion no hay ejecucion ------------------------------------


def test_5_un_detalle_pendiente_no_se_inicia(cliente, tmp_path):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA)
    ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    orden = tomada(cliente, orden_id)

    iniciables = [
        a["detalle_id"]
        for a in orden["acciones_disponibles"]
        if a["codigo"] == "INICIAR_DETALLE"
    ]
    assert iniciables == ["DET-001"]

    antes = archivo(tmp_path, orden_id)
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/details/DET-002/start",
        json={"usuario_id": TECNICO},
    )
    mensaje = conflicto(respuesta)
    assert "autorizacion del cliente" in mensaje
    assert archivo(tmp_path, orden_id) == antes
    orden = _orden(cliente, orden_id)
    assert orden["ejecuciones"] == []
    assert stock(tmp_path, INSUMO_PANTALLA) == Decimal("5")


# --- 7. Rechazo y cancelacion individual -------------------------------------


def test_7_rechazo_individual_distinto_de_la_cancelacion_interna(cliente):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA, BATERIA)
    ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    # Recepcion cancela DET-003 por su cuenta (no es una decision del
    # cliente): cancelacion interna de un Detalle todavia pendiente.
    interna = ok(cancelar_detalle(cliente, orden_id, "DET-003"))
    assert detalle(interna, "DET-003")["cancelacion"]["origen"] == "INTERNA"
    assert detalle(interna, "DET-003")["estado_autorizacion"] == (
        "SIN_DECISION"
    )
    assert _situaciones(interna)["DET-003"] == "CANCELADO"

    orden = ok(
        decidir(
            cliente,
            orden_id,
            {"DET-002": "RECHAZADO"},
            canal="TELEFONO",
            observaciones="Llamado 14:30",
        )
    )

    assert ids(orden)[-3:] == ["PROC-REP-047", "PROC-REP-300", "PROC-REP-211"]
    assert orden["historial"][-3]["observacion"] == "RECHAZA_ALGUNOS_DETALLES"
    rechazado = detalle(orden, "DET-002")
    assert rechazado["cancelacion"]["origen"] == "RECHAZO_CLIENTE"
    assert rechazado["cancelacion"]["usuario_id"] == RECEPCION
    assert "Llamado 14:30" in rechazado["cancelacion"]["motivo"]
    assert _situaciones(orden) == {
        "DET-001": "AUTORIZADO_FACTIBLE",
        "DET-002": "CANCELADO_POR_RECHAZO",
        "DET-003": "CANCELADO",
    }
    assert _decisiones_ofrecidas(orden) == [
        ("DESISTIR_DETALLE", "DET-001"),
        ("DESISTIR_TODO", None),
    ]


# --- 8. Autorizacion parcial con factibilidad --------------------------------


def test_8_autorizado_sin_stock_no_bloquea_al_factible(cliente, tmp_path):
    _fijar_stock(tmp_path, INSUMO_PANTALLA, "0")
    orden_id = _finalizada(cliente, BATERIA, PANTALLA)

    orden = ok(
        decidir(
            cliente,
            orden_id,
            {"DET-001": "AUTORIZADO", "DET-002": "AUTORIZADO"},
        )
    )

    assert _situaciones(orden) == {
        "DET-001": "AUTORIZADO_FACTIBLE",
        "DET-002": "AUTORIZADO_SIN_STOCK",
    }
    assert detalle(orden, "DET-002")["condicion"] == "BLOQUEADO_POR_RECURSOS"
    assert orden["historial"][-2]["observacion"] == "Si"
    assert orden["estado_workflow"] == "HABILITADA"
    assert "OVERRIDE_RECURSOS" in codigos(orden)


def test_8_un_unico_autorizado_sin_stock_queda_en_100(cliente, tmp_path):
    _fijar_stock(tmp_path, INSUMO_PANTALLA, "0")
    orden_id = _finalizada(cliente, PANTALLA)

    orden = ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))

    assert ids(orden)[-4:] == [
        "PROC-REP-047",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-100",
    ]
    assert orden["estado_workflow"] == "REQUERIMIENTO"
    assert "ESPERAR_RECURSOS" in codigos(orden)


# --- 9. Varios Detalles en situaciones distintas -----------------------------


def test_9_varios_detalles_en_situaciones_distintas(cliente, tmp_path):
    _fijar_stock(tmp_path, INSUMO_PANTALLA, "0")
    orden_id = _finalizada(cliente, BATERIA, PANTALLA, BATERIA, PANTALLA)

    ok(
        decidir(
            cliente,
            orden_id,
            {
                "DET-001": "AUTORIZADO",
                "DET-002": "AUTORIZADO",
                "DET-004": "RECHAZADO",
            },
        )
    )
    consulta = ok(cliente.get(f"/api/orders/{orden_id}/authorizations"))

    assert consulta["requerida"] is True
    assert consulta["registrable"] is True
    por_id = {d["detalle_id"]: d for d in consulta["detalles"]}
    assert {i: d["situacion"] for i, d in por_id.items()} == {
        "DET-001": "AUTORIZADO_FACTIBLE",
        "DET-002": "AUTORIZADO_SIN_STOCK",
        "DET-003": "PENDIENTE_AUTORIZACION",
        "DET-004": "CANCELADO_POR_RECHAZO",
    }
    assert [i for i, d in por_id.items() if d["decidible"]] == ["DET-003"]
    assert por_id["DET-001"]["decision_vigente"]["resultado"] == "AUTORIZADO"
    assert por_id["DET-003"]["decision_vigente"] is None
    assert por_id["DET-004"]["tipo_reparacion_nombre"] == "Cambio de pantalla"
    assert por_id["DET-004"]["precio"] == "50000"

    # Se trabaja el factible. Despues no queda nada trabajable: el pendiente
    # de autorizacion tiene prioridad sobre el bloqueo por recursos (V1.4).
    tomada(cliente, orden_id)
    orden = ejecutar(cliente, orden_id, "DET-001")
    assert orden["historial"][-2]["observacion"] == "PENDIENTE_AUTORIZACION"
    assert orden["current_process"] == "PROC-REP-129"
    assert _situaciones(orden)["DET-001"] == "COMPLETO"


# --- 10/11/12. Redefinicion y version de la definicion -----------------------


def test_10_la_redefinicion_invalida_la_autorizacion(cliente):
    orden_id = _finalizada(cliente, BATERIA)

    orden = _redefinido(cliente, orden_id)

    assert ids(orden)[-3:] == ["PROC-REP-127", "PROC-REP-211", "PROC-REP-129"]
    redefinido = detalle(orden, "DET-001")
    assert redefinido["version_definicion"] == 2
    assert redefinido["estado_autorizacion"] == "PENDIENTE"
    assert redefinido["tipo_reparacion_id"] == PANTALLA
    # La definicion anterior y su autorizacion se conservan como historia.
    (anterior,) = redefinido["definiciones_anteriores"]
    assert anterior["tipo_reparacion_id"] == BATERIA
    (vieja,) = redefinido["autorizaciones"]
    assert (vieja["version_definicion"], vieja["resultado"]) == (
        1,
        "AUTORIZADO",
    )
    # Bloqueada la ejecucion hasta la nueva decision: no hay toma posible.
    assert "TOMAR" not in codigos(orden)
    assert [t["estado"] for t in orden["tomas"]] == ["CERRADA"]
    assert [a["codigo"] for a in orden["acciones_autorizacion"]] == [
        "REGISTRAR_DECISION_CLIENTE"
    ]


def test_11_la_autorizacion_queda_atada_a_su_version(cliente):
    orden_id = _finalizada(cliente, BATERIA)
    _redefinido(cliente, orden_id)

    consulta = ok(cliente.get(f"/api/orders/{orden_id}/authorizations"))
    (vista,) = consulta["detalles"]
    assert vista["version_definicion"] == 2
    assert vista["decision_vigente"] is None
    assert [h["version_definicion"] for h in vista["historial"]] == [1]

    orden = ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))

    redefinido = detalle(orden, "DET-001")
    assert [
        (r["version_definicion"], r["resultado"])
        for r in redefinido["autorizaciones"]
    ] == [(1, "AUTORIZADO"), (2, "AUTORIZADO")]
    # Factibilidad de la definicion nueva y, ya habilitada, vuelta a la
    # cola con su prioridad (sin repetir 140/150).
    assert ids(orden)[-6:] == [
        "PROC-REP-046",
        "PROC-REP-047",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-211",
        "PROC-REP-170",
    ]
    assert orden["estado_workflow"] == "EN_COLA"
    tomar(cliente, orden_id)
    iniciar(cliente, orden_id)


def test_12_una_respuesta_de_una_version_anterior_se_rechaza(
    cliente, tmp_path
):
    orden_id = _finalizada(cliente, BATERIA)
    _redefinido(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(
        decidir(
            cliente,
            orden_id,
            {"DET-001": "AUTORIZADO"},
            versiones={"DET-001": 1},
        )
    )

    assert "v1" in mensaje and "vigente es v2" in mensaje
    assert archivo(tmp_path, orden_id) == antes
    # Tampoco se acepta una version futura.
    conflicto(
        decidir(
            cliente,
            orden_id,
            {"DET-001": "AUTORIZADO"},
            versiones={"DET-001": 3},
        )
    )
    assert archivo(tmp_path, orden_id) == antes


# --- 13. Sin control con Detalles pendientes ---------------------------------


def test_13_no_hay_control_mientras_quede_un_detalle_pendiente(cliente):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA)
    ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    tomada(cliente, orden_id)

    orden = ejecutar(cliente, orden_id, "DET-001")

    assert ids(orden)[-2:] == ["PROC-REP-211", "PROC-REP-129"]
    assert orden["historial"][-2]["observacion"] == "PENDIENTE_AUTORIZACION"
    assert [t["estado"] for t in orden["tomas"]] == ["CERRADA"]
    assert "APROBAR_CONTROL" not in codigos(orden)
    conflicto(aprobar(cliente, orden_id, "DET-001"))

    # Resuelto el pendiente (rechazo), lo realizado sigue al control.
    orden = ok(decidir(cliente, orden_id, {"DET-002": "RECHAZADO"}))
    assert orden["historial"][-1]["observacion"] == "COMPLETA"
    assert "APROBAR_CONTROL" in codigos(orden)


# --- 14/15. Orden ya habilitada: toma, ejecucion y prioridad -----------------


def test_14_autorizar_con_una_ejecucion_en_curso_no_la_interrumpe(cliente):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA)
    ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    tomada(cliente, orden_id)
    ejecucion_id = iniciar(cliente, orden_id, "DET-001")
    toma_id = _orden(cliente, orden_id)["toma_activa"]["id"]

    orden = ok(decidir(cliente, orden_id, {"DET-002": "AUTORIZADO"}))

    assert ids(orden)[-5:] == [
        "PROC-REP-046",
        "PROC-REP-047",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-211",
    ]
    assert orden["historial"][-1]["observacion"] == "EN_EJECUCION"
    (ejecucion,) = orden["ejecuciones"]
    assert (ejecucion["id"], ejecucion["estado"]) == (
        ejecucion_id,
        "EN_PROGRESO",
    )
    assert orden["toma_activa"]["id"] == toma_id
    assert ids(orden).count("PROC-REP-140") == 1
    assert ids(orden).count("PROC-REP-150") == 1
    assert orden["prioridad"] == 3

    # Al terminar, el mismo tecnico sigue con el autorizado, sin retomar.
    orden = ok(cerrar_ejecucion(cliente, orden_id, ejecucion_id))
    assert orden["historial"][-1]["observacion"] == "ABIERTA_TRABAJABLE"
    assert orden["toma_activa"]["id"] == toma_id
    iniciar(cliente, orden_id, "DET-002")


def test_15_tras_esperar_al_cliente_vuelve_a_la_cola_con_su_prioridad(
    cliente,
):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA)
    ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id, "DET-001")  # -> 129, toma cerrada

    orden = ok(decidir(cliente, orden_id, {"DET-002": "AUTORIZADO"}))

    assert ids(orden)[-2:] == ["PROC-REP-211", "PROC-REP-170"]
    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["prioridad"] == 3
    assert ids(orden).count("PROC-REP-140") == 1
    assert ids(orden).count("PROC-REP-150") == 1
    assert [t["estado"] for t in orden["tomas"]] == ["CERRADA"]
    orden = tomar(cliente, orden_id)
    assert [t["estado"] for t in orden["tomas"]] == ["CERRADA", "ACTIVA"]


# --- 16. Orden cerrada -------------------------------------------------------


def test_16_una_orden_cerrada_no_registra_decisiones(cliente, tmp_path):
    entregada = definida(cliente, BATERIA)
    tomada(cliente, entregada)
    ejecutar(cliente, entregada)
    ok(aprobar(cliente, entregada, "DET-001"))
    notificar_pagar_entregar(cliente, entregada)
    antes = archivo(tmp_path, entregada)

    conflicto(
        decidir(cliente, entregada, {"DET-001": "AUTORIZADO"}),
        codigo="ORDEN_CERRADA",
    )
    assert archivo(tmp_path, entregada) == antes

    devuelta = _finalizada(cliente, BATERIA)
    ok(decidir(cliente, devuelta, {"DET-001": "RECHAZADO"}))
    ok(devolver(cliente, devuelta))
    conflicto(
        decidir(cliente, devuelta, {"DET-001": "AUTORIZADO"}),
        codigo="ORDEN_CERRADA",
    )


# --- 17. Permisos ------------------------------------------------------------


@pytest.mark.parametrize("usuario", [TECNICO, COORDINADOR, ADMINISTRADOR])
def test_17_solo_recepcion_registra_la_decision(cliente, tmp_path, usuario):
    orden_id = _finalizada(cliente, BATERIA)
    antes = archivo(tmp_path, orden_id)

    conflicto(
        decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}, usuario=usuario)
    )

    assert archivo(tmp_path, orden_id) == antes


def test_17_usuario_inexistente_y_request_mal_formado(cliente, tmp_path):
    orden_id = _finalizada(cliente, BATERIA)
    antes = archivo(tmp_path, orden_id)

    respuesta = decidir(
        cliente, orden_id, {"DET-001": "AUTORIZADO"}, usuario="NADIE"
    )
    assert respuesta.status_code == 404, respuesta.text
    for cuerpo in (
        {"canal": "SMS"},
        {"resultado": "PENDIENTE"},
        {"version_definicion": 0},
    ):
        decision = {
            "detalle_id": "DET-001",
            "version_definicion": 1,
            "resultado": "AUTORIZADO",
        }
        datos = {"usuario_id": RECEPCION, "canal": "PRESENCIAL"}
        datos.update({k: v for k, v in cuerpo.items() if k == "canal"})
        decision.update({k: v for k, v in cuerpo.items() if k != "canal"})
        datos["decisiones"] = [decision]
        respuesta = cliente.post(
            f"/api/orders/{orden_id}/authorizations", json=datos
        )
        assert respuesta.status_code == 422, (cuerpo, respuesta.text)
    assert archivo(tmp_path, orden_id) == antes


# --- 18. Reintentos sin duplicacion ------------------------------------------


def test_18_reintentar_no_duplica_decisiones_ni_cancelaciones(cliente):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA)
    ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    ok(decidir(cliente, orden_id, {"DET-002": "RECHAZADO"}))
    despues = _orden(cliente, orden_id)

    mensaje = conflicto(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    assert "no se reemplaza" in mensaje
    conflicto(decidir(cliente, orden_id, {"DET-002": "RECHAZADO"}))
    # Ni siquiera para cambiar la decision ya registrada.
    conflicto(decidir(cliente, orden_id, {"DET-001": "RECHAZADO"}))

    orden = _orden(cliente, orden_id)
    assert orden == despues
    assert ids(orden).count("PROC-REP-046") == 2
    assert ids(orden).count("PROC-REP-300") == 1
    assert len(detalle(orden, "DET-001")["autorizaciones"]) == 1
    assert len(detalle(orden, "DET-002")["autorizaciones"]) == 1


def test_18_una_operacion_mixta_invalida_no_aplica_nada(cliente, tmp_path):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA, BATERIA)
    ok(decidir(cliente, orden_id, {"DET-003": "AUTORIZADO"}))
    antes = archivo(tmp_path, orden_id)

    # Un Detalle inexistente, uno ya decidido o el mismo dos veces: la
    # operacion entera se rechaza, sin autorizar ni cancelar nada.
    respuesta = decidir(
        cliente, orden_id, {"DET-001": "AUTORIZADO", "DET-999": "RECHAZADO"}
    )
    assert respuesta.status_code == 404, respuesta.text
    conflicto(
        decidir(
            cliente,
            orden_id,
            {
                "DET-001": "AUTORIZADO",
                "DET-002": "RECHAZADO",
                "DET-003": "RECHAZADO",
            },
        )
    )
    repetido = cliente.post(
        f"/api/orders/{orden_id}/authorizations",
        json={
            "usuario_id": RECEPCION,
            "canal": "EMAIL",
            "decisiones": [
                {
                    "detalle_id": "DET-001",
                    "version_definicion": 1,
                    "resultado": resultado,
                }
                for resultado in ("AUTORIZADO", "RECHAZADO")
            ],
        },
    )
    conflicto(repetido)
    assert archivo(tmp_path, orden_id) == antes


def test_18_no_se_rechaza_un_detalle_completo_ni_uno_en_ejecucion(cliente):
    orden_id = _finalizada(cliente, BATERIA, PANTALLA, BATERIA)
    ok(
        decidir(
            cliente,
            orden_id,
            {"DET-001": "AUTORIZADO", "DET-002": "AUTORIZADO"},
        )
    )
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id, "DET-001", tipo=BATERIA)
    iniciar(cliente, orden_id, "DET-002")

    completo = conflicto(decidir(cliente, orden_id, {"DET-001": "RECHAZADO"}))
    en_curso = conflicto(decidir(cliente, orden_id, {"DET-002": "RECHAZADO"}))

    assert "ya tiene la decision" in completo
    assert "ya tiene la decision" in en_curso
    orden = _orden(cliente, orden_id)
    assert detalle(orden, "DET-001")["estado"] == "COMPLETO"
    assert detalle(orden, "DET-002")["estado"] == "EN_PROGRESO"
    # El pendiente si puede rechazarse sin tocar la ejecucion en curso.
    orden = ok(decidir(cliente, orden_id, {"DET-003": "RECHAZADO"}))
    assert detalle(orden, "DET-002")["estado"] == "EN_PROGRESO"
    assert orden["historial"][-1]["observacion"] == "EN_EJECUCION"


# --- 19. Compatibilidad JSON -------------------------------------------------


def test_19_una_orden_json_anterior_queda_pendiente_y_no_se_ejecuta(
    cliente, tmp_path
):
    """Politica de compatibilidad: sin autorizacion registrada, pendiente.

    Una Orden CLIENTE_EXTERNO guardada antes de esta version (sin
    ``autorizaciones`` ni ``cancelacion.origen``) sigue cargando y se puede
    consultar; su Detalle DEFINIDO queda PENDIENTE -no se presume una
    autorizacion que nadie registro- y no se toma ni se ejecuta hasta que
    Recepcion registre la decision.
    """
    orden_id = definida(cliente, BATERIA, PANTALLA)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/queue",
            json={"usuario_id": COORDINADOR, "prioridad": 2},
        )
    )
    ok(cancelar_detalle(cliente, orden_id, "DET-002"))
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    crudo = json.loads(ruta.read_text(encoding="utf-8"))
    for d in crudo["reparaciones_detail"]:
        d.pop("autorizaciones")
        if d["cancelacion"]:
            d["cancelacion"].pop("origen")
    crudo["historial"] = [
        p
        for p in crudo["historial"]
        if p["referencia_id"] not in ("PROC-REP-046", "PROC-REP-047")
    ]
    ruta.write_text(json.dumps(crudo), encoding="utf-8")

    legado = _orden(cliente, orden_id)

    assert legado["estado_workflow"] == "EN_COLA"
    assert detalle(legado, "DET-001")["estado_autorizacion"] == "PENDIENTE"
    assert detalle(legado, "DET-002")["cancelacion"]["origen"] == "INTERNA"
    assert detalle(legado, "DET-002")["estado_autorizacion"] == "SIN_DECISION"
    assert "TOMAR" not in codigos(legado)
    conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": TECNICO, "estacion_id": "EST-001"},
        )
    )
    assert (
        OrdenReparacion.model_validate(
            json.loads(ruta.read_text(encoding="utf-8"))
        )
        .reparaciones_detail[0]
        .autorizaciones
        == []
    )

    orden = ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["historial"][-1]["observacion"] == "ABIERTA_TRABAJABLE"
    assert "TOMAR" in codigos(orden)


def test_19_una_orden_json_anterior_ya_entregada_se_consulta(
    cliente, tmp_path
):
    orden_id = definida(cliente, BATERIA)
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id)
    ok(aprobar(cliente, orden_id, "DET-001"))
    notificar_pagar_entregar(cliente, orden_id)
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    crudo = json.loads(ruta.read_text(encoding="utf-8"))
    for d in crudo["reparaciones_detail"]:
        d.pop("autorizaciones")
    ruta.write_text(json.dumps(crudo), encoding="utf-8")

    legado = _orden(cliente, orden_id)

    assert legado["cerrada"] is True
    assert detalle(legado, "DET-001")["estado_autorizacion"] == "SIN_DECISION"
    assert detalle(legado, "DET-001")["situacion_autorizacion"] == "COMPLETO"
    assert (
        ok(cliente.get(f"/api/orders/{orden_id}/authorizations"))[
            "registrable"
        ]
        is False
    )
    assert repo_ordenes(tmp_path).obtener(orden_id).id == orden_id


# --- 20. Sin regresiones en RT_INTERNO y RMA ---------------------------------


def test_20_rt_interno_y_garantia_rma_no_piden_autorizacion(tmp_path):
    _sembrar_catalogos(tmp_path, stock="5")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as http:
        rt_id = _crear_orden_rt(http)
        rt = ok(
            definir_y_finalizar(
                http,
                rt_id,
                json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
                autorizar=False,
            )
        )
        origen = _orden_entregada(http)
        garantia = ok(_garantia_definida(http, origen["id"]))

        for orden in (rt, garantia):
            assert orden["estado_workflow"] == "HABILITADA"
            assert orden["autorizacion_requerida"] is False
            assert orden["acciones_autorizacion"] == []
            assert not {"PROC-REP-046", "PROC-REP-129"} & set(ids(orden))
            (d,) = orden["reparaciones_detail"]
            assert d["estado_autorizacion"] == "NO_REQUERIDA"
            assert d["situacion_autorizacion"] == "NO_REQUERIDA"
            mensaje = conflicto(
                decidir(http, orden["id"], {"DET-001": "AUTORIZADO"})
            )
            assert "no requiere" in mensaje
            assert (
                ok(http.get(f"/api/orders/{orden['id']}/authorizations"))[
                    "requerida"
                ]
                is False
            )
        assert ok(http.get("/api/orders/authorizations/pending")) == []


# --- Circuitos por HTTP ------------------------------------------------------


def test_circuito_autorizacion_parcial_hasta_la_entrega(cliente, tmp_path):
    """CE con dos Detalles: uno autorizado, otro pendiente hasta el final.

    Factibilidad del autorizado -> toma -> ejecucion -> la Orden espera la
    decision del segundo (sin control) -> se autoriza y ejecuta -> control
    -> pago -> entrega.
    """
    orden_id = _finalizada(cliente, BATERIA, PANTALLA)
    orden = ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    assert _situaciones(orden) == {
        "DET-001": "AUTORIZADO_FACTIBLE",
        "DET-002": "PENDIENTE_AUTORIZACION",
    }
    tomada(cliente, orden_id)
    orden = ejecutar(cliente, orden_id, "DET-001")
    assert orden["current_process"] == "PROC-REP-129"
    assert "APROBAR_CONTROL" not in codigos(orden)

    orden = ok(decidir(cliente, orden_id, {"DET-002": "AUTORIZADO"}))
    assert orden["estado_workflow"] == "EN_COLA"
    tomar(cliente, orden_id)
    orden = ejecutar(cliente, orden_id, "DET-002", tipo=PANTALLA)
    assert orden["historial"][-1]["observacion"] == "COMPLETA"
    ok(aprobar(cliente, orden_id, "DET-001"))
    ok(aprobar(cliente, orden_id, "DET-002"))
    entregada = notificar_pagar_entregar(cliente, orden_id)

    assert entregada["estado_workflow"] == "ENTREGADA"
    assert Decimal(entregada["resumen"]["total"]) == Decimal("130000")
    assert stock(tmp_path, INSUMO_BATERIA) == Decimal("4")
    assert stock(tmp_path, INSUMO_PANTALLA) == Decimal("4")
