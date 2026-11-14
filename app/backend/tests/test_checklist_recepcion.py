"""Advertencia por informacion faltante (BR-REP-025, DC12) en JSON.

Nunca bloquea: la Orden informa que falta y Recepcion puede continuar
igualmente, lo que queda registrado. El catalogo del checklist se
administra sobre PostgreSQL (tests/postgres/test_checklist_postgres.py).
"""

import pytest

from tests.fixtures import api_salidas as f


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def test_advertencia_no_bloquea_y_la_confirmacion_queda(cliente):
    orden_id = f.crear(cliente)
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert orden["informacion_faltante"] == [
        "Fotografias",
        "Observaciones del equipo",
        "Checklist de recepcion",
    ]
    # No bloquea: se puede seguir con los trabajos sin confirmar.
    f.agregar(cliente, orden_id)

    f.conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/missing-info-ack",
            json={"usuario_id": f.TECNICO},
        )
    )
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/missing-info-ack",
            json={"usuario_id": f.RECEPCION},
        )
    )
    assert orden["informacion_faltante"] == []
    assert f.ok(cliente.get("/api/catalogs/checklist")) == {
        "editable": False,
        "tipos": [],
        "preguntas": [],
    }
    assert (
        cliente.post(
            f"/api/orders/{orden_id}/checklist",
            json={"usuario_id": f.RECEPCION, "tipo_equipo_id": "TEQ-0001"},
        ).status_code
        == 404
    )
