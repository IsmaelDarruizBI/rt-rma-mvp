"""BF-12 (D-02, alternativa A): el trabajo adicional del técnico espera al
cliente en Cliente Externo, y Recepción lo ve como pendiente de su sector
aunque otro trabajo esté en ejecución.

Recorrido completo por la API: el técnico propone el adicional durante la
ejecución (PROC-REP-128) → la Orden figura en «Pendientes de mi sector» de
Recepción y en su bandeja de autorizaciones → el adicional no se puede
iniciar (409) → Recepción registra la autorización → recién entonces se
inicia. En RT_INTERNO el adicional no espera (lo cubre
``test_macro_v14.py::test_adicional_en_rt_interno_pasa_por_la_factibilidad``).
"""

import pytest

from tests.fixtures import api_salidas as f


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _orden(cliente, orden_id) -> dict:
    return f.ok(cliente.get(f"/api/orders/{orden_id}"))


def _del_listado(cliente, orden_id) -> dict:
    (resumen,) = [
        o for o in f.ok(cliente.get("/api/orders")) if o["id"] == orden_id
    ]
    return resumen


def _avisos(orden) -> list[str]:
    return [a["codigo"] for a in orden["situacion"]["avisos"]]


def _con_adicional_durante_la_ejecucion(cliente) -> tuple[str, str]:
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)
    ejecucion_id = f.iniciar(cliente, orden_id)
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/additional",
            json={"usuario_id": f.TECNICO, "tipo_reparacion_id": f.PANTALLA},
        )
    )
    return orden_id, ejecucion_id


def test_el_adicional_pendiente_es_del_sector_de_recepcion(cliente):
    orden_id, _ = _con_adicional_durante_la_ejecucion(cliente)

    orden = _orden(cliente, orden_id)
    assert f.detalle(orden, "DET-002")["estado_autorizacion"] == "PENDIENTE"
    # Lo principal sigue siendo la ejecución en curso; la autorización es
    # un aviso, y aun así suma a Recepción al sector que debe actuar.
    assert orden["situacion"]["codigo"] != "ESPERANDO_AUTORIZACION"
    assert "AUTORIZACION_PENDIENTE" in _avisos(orden)
    assert "RECEPCION" in orden["situacion"]["roles"]
    assert "TECNICO" in orden["situacion"]["roles"]
    # El listado (de donde sale el filtro «Pendientes de mi sector») lleva
    # la misma situación.
    assert "RECEPCION" in _del_listado(cliente, orden_id)["situacion"]["roles"]


def test_sin_autorizacion_no_se_inicia_y_con_ella_si(cliente):
    orden_id, ejecucion_id = _con_adicional_durante_la_ejecucion(cliente)

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/details/DET-002/start",
        json={"usuario_id": f.TECNICO},
    )
    assert "autorizacion del cliente" in f.conflicto(respuesta)

    orden = f.ok(f.decidir(cliente, orden_id, {"DET-002": "AUTORIZADO"}))
    assert f.detalle(orden, "DET-002")["estado_autorizacion"] == "AUTORIZADO"
    assert "AUTORIZACION_PENDIENTE" not in _avisos(orden)
    assert "RECEPCION" not in orden["situacion"]["roles"]

    # Termina el trabajo en curso y el adicional ya se puede iniciar.
    f.ok(f.cerrar_ejecucion(cliente, orden_id, ejecucion_id))
    nueva = f.iniciar(cliente, orden_id, "DET-002")
    orden = _orden(cliente, orden_id)
    (activa,) = [
        e for e in orden["ejecuciones"] if e["estado"] == "EN_PROGRESO"
    ]
    assert activa["id"] == nueva


def test_un_rechazo_tambien_saca_la_orden_del_sector_de_recepcion(cliente):
    orden_id, _ = _con_adicional_durante_la_ejecucion(cliente)

    orden = f.ok(f.decidir(cliente, orden_id, {"DET-002": "RECHAZADO"}))

    assert f.detalle(orden, "DET-002")["estado"] == "CANCELADO"
    assert "RECEPCION" not in orden["situacion"]["roles"]
