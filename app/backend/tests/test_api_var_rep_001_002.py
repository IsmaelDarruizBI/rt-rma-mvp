"""VAR-REP-001 / VAR-REP-002 (ingreso sin diagnostico) por HTTP.

    HTTP -> router -> application -> services -> repositories -> JSON

VAR-REP-001 aplica a CLIENTE_EXTERNO y RMA_GARANTIA_REPARACION (con
comprobante); VAR-REP-002 a RT_INTERNO (sin comprobante). La diferencia
sale solo de ``PoliticaOrigen.requiere_comprobante_recepcion``.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import TipoReparacion
from app.main import create_app
from app.storage.json.base import escribir_json_atomico
from tests.test_api_hp_rep_002 import (
    ADMINISTRADOR,
    COORDINADOR,
    RECEPCION,
    TECNICO,
    TIPO,
    _crear_orden_rt,
    _sembrar_catalogos,
)
from tests.test_api_hp_rep_003 import (
    _circuito_tecnico,
    _generar_garantia,
    _orden_entregada,
)


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


def _definir(cliente, orden_id, usuario=RECEPCION, tipo=TIPO, final=True):
    return cliente.post(
        f"/api/orders/{orden_id}/review/details",
        json={
            "usuario_id": usuario,
            "tipo_reparacion_id": tipo,
            "finalizar_definicion": final,
        },
    )


def _ids(orden: dict) -> list[str]:
    return [p["referencia_id"] for p in orden["historial"]]


def _codigos(orden: dict) -> list[str]:
    return [a["codigo"] for a in orden["acciones_disponibles"]]


# --- VAR-REP-001: CLIENTE_EXTERNO --------------------------------------


def test_var_rep_001_cliente_externo_de_punta_a_punta(cliente):
    orden_id = _crear_orden(cliente)
    assert _codigos(cliente.get(f"/api/orders/{orden_id}").json()) == [
        "DEFINIR_REPARACION",
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
    assert _codigos(orden) == ["DEFINIR_REPARACION_DESDE_REVISION"]

    # 068 Si -> 075 -> 080 -> 090 -> 140 (sin 050/060 otra vez)
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


# --- RMA_GARANTIA_REPARACION en revision --------------------------------


def test_garantia_rma_en_revision_de_punta_a_punta(cliente, tmp_path):
    origen = _orden_entregada(cliente)
    origen_id = origen["id"]
    foto_origen = cliente.get(f"/api/orders/{origen_id}").json()

    respuesta = cliente.post(
        f"/api/orders/{origen_id}/details/DET-001/warranty-rma/review",
        json={"usuario_id": RECEPCION},
    )
    assert respuesta.status_code == 201, respuesta.text
    orden = respuesta.json()
    orden_id = orden["id"]

    assert orden_id != origen_id
    assert orden["origen"] == "RMA_GARANTIA_REPARACION"
    assert orden["estado_workflow"] == "EN_REVISION"
    assert orden["orden_origen_id"] == origen_id
    assert orden["detalles_origen_ids"] == ["DET-001"]
    assert orden["reparaciones_detail"] == []
    assert orden["pagos"] == []
    assert orden["cliente"] == origen["cliente"]
    assert _ids(orden) == [
        "PROC-REP-035",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-055",
        "PROC-REP-050",
        "PROC-REP-060",
    ]
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is True
    assert cliente.get(f"/api/orders/{origen_id}").json() == foto_origen

    # El catalogo cambia ANTES de PROC-REP-075: el Detalle toma el
    # snapshot vigente, no el del Detalle historico.
    escribir_json_atomico(
        tmp_path / "catalogs" / "tipos_reparacion.json",
        [
            TipoReparacion(
                id=TIPO,
                nombre="Cambio bateria iPhone 14",
                precio=Decimal("95000"),
                puntaje=12,
                garantia_dias=120,
            ).model_dump(mode="json")
        ],
    )

    assert _revisar(cliente, orden_id).status_code == 200
    orden = _definir(cliente, orden_id).json()
    assert orden["estado_workflow"] == "HABILITADA"
    (detalle,) = orden["reparaciones_detail"]
    assert detalle["detalle_origen_id"] == "DET-001"
    assert Decimal(detalle["precio"]) == Decimal("95000")
    assert detalle["puntaje"] == 12
    assert detalle["garantia_dias"] == 120
    assert origen["reparaciones_detail"][0]["precio"] == "80000"
    assert "PROC-REP-070" not in _ids(orden)
    assert _ids(orden).count("PROC-REP-060") == 1
    assert orden["detalles_origen_ids"] == ["DET-001"]
    assert cliente.get(f"/api/orders/{origen_id}").json() == foto_origen

    # Converge con el circuito de garantia directa (NO_COBRABLE).
    orden = _circuito_tecnico(cliente, orden_id)
    assert orden["resumen"]["condicion_comercial"] == "NO_COBRABLE"
    assert "REGISTRAR_PAGO" not in _codigos(orden)


def test_garantia_directa_completa_detalles_origen_ids(cliente):
    origen = _orden_entregada(cliente)
    orden = _generar_garantia(cliente, origen["id"], "DET-001").json()

    assert orden["detalles_origen_ids"] == ["DET-001"]
    assert orden["reparaciones_detail"][0]["detalle_origen_id"] == "DET-001"
    assert "PROC-REP-055" not in _ids(orden)


# --- Multi-Detalle luego de revision -----------------------------------


def test_multidetalle_luego_de_revision(cliente):
    orden_id = _crear_orden(cliente)
    _enviar(cliente, orden_id)
    _revisar(cliente, orden_id)

    orden = _definir(cliente, orden_id, final=False).json()
    assert orden["estado_workflow"] == "EN_REVISION"
    assert _codigos(orden) == [
        "DEFINIR_REPARACION_DESDE_REVISION",
        "REGISTRAR_PAGO",
    ]
    assert _ids(orden)[-2:] == ["PROC-REP-068", "PROC-REP-075"]

    orden = _definir(cliente, orden_id, final=True).json()
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


@pytest.mark.parametrize("usuario", [TECNICO, COORDINADOR, ADMINISTRADOR])
def test_garantia_en_revision_solo_recepcion(cliente, usuario):
    origen = _orden_entregada(cliente)
    respuesta = cliente.post(
        f"/api/orders/{origen['id']}/details/DET-001/warranty-rma/review",
        json={"usuario_id": usuario},
    )
    assert respuesta.status_code == 409, respuesta.text
    assert len(cliente.get("/api/orders").json()) == 1


# --- Negativos --------------------------------------------------------------


def test_enviar_a_revision_con_detalles_o_fuera_de_requerimiento(cliente):
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={
            "usuario_id": RECEPCION,
            "tipo_reparacion_id": TIPO,
            "finalizar_definicion": False,
        },
    )
    assert _enviar(cliente, orden_id).status_code == 409  # con Detalles

    otra = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{otra}/details",
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
    assert _definir(cliente, orden_id).status_code == 409
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
    assert _definir(cliente, orden_id, tipo="TR-OFF").status_code == 409

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


def test_garantia_en_revision_negativos(cliente):
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/warranty-rma/review",
        json={"usuario_id": RECEPCION},
    )
    assert respuesta.status_code == 409, respuesta.text  # no ENTREGADA

    origen = _orden_entregada(cliente)
    respuesta = cliente.post(
        f"/api/orders/{origen['id']}/details/DET-999/warranty-rma/review",
        json={"usuario_id": RECEPCION},
    )
    assert respuesta.status_code == 404, respuesta.text


def test_garantia_directa_sigue_igual(cliente):
    origen = _orden_entregada(cliente)
    respuesta = _generar_garantia(cliente, origen["id"], "DET-001")
    assert respuesta.status_code == 201
    orden = respuesta.json()
    assert orden["estado_workflow"] == "HABILITADA"
    assert _ids(orden) == [
        "PROC-REP-035",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]


def test_hp1_no_registra_nodos_de_revision(cliente):
    """HP1 sigue sin 055/065/068/075 (045 Si -> 070)."""
    orden_id = _crear_orden(cliente)
    orden = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    ).json()
    assert not {
        "PROC-REP-055",
        "PROC-REP-065",
        "PROC-REP-068",
        "PROC-REP-075",
    } & set(_ids(orden))


def test_factibilidad_fallida_luego_de_revision_no_habilita(tmp_path):
    """Sin stock, 090 no aprueba: 409 y NO se llega a PROC-REP-140.

    No se implementan 100/110/120/130 (EXC-REP-001/002). Como en
    ``definir_reparacion``, el comando falla antes de persistir: la Orden
    queda como estaba luego de PROC-REP-065.
    """
    _sembrar_catalogos(tmp_path, stock="0")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as cliente:
        orden_id = _crear_orden(cliente)
        _enviar(cliente, orden_id)
        _revisar(cliente, orden_id)

        respuesta = _definir(cliente, orden_id)
        assert respuesta.status_code == 409, respuesta.text

        orden = cliente.get(f"/api/orders/{orden_id}").json()
        assert orden["estado_workflow"] == "EN_REVISION"
        assert orden["reparaciones_detail"] == []
        assert _ids(orden)[-1] == "PROC-REP-065"
        assert "PROC-REP-140" not in _ids(orden)
        assert _codigos(orden) == ["DEFINIR_REPARACION_DESDE_REVISION"]
