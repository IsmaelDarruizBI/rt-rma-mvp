"""E2: la toma activa es exclusiva del tecnico que tomo la Orden.

Decision de negocio aprobada (auditoria funcional MVP v2, E2): mientras
la toma pertenece a un tecnico, la Orden queda bajo su responsabilidad
operativa. Los demas tecnicos pueden consultarla y ver quien la tiene,
pero no pueden iniciar, completar, interrumpir ni liberar. Liberada (y si
sigue siendo trabajable), otro tecnico puede tomarla.

Antes de la correccion, TECH-002 podia iniciar una Ejecucion sobre la
toma de TECH-001 y la Orden quedaba trabada: ni uno ni otro podia
completarla, interrumpirla ni liberarla.

    HTTP -> router -> application -> services -> repositories -> JSON
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.fixtures.api_definicion import definir_y_finalizar
from tests.test_api_hp_rep_002 import (
    COORDINADOR,
    ESTACION,
    INSUMO,
    RECEPCION,
    TECNICO,
    TIPO,
    _sembrar_catalogos,
)
from tests.test_api_var_rep_003 import TECNICO_B, _agregar_tecnico_b

CODIGO_TOMA_AJENA = "TOMA_DE_OTRO_TECNICO"


@pytest.fixture
def cliente(tmp_path):
    _sembrar_catalogos(tmp_path, stock="5")
    _agregar_tecnico_b(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def _archivo(tmp_path, orden_id: str) -> bytes:
    return (tmp_path / "ordenes" / f"{orden_id}.json").read_bytes()


def _tomada_por_tech_001(cliente: TestClient) -> str:
    """CLIENTE_EXTERNO definida, en cola y tomada por TECH-001."""
    orden_id = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "Cliente", "telefono": "341-1"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "La bateria dura poco.",
            },
        },
    ).json()["id"]
    respuesta = definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    assert respuesta.status_code == 200, respuesta.text
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    tomada = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    )
    assert tomada.status_code == 200, tomada.text
    return orden_id


def _iniciar(cliente, orden_id, usuario):
    return cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/start",
        json={"usuario_id": usuario},
    )


def _cerrar(cliente, orden_id, ejecucion_id, usuario, accion="complete"):
    motivo = {} if accion == "complete" else {"motivo": "Falta una pieza."}
    return cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/{accion}",
        json={
            "usuario_id": usuario,
            "insumos_utilizados": [{"insumo_id": INSUMO, "cantidad": "1"}],
            **motivo,
        },
    )


def _liberar(cliente, orden_id, usuario):
    return cliente.post(
        f"/api/orders/{orden_id}/release", json={"usuario_id": usuario}
    )


def _assert_rechazo_toma_ajena(respuesta) -> None:
    assert respuesta.status_code == 409, respuesta.text
    error = respuesta.json()["error"]
    assert error["codigo"] == CODIGO_TOMA_AJENA
    assert TECNICO in error["mensaje"]


# --- Visibilidad -------------------------------------------------------------


def test_otro_tecnico_ve_quien_tiene_la_toma(cliente):
    orden_id = _tomada_por_tech_001(cliente)

    orden = cliente.get(f"/api/orders/{orden_id}").json()

    toma = orden["toma_activa"]
    assert toma["usuario_id"] == TECNICO
    assert toma["estacion_id"] == ESTACION
    assert toma["estado"] == "ACTIVA"
    assert toma["inicio"] is not None
    # Las acciones tecnicas declaran a su unico titular: la UI las
    # deshabilita para cualquier otro tecnico.
    tecnicas = {
        a["codigo"]: a["usuario_id"]
        for a in orden["acciones_disponibles"]
        if a["codigo"] in ("INICIAR_DETALLE", "LIBERAR_ORDEN")
    }
    assert tecnicas == {"INICIAR_DETALLE": TECNICO, "LIBERAR_ORDEN": TECNICO}


def test_sin_toma_activa_no_hay_titular(cliente):
    orden_id = _tomada_por_tech_001(cliente)
    _liberar(cliente, orden_id, TECNICO)

    orden = cliente.get(f"/api/orders/{orden_id}").json()

    assert orden["toma_activa"] is None
    (tomar,) = [
        a for a in orden["acciones_disponibles"] if a["codigo"] == "TOMAR"
    ]
    assert tomar["usuario_id"] is None  # cualquier tecnico puede tomarla


# --- Otro tecnico no opera sobre la toma ajena -------------------------------


def test_otro_tecnico_no_puede_iniciar_sobre_la_toma_ajena(cliente, tmp_path):
    orden_id = _tomada_por_tech_001(cliente)
    archivo_antes = _archivo(tmp_path, orden_id)

    _assert_rechazo_toma_ajena(_iniciar(cliente, orden_id, TECNICO_B))

    # Nada cambio: ni Ejecucion, ni reserva, ni historial.
    assert _archivo(tmp_path, orden_id) == archivo_antes


def test_otro_tecnico_no_puede_completar_ni_interrumpir(cliente, tmp_path):
    orden_id = _tomada_por_tech_001(cliente)
    ejecucion_id = _iniciar(cliente, orden_id, TECNICO).json()["ejecuciones"][
        0
    ]["id"]
    archivo_antes = _archivo(tmp_path, orden_id)

    for accion in ("complete", "interrupt", "requires-redefinition"):
        respuesta = cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion_id}/{accion}",
            json={
                "usuario_id": TECNICO_B,
                "insumos_utilizados": [],
                "motivo": "No sirve.",
            },
        )
        _assert_rechazo_toma_ajena(respuesta)

    assert _archivo(tmp_path, orden_id) == archivo_antes
    # El titular sigue pudiendo cerrar su Ejecucion.
    cerrada = _cerrar(cliente, orden_id, ejecucion_id, TECNICO)
    assert cerrada.status_code == 200, cerrada.text


def test_otro_tecnico_no_puede_liberar_la_orden(cliente, tmp_path):
    orden_id = _tomada_por_tech_001(cliente)
    archivo_antes = _archivo(tmp_path, orden_id)

    _assert_rechazo_toma_ajena(_liberar(cliente, orden_id, TECNICO_B))

    assert _archivo(tmp_path, orden_id) == archivo_antes
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    assert orden["toma_activa"]["usuario_id"] == TECNICO


def test_otro_tecnico_no_puede_tomar_una_orden_ya_tomada(cliente, tmp_path):
    orden_id = _tomada_por_tech_001(cliente)
    archivo_antes = _archivo(tmp_path, orden_id)

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO_B, "estacion_id": ESTACION},
    )

    assert respuesta.status_code == 409, respuesta.text
    assert TECNICO in respuesta.json()["error"]["mensaje"]
    assert _archivo(tmp_path, orden_id) == archivo_antes


# --- El titular trabaja y libera; despues otro puede tomarla -----------------


def test_el_titular_trabaja_libera_y_otro_tecnico_toma(cliente):
    orden_id = _tomada_por_tech_001(cliente)

    iniciada = _iniciar(cliente, orden_id, TECNICO)
    assert iniciada.status_code == 200, iniciada.text
    ejecucion_id = iniciada.json()["ejecuciones"][0]["id"]
    interrumpida = _cerrar(
        cliente, orden_id, ejecucion_id, TECNICO, accion="interrupt"
    )
    assert interrumpida.status_code == 200, interrumpida.text

    liberada = _liberar(cliente, orden_id, TECNICO)
    assert liberada.status_code == 200, liberada.text
    assert liberada.json()["estado_workflow"] == "EN_COLA"
    assert liberada.json()["toma_activa"] is None

    tomada = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO_B, "estacion_id": ESTACION},
    )
    assert tomada.status_code == 200, tomada.text
    assert tomada.json()["toma_activa"]["usuario_id"] == TECNICO_B

    # Ahora el ajeno es TECH-001.
    respuesta = _iniciar(cliente, orden_id, TECNICO)
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["codigo"] == CODIGO_TOMA_AJENA

    nueva = _iniciar(cliente, orden_id, TECNICO_B)
    assert nueva.status_code == 200, nueva.text
    orden = nueva.json()
    # Historial de tomas conservado; ninguna Ejecucion ni reserva colgada.
    assert [(t["usuario_id"], t["estado"]) for t in orden["tomas"]] == [
        (TECNICO, "CERRADA"),
        (TECNICO_B, "ACTIVA"),
    ]
    assert [(e["usuario_id"], e["estado"]) for e in orden["ejecuciones"]] == [
        (TECNICO, "INTERRUMPIDO"),
        (TECNICO_B, "EN_PROGRESO"),
    ]


def test_los_intentos_ajenos_no_dejan_ejecuciones_ni_reservas(
    cliente, tmp_path
):
    from app.application import construir_contexto
    from app.services import hay_reservas_activas

    orden_id = _tomada_por_tech_001(cliente)

    for _ in range(3):
        _iniciar(cliente, orden_id, TECNICO_B)
        _liberar(cliente, orden_id, TECNICO_B)

    orden = construir_contexto(Settings(data_dir=tmp_path)).ordenes.obtener(
        orden_id
    )
    assert orden.ejecuciones == []
    assert not hay_reservas_activas(orden.movimientos_insumo)
    assert [t.usuario_id for t in orden.tomas] == [TECNICO]
