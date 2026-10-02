"""HP-REP-003 (garantia RMA) recorrido de punta a punta por HTTP.

    HTTP -> router -> application -> services -> repositories -> JSON

Parte de una Orden CLIENTE_EXTERNO ENTREGADA (HP-REP-001 por la API) e
inicia la garantia RMA eligiendo 1..N de sus Detalles. La revision
tecnica es obligatoria (BR-REP-019): la Orden nueva nace EN_REVISION y
sus Detalles se definen despues de PROC-REP-065.
"""

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import TipoReparacion
from app.main import create_app
from app.storage.json.base import escribir_json_atomico
from tests import test_multidetalle as multi
from tests.fixtures.api_definicion import (
    definir_desde_revision_y_finalizar,
    definir_y_finalizar,
    finalizar_definicion,
)
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
    respuesta = definir_y_finalizar(
        cliente,
        orden_id,
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


def _iniciar_garantia(
    cliente, origen_id, detalle_origen_ids=("DET-001",), usuario=RECEPCION
):
    """``POST /{origen}/warranty-rma``: una Orden nueva, EN_REVISION."""
    return cliente.post(
        f"/api/orders/{origen_id}/warranty-rma",
        json={
            "usuario_id": usuario,
            "detalle_origen_ids": list(detalle_origen_ids),
        },
    )


def _revisar(cliente, orden_id, resultado="Falla cubierta por garantia."):
    return cliente.post(
        f"/api/orders/{orden_id}/technical-review",
        json={"usuario_id": TECNICO, "resultado": resultado},
    )


def _garantia_definida(cliente, origen_id, tipo=TIPO):
    """Garantia de DET-001 por el unico camino canonico, ya definida.

    035 -> 040 -> 045 No -> 055 -> 050 -> 060 -> 065 -> 068 Si -> 075 ->
    080 -> 090 -> 140 | 100. Devuelve la respuesta de finalizar.
    """
    garantia = _iniciar_garantia(cliente, origen_id)
    assert garantia.status_code == 201, garantia.text
    orden_id = garantia.json()["id"]
    assert _revisar(cliente, orden_id).status_code == 200
    return definir_desde_revision_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": tipo},
    )


def _ids(orden: dict) -> list[str]:
    return [p["referencia_id"] for p in orden["historial"]]


def _codigos(orden: dict) -> list[str]:
    return [a["codigo"] for a in orden["acciones_disponibles"]]


def test_hp_rep_003_end_to_end_por_http(cliente):
    origen = _orden_entregada(cliente)
    origen_id = origen["id"]

    # El backend publica UNA capacidad a nivel Orden (no una por Detalle):
    # la eleccion de Detalles es del formulario.
    (accion,) = origen["acciones_disponibles"]
    assert accion["codigo"] == "INICIAR_GARANTIA_RMA"
    assert accion["detalle_id"] is None
    assert accion["roles"] == ["RECEPCION"]

    foto_origen = cliente.get(f"/api/orders/{origen_id}").json()

    # PROC-REP-035 -> 040 -> 045 (No) -> 055 -> 050 -> 060, y se detiene.
    respuesta = _iniciar_garantia(cliente, origen_id, ["DET-001"])
    assert respuesta.status_code == 201, respuesta.text
    orden = respuesta.json()
    orden_id = orden["id"]

    assert orden_id != origen_id
    assert orden["origen"] == "RMA_GARANTIA_REPARACION"
    assert orden["orden_origen_id"] == origen_id
    assert orden["detalles_origen_ids"] == ["DET-001"]
    assert orden["detalles_origen"] == [
        {"id": "DET-001", "tipo_reparacion_nombre": "Cambio bateria iPhone 14"}
    ]
    assert orden["cliente"] == origen["cliente"]
    assert orden["estado_workflow"] == "EN_REVISION"
    assert orden["reparaciones_detail"] == []
    assert orden["resumen"]["condicion_comercial"] == "NO_COBRABLE"
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is True
    assert _ids(orden) == [
        "PROC-REP-035",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-055",
        "PROC-REP-050",
        "PROC-REP-060",
    ]
    assert orden["historial"][2]["observacion"] == "No"
    assert _codigos(orden) == ["REALIZAR_REVISION"]

    # PROC-REP-065 (Tecnico): revision obligatoria.
    orden = _revisar(cliente, orden_id).json()
    assert _codigos(orden) == [
        "AGREGAR_DETALLE_DESDE_REVISION",
        "FINALIZAR_SIN_REPARACION",
    ]

    # 068 Si -> 075: el Detalle nuevo queda vinculado al unico origen.
    orden = cliente.post(
        f"/api/orders/{orden_id}/review/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    ).json()
    (detalle,) = orden["reparaciones_detail"]
    assert detalle["detalle_origen_id"] == "DET-001"
    assert _ids(orden)[-2:] == ["PROC-REP-068", "PROC-REP-075"]
    # NO_COBRABLE: sin REGISTRAR_PAGO aunque haya precio snapshot.
    assert _codigos(orden) == [
        "AGREGAR_DETALLE_DESDE_REVISION",
        "FINALIZAR_DEFINICION",
    ]

    # Finalizar: 080 -> 090 -> 140, sin repetir el comprobante.
    orden = finalizar_definicion(cliente, orden_id, RECEPCION).json()
    assert orden["estado_workflow"] == "HABILITADA"
    assert _ids(orden)[-3:] == ["PROC-REP-080", "PROC-REP-090", "PROC-REP-140"]
    assert _ids(orden).count("PROC-REP-060") == 1
    assert "PROC-REP-070" not in _ids(orden)

    # Circuito tecnico normal, sin versiones *_garantia.
    orden = _circuito_tecnico(cliente, orden_id)
    assert orden["estado_workflow"] == "REPARACION_LISTA"

    # No hay pagos: ni accion ni endpoint.
    assert "REGISTRAR_PAGO" not in _codigos(orden)
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
    assert "PROC-REP-266" not in _ids(orden)

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
    assert set(_ids(orden)).isdisjoint(
        {"PROC-REP-010", "PROC-REP-030", "PROC-REP-266", "PROC-REP-290"}
    )
    # La ruta de referencia de HP-REP-003 incluye la revision y se
    # completa entera, sin nodos duplicados.
    ruta = [p["process_id"] for p in orden["progreso"]]
    assert len(ruta) == len(set(ruta))
    assert ruta[3:9] == [
        "PROC-REP-055",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-065",
        "PROC-REP-068",
        "PROC-REP-075",
    ]
    assert all(p["alcanzado"] for p in orden["progreso"])

    # La Orden origen no cambio en nada.
    assert cliente.get(f"/api/orders/{origen_id}").json() == foto_origen

    # El listado distingue la garantia y su origen.
    filas = {f["id"]: f for f in cliente.get("/api/orders").json()}
    assert filas[orden_id]["origen"] == "RMA_GARANTIA_REPARACION"
    assert filas[orden_id]["orden_origen_id"] == origen_id
    assert filas[origen_id]["orden_origen_id"] is None


def test_no_existe_el_bypass_de_garantia_directa(cliente):
    """La revision es obligatoria: no hay camino que copie el Tipo origen.

    Los endpoints por Detalle (directo y "para revision") ya no existen,
    y la definicion normal (045 Si -> 070) no aplica a una garantia.
    """
    origen = _orden_entregada(cliente)
    for ruta in (
        f"/api/orders/{origen['id']}/details/DET-001/warranty-rma",
        f"/api/orders/{origen['id']}/details/DET-001/warranty-rma/review",
    ):
        respuesta = cliente.post(ruta, json={"usuario_id": RECEPCION})
        assert respuesta.status_code in (404, 405), respuesta.text
    assert len(cliente.get("/api/orders").json()) == 1

    orden_id = _iniciar_garantia(cliente, origen["id"]).json()["id"]
    _revisar(cliente, orden_id)
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    assert respuesta.status_code == 409, respuesta.text
    assert "PROC-REP-070" not in _ids(
        cliente.get(f"/api/orders/{orden_id}").json()
    )


def test_garantia_rechaza_usuario_que_no_es_recepcion(cliente):
    origen = _orden_entregada(cliente)
    for usuario in (TECNICO, COORDINADOR, ADMINISTRADOR):
        respuesta = _iniciar_garantia(cliente, origen["id"], usuario=usuario)
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
    definir_y_finalizar(
        cliente,
        orden["id"],
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    foto = cliente.get(f"/api/orders/{orden['id']}").json()
    respuesta = _iniciar_garantia(cliente, orden["id"])
    assert respuesta.status_code == 409, respuesta.text
    assert len(cliente.get("/api/orders").json()) == 1
    assert cliente.get(f"/api/orders/{orden['id']}").json() == foto


def test_garantia_rechaza_orden_o_detalle_inexistente(cliente):
    respuesta = _iniciar_garantia(cliente, "OR-999999")
    assert respuesta.status_code == 404, respuesta.text

    origen = _orden_entregada(cliente)
    respuesta = _iniciar_garantia(cliente, origen["id"], ["DET-999"])
    assert respuesta.status_code == 404, respuesta.text
    respuesta = _iniciar_garantia(cliente, origen["id"], ["DET-001", "DET-9"])
    assert respuesta.status_code == 404, respuesta.text
    assert len(cliente.get("/api/orders").json()) == 1


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"usuario_id": RECEPCION},
        {"usuario_id": RECEPCION, "detalle_origen_ids": []},
        {"usuario_id": RECEPCION, "detalle_origen_ids": "DET-001"},
        {"detalle_origen_ids": ["DET-001"]},
    ],
)
def test_garantia_request_mal_formado_devuelve_422(cliente, cuerpo):
    origen = _orden_entregada(cliente)
    respuesta = cliente.post(
        f"/api/orders/{origen['id']}/warranty-rma", json=cuerpo
    )
    assert respuesta.status_code == 422, respuesta.text
    assert len(cliente.get("/api/orders").json()) == 1


def test_garantia_rechaza_detalles_origen_repetidos(cliente):
    origen = _orden_entregada(cliente)
    respuesta = _iniciar_garantia(cliente, origen["id"], ["DET-001"] * 2)
    assert respuesta.status_code == 409, respuesta.text
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
    garantia = _garantia_definida(cliente, origen["id"]).json()
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
    definir_y_finalizar(
        cliente,
        orden_id,
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
    definir_y_finalizar(
        cliente,
        orden["id"],
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


# --- Garantia de 1..N Detalles origen ----------------------------------


@pytest.fixture
def cliente_multi(tmp_path):
    multi._sembrar_catalogos(tmp_path)
    insumos = tmp_path / "catalogs" / "insumos.json"
    datos = json.loads(insumos.read_text(encoding="utf-8"))
    for insumo in datos:
        insumo["stock_fisico"] = "5"
    escribir_json_atomico(insumos, datos)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def _entregada_con_dos_detalles(cliente: TestClient) -> dict:
    """HP-REP-001 con DET-001 (bateria) y DET-002 (pantalla), entregada."""
    orden_id = multi._crear_orden(cliente)
    for tipo in (multi.TIPO_BATERIA, multi.TIPO_PANTALLA):
        cliente.post(
            f"/api/orders/{orden_id}/details",
            json={"usuario_id": multi.RECEPCION, "tipo_reparacion_id": tipo},
        )
    finalizar_definicion(cliente, orden_id, multi.RECEPCION)
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": multi.COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": multi.TECNICO, "estacion_id": multi.ESTACION},
    )
    for detalle_id, insumo_id in (
        ("DET-001", multi.INSUMO_BATERIA),
        ("DET-002", multi.INSUMO_PANTALLA),
    ):
        ejecucion_id = cliente.post(
            f"/api/orders/{orden_id}/details/{detalle_id}/start",
            json={"usuario_id": multi.TECNICO},
        ).json()["ejecuciones"][-1]["id"]
        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
            json={
                "usuario_id": multi.TECNICO,
                "insumos_utilizados": [
                    {"insumo_id": insumo_id, "cantidad": "1"}
                ],
            },
        )
    cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={"usuario_id": multi.RECEPCION},
    )
    cliente.post(
        f"/api/orders/{orden_id}/notify",
        json={"usuario_id": multi.RECEPCION},
    )
    cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": multi.RECEPCION,
            "monto": "130000",
            "metodo": "EFECTIVO",
        },
    )
    orden = cliente.post(
        f"/api/orders/{orden_id}/deliver",
        json={"usuario_id": multi.ADMINISTRADOR},
    ).json()
    assert orden["estado_workflow"] == "ENTREGADA", orden
    return orden


def _agregar_desde_revision(cliente, orden_id, tipo, detalle_origen_id=None):
    cuerpo = {"usuario_id": multi.RECEPCION, "tipo_reparacion_id": tipo}
    if detalle_origen_id is not None:
        cuerpo["detalle_origen_id"] = detalle_origen_id
    return cliente.post(f"/api/orders/{orden_id}/review/details", json=cuerpo)


def test_garantia_de_varios_detalles_crea_una_unica_orden(cliente_multi):
    cliente = cliente_multi
    origen = _entregada_con_dos_detalles(cliente)
    foto_origen = cliente.get(f"/api/orders/{origen['id']}").json()
    assert _codigos(origen) == ["INICIAR_GARANTIA_RMA"]

    respuesta = _iniciar_garantia(
        cliente, origen["id"], ["DET-002", "DET-001"]
    )
    assert respuesta.status_code == 201, respuesta.text
    orden = respuesta.json()
    orden_id = orden["id"]

    # UNA sola Orden nueva para los N Detalles origen.
    assert len(cliente.get("/api/orders").json()) == 2
    assert orden["detalles_origen_ids"] == ["DET-002", "DET-001"]
    assert orden["detalles_origen"] == [
        {
            "id": "DET-002",
            "tipo_reparacion_nombre": "Cambio de pantalla iPhone 14",
        },
        {
            "id": "DET-001",
            "tipo_reparacion_nombre": "Cambio de bateria iPhone 14",
        },
    ]
    assert orden["estado_workflow"] == "EN_REVISION"
    assert orden["reparaciones_detail"] == []
    assert "DET-002,DET-001" in orden["historial"][0]["observacion"]

    _revisar(cliente, orden_id)

    # Con N origenes hay que elegir a cual corresponde el Detalle nuevo,
    # y solo entre los seleccionados. Un rechazo no deja rastros.
    antes = cliente.get(f"/api/orders/{orden_id}").json()
    respuesta = _agregar_desde_revision(cliente, orden_id, multi.TIPO_BATERIA)
    assert respuesta.status_code == 409, respuesta.text
    respuesta = _agregar_desde_revision(
        cliente, orden_id, multi.TIPO_BATERIA, "DET-003"
    )
    assert respuesta.status_code == 409, respuesta.text
    assert cliente.get(f"/api/orders/{orden_id}").json() == antes

    # Sin relacion 1:1: DET-001 origina dos Detalles y DET-002 ninguno.
    for tipo in (multi.TIPO_BATERIA, multi.TIPO_PANTALLA):
        respuesta = _agregar_desde_revision(cliente, orden_id, tipo, "DET-001")
        assert respuesta.status_code == 200, respuesta.text

    orden = finalizar_definicion(cliente, orden_id, multi.RECEPCION).json()
    assert orden["estado_workflow"] == "HABILITADA"
    assert [
        (d["id"], d["tipo_reparacion_id"], d["detalle_origen_id"])
        for d in orden["reparaciones_detail"]
    ] == [
        ("DET-001", multi.TIPO_BATERIA, "DET-001"),
        ("DET-002", multi.TIPO_PANTALLA, "DET-001"),
    ]
    assert orden["detalles_origen_ids"] == ["DET-002", "DET-001"]
    assert cliente.get(f"/api/orders/{origen['id']}").json() == foto_origen


def test_garantia_de_un_subconjunto_vincula_al_unico_origen(cliente_multi):
    cliente = cliente_multi
    origen = _entregada_con_dos_detalles(cliente)

    orden_id = _iniciar_garantia(cliente, origen["id"], ["DET-002"]).json()[
        "id"
    ]
    _revisar(cliente, orden_id)
    orden = _agregar_desde_revision(
        cliente, orden_id, multi.TIPO_PANTALLA
    ).json()

    (detalle,) = orden["reparaciones_detail"]
    assert detalle["detalle_origen_id"] == "DET-002"
    assert orden["detalles_origen"] == [
        {
            "id": "DET-002",
            "tipo_reparacion_nombre": "Cambio de pantalla iPhone 14",
        }
    ]


def test_garantia_toma_el_snapshot_vigente_al_definir_luego_de_revision(
    cliente, tmp_path
):
    """El Detalle nuevo usa el Tipo vigente en 075, no el del origen."""
    origen = _orden_entregada(cliente)
    foto_origen = cliente.get(f"/api/orders/{origen['id']}").json()
    orden_id = _iniciar_garantia(cliente, origen["id"]).json()["id"]

    escribir_json_atomico(
        tmp_path / "catalogs" / "tipos_reparacion.json",
        [
            TipoReparacion(
                id=TIPO,
                nombre="Cambio bateria iPhone 14",
                precio=Decimal("95000"),
                puntaje=12,
                garantia_dias=120,
            ).model_dump(mode="json")
        ],
    )

    _revisar(cliente, orden_id)
    orden = definir_desde_revision_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    ).json()

    assert orden["estado_workflow"] == "HABILITADA"
    (detalle,) = orden["reparaciones_detail"]
    assert Decimal(detalle["precio"]) == Decimal("95000")
    assert detalle["puntaje"] == 12
    assert detalle["garantia_dias"] == 120
    assert origen["reparaciones_detail"][0]["precio"] == "80000"
    assert cliente.get(f"/api/orders/{origen['id']}").json() == foto_origen
