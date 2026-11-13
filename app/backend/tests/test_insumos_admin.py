"""Insumos administrados (DEC-MI-13): en la persistencia JSON (demo) se
consultan y no se editan; la edicion se prueba sobre PostgreSQL."""

import pytest

from tests.fixtures import api_salidas as f


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def test_insumos_de_solo_lectura_en_json(cliente):
    datos = f.ok(cliente.get("/api/admin/supplies"))
    assert datos["editable"] is False
    assert {i["id"] for i in datos["insumos"]} >= {
        f.INSUMO_BATERIA,
        f.INSUMO_PANTALLA,
    }
    assert "PostgreSQL" in f.conflicto(
        cliente.post(
            "/api/admin/supplies",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "clave": "INS-900",
                "codigo": "X",
                "nombre": "X",
            },
        )
    )
