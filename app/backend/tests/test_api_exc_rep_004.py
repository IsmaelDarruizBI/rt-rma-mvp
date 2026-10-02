"""EXC-REP-004 (Detalle requiere revision tecnica posterior) por HTTP.

    HTTP -> router -> application -> services -> repositories -> JSON

POST .../executions/{id}/requires-redefinition   PROC-REP-200 (3er resultado)
POST .../details/{id}/technical-review           PROC-REP-126 (Tecnico)
POST .../details/{id}/redefine                   PROC-REP-127 -> 080 (Recep.)
"""

from decimal import Decimal

import pytest

from tests import test_multidetalle as multi
from tests.test_api_exc_rep_001 import (
    _cliente,
    _cliente_multi,
    _codigos,
    _fijar_stock,
    _ids,
    _stock,
)
from tests.test_api_exc_rep_002 import _override, _tomar
from tests.test_api_hp_rep_002 import (
    INSUMO,
    RECEPCION,
    TECNICO,
    _crear_orden_rt,
)
from tests.test_api_hp_rep_003 import _orden_entregada

MOTIVO = "La placa esta danada: no alcanza con cambiar la bateria."


def _sin_pago(orden: dict) -> list[str]:
    return [c for c in _codigos(orden) if c != "REGISTRAR_PAGO"]


def _orden(cliente, orden_id) -> dict:
    return cliente.get(f"/api/orders/{orden_id}").json()


def _detalle(orden: dict, detalle_id="DET-001") -> dict:
    return next(
        d for d in orden["reparaciones_detail"] if d["id"] == detalle_id
    )


def _encolar_y_tomar(cliente, orden_id) -> None:
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": multi.COORDINADOR, "prioridad": 1},
    )
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": multi.TECNICO, "estacion_id": multi.ESTACION},
    )
    assert respuesta.status_code == 200, respuesta.text


def _iniciar(cliente, orden_id, detalle_id="DET-001") -> str:
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": multi.TECNICO},
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["ejecuciones"][-1]["id"]


def _requiere(cliente, orden_id, ejecucion_id, **cuerpo):
    datos = {
        "usuario_id": multi.TECNICO,
        "insumos_utilizados": [],
        "motivo": MOTIVO,
    }
    datos.update(cuerpo)
    return cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}"
        "/requires-redefinition",
        json=datos,
    )


def _revisar(cliente, orden_id, detalle_id="DET-001", usuario=None, **c):
    datos = {
        "usuario_id": usuario or multi.TECNICO,
        "resultado": "Placa con corrosion",
    }
    datos.update(c)
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/technical-review",
        json=datos,
    )


def _redefinir(
    cliente, orden_id, tipo=None, detalle_id="DET-001", usuario=None
):
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/redefine",
        json={
            "usuario_id": usuario or multi.RECEPCION,
            "tipo_reparacion_id": tipo or multi.TIPO_PANTALLA,
        },
    )


def _completar(cliente, orden_id, ejecucion_id, insumo):
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={
            "usuario_id": multi.TECNICO,
            "insumos_utilizados": [{"insumo_id": insumo, "cantidad": "1"}],
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _hasta_en_ejecucion(tmp_path, a="2", b="2"):
    """Un Detalle (bateria) en ejecucion. Devuelve (cliente, orden, ejec.)."""
    cliente = _cliente_multi(tmp_path, a=a, b=b)
    orden_id = multi._crear_orden(cliente)
    definida = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={
            "usuario_id": multi.RECEPCION,
            "tipo_reparacion_id": multi.TIPO_BATERIA,
        },
    ).json()
    assert definida["estado_workflow"] == "HABILITADA"
    _encolar_y_tomar(cliente, orden_id)
    return cliente, orden_id, _iniciar(cliente, orden_id)


def _hasta_125(tmp_path, **stock):
    cliente, orden_id, ejecucion_id = _hasta_en_ejecucion(tmp_path, **stock)
    respuesta = _requiere(cliente, orden_id, ejecucion_id)
    assert respuesta.status_code == 200, respuesta.text
    return cliente, orden_id


# --- Caso B: unico Detalle -> 125 -> 126 -> 127 -> 080 -> reingreso ---


def test_caso_b_e2e_requiere_redefinicion_125_126_127_080_y_reingreso(
    tmp_path,
):
    cliente, orden_id, ejecucion_id = _hasta_en_ejecucion(tmp_path)
    with cliente:
        respuesta = _requiere(
            cliente,
            orden_id,
            ejecucion_id,
            insumos_utilizados=[{"insumo_id": "INS-001", "cantidad": "1"}],
            observaciones="Se abrio el equipo",
        )
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()

        assert _ids(orden)[-5:] == [
            "PROC-REP-190",
            "PROC-REP-200",
            "PROC-REP-210",
            "PROC-REP-211",
            "PROC-REP-125",
        ]
        paso_200 = orden["historial"][-4]
        assert paso_200["observacion"] == "Requiere redefinicion"
        assert orden["historial"][-2]["observacion"] == "REQUIERE_REVISION"
        (ejecucion,) = orden["ejecuciones"]
        assert ejecucion["estado"] == "INTERRUMPIDO"
        assert ejecucion["motivo_redefinicion"] == MOTIVO
        assert ejecucion["observaciones"] == "Se abrio el equipo"
        detalle = _detalle(orden)
        assert (detalle["estado"], detalle["condicion"]) == (
            "DEFINIDO",
            "REQUIERE_DEFINICION",
        )
        assert [t["estado"] for t in orden["tomas"]] == ["CERRADA"]
        assert orden["estado_workflow"] == "EN_REPARACION"
        assert orden["current_process"] == "PROC-REP-125"
        assert _sin_pago(orden) == ["REVISAR_DETALLE"]
        # 210: lo usado se consumio (stock fisico 2 -> 1).
        assert _stock(tmp_path, "INS-001") == Decimal("1")

        orden = _revisar(cliente, orden_id).json()
        assert orden["historial"][-1]["referencia_id"] == "PROC-REP-126"
        assert orden["historial"][-1]["usuario_id"] == multi.TECNICO
        assert _detalle(orden)["tipo_reparacion_id"] == multi.TIPO_BATERIA
        assert _sin_pago(orden) == ["REDEFINIR_DETALLE"]

        respuesta = _redefinir(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert _ids(orden)[-4:] == [
            "PROC-REP-127",
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-140",
        ]
        detalle = _detalle(orden)
        assert detalle["id"] == "DET-001"
        assert detalle["tipo_reparacion_id"] == multi.TIPO_PANTALLA
        assert detalle["condicion"] == "SIN_BLOQUEO"
        (anterior,) = detalle["definiciones_anteriores"]
        assert anterior["tipo_reparacion_id"] == multi.TIPO_BATERIA
        assert anterior["usuario_id"] == multi.RECEPCION
        assert orden["estado_workflow"] == "HABILITADA"

        # Reingreso al flujo normal: 150 -> 170 -> tomar -> iniciar.
        _encolar_y_tomar(cliente, orden_id)
        nueva = _iniciar(cliente, orden_id)
        orden = _completar(cliente, orden_id, nueva, "INS-002")
        assert orden["historial"][-1]["observacion"] == "COMPLETA"
        assert len(orden["ejecuciones"]) == 2

        ruta = [p["process_id"] for p in orden["progreso"]]
        i = ruta.index("PROC-REP-211")
        assert ruta[i + 1 : i + 4] == [
            "PROC-REP-125",
            "PROC-REP-126",
            "PROC-REP-127",
        ]


def test_caso_b_sin_stock_tras_127_va_a_100_y_admite_override(tmp_path):
    cliente, orden_id = _hasta_125(tmp_path, a="2", b="0")
    with cliente:
        _revisar(cliente, orden_id)
        orden = _redefinir(cliente, orden_id).json()  # pantalla sin stock

        assert _ids(orden)[-4:] == [
            "PROC-REP-127",
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-100",
        ]
        assert orden["historial"][-2]["observacion"] == "Ninguno trabajable"
        assert _detalle(orden)["condicion"] == "BLOQUEADO_POR_RECURSOS"
        assert "OVERRIDE_RECURSOS" in _codigos(orden)

        forzada = _override(cliente, orden_id)
        assert forzada.status_code == 200, forzada.text
        assert forzada.json()["estado_workflow"] == "HABILITADA"


# --- Caso A: Multi-Detalle ---


def test_caso_a_multidetalle_continua_b_y_despues_entra_a_125(tmp_path):
    with _cliente_multi(tmp_path, a="2", b="2") as cliente:
        orden_id = multi._crear_orden(cliente)
        for tipo, finalizar in (
            (multi.TIPO_BATERIA, False),
            (multi.TIPO_PANTALLA, True),
        ):
            cliente.post(
                f"/api/orders/{orden_id}/details",
                json={
                    "usuario_id": multi.RECEPCION,
                    "tipo_reparacion_id": tipo,
                    "finalizar_definicion": finalizar,
                },
            )
        _encolar_y_tomar(cliente, orden_id)
        ejecucion_a = _iniciar(cliente, orden_id, "DET-001")

        orden = _requiere(cliente, orden_id, ejecucion_a).json()

        assert orden["historial"][-1]["referencia_id"] == "PROC-REP-211"
        assert orden["historial"][-1]["observacion"] == "ABIERTA_TRABAJABLE"
        assert "PROC-REP-125" not in _ids(orden)
        assert [t["estado"] for t in orden["tomas"]] == ["ACTIVA"]
        assert orden["estado_workflow"] == "EN_REPARACION"
        assert _detalle(orden, "DET-001")["condicion"] == (
            "REQUIERE_DEFINICION"
        )
        assert _sin_pago(orden) == ["INICIAR_DETALLE", "LIBERAR_ORDEN"]
        assert orden["acciones_disponibles"][0]["detalle_id"] == "DET-002"

        ejecucion_b = _iniciar(cliente, orden_id, "DET-002")
        orden = _orden(cliente, orden_id)
        assert _ids(orden)[-4:-2] == ["PROC-REP-212", "PROC-REP-181"]
        orden = _completar(cliente, orden_id, ejecucion_b, "INS-002")

        assert _ids(orden)[-2:] == ["PROC-REP-211", "PROC-REP-125"]
        assert [t["estado"] for t in orden["tomas"]] == ["CERRADA"]
        revisar = [
            a
            for a in orden["acciones_disponibles"]
            if a["codigo"] == "REVISAR_DETALLE"
        ]
        assert [a["detalle_id"] for a in revisar] == ["DET-001"]


# --- requires-redefinition: errores ---


def test_requires_redefinition_404_409_422(tmp_path):
    cliente, orden_id, ejecucion_id = _hasta_en_ejecucion(tmp_path)
    with cliente:
        assert _requiere(cliente, "OR-999999", ejecucion_id).status_code == (
            404
        )
        assert _requiere(cliente, orden_id, "EJE-999").status_code == 404
        assert (
            _requiere(
                cliente, orden_id, ejecucion_id, usuario_id=multi.RECEPCION
            ).status_code
            == 409
        )
        assert (
            _requiere(
                cliente, orden_id, ejecucion_id, motivo="   "
            ).status_code
            == 409
        )
        assert (
            _requiere(cliente, orden_id, ejecucion_id, motivo="").status_code
            == 422
        )
        sin_motivo = cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion_id}"
            "/requires-redefinition",
            json={"usuario_id": multi.TECNICO},
        )
        assert sin_motivo.status_code == 422
        # Nada se persistio.
        orden = _orden(cliente, orden_id)
        assert orden["ejecuciones"][0]["estado"] == "EN_PROGRESO"
        assert "PROC-REP-200" not in _ids(orden)

        assert _requiere(cliente, orden_id, ejecucion_id).status_code == 200
        # Ya cerrada: no se puede volver a cerrar.
        assert _requiere(cliente, orden_id, ejecucion_id).status_code == 409


# --- technical-review: errores ---


def test_technical_review_404_409_422(tmp_path):
    cliente, orden_id = _hasta_125(tmp_path)
    with cliente:
        assert _revisar(cliente, "OR-999999").status_code == 404
        assert _revisar(cliente, orden_id, "DET-999").status_code == 404
        assert (
            _revisar(cliente, orden_id, usuario=multi.RECEPCION).status_code
            == 409
        )
        assert _revisar(cliente, orden_id, resultado="  ").status_code == 409
        assert _revisar(cliente, orden_id, resultado="").status_code == 422
        assert "PROC-REP-126" not in _ids(_orden(cliente, orden_id))


def test_technical_review_fuera_de_125_es_409(tmp_path):
    cliente, orden_id, _ = _hasta_en_ejecucion(tmp_path)
    with cliente:
        assert _revisar(cliente, orden_id).status_code == 409


# --- redefine: errores ---


def test_redefine_404_409_422(tmp_path):
    cliente, orden_id = _hasta_125(tmp_path)
    with cliente:
        # Sin 126 previo.
        assert _redefinir(cliente, orden_id).status_code == 409
        _revisar(cliente, orden_id)
        assert _redefinir(cliente, "OR-999999").status_code == 404
        assert _redefinir(
            cliente, orden_id, detalle_id="DET-999"
        ).status_code == (404)
        assert _redefinir(cliente, orden_id, tipo="TR-999").status_code == 404
        assert (
            _redefinir(cliente, orden_id, usuario=multi.TECNICO).status_code
            == 409
        )
        sin_tipo = cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/redefine",
            json={"usuario_id": multi.RECEPCION},
        )
        assert sin_tipo.status_code == 422
        assert "PROC-REP-127" not in _ids(_orden(cliente, orden_id))


# --- Garantia RMA (HP-REP-003) ---


def test_garantia_rma_conserva_vinculo_al_detalle_origen(tmp_path):
    with _cliente(tmp_path, stock="5") as cliente:
        origen = _orden_entregada(cliente)
        garantia = cliente.post(
            f"/api/orders/{origen['id']}/details/DET-001/warranty-rma",
            json={"usuario_id": RECEPCION},
        ).json()
        assert garantia["estado_workflow"] == "HABILITADA"
        _tomar(cliente, garantia["id"])
        iniciada = cliente.post(
            f"/api/orders/{garantia['id']}/details/DET-001/start",
            json={"usuario_id": TECNICO},
        ).json()
        ejecucion_id = iniciada["ejecuciones"][0]["id"]

        assert (
            _requiere(
                cliente, garantia["id"], ejecucion_id, usuario_id=TECNICO
            ).status_code
            == 200
        )
        _revisar(cliente, garantia["id"], usuario=TECNICO)
        respuesta = _redefinir(
            cliente,
            garantia["id"],
            tipo=garantia["reparaciones_detail"][0]["tipo_reparacion_id"],
            usuario=RECEPCION,
        )
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()

        assert orden["origen"] == "RMA_GARANTIA_REPARACION"
        assert orden["orden_origen_id"] == origen["id"]
        detalle = _detalle(orden)
        assert detalle["detalle_origen_id"] == "DET-001"
        assert len(detalle["definiciones_anteriores"]) == 1  # mismo Tipo
        assert orden["estado_workflow"] == "HABILITADA"


# --- RT_INTERNO ---


@pytest.mark.parametrize("stock_pantalla", ["2", "0"])
def test_rt_interno_redefinicion_sin_pagos(tmp_path, stock_pantalla):
    with _cliente_multi(tmp_path, a="2", b=stock_pantalla) as cliente:
        orden_id = _crear_orden_rt(cliente)
        cliente.post(
            f"/api/orders/{orden_id}/details",
            json={
                "usuario_id": multi.RECEPCION,
                "tipo_reparacion_id": multi.TIPO_BATERIA,
            },
        )
        _encolar_y_tomar(cliente, orden_id)
        ejecucion_id = _iniciar(cliente, orden_id)

        orden = _requiere(cliente, orden_id, ejecucion_id).json()
        assert _codigos(orden) == ["REVISAR_DETALLE"]  # RT: sin pagos
        _revisar(cliente, orden_id)
        orden = _redefinir(cliente, orden_id).json()
        esperado = "PROC-REP-140" if stock_pantalla != "0" else "PROC-REP-100"
        assert orden["historial"][-1]["referencia_id"] == esperado


# --- Stock y atomicidad del cierre ---


def test_requiere_redefinicion_no_deja_reservas_activas(tmp_path):
    cliente, orden_id, ejecucion_id = _hasta_en_ejecucion(tmp_path, a="3")
    with cliente:
        _fijar_stock(tmp_path, **{INSUMO: 3})
        orden = _requiere(cliente, orden_id, ejecucion_id).json()
        assert orden["ejecuciones"][0]["insumos_utilizados"] == []
        # Nada se consumio: el stock fisico queda igual.
        assert _stock(tmp_path, "INS-001") == Decimal("3")
