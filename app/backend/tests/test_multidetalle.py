"""Multi-Detalle (Slice 1): una Orden con 2 Detalles operativos.

Complementa ``test_api_hp_rep_001.py`` (HP-REP-001 con un unico
Detalle, que sigue verde sin cambios). Este archivo recorre el mismo
Happy Path pero con dos Detalles, por HTTP de punta a punta:

    crear Orden
    -> definir DET-001 (finalizar_definicion=False)
    -> definir DET-002 (finaliza: comprobante + factibilidad + habilita)
    -> priorizar -> cola -> tecnico toma
    -> selecciona DET-001 -> inicia -> completa
    -> resolver = ABIERTA_TRABAJABLE (misma toma continua, BR-REP-018)
    -> selecciona DET-002 -> inicia -> completa
    -> resolver = COMPLETA (recien ahora se cierra la toma)
    -> control DET-001 -> control DET-002 -> REPARACION_LISTA

No es un Scenario nuevo (docs/discovery/README.md - "MVP v2 - Scope
funcional cerrado"): Multi-Detalle es mecanica normal del proceso
(BR-REP-018), ya cubierta por HP-REP-001 con N Detalles.

Cada Detalle usa su propio Tipo de Reparacion e Insumo -sin contencion
de stock entre ambos- para poder verificar snapshots y movimientos de
inventario independientes sin acoplar el test a la concurrencia de
``PROC-REP-185``.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.application import construir_contexto, obtener_orden
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

RECEPCION = "RECEP-001"
COORDINADOR = "COORD-001"
TECNICO = "TECH-001"
ADMINISTRADOR = "ADMIN-001"
ESTACION = "EST-001"

TIPO_BATERIA = "TR-001"
TIPO_PANTALLA = "TR-002"
INSUMO_BATERIA = "INS-001"
INSUMO_PANTALLA = "INS-002"


def _sembrar_catalogos(directorio) -> None:
    """Dos Tipos de Reparacion, cada uno con su propio Insumo."""
    catalogos = {
        "tipos_reparacion.json": [
            TipoReparacion(
                id=TIPO_BATERIA,
                nombre="Cambio de bateria iPhone 14",
                precio=Decimal("80000"),
                puntaje=10,
                garantia_dias=90,
            ),
            TipoReparacion(
                id=TIPO_PANTALLA,
                nombre="Cambio de pantalla iPhone 14",
                precio=Decimal("50000"),
                puntaje=5,
                garantia_dias=60,
            ),
        ],
        "insumos.json": [
            Insumo(
                id=INSUMO_BATERIA,
                codigo="BAT-IP14",
                nombre="Bateria iPhone 14",
                stock_fisico=Decimal("1"),
            ),
            Insumo(
                id=INSUMO_PANTALLA,
                codigo="PANT-IP14",
                nombre="Pantalla iPhone 14",
                stock_fisico=Decimal("1"),
            ),
        ],
        "tipo_reparacion_insumos.json": [
            TipoReparacionInsumos(
                tipo_reparacion_id=TIPO_BATERIA,
                insumo_id=INSUMO_BATERIA,
                cantidad=Decimal("1"),
            ),
            TipoReparacionInsumos(
                tipo_reparacion_id=TIPO_PANTALLA,
                insumo_id=INSUMO_PANTALLA,
                cantidad=Decimal("1"),
            ),
        ],
        "estaciones.json": [
            EstacionTrabajo(id=ESTACION, nombre="Mesa tecnica 1")
        ],
        "tipo_reparacion_estaciones.json": [
            TipoReparacionEstacion(
                tipo_reparacion_id=TIPO_BATERIA, estacion_id=ESTACION
            ),
            TipoReparacionEstacion(
                tipo_reparacion_id=TIPO_PANTALLA, estacion_id=ESTACION
            ),
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


def _crear_orden(cliente: TestClient) -> str:
    respuesta = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {
                "nombre": "Cliente Multi-Detalle",
                "telefono": "341-1111111",
            },
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "Bateria y pantalla danadas.",
            },
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def test_multidetalle_dos_detalles_end_to_end_por_http(cliente, tmp_path):
    """Recorre HP-REP-001 con 2 Detalles, entero por HTTP."""
    orden_id = _crear_orden(cliente)

    # --- Definicion de N Detalles, antes de habilitar -------------------

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={
            "usuario_id": RECEPCION,
            "tipo_reparacion_id": TIPO_BATERIA,
            "finalizar_definicion": False,
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    assert orden["estado_workflow"] == "REQUERIMIENTO"
    assert len(orden["reparaciones_detail"]) == 1
    det1 = orden["reparaciones_detail"][0]["id"]
    # Recepcion todavia puede seguir definiendo Detalles.
    codigos = [a["codigo"] for a in orden["acciones_disponibles"]]
    assert "DEFINIR_REPARACION" in codigos
    # Sin finalizar, el comprobante y la habilitacion todavia no corren.
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is False

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO_PANTALLA},
    )
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    assert orden["estado_workflow"] == "HABILITADA"
    assert len(orden["reparaciones_detail"]) == 2
    det2 = next(
        d["id"] for d in orden["reparaciones_detail"] if d["id"] != det1
    )
    assert det1 != det2

    # Snapshots independientes por Detalle (BR-REP-015).
    d1 = next(d for d in orden["reparaciones_detail"] if d["id"] == det1)
    d2 = next(d for d in orden["reparaciones_detail"] if d["id"] == det2)
    assert d1["precio"] == "80000"
    assert d1["puntaje"] == 10
    assert d1["garantia_dias"] == 90
    assert d2["precio"] == "50000"
    assert d2["puntaje"] == 5
    assert d2["garantia_dias"] == 60
    assert orden["resumen"]["total"] == "130000"

    # Un unico comprobante de recepcion, aunque hubo 2 llamadas a /details.
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is True
    comprobantes = [
        p for p in orden["historial"] if p["process_id"] == "PROC-REP-060"
    ]
    assert len(comprobantes) == 1

    # --- Cola y toma ------------------------------------------------------

    orden = cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    ).json()
    assert orden["estado_workflow"] == "EN_COLA"

    orden = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    ).json()
    assert len(orden["tomas"]) == 1
    toma_id = orden["tomas"][0]["id"]

    # Ambos Detalles trabajables ofrecen INICIAR_DETALLE: el tecnico
    # elige cual, no se le impone uno solo (PROC-REP-181).
    inicios = {
        a["detalle_id"]
        for a in orden["acciones_disponibles"]
        if a["codigo"] == "INICIAR_DETALLE"
    }
    assert inicios == {det1, det2}
    assert "LIBERAR_ORDEN" in [
        a["codigo"] for a in orden["acciones_disponibles"]
    ]

    # --- Selecciona DET-001, inicia, completa ------------------------------

    orden = cliente.post(
        f"/api/orders/{orden_id}/details/{det1}/start",
        json={"usuario_id": TECNICO},
    ).json()
    assert orden["estado_workflow"] == "EN_REPARACION"
    ejecucion_1 = next(
        e["id"]
        for e in orden["ejecuciones"]
        if e["reparacion_detail_id"] == det1
    )

    orden = cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_1}/complete",
        json={
            "usuario_id": TECNICO,
            "insumos_utilizados": [
                {"insumo_id": INSUMO_BATERIA, "cantidad": "1"}
            ],
        },
    ).json()
    d1 = next(d for d in orden["reparaciones_detail"] if d["id"] == det1)
    d2 = next(d for d in orden["reparaciones_detail"] if d["id"] == det2)
    assert d1["estado"] == "COMPLETO"
    assert d2["estado"] == "DEFINIDO"

    # resolver = ABIERTA_TRABAJABLE: la misma toma sigue activa
    # (BR-REP-018), no se cierra automaticamente ni se crea una nueva.
    assert orden["tomas"][0]["estado"] == "ACTIVA"
    assert orden["tomas"][0]["id"] == toma_id
    assert len(orden["tomas"]) == 1

    # Ahora solo DET-002 ofrece INICIAR_DETALLE.
    inicios = [
        a["detalle_id"]
        for a in orden["acciones_disponibles"]
        if a["codigo"] == "INICIAR_DETALLE"
    ]
    assert inicios == [det2]

    # LIBERAR_ORDEN sigue disponible: toma activa y sin Ejecucion en
    # curso, tambien despues de completar un Detalle con otro pendiente.
    assert "LIBERAR_ORDEN" in [
        a["codigo"] for a in orden["acciones_disponibles"]
    ]

    # Con DET-002 todavia no terminal, el control tecnico no puede
    # iniciarse ni para DET-001, que ya esta COMPLETO (PROC-REP-220
    # solo se alcanza cuando TODA la Orden es terminal).
    assert "APROBAR_CONTROL" not in [
        a["codigo"] for a in orden["acciones_disponibles"]
    ]
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={"usuario_id": RECEPCION, "detalle_id": det1},
    )
    assert respuesta.status_code == 409, respuesta.text
    d1 = next(d for d in orden["reparaciones_detail"] if d["id"] == det1)
    assert d1["control_estado"] == "PENDIENTE"

    # --- Continua con DET-002, sin volver a tomar la Orden -----------------

    orden = cliente.post(
        f"/api/orders/{orden_id}/details/{det2}/start",
        json={"usuario_id": TECNICO},
    ).json()
    assert len(orden["tomas"]) == 1
    ejecucion_2 = next(
        e["id"]
        for e in orden["ejecuciones"]
        if e["reparacion_detail_id"] == det2
    )

    orden = cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_2}/complete",
        json={
            "usuario_id": TECNICO,
            "insumos_utilizados": [
                {"insumo_id": INSUMO_PANTALLA, "cantidad": "1"}
            ],
        },
    ).json()
    d2 = next(d for d in orden["reparaciones_detail"] if d["id"] == det2)
    assert d2["estado"] == "COMPLETO"

    # resolver = COMPLETA: recien ahora se cierra la toma (BR-REP-018).
    assert orden["tomas"][0]["estado"] == "CERRADA"

    # --- Control tecnico granular, Detalle por Detalle ----------------------

    orden = cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={"usuario_id": RECEPCION, "detalle_id": det1},
    ).json()
    d1 = next(d for d in orden["reparaciones_detail"] if d["id"] == det1)
    d2 = next(d for d in orden["reparaciones_detail"] if d["id"] == det2)
    assert d1["control_estado"] == "APROBADO"
    assert d2["control_estado"] == "PENDIENTE"
    # No se marca REPARACION_LISTA hasta que TODOS los Detalles esten
    # aprobados (PROC-REP-240).
    assert orden["estado_workflow"] == "EN_REPARACION"

    orden = cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={"usuario_id": RECEPCION, "detalle_id": det2},
    ).json()
    d1 = next(d for d in orden["reparaciones_detail"] if d["id"] == det1)
    d2 = next(d for d in orden["reparaciones_detail"] if d["id"] == det2)
    assert d1["control_estado"] == "APROBADO"
    assert d2["control_estado"] == "APROBADO"
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    assert orden["resumen"]["puntaje_total"] == 15

    # --- Inventario: movimientos vinculados al Detalle correcto -----------

    contexto = construir_contexto(Settings(data_dir=tmp_path))
    dominio = obtener_orden(contexto, orden_id)

    movimientos_det1 = [
        m
        for m in dominio.movimientos_insumo
        if m.reparacion_detail_id == det1
    ]
    movimientos_det2 = [
        m
        for m in dominio.movimientos_insumo
        if m.reparacion_detail_id == det2
    ]
    assert movimientos_det1
    assert all(m.insumo_id == INSUMO_BATERIA for m in movimientos_det1)
    assert movimientos_det2
    assert all(m.insumo_id == INSUMO_PANTALLA for m in movimientos_det2)


def test_hp_rep_001_un_solo_detalle_sigue_igual(cliente):
    """Compatibilidad: HP-REP-001 con 1 Detalle no cambia de comportamiento.

    Con ``finalizar_definicion`` en su default (``True``), una unica
    llamada a ``POST /details`` sigue agregando el Detalle Y habilitando
    la Orden en el mismo paso, exactamente como antes de Multi-Detalle.
    """
    orden_id = _crear_orden(cliente)

    orden = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO_BATERIA},
    ).json()

    assert orden["estado_workflow"] == "HABILITADA"
    assert len(orden["reparaciones_detail"]) == 1
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is True


def test_liberar_orden_devuelve_la_orden_a_en_cola(cliente):
    """PROC-REP-212 ("No") -> 213: liberar sin terminar el trabajo."""
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={
            "usuario_id": RECEPCION,
            "tipo_reparacion_id": TIPO_BATERIA,
            "finalizar_definicion": False,
        },
    )
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO_PANTALLA},
    )
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    )

    orden = cliente.post(
        f"/api/orders/{orden_id}/release",
        json={"usuario_id": TECNICO},
    ).json()

    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["tomas"][0]["estado"] == "CERRADA"
    assert [a["codigo"] for a in orden["acciones_disponibles"]] == [
        "TOMAR",
        "REGISTRAR_PAGO",
    ]


def test_control_tecnico_rechaza_si_algun_detalle_no_es_terminal(cliente):
    """PROC-REP-220 solo se alcanza con la Orden entera terminal.

    Con DET-001 COMPLETO y DET-002 todavia DEFINIDO, ni siquiera se
    puede iniciar el control tecnico de DET-001 -no alcanza con que ESE
    Detalle este COMPLETO si otro de la misma Orden no lo esta.
    """
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={
            "usuario_id": RECEPCION,
            "tipo_reparacion_id": TIPO_BATERIA,
            "finalizar_definicion": False,
        },
    )
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO_PANTALLA},
    )
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    orden = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    ).json()
    det1 = orden["reparaciones_detail"][0]["id"]

    orden = cliente.post(
        f"/api/orders/{orden_id}/details/{det1}/start",
        json={"usuario_id": TECNICO},
    ).json()
    ejecucion_1 = orden["ejecuciones"][0]["id"]
    orden = cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_1}/complete",
        json={
            "usuario_id": TECNICO,
            "insumos_utilizados": [
                {"insumo_id": INSUMO_BATERIA, "cantidad": "1"}
            ],
        },
    ).json()
    assert orden["reparaciones_detail"][0]["estado"] == "COMPLETO"
    assert orden["reparaciones_detail"][1]["estado"] == "DEFINIDO"

    # La accion ni siquiera se ofrece.
    assert "APROBAR_CONTROL" not in [
        a["codigo"] for a in orden["acciones_disponibles"]
    ]

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={"usuario_id": RECEPCION, "detalle_id": det1},
    )
    assert respuesta.status_code == 409, respuesta.text
    assert (
        respuesta.json()["error"]["codigo"] == "PRECONDICION_INVALIDA"
    )

    # Nada cambio: DET-001 sigue con control PENDIENTE.
    sin_cambios = cliente.get(f"/api/orders/{orden_id}").json()
    assert sin_cambios["reparaciones_detail"][0]["control_estado"] == (
        "PENDIENTE"
    )
