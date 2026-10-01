"""EXC-REP-002 (recursos insuficientes, resuelto por override) por HTTP.

    HTTP -> router -> application -> services -> repositories -> JSON

Un Coordinador RMA fuerza UN Detalle bloqueado desde PROC-REP-100
(110 Si -> 130 -> 140). El override solo registra la autorizacion; la
reserva (185) y el consumo (210) posteriores pueden dejar el disponible y el
stock fisico negativos para ese Detalle.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests import test_multidetalle as multi
from tests.test_api_exc_rep_001 import (
    _cliente,
    _cliente_multi,
    _codigos,
    _definir,
    _definir_dos,
    _esperar,
    _fijar_stock,
    _ids,
    _stock,
)
from tests.test_api_hp_rep_002 import (
    ADMINISTRADOR,
    COORDINADOR,
    ESTACION,
    INSUMO,
    RECEPCION,
    TECNICO,
    _crear_orden_rt,
)
from tests.test_api_hp_rep_003 import _orden_entregada
from tests.test_api_var_rep_001_002 import _crear_orden as _crear_orden_cliente

MOTIVO = "Cliente urgente; el repuesto llega manana."


def _override(
    cliente: TestClient,
    orden_id,
    detalle_id="DET-001",
    usuario=COORDINADOR,
    motivo=MOTIVO,
):
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/resources/override",
        json={"usuario_id": usuario, "motivo": motivo},
    )


def _hasta_100(cliente) -> str:
    orden_id = _crear_orden_cliente(cliente)
    assert (
        _definir(cliente, orden_id).json()["current_process"] == "PROC-REP-100"
    )
    return orden_id


def _tomar(cliente, orden_id) -> None:
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    )


def _iniciar(cliente, orden_id):
    return cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/start",
        json={"usuario_id": TECNICO},
    )


# --- Flujo y trazabilidad ---


def test_cliente_externo_override_090_ninguno_100_110_si_130_140(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _hasta_100(cliente)
        orden = cliente.get(f"/api/orders/{orden_id}").json()
        # Conviven las dos decisiones de PROC-REP-110.
        assert _codigos(orden)[:2] == ["ESPERAR_RECURSOS", "OVERRIDE_RECURSOS"]
        accion = next(
            a
            for a in orden["acciones_disponibles"]
            if a["codigo"] == "OVERRIDE_RECURSOS"
        )
        assert accion["detalle_id"] == "DET-001"
        assert accion["roles"] == ["COORDINADOR_RMA"]
        assert accion["requiere_actor"] is True

        respuesta = _override(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()

        assert _ids(orden)[-6:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-100",
            "PROC-REP-110",
            "PROC-REP-130",
            "PROC-REP-140",
        ]
        observaciones_090 = [
            p["observacion"]
            for p in orden["historial"]
            if p["referencia_id"] == "PROC-REP-090"
        ]
        assert observaciones_090 == ["Ninguno trabajable"]  # sin 090 "Si"
        paso_110, paso_130 = orden["historial"][-3:-1]
        assert paso_110["observacion"] == "Si"
        assert paso_110["usuario_id"] == COORDINADOR
        assert paso_130["usuario_id"] == COORDINADOR
        assert paso_130["reparacion_detail_id"] == "DET-001"
        assert MOTIVO in paso_130["observacion"]
        assert "Validacion ignorada" in paso_130["observacion"]
        assert orden["estado_workflow"] == "HABILITADA"
        assert orden["current_process"] == "PROC-REP-140"
        assert orden["reparaciones_detail"][0]["condicion"] == "SIN_BLOQUEO"
        assert "ENCOLAR" in _codigos(orden)
        # 130 no reserva ni descuenta stock.
        assert _stock(tmp_path, INSUMO) == Decimal("0")


@pytest.mark.parametrize("usuario", [RECEPCION, TECNICO, ADMINISTRADOR])
def test_solo_el_coordinador_rma_puede_hacer_el_override(tmp_path, usuario):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _hasta_100(cliente)
        assert _override(cliente, orden_id, usuario=usuario).status_code == 409
        orden = cliente.get(f"/api/orders/{orden_id}").json()
        assert orden["current_process"] == "PROC-REP-100"
        assert "PROC-REP-130" not in _ids(orden)


def test_el_motivo_es_obligatorio(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _hasta_100(cliente)
        assert _override(cliente, orden_id, motivo="").status_code == 422
        sin_motivo = cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/resources/override",
            json={"usuario_id": COORDINADOR},
        )
        assert sin_motivo.status_code == 422
        assert _override(cliente, orden_id, motivo="   ").status_code == 409
        assert "PROC-REP-130" not in _ids(
            cliente.get(f"/api/orders/{orden_id}").json()
        )


def test_el_override_valida_orden_detalle_y_punto_del_proceso(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        assert _override(cliente, "OR-999999").status_code == 404

        orden_id = _crear_orden_cliente(cliente)
        assert _override(cliente, orden_id).status_code == 409  # antes de 100

        _definir(cliente, orden_id)
        assert _override(cliente, orden_id, "DET-999").status_code == 404

        _esperar(cliente, orden_id)  # en 120: ya no es el punto de 110
        assert _override(cliente, orden_id).status_code == 409

        _fijar_stock(tmp_path, **{INSUMO: 5})
        cliente.post(f"/api/orders/{orden_id}/resources/revalidate")  # 140
        assert _override(cliente, orden_id).status_code == 409  # no bloqueado


def test_la_rama_110_no_hacia_120_no_tiene_regresion(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _hasta_100(cliente)
        orden = _esperar(cliente, orden_id).json()
        assert _ids(orden)[-2:] == ["PROC-REP-110", "PROC-REP-120"]
        assert orden["historial"][-2]["observacion"] == "No"
        assert "OVERRIDE_RECURSOS" not in _codigos(orden)


# --- Multi-Detalle ---


def test_multidetalle_override_de_uno_habilita_y_solo_ese_se_inicia(tmp_path):
    with _cliente_multi(tmp_path, a="0", b="0") as cliente:
        orden_id = multi._crear_orden(cliente)
        orden = _definir_dos(cliente, orden_id).json()
        assert orden["current_process"] == "PROC-REP-100"
        overrides = [
            a["detalle_id"]
            for a in orden["acciones_disponibles"]
            if a["codigo"] == "OVERRIDE_RECURSOS"
        ]
        assert overrides == ["DET-001", "DET-002"]

        respuesta = _override(cliente, orden_id, "DET-001", COORDINADOR)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert orden["estado_workflow"] == "HABILITADA"
        assert [d["condicion"] for d in orden["reparaciones_detail"]] == [
            "SIN_BLOQUEO",
            "BLOQUEADO_POR_RECURSOS",
        ]

        cliente.post(
            f"/api/orders/{orden_id}/queue",
            json={"usuario_id": multi.COORDINADOR, "prioridad": 1},
        )
        orden = cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": multi.TECNICO, "estacion_id": multi.ESTACION},
        ).json()
        iniciables = [
            a["detalle_id"]
            for a in orden["acciones_disponibles"]
            if a["codigo"] == "INICIAR_DETALLE"
        ]
        assert iniciables == ["DET-001"]
        directo = cliente.post(
            f"/api/orders/{orden_id}/details/DET-002/start",
            json={"usuario_id": multi.TECNICO},
        )
        assert directo.status_code == 409, directo.text
        valido = cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": multi.TECNICO},
        )
        assert valido.status_code == 200, valido.text


# --- 185 y 210: stock negativo solo con override ---


def test_con_override_se_reserva_y_se_consume_dejando_stock_negativo(
    tmp_path,
):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _hasta_100(cliente)
        _override(cliente, orden_id)
        _tomar(cliente, orden_id)

        # 185: reserva aunque el stock sea 0; el stock fisico no se toca.
        iniciada = _iniciar(cliente, orden_id)
        assert iniciada.status_code == 200, iniciada.text
        ejecucion = iniciada.json()["ejecuciones"][0]
        assert ejecucion["estado"] == "EN_PROGRESO"
        assert _stock(tmp_path, INSUMO) == Decimal("0")

        # 210: el CONSUMO baja el stock fisico a -1.
        completada = cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion['id']}/complete",
            json={
                "usuario_id": TECNICO,
                "insumos_utilizados": [{"insumo_id": INSUMO, "cantidad": "1"}],
            },
        )
        assert completada.status_code == 200, completada.text
        assert _stock(tmp_path, INSUMO) == Decimal("-1")


def test_interrumpir_con_override_sin_usar_nada_no_toca_el_stock(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _hasta_100(cliente)
        _override(cliente, orden_id)
        _tomar(cliente, orden_id)
        ejecucion_id = _iniciar(cliente, orden_id).json()["ejecuciones"][0][
            "id"
        ]

        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion_id}/interrupt",
            json={"usuario_id": TECNICO, "insumos_utilizados": []},
        )

        # LIBERACION_RESERVA no descuenta: el stock sigue en 0.
        assert _stock(tmp_path, INSUMO) == Decimal("0")


def test_sin_override_iniciar_con_stock_insuficiente_sigue_siendo_409(
    tmp_path,
):
    """EXC-REP-003 (reserva fallida) sigue sin implementarse."""
    with _cliente(tmp_path, stock="1") as cliente:
        primera = _crear_orden_cliente(cliente)
        _definir(cliente, primera)
        segunda = _crear_orden_cliente(cliente)
        _definir(cliente, segunda)  # ambas pasan 080 (solo consulta)
        _tomar(cliente, primera)
        _tomar(cliente, segunda)

        assert _iniciar(cliente, primera).status_code == 200
        perdedora = _iniciar(cliente, segunda)
        assert perdedora.status_code == 409
        assert perdedora.json()["error"]["codigo"] == "RECURSO_NO_DISPONIBLE"


# --- Origenes ---


def test_rt_interno_override_sin_comprobante_ni_pagos(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _crear_orden_rt(cliente)
        orden = _definir(cliente, orden_id).json()
        assert orden["current_process"] == "PROC-REP-100"
        assert "OVERRIDE_RECURSOS" in _codigos(orden)

        orden = _override(cliente, orden_id).json()

        assert orden["estado_workflow"] == "HABILITADA"
        assert "PROC-REP-060" not in _ids(orden)
        assert orden["pagos"] == []


def test_garantia_rma_override_conserva_origen_y_no_toca_la_orden_origen(
    tmp_path,
):
    with _cliente(tmp_path, stock="5") as cliente:
        origen = _orden_entregada(cliente)
        foto = cliente.get(f"/api/orders/{origen['id']}").json()
        _fijar_stock(tmp_path, **{INSUMO: 0})
        garantia = cliente.post(
            f"/api/orders/{origen['id']}/details/DET-001/warranty-rma",
            json={"usuario_id": RECEPCION},
        ).json()
        assert garantia["current_process"] == "PROC-REP-100"

        orden = _override(cliente, garantia["id"]).json()

        assert orden["estado_workflow"] == "HABILITADA"
        assert orden["orden_origen_id"] == origen["id"]
        assert orden["detalles_origen_ids"] == ["DET-001"]
        assert (
            orden["reparaciones_detail"][0]["detalle_origen_id"] == "DET-001"
        )
        assert cliente.get(f"/api/orders/{origen['id']}").json() == foto
