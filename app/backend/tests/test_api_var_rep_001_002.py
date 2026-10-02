"""VAR-REP-001 / VAR-REP-002 (ingreso sin diagnostico) por HTTP.

    HTTP -> router -> application -> services -> repositories -> JSON

VAR-REP-001 aplica a CLIENTE_EXTERNO (con comprobante); VAR-REP-002 a
RT_INTERNO (sin comprobante). La diferencia sale solo de
``PoliticaOrigen.requiere_comprobante_recepcion``. En una garantia RMA la
revision es obligatoria y forma parte de HP-REP-003
(``test_api_hp_rep_003.py``).
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import TipoReparacion
from app.main import create_app
from app.storage.json.base import escribir_json_atomico
from tests.fixtures.api_definicion import (
    definir_desde_revision_y_finalizar,
    definir_y_finalizar,
)
from tests.test_api_hp_rep_002 import (
    ADMINISTRADOR,
    COORDINADOR,
    RECEPCION,
    TECNICO,
    TIPO,
    _crear_orden_rt,
    _sembrar_catalogos,
)
from tests.test_api_hp_rep_003 import _circuito_tecnico


@pytest.fixture
def cliente(tmp_path):
    _sembrar_catalogos(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def _crear_orden(cliente: TestClient) -> str:
    respuesta = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "Cliente", "telefono": "341-1"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "No enciende y no se sabe por que.",
            },
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _enviar(cliente, orden_id, usuario=RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/send-to-review", json={"usuario_id": usuario}
    )


def _revisar(cliente, orden_id, usuario=TECNICO, resultado="Falla de placa."):
    return cliente.post(
        f"/api/orders/{orden_id}/technical-review",
        json={"usuario_id": usuario, "resultado": resultado},
    )


def _agregar(cliente, orden_id, usuario=RECEPCION, tipo=TIPO):
    """Agrega UN Detalle luego de la revision (068 Si -> 075)."""
    return cliente.post(
        f"/api/orders/{orden_id}/review/details",
        json={"usuario_id": usuario, "tipo_reparacion_id": tipo},
    )


def _definir(cliente, orden_id, usuario=RECEPCION, tipo=TIPO):
    """Agrega UN Detalle luego de la revision y finaliza la definicion."""
    return definir_desde_revision_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": usuario, "tipo_reparacion_id": tipo},
    )


def _ids(orden: dict) -> list[str]:
    return [p["referencia_id"] for p in orden["historial"]]


def _codigos(orden: dict) -> list[str]:
    return [a["codigo"] for a in orden["acciones_disponibles"]]


# --- VAR-REP-001: CLIENTE_EXTERNO --------------------------------------


def test_var_rep_001_cliente_externo_de_punta_a_punta(cliente):
    orden_id = _crear_orden(cliente)
    assert _codigos(cliente.get(f"/api/orders/{orden_id}").json()) == [
        "AGREGAR_DETALLE",
        "ENVIAR_A_REVISION",
    ]

    # 045 No -> 055 -> 050 Si -> 060
    respuesta = _enviar(cliente, orden_id)
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    assert orden["estado_workflow"] == "EN_REVISION"
    assert orden["reparaciones_detail"] == []
    assert _ids(orden)[-4:] == [
        "PROC-REP-045",
        "PROC-REP-055",
        "PROC-REP-050",
        "PROC-REP-060",
    ]
    paso_045 = next(
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-045"
    )
    assert paso_045["observacion"] == "No"
    paso_055 = next(
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-055"
    )
    assert paso_055["usuario_id"] is None  # ACT-SYSTEM
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is True
    assert _codigos(orden) == ["REALIZAR_REVISION"]

    # 065 (Tecnico)
    orden = _revisar(cliente, orden_id, resultado="  Placa danada.  ").json()
    paso_065 = orden["historial"][-1]
    assert paso_065["referencia_id"] == "PROC-REP-065"
    assert paso_065["usuario_id"] == TECNICO
    assert paso_065["observacion"] == "Placa danada."
    assert orden["estado_workflow"] == "EN_REVISION"
    assert _codigos(orden) == [
        "AGREGAR_DETALLE_DESDE_REVISION",
        "FINALIZAR_SIN_REPARACION",
    ]

    # 068 Si -> 075, y al finalizar 080 -> 090 -> 140 (sin 050/060 otra vez)
    respuesta = _definir(cliente, orden_id)
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    assert _ids(orden)[-5:] == [
        "PROC-REP-068",
        "PROC-REP-075",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]
    assert _ids(orden).count("PROC-REP-050") == 1
    assert _ids(orden).count("PROC-REP-060") == 1
    assert "PROC-REP-070" not in _ids(orden)
    assert orden["estado_workflow"] == "HABILITADA"
    (detalle,) = orden["reparaciones_detail"]
    assert detalle["estado"] == "DEFINIDO"
    assert Decimal(detalle["precio"]) == Decimal("80000")
    assert detalle["puntaje"] == 10
    assert detalle["garantia_dias"] == 90
    assert detalle["detalle_origen_id"] is None
    assert "ENCOLAR" in _codigos(orden)

    # El circuito normal posterior sigue disponible.
    orden = _circuito_tecnico(cliente, orden_id)
    assert orden["estado_workflow"] == "REPARACION_LISTA"


def test_progreso_de_la_variante_refleja_la_revision(cliente):
    orden_id = _crear_orden(cliente)
    orden = _enviar(cliente, orden_id).json()
    ruta = [p["process_id"] for p in orden["progreso"]]
    assert ruta[:9] == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-055",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-065",
        "PROC-REP-068",
    ]
    assert ruta[9:11] == ["PROC-REP-075", "PROC-REP-080"]
    assert "PROC-REP-070" not in ruta
    alcanzados = [p["process_id"] for p in orden["progreso"] if p["alcanzado"]]
    assert alcanzados[-1] == "PROC-REP-060"


# --- VAR-REP-002: RT_INTERNO -------------------------------------------


def test_var_rep_002_rt_interno_sin_comprobante(cliente):
    orden_id = _crear_orden_rt(cliente)

    respuesta = _enviar(cliente, orden_id)
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    assert orden["estado_workflow"] == "EN_REVISION"
    assert _ids(orden)[-3:] == ["PROC-REP-045", "PROC-REP-055", "PROC-REP-050"]
    assert "PROC-REP-060" not in _ids(orden)
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is False
    paso_050 = orden["historial"][-1]
    assert paso_050["observacion"] == "No"

    _revisar(cliente, orden_id)
    orden = _definir(cliente, orden_id).json()
    assert orden["estado_workflow"] == "HABILITADA"
    assert _ids(orden)[-6:] == [
        "PROC-REP-065",
        "PROC-REP-068",
        "PROC-REP-075",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]
    assert "PROC-REP-060" not in _ids(orden)
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is False

    ruta = [p["process_id"] for p in orden["progreso"]]
    assert "PROC-REP-020" in ruta and "PROC-REP-060" not in ruta
    assert ruta.index("PROC-REP-055") == ruta.index("PROC-REP-045") + 1

    # El Happy Path RT continua con normalidad.
    orden = _circuito_tecnico(cliente, orden_id)
    assert "INFORMAR_RT" in _codigos(orden)
    orden = cliente.post(f"/api/orders/{orden_id}/inform-rt", json={}).json()
    orden = cliente.post(
        f"/api/orders/{orden_id}/return-rt", json={"usuario_id": ADMINISTRADOR}
    ).json()
    assert orden["current_process"] == "EVT-REP-999"


# --- Multi-Detalle luego de revision -----------------------------------


def test_multidetalle_luego_de_revision(cliente):
    orden_id = _crear_orden(cliente)
    _enviar(cliente, orden_id)
    _revisar(cliente, orden_id)

    orden = _agregar(cliente, orden_id).json()
    assert orden["estado_workflow"] == "EN_REVISION"
    # Con un Detalle ya no se ofrece SIN_REPARACION: se agrega otro o se
    # finaliza la definicion.
    assert _codigos(orden) == [
        "AGREGAR_DETALLE_DESDE_REVISION",
        "FINALIZAR_DEFINICION",
        "REGISTRAR_PAGO",
    ]
    assert _ids(orden)[-2:] == ["PROC-REP-068", "PROC-REP-075"]
    assert "PROC-REP-080" not in _ids(orden)

    orden = _definir(cliente, orden_id).json()
    assert orden["estado_workflow"] == "HABILITADA"
    assert [d["id"] for d in orden["reparaciones_detail"]] == [
        "DET-001",
        "DET-002",
    ]
    ids = _ids(orden)
    assert ids.count("PROC-REP-068") == 1
    assert ids.count("PROC-REP-075") == 2
    assert ids.count("PROC-REP-050") == 1
    assert ids.count("PROC-REP-060") == 1
    assert ids[-3:] == ["PROC-REP-080", "PROC-REP-090", "PROC-REP-140"]


# --- Autorizacion (409 exacto) -------------------------------------------


@pytest.mark.parametrize("usuario", [TECNICO, COORDINADOR, ADMINISTRADOR])
def test_send_to_review_solo_recepcion(cliente, usuario):
    orden_id = _crear_orden(cliente)
    assert _enviar(cliente, orden_id, usuario).status_code == 409


@pytest.mark.parametrize("usuario", [RECEPCION, COORDINADOR, ADMINISTRADOR])
def test_technical_review_solo_tecnico(cliente, usuario):
    orden_id = _crear_orden(cliente)
    _enviar(cliente, orden_id)
    assert _revisar(cliente, orden_id, usuario).status_code == 409


@pytest.mark.parametrize("usuario", [TECNICO, COORDINADOR, ADMINISTRADOR])
def test_definir_desde_revision_solo_recepcion(cliente, usuario):
    orden_id = _crear_orden(cliente)
    _enviar(cliente, orden_id)
    _revisar(cliente, orden_id)
    assert _definir(cliente, orden_id, usuario).status_code == 409


# --- Negativos --------------------------------------------------------------


def test_enviar_a_revision_con_detalles_o_fuera_de_requerimiento(cliente):
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={
            "usuario_id": RECEPCION,
            "tipo_reparacion_id": TIPO,
        },
    )
    assert _enviar(cliente, orden_id).status_code == 409  # con Detalles

    otra = _crear_orden(cliente)
    definir_y_finalizar(
        cliente,
        otra,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )  # queda HABILITADA
    assert _enviar(cliente, otra).status_code == 409  # fuera de REQUERIMIENTO

    en_revision = _crear_orden(cliente)
    _enviar(cliente, en_revision)
    assert _enviar(cliente, en_revision).status_code == 409  # ya enviada


def test_revision_tecnica_negativos(cliente):
    orden_id = _crear_orden(cliente)
    assert _revisar(cliente, orden_id).status_code == 409  # no EN_REVISION

    _enviar(cliente, orden_id)
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/technical-review",
        json={"usuario_id": TECNICO, "resultado": ""},
    )
    assert respuesta.status_code == 422, respuesta.text
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/technical-review",
        json={"usuario_id": TECNICO, "resultado": "   "},
    )
    assert respuesta.status_code == 409, respuesta.text

    assert _revisar(cliente, orden_id).status_code == 200
    assert _revisar(cliente, orden_id).status_code == 409  # repetida


def test_definir_desde_revision_negativos(cliente, tmp_path):
    orden_id = _crear_orden(cliente)
    _enviar(cliente, orden_id)

    # Antes de PROC-REP-065.
    assert _agregar(cliente, orden_id).status_code == 409
    # El endpoint normal (045 Si -> 070) no sirve sobre EN_REVISION.
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    assert respuesta.status_code == 409, respuesta.text

    _revisar(cliente, orden_id)
    escribir_json_atomico(
        tmp_path / "catalogs" / "tipos_reparacion.json",
        [
            TipoReparacion(
                id="TR-OFF",
                nombre="Inactivo",
                precio=Decimal("1"),
                puntaje=1,
                garantia_dias=1,
                activo=False,
            ).model_dump(mode="json")
        ],
    )
    assert _agregar(cliente, orden_id, tipo="TR-OFF").status_code == 409

    # Un Detalle de una Orden que no es garantia no admite Detalle origen.
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/review/details",
        json={
            "usuario_id": RECEPCION,
            "tipo_reparacion_id": "TR-OFF",
            "detalle_origen_id": "DET-001",
        },
    )
    assert respuesta.status_code == 409, respuesta.text


def test_hp1_no_registra_nodos_de_revision(cliente):
    """HP1 sigue sin 055/065/068/075 (045 Si -> 070)."""
    orden_id = _crear_orden(cliente)
    orden = definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    ).json()
    assert not {
        "PROC-REP-055",
        "PROC-REP-065",
        "PROC-REP-068",
        "PROC-REP-075",
    } & set(_ids(orden))


def test_factibilidad_fallida_luego_de_revision_espera_recursos(tmp_path):
    """Sin stock, 090 no aprueba: EXC-REP-001 (ya no es un 409).

    Slice 4 caracterizaba 409 y nada persistido; Slice 6 lo vuelve
    obsoleto a proposito: el Detalle se define y persiste BLOQUEADO y la
    Orden queda en PROC-REP-100, sin llegar a PROC-REP-140. Luego espera
    (110 No -> 120) sin repetir 065/068/075 ni el comprobante.
    """
    _sembrar_catalogos(tmp_path, stock="0")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as cliente:
        orden_id = _crear_orden(cliente)
        _enviar(cliente, orden_id)
        _revisar(cliente, orden_id)

        respuesta = _definir(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text

        orden = cliente.get(f"/api/orders/{orden_id}").json()
        assert orden["estado_workflow"] == "EN_REVISION"
        assert orden["current_process"] == "PROC-REP-100"
        (detalle,) = orden["reparaciones_detail"]
        assert detalle["condicion"] == "BLOQUEADO_POR_RECURSOS"
        assert _ids(orden)[-4:] == [
            "PROC-REP-075",
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-100",
        ]
        assert "PROC-REP-140" not in _ids(orden)
        # La definicion ya se finalizo (080): no se agregan ni se finalizan
        # Detalles otra vez.
        assert "AGREGAR_DETALLE_DESDE_REVISION" not in _codigos(orden)
        assert "FINALIZAR_DEFINICION" not in _codigos(orden)
        assert "ESPERAR_RECURSOS" in _codigos(orden)

        orden = cliente.post(f"/api/orders/{orden_id}/resources/wait").json()
        assert _ids(orden)[-2:] == ["PROC-REP-110", "PROC-REP-120"]
        ids = _ids(orden)
        assert ids.count("PROC-REP-065") == 1
        assert ids.count("PROC-REP-068") == 1
        assert ids.count("PROC-REP-075") == 1
        assert ids.count("PROC-REP-060") == 1
