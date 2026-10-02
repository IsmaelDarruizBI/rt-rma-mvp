"""Agregar un Detalle y finalizar la definicion: dos intenciones por HTTP.

    POST /api/orders/{id}/details              agrega UN Detalle (070)
    POST /api/orders/{id}/review/details       agrega UN Detalle (075)
    POST /api/orders/{id}/definition/finalize  [050 -> 060] -> 080 -> 090
                                               -> 140 | 100

Agregar nunca genera el comprobante, valida factibilidad ni habilita.
Finalizar exige ACT-RECEP y al menos un Detalle, y en el camino de
revision no regenera el comprobante. ``acciones_disponibles`` publica
cual de las dos corresponde: la UI no deduce reglas del proceso.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.fixtures.api_definicion import finalizar_definicion
from tests.test_api_hp_rep_002 import (
    ADMINISTRADOR,
    COORDINADOR,
    RECEPCION,
    TECNICO,
    TIPO,
    _sembrar_catalogos,
)
from tests.test_api_var_rep_001_002 import _crear_orden as _crear_orden_cliente


@pytest.fixture
def cliente(tmp_path):
    _sembrar_catalogos(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def _ids(orden: dict) -> list[str]:
    return [p["referencia_id"] for p in orden["historial"]]


def _codigos(orden: dict) -> list[str]:
    return [a["codigo"] for a in orden["acciones_disponibles"]]


def _agregar(cliente, orden_id, ruta="details", usuario=RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/{ruta}",
        json={"usuario_id": usuario, "tipo_reparacion_id": TIPO},
    )


def test_agregar_no_finaliza_y_finalizar_cierra_la_definicion(cliente):
    orden_id = _crear_orden_cliente(cliente)
    assert _codigos(cliente.get(f"/api/orders/{orden_id}").json()) == [
        "AGREGAR_DETALLE",
        "ENVIAR_A_REVISION",
    ]

    for numero in (1, 2):
        respuesta = _agregar(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert len(orden["reparaciones_detail"]) == numero
        assert orden["estado_workflow"] == "REQUERIMIENTO"
        assert (
            orden["documentos"]["comprobante_recepcion"]["generado"] is False
        )
        assert not {"PROC-REP-050", "PROC-REP-080"} & set(_ids(orden))
        assert _codigos(orden)[:2] == [
            "AGREGAR_DETALLE",
            "FINALIZAR_DEFINICION",
        ]
        assert "ENVIAR_A_REVISION" not in _codigos(orden)
    assert _ids(orden).count("PROC-REP-045") == 1  # "Si", una sola vez
    assert _ids(orden).count("PROC-REP-070") == 2

    respuesta = finalizar_definicion(cliente, orden_id, RECEPCION)
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    assert _ids(orden)[-5:] == [
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]
    assert orden["estado_workflow"] == "HABILITADA"
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is True
    assert "AGREGAR_DETALLE" not in _codigos(orden)
    assert "FINALIZAR_DEFINICION" not in _codigos(orden)

    # Cerrada la definicion, no se agrega ni se vuelve a finalizar.
    antes = cliente.get(f"/api/orders/{orden_id}").json()
    assert _agregar(cliente, orden_id).status_code == 409
    assert (
        finalizar_definicion(cliente, orden_id, RECEPCION).status_code == 409
    )
    assert cliente.get(f"/api/orders/{orden_id}").json() == antes


def test_finalizar_sin_detalles_es_un_conflicto_sin_efectos(cliente):
    orden_id = _crear_orden_cliente(cliente)
    antes = cliente.get(f"/api/orders/{orden_id}").json()

    respuesta = finalizar_definicion(cliente, orden_id, RECEPCION)

    assert respuesta.status_code == 409, respuesta.text
    assert cliente.get(f"/api/orders/{orden_id}").json() == antes


@pytest.mark.parametrize("usuario", [TECNICO, COORDINADOR, ADMINISTRADOR])
def test_finalizar_solo_recepcion(cliente, usuario):
    orden_id = _crear_orden_cliente(cliente)
    _agregar(cliente, orden_id)
    antes = cliente.get(f"/api/orders/{orden_id}").json()

    assert finalizar_definicion(cliente, orden_id, usuario).status_code == 409
    assert cliente.get(f"/api/orders/{orden_id}").json() == antes


def test_finalizar_valida_orden_y_request(cliente):
    assert finalizar_definicion(
        cliente, "OR-999999", RECEPCION
    ).status_code == (404)
    orden_id = _crear_orden_cliente(cliente)
    _agregar(cliente, orden_id)
    for cuerpo in ({}, {"usuario_id": ""}):
        respuesta = cliente.post(
            f"/api/orders/{orden_id}/definition/finalize", json=cuerpo
        )
        assert respuesta.status_code == 422, respuesta.text


def test_sin_stock_finalizar_deja_la_orden_en_100_sin_error(tmp_path):
    _sembrar_catalogos(tmp_path, stock="0")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as cliente:
        orden_id = _crear_orden_cliente(cliente)
        _agregar(cliente, orden_id)

        respuesta = finalizar_definicion(cliente, orden_id, RECEPCION)

        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert orden["current_process"] == "PROC-REP-100"
        assert "PROC-REP-140" not in _ids(orden)
        assert _codigos(orden)[:2] == ["ESPERAR_RECURSOS", "OVERRIDE_RECURSOS"]


def test_camino_de_revision_finaliza_sin_regenerar_el_comprobante(cliente):
    orden_id = _crear_orden_cliente(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/send-to-review",
        json={"usuario_id": RECEPCION},
    )
    # Antes de 065 no hay definicion que finalizar.
    assert (
        finalizar_definicion(cliente, orden_id, RECEPCION).status_code == 409
    )
    cliente.post(
        f"/api/orders/{orden_id}/technical-review",
        json={"usuario_id": TECNICO, "resultado": "Placa danada."},
    )

    for _ in range(2):
        orden = _agregar(cliente, orden_id, ruta="review/details").json()
        assert orden["estado_workflow"] == "EN_REVISION"
        assert _codigos(orden)[:2] == [
            "AGREGAR_DETALLE_DESDE_REVISION",
            "FINALIZAR_DEFINICION",
        ]
        assert "PROC-REP-080" not in _ids(orden)

    orden = finalizar_definicion(cliente, orden_id, RECEPCION).json()

    ids = _ids(orden)
    assert ids[-3:] == ["PROC-REP-080", "PROC-REP-090", "PROC-REP-140"]
    assert ids.count("PROC-REP-050") == ids.count("PROC-REP-060") == 1
    assert ids.count("PROC-REP-068") == 1
    assert ids.count("PROC-REP-075") == 2
    assert orden["estado_workflow"] == "HABILITADA"


def test_el_campo_finalizar_definicion_ya_no_existe(cliente):
    """Un cliente viejo que lo envia solo agrega: nunca finaliza."""
    orden_id = _crear_orden_cliente(cliente)

    orden = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={
            "usuario_id": RECEPCION,
            "tipo_reparacion_id": TIPO,
            "finalizar_definicion": True,
        },
    ).json()

    assert orden["estado_workflow"] == "REQUERIMIENTO"
    assert "PROC-REP-080" not in _ids(orden)
