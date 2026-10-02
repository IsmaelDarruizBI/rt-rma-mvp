"""Cambios funcionales de la iteracion de reconciliacion.

Cubre lo que surgio de la prueba manual del MVP desde el navegador:

- el Detalle expone el nombre del Tipo de Reparacion, no solo su ID;
- ``tipo_pago`` derivado (ANTICIPO / PAGO), distinto del medio;
- el Pago es transversal: se puede registrar antes de REPARACION_LISTA;
- PROC-REP-150 admite ACT-COORD o ACT-RECEP;
- PROC-REP-270 admite ACT-ADMIN o ACT-RECEP.

Reutiliza los helpers de ``test_api_hp_rep_001`` para no duplicar el
armado de catalogos ni el recorrido del Happy Path.
"""

import json

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.api_definicion import definir_y_finalizar

from .test_api_hp_rep_001 import (
    ADMINISTRADOR,
    COORDINADOR,
    INSUMO,
    RECEPCION,
    TECNICO,
    TIPO,
    _crear_orden,
    _hasta_ejecucion_iniciada,
    cliente,  # noqa: F401  (fixture de pytest)
)

# --- Nombre del Tipo de Reparacion --------------------------------------


def test_el_detalle_expone_el_nombre_del_tipo(cliente):  # noqa: F811
    """La UI muestra que reparacion es, no solo su ID tecnico."""
    orden_id = _crear_orden(cliente)
    orden = definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    ).json()

    detalle = orden["reparaciones_detail"][0]

    assert detalle["tipo_reparacion_id"] == TIPO
    assert detalle["tipo_reparacion_nombre"] == "Cambio bateria iPhone 14"


def test_el_nombre_del_tipo_no_se_persiste(cliente, tmp_path):  # noqa: F811
    """Es dato de catalogo vigente, no del aggregate."""
    orden_id = _crear_orden(cliente)
    definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )

    archivo = tmp_path / "ordenes" / f"{orden_id}.json"
    crudo = json.loads(archivo.read_text(encoding="utf-8"))
    detalle = crudo["reparaciones_detail"][0]

    assert "tipo_reparacion_nombre" not in detalle
    assert detalle["tipo_reparacion_id"] == TIPO


# --- Tipo de pago: ANTICIPO / PAGO --------------------------------------


def test_un_pago_temprano_es_un_anticipo(cliente):  # noqa: F811
    """BR-REP-017: el Pago es transversal, no espera la fase de cierre."""
    orden_id = _crear_orden(cliente)
    definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    antes = cliente.get(f"/api/orders/{orden_id}").json()

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": RECEPCION,
            "monto": "20000",
            "metodo": "EFECTIVO",
        },
    )

    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()

    assert orden["pagos"][0]["tipo_pago"] == "ANTICIPO"
    assert orden["resumen"]["pagado"] == "20000"
    assert orden["resumen"]["saldo"] == "60000"
    assert orden["resumen"]["estado_pago"] == "PARCIAL"

    # El pago no es un nodo del proceso: no mueve el recorrido...
    assert orden["current_process"] == antes["current_process"]
    referencias = [paso["referencia_id"] for paso in orden["historial"]]
    assert "PROC-REP-265" not in referencias

    # ...pero si deja traza, como accion transversal.
    assert len(orden["historial"]) == len(antes["historial"]) + 1
    ultima = orden["historial"][-1]
    assert ultima["tipo_referencia"] == "FUNCTIONAL_ACTION"
    assert ultima["referencia_id"] == "ACC-REP-020"
    assert ultima["accion"] == "REGISTRAR_PAGO"
    assert ultima["usuario_id"] == RECEPCION
    assert ultima["pago_id"] == orden["pagos"][0]["id"]
    assert ultima["process_id"] is None
    assert "ANTICIPO" in ultima["observacion"]
    assert "EFECTIVO" in ultima["observacion"]
    assert "20000" in ultima["observacion"]


def _hasta_reparacion_lista(cliente) -> str:  # noqa: F811
    orden_id, _, ejecucion_id = _hasta_ejecucion_iniciada(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={
            "usuario_id": TECNICO,
            "insumos_utilizados": [{"insumo_id": INSUMO, "cantidad": "1"}],
        },
    )
    cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={"usuario_id": RECEPCION},
    )
    return orden_id


def test_el_pago_del_cierre_es_de_tipo_pago(cliente):  # noqa: F811
    """Desde REPARACION_LISTA, el cobro es el del cierre."""
    orden_id = _hasta_reparacion_lista(cliente)

    orden = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": ADMINISTRADOR,
            "monto": "80000",
            "metodo": "EFECTIVO",
        },
    ).json()

    assert orden["pagos"][-1]["tipo_pago"] == "PAGO"
    # El cierre comercial todavia no empezo (current_process 240): el
    # Pago es transversal y NO evalua PROC-REP-265.
    assert orden["puede_entregar"] is False
    recorridos = [paso["process_id"] for paso in orden["historial"]]
    assert "PROC-REP-265" not in recorridos
    assert orden["current_process"] == "PROC-REP-240"


def test_anticipo_y_pago_conviven_en_la_misma_orden(cliente):  # noqa: F811
    """Anticipo temprano + saldo al retirar: dos tipos, un mismo medio."""
    orden_id, _, ejecucion_id = _hasta_ejecucion_iniciada(cliente)

    cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": RECEPCION,
            "monto": "30000",
            "metodo": "EFECTIVO",
        },
    )
    cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={
            "usuario_id": TECNICO,
            "insumos_utilizados": [{"insumo_id": INSUMO, "cantidad": "1"}],
        },
    )
    cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={"usuario_id": RECEPCION},
    )
    orden = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": ADMINISTRADOR,
            "monto": "50000",
            "metodo": "TRANSFERENCIA",
        },
    ).json()

    assert [pago["tipo_pago"] for pago in orden["pagos"]] == [
        "ANTICIPO",
        "PAGO",
    ]
    assert orden["resumen"]["saldo"] == "0"
    assert orden["puede_entregar"] is False
    assert orden["current_process"] == "PROC-REP-240"


def test_un_tecnico_no_puede_registrar_un_pago_por_http(cliente):  # noqa: F811
    """BR-REP-017: usuario ACTIVO AND rol != TECNICO, exigido en la API."""
    orden_id = _crear_orden(cliente)
    definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": TECNICO,
            "monto": "1000",
            "metodo": "EFECTIVO",
        },
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["codigo"] == "PRECONDICION_INVALIDA"


def test_el_anticipo_habilita_la_accion_de_pago_temprano(cliente):  # noqa: F811
    """Con saldo > 0 la UI debe poder ofrecer REGISTRAR_PAGO."""
    orden_id = _crear_orden(cliente)
    orden = definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    ).json()

    codigos = [accion["codigo"] for accion in orden["acciones_disponibles"]]

    assert "REGISTRAR_PAGO" in codigos
    pago = next(
        accion
        for accion in orden["acciones_disponibles"]
        if accion["codigo"] == "REGISTRAR_PAGO"
    )
    # BR-REP-017: usuario ACTIVO AND rol != TECNICO.
    assert pago["roles"] == ["ADMINISTRADOR", "RECEPCION", "COORDINADOR_RMA"]


# --- Ingreso a cola: ACT-COORD o ACT-RECEP ------------------------------


def _hasta_habilitada(cliente) -> str:  # noqa: F811
    orden_id = _crear_orden(cliente)
    definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    return orden_id


def test_recepcion_puede_ingresar_la_orden_a_la_cola(cliente):  # noqa: F811
    """PROC-REP-150 declara actores_alternativos: [ACT-RECEP]."""
    orden_id = _hasta_habilitada(cliente)

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": RECEPCION, "prioridad": 2},
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado_workflow"] == "EN_COLA"
    assert respuesta.json()["prioridad"] == 2


def test_el_coordinador_sigue_pudiendo_encolar(cliente):  # noqa: F811
    orden_id = _hasta_habilitada(cliente)

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado_workflow"] == "EN_COLA"


@pytest.mark.parametrize("usuario_id", [TECNICO, ADMINISTRADOR])
def test_tecnico_y_admin_no_encolan(cliente, usuario_id):  # noqa: F811
    orden_id = _hasta_habilitada(cliente)

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": usuario_id, "prioridad": 1},
    )

    assert respuesta.status_code == 409


# --- Entrega: ACT-ADMIN o ACT-RECEP -------------------------------------


def _hasta_lista_para_entregar(cliente, pagador: str) -> str:  # noqa: F811
    orden_id = _hasta_reparacion_lista(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    )
    cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": pagador,
            "monto": "80000",
            "metodo": "EFECTIVO",
        },
    )
    return orden_id


def test_recepcion_puede_entregar_el_equipo(cliente):  # noqa: F811
    """PROC-REP-270 declara actores_alternativos: [ACT-RECEP]."""
    orden_id = _hasta_lista_para_entregar(cliente, RECEPCION)

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": RECEPCION}
    )

    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["current_process"] == "EVT-REP-999"


def test_el_administrador_sigue_pudiendo_entregar(cliente):  # noqa: F811
    orden_id = _hasta_lista_para_entregar(cliente, ADMINISTRADOR)

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver",
        json={"usuario_id": ADMINISTRADOR},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado_workflow"] == "ENTREGADA"


@pytest.mark.parametrize("usuario_id", [TECNICO, COORDINADOR])
def test_tecnico_y_coordinador_no_entregan(cliente, usuario_id):  # noqa: F811
    orden_id = _hasta_lista_para_entregar(cliente, ADMINISTRADOR)

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": usuario_id}
    )

    assert respuesta.status_code == 409


def test_recepcion_no_entrega_con_saldo_pendiente(cliente):  # noqa: F811
    """Ampliar el actor no relaja la condicion comercial."""
    orden_id = _hasta_reparacion_lista(cliente)

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver", json={"usuario_id": RECEPCION}
    )

    assert respuesta.status_code == 409


def test_el_happy_path_no_cambio_de_actores(cliente):  # noqa: F811
    """HP-REP-001 no cambia: sigue encolando con COORD."""
    orden_id = _hasta_habilitada(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )

    orden = cliente.get(f"/api/orders/{orden_id}").json()
    por_nodo = {
        paso["process_id"]: paso["usuario_id"] for paso in orden["historial"]
    }

    assert por_nodo["PROC-REP-150"] == COORDINADOR


def test_la_respuesta_incluye_los_pagos_para_la_ui(cliente):  # noqa: F811
    """El frontend arma el historial de pagos con lo que ya devuelve la API."""
    orden_id = _crear_orden(cliente)
    definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": RECEPCION,
            "monto": "20000",
            "metodo": "EFECTIVO",
        },
    )

    pagos = cliente.get(f"/api/orders/{orden_id}").json()["pagos"]

    assert len(pagos) == 1
    assert set(pagos[0]) >= {
        "id",
        "monto",
        "tipo_pago",
        "metodo",
        "usuario_id",
        "fecha",
    }


def test_el_cliente_es_un_testclient(cliente):  # noqa: F811
    """Guarda de que el fixture importado sigue siendo el esperado."""
    assert isinstance(cliente, TestClient)


def test_las_acciones_multi_rol_declaran_sus_dos_actores(cliente):  # noqa: F811
    """La UI recibe los dos roles autorizados, no uno solo."""
    orden_id = _hasta_habilitada(cliente)

    orden = cliente.get(f"/api/orders/{orden_id}").json()
    encolar = next(
        accion
        for accion in orden["acciones_disponibles"]
        if accion["codigo"] == "ENCOLAR"
    )

    assert set(encolar["roles"]) == {"COORDINADOR_RMA", "RECEPCION"}


def test_la_accion_de_entregar_declara_sus_dos_actores(cliente):  # noqa: F811
    orden_id = _hasta_lista_para_entregar(cliente, ADMINISTRADOR)

    orden = cliente.get(f"/api/orders/{orden_id}").json()
    entregar = next(
        accion
        for accion in orden["acciones_disponibles"]
        if accion["codigo"] == "ENTREGAR"
    )

    assert set(entregar["roles"]) == {"ADMINISTRADOR", "RECEPCION"}
