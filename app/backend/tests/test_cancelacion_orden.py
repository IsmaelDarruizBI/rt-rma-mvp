"""PROC-REP-305 / 306: cancelacion de la Orden y devolucion del equipo.

PROC-REP-305 cancela los Detalles PENDIENTE de la Orden y deja COMPLETO lo
que ya se hizo; el resolver (PROC-REP-211) decide el desenlace: CANCELADA
si todos quedan CANCELADO, o el cierre normal (control, cobro, entrega)
si hay trabajo realizado. Una Orden sin Detalles se cancela de forma
explicita (PROC-REP-306, V1.4). Con una Ejecucion activa no se cancela
nada. Una Orden CANCELADA no es ENTREGADA: si el equipo esta en custodia,
su devolucion fisica (PROC-REP-270, sin cobro) se registra antes del
cierre operativo (EVT-REP-999).
"""

from decimal import Decimal

import pytest

from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    COORDINADOR,
    MOTIVO,
    PANTALLA,
    RECEPCION,
    TECNICO,
    aprobar,
    archivo,
    cancelar_detalle,
    cancelar_orden,
    cliente_http,
    codigos,
    codigos_cancelacion,
    conflicto,
    crear,
    definida,
    detalle,
    devolver,
    ejecutar,
    encolar,
    finalizar,
    ids,
    iniciar,
    notificar_pagar_entregar,
    ok,
    repo_ordenes,
    tomada,
)
from tests.fixtures.custodia import confirmar_recepcion, no_recibido


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


# --- Sin Detalles ------------------------------------------------------------


def test_una_orden_sin_detalles_se_cancela_explicitamente(cliente):
    """Recien creada, sin decision de custodia: no cierra sola.

    Cierra cuando Recepcion registra que el equipo nunca ingreso (o, si lo
    tiene, confirma la recepcion y lo devuelve).
    """
    orden_id = crear(cliente)
    assert ("CANCELAR_ORDEN", None) in codigos_cancelacion(
        cliente.get(f"/api/orders/{orden_id}").json()
    )

    orden = ok(cancelar_orden(cliente, orden_id))

    assert orden["estado_workflow"] == "CANCELADA"
    assert ids(orden)[-1] == "PROC-REP-306"
    paso = orden["historial"][-1]
    assert paso["usuario_id"] == RECEPCION and MOTIVO in paso["observacion"]
    assert orden["current_process"] == "PROC-REP-306"
    assert orden["devolucion_pendiente"] is False
    assert orden["cerrada"] is False
    assert orden["acciones_disponibles"] == []
    assert "Falta definir la custodia" in orden["pendientes_de_cierre"][0]

    orden = ok(no_recibido(cliente, orden_id))

    assert orden["current_process"] == "EVT-REP-999"
    assert orden["cerrada"] is True
    assert orden["custodia"]["estado"] == "NO_RECIBIDO"
    conflicto(cancelar_orden(cliente, orden_id), "ORDEN_CERRADA")


def test_sin_detalles_en_revision_requiere_devolver_el_equipo(cliente):
    """EN_REVISION con la recepcion confirmada: el equipo esta en custodia.

    La custodia sale de la confirmacion, no del comprobante emitido al
    enviar a revision.
    """
    orden_id = crear(cliente)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/send-to-review",
            json={"usuario_id": RECEPCION},
        )
    )
    confirmar_recepcion(cliente, orden_id)

    orden = ok(cancelar_orden(cliente, orden_id))

    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["devolucion_pendiente"] is True
    assert orden["cerrada"] is False
    assert codigos(orden) == ["REGISTRAR_DEVOLUCION"]


# --- Con Detalles ------------------------------------------------------------


def test_cancelar_la_orden_cancela_todos_los_pendientes(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA, PANTALLA)

    orden = ok(cancelar_orden(cliente, orden_id))

    assert [d["estado"] for d in orden["reparaciones_detail"]] == [
        "CANCELADO",
        "CANCELADO",
    ]
    assert all(
        d["cancelacion"]["motivo"] == MOTIVO
        for d in orden["reparaciones_detail"]
    )
    assert ids(orden)[-2:] == ["PROC-REP-305", "PROC-REP-211"]
    assert orden["historial"][-1]["observacion"] == "TODO_CANCELADO"
    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["devolucion_pendiente"] is True
    # Nada que cobrar: total 0, y no figura PAGADA sin haber pagado.
    assert Decimal(orden["resumen"]["total"]) == Decimal("0")
    assert orden["resumen"]["estado_pago"] == "PENDIENTE"
    # Nada se borra: prioridad, habilitacion e historial se conservan.
    assert "PROC-REP-140" in ids(orden)


def test_completos_y_pendientes_cancela_solo_los_pendientes(cliente):
    """Con trabajo realizado la Orden NO queda CANCELADA: sigue el cierre."""
    orden_id = definida(cliente, BATERIA, PANTALLA)
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id, "DET-001")

    orden = ok(cancelar_orden(cliente, orden_id))

    assert detalle(orden, "DET-001")["estado"] == "COMPLETO"
    assert detalle(orden, "DET-002")["estado"] == "CANCELADO"
    assert orden["estado_workflow"] == "EN_REPARACION"
    assert orden["historial"][-1]["observacion"] == "COMPLETA"
    assert orden["toma_activa"] is None
    orden = ok(aprobar(cliente, orden_id, "DET-001"))
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    entregada = notificar_pagar_entregar(cliente, orden_id)
    assert entregada["estado_workflow"] == "ENTREGADA"
    assert Decimal(entregada["resumen"]["total"]) == Decimal("80000")


def test_con_ejecucion_activa_no_se_cancela_nada(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    tomada(cliente, orden_id)
    iniciar(cliente, orden_id, "DET-001")
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(cancelar_orden(cliente, orden_id))

    assert "Ejecucion activa" in mensaje
    assert "interrump" in mensaje.lower()
    # Reservas, Ejecucion y Detalles intactos hasta su conciliacion.
    assert archivo(tmp_path, orden_id) == antes
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    assert ("CANCELAR_ORDEN", None) not in codigos_cancelacion(orden)


def test_no_hay_pendientes_que_cancelar(cliente, tmp_path):
    orden_id = definida(cliente)
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id, "DET-001")
    antes = archivo(tmp_path, orden_id)

    conflicto(cancelar_orden(cliente, orden_id))

    assert archivo(tmp_path, orden_id) == antes


def test_roles_y_motivo(cliente, tmp_path):
    orden_id = definida(cliente)
    antes = archivo(tmp_path, orden_id)

    conflicto(cancelar_orden(cliente, orden_id, usuario=TECNICO))
    conflicto(cancelar_orden(cliente, orden_id, motivo="  "))
    assert cancelar_orden(cliente, orden_id, motivo="").status_code == 422
    assert archivo(tmp_path, orden_id) == antes

    ok(cancelar_orden(cliente, orden_id, usuario=COORDINADOR))
    # Ya CANCELADA: no se cancela de nuevo.
    conflicto(cancelar_orden(cliente, orden_id))


def test_no_se_cancela_una_orden_entregada(cliente, tmp_path):
    orden_id = definida(cliente)
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id, "DET-001")
    ok(aprobar(cliente, orden_id, "DET-001"))
    notificar_pagar_entregar(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    conflicto(cancelar_orden(cliente, orden_id), "ORDEN_CERRADA")
    conflicto(cancelar_detalle(cliente, orden_id, "DET-001"), "ORDEN_CERRADA")

    assert archivo(tmp_path, orden_id) == antes


def test_una_orden_lista_no_se_cancela(cliente, tmp_path):
    orden_id = definida(cliente)
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id, "DET-001")
    ok(aprobar(cliente, orden_id, "DET-001"))
    antes = archivo(tmp_path, orden_id)

    conflicto(cancelar_orden(cliente, orden_id))

    assert archivo(tmp_path, orden_id) == antes
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    assert codigos_cancelacion(orden) == []


# --- Devolucion fisica -------------------------------------------------------


def test_devolucion_fisica_despues_de_cancelar(cliente, tmp_path):
    orden_id = definida(cliente)
    orden = ok(cancelar_orden(cliente, orden_id))
    assert orden["estado_workflow"] == "CANCELADA"

    # Una Orden CANCELADA no es ENTREGADA: no se notifica, cobra ni entrega.
    conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={"usuario_id": RECEPCION, "monto": "1", "metodo": "EFECTIVO"},
        )
    )
    conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": ADMINISTRADOR},
        )
    )
    conflicto(devolver(cliente, orden_id, usuario=TECNICO))
    conflicto(devolver(cliente, orden_id, recibido_por="  "))

    orden = ok(devolver(cliente, orden_id, recibido_por="Juan Perez"))

    assert orden["estado_workflow"] == "CANCELADA"  # nunca ENTREGADA
    assert orden["current_process"] == "EVT-REP-999"
    assert orden["cerrada"] is True
    assert orden["devolucion_pendiente"] is False
    devolucion = orden["devolucion"]
    assert devolucion["entregado_por"] == RECEPCION
    assert devolucion["recibido_por"] == "Juan Perez"
    assert devolucion["fecha"] is not None
    paso = orden["historial"][-1]
    assert (paso["referencia_id"], paso["accion"]) == (
        "PROC-REP-270",
        "DEVOLVER_EQUIPO_SIN_REPARAR",
    )
    assert "Juan Perez" in paso["observacion"]
    # Sin cobro ni documentos comerciales por cancelar.
    assert orden["pagos"] == []
    assert orden["documentos"]["comprobante_final"]["generado"] is False
    # No se registra una segunda devolucion.
    conflicto(devolver(cliente, orden_id), "ORDEN_CERRADA")


def test_sin_custodia_no_hay_devolucion_que_registrar(cliente):
    orden_id = crear(cliente)
    ok(cancelar_orden(cliente, orden_id))

    assert "custodia confirmada" in conflicto(devolver(cliente, orden_id))
    ok(no_recibido(cliente, orden_id))
    conflicto(devolver(cliente, orden_id), "ORDEN_CERRADA")


def test_una_orden_rt_cancelada_se_devuelve_a_gestion_rt(cliente):
    respuesta = cliente.post(
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
    orden_id = ok(respuesta)["id"]

    orden = ok(cancelar_orden(cliente, orden_id))
    assert orden["devolucion_pendiente"] is True

    orden = ok(devolver(cliente, orden_id, recibido_por="Gestion RT"))
    assert orden["cerrada"] is True
    assert orden["devolucion"]["recibido_por"] == "Gestion RT"


def test_un_anticipo_queda_registrado_sin_cobro_adicional(cliente, tmp_path):
    """La devolucion de dinero sigue pendiente (V1.4 PROC-REP-267/268)."""
    orden_id = definida(cliente)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": RECEPCION,
                "monto": "10000",
                "metodo": "EFECTIVO",
            },
        )
    )

    orden = ok(cancelar_orden(cliente, orden_id))

    assert len(orden["pagos"]) == 1
    assert Decimal(orden["resumen"]["total"]) == Decimal("0")
    assert Decimal(orden["resumen"]["saldo"]) == Decimal("-10000")
    assert "REGISTRAR_PAGO" not in codigos(orden)


# --- Circuito completo -------------------------------------------------------


def test_circuito_ingreso_definicion_cancelacion_devolucion_cierre(
    cliente, tmp_path
):
    orden_id = crear(cliente)
    confirmar_recepcion(cliente, orden_id)
    for tipo in (BATERIA, PANTALLA):
        ok(
            cliente.post(
                f"/api/orders/{orden_id}/details",
                json={"usuario_id": RECEPCION, "tipo_reparacion_id": tipo},
            )
        )
    # Comprobante de ingreso: confirma, autoriza y entra a la cola.
    en_cola = finalizar(cliente, orden_id)
    assert en_cola["estado_workflow"] == "EN_COLA"
    ok(encolar(cliente, orden_id, 2))

    cancelada = ok(cancelar_orden(cliente, orden_id, "El cliente desiste."))
    assert cancelada["estado_workflow"] == "CANCELADA"
    assert cancelada["prioridad"] == 2

    cerrada = ok(devolver(cliente, orden_id, recibido_por="Cliente"))
    assert cerrada["cerrada"] is True
    assert cerrada["acciones_disponibles"] == []
    assert cerrada["acciones_cancelacion"] == []

    persistida = repo_ordenes(tmp_path).obtener(orden_id)
    assert persistida.current_process == "EVT-REP-999"
    # Solo los nodos del proceso (el cambio de prioridad es transversal).
    assert [p.process_id for p in persistida.historial if p.process_id][
        -4:
    ] == [
        "PROC-REP-170",
        "PROC-REP-305",
        "PROC-REP-211",
        "PROC-REP-270",
    ]
    # Cualquier otro comando queda rechazado: la Orden esta cerrada.
    conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": TECNICO, "estacion_id": "EST-001"},
        ),
        "ORDEN_CERRADA",
    )
