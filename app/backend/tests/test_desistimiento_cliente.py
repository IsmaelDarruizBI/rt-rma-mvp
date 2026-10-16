"""Rechazo y desistimiento del cliente (BR-REP-028, PROC-REP-046/047).

    POST /api/orders/{id}/authorizations                  rechazo (pendiente)
    POST /api/orders/{id}/details/{detalle_id}/withdrawal desiste de UNO
    POST /api/orders/{id}/withdrawal                      desiste de TODO

Rechazar es responder "no" a una propuesta pendiente. Desistir es dejar sin
efecto un trabajo YA autorizado antes de que se realice: la autorizacion
queda en la historia y el Detalle se cancela con origen
DESISTIMIENTO_CLIENTE. El desistimiento total rechaza ademas lo pendiente,
conserva lo COMPLETO y no se aplica si algo lo impide (Ejecucion activa o
reservas sin conciliar).
"""

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import (
    CanalComunicacion,
    OrdenReparacion,
    OrigenCancelacion,
)
from app.main import create_app
from app.services import (
    PrecondicionInvalidaError,
    analizar_desistimiento,
    registrar_desistimiento_cliente,
)
from app.services.inventario import crear_reserva
from tests.fixtures import flujo_mvp
from tests.fixtures.api_definicion import definir_y_finalizar
from tests.fixtures.api_salidas import (
    BATERIA,
    PANTALLA,
    RECEPCION,
    TECNICO,
    aprobar,
    archivo,
    cliente_http,
    codigos,
    conflicto,
    decidir,
    definida,
    detalle,
    devolver,
    ejecutar,
    ids,
    iniciar,
    notificar_pagar_entregar,
    ok,
    repo_ordenes,
    tomada,
)
from tests.fixtures.catalogos_mvp import RECEPCION as RECEPCION_DEMO
from tests.fixtures.catalogos_mvp import t
from tests.test_api_hp_rep_002 import TIPO, _crear_orden_rt, _sembrar_catalogos

MOTIVO = "Consiguio el repuesto por su cuenta."


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def desistir(
    cliente,
    orden_id,
    detalle_id=None,
    motivo=MOTIVO,
    canal="TELEFONO",
    usuario=RECEPCION,
):
    ruta = (
        f"/api/orders/{orden_id}/withdrawal"
        if detalle_id is None
        else f"/api/orders/{orden_id}/details/{detalle_id}/withdrawal"
    )
    return cliente.post(
        ruta, json={"usuario_id": usuario, "canal": canal, "motivo": motivo}
    )


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _mixta(cliente) -> str:
    """El ejemplo del caso: DET-001 y DET-003 autorizados, DET-002 no."""
    orden_id = definida(cliente, BATERIA, PANTALLA, BATERIA, autorizar=False)
    ok(
        decidir(
            cliente,
            orden_id,
            {"DET-001": "AUTORIZADO", "DET-003": "AUTORIZADO"},
        )
    )
    return orden_id


def _ofrecidas(orden: dict) -> list[tuple[str, str | None]]:
    return [
        (a["codigo"], a["detalle_id"]) for a in orden["acciones_autorizacion"]
    ]


# --- 1. Rechazo de lo pendiente (sin cambios) --------------------------------


def test_1_rechazar_todos_los_pendientes_sigue_siendo_un_rechazo(cliente):
    orden_id = definida(cliente, BATERIA, PANTALLA, autorizar=False)
    # Con solo pendientes no hay de que desistir: se ofrece la decision.
    assert _ofrecidas(_orden(cliente, orden_id)) == [
        ("REGISTRAR_DECISION_CLIENTE", None)
    ]

    orden = ok(
        decidir(
            cliente, orden_id, {"DET-001": "RECHAZADO", "DET-002": "RECHAZADO"}
        )
    )

    assert orden["estado_workflow"] == "CANCELADA"
    assert {
        d["cancelacion"]["origen"] for d in orden["reparaciones_detail"]
    } == {"RECHAZO_CLIENTE"}
    assert "PROC-REP-305" in ids(orden)


# --- 2/4/5. Desistir de UN Detalle autorizado --------------------------------


def test_2_desistir_de_un_detalle_autorizado_sin_ejecucion(cliente):
    orden_id = definida(cliente, BATERIA, PANTALLA)  # ambos autorizados
    assert ("DESISTIR_DETALLE", "DET-002") in _ofrecidas(
        _orden(cliente, orden_id)
    )

    orden = ok(desistir(cliente, orden_id, "DET-002"))

    assert ids(orden)[-4:] == [
        "PROC-REP-046",
        "PROC-REP-047",
        "PROC-REP-300",
        "PROC-REP-211",
    ]
    assert (
        orden["historial"][-4]["accion"] == "REGISTRAR_DESISTIMIENTO_CLIENTE"
    )
    assert orden["historial"][-3]["observacion"] == "RECHAZA_ALGUNOS_DETALLES"
    desistido = detalle(orden, "DET-002")
    assert desistido["estado"] == "CANCELADO"
    assert desistido["cancelacion"]["origen"] == "DESISTIMIENTO_CLIENTE"
    assert desistido["situacion_autorizacion"] == "CANCELADO_POR_DESISTIMIENTO"
    # El otro sigue igual y la Orden sigue habilitada.
    assert detalle(orden, "DET-001")["situacion_autorizacion"] == (
        "AUTORIZADO_FACTIBLE"
    )
    assert orden["estado_workflow"] == "HABILITADA"
    assert Decimal(orden["resumen"]["total"]) == Decimal("80000")


def test_4_la_autorizacion_previa_permanece_en_la_historia(cliente):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    antes = detalle(_orden(cliente, orden_id), "DET-002")["autorizaciones"]

    orden = ok(desistir(cliente, orden_id, "DET-002"))

    desistido = detalle(orden, "DET-002")
    assert desistido["autorizaciones"] == antes
    assert [r["resultado"] for r in desistido["autorizaciones"]] == [
        "AUTORIZADO"
    ]
    # La decision vigente sigue siendo la autorizacion: lo que cambio es que
    # el trabajo se cancelo despues, por desistimiento.
    assert desistido["estado_autorizacion"] == "AUTORIZADO"
    consulta = ok(cliente.get(f"/api/orders/{orden_id}/authorizations"))
    vista = next(
        d for d in consulta["detalles"] if d["detalle_id"] == "DET-002"
    )
    assert vista["situacion"] == "CANCELADO_POR_DESISTIMIENTO"
    assert vista["decision_vigente"]["resultado"] == "AUTORIZADO"


def test_5_motivo_y_usuario_del_desistimiento(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA, PANTALLA)
    antes = archivo(tmp_path, orden_id)
    respuesta = desistir(cliente, orden_id, "DET-002", motivo="")
    assert respuesta.status_code == 422, respuesta.text
    mensaje = conflicto(desistir(cliente, orden_id, "DET-002", motivo="   "))
    assert "motivo" in mensaje
    assert archivo(tmp_path, orden_id) == antes

    orden = ok(desistir(cliente, orden_id, "DET-002", canal="WHATSAPP"))

    cancelacion = detalle(orden, "DET-002")["cancelacion"]
    assert cancelacion["usuario_id"] == RECEPCION
    assert cancelacion["fecha"] is not None
    assert cancelacion["motivo"] == (
        f"El cliente desiste despues de autorizar (WHATSAPP): {MOTIVO}"
    )
    paso_046 = orden["historial"][-4]
    assert paso_046["usuario_id"] == RECEPCION
    assert paso_046["reparacion_detail_id"] == "DET-002"
    assert paso_046["observacion"].startswith("DESISTE (definicion v1, ")
    assert f"autorizado por {RECEPCION}" in paso_046["observacion"]
    assert MOTIVO in paso_046["observacion"]


# --- 3/10/11. Desistir de todo: pendientes + autorizados ---------------------


def test_3_desistir_de_todo_mezcla_autorizados_y_pendientes(cliente):
    orden_id = _mixta(cliente)
    orden = _orden(cliente, orden_id)
    assert ("DESISTIR_TODO", None) in _ofrecidas(orden)
    assert orden["desistimiento"] == {
        "rechazables": ["DET-002"],
        "desistibles": ["DET-001", "DET-003"],
        "conservados": [],
        "bloqueantes": [],
    }

    orden = ok(desistir(cliente, orden_id))

    assert ids(orden)[-6:] == [
        "PROC-REP-046",
        "PROC-REP-046",
        "PROC-REP-046",
        "PROC-REP-047",
        "PROC-REP-305",
        "PROC-REP-211",
    ]
    acciones_046 = [
        (p["reparacion_detail_id"], p["accion"])
        for p in orden["historial"][-6:-3]
    ]
    assert acciones_046 == [
        ("DET-002", "REGISTRAR_DECISION_CLIENTE"),
        ("DET-001", "REGISTRAR_DESISTIMIENTO_CLIENTE"),
        ("DET-003", "REGISTRAR_DESISTIMIENTO_CLIENTE"),
    ]
    assert orden["historial"][-3]["observacion"] == (
        "RECHAZA_TODOS_LOS_TRABAJOS"
    )
    assert {
        d["id"]: d["cancelacion"]["origen"]
        for d in orden["reparaciones_detail"]
    } == {
        "DET-001": "DESISTIMIENTO_CLIENTE",
        "DET-002": "RECHAZO_CLIENTE",
        "DET-003": "DESISTIMIENTO_CLIENTE",
    }
    # El pendiente queda rechazado (decision nueva); los autorizados
    # conservan su autorizacion.
    assert [
        r["resultado"] for r in detalle(orden, "DET-002")["autorizaciones"]
    ] == ["RECHAZADO"]
    for desistido in ("DET-001", "DET-003"):
        assert [
            r["resultado"] for r in detalle(orden, desistido)["autorizaciones"]
        ] == ["AUTORIZADO"]


def test_10_11_todo_cancelado_queda_cancelada_y_exige_la_devolucion(cliente):
    orden_id = _mixta(cliente)

    orden = ok(desistir(cliente, orden_id))

    assert orden["historial"][-1]["observacion"] == "TODO_CANCELADO"
    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["devolucion_pendiente"] is True
    assert orden["cerrada"] is False
    assert Decimal(orden["resumen"]["total"]) == Decimal("0")
    assert codigos(orden) == ["REGISTRAR_DEVOLUCION"]
    assert orden["acciones_autorizacion"] == []

    cerrada = ok(devolver(cliente, orden_id, recibido_por="Cliente"))
    assert cerrada["cerrada"] is True
    assert cerrada["estado_workflow"] == "CANCELADA"


# --- 6/13. Ejecucion activa: no se aplica nada -------------------------------


def test_6_13_con_una_ejecucion_activa_no_se_desiste_de_todo(
    cliente, tmp_path
):
    orden_id = _mixta(cliente)
    tomada(cliente, orden_id)
    ejecucion_id = iniciar(cliente, orden_id, "DET-001")
    orden = _orden(cliente, orden_id)
    assert ("DESISTIR_TODO", None) in _ofrecidas(orden)
    assert orden["desistimiento"]["bloqueantes"] == [
        {
            "detalle_id": "DET-001",
            "motivo": "tiene una Ejecucion activa: hay que completarla o "
            "interrumpirla (PROC-REP-200)",
        }
    ]
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(desistir(cliente, orden_id))

    assert "DET-001" in mensaje and "Ejecucion activa" in mensaje
    assert "no se cancelo nada" in mensaje
    assert archivo(tmp_path, orden_id) == antes
    conflicto(desistir(cliente, orden_id, "DET-001"))
    assert archivo(tmp_path, orden_id) == antes
    orden = _orden(cliente, orden_id)
    assert detalle(orden, "DET-001")["estado"] == "EN_PROGRESO"
    assert [e["id"] for e in orden["ejecuciones"]] == [ejecucion_id]
    # El desistimiento de OTRO Detalle no toca la Ejecucion en curso.
    orden = ok(desistir(cliente, orden_id, "DET-003"))
    assert orden["historial"][-1]["observacion"] == "EN_EJECUCION"
    assert detalle(orden, "DET-001")["estado"] == "EN_PROGRESO"


def test_13_no_se_desiste_de_un_detalle_pendiente(cliente, tmp_path):
    orden_id = _mixta(cliente)
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(desistir(cliente, orden_id, "DET-002"))

    assert "rechazo" in mensaje
    assert archivo(tmp_path, orden_id) == antes


# --- 8/9. Lo COMPLETO se conserva y sigue al cierre --------------------------


def test_8_9_lo_completo_se_conserva_y_sigue_al_control_y_cierre(cliente):
    orden_id = _mixta(cliente)
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id, "DET-001")  # sigue trabajable DET-003
    orden = _orden(cliente, orden_id)
    assert orden["desistimiento"]["conservados"] == ["DET-001"]

    mensaje = conflicto(desistir(cliente, orden_id, "DET-001"))
    assert "COMPLETO" in mensaje

    orden = ok(desistir(cliente, orden_id))

    assert detalle(orden, "DET-001")["estado"] == "COMPLETO"
    assert detalle(orden, "DET-001")["cancelacion"] is None
    assert orden["historial"][-1]["observacion"] == "COMPLETA"
    assert orden["estado_workflow"] != "CANCELADA"
    assert [t_["estado"] for t_ in orden["tomas"]] == ["CERRADA"]
    assert "APROBAR_CONTROL" in codigos(orden)
    assert Decimal(orden["resumen"]["total"]) == Decimal("80000")
    ok(aprobar(cliente, orden_id, "DET-001"))
    entregada = notificar_pagar_entregar(cliente, orden_id)
    assert entregada["estado_workflow"] == "ENTREGADA"


# --- 12. Orden cerrada -------------------------------------------------------


def test_12_no_se_desiste_en_una_orden_entregada(cliente, tmp_path):
    orden_id = definida(cliente, BATERIA)
    tomada(cliente, orden_id)
    ejecutar(cliente, orden_id)
    ok(aprobar(cliente, orden_id, "DET-001"))
    notificar_pagar_entregar(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    conflicto(desistir(cliente, orden_id), codigo="ORDEN_CERRADA")
    conflicto(desistir(cliente, orden_id, "DET-001"), codigo="ORDEN_CERRADA")

    assert archivo(tmp_path, orden_id) == antes


# --- 14. Reintentos ----------------------------------------------------------


def test_14_reintentar_no_duplica_eventos(cliente):
    orden_id = _mixta(cliente)
    ok(desistir(cliente, orden_id, "DET-003"))
    despues_uno = _orden(cliente, orden_id)

    mensaje = conflicto(desistir(cliente, orden_id, "DET-003"))
    assert "ya esta CANCELADO" in mensaje
    assert _orden(cliente, orden_id) == despues_uno

    ok(desistir(cliente, orden_id))
    despues_todo = _orden(cliente, orden_id)
    conflicto(desistir(cliente, orden_id))
    assert _orden(cliente, orden_id) == despues_todo
    assert ids(despues_todo).count("PROC-REP-300") == 1
    assert ids(despues_todo).count("PROC-REP-305") == 1
    assert ids(despues_todo).count("PROC-REP-047") == 3  # 1 + 2 desistires


# --- 15. Las autorizaciones parciales siguen igual ---------------------------


def test_15_tras_desistir_de_uno_se_autoriza_el_pendiente(cliente):
    orden_id = _mixta(cliente)
    ok(desistir(cliente, orden_id, "DET-003"))

    orden = ok(decidir(cliente, orden_id, {"DET-002": "AUTORIZADO"}))

    # Ya habilitada: 046 -> 047 -> 080 -> 090 -> 211, sin repetir 140.
    assert ids(orden)[-5:] == [
        "PROC-REP-046",
        "PROC-REP-047",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-211",
    ]
    assert orden["historial"][-4]["observacion"] == "ACEPTA_TRABAJOS"
    assert ids(orden).count("PROC-REP-140") == 1
    assert {
        d["id"]: d["situacion_autorizacion"]
        for d in orden["reparaciones_detail"]
    } == {
        "DET-001": "AUTORIZADO_FACTIBLE",
        "DET-002": "AUTORIZADO_FACTIBLE",
        "DET-003": "CANCELADO_POR_DESISTIMIENTO",
    }
    tomada(cliente, orden_id)
    orden = ejecutar(cliente, orden_id, "DET-002", tipo=PANTALLA)
    # Queda DET-001 trabajable: la toma sigue con el mismo tecnico.
    assert orden["historial"][-1]["observacion"] == "ABIERTA_TRABAJABLE"
    assert orden["toma_activa"]["usuario_id"] == TECNICO


# --- Permisos y Origenes -----------------------------------------------------


@pytest.mark.parametrize("usuario", ["TECH-001", "COORD-001", "ADMIN-001"])
def test_solo_recepcion_registra_el_desistimiento(cliente, tmp_path, usuario):
    orden_id = _mixta(cliente)
    antes = archivo(tmp_path, orden_id)

    conflicto(desistir(cliente, orden_id, usuario=usuario))
    conflicto(desistir(cliente, orden_id, "DET-001", usuario=usuario))

    assert archivo(tmp_path, orden_id) == antes


def test_rt_interno_no_tiene_desistimiento_comercial(tmp_path):
    _sembrar_catalogos(tmp_path, stock="5")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as http:
        orden_id = _crear_orden_rt(http)
        orden = ok(
            definir_y_finalizar(
                http,
                orden_id,
                json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
            )
        )
        assert orden["desistimiento"] is None
        assert orden["acciones_autorizacion"] == []
        mensaje = conflicto(desistir(http, orden_id))
        assert "cancelacion interna" in mensaje


# --- 7. Reservas sin conciliar (services) ------------------------------------


def _con_reserva_sin_conciliar() -> OrdenReparacion:
    """DET-001 autorizado y habilitado, con una reserva que nadie concilio."""
    orden = flujo_mvp.orden_habilitada().model_copy(deep=True)
    orden.movimientos_insumo.append(
        crear_reserva(
            insumo_id="INS-001",
            reparacion_detail_id=flujo_mvp.DETALLE_ID,
            cantidad=Decimal("1"),
            fecha=t(21),
        )
    )
    return orden


@pytest.mark.parametrize("detalle_id", [None, flujo_mvp.DETALLE_ID])
def test_7_con_reservas_sin_conciliar_no_se_desiste(detalle_id):
    orden = _con_reserva_sin_conciliar()
    analisis = analizar_desistimiento(orden)
    assert analisis.bloqueantes == (
        (flujo_mvp.DETALLE_ID, "tiene reservas de insumos sin conciliar"),
    )
    copia = orden.model_copy(deep=True)

    with pytest.raises(PrecondicionInvalidaError, match="reservas"):
        registrar_desistimiento_cliente(
            orden,
            usuario=RECEPCION_DEMO,
            canal=CanalComunicacion.PRESENCIAL,
            motivo=MOTIVO,
            fecha=t(30),
            detalle_id=detalle_id,
        )
    assert orden == copia


def test_el_desistimiento_no_modifica_la_orden_recibida():
    orden = flujo_mvp.orden_habilitada()
    copia = orden.model_copy(deep=True)

    nueva = registrar_desistimiento_cliente(
        orden,
        usuario=RECEPCION_DEMO,
        canal=CanalComunicacion.EMAIL,
        motivo=MOTIVO,
        fecha=t(30),
    )

    assert orden == copia
    (desistido,) = nueva.reparaciones_detail
    assert desistido.cancelacion.origen is (
        OrigenCancelacion.DESISTIMIENTO_CLIENTE
    )


# --- 17. Compatibilidad JSON -------------------------------------------------


def test_17_json_anterior_y_round_trip_del_desistimiento(cliente, tmp_path):
    orden_id = _mixta(cliente)
    ok(desistir(cliente, orden_id, "DET-003"))
    recargada = repo_ordenes(tmp_path).obtener(orden_id)
    assert (
        next(
            d for d in recargada.reparaciones_detail if d.id == "DET-003"
        ).cancelacion.origen
        is OrigenCancelacion.DESISTIMIENTO_CLIENTE
    )

    # Un JSON anterior (sin autorizaciones ni cancelacion.origen): sus
    # Detalles DEFINIDO quedan pendientes, asi que el desistimiento total
    # los RECHAZA (no presume autorizaciones que nadie registro).
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    crudo = json.loads(ruta.read_text(encoding="utf-8"))
    for d in crudo["reparaciones_detail"]:
        d.pop("autorizaciones")
        if d["cancelacion"]:
            d["cancelacion"].pop("origen")
    ruta.write_text(json.dumps(crudo), encoding="utf-8")
    legado = _orden(cliente, orden_id)
    assert detalle(legado, "DET-003")["cancelacion"]["origen"] == "INTERNA"
    assert legado["desistimiento"]["rechazables"] == ["DET-001", "DET-002"]

    orden = ok(desistir(cliente, orden_id))

    assert {
        d["id"]: d["cancelacion"]["origen"]
        for d in orden["reparaciones_detail"]
        if d["id"] != "DET-003"
    } == {"DET-001": "RECHAZO_CLIENTE", "DET-002": "RECHAZO_CLIENTE"}
    assert orden["estado_workflow"] == "CANCELADA"


# --- Circuito por HTTP -------------------------------------------------------


def test_circuito_desistimiento_posterior_a_la_autorizacion(cliente, tmp_path):
    """Autoriza, se trabaja e interrumpe, y despues el cliente desiste.

    La Ejecucion interrumpida y sus movimientos se conservan; el
    desistimiento total no se aplica mientras haya una Ejecucion activa y
    si despues de interrumpirla.
    """
    orden_id = _mixta(cliente)
    tomada(cliente, orden_id)
    ejecucion_id = iniciar(cliente, orden_id, "DET-001")
    conflicto(desistir(cliente, orden_id))
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion_id}/interrupt",
            json={
                "usuario_id": TECNICO,
                "insumos_utilizados": [],
                "motivo": "El cliente desiste.",
            },
        )
    )
    movimientos = len(
        repo_ordenes(tmp_path).obtener(orden_id).movimientos_insumo
    )

    orden = ok(desistir(cliente, orden_id, motivo="Se lleva el equipo."))

    assert orden["estado_workflow"] == "CANCELADA"
    assert [e["estado"] for e in orden["ejecuciones"]] == ["INTERRUMPIDO"]
    assert (
        len(repo_ordenes(tmp_path).obtener(orden_id).movimientos_insumo)
        == movimientos
    )
    assert orden["toma_activa"] is None
    cerrada = ok(devolver(cliente, orden_id))
    assert cerrada["cerrada"] is True
    # Nada se puede tomar ni iniciar despues.
    conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": TECNICO},
        ),
        codigo="ORDEN_CERRADA",
    )
