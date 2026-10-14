"""Validaciones cruzadas de las correcciones E1-E4 (MVP v2).

Cada correccion tiene su propio archivo de tests; aqui se verifica que no
se contradigan entre si:

- E1 + E2: una Orden entregada sigue cerrada aunque opere quien tuvo la
  ultima toma.
- E2 + E3: un override no habilita a otro tecnico sobre la toma ajena.
- E3 + E4: consumos simultaneos dejan reservas, movimientos y stock
  consistentes.
- E1 + E4: una version obsoleta no puede sobrescribir una Orden entregada.
"""

import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.application import construir_contexto
from app.core.config import Settings
from app.domain.models import EstadoWorkflow
from app.main import create_app
from app.services import registrar_paso
from tests.fixtures.catalogos_mvp import t
from tests.test_api_hp_rep_002 import (
    ADMINISTRADOR,
    ESTACION,
    RECEPCION,
    TECNICO,
    _sembrar_catalogos,
)
from tests.test_api_hp_rep_003 import _orden_entregada
from tests.test_api_var_rep_003 import TECNICO_B, _agregar_tecnico_b
from tests.test_override_reservas_ajenas import (
    COORDINADOR,
    TIPO_CUATRO,
    TIPO_TRES,
    TIPO_UNA,
    _cliente,
    _completar,
    _definida,
    _disponible,
    _iniciada,
    _movimientos,
    _override,
    _stock_fisico,
)


@pytest.fixture
def cliente(tmp_path):
    _sembrar_catalogos(tmp_path, stock="5")
    _agregar_tecnico_b(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


# --- E1 + E2 -----------------------------------------------------------------


def test_la_toma_anterior_no_reabre_una_orden_entregada(cliente):
    entregada = _orden_entregada(cliente)
    orden_id = entregada["id"]
    (toma,) = entregada["tomas"]
    assert (toma["usuario_id"], toma["estado"]) == (TECNICO, "CERRADA")
    antes = cliente.get(f"/api/orders/{orden_id}").json()

    intentos = [
        ("take", {"usuario_id": TECNICO, "estacion_id": ESTACION}),
        ("details/DET-001/start", {"usuario_id": TECNICO}),
        ("release", {"usuario_id": TECNICO}),
    ]
    for ruta, cuerpo in intentos:
        respuesta = cliente.post(f"/api/orders/{orden_id}/{ruta}", json=cuerpo)
        assert respuesta.status_code == 409, (ruta, respuesta.text)
        assert respuesta.json()["error"]["codigo"] == "ORDEN_CERRADA"

    orden = cliente.get(f"/api/orders/{orden_id}").json()
    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["toma_activa"] is None
    assert orden == antes


# --- E2 + E3 -----------------------------------------------------------------


def test_el_override_no_habilita_a_otro_tecnico_sobre_la_toma(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _definida(cliente, TIPO_UNA)["id"]
        assert _override(cliente, orden_id, confirmado=True).status_code == 200
        cliente.post(
            f"/api/orders/{orden_id}/queue",
            json={"usuario_id": COORDINADOR, "prioridad": 1},
        )
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": TECNICO, "estacion_id": ESTACION},
        )

        ajeno = cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": TECNICO_B},
        )
        assert ajeno.status_code == 409, ajeno.text
        assert ajeno.json()["error"]["codigo"] == "TOMA_DE_OTRO_TECNICO"
        assert _movimientos(tmp_path, orden_id) == []

        titular = cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": TECNICO},
        )
        assert titular.status_code == 200, titular.text
        assert _disponible(tmp_path) == Decimal("-1")


# --- E3 + E4 -----------------------------------------------------------------


def test_consumos_simultaneos_con_override_quedan_consistentes(tmp_path):
    with _cliente(tmp_path, stock="5") as cliente:
        orden_a = _definida(cliente, TIPO_CUATRO)["id"]
        ejecucion_a = _iniciada(cliente, orden_a, TECNICO)
        orden_b = _definida(cliente, TIPO_TRES)["id"]
        assert _override(cliente, orden_b, confirmado=True).status_code == 200
        ejecucion_b = _iniciada(cliente, orden_b, TECNICO_B)

        largada = threading.Barrier(2)
        estados: dict[str, int] = {}

        def completar(orden_id, ejecucion_id, tecnico, cantidad):
            largada.wait()
            estados[orden_id] = _completar(
                cliente, orden_id, ejecucion_id, tecnico, cantidad
            ).status_code

        hilos = [
            threading.Thread(
                target=completar, args=(orden_a, ejecucion_a, TECNICO, "4")
            ),
            threading.Thread(
                target=completar, args=(orden_b, ejecucion_b, TECNICO_B, "3")
            ),
        ]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=60)

        assert estados == {orden_a: 200, orden_b: 200}
        assert _stock_fisico(tmp_path) == Decimal("-2")  # 5 - 4 - 3
        assert _disponible(tmp_path) == Decimal("-2")  # sin reservas abiertas
        for orden_id, cantidad in ((orden_a, "4"), (orden_b, "3")):
            tipos = sorted(
                (m["tipo"], m["cantidad"])
                for m in _movimientos(tmp_path, orden_id)
            )
            assert tipos == [("CONSUMO", cantidad), ("RESERVA", cantidad)]


# --- E1 + E4 -----------------------------------------------------------------


def test_una_version_obsoleta_no_sobrescribe_una_orden_entregada(
    cliente, tmp_path
):
    from app.repositories import RepositoryError

    repo = construir_contexto(Settings(data_dir=tmp_path)).ordenes
    entregada = _orden_entregada(cliente)
    orden_id = entregada["id"]
    archivo = (tmp_path / "ordenes" / f"{orden_id}.json").read_bytes()

    # Una operacion que hubiera leido la Orden antes de la entrega.
    historial_previo = len(repo.obtener(orden_id).historial) - 2
    obsoleta = repo.obtener(orden_id).model_copy(deep=True)
    obsoleta.historial = obsoleta.historial[:historial_previo]
    obsoleta.estado_workflow = EstadoWorkflow.REPARACION_LISTA
    obsoleta.current_process = "PROC-REP-265"
    obsoleta = registrar_paso(
        obsoleta, process_id="PROC-REP-240", accion="REABRIR", fecha=t(900)
    )

    with pytest.raises(RepositoryError) as error:
        repo.guardar(obsoleta)

    assert type(error.value).__name__ == "ConflictoDeEscrituraError"
    assert (tmp_path / "ordenes" / f"{orden_id}.json").read_bytes() == archivo


def test_entregar_y_aprobar_a_la_vez_no_reabren_la_orden(cliente):
    """Con la Orden lista para entregar, dos comandos llegan juntos."""
    from tests.fixtures.api_definicion import definir_y_finalizar
    from tests.test_api_hp_rep_003 import _circuito_tecnico

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
    definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": "TR-001"},
    )
    _circuito_tecnico(cliente, orden_id)
    cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    )
    cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={"usuario_id": RECEPCION, "monto": "80000", "metodo": "EFECTIVO"},
    )

    largada = threading.Barrier(2)
    estados: dict[str, int] = {}

    def enviar(nombre, ruta, cuerpo):
        largada.wait()
        estados[nombre] = cliente.post(ruta, json=cuerpo).status_code

    hilos = [
        threading.Thread(
            target=enviar,
            args=(
                "entregar",
                f"/api/orders/{orden_id}/deliver",
                {"usuario_id": ADMINISTRADOR},
            ),
        ),
        threading.Thread(
            target=enviar,
            args=(
                "aprobar",
                f"/api/orders/{orden_id}/control/approve",
                {"usuario_id": RECEPCION},
            ),
        ),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=60)

    orden = cliente.get(f"/api/orders/{orden_id}").json()
    entregas = [
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-270"
    ]
    # Desde E14 la reaprobacion se rechaza siempre -antes o despues de la
    # entrega-, asi que la entrega gana sin importar el orden de llegada:
    # una unica entrega y nunca una Orden reabierta.
    assert estados == {"entregar": 200, "aprobar": 409}
    assert orden["estado_workflow"] == "ENTREGADA"
    assert len(entregas) == 1
