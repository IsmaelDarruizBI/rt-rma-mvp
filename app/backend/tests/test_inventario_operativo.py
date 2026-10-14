"""Inventario operativo y custodia antes de ejecutar (MVP v2).

Casos 1-25: consulta de fisico/reservado/disponible, ingresos y ajustes
con motivo (todo ajuste negativo se confirma), historial de movimientos,
faltantes y su correccion, permisos, revalidacion masiva de Ordenes que
esperan recursos -tambien con factibilidad parcial-, y la regla "sin
custodia confirmada no se inicia ninguna Ejecucion". Todo con catalogos y
datos en ``tmp_path``.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.models import (
    CondicionReparacionDetail,
    MovimientoStock,
    TipoMovimientoInsumo,
)
from app.repositories import ConflictoDeEscrituraError
from app.services import (
    PrecondicionInvalidaError,
    desbloquear_detalles_con_recursos,
    detalles_bloqueados_por_recursos,
)
from app.storage import JsonCatalogosRepository
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    COORDINADOR,
    INSUMO_BATERIA,
    INSUMO_PANTALLA,
    PANTALLA,
    RECEPCION,
    TECNICO,
    agregar,
    archivo,
    autorizar_todo,
    cerrar_ejecucion,
    cliente_http,
    conflicto,
    crear,
    decidir,
    definida,
    finalizar,
    iniciar,
    ok,
    repo_ordenes,
    stock,
    tomada,
)
from tests.fixtures.custodia import confirmar_recepcion


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path, stock="8") as test_client:
        yield test_client


def _cliente(tmp_path, stock_bateria, stock_pantalla="5", por_detalle="1"):
    """Catalogo propio: stock por insumo y unidades que reserva TR-001."""
    with cliente_http(tmp_path) as _:
        pass
    catalogos = tmp_path / "catalogs"
    insumos = json.loads((catalogos / "insumos.json").read_text("utf-8"))
    for insumo in insumos:
        insumo["stock_fisico"] = (
            stock_bateria if insumo["id"] == INSUMO_BATERIA else stock_pantalla
        )
    (catalogos / "insumos.json").write_text(json.dumps(insumos), "utf-8")
    previstos = json.loads(
        (catalogos / "tipo_reparacion_insumos.json").read_text("utf-8")
    )
    for previsto in previstos:
        if previsto["tipo_reparacion_id"] == BATERIA:
            previsto["cantidad"] = por_detalle
    (catalogos / "tipo_reparacion_insumos.json").write_text(
        json.dumps(previstos), "utf-8"
    )
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    return TestClient(create_app(Settings(data_dir=tmp_path)))


# --- Atajos ------------------------------------------------------------------


def _inventario(cliente, **parametros) -> list[dict]:
    return ok(cliente.get("/api/inventory", params=parametros))


def _situacion(cliente, insumo_id=INSUMO_BATERIA) -> dict:
    return next(i for i in _inventario(cliente) if i["id"] == insumo_id)


def _detalle(cliente, insumo_id=INSUMO_BATERIA) -> dict:
    return ok(cliente.get(f"/api/inventory/{insumo_id}"))


def _ingreso(cliente, cantidad, insumo_id=INSUMO_BATERIA, **extra):
    cuerpo = {"usuario_id": COORDINADOR, "cantidad": cantidad}
    cuerpo.setdefault("motivo", "Compra al proveedor")
    cuerpo.update(extra)
    return cliente.post(f"/api/inventory/{insumo_id}/receipts", json=cuerpo)


def _ajuste(cliente, diferencia, insumo_id=INSUMO_BATERIA, **extra):
    cuerpo = {
        "usuario_id": ADMINISTRADOR,
        "diferencia": diferencia,
        "motivo": "Conteo fisico",
    }
    cuerpo.update(extra)
    return cliente.post(f"/api/inventory/{insumo_id}/adjustments", json=cuerpo)


def _revalidar(cliente, usuario=COORDINADOR):
    return cliente.post(
        "/api/inventory/revalidate-orders", json={"usuario_id": usuario}
    )


def _con_reserva(cliente, tipo=BATERIA) -> str:
    """Orden definida, con custodia, tomada y con el Detalle iniciado."""
    orden_id = definida(cliente, tipo)
    tomada(cliente, orden_id)
    iniciar(cliente, orden_id)
    return orden_id


def _sin_custodia_tomada(cliente) -> str:
    """Definida, autorizada y tomada, con la recepcion SIN confirmar."""
    orden_id = crear(cliente)
    agregar(cliente, orden_id)
    finalizar(cliente, orden_id, confirmar_recepcion=False)
    autorizar_todo(cliente, orden_id)
    tomada(cliente, orden_id)
    return orden_id


def _start(cliente, orden_id, detalle_id="DET-001"):
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": TECNICO},
    )


def _ids(orden) -> list[str]:
    return [paso["referencia_id"] for paso in orden["historial"]]


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _detalles(orden) -> dict[str, dict]:
    return {d["id"]: d for d in orden["reparaciones_detail"]}


# --- 1/2. Consulta -----------------------------------------------------------


def test_1_fisico_reservado_y_disponible(cliente):
    _con_reserva(cliente)

    bateria = _situacion(cliente)
    pantalla = _situacion(cliente, INSUMO_PANTALLA)

    assert (bateria["stock_fisico"], bateria["reservado"]) == ("8", "1")
    assert bateria["disponible"] == "7"
    assert bateria["ordenes_con_reserva"] == 1
    assert bateria["detalles_con_reserva"] == 1
    assert bateria["faltante"] is False
    assert (pantalla["reservado"], pantalla["disponible"]) == ("0", "8")
    assert pantalla["codigo"] == "PANT"


def test_2_busqueda_por_codigo_y_nombre(cliente):
    assert [i["id"] for i in _inventario(cliente, buscar="bater")] == [
        INSUMO_BATERIA
    ]
    assert [i["id"] for i in _inventario(cliente, buscar="pant")] == [
        INSUMO_PANTALLA
    ]
    assert _inventario(cliente, buscar="zzz") == []
    assert _inventario(cliente, solo_faltantes=True) == []
    assert len(_inventario(cliente)) == 2


# --- 3/4. Ingresos -----------------------------------------------------------


def test_3_ingreso_suma_al_fisico_sin_tocar_reservas(tmp_path):
    with _cliente(tmp_path, stock_bateria="2") as cliente:
        orden_id = _con_reserva(cliente)
        reserva_antes = archivo(tmp_path, orden_id)

        respuesta = ok(_ingreso(cliente, "10", referencia="REMITO-0012"))

        movimiento = respuesta["movimiento"]
        assert movimiento["tipo"] == "INGRESO"
        assert movimiento["cantidad"] == "10"
        assert (
            movimiento["stock_anterior"],
            movimiento["stock_resultante"],
        ) == (
            "2",
            "12",
        )
        assert movimiento["usuario_id"] == COORDINADOR
        assert movimiento["observacion"] == "Compra al proveedor"
        assert movimiento["referencia"] == "REMITO-0012"
        assert respuesta["insumo"]["stock_fisico"] == "12"
        assert respuesta["insumo"]["reservado"] == "1"
        assert stock(tmp_path) == Decimal("12")
        # La Orden con la reserva no cambia.
        assert archivo(tmp_path, orden_id) == reserva_antes


@pytest.mark.parametrize("cantidad", ["0", "-3", "abc", "NaN", "Infinity"])
def test_4_ingreso_invalido_se_rechaza(cliente, tmp_path, cantidad):
    antes = stock(tmp_path)

    assert _ingreso(cliente, cantidad).status_code == 422

    assert stock(tmp_path) == antes


def test_4_ingreso_sin_motivo_o_de_insumo_inexistente(cliente, tmp_path):
    assert _ingreso(cliente, "1", motivo="").status_code == 422
    assert "motivo" in conflicto(_ingreso(cliente, "1", motivo="   "))
    assert _ingreso(cliente, "1", insumo_id="NO-EXISTE").status_code == 404
    assert stock(tmp_path) == Decimal("8")
    assert _detalle(cliente)["movimientos"] == []


# --- 5/6/7/8/9/17. Ajustes ---------------------------------------------------


def test_5_ajuste_positivo(cliente, tmp_path):
    movimiento = ok(_ajuste(cliente, "3", motivo="Aparecieron en deposito"))[
        "movimiento"
    ]

    assert movimiento["tipo"] == "AJUSTE_POSITIVO"
    assert movimiento["cantidad"] == "3"
    assert movimiento["stock_resultante"] == "11"
    assert stock(tmp_path) == Decimal("11")


def test_6_ajuste_negativo_exige_confirmacion(tmp_path):
    with _cliente(tmp_path, stock_bateria="10") as cliente:
        # Sin confirmar: 409 con el impacto, aunque el disponible alcance.
        mensaje = conflicto(_ajuste(cliente, "-3"), "CONFIRMACION_REQUERIDA")
        assert "fisico 10 -> 7, disponible 10 -> 7" in mensaje
        assert "Deja el disponible negativo" not in mensaje
        assert stock(tmp_path) == Decimal("10")
        assert _detalle(cliente)["movimientos"] == []

        movimiento = ok(_ajuste(cliente, "-3", confirmado=True))["movimiento"]
        assert movimiento["tipo"] == "AJUSTE_NEGATIVO"
        assert movimiento["cantidad"] == "3"
        assert movimiento["usuario_id"] == ADMINISTRADOR
        assert movimiento["observacion"] == "Conteo fisico"
        assert movimiento["fecha"]
        assert stock(tmp_path) == Decimal("7")

        # Nunca por debajo de cero, ni confirmado; ni una diferencia nula.
        assert "por debajo de cero" in conflicto(_ajuste(cliente, "-8"))
        assert "por debajo de cero" in conflicto(
            _ajuste(cliente, "-8", confirmado=True)
        )
        assert "distinta de cero" in conflicto(_ajuste(cliente, "0"))
        assert stock(tmp_path) == Decimal("7")
        # Un ajuste positivo no pide confirmacion.
        ok(_ajuste(cliente, "2"))
        assert stock(tmp_path) == Decimal("9")


def test_6_un_ajuste_negativo_reintentado_no_se_duplica(tmp_path):
    with _cliente(tmp_path, stock_bateria="10") as cliente:
        ok(_ajuste(cliente, "-2", confirmado=True, operacion_id="aj-1"))

        # El reintento choca con el primero, confirmado o no.
        for confirmado in (True, False):
            mensaje = conflicto(
                _ajuste(
                    cliente, "-2", confirmado=confirmado, operacion_id="aj-1"
                )
            )
            assert "no se aplica dos veces" in mensaje

        assert stock(tmp_path) == Decimal("8")
        assert [m["tipo"] for m in _detalle(cliente)["movimientos"]] == [
            "AJUSTE_NEGATIVO"
        ]


def test_7_8_9_17_ajuste_con_reservas_exige_confirmacion(tmp_path):
    """Fisico 8, reservado 5, salida de 4: fisico 4, disponible -1."""
    with _cliente(tmp_path, stock_bateria="8", por_detalle="5") as cliente:
        orden_id = _con_reserva(cliente)
        assert _situacion(cliente)["disponible"] == "3"
        orden_antes = archivo(tmp_path, orden_id)

        mensaje = conflicto(_ajuste(cliente, "-4"), "CONFIRMACION_REQUERIDA")
        assert "disponible 3 -> -1" in mensaje
        assert "Deja el disponible negativo: hay 5 reservadas" in mensaje
        assert stock(tmp_path) == Decimal("8")

        ok(_ajuste(cliente, "-4", confirmado=True))

        situacion = _situacion(cliente)
        assert situacion["stock_fisico"] == "4"
        assert situacion["reservado"] == "5"
        assert situacion["disponible"] == "-1"
        assert situacion["disponible_negativo"] is True
        assert situacion["faltante"] is True
        assert [
            i["id"] for i in _inventario(cliente, solo_faltantes=True)
        ] == [INSUMO_BATERIA]
        # 17: las reservas de la Orden no se tocan.
        assert archivo(tmp_path, orden_id) == orden_antes
        (reserva,) = _detalle(cliente)["reservas"]
        assert (reserva["orden_id"], reserva["cantidad"]) == (orden_id, "5")
        (faltante,) = _detalle(cliente)["faltantes"]
        assert faltante["origen"] == "AJUSTE_NEGATIVO"
        assert "-1" in faltante["descripcion"]


# --- 10/11. Historial y duplicados -------------------------------------------


def test_10_historial_de_movimientos(cliente):
    orden_id = definida(cliente)
    tomada(cliente, orden_id)
    ejecucion_id = iniciar(cliente, orden_id)
    ok(cerrar_ejecucion(cliente, orden_id, ejecucion_id))
    ok(_ingreso(cliente, "4"))
    ok(_ajuste(cliente, "-1", confirmado=True))

    movimientos = _detalle(cliente)["movimientos"]

    assert [m["tipo"] for m in movimientos] == [
        "RESERVA",
        "CONSUMO",
        "INGRESO",
        "AJUSTE_NEGATIVO",
    ]
    reserva, consumo, ingreso, ajuste = movimientos
    assert (reserva["origen"], reserva["orden_id"]) == ("ORDEN", orden_id)
    assert reserva["detalle_id"] == "DET-001"
    assert consumo["movimiento_origen_id"] == reserva["id"]
    assert consumo["ejecucion_id"] == ejecucion_id
    assert (ingreso["origen"], ingreso["usuario_id"]) == (
        "INVENTARIO",
        COORDINADOR,
    )
    assert (ingreso["stock_anterior"], ingreso["stock_resultante"]) == (
        "7",
        "11",
    )
    assert ajuste["usuario_id"] == ADMINISTRADOR
    # Filtros de la consulta global.
    consumos = ok(
        cliente.get(
            "/api/inventory/movements",
            params={"insumo_id": INSUMO_BATERIA, "tipo": "CONSUMO"},
        )
    )
    assert [m["id"] for m in consumos] == [consumo["id"]]


def test_11_un_reintento_no_duplica_movimientos(cliente, tmp_path):
    ok(_ingreso(cliente, "2", operacion_id="op-1"))
    assert "op-1" not in conflicto(_ingreso(cliente, "2", operacion_id="op-1"))
    assert stock(tmp_path) == Decimal("10")

    ok(_ingreso(cliente, "1", referencia="REM-9"))
    assert "REM-9" in conflicto(_ingreso(cliente, "1", referencia="rem-9"))
    # La misma referencia en otro insumo es otra linea del remito.
    ok(_ingreso(cliente, "1", insumo_id=INSUMO_PANTALLA, referencia="REM-9"))

    assert stock(tmp_path) == Decimal("11")
    assert len(_detalle(cliente)["movimientos"]) == 2


# --- 12. Permisos ------------------------------------------------------------


def test_12_permisos_por_rol(cliente, tmp_path):
    for usuario in (TECNICO, RECEPCION):
        conflicto(_ingreso(cliente, "1", usuario_id=usuario))
        conflicto(_ajuste(cliente, "1", usuario_id=usuario))
        conflicto(_revalidar(cliente, usuario=usuario))
    assert stock(tmp_path) == Decimal("8")

    ok(_ingreso(cliente, "1", usuario_id=ADMINISTRADOR))
    ok(_ajuste(cliente, "1", usuario_id=COORDINADOR))
    ok(_revalidar(cliente, usuario=ADMINISTRADOR))
    # La consulta es de todos (el MVP no autentica lecturas).
    assert _inventario(cliente)


# --- 13/14/15/16. Revalidacion masiva ----------------------------------------


def test_13_revalidacion_de_ordenes_esperando_recursos(tmp_path):
    with _cliente(tmp_path, stock_bateria="0") as cliente:
        orden_id = definida(cliente)
        orden = ok(cliente.get(f"/api/orders/{orden_id}"))
        assert orden["current_process"] == "PROC-REP-100"

        antes = archivo(tmp_path, orden_id)

        sin_stock = ok(_revalidar(cliente))
        assert (sin_stock["evaluadas"], sin_stock["siguen_esperando"]) == (
            1,
            1,
        )
        assert "DET-001 [INS-001]" in sin_stock["ordenes"][0]["detalle"]
        # Sin recursos nuevos no se recorre ningun nodo: repetir la
        # revalidacion no duplica transiciones.
        ok(_revalidar(cliente))
        assert archivo(tmp_path, orden_id) == antes

        ok(_ingreso(cliente, "3"))
        resultado = ok(_revalidar(cliente))

        assert (resultado["evaluadas"], resultado["trabajables"]) == (1, 1)
        (fila,) = resultado["ordenes"]
        assert (fila["orden_id"], fila["resultado"]) == (
            orden_id,
            "TRABAJABLE",
        )
        assert fila["detalles_revalidados"] == ["DET-001"]
        orden = ok(cliente.get(f"/api/orders/{orden_id}"))
        assert orden["estado_workflow"] == "HABILITADA"
        assert orden["current_process"] == "PROC-REP-140"
        assert _ids(orden)[-6:] == [
            "ACC-REP-028",
            "PROC-REP-110",
            "PROC-REP-120",
            "PROC-REP-080",
            "PROC-REP-090",
            "PROC-REP-140",
        ]
        traza = [
            p
            for p in orden["historial"]
            if p["referencia_id"] == "ACC-REP-028"
        ]
        assert traza[-1]["usuario_id"] == COORDINADOR
        # Revalidar no reserva: el stock queda libre hasta iniciar.
        assert _situacion(cliente)["reservado"] == "0"
        # Ya habilitada, no vuelve a evaluarse.
        habilitada = archivo(tmp_path, orden_id)
        assert ok(_revalidar(cliente))["ordenes"] == []
        assert archivo(tmp_path, orden_id) == habilitada


def test_14_revalidacion_respeta_la_autorizacion_pendiente(tmp_path):
    with _cliente(tmp_path, stock_bateria="0") as cliente:
        orden_id = crear(cliente)
        agregar(cliente, orden_id, BATERIA)
        agregar(cliente, orden_id, PANTALLA)
        finalizar(cliente, orden_id)
        ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
        assert (
            ok(cliente.get(f"/api/orders/{orden_id}"))["current_process"]
            == "PROC-REP-100"
        )
        ok(_ingreso(cliente, "2"))
        antes = archivo(tmp_path, orden_id)

        (fila,) = ok(_revalidar(cliente))["ordenes"]

        # Con un Detalle esperando al cliente no se presume nada: la Orden
        # no se toca y se informa que falta.
        assert fila["resultado"] == "OTRA_INTERVENCION"
        assert "decision del cliente sobre DET-002" in fila["detalle"]
        assert archivo(tmp_path, orden_id) == antes
        # Decidido el cliente, la Orden queda esperando recursos y la
        # revalidacion ya puede usar el stock nuevo.
        orden = ok(decidir(cliente, orden_id, {"DET-002": "RECHAZADO"}))
        assert orden["current_process"] == "PROC-REP-120"
        (fila,) = ok(_revalidar(cliente))["ordenes"]
        assert fila["resultado"] == "TRABAJABLE"
        orden = ok(cliente.get(f"/api/orders/{orden_id}"))
        detalles = {d["id"]: d for d in orden["reparaciones_detail"]}
        assert detalles["DET-001"]["condicion"] == "SIN_BLOQUEO"
        assert detalles["DET-002"]["estado"] == "CANCELADO"
        assert orden["estado_workflow"] == "HABILITADA"


def test_15_no_toca_ordenes_que_no_esperan_recursos(tmp_path):
    with _cliente(tmp_path, stock_bateria="5", stock_pantalla="0") as cliente:
        habilitada = definida(cliente)
        parcial = definida(cliente, BATERIA, PANTALLA)
        antes = (archivo(tmp_path, habilitada), archivo(tmp_path, parcial))

        resultado = ok(_revalidar(cliente))

        # La habilitada ni se evalua; la parcial (activa, con un Detalle
        # bloqueado y todavia sin stock) se informa sin modificarse.
        assert [fila["orden_id"] for fila in resultado["ordenes"]] == [parcial]
        assert resultado["ordenes"][0]["resultado"] == "SIGUE_ESPERANDO"
        assert "DET-002 [INS-002]" in resultado["ordenes"][0]["detalle"]
        assert (
            archivo(tmp_path, habilitada),
            archivo(tmp_path, parcial),
        ) == antes


def test_16_revalidar_no_cambia_la_prioridad(tmp_path):
    with _cliente(tmp_path, stock_bateria="1") as cliente:
        orden_id = definida(cliente)
        tomada(cliente, orden_id)  # prioridad 3
        ok(_ajuste(cliente, "-1", motivo="Unidad danada", confirmado=True))
        # La reserva falla (EXC-REP-003): 185 -> 186 -> 211 -> 120.
        orden = ok(_start(cliente, orden_id))
        assert orden["current_process"] == "PROC-REP-120"
        ok(_ingreso(cliente, "2"))

        ok(_revalidar(cliente))

        orden = ok(cliente.get(f"/api/orders/{orden_id}"))
        assert orden["estado_workflow"] == "HABILITADA"
        assert orden["prioridad"] == 3
        assert _ids(orden).count("PROC-REP-140") == 2


# --- 13. Revalidacion con factibilidad parcial ------------------------------


def _parcial(cliente) -> str:
    """Habilitada con DET-001 (bateria) trabajable y DET-002 (pantalla)
    bloqueado: no hay pantallas."""
    orden_id = definida(cliente, BATERIA, PANTALLA)
    orden = _orden(cliente, orden_id)
    assert orden["current_process"] == "PROC-REP-140"
    assert {d: v["condicion"] for d, v in _detalles(orden).items()} == {
        "DET-001": "SIN_BLOQUEO",
        "DET-002": "BLOQUEADO_POR_RECURSOS",
    }
    return orden_id


def test_13_parcial_revalida_solo_el_detalle_bloqueado(tmp_path):
    with _cliente(tmp_path, stock_bateria="5", stock_pantalla="0") as cliente:
        orden_id = _parcial(cliente)
        antes = _orden(cliente, orden_id)
        ok(_ingreso(cliente, "1", insumo_id=INSUMO_PANTALLA))

        resultado = ok(_revalidar(cliente))

        (fila,) = resultado["ordenes"]
        assert (fila["resultado"], fila["detalles_revalidados"]) == (
            "TRABAJABLE",
            ["DET-002"],
        )
        assert "sin nueva habilitacion" in fila["detalle"]
        orden = _orden(cliente, orden_id)
        detalles, previos = _detalles(orden), _detalles(antes)
        assert detalles["DET-002"] == {
            **previos["DET-002"],
            "condicion": "SIN_BLOQUEO",
            "situacion_autorizacion": "AUTORIZADO_FACTIBLE",
        }
        assert previos["DET-002"]["situacion_autorizacion"] == (
            "AUTORIZADO_SIN_STOCK"
        )
        # El otro Detalle, la autorizacion y el historial no cambian.
        assert detalles["DET-001"] == previos["DET-001"]
        assert (
            detalles["DET-002"]["autorizaciones"]
            == (previos["DET-002"]["autorizaciones"])
        )
        historial = orden["historial"]
        assert historial[: len(antes["historial"])] == antes["historial"]
        (traza,) = historial[len(antes["historial"]) :]
        assert (
            traza["referencia_id"],
            traza["reparacion_detail_id"],
            traza["usuario_id"],
        ) == ("ACC-REP-028", "DET-002", COORDINADOR)
        assert traza["process_id"] is None
        # Habilitada antes: sin segunda habilitacion ni otro nodo.
        assert _ids(orden).count("PROC-REP-140") == 1
        assert (orden["current_process"], orden["estado_workflow"]) == (
            antes["current_process"],
            antes["estado_workflow"],
        )
        assert orden["prioridad"] == antes["prioridad"]
        # Revalidar no reserva.
        assert _situacion(cliente, INSUMO_PANTALLA)["reservado"] == "0"

        # Repetida: ya no hay nada bloqueado, nada cambia.
        despues = archivo(tmp_path, orden_id)
        assert ok(_revalidar(cliente))["ordenes"] == []
        assert archivo(tmp_path, orden_id) == despues


def test_13_parcial_no_toca_la_toma_ni_la_ejecucion(tmp_path):
    with _cliente(tmp_path, stock_bateria="5", stock_pantalla="0") as cliente:
        orden_id = _parcial(cliente)
        tomada(cliente, orden_id)  # prioridad 3
        ejecucion_id = iniciar(cliente, orden_id)
        antes = _orden(cliente, orden_id)
        assert antes["current_process"] == "PROC-REP-185"
        ok(_ingreso(cliente, "1", insumo_id=INSUMO_PANTALLA))

        (fila,) = ok(_revalidar(cliente))["ordenes"]

        assert fila["resultado"] == "TRABAJABLE"
        orden = _orden(cliente, orden_id)
        assert orden["tomas"] == antes["tomas"]
        assert orden["ejecuciones"] == antes["ejecuciones"]
        assert (
            orden["current_process"],
            orden["estado_workflow"],
            orden["prioridad"],
        ) == ("PROC-REP-185", antes["estado_workflow"], 3)
        assert _detalles(orden)["DET-001"] == _detalles(antes)["DET-001"]
        assert _situacion(cliente, INSUMO_PANTALLA)["reservado"] == "0"

        # La Orden sigue operando: termina DET-001 y el mismo tecnico, con
        # la misma toma, inicia DET-002 (recien ahi se reserva).
        ok(cerrar_ejecucion(cliente, orden_id, ejecucion_id))
        iniciar(cliente, orden_id, "DET-002")
        orden = _orden(cliente, orden_id)
        assert orden["tomas"][-1] == antes["tomas"][-1]
        assert _situacion(cliente, INSUMO_PANTALLA)["reservado"] == "1"


def test_13_parcial_respeta_la_autorizacion_pendiente(tmp_path):
    with _cliente(tmp_path, stock_bateria="5", stock_pantalla="0") as cliente:
        orden_id = crear(cliente)
        for tipo in (BATERIA, PANTALLA, PANTALLA):
            agregar(cliente, orden_id, tipo)
        finalizar(cliente, orden_id)
        ok(
            decidir(
                cliente,
                orden_id,
                {"DET-001": "AUTORIZADO", "DET-002": "AUTORIZADO"},
            )
        )
        antes = _orden(cliente, orden_id)
        assert antes["current_process"] == "PROC-REP-140"
        assert _detalles(antes)["DET-003"]["estado_autorizacion"] == (
            "PENDIENTE"
        )
        # Alcanzaria para los dos Detalles de pantalla.
        ok(_ingreso(cliente, "2", insumo_id=INSUMO_PANTALLA))

        (fila,) = ok(_revalidar(cliente))["ordenes"]

        assert fila["detalles_revalidados"] == ["DET-002"]
        detalles = _detalles(_orden(cliente, orden_id))
        assert detalles["DET-002"]["condicion"] == "SIN_BLOQUEO"
        # El pendiente de autorizacion no se evalua ni se habilita.
        assert detalles["DET-003"] == _detalles(antes)["DET-003"]


def test_13_un_detalle_en_revision_no_es_un_bloqueo_por_recursos(tmp_path):
    with _cliente(tmp_path, stock_bateria="5", stock_pantalla="0") as cliente:
        orden_id = _parcial(cliente)
    orden = repo_ordenes(tmp_path).obtener(orden_id)
    en_revision = orden.model_copy(deep=True)
    en_revision.reparaciones_detail[
        1
    ].condicion = CondicionReparacionDetail.REQUIERE_DEFINICION

    assert detalles_bloqueados_por_recursos(orden) == ["DET-002"]
    assert detalles_bloqueados_por_recursos(en_revision) == []
    with pytest.raises(PrecondicionInvalidaError):
        desbloquear_detalles_con_recursos(
            en_revision,
            detalle_ids=["DET-002"],
            usuario_id=COORDINADOR,
            fecha=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )


# --- 18/19. Override, faltante y correccion ----------------------------------


def test_18_19_consumo_con_override_y_correccion_del_faltante(tmp_path):
    with _cliente(tmp_path, stock_bateria="1") as cliente:
        con_reserva = _con_reserva(cliente)
        forzada = definida(cliente)
        assert (
            ok(cliente.get(f"/api/orders/{forzada}"))["current_process"]
            == "PROC-REP-100"
        )
        ok(
            cliente.post(
                f"/api/orders/{forzada}/details/DET-001/resources/override",
                json={
                    "usuario_id": COORDINADOR,
                    "motivo": "Urgente",
                    "confirmado": True,
                },
            )
        )
        tomada(cliente, forzada)
        ejecucion = iniciar(cliente, forzada)
        assert _situacion(cliente)["disponible"] == "-1"
        ok(cerrar_ejecucion(cliente, forzada, ejecucion))
        # La Orden con reserva consume igual: el fisico queda negativo.
        ejecucion = _ultima_ejecucion(cliente, con_reserva)
        ok(cerrar_ejecucion(cliente, con_reserva, ejecucion))

        situacion = _situacion(cliente)
        assert situacion["stock_fisico"] == "-1"
        assert situacion["fisico_negativo"] is True
        (faltante,) = _detalle(cliente)["faltantes"]
        assert faltante["origen"] == "CONSUMO"
        assert faltante["orden_id"] == con_reserva
        # Un ajuste manual no lo hunde mas; se corrige con un ingreso.
        conflicto(_ajuste(cliente, "-1"))
        ok(_ingreso(cliente, "3", motivo="Reposicion por faltante"))

        detalle = _detalle(cliente)
        assert detalle["insumo"]["stock_fisico"] == "2"
        assert detalle["insumo"]["faltante"] is False
        # La evidencia del faltante y los movimientos se conservan.
        assert len(detalle["faltantes"]) == 1
        assert [m["tipo"] for m in detalle["movimientos"]].count(
            "CONSUMO"
        ) == 2


def _ultima_ejecucion(cliente, orden_id) -> str:
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    return [e for e in orden["ejecuciones"] if e["estado"] == "EN_PROGRESO"][
        0
    ]["id"]


# --- 20-24. Custodia antes de ejecutar ---------------------------------------


def test_20_24_sin_custodia_no_se_inicia_ninguna_ejecucion(cliente, tmp_path):
    orden_id = _sin_custodia_tomada(cliente)
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    (iniciar_accion,) = [
        a
        for a in orden["acciones_disponibles"]
        if a["codigo"] == "INICIAR_DETALLE"
    ]
    assert iniciar_accion["bloqueo"] == (
        "Debe confirmarse la recepcion fisica del equipo antes de iniciar la "
        "reparacion"
    )
    antes = archivo(tmp_path, orden_id)
    stock_antes = stock(tmp_path)

    mensaje = conflicto(_start(cliente, orden_id))

    assert mensaje.startswith("Debe confirmarse la recepcion fisica")
    # 24: ni Ejecucion, ni reserva, ni pasos, ni stock.
    assert archivo(tmp_path, orden_id) == antes
    assert stock(tmp_path) == stock_antes
    assert _situacion(cliente)["reservado"] == "0"


def test_21_equipo_no_recibido_no_se_ejecuta(cliente, tmp_path):
    """La guarda cubre tambien NO_RECIBIDO (estado que por la API solo
    alcanza una Orden cancelada; aca se fuerza en el JSON)."""
    orden_id = _sin_custodia_tomada(cliente)
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["recepcion"]["no_recibido"] = {
        "usuario_id": RECEPCION,
        "fecha": "2026-10-01T10:00:00Z",
        "motivo": "No lo trajo.",
    }
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    assert "no se recibio" in conflicto(_start(cliente, orden_id))
    assert _situacion(cliente)["reservado"] == "0"


def test_22_con_custodia_confirmada_se_ejecuta(cliente):
    orden_id = _sin_custodia_tomada(cliente)
    orden = confirmar_recepcion(cliente, orden_id)
    assert all(
        a["bloqueo"] is None
        for a in orden["acciones_disponibles"]
        if a["codigo"] == "INICIAR_DETALLE"
    )

    orden = ok(_start(cliente, orden_id))

    assert orden["estado_workflow"] == "EN_REPARACION"
    assert _situacion(cliente)["reservado"] == "1"


def test_23_rt_interno_conserva_su_circuito(cliente):
    orden_id = ok(
        cliente.post(
            "/api/orders/rt-interno",
            json={
                "usuario_id": RECEPCION,
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 13",
                    "falla_reportada": "No carga.",
                },
                "referencia_rt": "RT-0007",
            },
        )
    )["id"]
    agregar(cliente, orden_id)
    finalizar(cliente, orden_id)
    tomada(cliente, orden_id)

    orden = ok(_start(cliente, orden_id))

    assert orden["custodia"]["confirmacion_requerida"] is False
    assert orden["estado_workflow"] == "EN_REPARACION"


# --- 25. Compatibilidad ------------------------------------------------------


def test_25_json_anterior(cliente, tmp_path):
    # Catalogo sin "unidad" y sin historico de movimientos: carga igual.
    insumos = json.loads(
        (tmp_path / "catalogs" / "insumos.json").read_text("utf-8")
    )
    for insumo in insumos:
        insumo.pop("unidad", None)
    (tmp_path / "catalogs" / "insumos.json").write_text(
        json.dumps(insumos), "utf-8"
    )
    assert _situacion(cliente)["unidad"] is None
    assert _detalle(cliente)["movimientos"] == []

    # Orden anterior sin registro de recepcion: no se presume la custodia.
    orden_id = _sin_custodia_tomada(cliente)
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos.pop("recepcion")
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert "regularizala" in conflicto(_start(cliente, orden_id))


def test_el_historico_no_queda_a_medias_si_el_stock_cambio(tmp_path):
    """El repositorio rechaza un movimiento armado sobre un stock viejo."""
    with cliente_http(tmp_path) as _:
        pass
    repo = JsonCatalogosRepository(tmp_path / "catalogs")
    movimiento = MovimientoStock(
        id="MST-1",
        tipo=TipoMovimientoInsumo.INGRESO,
        insumo_id=INSUMO_BATERIA,
        cantidad=Decimal("1"),
        stock_anterior=Decimal("99"),
        stock_resultante=Decimal("100"),
        disponible_resultante=Decimal("100"),
        usuario_id=COORDINADOR,
        fecha=datetime(2026, 10, 1, tzinfo=timezone.utc),
        motivo="x",
    )

    with pytest.raises(ConflictoDeEscrituraError):
        repo.registrar_movimiento_stock(movimiento)

    assert repo.listar_movimientos_stock() == []
    assert repo.obtener_insumo(INSUMO_BATERIA).stock_fisico == Decimal("5")
