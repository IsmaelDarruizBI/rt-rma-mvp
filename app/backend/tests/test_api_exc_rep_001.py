"""EXC-REP-001 (recursos insuficientes, en espera de revalidacion) por HTTP.

    HTTP -> router -> application -> services -> repositories -> JSON

Ningun Detalle trabajable ya no es un error: la Orden se persiste detenida
en PROC-REP-100 con los Detalles BLOQUEADO_POR_RECURSOS, espera
(110 No -> 120) y se revalida (120 -> 080 -> 090 [-> 140 | -> 100]) contra
el stock GLOBAL actual. Mecanismo transversal a los Origenes.
"""

import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.storage.json.base import escribir_json_atomico
from tests import test_multidetalle as multi
from tests.test_api_hp_rep_002 import (
    INSUMO,
    RECEPCION,
    TECNICO,
    TIPO,
    _crear_orden_rt,
    _sembrar_catalogos,
)
from tests.test_api_hp_rep_003 import _orden_entregada
from tests.test_api_var_rep_001_002 import _crear_orden as _crear_orden_cliente
from tests.test_api_var_rep_003 import _desde_cola, _interrumpir


def _fijar_stock(directorio, **valores) -> None:
    ruta = directorio / "catalogs" / "insumos.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    for insumo in datos:
        if insumo["id"] in valores:
            insumo["stock_fisico"] = str(valores[insumo["id"]])
    escribir_json_atomico(ruta, datos)


def _stock(directorio, insumo_id) -> Decimal:
    ruta = directorio / "catalogs" / "insumos.json"
    for insumo in json.loads(ruta.read_text(encoding="utf-8")):
        if insumo["id"] == insumo_id:
            return Decimal(str(insumo["stock_fisico"]))
    raise AssertionError(insumo_id)


def _cliente(directorio, stock="0") -> TestClient:
    _sembrar_catalogos(directorio, stock=stock)
    return TestClient(create_app(Settings(data_dir=directorio)))


def _ids(orden: dict) -> list[str]:
    return [p["referencia_id"] for p in orden["historial"]]


def _codigos(orden: dict) -> list[str]:
    return [a["codigo"] for a in orden["acciones_disponibles"]]


def _definir(cliente, orden_id):
    return cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )


def _esperar(cliente, orden_id):
    return cliente.post(f"/api/orders/{orden_id}/resources/wait")


def _revalidar(cliente, orden_id):
    return cliente.post(f"/api/orders/{orden_id}/resources/revalidate")


# --- CLIENTE_EXTERNO: ciclo completo ---


def test_cliente_externo_sin_stock_espera_y_se_habilita_al_revalidar(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _crear_orden_cliente(cliente)

        # 090 Ninguno trabajable -> 100: 200, no 409.
        respuesta = _definir(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert _ids(orden)[-4:] == [
            "PROC-REP-060",
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-100",
        ]
        assert orden["current_process"] == "PROC-REP-100"
        assert orden["estado_workflow"] == "REQUERIMIENTO"
        assert orden["reparaciones_detail"][0]["estado"] == "DEFINIDO"
        assert orden["reparaciones_detail"][0]["condicion"] == (
            "BLOQUEADO_POR_RECURSOS"
        )
        paso_100 = orden["historial"][-1]
        assert paso_100["reparacion_detail_id"] == "DET-001"
        assert paso_100["observacion"] == f"Faltantes: {INSUMO}"
        assert _codigos(orden) == ["ESPERAR_RECURSOS", "REGISTRAR_PAGO"]
        espera = orden["acciones_disponibles"][0]
        assert espera["requiere_actor"] is False and espera["roles"] == []

        # 110 No -> 120
        orden = _esperar(cliente, orden_id).json()
        assert _ids(orden)[-2:] == ["PROC-REP-110", "PROC-REP-120"]
        assert _codigos(orden) == ["REVALIDAR_RECURSOS", "REGISTRAR_PAGO"]

        # Sigue sin stock: 120 -> 080 -> 090 Ninguno -> 100.
        orden = _revalidar(cliente, orden_id).json()
        assert _ids(orden)[-3:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-100",
        ]
        assert orden["current_process"] == "PROC-REP-100"
        assert _codigos(orden)[0] == "ESPERAR_RECURSOS"
        orden = _esperar(cliente, orden_id).json()
        assert orden["current_process"] == "PROC-REP-120"

        # Llega stock: revalidar -> 090 Si -> 140.
        _fijar_stock(tmp_path, **{INSUMO: 2})
        respuesta = _revalidar(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert _ids(orden)[-3:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-140",
        ]
        assert orden["estado_workflow"] == "HABILITADA"
        assert orden["reparaciones_detail"][0]["condicion"] == "SIN_BLOQUEO"
        assert "ENCOLAR" in _codigos(orden)
        ids = _ids(orden)
        assert ids.count("PROC-REP-060") == 1  # sin comprobante nuevo
        assert ids.count("PROC-REP-070") == 1
        assert ids.count("PROC-REP-080") == 3  # cada ciclo se conserva
        assert ids.count("PROC-REP-120") == 2

        # La factibilidad nunca reserva ni mueve el stock fisico.
        assert _stock(tmp_path, INSUMO) == Decimal("2")


def test_los_endpoints_de_recursos_solo_valen_en_su_nodo(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _crear_orden_cliente(cliente)
        # Antes de definir (PROC-REP-040).
        assert _esperar(cliente, orden_id).status_code == 409
        assert _revalidar(cliente, orden_id).status_code == 409

        _definir(cliente, orden_id)  # queda en 100
        assert _revalidar(cliente, orden_id).status_code == 409
        assert _esperar(cliente, orden_id).status_code == 200  # ahora en 120
        assert _esperar(cliente, orden_id).status_code == 409

        _fijar_stock(tmp_path, **{INSUMO: 1})
        assert _revalidar(cliente, orden_id).status_code == 200  # 140
        assert _revalidar(cliente, orden_id).status_code == 409
        assert _esperar(cliente, orden_id).status_code == 409


def test_ordenes_inexistentes_devuelven_404(tmp_path):
    with _cliente(tmp_path) as cliente:
        assert _esperar(cliente, "OR-999999").status_code == 404
        assert _revalidar(cliente, "OR-999999").status_code == 404


# --- Reservas globales y liberacion externa ---


def test_una_reserva_ajena_bloquea_y_su_liberacion_desbloquea(tmp_path):
    with _cliente(tmp_path, stock="1") as cliente:
        # Orden A reserva la unica unidad (Ejecucion en curso).
        orden_a = _crear_orden_cliente(cliente)
        _definir(cliente, orden_a)
        _, _, ejecucion_a = _desde_cola(cliente, orden_a)

        # Orden B: stock fisico 1 pero disponible 0 -> espera.
        orden_b = _crear_orden_cliente(cliente)
        respuesta = _definir(cliente, orden_b)
        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["current_process"] == "PROC-REP-100"
        assert _esperar(cliente, orden_b).status_code == 200
        todavia = _revalidar(cliente, orden_b).json()
        assert todavia["current_process"] == "PROC-REP-100"

        # A interrumpe sin usar nada: la reserva se libera (stock intacto).
        _interrumpir(cliente, orden_a, ejecucion_a, usado="")
        assert _stock(tmp_path, INSUMO) == Decimal("1")

        _esperar(cliente, orden_b)
        orden = _revalidar(cliente, orden_b).json()
        assert orden["current_process"] == "PROC-REP-140"
        assert orden["estado_workflow"] == "HABILITADA"
        assert orden["reparaciones_detail"][0]["condicion"] == "SIN_BLOQUEO"


# --- RT_INTERNO y RMA_GARANTIA_REPARACION ---


def test_rt_interno_sin_stock_espera_sin_comprobante_ni_pagos(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _crear_orden_rt(cliente)

        orden = _definir(cliente, orden_id).json()
        assert _ids(orden)[-4:] == [
            "PROC-REP-050",
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-100",
        ]
        assert "PROC-REP-060" not in _ids(orden)
        assert (
            orden["documentos"]["comprobante_recepcion"]["generado"] is False
        )
        assert orden["current_process"] == "PROC-REP-100"
        assert _codigos(orden) == ["ESPERAR_RECURSOS"]  # sin pagos

        orden = _esperar(cliente, orden_id).json()
        assert _ids(orden)[-2:] == ["PROC-REP-110", "PROC-REP-120"]
        assert _codigos(orden) == ["REVALIDAR_RECURSOS"]

        _fijar_stock(tmp_path, **{INSUMO: 1})
        orden = _revalidar(cliente, orden_id).json()
        assert orden["estado_workflow"] == "HABILITADA"
        assert _ids(orden)[-3:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-140",
        ]


def test_garantia_rma_sin_stock_persiste_bloqueada_y_la_origen_no_cambia(
    tmp_path,
):
    with _cliente(tmp_path, stock="5") as cliente:
        origen = _orden_entregada(cliente)
        foto = cliente.get(f"/api/orders/{origen['id']}").json()
        _fijar_stock(tmp_path, **{INSUMO: 0})

        respuesta = cliente.post(
            f"/api/orders/{origen['id']}/details/DET-001/warranty-rma",
            json={"usuario_id": RECEPCION},
        )
        assert respuesta.status_code == 201, respuesta.text
        orden = respuesta.json()
        assert orden["origen"] == "RMA_GARANTIA_REPARACION"
        assert orden["current_process"] == "PROC-REP-100"
        assert orden["orden_origen_id"] == origen["id"]
        assert orden["detalles_origen_ids"] == ["DET-001"]
        (detalle,) = orden["reparaciones_detail"]
        assert detalle["detalle_origen_id"] == "DET-001"
        assert detalle["condicion"] == "BLOQUEADO_POR_RECURSOS"
        assert cliente.get(f"/api/orders/{origen['id']}").json() == foto

        _esperar(cliente, orden["id"])
        _fijar_stock(tmp_path, **{INSUMO: 3})
        orden = _revalidar(cliente, orden["id"]).json()
        assert orden["estado_workflow"] == "HABILITADA"
        assert (
            orden["reparaciones_detail"][0]["detalle_origen_id"] == "DET-001"
        )
        assert cliente.get(f"/api/orders/{origen['id']}").json() == foto


def test_garantia_en_revision_sin_stock_no_repite_065_068_075(tmp_path):
    with _cliente(tmp_path, stock="5") as cliente:
        origen = _orden_entregada(cliente)
        _fijar_stock(tmp_path, **{INSUMO: 0})
        orden = cliente.post(
            f"/api/orders/{origen['id']}/details/DET-001/warranty-rma/review",
            json={"usuario_id": RECEPCION},
        ).json()
        orden_id = orden["id"]
        cliente.post(
            f"/api/orders/{orden_id}/technical-review",
            json={"usuario_id": TECNICO, "resultado": "Falla de placa."},
        )
        cliente.post(
            f"/api/orders/{orden_id}/review/details",
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
        )

        orden = cliente.get(f"/api/orders/{orden_id}").json()
        assert orden["estado_workflow"] == "EN_REVISION"
        assert orden["current_process"] == "PROC-REP-100"
        assert "DEFINIR_REPARACION_DESDE_REVISION" not in _codigos(orden)

        _esperar(cliente, orden_id)
        _fijar_stock(tmp_path, **{INSUMO: 1})
        orden = _revalidar(cliente, orden_id).json()
        ids = _ids(orden)
        assert orden["estado_workflow"] == "HABILITADA"
        assert ids.count("PROC-REP-065") == ids.count("PROC-REP-068") == 1
        assert ids.count("PROC-REP-075") == ids.count("PROC-REP-060") == 1


# --- Multi-Detalle ---


def _cliente_multi(directorio, a="0", b="1") -> TestClient:
    multi._sembrar_catalogos(directorio)
    _fijar_stock(directorio, **{"INS-001": a, "INS-002": b})
    return TestClient(create_app(Settings(data_dir=directorio)))


def _definir_dos(cliente, orden_id):
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={
            "usuario_id": multi.RECEPCION,
            "tipo_reparacion_id": multi.TIPO_BATERIA,
            "finalizar_definicion": False,
        },
    )
    return cliente.post(
        f"/api/orders/{orden_id}/details",
        json={
            "usuario_id": multi.RECEPCION,
            "tipo_reparacion_id": multi.TIPO_PANTALLA,
        },
    )


def test_multidetalle_parcial_habilita_y_solo_el_trabajable_se_inicia(
    tmp_path,
):
    with _cliente_multi(tmp_path, a="0", b="1") as cliente:
        orden_id = multi._crear_orden(cliente)

        respuesta = _definir_dos(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert orden["estado_workflow"] == "HABILITADA"
        assert orden["current_process"] == "PROC-REP-140"
        det1, det2 = orden["reparaciones_detail"]
        assert det1["condicion"] == "BLOQUEADO_POR_RECURSOS"
        assert det2["condicion"] == "SIN_BLOQUEO"
        assert "PROC-REP-100" not in _ids(orden)  # hay uno trabajable

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
        assert iniciables == [det2["id"]]

        directo = cliente.post(
            f"/api/orders/{orden_id}/details/{det1['id']}/start",
            json={"usuario_id": multi.TECNICO},
        )
        assert directo.status_code == 409, directo.text
        valido = cliente.post(
            f"/api/orders/{orden_id}/details/{det2['id']}/start",
            json={"usuario_id": multi.TECNICO},
        )
        assert valido.status_code == 200, valido.text


def test_multidetalle_todos_bloqueados_espera_con_una_advertencia_por_detalle(
    tmp_path,
):
    with _cliente_multi(tmp_path, a="0", b="0") as cliente:
        orden_id = multi._crear_orden(cliente)

        orden = _definir_dos(cliente, orden_id).json()

        assert orden["current_process"] == "PROC-REP-100"
        assert orden["estado_workflow"] == "REQUERIMIENTO"
        advertencias = [
            (p["reparacion_detail_id"], p["observacion"])
            for p in orden["historial"]
            if p["referencia_id"] == "PROC-REP-100"
        ]
        assert advertencias == [
            ("DET-001", "Faltantes: INS-001"),
            ("DET-002", "Faltantes: INS-002"),
        ]
        assert [d["condicion"] for d in orden["reparaciones_detail"]] == [
            "BLOQUEADO_POR_RECURSOS",
            "BLOQUEADO_POR_RECURSOS",
        ]
        assert "ENCOLAR" not in _codigos(orden)
        orden = _esperar(cliente, orden_id).json()
        assert orden["current_process"] == "PROC-REP-120"
        assert orden["estado_workflow"] != "HABILITADA"


def test_un_detalle_se_desbloquea_y_otro_sigue_bloqueado_al_revalidar(
    tmp_path,
):
    with _cliente_multi(tmp_path, a="0", b="0") as cliente:
        orden_id = multi._crear_orden(cliente)
        _definir_dos(cliente, orden_id)
        _esperar(cliente, orden_id)

        _fijar_stock(tmp_path, **{"INS-002": 1})
        orden = _revalidar(cliente, orden_id).json()

        assert orden["estado_workflow"] == "HABILITADA"
        assert [d["condicion"] for d in orden["reparaciones_detail"]] == [
            "BLOQUEADO_POR_RECURSOS",
            "SIN_BLOQUEO",
        ]


def test_el_happy_path_con_stock_no_cambia(tmp_path):
    """Con recursos, 090 Si -> 140 directo: sin 100/110/120."""
    with _cliente(tmp_path, stock="5") as cliente:
        orden_id = _crear_orden_cliente(cliente)
        orden = _definir(cliente, orden_id).json()

        assert orden["estado_workflow"] == "HABILITADA"
        assert not {"PROC-REP-100", "PROC-REP-110", "PROC-REP-120"} & set(
            _ids(orden)
        )


# --- B-1: PROC-REP-211 PENDIENTE_RECURSOS -> PROC-REP-120 -------------------


def _hasta_211_pendiente_recursos(cliente, directorio):
    """Parcial (A bloqueado, B trabajable) -> completar B -> 211 -> 120."""
    orden_id = multi._crear_orden(cliente)
    orden = _definir_dos(cliente, orden_id).json()
    assert orden["estado_workflow"] == "HABILITADA"
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": multi.COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": multi.TECNICO, "estacion_id": multi.ESTACION},
    )
    orden = cliente.post(
        f"/api/orders/{orden_id}/details/DET-002/start",
        json={"usuario_id": multi.TECNICO},
    ).json()
    ejecucion_id = orden["ejecuciones"][0]["id"]
    orden = cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={
            "usuario_id": multi.TECNICO,
            "insumos_utilizados": [{"insumo_id": "INS-002", "cantidad": "1"}],
        },
    ).json()
    return orden_id, orden


def test_211_pendiente_de_recursos_pasa_directo_a_120_y_cierra_la_toma(
    tmp_path,
):
    with _cliente_multi(tmp_path, a="0", b="1") as cliente:
        orden_id, orden = _hasta_211_pendiente_recursos(cliente, tmp_path)

        ids = _ids(orden)
        assert ids[-2:] == ["PROC-REP-211", "PROC-REP-120"]
        assert orden["historial"][-2]["observacion"] == "PENDIENTE_RECURSOS"
        assert orden["historial"][-1]["usuario_id"] is None
        # Directo (211 -> 120): ningun 100/110 entre ambos ni despues de 211.
        assert ids.index("PROC-REP-211") == len(ids) - 2
        assert "PROC-REP-100" not in ids and "PROC-REP-110" not in ids
        assert orden["current_process"] == "PROC-REP-120"
        assert orden["estado_workflow"] == "EN_REPARACION"
        (toma,) = orden["tomas"]
        assert toma["estado"] == "CERRADA" and toma["fin"] is not None
        det1, det2 = orden["reparaciones_detail"]
        assert (det1["estado"], det1["condicion"]) == (
            "DEFINIDO",
            "BLOQUEADO_POR_RECURSOS",
        )
        assert det2["estado"] == "COMPLETO"
        codigos = _codigos(orden)
        assert "REVALIDAR_RECURSOS" in codigos
        for ausente in ("LIBERAR_ORDEN", "TOMAR", "INICIAR_DETALLE"):
            assert ausente not in codigos
        assert set(codigos) <= {"REVALIDAR_RECURSOS", "REGISTRAR_PAGO"}


def test_revalidar_sin_stock_desde_211_vuelve_a_100_y_luego_espera(tmp_path):
    with _cliente_multi(tmp_path, a="0", b="1") as cliente:
        orden_id, _ = _hasta_211_pendiente_recursos(cliente, tmp_path)

        orden = _revalidar(cliente, orden_id).json()
        assert _ids(orden)[-3:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-100",
        ]
        assert orden["historial"][-2]["observacion"] == "Ninguno trabajable"
        assert _codigos(orden)[0] == "ESPERAR_RECURSOS"
        # La toma ya cerrada no se reabre.
        assert orden["tomas"][0]["estado"] == "CERRADA"

        orden = _esperar(cliente, orden_id).json()
        assert _ids(orden)[-2:] == ["PROC-REP-110", "PROC-REP-120"]
        assert "REVALIDAR_RECURSOS" in _codigos(orden)


def test_e2e_parcial_espera_stock_revalida_reencola_y_llega_al_control(
    tmp_path,
):
    with _cliente_multi(tmp_path, a="0", b="1") as cliente:
        orden_id, _ = _hasta_211_pendiente_recursos(cliente, tmp_path)
        toma_1 = cliente.get(f"/api/orders/{orden_id}").json()["tomas"][0][
            "id"
        ]

        # Vuelve el stock: 120 -> 080 -> 090 Si -> 140.
        _fijar_stock(tmp_path, **{"INS-001": 5})
        orden = _revalidar(cliente, orden_id).json()
        assert _ids(orden)[-3:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-140",
        ]
        assert orden["historial"][-2]["observacion"] == "Si"
        assert orden["estado_workflow"] == "HABILITADA"
        assert [d["condicion"] for d in orden["reparaciones_detail"]] == [
            "SIN_BLOQUEO",
            "SIN_BLOQUEO",
        ]
        assert orden["reparaciones_detail"][1]["estado"] == "COMPLETO"
        assert "ENCOLAR" in _codigos(orden)

        # El proceso vuelve naturalmente: 150 -> 170 -> toma -> iniciar.
        orden = cliente.post(
            f"/api/orders/{orden_id}/queue",
            json={"usuario_id": multi.COORDINADOR, "prioridad": 1},
        ).json()
        assert _ids(orden)[-2:] == ["PROC-REP-150", "PROC-REP-170"]
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": multi.TECNICO, "estacion_id": multi.ESTACION},
        )
        orden = cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": multi.TECNICO},
        ).json()
        ejecucion_id = orden["ejecuciones"][-1]["id"]
        orden = cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
            json={
                "usuario_id": multi.TECNICO,
                "insumos_utilizados": [
                    {"insumo_id": "INS-001", "cantidad": "1"}
                ],
            },
        ).json()

        # Todos los Detalles terminaron: 211 COMPLETA y sigue el control.
        assert orden["historial"][-1]["referencia_id"] == "PROC-REP-211"
        assert orden["historial"][-1]["observacion"] == "COMPLETA"
        assert [t["estado"] for t in orden["tomas"]] == ["CERRADA", "CERRADA"]
        assert orden["tomas"][0]["id"] == toma_1
        assert "APROBAR_CONTROL" in _codigos(orden)

        for detalle in ("DET-001", "DET-002"):
            orden = cliente.post(
                f"/api/orders/{orden_id}/control/approve",
                json={"usuario_id": multi.RECEPCION, "detalle_id": detalle},
            ).json()
        assert orden["estado_workflow"] == "REPARACION_LISTA"
