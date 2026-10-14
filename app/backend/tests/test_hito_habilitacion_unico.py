"""La habilitacion inicial (PROC-REP-140) es un hito historico unico.

En todos los caminos que llegan a habilitar -revalidacion de recursos (por
la Orden o en masa), override desde PROC-REP-100 y redefinicion de un
Detalle (EXC-REP-004)-:

- Nunca habilitada: 140 como siempre, y despues la priorizacion (150).
- Ya habilitada: ni 140 ni 150 se repiten; PROC-REP-211 la devuelve a la
  cola con su prioridad, sin tocar tomas ni Ejecuciones, conservando el
  historial, y repetir la operacion no cambia nada.
"""

from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    COORDINADOR,
    ESTACION,
    INSUMO_BATERIA,
    PANTALLA,
    RECEPCION,
    TECNICO,
    agregar,
    archivo,
    codigos,
    conflicto,
    definida,
    ejecutar,
    finalizar,
    ids,
    iniciar,
    ok,
    tomada,
)
from tests.test_api_hp_rep_002 import _crear_orden_rt
from tests.test_inventario_operativo import _cliente


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _revalidar_orden(cliente, orden_id):
    return cliente.post(f"/api/orders/{orden_id}/resources/revalidate")


def _revalidar_todo(cliente) -> list[dict]:
    return ok(
        cliente.post(
            "/api/inventory/revalidate-orders",
            json={"usuario_id": COORDINADOR},
        )
    )["ordenes"]


def _ingreso(cliente, cantidad, insumo_id=INSUMO_BATERIA):
    ok(
        cliente.post(
            f"/api/inventory/{insumo_id}/receipts",
            json={
                "usuario_id": COORDINADOR,
                "cantidad": cantidad,
                "motivo": "Reposicion",
            },
        )
    )


def _quitar_baterias(cliente, cantidad="1"):
    ok(
        cliente.post(
            f"/api/inventory/{INSUMO_BATERIA}/adjustments",
            json={
                "usuario_id": ADMINISTRADOR,
                "diferencia": f"-{cantidad}",
                "motivo": "Unidad danada",
                "confirmado": True,
            },
        )
    )


def _tomar(cliente, orden_id):
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": TECNICO, "estacion_id": ESTACION},
        )
    )


def _reserva_fallida(cliente) -> str:
    """Habilitada, en cola con prioridad 3 y tomada; al iniciar ya no hay
    baterias: 185 -> 186 -> 211 -> 120, con la toma cerrada."""
    orden_id = definida(cliente)
    tomada(cliente, orden_id)  # 150 (prioridad 3) -> 170 -> 180
    _quitar_baterias(cliente)
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": TECNICO},
        )
    )
    assert ids(orden)[-4:] == [
        "PROC-REP-185",
        "PROC-REP-186",
        "PROC-REP-211",
        "PROC-REP-120",
    ]
    assert orden["estado_workflow"] == "EN_COLA"
    assert [t["estado"] for t in orden["tomas"]] == ["CERRADA"]
    assert ids(orden).count("PROC-REP-140") == 1
    return orden_id


# --- Nunca habilitada: 140 como siempre --------------------------------------


def test_una_orden_nunca_habilitada_se_habilita_en_140(tmp_path):
    with _cliente(tmp_path, stock_bateria="0") as cliente:
        orden_id = definida(cliente)
        ok(cliente.post(f"/api/orders/{orden_id}/resources/wait"))
        assert _orden(cliente, orden_id)["current_process"] == "PROC-REP-120"
        assert "PROC-REP-140" not in ids(_orden(cliente, orden_id))
        _ingreso(cliente, "1")

        orden = ok(_revalidar_orden(cliente, orden_id))

        assert ids(orden)[-3:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-140",
        ]
        assert orden["estado_workflow"] == "HABILITADA"
        assert ids(orden).count("PROC-REP-140") == 1
        # Recien ahora se prioriza y entra a la cola.
        assert "ENCOLAR" in codigos(orden)
        orden = ok(
            cliente.post(
                f"/api/orders/{orden_id}/queue",
                json={"usuario_id": COORDINADOR, "prioridad": 2},
            )
        )
        assert (orden["estado_workflow"], orden["prioridad"]) == ("EN_COLA", 2)


# --- Ya habilitada: reserva fallida (EXC-REP-003) ----------------------------


def test_tras_una_reserva_fallida_no_repite_140(tmp_path):
    with _cliente(tmp_path, stock_bateria="1") as cliente:
        orden_id = _reserva_fallida(cliente)
        antes = _orden(cliente, orden_id)
        _ingreso(cliente, "2")

        orden = ok(_revalidar_orden(cliente, orden_id))

        assert ids(orden)[-3:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-211",
        ]
        assert orden["historial"][-2]["observacion"] == "Si"
        assert orden["historial"][-1]["observacion"] == "ABIERTA_TRABAJABLE"
        # Sin segunda habilitacion ni priorizacion: sigue en la cola.
        assert ids(orden).count("PROC-REP-140") == 1
        assert ids(orden).count("PROC-REP-150") == 1
        assert (orden["estado_workflow"], orden["prioridad"]) == ("EN_COLA", 3)
        assert "ENCOLAR" not in codigos(orden)
        # El historial se conserva y las tomas y Ejecuciones no cambian.
        assert (
            orden["historial"][: len(antes["historial"])]
            == (antes["historial"])
        )
        assert orden["tomas"] == antes["tomas"]
        assert orden["ejecuciones"] == antes["ejecuciones"] == []
        assert orden["reparaciones_detail"][0]["condicion"] == "SIN_BLOQUEO"

        # Repetida, por la Orden o en masa: nada cambia.
        revalidada = archivo(tmp_path, orden_id)
        assert "PROC-REP-120" in conflicto(_revalidar_orden(cliente, orden_id))
        assert _revalidar_todo(cliente) == []
        assert archivo(tmp_path, orden_id) == revalidada

        # Continua al taller: se toma de nuevo e inicia, con su prioridad.
        _tomar(cliente, orden_id)
        iniciar(cliente, orden_id)
        orden = _orden(cliente, orden_id)
        assert orden["estado_workflow"] == "EN_REPARACION"
        assert orden["prioridad"] == 3
        assert ids(orden).count("PROC-REP-140") == 1


def test_tras_una_reserva_fallida_la_revalidacion_masiva_tampoco(tmp_path):
    with _cliente(tmp_path, stock_bateria="1") as cliente:
        orden_id = _reserva_fallida(cliente)
        _ingreso(cliente, "2")

        (fila,) = _revalidar_todo(cliente)

        assert (fila["orden_id"], fila["resultado"]) == (
            orden_id,
            "TRABAJABLE",
        )
        assert fila["detalles_revalidados"] == ["DET-001"]
        assert "sin repetir PROC-REP-140" in fila["detalle"]
        orden = _orden(cliente, orden_id)
        assert ids(orden)[-4:] == [
            "ACC-REP-028",
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-211",
        ]
        assert ids(orden).count("PROC-REP-140") == 1
        assert (orden["estado_workflow"], orden["prioridad"]) == ("EN_COLA", 3)

        revalidada = archivo(tmp_path, orden_id)
        assert _revalidar_todo(cliente) == []
        assert archivo(tmp_path, orden_id) == revalidada


# --- Ya habilitada: venia del taller -----------------------------------------


def test_desde_el_taller_vuelve_a_la_cola_con_su_prioridad(tmp_path):
    with _cliente(tmp_path, stock_bateria="1", stock_pantalla="1") as cliente:
        orden_id = definida(cliente, BATERIA, PANTALLA)
        tomada(cliente, orden_id)  # prioridad 3
        ejecutar(cliente, orden_id, "DET-002", PANTALLA)
        _quitar_baterias(cliente)
        orden = ok(
            cliente.post(
                f"/api/orders/{orden_id}/details/DET-001/start",
                json={"usuario_id": TECNICO},
            )
        )
        # DET-002 completo, DET-001 sin baterias: 211 cierra la toma y la
        # Orden espera en 120 conservando EN_REPARACION.
        assert orden["current_process"] == "PROC-REP-120"
        assert orden["estado_workflow"] == "EN_REPARACION"
        antes = _orden(cliente, orden_id)
        _ingreso(cliente, "1")

        orden = ok(_revalidar_orden(cliente, orden_id))

        assert ids(orden)[-4:] == [
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-211",
            "PROC-REP-170",
        ]
        assert ids(orden).count("PROC-REP-140") == 1
        assert (orden["estado_workflow"], orden["prioridad"]) == ("EN_COLA", 3)
        assert orden["tomas"] == antes["tomas"]
        assert orden["ejecuciones"] == antes["ejecuciones"]
        detalles = {d["id"]: d for d in orden["reparaciones_detail"]}
        assert (
            detalles["DET-002"]
            == {d["id"]: d for d in antes["reparaciones_detail"]}["DET-002"]
        )
        assert detalles["DET-001"]["condicion"] == "SIN_BLOQUEO"

        _tomar(cliente, orden_id)
        iniciar(cliente, orden_id)
        assert _orden(cliente, orden_id)["estado_workflow"] == "EN_REPARACION"


# --- Override (EXC-REP-002) --------------------------------------------------


def _override(cliente, orden_id, detalle_id="DET-001"):
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/{detalle_id}/resources/override",
            json={
                "usuario_id": COORDINADOR,
                "motivo": "Urgente",
                "confirmado": True,
            },
        )
    )


def test_override_antes_de_la_habilitacion_habilita_en_140(tmp_path):
    with _cliente(tmp_path, stock_bateria="0") as cliente:
        orden_id = definida(cliente)
        assert _orden(cliente, orden_id)["current_process"] == "PROC-REP-100"

        orden = _override(cliente, orden_id)

        assert ids(orden)[-3:] == [
            "PROC-REP-110",
            "PROC-REP-130",
            "PROC-REP-140",
        ]
        assert orden["estado_workflow"] == "HABILITADA"
        # Primera priorizacion.
        assert "ENCOLAR" in codigos(orden)
        tomada(cliente, orden_id)
        orden = _orden(cliente, orden_id)
        assert (ids(orden).count("PROC-REP-140"), orden["prioridad"]) == (1, 3)


def test_override_despues_de_la_habilitacion_no_repite_140(tmp_path):
    with _cliente(tmp_path, stock_bateria="1") as cliente:
        orden_id = _reserva_fallida(cliente)
        # Sin stock: 120 -> 080 -> 090 Ninguno -> 100.
        orden = ok(_revalidar_orden(cliente, orden_id))
        assert orden["current_process"] == "PROC-REP-100"
        antes = _orden(cliente, orden_id)

        orden = _override(cliente, orden_id)

        assert ids(orden)[-4:] == [
            "ACC-REP-049",
            "PROC-REP-110",
            "PROC-REP-130",
            "PROC-REP-211",
        ]
        assert ids(orden).count("PROC-REP-140") == 1
        assert ids(orden).count("PROC-REP-150") == 1
        assert (orden["estado_workflow"], orden["prioridad"]) == ("EN_COLA", 3)
        assert "ENCOLAR" not in codigos(orden)
        assert (
            orden["historial"][: len(antes["historial"])]
            == (antes["historial"])
        )
        assert orden["tomas"] == antes["tomas"]
        assert orden["ejecuciones"] == antes["ejecuciones"]

        # Continua al taller: con el override reserva aunque no haya stock.
        _tomar(cliente, orden_id)
        iniciar(cliente, orden_id)
        orden = _orden(cliente, orden_id)
        assert (orden["estado_workflow"], orden["prioridad"]) == (
            "EN_REPARACION",
            3,
        )


def test_override_en_120_y_revalidacion_masiva_no_repiten_140(tmp_path):
    with _cliente(tmp_path, stock_bateria="1") as cliente:
        orden_id = _reserva_fallida(cliente)

        # En 120 el override solo autoriza el Detalle (sin nodos).
        orden = _override(cliente, orden_id)
        assert orden["current_process"] == "PROC-REP-120"
        assert ids(orden)[-1] == "ACC-REP-049"

        (fila,) = _revalidar_todo(cliente)

        assert fila["resultado"] == "TRABAJABLE"
        orden = _orden(cliente, orden_id)
        assert ids(orden)[-4:] == [
            "ACC-REP-028",
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-211",
        ]
        assert ids(orden).count("PROC-REP-140") == 1
        assert (orden["estado_workflow"], orden["prioridad"]) == ("EN_COLA", 3)


def test_override_con_toma_y_ejecucion_activas_no_recorre_nodos(tmp_path):
    with _cliente(tmp_path, stock_bateria="5", stock_pantalla="0") as cliente:
        orden_id = definida(cliente, BATERIA, PANTALLA)  # DET-002 bloqueado
        tomada(cliente, orden_id)
        iniciar(cliente, orden_id)
        antes = _orden(cliente, orden_id)

        orden = _override(cliente, orden_id, "DET-002")

        assert ids(orden)[len(antes["historial"]) :] == ["ACC-REP-049"]
        assert orden["current_process"] == antes["current_process"]
        assert orden["tomas"] == antes["tomas"]
        assert orden["ejecuciones"] == antes["ejecuciones"]
        assert ids(orden).count("PROC-REP-140") == 1


# --- Redefinicion de un Detalle (EXC-REP-004) --------------------------------


def _rt_en_revision(cliente) -> str:
    """RT_INTERNO habilitada, en cola con prioridad 2, tomada y con la
    Ejecucion de DET-001 cerrada por "Requiere redefinicion": 211 cierra la
    toma y la Orden espera la revision (125)."""
    orden_id = _crear_orden_rt(cliente)
    agregar(cliente, orden_id, BATERIA)
    finalizar(cliente, orden_id, confirmar_recepcion=False)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/queue",
            json={"usuario_id": COORDINADOR, "prioridad": 2},
        )
    )
    _tomar(cliente, orden_id)
    ejecucion_id = iniciar(cliente, orden_id)
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion_id}"
            "/requires-redefinition",
            json={
                "usuario_id": TECNICO,
                "insumos_utilizados": [],
                "motivo": "La placa esta danada.",
            },
        )
    )
    assert orden["current_process"] == "PROC-REP-125"
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/technical-review",
            json={"usuario_id": TECNICO, "resultado": "Placa con corrosion"},
        )
    )
    return orden_id


def _redefinir(cliente, orden_id):
    return cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/redefine",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": PANTALLA},
    )


def test_redefinicion_antes_de_la_habilitacion_no_es_posible(tmp_path):
    """Solo PROC-REP-200 marca un Detalle para redefinir, y eso exige una
    Ejecucion: una Orden nunca habilitada no llega a 127 ni a 140."""
    with _cliente(tmp_path, stock_bateria="0") as cliente:
        orden_id = definida(cliente)  # sin stock: 100, nunca habilitada
        antes = archivo(tmp_path, orden_id)

        conflicto(_redefinir(cliente, orden_id))

        assert archivo(tmp_path, orden_id) == antes
        assert "PROC-REP-140" not in ids(_orden(cliente, orden_id))


def test_redefinicion_despues_de_la_habilitacion_vuelve_a_la_cola(tmp_path):
    with _cliente(tmp_path, stock_bateria="2", stock_pantalla="2") as cliente:
        orden_id = _rt_en_revision(cliente)
        antes = _orden(cliente, orden_id)

        orden = ok(_redefinir(cliente, orden_id))

        assert ids(orden)[-5:] == [
            "PROC-REP-127",
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-211",
            "PROC-REP-170",
        ]
        assert ids(orden).count("PROC-REP-140") == 1
        assert ids(orden).count("PROC-REP-150") == 1
        assert (orden["estado_workflow"], orden["prioridad"]) == ("EN_COLA", 2)
        assert (
            orden["historial"][: len(antes["historial"])]
            == (antes["historial"])
        )
        assert orden["tomas"] == antes["tomas"]
        assert orden["ejecuciones"] == antes["ejecuciones"]
        assert orden["reparaciones_detail"][0]["condicion"] == "SIN_BLOQUEO"

        # Continua al taller con la definicion nueva.
        _tomar(cliente, orden_id)
        iniciar(cliente, orden_id)
        orden = _orden(cliente, orden_id)
        assert (orden["estado_workflow"], orden["prioridad"]) == (
            "EN_REPARACION",
            2,
        )


def test_redefinicion_sin_stock_y_override_no_repiten_140(tmp_path):
    with _cliente(tmp_path, stock_bateria="2", stock_pantalla="0") as cliente:
        orden_id = _rt_en_revision(cliente)

        orden = ok(_redefinir(cliente, orden_id))
        # Sin pantallas: 090 Ninguno -> 100, como siempre.
        assert ids(orden)[-4:] == [
            "PROC-REP-127",
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-100",
        ]

        orden = _override(cliente, orden_id)

        # Venia del taller: 130 -> 211 -> 170, sin repetir 140.
        assert ids(orden)[-4:] == [
            "PROC-REP-110",
            "PROC-REP-130",
            "PROC-REP-211",
            "PROC-REP-170",
        ]
        assert ids(orden).count("PROC-REP-140") == 1
        assert (orden["estado_workflow"], orden["prioridad"]) == ("EN_COLA", 2)
