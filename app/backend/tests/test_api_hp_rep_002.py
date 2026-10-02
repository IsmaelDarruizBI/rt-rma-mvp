"""HP-REP-002 recorrido de punta a punta por HTTP.

Origen RT_INTERNO: cada paso entra por la API real

    HTTP -> router -> application -> services -> repositories -> JSON

igual que ``test_api_hp_rep_001.py``, pero sin Cliente y con el cierre
propio de Gestion RT (informar resultado + devolucion del equipo).
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import (
    EstacionTrabajo,
    Insumo,
    RolUsuario,
    TipoReparacion,
    TipoReparacionEstacion,
    TipoReparacionInsumos,
    Usuario,
)
from app.main import create_app
from app.storage.json.base import escribir_json_atomico
from tests.fixtures.api_definicion import definir_y_finalizar

RECEPCION = "RECEP-001"
COORDINADOR = "COORD-001"
TECNICO = "TECH-001"
ADMINISTRADOR = "ADMIN-001"
ESTACION = "EST-001"
TIPO = "TR-001"
INSUMO = "INS-001"


def _sembrar_catalogos(directorio, stock: str = "2") -> None:
    """Catalogos DEMO en el directorio temporal del test."""
    catalogos = {
        "tipos_reparacion.json": [
            TipoReparacion(
                id=TIPO,
                nombre="Cambio bateria iPhone 14",
                precio=Decimal("80000"),
                puntaje=10,
                garantia_dias=90,
            )
        ],
        "insumos.json": [
            Insumo(
                id=INSUMO,
                codigo="BAT-IP14",
                nombre="Bateria iPhone 14",
                stock_fisico=Decimal(stock),
            )
        ],
        "tipo_reparacion_insumos.json": [
            TipoReparacionInsumos(
                tipo_reparacion_id=TIPO,
                insumo_id=INSUMO,
                cantidad=Decimal("1"),
            )
        ],
        "estaciones.json": [
            EstacionTrabajo(id=ESTACION, nombre="Mesa tecnica 1")
        ],
        "tipo_reparacion_estaciones.json": [
            TipoReparacionEstacion(
                tipo_reparacion_id=TIPO, estacion_id=ESTACION
            )
        ],
        "usuarios.json": [
            Usuario(
                id=RECEPCION, nombre="Recepcion", rol=RolUsuario.RECEPCION
            ),
            Usuario(
                id=COORDINADOR,
                nombre="Coordinacion",
                rol=RolUsuario.COORDINADOR_RMA,
            ),
            Usuario(id=TECNICO, nombre="Tecnico", rol=RolUsuario.TECNICO),
            Usuario(
                id=ADMINISTRADOR,
                nombre="Administracion",
                rol=RolUsuario.ADMINISTRADOR,
            ),
        ],
    }
    for archivo, entidades in catalogos.items():
        escribir_json_atomico(
            directorio / "catalogs" / archivo,
            [entidad.model_dump(mode="json") for entidad in entidades],
        )


@pytest.fixture
def cliente(tmp_path):
    _sembrar_catalogos(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def _crear_orden_rt(cliente: TestClient) -> str:
    respuesta = cliente.post(
        "/api/orders/rt-interno",
        json={
            "usuario_id": RECEPCION,
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 13",
                "falla_reportada": "No enciende.",
            },
            "referencia_rt": "RT-INGRESO-0001",
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def test_crear_orden_rt_no_pide_ni_devuelve_cliente(cliente):
    orden_id = _crear_orden_rt(cliente)
    orden = cliente.get(f"/api/orders/{orden_id}").json()

    assert orden["origen"] == "RT_INTERNO"
    assert orden["cliente"] is None
    assert orden["referencia_rt"] == "RT-INGRESO-0001"
    assert orden["estado_workflow"] == "REQUERIMIENTO"


def test_hp_rep_002_end_to_end_por_http(cliente):
    """Recorre HP-REP-002 entero usando solo la API."""

    # PROC-REP-010 -> 020 -> 040
    orden_id = _crear_orden_rt(cliente)

    # PROC-REP-045 -> 070 -> 050 (No) -> 080 -> 090 -> 140
    respuesta = definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    detalle_id = orden["reparaciones_detail"][0]["id"]

    assert orden["estado_workflow"] == "HABILITADA"
    assert orden["resumen"]["condicion_comercial"] == (
        "NO_COBRABLE_AL_CLIENTE"
    )
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is False

    # PROC-REP-150 -> 170
    orden = cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    ).json()
    assert orden["estado_workflow"] == "EN_COLA"

    # PROC-REP-172 -> 180
    orden = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    ).json()
    assert orden["tomas"][0]["estado"] == "ACTIVA"

    # PROC-REP-181 -> 174 -> 185
    orden = cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": TECNICO},
    ).json()
    ejecucion_id = orden["ejecuciones"][0]["id"]
    assert orden["estado_workflow"] == "EN_REPARACION"

    # PROC-REP-190 -> 200 -> 210 -> 211
    orden = cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={
            "usuario_id": TECNICO,
            "insumos_utilizados": [{"insumo_id": INSUMO, "cantidad": "1"}],
            "observaciones": "Diagnostico y reparacion sin novedades.",
        },
    ).json()

    assert orden["reparaciones_detail"][0]["estado"] == "COMPLETO"
    # La misma toma sigue: BR-REP-018 solo la cierra si ya no queda nada
    # trabajable ni en ejecucion, y aca la Orden ya quedo COMPLETA.
    assert orden["tomas"][0]["estado"] == "CERRADA"

    # PROC-REP-220 -> 230 -> 245 -> 240
    orden = cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={
            "usuario_id": RECEPCION,
            "observaciones": "Diagnostico confirmado, reparacion validada.",
        },
    ).json()
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    assert orden["resumen"]["puntaje_total"] == 10

    # No debe ofrecerse Pago, Notificar ni Entregar (cliente).
    codigos = {a["codigo"] for a in orden["acciones_disponibles"]}
    assert "REGISTRAR_PAGO" not in codigos
    assert "NOTIFICAR" not in codigos
    assert "ENTREGAR" not in codigos
    assert "INFORMAR_RT" in codigos

    # PROC-REP-290 es ACT-SYSTEM: se publica sin actor requerido.
    accion_informar = next(
        a
        for a in orden["acciones_disponibles"]
        if a["codigo"] == "INFORMAR_RT"
    )
    assert accion_informar["requiere_actor"] is False
    assert accion_informar["roles"] == []

    # DEVOLVER_RT no puede ejecutarse antes de informar a Gestion RT.
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/return-rt",
        json={"usuario_id": ADMINISTRADOR},
    )
    assert respuesta.status_code == 409, respuesta.text

    # Registrar Pago tampoco, aunque se lo invoque directo por HTTP.
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={"usuario_id": ADMINISTRADOR, "monto": "1", "metodo": "EFECTIVO"},
    )
    assert respuesta.status_code == 409, respuesta.text

    # PROC-REP-250 (No) -> 290. ACT-SYSTEM: sin usuario_id en el body.
    orden = cliente.post(f"/api/orders/{orden_id}/inform-rt", json={}).json()
    assert orden["current_process"] == "PROC-REP-290"
    referencias = [p["referencia_id"] for p in orden["historial"]]
    assert "PROC-REP-260" not in referencias
    assert "PROC-REP-265" not in referencias
    assert "PROC-REP-266" not in referencias
    assert "PROC-REP-280" not in referencias

    paso_290 = next(
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-290"
    )
    assert paso_290["usuario_id"] is None

    # PROC-REP-270 (reutilizado) -> EVT-REP-999. No exige saldo 0.
    assert Decimal(orden["resumen"]["saldo"]) > 0
    orden = cliente.post(
        f"/api/orders/{orden_id}/return-rt",
        json={"usuario_id": ADMINISTRADOR},
    ).json()

    # --- expected de HP-REP-002 ---
    assert orden["current_process"] == "EVT-REP-999"
    # El estado terminal sigue pendiente de definicion (V1.3): no se
    # asume ENTREGADA para RT_INTERNO.
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    assert orden["acciones_disponibles"] == []
    assert all(e["estado"] == "COMPLETADO" for e in orden["ejecuciones"])
    assert all(t["estado"] == "CERRADA" for t in orden["tomas"])
    assert orden["documentos"]["comprobante_final"]["generado"] is False
    assert orden["documentos"]["garantia_reparacion"]["generado"] is False

    # Un unico comprobante de recepcion: ninguno, en este origen.
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is False

    # Persistido y releible.
    recargada = cliente.get(f"/api/orders/{orden_id}").json()
    assert recargada["current_process"] == "EVT-REP-999"
    assert len(cliente.get("/api/orders").json()) == 1


def test_cliente_externo_sigue_funcionando_igual_junto_a_rt_interno(cliente):
    """HP1 no se degrada por la presencia de RT_INTERNO en el mismo backend."""
    respuesta = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {
                "nombre": "Cliente de Prueba",
                "telefono": "341-0000000",
            },
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "La bateria dura poco.",
            },
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    orden = respuesta.json()

    assert orden["origen"] == "CLIENTE_EXTERNO"
    assert orden["cliente"]["nombre"] == "Cliente de Prueba"
    assert orden["resumen"]["condicion_comercial"] == "COBRABLE"

    orden = definir_y_finalizar(
        cliente,
        orden["id"],
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    ).json()
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is True


def test_listado_muestra_referencia_rt_cuando_no_hay_cliente(cliente):
    _crear_orden_rt(cliente)

    listado = cliente.get("/api/orders").json()
    assert len(listado) == 1
    assert "RT-INGRESO-0001" in listado[0]["cliente_nombre"]


def _hasta_reparacion_lista_rt(cliente: TestClient) -> str:
    orden_id = _crear_orden_rt(cliente)
    definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    )
    detalle_id = cliente.get(f"/api/orders/{orden_id}").json()[
        "reparaciones_detail"
    ][0]["id"]
    ejecucion_id = cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": TECNICO},
    ).json()["ejecuciones"][0]["id"]
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


def test_registrar_pago_rechaza_rt_interno_con_admin_activo_por_http(cliente):
    """BR-REP-016/017: NO_COBRABLE_AL_CLIENTE rechaza el pago (no solo UI)."""
    orden_id = _hasta_reparacion_lista_rt(cliente)

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": ADMINISTRADOR,
            "monto": "80000",
            "metodo": "EFECTIVO",
        },
    )

    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["error"]["codigo"] == "PRECONDICION_INVALIDA"


def test_registrar_pago_cliente_externo_no_se_ve_afectado(cliente):
    """CLIENTE_EXTERNO (COBRABLE) sigue aceptando Pago de todos sus roles."""
    respuesta = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "Cliente de Prueba", "telefono": "341-0"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "La bateria dura poco.",
            },
        },
    ).json()
    orden_id = respuesta["id"]
    definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )

    for usuario_id in (ADMINISTRADOR, RECEPCION, COORDINADOR):
        respuesta = cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": usuario_id,
                "monto": "1",
                "metodo": "EFECTIVO",
            },
        )
        assert respuesta.status_code == 200, respuesta.text


def test_representacion_comercial_rt_no_es_deuda_pendiente_por_http(cliente):
    """El snapshot ($80000) no se presenta como deuda del cliente."""
    orden_id = _hasta_reparacion_lista_rt(cliente)
    orden = cliente.get(f"/api/orders/{orden_id}").json()

    assert orden["resumen"]["condicion_comercial"] == (
        "NO_COBRABLE_AL_CLIENTE"
    )
    assert orden["resumen"]["total"] == "80000"
    assert orden["resumen"]["saldo"] == "80000"
    codigos = {a["codigo"] for a in orden["acciones_disponibles"]}
    assert "REGISTRAR_PAGO" not in codigos


def test_devolver_rt_rechaza_tecnico_por_http(cliente):
    """PROC-REP-270 NO es ACT-SYSTEM: exige ADMINISTRADOR o RECEPCION."""
    orden_id = _hasta_reparacion_lista_rt(cliente)
    cliente.post(f"/api/orders/{orden_id}/inform-rt", json={})

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/return-rt",
        json={"usuario_id": TECNICO},
    )

    assert respuesta.status_code == 409, respuesta.text


def test_devolver_rt_con_recepcion_registra_su_usuario_por_http(cliente):
    orden_id = _hasta_reparacion_lista_rt(cliente)
    cliente.post(f"/api/orders/{orden_id}/inform-rt", json={})

    orden = cliente.post(
        f"/api/orders/{orden_id}/return-rt",
        json={"usuario_id": RECEPCION},
    ).json()

    paso_270 = next(
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-270"
    )
    assert paso_270["usuario_id"] == RECEPCION
    assert orden["current_process"] == "EVT-REP-999"
    assert orden["estado_workflow"] != "ENTREGADA"
    codigos = {a["codigo"] for a in orden["acciones_disponibles"]}
    assert "REGISTRAR_PAGO" not in codigos
