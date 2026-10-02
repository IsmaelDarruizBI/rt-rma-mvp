"""El historial distingue recorrido de capacidades transversales.

Un paso del Business Process (``PROC-REP-*``) avanza el flujo; una
capacidad transversal (``ACC-REP-*``) deja traza sin moverlo. Antes de
esta iteracion Registrar Pago no dejaba ninguna, y el recorrido no
explicaba que habia pasado entre PROC-REP-266 y PROC-REP-265.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.domain.models import (
    HistorialWorkflow,
    OrdenReparacion,
    TipoReferenciaHistorial,
)
from app.services import registrar_accion_funcional, registrar_paso
from app.storage import JsonOrdenReparacionRepository
from tests.fixtures import flujo_mvp
from tests.fixtures.catalogos_mvp import RECEPCION, t

from .test_api_hp_rep_001 import ADMINISTRADOR as ADMIN_ID
from .test_api_hp_rep_001 import (
    INSUMO,
    TECNICO,
    TIPO,
    _crear_orden,
    _hasta_ejecucion_iniciada,
    cliente,  # noqa: F401  (fixture)
)
from .test_api_hp_rep_001 import RECEPCION as RECEP_ID

AHORA = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


# --- Modelo -------------------------------------------------------------


def test_una_entrada_nace_como_nodo_de_proceso():
    """El default cubre las Ordenes ya persistidas."""
    paso = HistorialWorkflow(
        process_id="PROC-REP-040", accion="CREAR_ORDEN", fecha=AHORA
    )

    assert paso.tipo_referencia is TipoReferenciaHistorial.PROCESS_NODE
    assert paso.referencia_id == "PROC-REP-040"
    assert paso.process_id == "PROC-REP-040"
    assert paso.es_accion_funcional is False


def test_una_accion_funcional_no_expone_process_id():
    """Un consumidor que solo entiende nodos no la confunde."""
    paso = HistorialWorkflow(
        tipo_referencia=TipoReferenciaHistorial.FUNCTIONAL_ACTION,
        referencia_id="ACC-REP-020",
        accion="REGISTRAR_PAGO",
        fecha=AHORA,
    )

    assert paso.process_id is None
    assert paso.es_accion_funcional is True
    assert paso.referencia_id == "ACC-REP-020"


def test_el_json_historico_se_carga_sin_migracion():
    """Las Ordenes ya guardadas traen process_id, no referencia_id."""
    paso = HistorialWorkflow.model_validate(
        {
            "process_id": "PROC-REP-150",
            "accion": "DEFINIR_PRIORIDAD",
            "fecha": "2026-09-21T09:25:00Z",
        }
    )

    assert paso.referencia_id == "PROC-REP-150"
    assert paso.tipo_referencia is TipoReferenciaHistorial.PROCESS_NODE


def test_al_serializar_se_escribe_referencia_id():
    paso = HistorialWorkflow(
        process_id="PROC-REP-040", accion="CREAR_ORDEN", fecha=AHORA
    )

    volcado = paso.model_dump(mode="json")

    assert volcado["referencia_id"] == "PROC-REP-040"
    assert volcado["tipo_referencia"] == "PROCESS_NODE"
    # process_id es solo de lectura: no se persiste.
    assert "process_id" not in volcado


# --- Helpers ------------------------------------------------------------


def test_registrar_paso_sigue_avanzando_el_nodo_actual():
    orden = flujo_mvp.orden_creada()

    nueva = registrar_paso(
        orden,
        process_id="PROC-REP-140",
        accion="HABILITAR_ORDEN",
        fecha=t(20),
    )

    assert nueva.current_process == "PROC-REP-140"
    assert nueva.historial[-1].tipo_referencia is (
        TipoReferenciaHistorial.PROCESS_NODE
    )
    assert orden.current_process != "PROC-REP-140"


def test_registrar_accion_funcional_no_toca_el_nodo_actual():
    orden = flujo_mvp.orden_con_detalle()
    antes = orden.current_process

    nueva = registrar_accion_funcional(
        orden,
        accion_id="ACC-REP-020",
        accion="REGISTRAR_PAGO",
        fecha=t(30),
        usuario_id=RECEPCION.id,
        observacion="ANTICIPO · EFECTIVO · $20000",
    )

    assert nueva.current_process == antes
    assert nueva.updated_at == t(30)
    assert len(nueva.historial) == len(orden.historial) + 1
    assert nueva.historial[-1].es_accion_funcional is True
    # No muta la Orden recibida.
    assert len(orden.historial) == len(nueva.historial) - 1


# --- Persistencia de un historial mixto ---------------------------------


def test_un_historial_mixto_sobrevive_el_round_trip(tmp_path):
    """PROCESS_NODE -> FUNCTIONAL_ACTION -> PROCESS_NODE."""
    repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")

    orden = flujo_mvp.orden_con_detalle()
    orden = registrar_accion_funcional(
        orden,
        accion_id="ACC-REP-020",
        accion="REGISTRAR_PAGO",
        fecha=t(30),
        usuario_id=RECEPCION.id,
        pago_id="PAG-DEMO",
        observacion="ANTICIPO · EFECTIVO · $20000",
    )
    orden = registrar_paso(
        orden, process_id="PROC-REP-140", accion="HABILITAR_ORDEN",
        fecha=t(35),
    )

    repo.guardar(orden)
    recuperada = repo.obtener(orden.id)

    assert recuperada == orden

    tipos = [paso.tipo_referencia.value for paso in recuperada.historial]
    assert "FUNCTIONAL_ACTION" in tipos
    assert tipos[-1] == "PROCESS_NODE"

    transversal = next(
        paso for paso in recuperada.historial if paso.es_accion_funcional
    )
    assert transversal.referencia_id == "ACC-REP-020"
    assert transversal.pago_id == "PAG-DEMO"
    assert transversal.process_id is None
    assert recuperada.current_process == "PROC-REP-140"


def test_la_orden_final_del_happy_path_sigue_siendo_valida(tmp_path):
    """HP-REP-001 completo: nodos mas el pago como accion transversal."""
    repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    orden = flujo_mvp.orden_entregada()

    repo.guardar(orden)

    assert repo.obtener(orden.id) == orden

    transversales = [
        paso for paso in orden.historial if paso.es_accion_funcional
    ]
    assert len(transversales) == 1
    assert transversales[0].referencia_id == "ACC-REP-020"

    # El resto sigue siendo el recorrido de nodos.
    nodos = [
        paso for paso in orden.historial if not paso.es_accion_funcional
    ]
    assert all(
        paso.referencia_id.startswith("PROC-REP-") for paso in nodos
    )
    assert orden.current_process == "EVT-REP-999"


def test_el_fixture_declarativo_se_construye_con_process_id(tmp_path):
    """La forma historica de construir el historial sigue funcionando."""
    from tests.fixtures.hp_rep_001 import construir_orden_hp_rep_001

    repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    orden = construir_orden_hp_rep_001()

    repo.guardar(orden)

    assert repo.obtener(orden.id) == orden
    assert all(
        paso.tipo_referencia is TipoReferenciaHistorial.PROCESS_NODE
        for paso in orden.historial
    )


# --- API ----------------------------------------------------------------


def test_la_api_distingue_los_dos_tipos_de_referencia(cliente):  # noqa: F811
    """GET /api/orders/{id} devuelve ambas clases bien diferenciadas."""
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEP_ID, "tipo_reparacion_id": TIPO},
    )
    cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": RECEP_ID,
            "monto": "20000",
            "metodo": "EFECTIVO",
        },
    )

    historial = cliente.get(f"/api/orders/{orden_id}").json()["historial"]

    nodos = [
        paso for paso in historial
        if paso["tipo_referencia"] == "PROCESS_NODE"
    ]
    transversales = [
        paso for paso in historial
        if paso["tipo_referencia"] == "FUNCTIONAL_ACTION"
    ]

    assert len(transversales) == 1
    assert transversales[0]["referencia_id"] == "ACC-REP-020"
    assert transversales[0]["process_id"] is None
    assert transversales[0]["pago_id"] is not None

    assert nodos, "el recorrido de nodos sigue presente"
    assert all(
        paso["referencia_id"].startswith("PROC-REP-") for paso in nodos
    )
    assert all(paso["process_id"] == paso["referencia_id"] for paso in nodos)


def test_el_pago_final_queda_entre_266_y_265(cliente):  # noqa: F811
    """El historial explica que paso entre el bloqueo y la revalidacion."""
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
        json={"usuario_id": RECEP_ID},
    )
    cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEP_ID}
    )
    orden = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": RECEP_ID,
            "monto": "80000",
            "metodo": "EFECTIVO",
        },
    ).json()

    referencias = [paso["referencia_id"] for paso in orden["historial"]]

    # Secuencia exacta del cierre: bloqueo -> pago -> revalidacion.
    indice_266 = referencias.index("PROC-REP-266")
    cola = referencias[indice_266:]
    assert cola[:3] == ["PROC-REP-266", "ACC-REP-020", "PROC-REP-265"]

    pago = orden["historial"][indice_266 + 1]
    assert pago["accion"] == "REGISTRAR_PAGO"
    assert pago["usuario_id"] == RECEP_ID
    assert "PAGO" in pago["observacion"]
    assert "EFECTIVO" in pago["observacion"]
    assert "80000" in pago["observacion"]
    # PROC-REP-266 no se reemplaza: el bloqueo fue real.
    assert referencias.count("PROC-REP-266") == 1


def test_la_accion_transversal_no_marca_progreso(cliente):  # noqa: F811
    """ACC-REP-020 no pertenece al recorrido de HP-REP-001."""
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEP_ID, "tipo_reparacion_id": TIPO},
    )
    antes = cliente.get(f"/api/orders/{orden_id}").json()
    alcanzados_antes = sum(
        1 for paso in antes["progreso"] if paso["alcanzado"]
    )

    cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": ADMIN_ID,
            "monto": "10000",
            "metodo": "EFECTIVO",
        },
    )

    despues = cliente.get(f"/api/orders/{orden_id}").json()
    alcanzados_despues = sum(
        1 for paso in despues["progreso"] if paso["alcanzado"]
    )

    assert alcanzados_despues == alcanzados_antes


@pytest.mark.parametrize(
    ("usuario_id", "metodo", "monto"),
    [
        (RECEP_ID, "EFECTIVO", "15000"),
        (ADMIN_ID, "TRANSFERENCIA", "25000"),
    ],
)
def test_la_observacion_conserva_tipo_medio_e_importe(
    cliente,  # noqa: F811
    usuario_id,
    metodo,
    monto,
):
    """No hace falta el frontend para reconstruir el significado."""
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEP_ID, "tipo_reparacion_id": TIPO},
    )

    orden = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": usuario_id,
            "monto": monto,
            "metodo": metodo,
        },
    ).json()

    observacion = orden["historial"][-1]["observacion"]

    assert "ANTICIPO" in observacion
    assert metodo in observacion
    assert monto in observacion


def test_el_historial_enlaza_con_el_pago_que_lo_origino(cliente):  # noqa: F811
    """Orden -> Historial -> ACC-REP-020 -> Pago."""
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEP_ID, "tipo_reparacion_id": TIPO},
    )
    orden = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": RECEP_ID,
            "monto": "20000",
            "metodo": "EFECTIVO",
        },
    ).json()

    entrada = orden["historial"][-1]
    pagos_por_id = {pago["id"]: pago for pago in orden["pagos"]}

    assert entrada["pago_id"] in pagos_por_id
    assert pagos_por_id[entrada["pago_id"]]["monto"] == "20000"


def test_el_stock_demo_alcanza_para_varias_pruebas():
    """El catalogo versionado usa stock 2 para permitir demostrar
    EXC-REP-001/002/003 de forma practica en el MVP v2 Demo."""
    from pathlib import Path

    from app.storage import JsonCatalogosRepository

    directorio = Path(__file__).parent.parent / "data" / "catalogs"
    repo = JsonCatalogosRepository(directorio)

    assert repo.obtener_insumo("INS-001").stock_fisico == Decimal("2")


def test_el_cliente_sigue_siendo_un_testclient(cliente):  # noqa: F811
    assert isinstance(cliente, TestClient)


def test_la_orden_es_el_aggregate_esperado():
    assert isinstance(flujo_mvp.orden_creada(), OrdenReparacion)
