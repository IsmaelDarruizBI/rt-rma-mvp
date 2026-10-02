"""VAR-REP-003 (ejecucion interrumpida) por HTTP.

    HTTP -> router -> application -> services -> repositories -> JSON

Interrumpir es la otra salida de PROC-REP-200: la Ejecucion queda
INTERRUMPIDO, el Detalle vuelve a DEFINIDO, el inventario se concilia con
lo realmente usado y la toma sigue activa. Continuar es una Ejecucion
NUEVA (mismo u otro tecnico, este ultimo tras liberar la Orden).
"""

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import RolUsuario, Usuario
from app.main import create_app
from app.storage.json.base import escribir_json_atomico
from tests import test_multidetalle as multi
from tests.fixtures.api_definicion import (
    definir_y_finalizar,
    finalizar_definicion,
)
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

TECNICO_B = "TECH-002"


def _agregar_tecnico_b(directorio) -> None:
    ruta = directorio / "catalogs" / "usuarios.json"
    usuarios = json.loads(ruta.read_text(encoding="utf-8"))
    usuarios.append(
        Usuario(
            id=TECNICO_B, nombre="Tecnico B", rol=RolUsuario.TECNICO
        ).model_dump(mode="json")
    )
    escribir_json_atomico(ruta, usuarios)


@pytest.fixture
def cliente(tmp_path):
    _sembrar_catalogos(tmp_path, stock="5")
    _agregar_tecnico_b(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def _stock(tmp_path, insumo_id=INSUMO) -> Decimal:
    ruta = tmp_path / "catalogs" / "insumos.json"
    for insumo in json.loads(ruta.read_text(encoding="utf-8")):
        if insumo["id"] == insumo_id:
            return Decimal(str(insumo["stock_fisico"]))
    raise AssertionError(insumo_id)


def _ids(orden: dict) -> list[str]:
    return [p["referencia_id"] for p in orden["historial"]]


def _codigos(orden: dict) -> list[str]:
    return [a["codigo"] for a in orden["acciones_disponibles"]]


def _hasta_ejecucion(cliente, tecnico=TECNICO) -> tuple[str, str, str]:
    """CLIENTE_EXTERNO: crear, definir, encolar, tomar, iniciar Detalle."""
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
    definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    return _desde_cola(cliente, orden_id, tecnico)


def _desde_cola(cliente, orden_id, tecnico=TECNICO) -> tuple[str, str, str]:
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": tecnico, "estacion_id": ESTACION},
    )
    detalle_id = cliente.get(f"/api/orders/{orden_id}").json()[
        "reparaciones_detail"
    ][0]["id"]
    orden = cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": tecnico},
    ).json()
    return orden_id, detalle_id, orden["ejecuciones"][-1]["id"]


def _interrumpir(cliente, orden_id, ejecucion_id, usuario=TECNICO, usado="1"):
    insumos = [{"insumo_id": INSUMO, "cantidad": usado}] if usado else []
    return cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/interrupt",
        json={
            "usuario_id": usuario,
            "insumos_utilizados": insumos,
            "observaciones": "Falta una herramienta.",
        },
    )


def _completar(cliente, orden_id, ejecucion_id, usuario=TECNICO, usado="1"):
    return cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={
            "usuario_id": usuario,
            "insumos_utilizados": [{"insumo_id": INSUMO, "cantidad": usado}],
        },
    )


# --- E2E principal ---------------------------------------------------------


def test_var_rep_003_interrupcion_de_punta_a_punta(cliente, tmp_path):
    orden_id, detalle_id, ejecucion_id = _hasta_ejecucion(cliente)
    antes = cliente.get(f"/api/orders/{orden_id}").json()
    assert "INTERRUMPIR_EJECUCION" in _codigos(antes)
    assert "COMPLETAR_EJECUCION" in _codigos(antes)

    respuesta = _interrumpir(cliente, orden_id, ejecucion_id)
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()

    assert _ids(orden)[-7:] == [
        "PROC-REP-181",
        "PROC-REP-174",
        "PROC-REP-185",
        "PROC-REP-190",
        "PROC-REP-200",
        "PROC-REP-210",
        "PROC-REP-211",
    ]
    paso_200 = next(
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-200"
    )
    assert paso_200["observacion"] == "Interrumpido"
    assert orden["historial"][-1]["observacion"] == "ABIERTA_TRABAJABLE"

    assert orden["estado_workflow"] == "EN_REPARACION"
    (detalle,) = orden["reparaciones_detail"]
    assert detalle["estado"] == "DEFINIDO"
    (ejecucion,) = orden["ejecuciones"]
    assert ejecucion["estado"] == "INTERRUMPIDO"
    assert ejecucion["fin"] is not None
    assert ejecucion["observaciones"] == "Falta una herramienta."
    assert ejecucion["insumos_utilizados"] == [
        {"insumo_id": INSUMO, "cantidad": "1"}
    ]
    (toma,) = orden["tomas"]
    assert toma["estado"] == "ACTIVA"
    assert _codigos(orden) == [
        "INICIAR_DETALLE",
        "LIBERAR_ORDEN",
        "REGISTRAR_PAGO",
    ]
    assert _stock(tmp_path) == Decimal("4")  # 1 usado de 5

    # La Ejecución ya es terminal: volver a cerrarla debe rechazarse.
    assert _interrumpir(cliente, orden_id, ejecucion_id).status_code == 409
    assert _completar(cliente, orden_id, ejecucion_id).status_code == 409
    assert detalle["id"] == detalle_id


def test_el_progreso_no_cambia_con_la_interrupcion(cliente):
    orden_id, _, ejecucion_id = _hasta_ejecucion(cliente)
    ruta_antes = [
        p["process_id"]
        for p in cliente.get(f"/api/orders/{orden_id}").json()["progreso"]
    ]

    orden = _interrumpir(cliente, orden_id, ejecucion_id).json()

    assert [p["process_id"] for p in orden["progreso"]] == ruta_antes
    assert "PROC-REP-200" in [
        p["process_id"] for p in orden["progreso"] if p["alcanzado"]
    ]


# --- Inventario ---


@pytest.mark.parametrize(
    ("usado", "stock"),
    [("", Decimal("5")), ("1", Decimal("4"))],
    ids=["sin_consumo", "consumo_total_de_lo_reservado"],
)
def test_el_stock_fisico_refleja_lo_realmente_utilizado(
    cliente, tmp_path, usado, stock
):
    """PROC-REP-210: lo usado se consume; lo reservado y no usado vuelve.

    El ledger no se expone en ``OrdenOut``: el detalle de CONSUMO y
    LIBERACION_RESERVA (incluido el consumo parcial) lo cubren los tests
    de service. Aqui: el stock fisico, y que no queden reservas activas
    bloqueando una Ejecucion nueva.
    """
    orden_id, detalle_id, ejecucion_id = _hasta_ejecucion(cliente)

    _interrumpir(cliente, orden_id, ejecucion_id, usado=usado)

    assert _stock(tmp_path) == stock
    nueva = cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": TECNICO},
    )
    assert nueva.status_code == 200, nueva.text


# --- Continuar: mismo tecnico ----------------------------------------------


def test_el_mismo_tecnico_continua_con_una_ejecucion_nueva(cliente):
    orden_id, detalle_id, eje1 = _hasta_ejecucion(cliente)
    _interrumpir(cliente, orden_id, eje1)

    orden = cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": TECNICO},
    ).json()

    primera, segunda = orden["ejecuciones"]
    assert primera["id"] == eje1
    assert primera["estado"] == "INTERRUMPIDO"
    assert segunda["id"] != eje1
    assert segunda["estado"] == "EN_PROGRESO"
    assert segunda["toma_orden_id"] == primera["toma_orden_id"]
    assert len(orden["tomas"]) == 1

    orden = _completar(cliente, orden_id, segunda["id"]).json()
    assert [e["estado"] for e in orden["ejecuciones"]] == [
        "INTERRUMPIDO",
        "COMPLETADO",
    ]
    assert orden["reparaciones_detail"][0]["estado"] == "COMPLETO"
    assert "APROBAR_CONTROL" in _codigos(orden)  # el flujo normal sigue


# --- Continuar: otro tecnico ----------------------------------------------


def test_otro_tecnico_continua_luego_de_liberar_la_orden(cliente):
    orden_id, detalle_id, eje1 = _hasta_ejecucion(cliente)
    _interrumpir(cliente, orden_id, eje1)

    liberada = cliente.post(
        f"/api/orders/{orden_id}/release", json={"usuario_id": TECNICO}
    )
    assert liberada.status_code == 200, liberada.text
    assert liberada.json()["estado_workflow"] == "EN_COLA"

    tomada = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO_B, "estacion_id": ESTACION},
    )
    assert tomada.status_code == 200, tomada.text
    orden = cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": TECNICO_B},
    ).json()

    toma_a, toma_b = orden["tomas"]
    assert (toma_a["usuario_id"], toma_a["estado"]) == (TECNICO, "CERRADA")
    assert (toma_b["usuario_id"], toma_b["estado"]) == (TECNICO_B, "ACTIVA")
    ejecucion_a, ejecucion_b = orden["ejecuciones"]
    assert (ejecucion_a["usuario_id"], ejecucion_a["estado"]) == (
        TECNICO,
        "INTERRUMPIDO",
    )
    assert (ejecucion_b["usuario_id"], ejecucion_b["estado"]) == (
        TECNICO_B,
        "EN_PROGRESO",
    )
    assert ejecucion_a["id"] == eje1
    assert ejecucion_a["toma_orden_id"] == toma_a["id"]
    assert ejecucion_b["toma_orden_id"] == toma_b["id"]


# --- Autorizacion y negativos -----------------------------------------------


def test_solo_el_tecnico_propietario_puede_interrumpir(cliente):
    orden_id, _, ejecucion_id = _hasta_ejecucion(cliente)

    for usuario in (TECNICO_B, RECEPCION, COORDINADOR, ADMINISTRADOR):
        respuesta = _interrumpir(cliente, orden_id, ejecucion_id, usuario)
        assert respuesta.status_code == 409, (usuario, respuesta.text)

    orden = cliente.get(f"/api/orders/{orden_id}").json()
    assert orden["ejecuciones"][0]["estado"] == "EN_PROGRESO"


def test_interrumpir_una_ejecucion_inexistente_devuelve_404(cliente):
    orden_id, _, _ = _hasta_ejecucion(cliente)
    assert _interrumpir(cliente, orden_id, "EJE-NO-EXISTE").status_code == 404


def test_interrumpir_una_ejecucion_completada_devuelve_409(cliente):
    orden_id, _, ejecucion_id = _hasta_ejecucion(cliente)
    _completar(cliente, orden_id, ejecucion_id)
    assert _interrumpir(cliente, orden_id, ejecucion_id).status_code == 409


def test_complete_conserva_su_contrato(cliente):
    """HP-REP-001: completar sigue dando COMPLETADO / COMPLETO."""
    orden_id, _, ejecucion_id = _hasta_ejecucion(cliente)
    orden = _completar(cliente, orden_id, ejecucion_id).json()

    assert orden["ejecuciones"][0]["estado"] == "COMPLETADO"
    assert orden["reparaciones_detail"][0]["estado"] == "COMPLETO"
    assert orden["tomas"][0]["estado"] == "CERRADA"  # BR-REP-018: COMPLETA
    assert "INTERRUMPIR_EJECUCION" not in _codigos(orden)


# --- Origenes y Multi-Detalle ----------------------------------------------


def test_la_interrupcion_funciona_en_rt_interno(cliente):
    orden_id = _crear_orden_rt(cliente)
    definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    _, _, ejecucion_id = _desde_cola(cliente, orden_id)

    orden = _interrumpir(cliente, orden_id, ejecucion_id).json()

    assert orden["origen"] == "RT_INTERNO"
    assert orden["ejecuciones"][0]["estado"] == "INTERRUMPIDO"
    assert _ids(orden)[-3:] == ["PROC-REP-200", "PROC-REP-210", "PROC-REP-211"]
    assert _codigos(orden)[:2] == ["INICIAR_DETALLE", "LIBERAR_ORDEN"]


def test_la_interrupcion_funciona_en_garantia_rma(cliente):
    from tests.test_api_hp_rep_003 import _garantia_definida, _orden_entregada

    origen = _orden_entregada(cliente)
    garantia = _garantia_definida(cliente, origen["id"]).json()
    _, _, ejecucion_id = _desde_cola(cliente, garantia["id"])

    orden = _interrumpir(cliente, garantia["id"], ejecucion_id).json()

    assert orden["origen"] == "RMA_GARANTIA_REPARACION"
    assert orden["ejecuciones"][0]["estado"] == "INTERRUMPIDO"
    assert orden["reparaciones_detail"][0]["estado"] == "DEFINIDO"
    assert orden["reparaciones_detail"][0]["detalle_origen_id"] == "DET-001"


def test_multidetalle_interrumpir_uno_ofrece_los_trabajables(tmp_path):
    multi._sembrar_catalogos(tmp_path)
    insumos = tmp_path / "catalogs" / "insumos.json"
    datos = json.loads(insumos.read_text(encoding="utf-8"))
    for insumo in datos:
        insumo["stock_fisico"] = "5"
    escribir_json_atomico(insumos, datos)

    with TestClient(create_app(Settings(data_dir=tmp_path))) as cliente:
        orden_id = multi._crear_orden(cliente)
        for tipo in (multi.TIPO_BATERIA, multi.TIPO_PANTALLA):
            cliente.post(
                f"/api/orders/{orden_id}/details",
                json={
                    "usuario_id": multi.RECEPCION,
                    "tipo_reparacion_id": tipo,
                },
            )
        finalizar_definicion(cliente, orden_id, multi.RECEPCION)
        cliente.post(
            f"/api/orders/{orden_id}/queue",
            json={"usuario_id": multi.COORDINADOR, "prioridad": 1},
        )
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": multi.TECNICO, "estacion_id": multi.ESTACION},
        )
        det1, det2 = [
            d["id"]
            for d in cliente.get(f"/api/orders/{orden_id}").json()[
                "reparaciones_detail"
            ]
        ]
        orden = cliente.post(
            f"/api/orders/{orden_id}/details/{det1}/start",
            json={"usuario_id": multi.TECNICO},
        ).json()
        ejecucion_id = orden["ejecuciones"][0]["id"]

        orden = cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion_id}/interrupt",
            json={
                "usuario_id": multi.TECNICO,
                "insumos_utilizados": [],
                "observaciones": "Cambio de prioridad.",
            },
        ).json()

        assert orden["historial"][-1]["observacion"] == "ABIERTA_TRABAJABLE"
        trabajables = [
            a["detalle_id"]
            for a in orden["acciones_disponibles"]
            if a["codigo"] == "INICIAR_DETALLE"
        ]
        assert trabajables == [det1, det2]  # puede elegir otro (PROC-REP-181)
        otro = cliente.post(
            f"/api/orders/{orden_id}/details/{det2}/start",
            json={"usuario_id": multi.TECNICO},
        )
        assert otro.status_code == 200, otro.text
        assert [e["estado"] for e in otro.json()["ejecuciones"]] == [
            "INTERRUMPIDO",
            "EN_PROGRESO",
        ]
