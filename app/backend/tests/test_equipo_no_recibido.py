"""«Equipo no recibido»: la custodia se decide, nunca se deduce.

Una Orden CANCELADA con la custodia sin definir no cierra sola: Recepcion
o Administracion confirman que el equipo esta en el local (y despues se
registra su devolucion fisica) o registran, con motivo, que nunca
ingreso. En ambos casos el cierre respeta la cuenta: con saldo a favor
espera la devolucion del dinero. "No recibido" se rechaza si algo en la
Orden prueba que el equipo estuvo en el local, y ninguna decision cambia
con la Orden cerrada.
"""

import json

import pytest

from tests.fixtures.api_salidas import (
    RECEPCION,
    TECNICO,
    agregar,
    archivo,
    autorizar_todo,
    cancelar_orden,
    cerrar_ejecucion,
    cliente_http,
    conflicto,
    crear,
    definida,
    devolver,
    ejecutar,
    finalizar,
    ids,
    iniciar,
    notificar_pagar_entregar,
    ok,
    tomada,
)
from tests.fixtures.custodia import confirmar_recepcion, no_recibido

MOTIVO = "El cliente nunca trajo el equipo."


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def _sin_custodia(cliente) -> str:
    """Definida y autorizada, con el comprobante emitido y la recepcion
    fisica SIN confirmar."""
    orden_id = crear(cliente)
    agregar(cliente, orden_id)
    finalizar(cliente, orden_id, confirmar_recepcion=False)
    autorizar_todo(cliente, orden_id)
    return orden_id


def _cancelada_sin_custodia(cliente) -> str:
    orden_id = _sin_custodia(cliente)
    ok(cancelar_orden(cliente, orden_id))
    return orden_id


def _pagar(cliente, orden_id, monto) -> str:
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": RECEPCION,
                "monto": monto,
                "metodo": "EFECTIVO",
            },
        )
    )
    return orden["pagos"][-1]["id"]


def _reintegrar(cliente, orden_id, pago_id, monto) -> dict:
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/refunds",
            json={
                "usuario_id": RECEPCION,
                "pago_id": pago_id,
                "monto": monto,
                "medio": "EFECTIVO",
                "motivo": "Cancelacion.",
            },
        )
    )


def _custodia(orden) -> list[str]:
    return [accion["codigo"] for accion in orden["acciones_custodia"]]


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


# --- 1. Cancelacion con custodia pendiente -----------------------------------


def test_1_cancelar_con_custodia_pendiente_no_cierra(cliente):
    orden_id = _sin_custodia(cliente)

    orden = ok(cancelar_orden(cliente, orden_id))

    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["cerrada"] is False
    assert orden["current_process"] == "PROC-REP-211"
    assert orden["custodia"]["estado"] == "PENDIENTE_CONFIRMACION"
    assert orden["devolucion_pendiente"] is False
    assert orden["pendientes_de_cierre"] == [
        "Falta definir la custodia del equipo: confirmar la recepcion "
        "fisica (y despues registrar su devolucion) o registrar "
        '"Equipo no recibido".'
    ]
    assert {"CONFIRMAR_RECEPCION", "REGISTRAR_EQUIPO_NO_RECIBIDO"} <= set(
        _custodia(orden)
    )
    # Sin custodia confirmada tampoco hay devolucion fisica que registrar.
    assert "custodia confirmada" in conflicto(devolver(cliente, orden_id))


# --- 2/5. Equipo recibido y devuelto -----------------------------------------


def test_2_5_equipo_recibido_y_devuelto_cierra(cliente):
    orden_id = _cancelada_sin_custodia(cliente)

    orden = confirmar_recepcion(cliente, orden_id)

    assert orden["custodia"]["estado"] == "EN_CUSTODIA"
    assert orden["custodia"]["confirmada_por"] == RECEPCION
    assert orden["custodia"]["confirmada_en"] is not None
    assert orden["devolucion_pendiente"] is True
    assert orden["cerrada"] is False
    assert orden["pendientes_de_cierre"] == [
        "Falta registrar la devolucion fisica del equipo."
    ]
    # Confirmado el ingreso, ya no puede declararse "no recibido".
    assert "ya se confirmo" in conflicto(no_recibido(cliente, orden_id))

    orden = ok(devolver(cliente, orden_id, recibido_por="Cliente"))

    assert orden["cerrada"] is True
    assert orden["current_process"] == "EVT-REP-999"
    assert orden["custodia"]["estado"] == "DEVUELTO"
    assert orden["estado_workflow"] == "CANCELADA"


# --- 3/4/6. Equipo no recibido -----------------------------------------------


def test_3_6_no_recibido_cierra_sin_devolucion_fisica(cliente):
    orden_id = _cancelada_sin_custodia(cliente)

    orden = ok(no_recibido(cliente, orden_id, MOTIVO))

    decision = orden["recepcion"]["no_recibido"]
    assert decision["usuario_id"] == RECEPCION
    assert decision["motivo"] == MOTIVO
    assert decision["fecha"] is not None
    assert orden["custodia"]["estado"] == "NO_RECIBIDO"
    assert orden["recepcion"]["confirmacion"] is None
    paso = [
        p for p in orden["historial"] if p["referencia_id"] == "ACC-REP-027"
    ]
    assert paso[0]["accion"] == "REGISTRAR_EQUIPO_NO_RECIBIDO"
    assert paso[0]["observacion"] == MOTIVO
    # Sin equipo que devolver ni dinero de por medio: cierra.
    assert orden["cerrada"] is True
    assert orden["current_process"] == "EVT-REP-999"
    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["devolucion"] is None
    assert orden["pendientes_de_cierre"] == []
    # Ningun comprobante de devolucion para un equipo que nunca ingreso.
    assert [d["tipo"] for d in orden["documentos_emitidos"]] == [
        "COMPROBANTE_RECEPCION"
    ]
    conflicto(devolver(cliente, orden_id), "ORDEN_CERRADA")


def test_4_no_recibido_exige_motivo_y_rol(cliente, tmp_path):
    orden_id = _cancelada_sin_custodia(cliente)
    antes = archivo(tmp_path, orden_id)

    assert "motivo" in conflicto(no_recibido(cliente, orden_id, "   "))
    assert no_recibido(cliente, orden_id, "").status_code == 422
    conflicto(no_recibido(cliente, orden_id, MOTIVO, usuario=TECNICO))

    assert archivo(tmp_path, orden_id) == antes


def test_no_recibido_solo_en_una_orden_cancelada(cliente):
    """En una Orden activa la recepcion queda pendiente hasta que llegue."""
    orden_id = _sin_custodia(cliente)
    assert "REGISTRAR_EQUIPO_NO_RECIBIDO" not in _custodia(
        _orden(cliente, orden_id)
    )

    mensaje = conflicto(no_recibido(cliente, orden_id))

    assert "Orden cancelada" in mensaje


# --- 7. Cierre financiero ----------------------------------------------------


def test_7_no_recibido_con_credito_espera_la_devolucion_del_dinero(cliente):
    orden_id = _sin_custodia(cliente)
    pago_id = _pagar(cliente, orden_id, "30000")
    ok(cancelar_orden(cliente, orden_id))

    orden = ok(no_recibido(cliente, orden_id, MOTIVO))

    assert orden["cerrada"] is False
    assert orden["current_process"] == "PROC-REP-268"
    assert orden["pendientes_de_cierre"] == [
        "Falta devolver al cliente el saldo a favor: 30000."
    ]
    # La decision es unica: ya no se confirma la recepcion.
    assert "no se recibio" in conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/reception/confirm",
            json={"usuario_id": RECEPCION},
        )
    )

    orden = _reintegrar(cliente, orden_id, pago_id, "30000")

    assert orden["cerrada"] is True
    assert orden["estado_workflow"] == "CANCELADA"
    assert ids(orden)[-1] == "PROC-REP-268"


def test_custodia_pendiente_con_credito_no_cierra_al_devolver_el_dinero(
    cliente,
):
    """Devolver el dinero no alcanza: la custodia sigue sin definir."""
    orden_id = _sin_custodia(cliente)
    pago_id = _pagar(cliente, orden_id, "30000")
    ok(cancelar_orden(cliente, orden_id))

    orden = _reintegrar(cliente, orden_id, pago_id, "30000")

    assert orden["cerrada"] is False
    assert orden["pendientes_de_cierre"][0].startswith(
        "Falta definir la custodia"
    )
    assert ok(no_recibido(cliente, orden_id, MOTIVO))["cerrada"] is True


# --- 8/9. Historial contradictorio -------------------------------------------


def test_8_no_recibido_con_ejecucion_previa_se_rechaza(cliente):
    orden_id = _sin_custodia(cliente)
    tomada(cliente, orden_id)
    ejecucion_id = iniciar(cliente, orden_id)
    ok(
        cerrar_ejecucion(
            cliente, orden_id, ejecucion_id, accion="interrupt", cantidad=""
        )
    )
    orden = ok(cancelar_orden(cliente, orden_id))
    assert orden["cerrada"] is False
    assert "REGISTRAR_EQUIPO_NO_RECIBIDO" not in _custodia(orden)
    assert "registra trabajo" in orden["pendientes_de_cierre"][0]

    mensaje = conflicto(no_recibido(cliente, orden_id, MOTIVO))

    assert f"hubo ejecucion tecnica ({ejecucion_id})" in mensaje
    assert "Regulariza la custodia" in mensaje
    # La regularizacion: confirmar la recepcion y devolver el equipo.
    confirmar_recepcion(cliente, orden_id)
    assert ok(devolver(cliente, orden_id))["cerrada"] is True


def test_9_no_recibido_con_devolucion_o_entrega_anterior_se_rechaza(cliente):
    # Devuelto el equipo, la Orden sigue abierta esperando el dinero.
    devuelta = definida(cliente)
    _pagar(cliente, devuelta, "10000")
    ok(cancelar_orden(cliente, devuelta))
    orden = ok(devolver(cliente, devuelta))
    assert orden["cerrada"] is False
    assert orden["custodia"]["estado"] == "DEVUELTO"
    conflicto(no_recibido(cliente, devuelta, MOTIVO))

    # Entregada: cerrada.
    entregada = definida(cliente)
    tomada(cliente, entregada)
    ejecutar(cliente, entregada)
    ok(
        cliente.post(
            f"/api/orders/{entregada}/control/approve",
            json={"usuario_id": RECEPCION},
        )
    )
    notificar_pagar_entregar(cliente, entregada)
    conflicto(no_recibido(cliente, entregada, MOTIVO), "ORDEN_CERRADA")


# --- 10/11/12 ----------------------------------------------------------------


def test_10_una_orden_cerrada_no_modifica_la_custodia(cliente, tmp_path):
    orden_id = _cancelada_sin_custodia(cliente)
    ok(no_recibido(cliente, orden_id, MOTIVO))
    antes = archivo(tmp_path, orden_id)

    conflicto(no_recibido(cliente, orden_id, "Otro motivo"), "ORDEN_CERRADA")
    conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/reception/confirm",
            json={"usuario_id": RECEPCION},
        ),
        "ORDEN_CERRADA",
    )
    conflicto(
        cliente.put(
            f"/api/orders/{orden_id}/reception",
            json={"usuario_id": RECEPCION, "estado_fisico": "x"},
        ),
        "ORDEN_CERRADA",
    )
    assert _orden(cliente, orden_id)["acciones_custodia"] == []
    assert archivo(tmp_path, orden_id) == antes


def test_11_el_comprobante_no_implica_recepcion_fisica(cliente):
    orden_id = _sin_custodia(cliente)
    orden = _orden(cliente, orden_id)
    assert orden["custodia"]["comprobante_recepcion_emitido"] is True
    assert orden["custodia"]["estado"] == "PENDIENTE_CONFIRMACION"
    documento = ok(cliente.get(f"/api/orders/{orden_id}/documents"))[
        "emitidos"
    ][0]
    assert documento["contenido"]["recepcion_fisica"] == (
        "PENDIENTE_CONFIRMACION"
    )

    # El comprobante no es evidencia de custodia: ni impide "no recibido".
    ok(cancelar_orden(cliente, orden_id))
    orden = ok(no_recibido(cliente, orden_id, MOTIVO))

    assert orden["cerrada"] is True
    # El documento emitido no cambia.
    despues = ok(
        cliente.get(f"/api/orders/{orden_id}/documents/{documento['id']}")
    )
    assert despues["contenido"] == documento["contenido"]


def test_12_ordenes_json_anteriores(cliente, tmp_path):
    ruta = tmp_path / "ordenes"

    def reescribir(orden_id, cambio):
        archivo_orden = ruta / f"{orden_id}.json"
        datos = json.loads(archivo_orden.read_text(encoding="utf-8"))
        cambio(datos)
        archivo_orden.write_text(json.dumps(datos), encoding="utf-8")

    # Registro de recepcion sin el campo nuevo: sigue pendiente.
    pendiente = _sin_custodia(cliente)
    reescribir(pendiente, lambda d: d["recepcion"].pop("no_recibido"))
    assert _orden(cliente, pendiente)["custodia"]["estado"] == (
        "PENDIENTE_CONFIRMACION"
    )

    # Cerrada antes, sin registro de recepcion: nada de "no recibido".
    cerrada = _cancelada_sin_custodia(cliente)
    ok(no_recibido(cliente, cerrada, MOTIVO))
    reescribir(cerrada, lambda d: d.pop("recepcion"))
    orden = _orden(cliente, cerrada)
    assert orden["cerrada"] is True
    assert orden["custodia"]["estado"] == "SIN_REGISTRO"

    # Abierta y sin registro: no cierra hasta decidir; "no recibido" la
    # regulariza sin presumir nada.
    abierta = _cancelada_sin_custodia(cliente)
    reescribir(abierta, lambda d: d.pop("recepcion"))
    orden = _orden(cliente, abierta)
    assert orden["custodia"]["estado"] == "SIN_REGISTRO"
    assert orden["cerrada"] is False
    orden = ok(no_recibido(cliente, abierta, MOTIVO))
    assert orden["recepcion"]["registro"] == "REGULARIZACION"
    assert orden["custodia"]["estado"] == "NO_RECIBIDO"
    assert orden["cerrada"] is True


def test_rt_interno_no_usa_no_recibido(cliente):
    orden_id = ok(
        cliente.post(
            "/api/orders/rt-interno",
            json={
                "usuario_id": RECEPCION,
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 13",
                    "falla_reportada": "No enciende.",
                },
                "referencia_rt": "RT-0001",
            },
        )
    )["id"]
    orden = ok(cancelar_orden(cliente, orden_id))
    # Circuito RT: el equipo se devuelve a Gestion RT, como siempre.
    assert orden["devolucion_pendiente"] is True

    assert "Gestion RT" in conflicto(no_recibido(cliente, orden_id, MOTIVO))
