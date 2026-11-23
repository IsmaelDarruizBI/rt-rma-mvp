"""Progreso de la Orden con el aviso opcional (DEC-AJ-03, pendiente del
bloque 2 resuelto en el bloque 4).

Avisar al cliente (PROC-REP-260) dejo de ser obligatorio para entregar. El
«Recorrido tecnico del proceso» lo sigue listando (el grafo no cambia),
marcado como opcional; si la Orden se entrego sin aviso, figura omitido,
no pendiente. ``alcanzado`` conserva su significado.
"""

import pytest

from tests.fixtures import api_salidas as f
from tests.fixtures import iteracion1 as it
from tests.fixtures.custodia import checkin_si_falta


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _reparada(cliente) -> str:
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    checkin_si_falta(cliente, orden_id)
    return orden_id


def _entregar(cliente, orden_id) -> dict:
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": f.RECEPCION},
        )
    )


def _paso(orden: dict, process_id: str) -> dict:
    (paso,) = [p for p in orden["progreso"] if p["process_id"] == process_id]
    return paso


def test_progreso_la_entrega_sin_aviso_omite_el_paso_260(cliente):
    orden_id = _reparada(cliente)
    it.pagar(cliente, orden_id, "80000")
    lista = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert _paso(lista, "PROC-REP-260") == {
        "process_id": "PROC-REP-260",
        "etiqueta": "Notificar cliente",
        "alcanzado": False,
        "opcional": True,
        "omitido": False,
    }

    entregada = _entregar(cliente, orden_id)

    aviso = _paso(entregada, "PROC-REP-260")
    assert (aviso["alcanzado"], aviso["opcional"], aviso["omitido"]) == (
        False,
        True,
        True,
    )
    assert _paso(entregada, "PROC-REP-270")["alcanzado"] is True
    # Ningun otro paso es opcional ni queda omitido.
    assert [
        p["process_id"] for p in entregada["progreso"] if p["opcional"]
    ] == ["PROC-REP-260"]


def test_progreso_con_aviso_el_paso_260_queda_alcanzado(cliente):
    orden_id = _reparada(cliente)
    orden = f.notificar_pagar_entregar(cliente, orden_id)
    aviso = _paso(orden, "PROC-REP-260")
    assert (aviso["alcanzado"], aviso["omitido"]) == (True, False)


def test_progreso_sin_reparacion_entregada_sin_aviso(cliente):
    from tests.fixtures.custodia import enviar_a_revision

    orden_id = f.crear(cliente)
    f.ok(enviar_a_revision(cliente, orden_id))
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Sin falla."},
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/review/without-repair",
            json={"usuario_id": f.RECEPCION, "motivo": "No corresponde."},
        )
    )
    entregada = _entregar(cliente, orden_id)
    aviso = _paso(entregada, "PROC-REP-260")
    assert (aviso["alcanzado"], aviso["opcional"], aviso["omitido"]) == (
        False,
        True,
        True,
    )
