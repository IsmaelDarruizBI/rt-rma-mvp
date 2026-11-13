"""Comunicaciones asistidas por WhatsApp y consentimiento (DEC-MI-08).

- Cinco plantillas iniciales, operativas, con variables de la Orden.
- Preparar solo lee; el usuario puede editar el mensaje antes de abrir
  WhatsApp. Se registra el intento (no un envio) y despues la confirmacion
  manual, una sola vez. Nunca «entregado» ni «leido».
- El consentimiento es un historial: la preferencia del cliente se respeta.
"""

import json

import pytest

from tests.fixtures import api_salidas as f


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _intento(cliente, orden_id, usuario=f.RECEPCION, **cuerpo):
    return cliente.post(
        f"/api/orders/{orden_id}/messages",
        json={"usuario_id": usuario, **cuerpo},
    )


def test_plantillas_iniciales_y_mensaje_preparado(cliente):
    datos = f.ok(cliente.get("/api/communications/templates"))
    assert datos["editable"] is False
    assert [p["codigo"] for p in datos["plantillas"]] == [
        "INGRESO",
        "AUTORIZACION_PENDIENTE",
        "LISTO_PARA_RETIRAR",
        "RECORDATORIO_RETIRO",
        "GARANTIA",
    ]
    assert {p["finalidad"] for p in datos["plantillas"]} == {"OPERATIVA"}
    assert "garantia_hasta" in datos["variables"]

    orden_id = f.definida(cliente, f.BATERIA)
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    preparado = f.ok(
        cliente.get(
            f"/api/orders/{orden_id}/messages/prepare?plantilla=INGRESO"
        )
    )
    assert orden_id in preparado["mensaje"]
    assert orden["cliente"]["nombre_apellido"] in preparado["mensaje"]
    assert "{" not in preparado["mensaje"]
    assert preparado["faltantes"] == []
    assert preparado["impedimento"] is None
    assert preparado["destinatario"] == orden["cliente"]["telefono"]

    # Sin entrega todavia no hay vencimiento: queda para completar.
    garantia = f.ok(
        cliente.get(
            f"/api/orders/{orden_id}/messages/prepare?plantilla=GARANTIA"
        )
    )
    assert garantia["faltantes"] == ["garantia_hasta"]
    assert "{garantia_hasta}" in garantia["mensaje"]
    # Preparar no modifica la Orden.
    assert f.ok(cliente.get(f"/api/orders/{orden_id}"))["comunicaciones"] == []


def test_intento_y_confirmacion_manual(cliente):
    orden_id = f.definida(cliente, f.BATERIA)
    f.conflicto(_intento(cliente, orden_id, usuario=f.TECNICO, mensaje="Hola"))
    orden = f.ok(
        _intento(
            cliente,
            orden_id,
            plantilla_codigo="INGRESO",
            mensaje="Hola! Mensaje editado por Recepcion.",
            destinatario="3415550000",
        )
    )
    (comunicacion,) = orden["comunicaciones"]
    assert comunicacion["id"] == "COM-001"
    assert comunicacion["mensaje"] == "Hola! Mensaje editado por Recepcion."
    assert comunicacion["plantilla_codigo"] == "INGRESO"
    assert comunicacion["finalidad"] == "OPERATIVA"
    assert comunicacion["canal"] == "WHATSAPP"
    assert comunicacion["usuario_id"] == f.RECEPCION
    assert comunicacion["confirmacion"] is None

    ruta = f"/api/orders/{orden_id}/messages/COM-001/confirm"
    orden = f.ok(
        cliente.post(ruta, json={"usuario_id": f.RECEPCION, "enviado": True})
    )
    confirmacion = orden["comunicaciones"][0]["confirmacion"]
    assert (confirmacion["enviado"], confirmacion["usuario_id"]) == (
        True,
        f.RECEPCION,
    )
    assert "ya se confirmo" in f.conflicto(
        cliente.post(ruta, json={"usuario_id": f.RECEPCION, "enviado": False})
    )
    texto = json.dumps(orden).upper()
    assert "ENTREGADO" not in texto.replace("FECHA_ENTREGA", "")
    assert "LEIDO" not in texto


def test_la_preferencia_del_cliente_se_respeta(cliente):
    orden_id = f.definida(cliente, f.BATERIA)
    cliente_id = f.ok(cliente.get(f"/api/orders/{orden_id}"))["cliente"]["id"]
    ruta = f"/api/clients/{cliente_id}/consents"
    assert f.ok(cliente.get(ruta))["vigentes"] == {
        "OPERATIVA": None,
        "COMERCIAL": None,
    }
    assert "origen" in f.conflicto(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.RECEPCION,
                "finalidad": "OPERATIVA",
                "otorgado": False,
                "origen": "   ",
            },
        )
    )
    f.conflicto(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.TECNICO,
                "finalidad": "COMERCIAL",
                "otorgado": True,
                "origen": "Mostrador",
            },
        )
    )
    estado = f.ok(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.RECEPCION,
                "finalidad": "OPERATIVA",
                "otorgado": False,
                "origen": "Lo pidio por telefono",
            },
        )
    )
    assert estado["vigentes"]["OPERATIVA"] is False
    preparado = f.ok(
        cliente.get(
            f"/api/orders/{orden_id}/messages/prepare?plantilla=INGRESO"
        )
    )
    assert "preferencia" in preparado["impedimento"]
    assert "preferencia" in f.conflicto(
        _intento(cliente, orden_id, plantilla_codigo="INGRESO", mensaje="x")
    )

    estado = f.ok(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.RECEPCION,
                "finalidad": "OPERATIVA",
                "otorgado": True,
                "origen": "Volvio a autorizar en el mostrador",
            },
        )
    )
    assert estado["vigentes"]["OPERATIVA"] is True
    assert [r["otorgado"] for r in estado["historial"]] == [True, False]
    f.ok(_intento(cliente, orden_id, plantilla_codigo="INGRESO", mensaje="x"))
