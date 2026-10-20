"""PROC-REP-300: cancelacion individual de un Detalle (BR-REP-014).

Un Detalle PENDIENTE (DEFINIDO, sin Ejecucion activa) pasa a CANCELADO
con motivo obligatorio: no se borra, conserva su Tipo, su precio snapshot
y todo su historial. Un Detalle COMPLETO o en ejecucion no se cancela. La
Orden se reevalua (PROC-REP-211): los demas Detalles siguen su curso, y si
todos quedan CANCELADO la Orden sigue por el circuito de cancelacion.

    HTTP -> router -> application -> services -> repositories -> JSON
"""

from decimal import Decimal

import pytest

from tests.fixtures.api_salidas import (
    BATERIA,
    COORDINADOR,
    INSUMO_BATERIA,
    MOTIVO,
    PANTALLA,
    TECNICO,
    agregar,
    aprobar,
    archivo,
    cancelar_detalle,
    cerrar_ejecucion,
    cliente_http,
    codigos,
    codigos_cancelacion,
    conflicto,
    crear,
    definida,
    detalle,
    ejecutar,
    ids,
    iniciar,
    notificar_pagar_entregar,
    ok,
    repo_ordenes,
    stock,
    tomada,
)


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def test_cancelar_un_detalle_pendiente(cliente):
    orden_id = crear(cliente)
    agregar(cliente, orden_id, BATERIA)
    agregar(cliente, orden_id, PANTALLA)

    orden = ok(cancelar_detalle(cliente, orden_id, "DET-001"))

    cancelado = detalle(orden, "DET-001")
    assert cancelado["estado"] == "CANCELADO"
    assert cancelado["cancelacion"]["motivo"] == MOTIVO
    assert cancelado["cancelacion"]["usuario_id"] == "RECEP-001"
    assert cancelado["cancelacion"]["fecha"] is not None
    # No se borra: conserva Tipo y precio snapshot.
    assert cancelado["tipo_reparacion_id"] == BATERIA
    assert cancelado["precio"] == "80000"
    # Los demas no se tocan.
    assert detalle(orden, "DET-002")["estado"] == "DEFINIDO"
    assert ids(orden)[-2:] == ["PROC-REP-300", "PROC-REP-211"]
    paso_300 = orden["historial"][-2]
    assert paso_300["reparacion_detail_id"] == "DET-001"
    assert paso_300["usuario_id"] == "RECEP-001"
    assert MOTIVO in paso_300["observacion"]
    # Un Detalle cancelado no se cobra.
    assert Decimal(orden["resumen"]["total"]) == Decimal("50000")
    # La definicion sigue abierta para el Detalle vigente (ingreso inicial:
    # se cierra con el comprobante de ingreso).
    assert "GENERAR_COMPROBANTE_INGRESO" in codigos(orden)
    assert ("CANCELAR_DETALLE", "DET-001") not in codigos_cancelacion(orden)
    assert ("CANCELAR_DETALLE", "DET-002") in codigos_cancelacion(orden)


def test_el_motivo_es_obligatorio(cliente, tmp_path):
    orden_id = crear(cliente)
    agregar(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    assert (
        cancelar_detalle(cliente, orden_id, "DET-001", "").status_code == 422
    )
    conflicto(cancelar_detalle(cliente, orden_id, "DET-001", "   "))

    assert archivo(tmp_path, orden_id) == antes


def test_solo_roles_autorizados_cancelan(cliente, tmp_path):
    orden_id = crear(cliente)
    agregar(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    conflicto(cancelar_detalle(cliente, orden_id, "DET-001", usuario=TECNICO))
    assert archivo(tmp_path, orden_id) == antes
    ok(cancelar_detalle(cliente, orden_id, "DET-001", usuario=COORDINADOR))


def test_un_detalle_cancelado_no_se_cancela_dos_veces(cliente, tmp_path):
    orden_id = crear(cliente)
    agregar(cliente, orden_id, BATERIA)
    agregar(cliente, orden_id, PANTALLA)
    ok(cancelar_detalle(cliente, orden_id, "DET-001"))
    antes = archivo(tmp_path, orden_id)

    conflicto(cancelar_detalle(cliente, orden_id, "DET-001"))

    assert archivo(tmp_path, orden_id) == antes


def test_un_detalle_inexistente_es_404(cliente):
    orden_id = crear(cliente)
    agregar(cliente, orden_id)

    assert cancelar_detalle(cliente, orden_id, "DET-999").status_code == 404


def test_no_se_cancela_un_detalle_completo(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id, "DET-001")
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(cancelar_detalle(cliente, orden_id, "DET-001"))

    assert "COMPLETO" in mensaje
    assert archivo(tmp_path, orden_id) == antes


def test_no_se_cancela_un_detalle_con_ejecucion_activa(cliente, tmp_path):
    orden_id = definida(cliente)
    tomada(cliente, orden_id)
    iniciar(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(cancelar_detalle(cliente, orden_id, "DET-001"))

    assert "interrump" in mensaje.lower()
    # Reservas y movimientos intactos hasta conciliar.
    assert archivo(tmp_path, orden_id) == antes
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    assert orden["ejecuciones"][0]["estado"] == "EN_PROGRESO"
    assert ("CANCELAR_DETALLE", "DET-001") not in codigos_cancelacion(orden)


def test_cancelacion_parcial_con_otro_detalle_trabajable(cliente):
    """DET-001 cancelado con la Orden tomada: DET-002 sigue normalmente."""
    orden_id = definida(cliente, BATERIA, PANTALLA)
    tomada(cliente, orden_id)

    orden = ok(cancelar_detalle(cliente, orden_id, "DET-001"))

    assert orden["historial"][-1]["observacion"] == "ABIERTA_TRABAJABLE"
    assert orden["toma_activa"]["usuario_id"] == TECNICO
    assert ("INICIAR_DETALLE", "DET-002") in [
        (a["codigo"], a["detalle_id"]) for a in orden["acciones_disponibles"]
    ]
    assert "DET-001" not in [
        a["detalle_id"]
        for a in orden["acciones_disponibles"]
        if a["codigo"] == "INICIAR_DETALLE"
    ]
    orden = ejecutar(cliente, orden_id, "DET-002", PANTALLA)
    assert detalle(orden, "DET-002")["estado"] == "COMPLETO"


def test_completo_y_cancelado_avanzan_a_control_y_entrega(cliente):
    """DET-001 COMPLETO y DET-002 cancelado: control, cobro y entrega."""
    orden_id = definida(cliente, BATERIA, PANTALLA)
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id, "DET-001")

    orden = ok(cancelar_detalle(cliente, orden_id, "DET-002"))

    assert orden["historial"][-1]["observacion"] == "COMPLETA"
    assert orden["toma_activa"] is None
    assert [
        (a["codigo"], a["detalle_id"])
        for a in orden["acciones_disponibles"]
        if a["codigo"].endswith("_CONTROL")
    ] == [
        ("APROBAR_CONTROL", "DET-001"),
        ("RECHAZAR_CONTROL", "DET-001"),
    ]
    orden = ok(aprobar(cliente, orden_id, "DET-001"))
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    # Solo se cobra lo efectivamente realizado.
    assert Decimal(orden["resumen"]["total"]) == Decimal("80000")
    entregada = notificar_pagar_entregar(cliente, orden_id)
    assert entregada["estado_workflow"] == "ENTREGADA"
    assert detalle(entregada, "DET-002")["estado"] == "CANCELADO"


def test_todos_los_detalles_cancelados_llevan_a_la_cancelacion_de_la_orden(
    cliente,
):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    ok(cancelar_detalle(cliente, orden_id, "DET-001"))

    orden = ok(cancelar_detalle(cliente, orden_id, "DET-002"))

    assert orden["historial"][-1]["observacion"] == "TODO_CANCELADO"
    assert orden["estado_workflow"] == "CANCELADA"
    # La recepcion fisica se confirmo: el equipo esta en custodia y hay que
    # devolverlo antes del cierre operativo.
    assert orden["cerrada"] is False
    assert orden["devolucion_pendiente"] is True
    assert codigos(orden) == ["REGISTRAR_DEVOLUCION"]
    assert codigos_cancelacion(orden) == []


def test_cancelar_conserva_ejecuciones_y_movimientos(cliente, tmp_path):
    """Un Detalle interrumpido conserva su Ejecucion y su inventario."""
    orden_id = definida(cliente, BATERIA, PANTALLA)
    tomada(cliente, orden_id)
    ejecucion_id = iniciar(cliente, orden_id, "DET-001")
    ok(
        cerrar_ejecucion(
            cliente, orden_id, ejecucion_id, accion="interrupt", cantidad="1"
        )
    )
    previa = repo_ordenes(tmp_path).obtener(orden_id)
    movimientos = [m.model_dump() for m in previa.movimientos_insumo]
    ejecuciones = [e.model_dump() for e in previa.ejecuciones]
    historial = [p.model_dump() for p in previa.historial]

    ok(cancelar_detalle(cliente, orden_id, "DET-001"))

    actual = repo_ordenes(tmp_path).obtener(orden_id)
    assert [m.model_dump() for m in actual.movimientos_insumo] == movimientos
    assert [e.model_dump() for e in actual.ejecuciones] == ejecuciones
    assert [p.model_dump() for p in actual.historial][: len(historial)] == (
        historial
    )
    assert stock(tmp_path, INSUMO_BATERIA) == Decimal("4")  # lo consumido
    assert actual.reparaciones_detail[0].estado.value == "CANCELADO"
