"""Compatibilidad: Ordenes CANCELADA y abiertas del circuito anterior a DC31.

No se migran ni se cierran solas. Se reconocen por su estado (CANCELADA y
abierta: con DC31 cancelar cierra en el mismo acto), no por su id ni por
una fecha. Terminan el circuito anterior -custodia, devolucion fisica y
devolucion del dinero- y, una vez cerradas, no ofrecen acciones. No son
pendientes de Inicio ni de Taller.
"""

import pytest

from tests.fixtures.api_salidas import (
    BATERIA,
    PANTALLA,
    RECEPCION,
    agregar,
    cancelar_orden,
    cliente_http,
    codigos,
    conflicto,
    crear,
    definida,
    devolver,
    ok,
)
from tests.fixtures.cancelacion_heredada import cancelada_heredada
from tests.fixtures.custodia import no_recibido


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def _sin_acciones(orden: dict) -> None:
    for grupo in (
        "acciones_disponibles",
        "acciones_cancelacion",
        "acciones_autorizacion",
        "acciones_financieras",
        "acciones_custodia",
        "acciones_complementarias",
    ):
        assert orden[grupo] == [], grupo


def _bandejas(cliente, usuario=RECEPCION) -> dict:
    return ok(cliente.get("/api/work/inbox", params={"usuario_id": usuario}))


def _ids_en_bandejas(bandejas: dict) -> set[str]:
    return {
        item["orden"]["id"]
        for bandeja in bandejas["bandejas"]
        for item in bandeja["ordenes"]
    }


def test_con_equipo_en_custodia_se_devuelve_y_cierra(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    orden = cancelada_heredada(cliente, tmp_path, orden_id)

    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["cerrada"] is False
    assert orden["situacion"]["codigo"] == "CANCELADA_PENDIENTE_DEVOLUCION"
    assert codigos(orden) == ["REGISTRAR_DEVOLUCION"]
    # No se vuelve a cancelar: ya esta CANCELADA.
    conflicto(cancelar_orden(cliente, orden_id))

    orden = ok(devolver(cliente, orden_id, recibido_por="Cliente"))

    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["cerrada"] is True
    assert orden["current_process"] == "EVT-REP-999"
    _sin_acciones(orden)


def test_con_custodia_sin_definir_cierra_con_equipo_no_recibido(
    cliente, tmp_path
):
    orden_id = crear(cliente)
    agregar(cliente, orden_id, BATERIA)
    orden = cancelada_heredada(cliente, tmp_path, orden_id)
    assert orden["situacion"]["codigo"] == "CANCELADA_PENDIENTE_DEVOLUCION"
    assert "REGISTRAR_EQUIPO_NO_RECIBIDO" in [
        a["codigo"] for a in orden["acciones_custodia"]
    ]

    orden = ok(no_recibido(cliente, orden_id))

    assert orden["cerrada"] is True
    assert orden["custodia"]["estado"] == "NO_RECIBIDO"
    _sin_acciones(orden)


def test_con_credito_cierra_al_devolver_el_dinero(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA)
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": RECEPCION,
                "monto": "5000",
                "metodo": "EFECTIVO",
            },
        )
    )
    pago_id = orden["pagos"][-1]["id"]
    cancelada_heredada(cliente, tmp_path, orden_id)

    orden = ok(devolver(cliente, orden_id))
    assert orden["cerrada"] is False  # falta devolver el dinero
    assert "REGISTRAR_DEVOLUCION_DINERO" in [
        a["codigo"] for a in orden["acciones_financieras"]
    ]
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/refunds",
            json={
                "usuario_id": RECEPCION,
                "pago_id": pago_id,
                "monto": "5000",
                "medio": "EFECTIVO",
                "motivo": "Cancelacion.",
            },
        )
    )
    assert orden["cerrada"] is True
    _sin_acciones(orden)


def test_no_son_pendientes_de_inicio_ni_taller(cliente, tmp_path):
    heredada = definida(cliente, BATERIA)
    cancelada_heredada(cliente, tmp_path, heredada)
    activa = definida(cliente, BATERIA)

    for usuario in (RECEPCION, "TECH-001", "COORD-001", "ADMIN-001"):
        ids = _ids_en_bandejas(_bandejas(cliente, usuario))
        assert heredada not in ids, usuario
    taller = ok(
        cliente.get("/api/work/workshop", params={"usuario_id": "TECH-001"})
    )
    assert heredada not in _ids_en_bandejas(taller)
    assert activa in _ids_en_bandejas(_bandejas(cliente, "COORD-001"))
