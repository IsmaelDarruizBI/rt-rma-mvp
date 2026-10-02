"""EXC-REP-002 (recursos insuficientes, resuelto por override) por HTTP.

    HTTP -> router -> application -> services -> repositories -> JSON

Un Coordinador RMA autoriza UN Detalle bloqueado por recursos: capacidad
transversal (ACC-REP-049), con la Orden detenida en PROC-REP-100 (y ahi
continua 110 Si -> 130 -> 140) o con factibilidad parcial (Orden
habilitada, en cola, tomada o en reparacion, sin reiniciar nada). El
override solo registra la autorizacion; la reserva (185) y el consumo (210)
posteriores pueden dejar el disponible y el stock fisico negativos para ese
Detalle.
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
from tests.test_api_hp_rep_003 import _garantia_definida, _orden_entregada
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

        # La autorizacion es la capacidad transversal (ACC-REP-049); en el
        # circuito de 100 el proceso continua 110 Si -> 130 -> 140.
        assert _ids(orden)[-7:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-100",
            "ACC-REP-049",
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
        autorizacion, paso_110, paso_130 = orden["historial"][-4:-1]
        assert autorizacion["process_id"] is None
        assert autorizacion["usuario_id"] == COORDINADOR
        assert autorizacion["reparacion_detail_id"] == "DET-001"
        assert MOTIVO in autorizacion["observacion"]
        assert "Validacion ignorada" in autorizacion["observacion"]
        assert paso_110["observacion"] == "Si"
        assert paso_110["usuario_id"] == COORDINADOR
        assert paso_130["usuario_id"] == COORDINADOR
        assert paso_130["reparacion_detail_id"] == "DET-001"
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
        # Sin Detalles no hay Detalle que autorizar.
        assert _override(cliente, orden_id).status_code == 404

        _definir(cliente, orden_id)
        assert _override(cliente, orden_id, "DET-999").status_code == 404

        _fijar_stock(tmp_path, **{INSUMO: 5})
        _esperar(cliente, orden_id)
        cliente.post(f"/api/orders/{orden_id}/resources/revalidate")  # 140
        antes = cliente.get(f"/api/orders/{orden_id}").json()
        assert _override(cliente, orden_id).status_code == 409  # no bloqueado
        assert cliente.get(f"/api/orders/{orden_id}").json() == antes


def test_la_rama_110_no_hacia_120_no_tiene_regresion(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _hasta_100(cliente)
        orden = _esperar(cliente, orden_id).json()
        assert _ids(orden)[-2:] == ["PROC-REP-110", "PROC-REP-120"]
        assert orden["historial"][-2]["observacion"] == "No"
        # El override es transversal: el Detalle sigue bloqueado, asi que
        # la capacidad sigue publicada tambien en 120.
        assert _codigos(orden) == [
            "REVALIDAR_RECURSOS",
            "OVERRIDE_RECURSOS",
            "REGISTRAR_PAGO",
        ]


def test_override_en_120_autoriza_el_detalle_sin_mover_el_proceso(tmp_path):
    """En 120 la autorizacion no recorre 110/130: espera la revalidacion."""
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _hasta_100(cliente)
        _esperar(cliente, orden_id)

        orden = _override(cliente, orden_id).json()

        assert orden["current_process"] == "PROC-REP-120"
        assert _ids(orden)[-3:] == [
            "PROC-REP-110",
            "PROC-REP-120",
            "ACC-REP-049",
        ]
        assert "PROC-REP-130" not in _ids(orden)
        assert orden["reparaciones_detail"][0]["condicion"] == "SIN_BLOQUEO"
        assert "OVERRIDE_RECURSOS" not in _codigos(orden)
        assert _stock(tmp_path, INSUMO) == Decimal("0")

        # La revalidacion (evento de sistema existente) no lo rebloquea.
        orden = cliente.post(
            f"/api/orders/{orden_id}/resources/revalidate"
        ).json()
        assert orden["estado_workflow"] == "HABILITADA"
        assert _ids(orden)[-3:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-140",
        ]
        assert _stock(tmp_path, INSUMO) == Decimal("0")


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


def test_sin_override_iniciar_con_stock_insuficiente_registra_186(tmp_path):
    """Sin override rige EXC-REP-003: 200 con 185 fallida -> 186 -> 211."""
    with _cliente(tmp_path, stock="1") as cliente:
        primera = _crear_orden_cliente(cliente)
        _definir(cliente, primera)
        segunda = _crear_orden_cliente(cliente)
        _definir(cliente, segunda)  # ambas pasan 080 (solo consulta)
        _tomar(cliente, primera)
        _tomar(cliente, segunda)

        assert _iniciar(cliente, primera).status_code == 200
        perdedora = _iniciar(cliente, segunda)
        assert perdedora.status_code == 200, perdedora.text
        orden = perdedora.json()
        assert _ids(orden)[-4:] == [
            "PROC-REP-185",
            "PROC-REP-186",
            "PROC-REP-211",
            "PROC-REP-120",
        ]
        assert orden["ejecuciones"] == []


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
        garantia = _garantia_definida(cliente, origen["id"]).json()
        assert garantia["current_process"] == "PROC-REP-100"

        orden = _override(cliente, garantia["id"]).json()

        assert orden["estado_workflow"] == "HABILITADA"
        assert orden["orden_origen_id"] == origen["id"]
        assert orden["detalles_origen_ids"] == ["DET-001"]
        assert (
            orden["reparaciones_detail"][0]["detalle_origen_id"] == "DET-001"
        )
        assert cliente.get(f"/api/orders/{origen['id']}").json() == foto


# --- Override transversal: factibilidad parcial con la Orden tomada ---


def _parcial_tomada_con_ejecucion(cliente) -> str:
    """DET-001 bloqueado; DET-002 trabajable y en curso (Orden tomada)."""
    orden_id = multi._crear_orden(cliente)
    orden = _definir_dos(cliente, orden_id).json()
    assert orden["estado_workflow"] == "HABILITADA"
    assert [d["condicion"] for d in orden["reparaciones_detail"]] == [
        "BLOQUEADO_POR_RECURSOS",
        "SIN_BLOQUEO",
    ]
    _tomar(cliente, orden_id)
    orden = cliente.post(
        f"/api/orders/{orden_id}/details/DET-002/start",
        json={"usuario_id": TECNICO},
    ).json()
    assert orden["estado_workflow"] == "EN_REPARACION"
    return orden_id


def test_override_con_factibilidad_parcial_y_orden_tomada_no_reinicia(
    tmp_path,
):
    with _cliente_multi(tmp_path, a="0", b="1") as cliente:
        orden_id = _parcial_tomada_con_ejecucion(cliente)
        antes = cliente.get(f"/api/orders/{orden_id}").json()
        stock_antes = {i: _stock(tmp_path, i) for i in ("INS-001", "INS-002")}
        (accion,) = [
            a
            for a in antes["acciones_disponibles"]
            if a["codigo"] == "OVERRIDE_RECURSOS"
        ]
        assert accion["detalle_id"] == "DET-001"
        assert accion["roles"] == ["COORDINADOR_RMA"]

        respuesta = _override(cliente, orden_id, "DET-001")
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()

        # Solo se agrega la autorizacion: ni 110/130 ni vuelta a 140.
        assert _ids(orden) == _ids(antes) + ["ACC-REP-049"]
        autorizacion = orden["historial"][-1]
        assert autorizacion["process_id"] is None
        assert autorizacion["usuario_id"] == COORDINADOR
        assert autorizacion["reparacion_detail_id"] == "DET-001"
        assert MOTIVO in autorizacion["observacion"]
        # Workflow, punto del proceso, toma y Ejecucion en curso intactos.
        for campo in (
            "estado_workflow",
            "current_process",
            "tomas",
            "ejecuciones",
            "pagos",
            "documentos",
        ):
            assert orden[campo] == antes[campo], campo
        det1, det2 = orden["reparaciones_detail"]
        assert det1["condicion"] == "SIN_BLOQUEO"
        assert det1["estado"] == "DEFINIDO"
        assert det2 == antes["reparaciones_detail"][1]
        # No reserva ni descuenta stock.
        assert {i: _stock(tmp_path, i) for i in stock_antes} == stock_antes
        assert "OVERRIDE_RECURSOS" not in _codigos(orden)

        # La autorizacion queda vigente: al terminar DET-002, la misma toma
        # sigue y DET-001 se inicia sin reserva fallida (BR-REP-003).
        orden = cliente.post(
            f"/api/orders/{orden_id}/executions/"
            f"{orden['ejecuciones'][0]['id']}/complete",
            json={
                "usuario_id": TECNICO,
                "insumos_utilizados": [
                    {"insumo_id": "INS-002", "cantidad": "1"}
                ],
            },
        ).json()
        paso_211 = next(
            p
            for p in reversed(orden["historial"])
            if p["referencia_id"] == "PROC-REP-211"
        )
        assert paso_211["observacion"] == "ABIERTA_TRABAJABLE"
        assert [t["estado"] for t in orden["tomas"]] == ["ACTIVA"]
        respuesta = cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": TECNICO},
        )
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert orden["estado_workflow"] == "EN_REPARACION"
        assert _ids(orden)[-1] == "PROC-REP-185"
        assert "PROC-REP-186" not in _ids(orden)
        assert _ids(orden).count("PROC-REP-140") == 1


@pytest.mark.parametrize("usuario", [RECEPCION, TECNICO, ADMINISTRADOR])
def test_override_parcial_valida_y_no_deja_efectos(tmp_path, usuario):
    with _cliente_multi(tmp_path, a="0", b="1") as cliente:
        orden_id = _parcial_tomada_con_ejecucion(cliente)
        antes = cliente.get(f"/api/orders/{orden_id}").json()

        assert _override(cliente, orden_id, usuario=usuario).status_code == 409
        assert _override(cliente, orden_id, motivo="  ").status_code == 409
        # DET-002 esta en curso, no bloqueado por recursos.
        assert _override(cliente, orden_id, "DET-002").status_code == 409
        assert _override(cliente, orden_id, "DET-999").status_code == 404

        assert cliente.get(f"/api/orders/{orden_id}").json() == antes
