"""Firma opcional de los documentos emitidos (DEC-MI-06).

Ningun documento la exige: la entrega se completa sin firma. Si se firma,
la evidencia (en pantalla o foto del papel) queda ligada al documento,
tambien con la Orden ya entregada, sin modificarla.
"""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.storage import AlmacenFotosMemoria
from tests.fixtures.api_salidas import (
    BATERIA,
    RECEPCION,
    TECNICO,
    conflicto,
    notificar_pagar_entregar,
    ok,
    sembrar,
)
from tests.fixtures.ingreso_inicial import ingresada
from tests.test_garantia_checkin import _lista

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


@pytest.fixture
def cliente(tmp_path):
    sembrar(tmp_path, "10")
    app = create_app(Settings(data_dir=tmp_path))
    almacen = AlmacenFotosMemoria()
    app.state.contexto = replace(app.state.contexto, fotos=almacen)
    with TestClient(app) as test_client:
        test_client.almacen = almacen
        yield test_client


def _firmar(cliente, orden_id, documento_id, **params):
    return cliente.post(
        f"/api/orders/{orden_id}/documents/{documento_id}/signatures",
        params={"usuario_id": RECEPCION, "forma": "PANTALLA", **params},
        content=PNG,
        headers={"Content-Type": "image/png"},
    )


def test_la_firma_es_opcional_y_queda_ligada_al_documento(cliente):
    orden_id = ingresada(cliente, BATERIA)
    _lista(cliente, orden_id, BATERIA)
    # La entrega no exige firma.
    entregada = notificar_pagar_entregar(cliente, orden_id)
    assert entregada["estado_workflow"] == "ENTREGADA"
    documento = next(
        d
        for d in entregada["documentos_emitidos"]
        if d["tipo"] == "COMPROBANTE_ENTREGA"
    )
    assert ok(cliente.get(f"/api/orders/{orden_id}/signatures")) == []

    conflicto(_firmar(cliente, orden_id, documento["id"], usuario_id=TECNICO))
    respuesta = _firmar(cliente, orden_id, "DOC-NO")
    assert respuesta.status_code == 404
    (firma,) = ok(
        _firmar(cliente, orden_id, documento["id"], firmante="Ana Perez")
    )
    assert (firma["documento_id"], firma["forma"], firma["firmante"]) == (
        documento["id"],
        "PANTALLA",
        "Ana Perez",
    )
    assert firma["objeto"].startswith(f"firmas/{orden_id}/")
    imagen = cliente.get(f"/api/orders/{orden_id}/signatures/{firma['id']}")
    assert imagen.status_code == 200 and imagen.content == PNG
    # La Orden cerrada no cambio.
    assert (
        ok(cliente.get(f"/api/orders/{orden_id}"))["updated_at"]
        == (entregada["updated_at"])
    )

    foto = ok(
        _firmar(cliente, orden_id, documento["id"], forma="FOTO_DOCUMENTO")
    )
    assert [f["forma"] for f in foto] == ["PANTALLA", "FOTO_DOCUMENTO"]


def test_sin_imagen_valida_no_hay_firma(cliente):
    orden_id = ingresada(cliente, BATERIA)
    documento = ok(cliente.get(f"/api/orders/{orden_id}"))[
        "documentos_emitidos"
    ][0]
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/documents/{documento['id']}/signatures",
        params={"usuario_id": RECEPCION, "forma": "PANTALLA"},
        content=b"no es una imagen",
    )
    assert "imagen" in conflicto(respuesta)
    assert ok(cliente.get(f"/api/orders/{orden_id}/signatures")) == []
