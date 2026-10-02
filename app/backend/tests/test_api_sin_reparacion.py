"""PROC-REP-069 SIN_REPARACION por HTTP, para los tres Origenes.

    HTTP -> router -> application -> services -> repositories -> JSON

Tras la revision tecnica (065), sin Detalles, Recepcion concluye que no
corresponde reparar: 068 "No" -> 069 con motivo obligatorio (BR-REP-010).
No hay Tipo, Detalles ni precio (Subtotal 0) y no existe un estado de
workflow nuevo: SIN_REPARACION se deriva del historial. El cierre sigue
segun el Origen:

    CLIENTE_EXTERNO  250 -> 260 -> 265 -> 280 (sin garantia) -> 270
    RMA              igual, NO_COBRABLE
    RT_INTERNO       250 -> 290 -> 270
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.test_api_hp_rep_002 import (
    ADMINISTRADOR,
    RECEPCION,
    TECNICO,
    TIPO,
    _crear_orden_rt,
    _sembrar_catalogos,
)
from tests.test_api_hp_rep_003 import _iniciar_garantia, _orden_entregada
from tests.test_api_var_rep_001_002 import _crear_orden as _crear_orden_cliente

MOTIVO = "La falla es de uso: no corresponde reparar."


@pytest.fixture
def cliente(tmp_path):
    _sembrar_catalogos(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def _ids(orden: dict) -> list[str]:
    return [p["referencia_id"] for p in orden["historial"]]


def _codigos(orden: dict) -> list[str]:
    return [a["codigo"] for a in orden["acciones_disponibles"]]


def _revisada(cliente, orden_id: str) -> dict:
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/technical-review",
        json={"usuario_id": TECNICO, "resultado": "Sin falla reparable."},
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _enviada_y_revisada(cliente, orden_id: str) -> dict:
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/send-to-review",
        json={"usuario_id": RECEPCION},
    )
    assert respuesta.status_code == 200, respuesta.text
    return _revisada(cliente, orden_id)


def _sin_reparacion(cliente, orden_id, **cuerpo):
    return cliente.post(
        f"/api/orders/{orden_id}/review/without-repair",
        json={"usuario_id": RECEPCION, "motivo": MOTIVO, **cuerpo},
    )


def _assert_069(orden: dict) -> None:
    assert _ids(orden)[-2:] == ["PROC-REP-068", "PROC-REP-069"]
    paso_068, paso_069 = orden["historial"][-2:]
    assert paso_068["observacion"] == "No"
    assert paso_068["usuario_id"] == RECEPCION
    assert paso_069["usuario_id"] == RECEPCION
    assert MOTIVO in paso_069["observacion"]
    assert orden["finalizada_sin_reparacion"] is True
    # Sin Tipo inventado, sin Detalles, sin precio; sin estado nuevo.
    assert orden["reparaciones_detail"] == []
    assert orden["resumen"]["total"] == "0"
    assert orden["estado_workflow"] == "EN_REVISION"
    for ausente in ("PROC-REP-075", "PROC-REP-080", "PROC-REP-140"):
        assert ausente not in _ids(orden)


# --- CLIENTE_EXTERNO ---------------------------------------------------


def test_cliente_externo_sin_reparacion_de_punta_a_punta(cliente):
    orden_id = _crear_orden_cliente(cliente)
    orden = _enviada_y_revisada(cliente, orden_id)
    assert _codigos(orden) == [
        "AGREGAR_DETALLE_DESDE_REVISION",
        "FINALIZAR_SIN_REPARACION",
    ]

    respuesta = _sin_reparacion(
        cliente, orden_id, observaciones="Se informa al cliente."
    )
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    _assert_069(orden)
    assert "Se informa al cliente." in orden["historial"][-1]["observacion"]
    # Solo queda avisar al cliente: ni pago ni definicion.
    assert _codigos(orden) == ["NOTIFICAR"]

    # 250 -> 260 -> 265 (saldo 0, sin 266).
    orden = cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    ).json()
    assert _ids(orden)[-3:] == ["PROC-REP-250", "PROC-REP-260", "PROC-REP-265"]
    assert orden["puede_entregar"] is True
    assert "PROC-REP-266" not in _ids(orden)
    assert _codigos(orden) == ["ENTREGAR"]

    # 280 (sin garantia de reparacion) -> 270 -> EVT-REP-999.
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": ADMINISTRADOR}
    )
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    assert _ids(orden)[-2:] == ["PROC-REP-280", "PROC-REP-270"]
    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["current_process"] == "EVT-REP-999"
    assert orden["pagos"] == []
    assert orden["documentos"]["comprobante_final"]["generado"] is True
    assert orden["documentos"]["garantia_reparacion"]["generado"] is False
    # Sin Detalles no hay nada que garantizar.
    assert _codigos(orden) == []

    # El progreso salta de 069 al cierre y queda completo.
    ruta = [p["process_id"] for p in orden["progreso"]]
    i = ruta.index("PROC-REP-068")
    assert ruta[i : i + 3] == ["PROC-REP-068", "PROC-REP-069", "PROC-REP-250"]
    assert "PROC-REP-080" not in ruta
    faltantes = [
        p["process_id"] for p in orden["progreso"] if not p["alcanzado"]
    ]
    assert faltantes == ["PROC-REP-266"]


# --- RMA_GARANTIA_REPARACION -------------------------------------------


def test_garantia_rma_sin_reparacion_cierra_no_cobrable(cliente):
    origen = _orden_entregada(cliente)
    orden_id = _iniciar_garantia(cliente, origen["id"]).json()["id"]
    _revisada(cliente, orden_id)

    orden = _sin_reparacion(cliente, orden_id).json()
    _assert_069(orden)
    assert _codigos(orden) == ["NOTIFICAR"]

    orden = cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    ).json()
    assert orden["historial"][-1]["referencia_id"] == "PROC-REP-265"
    assert orden["historial"][-1]["observacion"] == "NO_COBRABLE_POR_ORIGEN"
    assert orden["puede_entregar"] is True

    orden = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": ADMINISTRADOR}
    ).json()
    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["current_process"] == "EVT-REP-999"
    assert orden["pagos"] == []
    assert orden["documentos"]["garantia_reparacion"]["generado"] is False
    assert orden["detalles_origen_ids"] == ["DET-001"]


# --- RT_INTERNO ----------------------------------------------------------


def test_rt_interno_sin_reparacion_informa_y_devuelve(cliente):
    orden_id = _crear_orden_rt(cliente)
    _enviada_y_revisada(cliente, orden_id)

    orden = _sin_reparacion(cliente, orden_id).json()
    _assert_069(orden)
    assert _codigos(orden) == ["INFORMAR_RT"]

    orden = cliente.post(f"/api/orders/{orden_id}/inform-rt").json()
    assert _ids(orden)[-2:] == ["PROC-REP-250", "PROC-REP-290"]
    assert _codigos(orden) == ["DEVOLVER_RT"]

    orden = cliente.post(
        f"/api/orders/{orden_id}/return-rt", json={"usuario_id": ADMINISTRADOR}
    ).json()
    assert orden["historial"][-1]["referencia_id"] == "PROC-REP-270"
    assert orden["current_process"] == "EVT-REP-999"
    assert not {"PROC-REP-260", "PROC-REP-265", "PROC-REP-280"} & set(
        _ids(orden)
    )


# --- Validaciones (sin efectos) -------------------------------------------


def test_sin_reparacion_exige_motivo(cliente):
    orden_id = _crear_orden_cliente(cliente)
    _enviada_y_revisada(cliente, orden_id)
    antes = cliente.get(f"/api/orders/{orden_id}").json()

    for cuerpo in (
        {"usuario_id": RECEPCION},
        {"usuario_id": RECEPCION, "motivo": ""},
        {"motivo": MOTIVO},
    ):
        respuesta = cliente.post(
            f"/api/orders/{orden_id}/review/without-repair", json=cuerpo
        )
        assert respuesta.status_code == 422, respuesta.text
    respuesta = _sin_reparacion(cliente, orden_id, motivo="   ")
    assert respuesta.status_code == 409, respuesta.text

    assert cliente.get(f"/api/orders/{orden_id}").json() == antes


@pytest.mark.parametrize("usuario", [TECNICO, ADMINISTRADOR, "COORD-001"])
def test_sin_reparacion_solo_recepcion(cliente, usuario):
    orden_id = _crear_orden_cliente(cliente)
    _enviada_y_revisada(cliente, orden_id)
    antes = cliente.get(f"/api/orders/{orden_id}").json()

    respuesta = _sin_reparacion(cliente, orden_id, usuario_id=usuario)
    assert respuesta.status_code == 409, respuesta.text
    assert cliente.get(f"/api/orders/{orden_id}").json() == antes


def test_sin_reparacion_solo_tras_065_sin_detalles_y_una_vez(cliente):
    assert _sin_reparacion(cliente, "OR-999999").status_code == 404

    # REQUERIMIENTO: no paso por revision.
    orden_id = _crear_orden_cliente(cliente)
    assert _sin_reparacion(cliente, orden_id).status_code == 409

    # EN_REVISION pero antes de 065.
    cliente.post(
        f"/api/orders/{orden_id}/send-to-review",
        json={"usuario_id": RECEPCION},
    )
    assert _sin_reparacion(cliente, orden_id).status_code == 409

    # Con un Detalle ya definido luego de la revision.
    con_detalle = _crear_orden_cliente(cliente)
    _enviada_y_revisada(cliente, con_detalle)
    cliente.post(
        f"/api/orders/{con_detalle}/review/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    antes = cliente.get(f"/api/orders/{con_detalle}").json()
    assert _sin_reparacion(cliente, con_detalle).status_code == 409
    assert cliente.get(f"/api/orders/{con_detalle}").json() == antes

    # Una sola vez; despues ya no se agregan Detalles.
    otra = _crear_orden_cliente(cliente)
    _enviada_y_revisada(cliente, otra)
    assert _sin_reparacion(cliente, otra).status_code == 200
    assert _sin_reparacion(cliente, otra).status_code == 409
    respuesta = cliente.post(
        f"/api/orders/{otra}/review/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    assert respuesta.status_code == 409, respuesta.text
    respuesta = cliente.post(
        f"/api/orders/{otra}/definition/finalize",
        json={"usuario_id": RECEPCION},
    )
    assert respuesta.status_code == 409, respuesta.text
