"""PROC-REP-230 "No" -> 235 -> 211: rechazo del control y retrabajo.

Recepcion rechaza, con motivo, el resultado tecnico de UN Detalle
COMPLETO. Ese Detalle -y solo ese- se reabre (vuelve a PENDIENTE) para
una Ejecucion NUEVA: las anteriores y el rechazo quedan en el historial,
y los Detalles aprobados siguen aprobados. La Orden vuelve a la cola
(PROC-REP-211 -> 170) y no llega a REPARACION_LISTA ni a la entrega hasta
que el retrabajo se apruebe.

E14 (auditoria): una aprobacion registrada no se vuelve a escribir. Las
aprobaciones y los rechazos son eventos que se acumulan en
``controles``; aprobar despues de un retrabajo es un control nuevo.
"""

import json
from decimal import Decimal

import pytest

from tests.fixtures.api_salidas import (
    BATERIA,
    INSUMO_BATERIA,
    PANTALLA,
    RECEPCION,
    TECNICO,
    TECNICO_B,
    aprobar,
    archivo,
    cerrar_ejecucion,
    cliente_http,
    codigos,
    conflicto,
    definida,
    detalle,
    ejecutar,
    ids,
    iniciar,
    notificar_pagar_entregar,
    ok,
    rechazar,
    stock,
    tomada,
    tomar,
)

MOTIVO_RECHAZO = "La bateria no carga."


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def _lista_para_control(cliente, *tipos) -> str:
    orden_id = definida(cliente, *tipos)
    tomada(cliente, orden_id)
    for numero, tipo in enumerate(tipos or (BATERIA,), start=1):
        ejecutar(cliente, orden_id, f"DET-{numero:03d}", tipo)
    return orden_id


def test_el_control_ofrece_aprobar_y_rechazar(cliente):
    orden_id = _lista_para_control(cliente)

    orden = cliente.get(f"/api/orders/{orden_id}").json()

    assert [
        (a["codigo"], a["detalle_id"], a["roles"])
        for a in orden["acciones_disponibles"]
        if a["codigo"].endswith("_CONTROL")
    ] == [
        ("APROBAR_CONTROL", "DET-001", ["RECEPCION"]),
        ("RECHAZAR_CONTROL", "DET-001", ["RECEPCION"]),
    ]


def test_el_motivo_del_rechazo_es_obligatorio(cliente, tmp_path):
    orden_id = _lista_para_control(cliente)
    antes = archivo(tmp_path, orden_id)

    assert rechazar(cliente, orden_id, "DET-001", motivo="").status_code == 422
    conflicto(rechazar(cliente, orden_id, "DET-001", motivo="   "))
    conflicto(rechazar(cliente, orden_id, "DET-001", usuario=TECNICO))

    assert archivo(tmp_path, orden_id) == antes


def test_rechazar_reabre_solo_ese_detalle_y_vuelve_a_la_cola(cliente):
    orden_id = _lista_para_control(cliente)

    orden = ok(rechazar(cliente, orden_id, "DET-001", MOTIVO_RECHAZO))

    rechazado = detalle(orden, "DET-001")
    assert rechazado["estado"] == "DEFINIDO"
    assert rechazado["control_estado"] == "PENDIENTE"
    assert rechazado["pendiente_de_retrabajo"] is True
    (control,) = rechazado["controles"]
    assert control["resultado"] == "RECHAZADO"
    assert control["usuario_id"] == RECEPCION
    assert control["observaciones"] == MOTIVO_RECHAZO
    assert control["ejecucion_id"] == orden["ejecuciones"][0]["id"]
    assert ids(orden)[-5:] == [
        "PROC-REP-220",
        "PROC-REP-230",
        "PROC-REP-235",
        "PROC-REP-211",
        "PROC-REP-170",
    ]
    assert orden["historial"][-4]["observacion"] == "No"
    assert MOTIVO_RECHAZO in orden["historial"][-3]["observacion"]
    assert orden["historial"][-2]["observacion"] == "ABIERTA_TRABAJABLE"
    # La Orden vuelve a la cola, con su prioridad y sin toma.
    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["prioridad"] == 3
    assert orden["toma_activa"] is None
    assert codigos(orden)[0] == "TOMAR"
    # La Ejecucion anterior no se toca.
    assert [e["estado"] for e in orden["ejecuciones"]] == ["COMPLETADO"]


def test_no_avanza_a_entrega_con_un_control_rechazado(cliente, tmp_path):
    orden_id = _lista_para_control(cliente)
    orden = ok(rechazar(cliente, orden_id, "DET-001", MOTIVO_RECHAZO))
    assert orden["estado_workflow"] != "REPARACION_LISTA"
    antes = archivo(tmp_path, orden_id)

    conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )
    conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": "ADMIN-001"},
        )
    )
    conflicto(aprobar(cliente, orden_id, "DET-001"))  # todavia sin retrabajo

    assert archivo(tmp_path, orden_id) == antes


def test_circuito_rechazo_retrabajo_aprobacion_entrega(cliente, tmp_path):
    """Ingreso -> ... -> ejecucion -> rechazo -> retrabajo -> entrega."""
    orden_id = _lista_para_control(cliente)
    assert stock(tmp_path, INSUMO_BATERIA) == Decimal("4")
    ok(rechazar(cliente, orden_id, "DET-001", MOTIVO_RECHAZO))

    # Otro tecnico puede tomar el retrabajo: es una participacion nueva.
    tomar(cliente, orden_id, TECNICO_B)
    nueva = iniciar(cliente, orden_id, "DET-001", TECNICO_B)
    orden = ok(cerrar_ejecucion(cliente, orden_id, nueva, tecnico=TECNICO_B))
    primera, segunda = orden["ejecuciones"]
    assert primera["estado"] == segunda["estado"] == "COMPLETADO"
    assert (primera["usuario_id"], segunda["usuario_id"]) == (
        TECNICO,
        TECNICO_B,
    )
    assert segunda["id"] == nueva != primera["id"]
    assert stock(tmp_path, INSUMO_BATERIA) == Decimal("3")  # nueva reserva
    reabierto = detalle(orden, "DET-001")
    assert reabierto["estado"] == "COMPLETO"
    assert reabierto["pendiente_de_retrabajo"] is False

    # Vuelve a control: aprobar el retrabajo es un control NUEVO.
    orden = ok(aprobar(cliente, orden_id, "DET-001"))
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    controles = detalle(orden, "DET-001")["controles"]
    assert [c["resultado"] for c in controles] == ["RECHAZADO", "APROBADO"]
    assert controles[1]["ejecucion_id"] == segunda["id"]

    entregada = notificar_pagar_entregar(cliente, orden_id)
    assert entregada["estado_workflow"] == "ENTREGADA"
    # Se cobra una sola vez el Detalle, aunque se haya ejecutado dos.
    assert Decimal(entregada["resumen"]["total"]) == Decimal("80000")


def test_rechazar_uno_no_reabre_ni_desaprueba_los_otros(cliente):
    orden_id = _lista_para_control(cliente, BATERIA, PANTALLA)
    aprobado = detalle(ok(aprobar(cliente, orden_id, "DET-001")), "DET-001")
    assert aprobado["control_estado"] == "APROBADO"

    orden = ok(rechazar(cliente, orden_id, "DET-002", "Pantalla con manchas."))

    # DET-001 conserva su aprobacion intacta.
    assert detalle(orden, "DET-001") == aprobado
    assert detalle(orden, "DET-001")["estado"] == "COMPLETO"
    assert detalle(orden, "DET-002")["estado"] == "DEFINIDO"
    assert orden["estado_workflow"] == "EN_COLA"

    # Tras el retrabajo solo se controla DET-002.
    tomar(cliente, orden_id)
    orden = ejecutar(cliente, orden_id, "DET-002", PANTALLA)
    assert [
        (a["codigo"], a["detalle_id"])
        for a in orden["acciones_disponibles"]
        if a["codigo"].endswith("_CONTROL")
    ] == [
        ("APROBAR_CONTROL", "DET-002"),
        ("RECHAZAR_CONTROL", "DET-002"),
    ]
    orden = ok(aprobar(cliente, orden_id, "DET-002"))
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    assert detalle(orden, "DET-001")["controles"] == aprobado["controles"]


def test_no_se_rechaza_un_detalle_ya_aprobado(cliente, tmp_path):
    orden_id = _lista_para_control(cliente, BATERIA, PANTALLA)
    ok(aprobar(cliente, orden_id, "DET-001"))
    antes = archivo(tmp_path, orden_id)

    conflicto(rechazar(cliente, orden_id, "DET-001"))

    assert archivo(tmp_path, orden_id) == antes


def test_no_se_rechaza_antes_del_control(cliente, tmp_path):
    """Con un Detalle todavia sin ejecutar no hay control que rechazar."""
    orden_id = definida(cliente, BATERIA, PANTALLA)
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id, "DET-001")
    antes = archivo(tmp_path, orden_id)

    conflicto(rechazar(cliente, orden_id, "DET-001"))

    assert archivo(tmp_path, orden_id) == antes


# --- E14: la aprobacion no se sobrescribe ------------------------------------


def test_e14_una_aprobacion_no_se_vuelve_a_escribir(cliente, tmp_path):
    orden_id = _lista_para_control(cliente, BATERIA, PANTALLA)
    primera = detalle(ok(aprobar(cliente, orden_id, "DET-001")), "DET-001")
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(aprobar(cliente, orden_id, "DET-001"))

    assert "ya fue aprobado" in mensaje
    assert archivo(tmp_path, orden_id) == antes
    actual = detalle(cliente.get(f"/api/orders/{orden_id}").json(), "DET-001")
    assert actual["control_usuario_id"] == primera["control_usuario_id"]
    assert actual["control_fecha"] == primera["control_fecha"]
    assert len(actual["controles"]) == 1


def test_e14_la_aprobacion_en_bloque_no_pisa_las_ya_registradas(
    cliente, tmp_path
):
    orden_id = _lista_para_control(cliente, BATERIA, PANTALLA)
    primera = detalle(ok(aprobar(cliente, orden_id, "DET-001")), "DET-001")

    orden = ok(aprobar(cliente, orden_id, None))  # sin detalle_id

    assert (
        detalle(orden, "DET-001")["control_fecha"] == primera["control_fecha"]
    )
    assert len(detalle(orden, "DET-001")["controles"]) == 1
    assert detalle(orden, "DET-002")["control_estado"] == "APROBADO"
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    # Ya no queda nada por aprobar.
    conflicto(aprobar(cliente, orden_id, None))


def test_un_json_anterior_sin_controles_ni_cancelacion_sigue_cargando(
    cliente, tmp_path
):
    """Detalles sin ``controles``/``cancelacion``; Orden sin ``devolucion``."""
    orden_id = _lista_para_control(cliente)
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos.pop("devolucion")
    for item in datos["reparaciones_detail"]:
        item.pop("controles")
        item.pop("cancelacion")
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    orden = ok(aprobar(cliente, orden_id, "DET-001"))

    assert orden["estado_workflow"] == "REPARACION_LISTA"
    assert [
        c["resultado"] for c in detalle(orden, "DET-001")["controles"]
    ] == ["APROBADO"]
