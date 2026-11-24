"""Topes del Ajuste Comercial al aplicarlo (BR-REP-016, DEC-AJ-10).

Un ajuste de importe fijo nunca supera el importe al que se aplica:
- al aplicarlo directamente sobre un trabajo o sobre la Orden;
- tampoco indirectamente: un ajuste nuevo de un trabajo achica la base del
  ajuste de la Orden, y si el importe fijo vigente de la Orden la superaria,
  se rechaza sin cambiar nada (antes se recortaba en silencio).
"""

from decimal import Decimal

import pytest

from tests.fixtures import api_salidas as f


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path) as test_client:
        yield test_client


def _ajustar(cliente, orden_id, tipo, valor, *, detalle_id=None):
    return cliente.post(
        f"/api/orders/{orden_id}/discount",
        json={
            "usuario_id": f.RECEPCION,
            "tipo": tipo,
            "valor": valor,
            "motivo": "Acuerdo comercial.",
            "clase": "DESCUENTO",
            "detalle_id": detalle_id,
        },
    )


def _orden(cliente, orden_id):
    return f.ok(cliente.get(f"/api/orders/{orden_id}"))


def test_un_importe_fijo_mayor_al_precio_del_trabajo_se_rechaza(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    precio = Decimal(
        _orden(cliente, orden_id)["reparaciones_detail"][1]["precio"]
    )

    respuesta = _ajustar(
        cliente, orden_id, "IMPORTE", str(precio + 1), detalle_id="DET-002"
    )

    assert respuesta.status_code == 409
    assert "no puede superar" in respuesta.json()["error"]["mensaje"]
    assert _orden(cliente, orden_id)["descuentos"] == []


def test_un_importe_fijo_mayor_al_subtotal_se_rechaza(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    subtotal = Decimal(_orden(cliente, orden_id)["resumen"]["subtotal"])

    respuesta = _ajustar(cliente, orden_id, "IMPORTE", str(subtotal + 1))

    assert respuesta.status_code == 409
    assert _orden(cliente, orden_id)["descuentos"] == []


def test_un_importe_igual_al_precio_se_acepta(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    precio = _orden(cliente, orden_id)["reparaciones_detail"][1]["precio"]

    orden = f.ok(
        _ajustar(cliente, orden_id, "IMPORTE", precio, detalle_id="DET-002")
    )

    assert Decimal(orden["descuentos"][0]["precio_final"]) == 0


def test_el_ajuste_de_un_trabajo_no_deja_al_de_la_orden_por_encima(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    orden = _orden(cliente, orden_id)
    subtotal = Decimal(orden["resumen"]["subtotal"])
    precio_1 = Decimal(orden["reparaciones_detail"][0]["precio"])
    # Ajuste de la Orden casi por todo el subtotal.
    f.ok(_ajustar(cliente, orden_id, "IMPORTE", str(subtotal - 1000)))

    # Un ajuste del trabajo 1 dejaria la base de la Orden por debajo de su
    # importe fijo vigente.
    respuesta = _ajustar(
        cliente,
        orden_id,
        "IMPORTE",
        str(precio_1 - 1),
        detalle_id="DET-001",
    )

    assert respuesta.status_code == 409
    assert "superaria" in respuesta.json()["error"]["mensaje"]
    despues = _orden(cliente, orden_id)
    assert len(despues["descuentos"]) == 1
    assert Decimal(despues["resumen"]["total"]) == 1000


def test_el_ajuste_de_un_trabajo_dentro_del_tope_se_acepta(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    orden = _orden(cliente, orden_id)
    subtotal = Decimal(orden["resumen"]["subtotal"])
    f.ok(_ajustar(cliente, orden_id, "IMPORTE", "1000"))

    orden = f.ok(
        _ajustar(cliente, orden_id, "IMPORTE", "500", detalle_id="DET-001")
    )

    assert Decimal(orden["resumen"]["total"]) == subtotal - 1500
