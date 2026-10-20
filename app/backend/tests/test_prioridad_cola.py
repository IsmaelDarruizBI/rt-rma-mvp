"""Prioridad 4 y entrada automatica a la cola (iteracion 1 del UAT).

Tras el comprobante de ingreso (y la factibilidad), la Orden entra sola a
la cola con prioridad 4 (Normal). Cambiar la prioridad es otra cosa:
tecnicos, Coordinacion o Recepcion, en cola o en reparacion, queda en el
historial con quien y cuando (ACC-REP-007), no vuelve a encolar y la cola
se reordena.
"""

import pytest

from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    COORDINADOR,
    RECEPCION,
    TECNICO,
    TECNICO_B,
    agregar,
    archivo,
    cliente_http,
    codigos,
    conflicto,
    ids,
    iniciar,
    ok,
    tomar,
)
from tests.fixtures.ingreso_inicial import complementarias, ingresada
from tests.test_api_hp_rep_002 import _crear_orden_rt


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path, stock="10") as test_client:
        yield test_client


def _cambiar(cliente, orden_id, prioridad, usuario=TECNICO, motivo=None):
    return cliente.post(
        f"/api/orders/{orden_id}/priority",
        json={
            "usuario_id": usuario,
            "prioridad": prioridad,
            "motivo": motivo,
        },
    )


def _cola(cliente) -> list[str]:
    bandejas = ok(
        cliente.get("/api/work/workshop", params={"usuario_id": TECNICO})
    )
    (cola,) = [b for b in bandejas["bandejas"] if b["codigo"] == "COLA"]
    return [item["orden"]["id"] for item in cola["ordenes"]]


def test_entra_sola_a_la_cola_con_prioridad_normal(cliente):
    orden_id = ingresada(cliente)

    orden = ok(cliente.get(f"/api/orders/{orden_id}"))

    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["prioridad"] == 4
    assert orden["prioridad_texto"] == "Prioridad 4 · Normal"
    assert ids(orden).count("PROC-REP-150") == 1
    assert ids(orden).count("PROC-REP-170") == 1
    assert "ENCOLAR" not in codigos(orden)
    assert ("CAMBIAR_PRIORIDAD", None) in complementarias(orden)
    assert orden_id in _cola(cliente)


def test_el_tecnico_cambia_la_prioridad_y_queda_registrado(cliente):
    orden_id = ingresada(cliente)
    antes = ok(cliente.get(f"/api/orders/{orden_id}"))

    orden = ok(_cambiar(cliente, orden_id, 1, motivo="Cliente viaja manana"))

    assert orden["prioridad"] == 1
    assert orden["estado_workflow"] == "EN_COLA"
    # No mueve el proceso ni vuelve a encolar.
    assert orden["current_process"] == antes["current_process"]
    assert ids(orden).count("PROC-REP-150") == 1
    assert ids(orden).count("PROC-REP-170") == 1
    cambio = orden["historial"][-1]
    assert cambio["tipo_referencia"] == "FUNCTIONAL_ACTION"
    assert cambio["referencia_id"] == "ACC-REP-007"
    assert cambio["accion"] == "CAMBIAR_PRIORIDAD"
    assert cambio["usuario_id"] == TECNICO
    assert cambio["fecha"] is not None
    assert cambio["observacion"] == "4 -> 1 (Urgente): Cliente viaja manana"


def test_la_cola_se_reordena(cliente):
    primera = ingresada(cliente)
    segunda = ingresada(cliente)
    assert _cola(cliente) == [primera, segunda]

    ok(_cambiar(cliente, segunda, 2, usuario=COORDINADOR))

    assert _cola(cliente) == [segunda, primera]


def test_tambien_en_reparacion_y_por_recepcion(cliente):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)
    iniciar(cliente, orden_id)

    orden = ok(_cambiar(cliente, orden_id, 2, usuario=RECEPCION))

    assert orden["estado_workflow"] == "EN_REPARACION"
    assert orden["prioridad"] == 2
    # Cualquier tecnico, no solo el titular.
    assert (
        ok(_cambiar(cliente, orden_id, 3, usuario=TECNICO_B))["prioridad"] == 3
    )


def test_validaciones(cliente, tmp_path):
    orden_id = ingresada(cliente)
    antes = archivo(tmp_path, orden_id)

    assert "ya tiene prioridad 4" in conflicto(_cambiar(cliente, orden_id, 4))
    conflicto(_cambiar(cliente, orden_id, 2, usuario=ADMINISTRADOR))
    for invalida in (0, 5):
        respuesta = _cambiar(cliente, orden_id, invalida)
        assert respuesta.status_code == 422, respuesta.text
    assert archivo(tmp_path, orden_id) == antes


def test_sin_priorizar_todavia_no_se_cambia(cliente, tmp_path):
    """RT_INTERNO conserva su circuito: Coordinacion la encola."""
    orden_id = _crear_orden_rt(cliente)
    agregar(cliente, orden_id)
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/definition/finalize",
            json={"usuario_id": RECEPCION},
        )
    )
    assert "ENCOLAR" in codigos(orden)
    assert orden["estado_workflow"] == "HABILITADA"
    assert not complementarias(orden)

    conflicto(_cambiar(cliente, orden_id, 2))
    encolada = ok(
        cliente.post(
            f"/api/orders/{orden_id}/queue",
            json={"usuario_id": COORDINADOR, "prioridad": 3},
        )
    )
    assert encolada["prioridad"] == 3
    assert ok(_cambiar(cliente, orden_id, 1))["prioridad"] == 1


def test_al_volver_a_la_cola_conserva_la_prioridad(cliente):
    orden_id = ingresada(cliente)
    ok(_cambiar(cliente, orden_id, 2))
    tomar(cliente, orden_id, TECNICO)

    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/release", json={"usuario_id": TECNICO}
        )
    )

    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["prioridad"] == 2
    assert ids(orden).count("PROC-REP-150") == 1
