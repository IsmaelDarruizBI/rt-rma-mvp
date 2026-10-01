"""HP-REP-003 (garantia RMA) recorrido de punta a punta por HTTP.

    HTTP -> router -> application -> services -> repositories -> JSON

Parte de una Orden CLIENTE_EXTERNO ENTREGADA (HP-REP-001 por la API) y
genera la garantia RMA de su unico Detalle.
"""

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.storage.json.base import escribir_json_atomico
from tests.test_api_hp_rep_002 import (
    ADMINISTRADOR,
    COORDINADOR,
    ESTACION,
    INSUMO,
    RECEPCION,
    TECNICO,
    TIPO,
    _sembrar_catalogos,
)


@pytest.fixture
def cliente(tmp_path):
    _sembrar_catalogos(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def _circuito_tecnico(cliente: TestClient, orden_id: str) -> dict:
    """Priorizar -> tomar -> ejecutar -> aprobar control (mismo circuito)."""
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    )
    detalle_id = cliente.get(f"/api/orders/{orden_id}").json()[
        "reparaciones_detail"
    ][0]["id"]
    ejecucion_id = cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": TECNICO},
    ).json()["ejecuciones"][0]["id"]
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={
            "usuario_id": TECNICO,
            "insumos_utilizados": [{"insumo_id": INSUMO, "cantidad": "1"}],
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={"usuario_id": RECEPCION},
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _orden_entregada(cliente: TestClient) -> dict:
    """HP-REP-001 completo por HTTP."""
    orden = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {
                "nombre": "Cliente de Prueba",
                "telefono": "341-0000000",
            },
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "La bateria dura poco.",
            },
        },
    ).json()
    orden_id = orden["id"]
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    assert respuesta.status_code == 200, respuesta.text
    _circuito_tecnico(cliente, orden_id)
    cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    )
    cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": RECEPCION,
            "monto": "80000",
            "metodo": "EFECTIVO",
        },
    )
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": ADMINISTRADOR}
    )
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    assert orden["estado_workflow"] == "ENTREGADA"
    return orden


def _generar_garantia(cliente, origen_id, detalle_id, usuario=RECEPCION):
    return cliente.post(
        f"/api/orders/{origen_id}/details/{detalle_id}/warranty-rma",
        json={"usuario_id": usuario},
    )


def test_hp_rep_003_end_to_end_por_http(cliente):
    origen = _orden_entregada(cliente)
    origen_id = origen["id"]
    detalle_origen_id = origen["reparaciones_detail"][0]["id"]

    # El backend publica la capacidad (no la deduce el frontend).
    (accion,) = origen["acciones_disponibles"]
    assert accion["codigo"] == "GENERAR_GARANTIA_RMA"
    assert accion["detalle_id"] == detalle_origen_id
    assert accion["roles"] == ["RECEPCION"]

    foto_origen = cliente.get(f"/api/orders/{origen_id}").json()

    # PROC-REP-035 -> 040 -> 045 -> 070 -> 050 -> 060 -> 080 -> 090 -> 140
    respuesta = _generar_garantia(cliente, origen_id, detalle_origen_id)
    assert respuesta.status_code == 201, respuesta.text
    orden = respuesta.json()
    orden_id = orden["id"]

    assert orden_id != origen_id
    assert orden["origen"] == "RMA_GARANTIA_REPARACION"
    assert orden["orden_origen_id"] == origen_id
    assert orden["cliente"] == origen["cliente"]
    assert orden["estado_workflow"] == "HABILITADA"
    assert orden["resumen"]["condicion_comercial"] == "NO_COBRABLE"
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is True
    (detalle,) = orden["reparaciones_detail"]
    assert detalle["detalle_origen_id"] == detalle_origen_id
    assert [p["referencia_id"] for p in orden["historial"]] == [
        "PROC-REP-035",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]

    # Circuito tecnico normal, sin versiones *_garantia.
    orden = _circuito_tecnico(cliente, orden_id)
    assert orden["estado_workflow"] == "REPARACION_LISTA"

    # No hay pagos: ni accion ni endpoint.
    assert "REGISTRAR_PAGO" not in {
        a["codigo"] for a in orden["acciones_disponibles"]
    }
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={"usuario_id": ADMINISTRADOR, "monto": "1", "metodo": "EFECTIVO"},
    )
    assert respuesta.status_code == 409, respuesta.text

    # PROC-REP-250 -> 260 -> 265 (NO_COBRABLE, sin 266).
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    )
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    assert orden["puede_entregar"] is True
    assert Decimal(orden["resumen"]["saldo"]) > 0  # nominal, no deuda
    paso_265 = orden["historial"][-1]
    assert paso_265["referencia_id"] == "PROC-REP-265"
    assert paso_265["observacion"] == "NO_COBRABLE_POR_ORIGEN"
    referencias_265 = [p["referencia_id"] for p in orden["historial"]]
    assert "PROC-REP-266" not in referencias_265

    # PROC-REP-280 -> 270 -> EVT-REP-999.
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": ADMINISTRADOR}
    )
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()

    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["current_process"] == "EVT-REP-999"
    assert orden["pagos"] == []
    assert orden["orden_origen_id"] is not None
    assert orden["reparaciones_detail"][0]["detalle_origen_id"] is not None
    assert orden["documentos"]["comprobante_final"]["generado"] is True
    referencias = {p["referencia_id"] for p in orden["historial"]}
    assert referencias.isdisjoint(
        {"PROC-REP-010", "PROC-REP-030", "PROC-REP-266", "PROC-REP-290"}
    )
    assert {p["process_id"] for p in orden["progreso"] if p["alcanzado"]} == {
        p["process_id"] for p in orden["progreso"]
    }

    # La Orden origen no cambio en nada.
    assert cliente.get(f"/api/orders/{origen_id}").json() == foto_origen

    # El listado distingue la garantia y su origen.
    filas = {f["id"]: f for f in cliente.get("/api/orders").json()}
    assert filas[orden_id]["origen"] == "RMA_GARANTIA_REPARACION"
    assert filas[orden_id]["orden_origen_id"] == origen_id
    assert filas[origen_id]["orden_origen_id"] is None


def test_garantia_rechaza_usuario_que_no_es_recepcion(cliente):
    origen = _orden_entregada(cliente)
    respuesta = _generar_garantia(
        cliente, origen["id"], "DET-001", usuario=TECNICO
    )
    assert respuesta.status_code == 409, respuesta.text
    assert len(cliente.get("/api/orders").json()) == 1


def test_garantia_rechaza_orden_no_entregada(cliente):
    orden = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "C", "telefono": "1"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "x",
            },
        },
    ).json()
    cliente.post(
        f"/api/orders/{orden['id']}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    respuesta = _generar_garantia(cliente, orden["id"], "DET-001")
    assert respuesta.status_code == 409, respuesta.text


def test_garantia_rechaza_orden_o_detalle_inexistente(cliente):
    respuesta = _generar_garantia(cliente, "OR-999999", "DET-001")
    assert respuesta.status_code == 404, respuesta.text

    origen = _orden_entregada(cliente)
    respuesta = _generar_garantia(cliente, origen["id"], "DET-999")
    assert respuesta.status_code == 404, respuesta.text
    assert len(cliente.get("/api/orders").json()) == 1


def test_orden_persistida_antes_de_slice3_sigue_cargando(cliente, tmp_path):
    origen = _orden_entregada(cliente)
    (ruta,) = tmp_path.rglob(f"{origen['id']}.json")

    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos.pop("orden_origen_id", None)
    for detalle in datos["reparaciones_detail"]:
        detalle.pop("detalle_origen_id", None)
    escribir_json_atomico(ruta, datos)

    recargada = cliente.get(f"/api/orders/{origen['id']}").json()
    assert recargada["orden_origen_id"] is None
    assert recargada["reparaciones_detail"][0]["detalle_origen_id"] is None


def _referencias(cliente: TestClient, orden_id: str) -> list[str]:
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    return [p["referencia_id"] for p in orden["historial"]]


def test_garantia_no_puede_entregarse_sin_notificar_ni_pasar_por_265(cliente):
    origen = _orden_entregada(cliente)
    garantia = _generar_garantia(cliente, origen["id"], "DET-001").json()
    orden_id = garantia["id"]
    orden = _circuito_tecnico(cliente, orden_id)
    assert orden["estado_workflow"] == "REPARACION_LISTA"

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": ADMINISTRADOR}
    )
    assert respuesta.status_code == 409, respuesta.text
    referencias = _referencias(cliente, orden_id)
    assert "PROC-REP-280" not in referencias
    assert "PROC-REP-270" not in referencias

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    )
    assert respuesta.status_code == 200, respuesta.text
    referencias = _referencias(cliente, orden_id)
    assert referencias[-2:] == ["PROC-REP-260", "PROC-REP-265"]

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": ADMINISTRADOR}
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado_workflow"] == "ENTREGADA"


def test_cliente_externo_pagado_por_adelantado_tampoco_saltea_265(cliente):
    orden = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "C", "telefono": "1"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "x",
            },
        },
    ).json()
    orden_id = orden["id"]
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    # Anticipo total antes de REPARACION_LISTA: el saldo ya es 0.
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": RECEPCION,
            "monto": "80000",
            "metodo": "EFECTIVO",
        },
    )
    assert Decimal(respuesta.json()["resumen"]["saldo"]) == 0
    orden = _circuito_tecnico(cliente, orden_id)
    assert orden["estado_workflow"] == "REPARACION_LISTA"

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": ADMINISTRADOR}
    )
    assert respuesta.status_code == 409, respuesta.text
    assert "PROC-REP-280" not in _referencias(cliente, orden_id)

    cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    )
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": ADMINISTRADOR}
    )
    assert respuesta.status_code == 200, respuesta.text


def _cliente_externo_lista(cliente: TestClient) -> str:
    orden = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "C", "telefono": "1"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "x",
            },
        },
    ).json()
    cliente.post(
        f"/api/orders/{orden['id']}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    _circuito_tecnico(cliente, orden["id"])
    return orden["id"]


def _pagar(cliente: TestClient, orden_id: str, monto: str) -> dict:
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={"usuario_id": RECEPCION, "monto": monto, "metodo": "EFECTIVO"},
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def test_pago_total_en_reparacion_lista_no_ejecuta_265(cliente):
    orden_id = _cliente_externo_lista(cliente)

    orden = _pagar(cliente, orden_id, "80000")

    assert orden["resumen"]["saldo"] == "0"
    assert orden["current_process"] == "PROC-REP-240"
    assert orden["puede_entregar"] is False
    referencias = [p["referencia_id"] for p in orden["historial"]]
    assert "PROC-REP-265" not in referencias
    assert "PROC-REP-266" not in referencias

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": ADMINISTRADOR}
    )
    assert respuesta.status_code == 409, respuesta.text

    orden = cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    ).json()
    referencias = [p["referencia_id"] for p in orden["historial"]]
    assert referencias[-3:] == ["PROC-REP-250", "PROC-REP-260", "PROC-REP-265"]
    assert orden["puede_entregar"] is True

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": ADMINISTRADOR}
    )
    assert respuesta.status_code == 200, respuesta.text


def _hasta_266(cliente: TestClient) -> str:
    orden_id = _cliente_externo_lista(cliente)
    orden = cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    ).json()
    referencias = [p["referencia_id"] for p in orden["historial"]]
    assert referencias[-2:] == ["PROC-REP-265", "PROC-REP-266"]
    assert orden["puede_entregar"] is False
    return orden_id


def test_pago_parcial_en_completar_cobro_vuelve_a_265_no_y_266(cliente):
    orden_id = _hasta_266(cliente)

    orden = _pagar(cliente, orden_id, "30000")

    referencias = [p["referencia_id"] for p in orden["historial"]]
    assert referencias[-3:] == [
        "ACC-REP-020",
        "PROC-REP-265",
        "PROC-REP-266",
    ]
    assert orden["current_process"] == "PROC-REP-266"
    assert orden["puede_entregar"] is False
    assert orden["resumen"]["saldo"] == "50000"


def test_pago_final_en_completar_cobro_aprueba_265_y_permite_entregar(
    cliente,
):
    orden_id = _hasta_266(cliente)
    _pagar(cliente, orden_id, "30000")

    orden = _pagar(cliente, orden_id, "50000")

    referencias = [p["referencia_id"] for p in orden["historial"]]
    assert referencias[-2:] == ["ACC-REP-020", "PROC-REP-265"]
    assert referencias.count("PROC-REP-266") == 2
    assert orden["current_process"] == "PROC-REP-265"
    assert orden["puede_entregar"] is True
    assert Decimal(orden["resumen"]["saldo"]) <= 0

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": ADMINISTRADOR}
    )
    assert respuesta.status_code == 200, respuesta.text
