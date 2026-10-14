"""E1: una Orden ENTREGADA queda cerrada para cualquier modificacion.

Decision de negocio aprobada (auditoria funcional MVP v2, E1): la Orden
entregada se puede consultar, pero ningun comando operativo la modifica
-ni aprobar, notificar, cobrar o entregar otra vez, ni tomarla, ejecutar,
redefinir o volver a REPARACION_LISTA-. Iniciar una garantia RMA desde
ella sigue funcionando y no la reabre: crea OTRA Orden.

Una Orden RT_INTERNO devuelta a Gestion RT (EVT-REP-999) tambien termino
su proceso, aunque su estado terminal siga pendiente de definicion y no
pase a ENTREGADA: recibe el mismo trato.

    HTTP -> router -> application -> services -> repositories -> JSON
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.fixtures.api_definicion import definir_y_finalizar
from tests.test_api_hp_rep_002 import (
    ADMINISTRADOR,
    COORDINADOR,
    ESTACION,
    RECEPCION,
    TECNICO,
    TIPO,
    _crear_orden_rt,
    _sembrar_catalogos,
)
from tests.test_api_hp_rep_003 import (
    _circuito_tecnico,
    _iniciar_garantia,
    _orden_entregada,
)

CODIGO_ORDEN_CERRADA = "ORDEN_CERRADA"


@pytest.fixture
def cliente(tmp_path):
    _sembrar_catalogos(tmp_path, stock="5")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def _archivo(tmp_path, orden_id: str) -> bytes:
    return (tmp_path / "ordenes" / f"{orden_id}.json").read_bytes()


def _comandos(orden: dict) -> list[tuple[str, dict | None]]:
    """Todos los comandos que modifican una Orden, con un cuerpo valido.

    Los cuerpos respetan la forma de cada endpoint para que la respuesta
    hable del estado de la Orden y no de un request mal formado (422).
    """
    orden_id = orden["id"]
    detalles = orden["reparaciones_detail"]
    ejecuciones = orden["ejecuciones"]
    detalle = detalles[0]["id"] if detalles else "DET-001"
    ejecucion = ejecuciones[0]["id"] if ejecuciones else "EJE-INEXISTENTE"
    base = f"/api/orders/{orden_id}"
    return [
        (
            f"{base}/details",
            {"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
        ),
        (f"{base}/definition/finalize", {"usuario_id": RECEPCION}),
        (f"{base}/send-to-review", {"usuario_id": RECEPCION}),
        (
            f"{base}/technical-review",
            {"usuario_id": TECNICO, "resultado": "Revision."},
        ),
        (
            f"{base}/review/details",
            {"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
        ),
        (
            f"{base}/review/without-repair",
            {"usuario_id": RECEPCION, "motivo": "Sin reparacion."},
        ),
        (
            f"{base}/details/{detalle}/resources/override",
            {
                "usuario_id": COORDINADOR,
                "motivo": "Urgente.",
                "confirmado": True,
            },
        ),
        (f"{base}/resources/wait", None),
        (f"{base}/resources/revalidate", None),
        (f"{base}/queue", {"usuario_id": COORDINADOR, "prioridad": 1}),
        (f"{base}/take", {"usuario_id": TECNICO, "estacion_id": ESTACION}),
        (f"{base}/details/{detalle}/start", {"usuario_id": TECNICO}),
        (
            f"{base}/executions/{ejecucion}/complete",
            {"usuario_id": TECNICO, "insumos_utilizados": []},
        ),
        (
            f"{base}/executions/{ejecucion}/interrupt",
            {"usuario_id": TECNICO, "insumos_utilizados": []},
        ),
        (
            f"{base}/executions/{ejecucion}/requires-redefinition",
            {
                "usuario_id": TECNICO,
                "insumos_utilizados": [],
                "motivo": "No sirve.",
            },
        ),
        (
            f"{base}/details/{detalle}/technical-review",
            {"usuario_id": TECNICO, "resultado": "Revision."},
        ),
        (
            f"{base}/details/{detalle}/redefine",
            {"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
        ),
        (f"{base}/release", {"usuario_id": TECNICO}),
        (f"{base}/control/approve", {"usuario_id": RECEPCION}),
        (f"{base}/notify", {"usuario_id": RECEPCION}),
        (
            f"{base}/payments",
            {"usuario_id": RECEPCION, "monto": "1000", "metodo": "EFECTIVO"},
        ),
        (f"{base}/deliver", {"usuario_id": ADMINISTRADOR}),
        (f"{base}/inform-rt", None),
        (f"{base}/return-rt", {"usuario_id": ADMINISTRADOR}),
    ]


def _post(cliente: TestClient, ruta: str, cuerpo: dict | None):
    if cuerpo is None:
        return cliente.post(ruta)
    return cliente.post(ruta, json=cuerpo)


def _assert_ningun_comando_la_modifica(cliente, tmp_path, orden: dict):
    """Cada comando responde 409 ORDEN_CERRADA y nada cambia."""
    orden_id = orden["id"]
    archivo_antes = _archivo(tmp_path, orden_id)
    vista_antes = cliente.get(f"/api/orders/{orden_id}").json()

    rechazos = {}
    for ruta, cuerpo in _comandos(vista_antes):
        respuesta = _post(cliente, ruta, cuerpo)
        rechazos[ruta] = (
            respuesta.status_code,
            respuesta.json().get("error", {}).get("codigo"),
        )

    esperado = {ruta: (409, CODIGO_ORDEN_CERRADA) for ruta in rechazos}
    assert rechazos == esperado

    # Ni el archivo persistido ni la vista cambiaron: sin historial nuevo,
    # sin pagos, sin volver a REPARACION_LISTA.
    assert _archivo(tmp_path, orden_id) == archivo_antes
    assert cliente.get(f"/api/orders/{orden_id}").json() == vista_antes


# --- CLIENTE_EXTERNO entregada -----------------------------------------------


def test_una_orden_entregada_rechaza_todos_los_comandos(cliente, tmp_path):
    entregada = _orden_entregada(cliente)

    _assert_ningun_comando_la_modifica(cliente, tmp_path, entregada)


def test_aprobar_el_control_de_una_orden_entregada_no_la_reabre(
    cliente, tmp_path
):
    """El bug reproducido en la auditoria: 240 otra vez sobre ENTREGADA."""
    entregada = _orden_entregada(cliente)
    archivo_antes = _archivo(tmp_path, entregada["id"])

    respuesta = cliente.post(
        f"/api/orders/{entregada['id']}/control/approve",
        json={"usuario_id": RECEPCION},
    )

    assert respuesta.status_code == 409, respuesta.text
    error = respuesta.json()["error"]
    assert error["codigo"] == CODIGO_ORDEN_CERRADA
    assert "entregada" in error["mensaje"].lower()
    orden = cliente.get(f"/api/orders/{entregada['id']}").json()
    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["current_process"] == "EVT-REP-999"
    assert _archivo(tmp_path, entregada["id"]) == archivo_antes


def test_no_se_registran_pagos_sobre_una_orden_entregada(cliente):
    entregada = _orden_entregada(cliente)

    respuesta = cliente.post(
        f"/api/orders/{entregada['id']}/payments",
        json={"usuario_id": RECEPCION, "monto": "1000", "metodo": "EFECTIVO"},
    )

    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["error"]["codigo"] == CODIGO_ORDEN_CERRADA
    orden = cliente.get(f"/api/orders/{entregada['id']}").json()
    assert len(orden["pagos"]) == 1  # solo el pago previo a la entrega


def test_una_orden_entregada_se_sigue_consultando(cliente):
    entregada = _orden_entregada(cliente)

    respuesta = cliente.get(f"/api/orders/{entregada['id']}")

    assert respuesta.status_code == 200
    orden = respuesta.json()
    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["cerrada"] is True
    assert [o["id"] for o in cliente.get("/api/orders").json()] == [
        entregada["id"]
    ]


def test_una_orden_abierta_no_figura_cerrada(cliente):
    orden_id = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "Cliente", "telefono": "341-1"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "No carga.",
            },
        },
    ).json()["id"]

    assert cliente.get(f"/api/orders/{orden_id}").json()["cerrada"] is False


def test_la_garantia_rma_nace_de_la_entregada_sin_reabrirla(cliente, tmp_path):
    entregada = _orden_entregada(cliente)
    archivo_antes = _archivo(tmp_path, entregada["id"])

    respuesta = _iniciar_garantia(cliente, entregada["id"])

    assert respuesta.status_code == 201, respuesta.text
    garantia = respuesta.json()
    assert garantia["id"] != entregada["id"]
    assert garantia["orden_origen_id"] == entregada["id"]
    assert garantia["cerrada"] is False
    # La Orden origen no se toco.
    assert _archivo(tmp_path, entregada["id"]) == archivo_antes
    origen = cliente.get(f"/api/orders/{entregada['id']}").json()
    assert origen["estado_workflow"] == "ENTREGADA"
    assert [a["codigo"] for a in origen["acciones_disponibles"]] == [
        "INICIAR_GARANTIA_RMA"
    ]


# --- SIN_REPARACION entregada ------------------------------------------------


def test_una_orden_sin_reparacion_entregada_queda_cerrada(cliente, tmp_path):
    """069 se deriva del historial: antes permitia notificar y re-entregar."""
    orden_id = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "Cliente", "telefono": "341-1"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "No enciende.",
            },
        },
    ).json()["id"]
    pasos = [
        (f"/api/orders/{orden_id}/send-to-review", {"usuario_id": RECEPCION}),
        (
            f"/api/orders/{orden_id}/technical-review",
            {"usuario_id": TECNICO, "resultado": "No tiene arreglo."},
        ),
        (
            f"/api/orders/{orden_id}/review/without-repair",
            {"usuario_id": RECEPCION, "motivo": "Placa irreparable."},
        ),
        (f"/api/orders/{orden_id}/notify", {"usuario_id": RECEPCION}),
        (f"/api/orders/{orden_id}/deliver", {"usuario_id": ADMINISTRADOR}),
    ]
    for ruta, cuerpo in pasos:
        respuesta = cliente.post(ruta, json=cuerpo)
        assert respuesta.status_code == 200, (ruta, respuesta.text)
    entregada = respuesta.json()
    assert entregada["estado_workflow"] == "ENTREGADA"

    _assert_ningun_comando_la_modifica(cliente, tmp_path, entregada)


# --- RT_INTERNO devuelta a Gestion RT ----------------------------------------


def test_una_orden_rt_devuelta_queda_cerrada(cliente, tmp_path):
    orden_id = _crear_orden_rt(cliente)
    respuesta = definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    assert respuesta.status_code == 200, respuesta.text
    _circuito_tecnico(cliente, orden_id)
    assert cliente.post(f"/api/orders/{orden_id}/inform-rt").status_code == 200
    devuelta = cliente.post(
        f"/api/orders/{orden_id}/return-rt",
        json={"usuario_id": ADMINISTRADOR},
    )
    assert devuelta.status_code == 200, devuelta.text
    assert devuelta.json()["current_process"] == "EVT-REP-999"
    assert devuelta.json()["cerrada"] is True

    _assert_ningun_comando_la_modifica(cliente, tmp_path, devuelta.json())
