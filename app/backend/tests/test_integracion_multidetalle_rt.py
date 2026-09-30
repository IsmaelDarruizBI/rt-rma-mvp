"""Integracion de Multi-Detalle (Slice 1) con RT_INTERNO (HP-REP-002).

HP-REP-002 reutiliza exactamente la mecanica de Multi-Detalle:
``180 -> 212 [Si] -> 181``, sin variante RT. Estos tests fijan lo que
solo aparece al combinar ambas ramas.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.test_api_hp_rep_002 import (
    ADMINISTRADOR,
    COORDINADOR,
    ESTACION,
    INSUMO,
    RECEPCION,
    TECNICO,
    TIPO,
    _crear_orden_rt,
    _sembrar_catalogos,
)


@pytest.fixture
def cliente(tmp_path):
    _sembrar_catalogos(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


TRAMO_TECNICO_HP2 = [
    "PROC-REP-170",
    "PROC-REP-172",
    "PROC-REP-180",
    "PROC-REP-212",
    "PROC-REP-181",
    "PROC-REP-174",
    "PROC-REP-185",
    "PROC-REP-190",
    "PROC-REP-200",
    "PROC-REP-210",
    "PROC-REP-211",
    "PROC-REP-220",
]


def _recorrer_hp2_hasta_lista(cliente) -> str:
    orden_id = _crear_orden_rt(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    )
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    detalle_id = orden["reparaciones_detail"][0]["id"]
    ejecucion_id = cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": TECNICO},
    ).json()["ejecuciones"][0]["id"]
    cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={
            "usuario_id": TECNICO,
            "insumos_utilizados": [{"insumo_id": INSUMO, "cantidad": "1"}],
        },
    )
    cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={"usuario_id": RECEPCION},
    )
    return orden_id


def test_hp2_recorre_212_entre_180_y_181_y_cierra_con_actores_correctos(
    cliente,
):
    orden_id = _recorrer_hp2_hasta_lista(cliente)

    orden = cliente.post(f"/api/orders/{orden_id}/inform-rt", json={}).json()
    orden = cliente.post(
        f"/api/orders/{orden_id}/return-rt",
        json={"usuario_id": ADMINISTRADOR},
    ).json()

    historial = [p["referencia_id"] for p in orden["historial"]]
    inicio = historial.index("PROC-REP-170")
    assert historial[inicio : inicio + len(TRAMO_TECNICO_HP2)] == (
        TRAMO_TECNICO_HP2
    )
    cierre = historial[inicio + len(TRAMO_TECNICO_HP2) :]
    assert cierre == [
        "PROC-REP-230",
        "PROC-REP-245",
        "PROC-REP-240",
        "PROC-REP-250",
        "PROC-REP-290",
        "PROC-REP-270",
    ]
    assert orden["current_process"] == "EVT-REP-999"

    por_id = {p["referencia_id"]: p for p in orden["historial"]}
    assert por_id["PROC-REP-290"]["usuario_id"] is None
    assert por_id["PROC-REP-270"]["usuario_id"] == ADMINISTRADOR


def test_progreso_rt_incluye_212_entre_180_y_181_y_consolida_puntaje(cliente):
    orden_id = _recorrer_hp2_hasta_lista(cliente)
    orden = cliente.get(f"/api/orders/{orden_id}").json()

    pasos = [p["process_id"] for p in orden["progreso"]]
    assert pasos.index("PROC-REP-212") == pasos.index("PROC-REP-180") + 1
    assert pasos.index("PROC-REP-181") == pasos.index("PROC-REP-212") + 1
    etiqueta_245 = next(
        p["etiqueta"] for p in orden["progreso"]
        if p["process_id"] == "PROC-REP-245"
    )
    assert etiqueta_245 == "Consolidar puntaje"


def test_hp2_conserva_acciones_multidetalle_con_toma_activa(cliente):
    """RT_INTERNO ofrece INICIAR_DETALLE por Detalle y LIBERAR_ORDEN."""
    orden_id = _crear_orden_rt(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    orden = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    ).json()

    acciones = {
        (a["codigo"], a["detalle_id"]) for a in orden["acciones_disponibles"]
    }
    assert ("INICIAR_DETALLE", "DET-001") in acciones
    assert ("LIBERAR_ORDEN", None) in acciones


def test_pago_rt_409_y_cliente_externo_sigue_cobrando(cliente):
    orden_id = _recorrer_hp2_hasta_lista(cliente)
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={"usuario_id": ADMINISTRADOR, "monto": "1", "metodo": "EFECTIVO"},
    )
    assert respuesta.status_code == 409, respuesta.text

    externa = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "Cliente", "telefono": "341-0000000"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "Bateria.",
            },
        },
    ).json()
    cliente.post(
        f"/api/orders/{externa['id']}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    respuesta = cliente.post(
        f"/api/orders/{externa['id']}/payments",
        json={"usuario_id": RECEPCION, "monto": "1000", "metodo": "EFECTIVO"},
    )
    assert respuesta.status_code in (200, 201), respuesta.text
    assert Decimal(respuesta.json()["resumen"]["saldo"]) > 0
