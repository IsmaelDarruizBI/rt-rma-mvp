"""Cancelacion de Detalles y de la Orden (DC31, 09/11/2026).

- Cancelar un Detalle cancela solo ese Detalle y NUNCA la Orden. Si todos
  quedan CANCELADO la Orden sigue abierta: SIN_TRABAJOS_VIGENTES
  (PROC-REP-307), sin trabajo tecnico.
- Cancelar la Orden es explicito y terminal (PROC-REP-308, o 306 sin
  Detalles): exige sin Ejecucion, toma, reservas ni saldo, la custodia
  resuelta (si el equipo ingreso, ya devuelto) y ningun Detalle COMPLETO;
  si algo falla no cambia nada. Cancela lo pendiente, fija CANCELADA y
  cierra la Orden en el mismo acto.
- La devolucion fisica (PROC-REP-270) se registra ANTES de cancelar, con la
  Orden sin trabajos pendientes: no cobra, no da garantia ni comprobante de
  entrega.

Las Ordenes CANCELADA y abiertas del circuito anterior estan en
``test_cancelacion_heredada.py``.
"""

from decimal import Decimal

import pytest

from app.domain.models import OrdenReparacion
from app.services import impedimentos_cancelacion
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    COORDINADOR,
    MOTIVO,
    PANTALLA,
    RECEPCION,
    TECNICO,
    agregar,
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
    ids,
    iniciar,
    notificar_pagar_entregar,
    ok,
    repo_ordenes,
    tomada,
)
from tests.fixtures.custodia import confirmar_recepcion, entregar, no_recibido


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _cancelar_orden_accion(orden: dict) -> dict | None:
    return next(
        (
            a
            for a in orden["acciones_cancelacion"]
            if a["codigo"] == "CANCELAR_ORDEN"
        ),
        None,
    )


def _sin_acciones(orden: dict) -> None:
    for grupo in (
        "acciones_disponibles",
        "acciones_cancelacion",
        "acciones_autorizacion",
        "acciones_financieras",
        "acciones_custodia",
        "acciones_complementarias",
    ):
        assert orden[grupo] == [], grupo


def _cancelar_todos_los_trabajos(cliente, orden_id) -> dict:
    orden = _orden(cliente, orden_id)
    for d in orden["reparaciones_detail"]:
        if d["estado"] == "DEFINIDO":
            orden = ok(cancelar_detalle(cliente, orden_id, d["id"]))
    return orden


# --- Cancelar Detalles no cancela la Orden -----------------------------------


def test_cancelar_un_detalle_entre_varios(cliente):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    antes = _orden(cliente, orden_id)["estado_workflow"]

    orden = ok(cancelar_detalle(cliente, orden_id, "DET-001"))

    assert detalle(orden, "DET-001")["estado"] == "CANCELADO"
    assert detalle(orden, "DET-002")["estado"] == "DEFINIDO"
    assert orden["estado_workflow"] == antes != "CANCELADA"
    assert orden["situacion"]["codigo"] != "SIN_TRABAJOS_VIGENTES"
    assert orden["cerrada"] is False


def test_cancelar_el_ultimo_detalle_deja_la_orden_sin_trabajos_vigentes(
    cliente,
):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    estado = _orden(cliente, orden_id)["estado_workflow"]

    orden = _cancelar_todos_los_trabajos(cliente, orden_id)

    assert [d["estado"] for d in orden["reparaciones_detail"]] == [
        "CANCELADO",
        "CANCELADO",
    ]
    # La Orden NO se cancela ni se cierra: queda abierta sin trabajo.
    assert orden["estado_workflow"] == estado
    assert orden["estado_workflow"] != "CANCELADA"
    assert orden["cerrada"] is False
    assert ids(orden)[-2:] == ["PROC-REP-211", "PROC-REP-307"]
    assert orden["situacion"]["codigo"] == "SIN_TRABAJOS_VIGENTES"
    # Sin trabajo tecnico: solo devolver el equipo (esta en el local).
    assert codigos(orden) == ["REGISTRAR_DEVOLUCION"]
    assert orden["toma_activa"] is None
    # Cancelar la Orden se ofrece, pero bloqueado hasta devolver el equipo.
    cancelar = _cancelar_orden_accion(orden)
    assert cancelar is not None and "devolucion" in cancelar["bloqueo"]
    # El historial de cada Detalle se conserva.
    assert all(
        d["cancelacion"]["motivo"] == MOTIVO
        for d in orden["reparaciones_detail"]
    )
    assert "PROC-REP-140" in ids(orden)


# --- Cancelacion explicita y terminal ----------------------------------------


def test_sin_trabajos_vigentes_devuelve_y_cancela(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    _cancelar_todos_los_trabajos(cliente, orden_id)

    # Con el equipo en el local no se puede cancelar: no cambia nada.
    antes = archivo(tmp_path, orden_id)
    mensaje = conflicto(cancelar_orden(cliente, orden_id))
    assert "devolucion" in mensaje and "No se cancelo nada" in mensaje
    assert archivo(tmp_path, orden_id) == antes

    # La devolucion fisica no es una entrega: sin cobro ni comprobante.
    conflicto(devolver(cliente, orden_id, usuario=TECNICO))
    conflicto(devolver(cliente, orden_id, recibido_por="  "))
    orden = ok(devolver(cliente, orden_id, recibido_por="Juan Perez"))
    assert orden["estado_workflow"] != "CANCELADA"
    assert orden["cerrada"] is False
    assert orden["devolucion"]["recibido_por"] == "Juan Perez"
    assert orden["pagos"] == []
    assert orden["documentos"]["comprobante_final"]["generado"] is False
    assert orden["situacion"]["codigo"] == "SIN_TRABAJOS_VIGENTES"
    assert codigos(orden) == []
    assert _cancelar_orden_accion(orden)["bloqueo"] is None
    assert [
        t["acciones"][0]["codigo"] for t in orden["situacion"]["tareas"]
    ] == ["CANCELAR_ORDEN"]
    conflicto(devolver(cliente, orden_id))  # no se devuelve dos veces

    orden = ok(cancelar_orden(cliente, orden_id))

    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["cerrada"] is True
    assert orden["current_process"] == "EVT-REP-999"
    paso = next(
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-308"
    )
    assert paso["usuario_id"] == RECEPCION and MOTIVO in paso["observacion"]
    _sin_acciones(orden)


def test_cancelar_la_orden_cancela_varios_pendientes(cliente):
    """El equipo nunca ingreso: se resuelve la custodia y se cancela todo."""
    orden_id = crear(cliente)
    agregar(cliente, orden_id, BATERIA)
    agregar(cliente, orden_id, PANTALLA)
    assert "custodia" in conflicto(cancelar_orden(cliente, orden_id))

    ok(no_recibido(cliente, orden_id))
    orden = ok(cancelar_orden(cliente, orden_id))

    assert [d["estado"] for d in orden["reparaciones_detail"]] == [
        "CANCELADO",
        "CANCELADO",
    ]
    paso = next(
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-308"
    )
    assert "DET-001, DET-002" in paso["observacion"]
    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["cerrada"] is True
    assert "PROC-REP-211" not in ids(orden)  # no se infiere: es explicita
    _sin_acciones(orden)


def test_sin_detalles_sin_custodia_definida(cliente, tmp_path):
    orden_id = crear(cliente)
    accion = _cancelar_orden_accion(_orden(cliente, orden_id))
    assert accion is not None and "custodia" in accion["bloqueo"]
    antes = archivo(tmp_path, orden_id)
    conflicto(cancelar_orden(cliente, orden_id))
    assert archivo(tmp_path, orden_id) == antes

    ok(no_recibido(cliente, orden_id))
    orden = ok(cancelar_orden(cliente, orden_id))

    assert ids(orden)[-1] == "PROC-REP-306"
    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["cerrada"] is True
    assert orden["custodia"]["estado"] == "NO_RECIBIDO"
    conflicto(cancelar_orden(cliente, orden_id), "ORDEN_CERRADA")


def test_sin_detalles_con_equipo_en_custodia(cliente):
    orden_id = crear(cliente)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/send-to-review",
            json={"usuario_id": RECEPCION},
        )
    )
    confirmar_recepcion(cliente, orden_id)
    assert "devolucion" in conflicto(cancelar_orden(cliente, orden_id))
    assert "REGISTRAR_DEVOLUCION" in codigos(_orden(cliente, orden_id))

    orden = ok(devolver(cliente, orden_id, recibido_por="Cliente"))
    assert orden["situacion"]["codigo"] == "SIN_TRABAJOS_VIGENTES"
    orden = ok(cancelar_orden(cliente, orden_id))

    assert orden["cerrada"] is True
    assert orden["devolucion"]["recibido_por"] == "Cliente"


# --- Precondiciones: si alguna falla no cambia nada -------------------------


def test_con_ejecucion_activa_y_reservas_no_se_cancela_nada(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    tomada(cliente, orden_id)
    iniciar(cliente, orden_id, "DET-001")
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(cancelar_orden(cliente, orden_id))

    assert "Ejecucion activa" in mensaje
    assert "tomada" in mensaje
    assert "reservas" in mensaje
    assert archivo(tmp_path, orden_id) == antes
    orden = repo_ordenes(tmp_path).obtener(orden_id)
    motivos = impedimentos_cancelacion(orden)
    assert any("Ejecucion activa" in m for m in motivos)
    assert any("reservas" in m for m in motivos)


def test_con_toma_abierta_no_se_cancela(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA)
    tomada(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    assert "tomada" in conflicto(cancelar_orden(cliente, orden_id))
    assert archivo(tmp_path, orden_id) == antes


def test_un_trabajo_completo_impide_la_cancelacion_total(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id, "DET-001")
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(cancelar_orden(cliente, orden_id))

    assert "COMPLETOS" in mensaje
    assert archivo(tmp_path, orden_id) == antes
    # No se ofrece: lo realizado sigue el cierre normal.
    assert _cancelar_orden_accion(_orden(cliente, orden_id)) is None
    # Cancelar el pendiente si: la Orden sigue al control, cobro y entrega.
    orden = ok(cancelar_detalle(cliente, orden_id, "DET-002"))
    assert detalle(orden, "DET-001")["estado"] == "COMPLETO"
    assert orden["situacion"]["codigo"] != "SIN_TRABAJOS_VIGENTES"
    ok(aprobar(cliente, orden_id, "DET-001"))
    entregada = notificar_pagar_entregar(cliente, orden_id)
    assert entregada["estado_workflow"] == "ENTREGADA"
    assert Decimal(entregada["resumen"]["total"]) == Decimal("80000")


def test_saldo_a_favor_se_devuelve_antes_de_cancelar(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA)
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": RECEPCION,
                "monto": "10000",
                "metodo": "EFECTIVO",
            },
        )
    )
    pago_id = orden["pagos"][-1]["id"]
    _cancelar_todos_los_trabajos(cliente, orden_id)
    ok(devolver(cliente, orden_id))

    antes = archivo(tmp_path, orden_id)
    assert "a favor del cliente" in conflicto(
        cancelar_orden(cliente, orden_id)
    )
    assert archivo(tmp_path, orden_id) == antes
    orden = _orden(cliente, orden_id)
    assert "REGISTRAR_DEVOLUCION_DINERO" in [
        a["codigo"] for a in orden["acciones_financieras"]
    ]

    ok(
        cliente.post(
            f"/api/orders/{orden_id}/refunds",
            json={
                "usuario_id": RECEPCION,
                "pago_id": pago_id,
                "monto": "10000",
                "medio": "EFECTIVO",
                "motivo": "Cancelacion.",
            },
        )
    )
    orden = ok(cancelar_orden(cliente, orden_id))

    assert orden["cerrada"] is True
    assert Decimal(orden["resumen"]["saldo"]) == Decimal("0")
    assert len(orden["pagos"]) == 1  # el pago original se conserva


def test_roles_y_motivo(cliente, tmp_path):
    orden_id = crear(cliente)
    ok(no_recibido(cliente, orden_id))
    antes = archivo(tmp_path, orden_id)

    conflicto(cancelar_orden(cliente, orden_id, usuario=TECNICO))
    conflicto(cancelar_orden(cliente, orden_id, motivo="  "))
    assert cancelar_orden(cliente, orden_id, motivo="").status_code == 422
    assert archivo(tmp_path, orden_id) == antes

    ok(cancelar_orden(cliente, orden_id, usuario=COORDINADOR))
    conflicto(cancelar_orden(cliente, orden_id), "ORDEN_CERRADA")


# --- Orden cancelada: terminal, sin acciones ---------------------------------


def test_orden_cancelada_cerrada_no_admite_acciones(cliente, tmp_path):
    orden_id = crear(cliente)
    ok(no_recibido(cliente, orden_id))
    orden = ok(cancelar_orden(cliente, orden_id))
    _sin_acciones(orden)

    for respuesta in (
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={"usuario_id": RECEPCION, "monto": "1", "metodo": "EFECTIVO"},
        ),
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": ADMINISTRADOR},
        ),
        cliente.post(
            f"/api/orders/{orden_id}/details",
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": BATERIA},
        ),
        devolver(cliente, orden_id),
    ):
        conflicto(respuesta, "ORDEN_CERRADA")
    # Se puede consultar: informacion, documentos e historial.
    assert cliente.get(f"/api/orders/{orden_id}").status_code == 200
    assert cliente.get(f"/api/orders/{orden_id}/documents").status_code == 200


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
    assert codigos_cancelacion(_orden(cliente, orden_id)) == []


def test_una_orden_rt_se_devuelve_a_gestion_rt_y_despues_se_cancela(cliente):
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
    assert "devolucion" in conflicto(cancelar_orden(cliente, orden_id))

    ok(devolver(cliente, orden_id, recibido_por="Gestion RT"))
    orden = ok(cancelar_orden(cliente, orden_id))

    assert orden["cerrada"] is True
    assert orden["devolucion"]["recibido_por"] == "Gestion RT"


def test_circuito_ingreso_cancelacion_devolucion_cierre(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    ok(encolar(cliente, orden_id, 2))

    _cancelar_todos_los_trabajos(cliente, orden_id)
    ok(devolver(cliente, orden_id, recibido_por="Cliente"))
    cerrada = ok(cancelar_orden(cliente, orden_id, "El cliente desiste."))

    assert cerrada["prioridad"] == 2
    persistida: OrdenReparacion = repo_ordenes(tmp_path).obtener(orden_id)
    assert persistida.current_process == "EVT-REP-999"
    pasos = [p.process_id for p in persistida.historial if p.process_id]
    assert pasos[-4:] == [
        "PROC-REP-307",
        "PROC-REP-270",
        "PROC-REP-308",
        "PROC-REP-268",
    ] or pasos[-3:] == ["PROC-REP-307", "PROC-REP-270", "PROC-REP-308"]
    conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": TECNICO, "estacion_id": "EST-001"},
        ),
        "ORDEN_CERRADA",
    )


# --- Una Orden con resultado devuelve el equipo en su cierre ----------------
#
# La devolucion de DC31 es la previa a cancelar. Una Orden que finalizo SIN
# REPARACION (PROC-REP-069) ya no se cancela: sigue su cierre (notificar y
# entregar, o informar a Gestion RT y devolver) sin saltear pasos.


def _con_continuacion(orden: dict) -> None:
    """Una Orden abierta siempre tiene como seguir."""
    if orden["cerrada"]:
        return
    assert any(
        orden[grupo]
        for grupo in (
            "acciones_disponibles",
            "acciones_cancelacion",
            "acciones_autorizacion",
            "acciones_financieras",
            "acciones_custodia",
            "acciones_complementarias",
        )
    ), orden["situacion"]


def _revisada_sin_reparacion(cliente, orden_id) -> dict:
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/technical-review",
            json={"usuario_id": TECNICO, "resultado": "Sin falla reparable."},
        )
    )
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/review/without-repair",
            json={"usuario_id": RECEPCION, "motivo": MOTIVO},
        )
    )


def _la_devolucion_previa_se_rechaza(cliente, tmp_path, orden_id) -> None:
    antes = archivo(tmp_path, orden_id)
    mensaje = conflicto(devolver(cliente, orden_id, usuario=ADMINISTRADOR))
    assert "resultado" in mensaje
    conflicto(cancelar_orden(cliente, orden_id))
    assert archivo(tmp_path, orden_id) == antes


def test_rt_sin_reparacion_informa_a_gestion_rt_antes_de_devolver(
    cliente, tmp_path
):
    respuesta = cliente.post(
        "/api/orders/rt-interno",
        json={
            "usuario_id": RECEPCION,
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 13",
                "falla_reportada": "No enciende.",
            },
            "referencia_rt": "RT-0002",
        },
    )
    orden_id = ok(respuesta)["id"]
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/send-to-review",
            json={"usuario_id": RECEPCION},
        )
    )
    orden = _revisada_sin_reparacion(cliente, orden_id)

    assert orden["custodia"]["estado"] == "EN_CUSTODIA"
    assert codigos(orden) == ["INFORMAR_RT"]
    assert codigos_cancelacion(orden) == []
    _con_continuacion(orden)
    _la_devolucion_previa_se_rechaza(cliente, tmp_path, orden_id)

    orden = ok(cliente.post(f"/api/orders/{orden_id}/inform-rt"))
    assert codigos(orden) == ["DEVOLVER_RT"]
    _con_continuacion(orden)

    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/return-rt",
            json={"usuario_id": ADMINISTRADOR},
        )
    )
    assert ids(orden)[-3:] == ["PROC-REP-250", "PROC-REP-290", "PROC-REP-270"]
    assert orden["current_process"] == "EVT-REP-999"
    assert orden["cerrada"] is True
    assert orden["devolucion"] is None


def test_cliente_sin_reparacion_con_custodia_notifica_y_entrega(
    cliente, tmp_path
):
    orden_id = crear(cliente)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/send-to-review",
            json={"usuario_id": RECEPCION},
        )
    )
    confirmar_recepcion(cliente, orden_id)
    orden = _revisada_sin_reparacion(cliente, orden_id)

    assert orden["custodia"]["estado"] == "EN_CUSTODIA"
    assert codigos(orden) == ["NOTIFICAR"]
    assert codigos_cancelacion(orden) == []
    _con_continuacion(orden)
    _la_devolucion_previa_se_rechaza(cliente, tmp_path, orden_id)

    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )
    assert codigos(orden) == ["ENTREGAR"]
    _con_continuacion(orden)

    orden = ok(entregar(cliente, orden_id, ADMINISTRADOR))
    assert ids(orden)[-2:] == ["PROC-REP-280", "PROC-REP-270"]
    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["cerrada"] is True
    assert orden["devolucion"] is None
