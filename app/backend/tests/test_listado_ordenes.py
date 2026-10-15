"""Listado de Ordenes (``GET /api/orders``) para buscar, filtrar y ordenar.

Cada fila trae los datos por los que se busca una Orden y su situacion
operativa -la misma que el detalle, calculada por
``application.situacion`` y no por el frontend-, con los roles del sector
que debe actuar y el tecnico titular. Listar es solo lectura.
"""

from tests.fixtures.api_salidas import (
    COORDINADOR,
    RECEPCION,
    TECNICO,
    agregar,
    aprobar,
    archivo,
    cerrar_ejecucion,
    crear,
    definida,
    finalizar,
    iniciar,
    ok,
    tomada,
)
from tests.fixtures.custodia import entregar
from tests.test_api_hp_rep_002 import _crear_orden_rt
from tests.test_inventario_operativo import _cliente


def _listado(cliente) -> dict[str, dict]:
    return {fila["id"]: fila for fila in ok(cliente.get("/api/orders"))}


def _detalle(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _con_identificadores(cliente) -> str:
    return ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": RECEPCION,
                "cliente": {
                    "nombre": "Laura Gómez",
                    "telefono": "341-555-0101",
                },
                "equipo": {
                    "marca": "Samsung",
                    "modelo": "Galaxy A54",
                    "falla_reportada": "No carga.",
                    "imei": "356789012345678",
                    "numero_serie": "SN-A54-0001",
                },
                "recepcion": {"estado_fisico": "Sin golpes."},
            },
        )
    )["id"]


def test_la_fila_trae_los_datos_de_busqueda(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        externa = _con_identificadores(cliente)
        interna = _crear_orden_rt(cliente)

        filas = _listado(cliente)

        fila = filas[externa]
        assert fila["cliente_nombre"] == "Laura Gómez"
        assert fila["cliente_telefono"] == "341-555-0101"
        assert (fila["equipo_marca"], fila["equipo_modelo"]) == (
            "Samsung",
            "Galaxy A54",
        )
        assert (fila["imei"], fila["numero_serie"]) == (
            "356789012345678",
            "SN-A54-0001",
        )
        assert fila["cobrable"] is True and fila["cerrada"] is False
        rt = filas[interna]
        assert rt["referencia_rt"] == "RT-INGRESO-0001"
        assert rt["cliente_telefono"] is None
        assert rt["cobrable"] is False


def test_la_situacion_del_listado_es_la_del_detalle(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        recien = crear(cliente)
        en_cola = definida(cliente)
        ok(
            cliente.post(
                f"/api/orders/{en_cola}/queue",
                json={"usuario_id": COORDINADOR, "prioridad": 2},
            )
        )
        tomada_id = definida(cliente)
        tomada(cliente, tomada_id)

        filas = _listado(cliente)

        for orden_id in (recien, en_cola, tomada_id):
            completa = _detalle(cliente, orden_id)["situacion"]
            resumida = filas[orden_id]["situacion"]
            for campo in (
                "codigo",
                "titulo",
                "responsable",
                "roles",
                "titular_id",
                "desde",
            ):
                assert resumida[campo] == completa[campo], (orden_id, campo)
        assert filas[recien]["situacion"]["codigo"] == "PENDIENTE_RECEPCION"
        assert (
            filas[en_cola]["situacion"]["titulo"]
            == "En cola (prioridad 2 · Alta)"
        )
        assert filas[tomada_id]["situacion"]["codigo"] == "TOMADA"


def test_roles_del_sector_y_tecnico_titular(tmp_path):
    with _cliente(tmp_path, stock_bateria="0") as cliente:
        esperando_cliente = crear(cliente)
        agregar(cliente, esperando_cliente)
        finalizar(cliente, esperando_cliente)
        sin_repuestos = definida(cliente)

        filas = _listado(cliente)

        assert filas[esperando_cliente]["situacion"]["roles"] == ["RECEPCION"]
        assert filas[sin_repuestos]["situacion"]["roles"] == [
            "COORDINADOR_RMA"
        ]
        assert filas[sin_repuestos]["tecnico_id"] is None

    with _cliente(tmp_path / "taller", stock_bateria="5") as cliente:
        orden_id = definida(cliente)
        tomada(cliente, orden_id)
        fila = _listado(cliente)[orden_id]
        assert fila["tecnico_id"] == TECNICO
        assert fila["situacion"]["roles"] == ["TECNICO"]
        assert fila["situacion"]["titular_id"] == TECNICO


def test_una_tarea_de_cualquier_usuario_es_de_todos_los_sectores(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _crear_orden_rt(cliente)
        agregar(cliente, orden_id)
        finalizar(cliente, orden_id, confirmar_recepcion=False)
        tomada(cliente, orden_id)
        ok(cerrar_ejecucion(cliente, orden_id, iniciar(cliente, orden_id)))
        ok(aprobar(cliente, orden_id, "DET-001"))

        situacion = _listado(cliente)[orden_id]["situacion"]

        # Informar a Gestion RT es un paso de sistema: lo puede hacer
        # cualquiera, asi que esta pendiente para cualquier sector.
        assert situacion["responsable"] == "Cualquier usuario"
        assert situacion["roles"] == [
            "RECEPCION",
            "TECNICO",
            "COORDINADOR_RMA",
            "ADMINISTRADOR",
        ]


def test_una_orden_entregada_figura_cerrada(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente)
        tomada(cliente, orden_id)
        ok(cerrar_ejecucion(cliente, orden_id, iniciar(cliente, orden_id)))
        ok(aprobar(cliente, orden_id, "DET-001"))
        saldo = ok(
            cliente.post(
                f"/api/orders/{orden_id}/notify",
                json={"usuario_id": RECEPCION},
            )
        )["resumen"]["saldo"]
        ok(
            cliente.post(
                f"/api/orders/{orden_id}/payments",
                json={
                    "usuario_id": RECEPCION,
                    "monto": saldo,
                    "metodo": "EFECTIVO",
                },
            )
        )
        ok(entregar(cliente, orden_id))

        fila = _listado(cliente)[orden_id]

        assert fila["cerrada"] is True
        assert fila["situacion"]["codigo"] == "CERRADA"
        assert fila["situacion"]["roles"] == []
        assert fila["tecnico_id"] is None


def test_listar_no_modifica_ninguna_orden(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        ordenes = [crear(cliente), definida(cliente)]
        antes = {orden_id: archivo(tmp_path, orden_id) for orden_id in ordenes}

        for _ in range(3):
            assert len(ok(cliente.get("/api/orders"))) == 2

        assert {
            orden_id: archivo(tmp_path, orden_id) for orden_id in ordenes
        } == antes


def test_el_listado_sigue_ordenado_del_mas_reciente_al_mas_antiguo(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        primera, segunda, tercera = (crear(cliente) for _ in range(3))

        ids = [fila["id"] for fila in ok(cliente.get("/api/orders"))]

        assert ids == [tercera, segunda, primera]
