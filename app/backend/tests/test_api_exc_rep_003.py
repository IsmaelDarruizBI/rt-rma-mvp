"""EXC-REP-003 (reserva de insumos fallida al iniciar la Ejecucion) por HTTP.

    HTTP -> router -> application -> services -> repositories -> JSON

La factibilidad (PROC-REP-080) fue correcta, pero al intentar la reserva real
(PROC-REP-185) el insumo ya no esta disponible: 185 "Reserva fallida" ->
186 -> 211. Es un RESULTADO funcional persistido (200), no un error: sin
Ejecucion, sin reservas y sin tocar el stock. Con otro Detalle trabajable la
toma sigue activa; sin ninguno, 211 cierra la toma y va directo a 120.
"""

from decimal import Decimal

import pytest

from app.storage import JsonOrdenReparacionRepository
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
    _revalidar,
    _stock,
)
from tests.test_api_exc_rep_002 import _override, _tomar
from tests.test_api_hp_rep_002 import (
    COORDINADOR,
    ESTACION,
    INSUMO,
    RECEPCION,
    TECNICO,
    _crear_orden_rt,
)
from tests.test_api_hp_rep_003 import _orden_entregada
from tests.test_api_var_rep_001_002 import _crear_orden as _crear_orden_cliente


def _iniciar(cliente, orden_id, detalle_id="DET-001", usuario=TECNICO):
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": usuario},
    )


def _orden(cliente, orden_id) -> dict:
    return cliente.get(f"/api/orders/{orden_id}").json()


def _movimientos(directorio, orden_id):
    """Movimientos de inventario persistidos (OrdenOut no los expone)."""
    return (
        JsonOrdenReparacionRepository(directorio / "ordenes")
        .obtener(orden_id)
        .movimientos_insumo
    )


def _sin_pago(orden: dict) -> list[str]:
    return [c for c in _codigos(orden) if c != "REGISTRAR_PAGO"]


def _uno_tomado(cliente, directorio, stock_al_iniciar="0") -> str:
    """Un Detalle factible y tomado; despues el stock desaparece."""
    orden_id = _crear_orden_cliente(cliente)
    assert _definir(cliente, orden_id).json()["estado_workflow"] == (
        "HABILITADA"
    )
    _tomar(cliente, orden_id)
    _fijar_stock(directorio, **{INSUMO: stock_al_iniciar})
    return orden_id


def _dos_tomados(cliente, directorio, a_al_iniciar="0", b_al_iniciar="1"):
    orden_id = multi._crear_orden(cliente)
    assert _definir_dos(cliente, orden_id).json()["estado_workflow"] == (
        "HABILITADA"
    )
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": multi.COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": multi.TECNICO, "estacion_id": multi.ESTACION},
    )
    _fijar_stock(
        directorio, **{"INS-001": a_al_iniciar, "INS-002": b_al_iniciar}
    )
    return orden_id


def _iniciar_multi(cliente, orden_id, detalle_id):
    return _iniciar(cliente, orden_id, detalle_id, usuario=multi.TECNICO)


# --- Caso A: queda otro Detalle trabajable ---


def test_caso_a_det_a_falla_det_b_sigue_trabajable(tmp_path):
    with _cliente_multi(tmp_path, a="1", b="1") as cliente:
        orden_id = _dos_tomados(cliente, tmp_path)
        antes = _orden(cliente, orden_id)

        respuesta = _iniciar_multi(cliente, orden_id, "DET-001")
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()

        assert _ids(orden)[-5:] == [
            "PROC-REP-181",
            "PROC-REP-174",
            "PROC-REP-185",
            "PROC-REP-186",
            "PROC-REP-211",
        ]
        paso_185, paso_186, paso_211 = orden["historial"][-3:]
        assert paso_185["observacion"] == "Reserva fallida"
        assert paso_185["reparacion_detail_id"] == "DET-001"
        assert paso_185["ejecucion_id"] is None
        assert paso_186["usuario_id"] is None
        assert paso_186["reparacion_detail_id"] == "DET-001"
        assert paso_186["observacion"] == "Faltantes: INS-001"
        assert paso_211["observacion"] == "ABIERTA_TRABAJABLE"

        det_a, det_b = orden["reparaciones_detail"]
        assert (det_a["estado"], det_a["condicion"]) == (
            "DEFINIDO",
            "BLOQUEADO_POR_RECURSOS",
        )
        assert (det_b["estado"], det_b["condicion"]) == (
            "DEFINIDO",
            "SIN_BLOQUEO",
        )
        # Atomicidad: sin Ejecucion, sin reservas, sin cambios de stock.
        assert orden["ejecuciones"] == []
        assert _movimientos(tmp_path, orden_id) == []
        assert _stock(tmp_path, "INS-001") == Decimal("0")
        assert _stock(tmp_path, "INS-002") == Decimal("1")
        # La toma sigue activa y el workflow no cambio.
        assert [t["estado"] for t in orden["tomas"]] == ["ACTIVA"]
        assert (
            orden["estado_workflow"] == antes["estado_workflow"] == ("EN_COLA")
        )
        assert orden["current_process"] == "PROC-REP-211"
        # Acciones: iniciar B + liberar (sin 100/110/120).
        assert _sin_pago(orden) == ["INICIAR_DETALLE", "LIBERAR_ORDEN"]
        (iniciar,) = [
            a
            for a in orden["acciones_disponibles"]
            if a["codigo"] == "INICIAR_DETALLE"
        ]
        assert iniciar["detalle_id"] == "DET-002"


def test_despues_se_inicia_det_b_con_212_si_y_se_continua_normal(tmp_path):
    with _cliente_multi(tmp_path, a="1", b="1") as cliente:
        orden_id = _dos_tomados(cliente, tmp_path)
        _iniciar_multi(cliente, orden_id, "DET-001")  # falla

        respuesta = _iniciar_multi(cliente, orden_id, "DET-002")
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert _ids(orden)[-5:] == [
            "PROC-REP-211",
            "PROC-REP-212",
            "PROC-REP-181",
            "PROC-REP-174",
            "PROC-REP-185",
        ]
        assert orden["historial"][-4]["observacion"] == "Si"  # 212 Si
        assert orden["estado_workflow"] == "EN_REPARACION"
        (ejecucion,) = orden["ejecuciones"]
        assert ejecucion["reparacion_detail_id"] == "DET-002"

        # Completar DET-002 deja a DET-001 bloqueado: 211 -> 120 directo.
        orden = cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion['id']}/complete",
            json={
                "usuario_id": multi.TECNICO,
                "insumos_utilizados": [
                    {"insumo_id": "INS-002", "cantidad": "1"}
                ],
            },
        ).json()
        assert _ids(orden)[-2:] == ["PROC-REP-211", "PROC-REP-120"]
        assert orden["historial"][-2]["observacion"] == "PENDIENTE_RECURSOS"
        assert [t["estado"] for t in orden["tomas"]] == ["CERRADA"]


def test_caso_a_liberar_la_orden_despues_de_la_reserva_fallida(tmp_path):
    with _cliente_multi(tmp_path, a="1", b="1") as cliente:
        orden_id = _dos_tomados(cliente, tmp_path)
        _iniciar_multi(cliente, orden_id, "DET-001")

        orden = cliente.post(
            f"/api/orders/{orden_id}/release",
            json={"usuario_id": multi.TECNICO},
        ).json()
        assert orden["estado_workflow"] == "EN_COLA"
        assert [t["estado"] for t in orden["tomas"]] == ["CERRADA"]
        assert _ids(orden)[-2:] == ["PROC-REP-213", "PROC-REP-170"]


# --- Caso B: no queda ningun Detalle trabajable ---


def test_caso_b_unico_detalle_211_pendiente_recursos_cierra_toma_y_va_a_120(
    tmp_path,
):
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _uno_tomado(cliente, tmp_path)
        antes = _orden(cliente, orden_id)

        respuesta = _iniciar(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()

        ids = _ids(orden)
        assert ids[-6:] == [
            "PROC-REP-181",
            "PROC-REP-174",
            "PROC-REP-185",
            "PROC-REP-186",
            "PROC-REP-211",
            "PROC-REP-120",
        ]
        # Directo 211 -> 120: nunca 100/110 entre ambos ni despues.
        assert "PROC-REP-100" not in ids and "PROC-REP-110" not in ids
        assert orden["historial"][-2]["observacion"] == "PENDIENTE_RECURSOS"
        assert orden["current_process"] == "PROC-REP-120"
        (toma,) = orden["tomas"]
        assert toma["estado"] == "CERRADA" and toma["fin"] is not None
        (detalle,) = orden["reparaciones_detail"]
        assert (detalle["estado"], detalle["condicion"]) == (
            "DEFINIDO",
            "BLOQUEADO_POR_RECURSOS",
        )
        assert orden["ejecuciones"] == []
        assert _movimientos(tmp_path, orden_id) == []
        assert _stock(tmp_path, INSUMO) == Decimal("0")
        # EN_COLA: la reserva fallo en el primer intento, nada empezo.
        assert (
            orden["estado_workflow"] == antes["estado_workflow"] == ("EN_COLA")
        )
        assert _sin_pago(orden) == ["REVALIDAR_RECURSOS"]


def test_el_progreso_muestra_186_y_120_con_evidencia_real(tmp_path):
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _uno_tomado(cliente, tmp_path)
        sin_fallo = [
            p["process_id"] for p in _orden(cliente, orden_id)["progreso"]
        ]
        assert "PROC-REP-186" not in sin_fallo

        orden = _iniciar(cliente, orden_id).json()
        ruta = [p["process_id"] for p in orden["progreso"]]
        alcanzados = {
            p["process_id"] for p in orden["progreso"] if p["alcanzado"]
        }

        assert ruta.index("PROC-REP-185") + 1 == ruta.index("PROC-REP-186")
        assert ruta.index("PROC-REP-211") + 1 == ruta.index("PROC-REP-120")
        assert {"PROC-REP-186", "PROC-REP-120"} <= alcanzados
        assert ruta.count("PROC-REP-120") == 1


def test_el_progreso_no_cambia_si_la_reserva_sale_bien(tmp_path):
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _uno_tomado(cliente, tmp_path, stock_al_iniciar="1")
        orden = _iniciar(cliente, orden_id).json()
        ruta = [p["process_id"] for p in orden["progreso"]]
        assert "PROC-REP-186" not in ruta and "PROC-REP-120" not in ruta


# --- I-1: revalidar una Orden que llego a 120 estando EN_COLA ---


def test_i1_en_cola_a_120_revalida_habilita_y_el_proceso_continua(tmp_path):
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _uno_tomado(cliente, tmp_path)
        orden = _iniciar(cliente, orden_id).json()
        assert orden["estado_workflow"] == "EN_COLA"
        assert orden["current_process"] == "PROC-REP-120"

        _fijar_stock(tmp_path, **{INSUMO: 5})
        respuesta = _revalidar(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text  # sin 409
        orden = respuesta.json()
        assert _ids(orden)[-3:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-140",
        ]
        assert orden["historial"][-2]["observacion"] == "Si"
        assert orden["estado_workflow"] == "HABILITADA"
        assert orden["reparaciones_detail"][0]["condicion"] == "SIN_BLOQUEO"

        orden = cliente.post(
            f"/api/orders/{orden_id}/queue",
            json={"usuario_id": COORDINADOR, "prioridad": 1},
        ).json()
        assert _ids(orden)[-2:] == ["PROC-REP-150", "PROC-REP-170"]
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": TECNICO, "estacion_id": ESTACION},
        )
        respuesta = _iniciar(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert orden["estado_workflow"] == "EN_REPARACION"
        assert len(orden["ejecuciones"]) == 1
        assert orden["historial"][-1]["referencia_id"] == "PROC-REP-185"


def test_i1_revalidar_sin_stock_vuelve_a_100_y_luego_espera(tmp_path):
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _uno_tomado(cliente, tmp_path)
        _iniciar(cliente, orden_id)

        orden = _revalidar(cliente, orden_id).json()
        assert _ids(orden)[-3:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-100",
        ]
        assert orden["historial"][-2]["observacion"] == "Ninguno trabajable"
        assert orden["estado_workflow"] == "EN_COLA"
        assert "PROC-REP-140" not in _ids(orden)[-3:]


def test_i1_003_120_revalidar_100_override_130_140_con_en_cola(tmp_path):
    """EXC-REP-003 -> EXC-REP-001 (120) -> EXC-REP-002 (override)."""
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _uno_tomado(cliente, tmp_path)
        _iniciar(cliente, orden_id)
        orden = _revalidar(cliente, orden_id).json()
        assert orden["current_process"] == "PROC-REP-100"

        respuesta = _override(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert _ids(orden)[-3:] == [
            "PROC-REP-110",
            "PROC-REP-130",
            "PROC-REP-140",
        ]
        assert orden["estado_workflow"] == "HABILITADA"

        # Con override, el mismo Detalle reserva aunque falte stock: no hay
        # 186 y la Ejecucion inicia.
        cliente.post(
            f"/api/orders/{orden_id}/queue",
            json={"usuario_id": COORDINADOR, "prioridad": 1},
        )
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": TECNICO, "estacion_id": ESTACION},
        )
        orden = _iniciar(cliente, orden_id).json()
        assert orden["historial"][-1]["referencia_id"] == "PROC-REP-185"
        assert orden["historial"][-1]["observacion"] is None
        assert len(orden["ejecuciones"]) == 1
        assert _stock(tmp_path, INSUMO) == Decimal("0")


def test_la_habilitacion_directa_desde_120_sigue_rechazada(tmp_path):
    """Aceptar EN_COLA en 140 no relaja el gate (090 Si o 130 valido)."""
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _uno_tomado(cliente, tmp_path)
        _iniciar(cliente, orden_id)  # EN_COLA, current_process = 120
        orden = _orden(cliente, orden_id)
        assert orden["estado_workflow"] == "EN_COLA"
        assert "ENCOLAR" not in _codigos(orden)
        # No existe un comando que habilite sin revalidar; la revalidacion
        # sin stock no habilita.
        _revalidar(cliente, orden_id)
        assert _orden(cliente, orden_id)["estado_workflow"] == "EN_COLA"


# --- Override y concurrencia ---


def test_con_override_del_mismo_detalle_no_hay_reserva_fallida(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _crear_orden_cliente(cliente)
        _definir(cliente, orden_id)
        assert _override(cliente, orden_id).status_code == 200
        _tomar(cliente, orden_id)

        orden = _iniciar(cliente, orden_id).json()
        assert "PROC-REP-186" not in _ids(orden)
        assert len(orden["ejecuciones"]) == 1
        assert orden["estado_workflow"] == "EN_REPARACION"


def test_el_override_de_otro_detalle_no_evita_la_reserva_fallida(tmp_path):
    with _cliente_multi(tmp_path, a="0", b="0") as cliente:
        orden_id = multi._crear_orden(cliente)
        _definir_dos(cliente, orden_id)
        assert (
            _override(cliente, orden_id, "DET-001").status_code == 200
        )  # solo DET-001 queda autorizado
        cliente.post(
            f"/api/orders/{orden_id}/queue",
            json={"usuario_id": multi.COORDINADOR, "prioridad": 1},
        )
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": multi.TECNICO, "estacion_id": multi.ESTACION},
        )

        # DET-002 sigue BLOQUEADO (no trabajable): precondicion, no 186.
        assert _iniciar_multi(cliente, orden_id, "DET-002").status_code == 409
        assert "PROC-REP-186" not in _ids(_orden(cliente, orden_id))


def test_dos_ordenes_la_segunda_pierde_la_ultima_unidad(tmp_path):
    with _cliente(tmp_path, stock="1") as cliente:
        primera = _crear_orden_cliente(cliente)
        _definir(cliente, primera)
        segunda = _crear_orden_cliente(cliente)
        _definir(cliente, segunda)  # ambas pasan 080 (solo consulta)
        _tomar(cliente, primera)
        _tomar(cliente, segunda)

        assert _iniciar(cliente, primera).status_code == 200
        respuesta = _iniciar(cliente, segunda)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert _ids(orden)[-5:] == [
            "PROC-REP-174",
            "PROC-REP-185",
            "PROC-REP-186",
            "PROC-REP-211",
            "PROC-REP-120",
        ]
        assert orden["ejecuciones"] == []
        assert _movimientos(tmp_path, segunda) == []
        # El stock fisico lo mueve solo PROC-REP-210: nadie lo toco.
        assert _stock(tmp_path, INSUMO) == Decimal("1")
        # La ganadora conserva su reserva intacta.
        assert len(_movimientos(tmp_path, primera)) == 1


# --- Precondiciones: siguen siendo 409 y no persisten nada ---


def test_las_precondiciones_siguen_siendo_409_y_no_persisten(tmp_path):
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _uno_tomado(cliente, tmp_path)
        antes = _orden(cliente, orden_id)

        rol = _iniciar(cliente, orden_id, usuario=RECEPCION)
        assert rol.status_code == 409
        inexistente = _iniciar(cliente, orden_id, "DET-999")
        assert inexistente.status_code in (404, 409)
        assert _orden(cliente, orden_id) == antes
        assert "PROC-REP-186" not in _ids(antes)


def test_sin_toma_no_se_registra_una_reserva_fallida(tmp_path):
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _crear_orden_cliente(cliente)
        _definir(cliente, orden_id)
        _fijar_stock(tmp_path, **{INSUMO: 0})

        assert _iniciar(cliente, orden_id).status_code == 409
        assert "PROC-REP-186" not in _ids(_orden(cliente, orden_id))


def test_con_ejecucion_activa_no_se_registra_una_reserva_fallida(tmp_path):
    with _cliente_multi(tmp_path, a="1", b="1") as cliente:
        orden_id = _dos_tomados(cliente, tmp_path, "1", "1")
        assert _iniciar_multi(cliente, orden_id, "DET-001").status_code == 200
        _fijar_stock(tmp_path, **{"INS-002": 0})

        assert _iniciar_multi(cliente, orden_id, "DET-002").status_code == 409
        assert "PROC-REP-186" not in _ids(_orden(cliente, orden_id))


# --- Origenes ---


def test_rt_interno_reserva_fallida_sin_pagos(tmp_path):
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _crear_orden_rt(cliente)
        assert _definir(cliente, orden_id).json()["estado_workflow"] == (
            "HABILITADA"
        )
        _tomar(cliente, orden_id)
        _fijar_stock(tmp_path, **{INSUMO: 0})

        respuesta = _iniciar(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert _ids(orden)[-4:] == [
            "PROC-REP-185",
            "PROC-REP-186",
            "PROC-REP-211",
            "PROC-REP-120",
        ]
        assert _codigos(orden) == ["REVALIDAR_RECURSOS"]  # RT: sin pagos
        assert orden["ejecuciones"] == []


def test_garantia_rma_reserva_fallida(tmp_path):
    with _cliente(tmp_path, stock="5") as cliente:
        origen = _orden_entregada(cliente)
        garantia = cliente.post(
            f"/api/orders/{origen['id']}/details/DET-001/warranty-rma",
            json={"usuario_id": RECEPCION},
        ).json()
        assert garantia["estado_workflow"] == "HABILITADA"
        _tomar(cliente, garantia["id"])
        _fijar_stock(tmp_path, **{INSUMO: 0})

        respuesta = _iniciar(cliente, garantia["id"])
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert orden["origen"] == "RMA_GARANTIA_REPARACION"
        assert _ids(orden)[-4:] == [
            "PROC-REP-185",
            "PROC-REP-186",
            "PROC-REP-211",
            "PROC-REP-120",
        ]
        assert orden["ejecuciones"] == []


# --- VAR-REP-003: un retry de un Detalle interrumpido sin stock ---


def test_un_detalle_interrumpido_sin_stock_entra_en_exc_003(tmp_path):
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _crear_orden_cliente(cliente)
        _definir(cliente, orden_id)
        _tomar(cliente, orden_id)
        orden = _iniciar(cliente, orden_id).json()
        ejecucion_id = orden["ejecuciones"][0]["id"]
        orden = cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion_id}/interrupt",
            json={"usuario_id": TECNICO, "insumos_utilizados": []},
        ).json()
        assert orden["reparaciones_detail"][0]["estado"] == "DEFINIDO"
        assert [t["estado"] for t in orden["tomas"]] == ["ACTIVA"]

        _fijar_stock(tmp_path, **{INSUMO: 0})
        respuesta = _iniciar(cliente, orden_id)
        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert _ids(orden)[-4:] == [
            "PROC-REP-185",
            "PROC-REP-186",
            "PROC-REP-211",
            "PROC-REP-120",
        ]
        # Ya habia trabajo previo: el hito se conserva.
        assert orden["estado_workflow"] == "EN_REPARACION"
        assert len(orden["ejecuciones"]) == 1  # solo la interrumpida
        assert [t["estado"] for t in orden["tomas"]] == ["CERRADA"]


@pytest.mark.parametrize("revalidar_antes", [False, True])
def test_ciclo_completo_003_espera_revalida_y_termina(
    tmp_path, revalidar_antes
):
    with _cliente(tmp_path, stock="1") as cliente:
        orden_id = _uno_tomado(cliente, tmp_path)
        _iniciar(cliente, orden_id)
        if revalidar_antes:
            _revalidar(cliente, orden_id)  # 090 Ninguno -> 100
            _esperar(cliente, orden_id)  # 110 No -> 120
        _fijar_stock(tmp_path, **{INSUMO: 2})
        assert _revalidar(cliente, orden_id).status_code == 200
        orden = _orden(cliente, orden_id)
        assert orden["estado_workflow"] == "HABILITADA"
