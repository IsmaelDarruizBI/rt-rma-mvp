"""HP-REP-001 recorrido de punta a punta por HTTP.

Complementa los E2E existentes -el de services en memoria y el
persistido-. Aqui cada paso entra por la API real:

    HTTP -> router -> application -> services -> repositories -> JSON

La app se levanta con ``Settings(data_dir=tmp_path)``, asi que los
catalogos DEMO versionados de ``app/backend/data`` nunca se tocan.
"""

import threading
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


def _cliente(tmp_path, stock: str = "2") -> TestClient:
    _sembrar_catalogos(tmp_path, stock)
    return TestClient(create_app(Settings(data_dir=tmp_path)))


@pytest.fixture
def cliente(tmp_path):
    with _cliente(tmp_path) as test_client:
        yield test_client


def _crear_orden(cliente: TestClient) -> str:
    respuesta = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {
                "nombre": "Cliente de Prueba",
                "telefono": "341-0000000",
                "email": "cliente.prueba@example.com",
            },
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "La bateria dura poco.",
            },
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _hasta_ejecucion_iniciada(cliente: TestClient) -> tuple[str, str, str]:
    """Lleva una Orden hasta tener una Ejecucion en curso."""
    orden_id = _crear_orden(cliente)

    cuerpo = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    ).json()
    detalle_id = cuerpo["reparaciones_detail"][0]["id"]

    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    )
    cuerpo = cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": TECNICO},
    ).json()
    ejecucion_id = cuerpo["ejecuciones"][0]["id"]

    return orden_id, detalle_id, ejecucion_id


# --- Lectura -----------------------------------------------------------


def test_los_catalogos_se_leen_por_http(cliente):
    tipos = cliente.get("/api/catalogs/repair-types").json()
    estaciones = cliente.get("/api/catalogs/stations").json()
    usuarios = cliente.get("/api/catalogs/users").json()

    assert [t["id"] for t in tipos] == [TIPO]
    assert [e["id"] for e in estaciones] == [ESTACION]
    assert {u["id"] for u in usuarios} == {
        RECEPCION,
        COORDINADOR,
        TECNICO,
        ADMINISTRADOR,
    }


def test_el_listado_arranca_vacio(cliente):
    assert cliente.get("/api/orders").json() == []


# --- Happy Path completo por HTTP --------------------------------------


def test_hp_rep_001_end_to_end_por_http(cliente):
    """Recorre HP-REP-001 entero usando solo la API."""

    # PROC-REP-010 -> 030 -> 040
    orden_id = _crear_orden(cliente)
    orden = cliente.get(f"/api/orders/{orden_id}").json()

    assert orden["estado_workflow"] == "REQUERIMIENTO"
    assert orden["reparaciones_detail"] == []
    assert orden["resumen"]["total"] == "0"
    assert orden["resumen"]["estado_pago"] == "PENDIENTE"

    # PROC-REP-045 -> 070 -> 050 -> 060 -> 080 -> 090 -> 140
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    assert respuesta.status_code == 200, respuesta.text
    orden = respuesta.json()
    detalle_id = orden["reparaciones_detail"][0]["id"]

    assert orden["estado_workflow"] == "HABILITADA"
    assert orden["resumen"]["total"] == "80000"
    assert orden["documentos"]["comprobante_recepcion"]["generado"] is True
    # La factibilidad consulta, no reserva.
    assert cliente.get("/api/catalogs/repair-types").status_code == 200

    # PROC-REP-150 -> 170
    orden = cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    ).json()
    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["prioridad"] == 1

    # PROC-REP-172 -> 180
    orden = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    ).json()
    assert len(orden["tomas"]) == 1
    assert orden["tomas"][0]["estado"] == "ACTIVA"

    # PROC-REP-181 -> 174 -> 185 (reserva real)
    orden = cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": TECNICO},
    ).json()
    ejecucion_id = orden["ejecuciones"][0]["id"]

    assert orden["estado_workflow"] == "EN_REPARACION"
    assert orden["ejecuciones"][0]["estado"] == "EN_PROGRESO"
    assert orden["reparaciones_detail"][0]["estado"] == "EN_PROGRESO"

    # PROC-REP-190 -> 200 -> 210 -> 211
    orden = cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={
            "usuario_id": TECNICO,
            "insumos_utilizados": [{"insumo_id": INSUMO, "cantidad": "1"}],
            "observaciones": "Bateria reemplazada sin novedades.",
        },
    ).json()

    assert orden["ejecuciones"][0]["estado"] == "COMPLETADO"
    assert orden["reparaciones_detail"][0]["estado"] == "COMPLETO"
    assert orden["tomas"][0]["estado"] == "CERRADA"

    # PROC-REP-220 -> 230 -> 245 -> 240
    orden = cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={
            "usuario_id": RECEPCION,
            "observaciones": "Equipo enciende y carga correctamente.",
        },
    ).json()

    assert orden["estado_workflow"] == "REPARACION_LISTA"
    assert orden["reparaciones_detail"][0]["control_estado"] == "APROBADO"
    assert orden["resumen"]["puntaje_total"] == 10

    # PROC-REP-250 -> 260 -> 265 (No) -> 266
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    ).json()

    assert respuesta["puede_entregar"] is False
    assert respuesta["resumen"]["saldo"] == "80000"

    # Registrar Pago (transversal) -> revalida PROC-REP-265 (Si)
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": ADMINISTRADOR,
            "monto": "80000",
            "metodo": "EFECTIVO",
        },
    ).json()

    assert respuesta["puede_entregar"] is True
    assert respuesta["resumen"]["saldo"] == "0"
    assert respuesta["resumen"]["estado_pago"] == "PAGADO"

    # PROC-REP-280 -> 270 -> EVT-REP-999
    orden = cliente.post(
        f"/api/orders/{orden_id}/deliver",
        json={"usuario_id": ADMINISTRADOR},
    ).json()

    # --- expected de HP-REP-001 ---
    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["current_process"] == "EVT-REP-999"
    assert all(e["estado"] == "COMPLETADO" for e in orden["ejecuciones"])
    assert all(t["estado"] == "CERRADA" for t in orden["tomas"])
    assert orden["resumen"]["saldo"] == "0"
    assert orden["documentos"]["comprobante_final"]["generado"] is True
    assert orden["documentos"]["garantia_reparacion"]["generado"] is True

    # Persistido y releible.
    recargada = cliente.get(f"/api/orders/{orden_id}").json()
    assert recargada["estado_workflow"] == "ENTREGADA"
    assert recargada["current_process"] == "EVT-REP-999"
    assert len(cliente.get("/api/orders").json()) == 1


def test_el_historial_llega_al_frontend(cliente):
    """La UI muestra el recorrido con los IDs funcionales reales."""
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )

    historial = cliente.get(f"/api/orders/{orden_id}").json()["historial"]
    recorridos = [paso["process_id"] for paso in historial]

    for process_id in (
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-070",
        "PROC-REP-060",
        "PROC-REP-140",
    ):
        assert process_id in recorridos

    creacion = next(p for p in historial if p["process_id"] == "PROC-REP-040")
    assert creacion["usuario_id"] == RECEPCION
    # Los nodos ACT-SYSTEM no llevan actor humano.
    comprobante = next(
        p for p in historial if p["process_id"] == "PROC-REP-060"
    )
    assert comprobante["usuario_id"] is None


def test_la_api_expone_las_acciones_disponibles(cliente):
    """El frontend no adivina el estado: la API le dice que se puede."""
    orden_id = _crear_orden(cliente)

    orden = cliente.get(f"/api/orders/{orden_id}").json()
    codigos = [a["codigo"] for a in orden["acciones_disponibles"]]

    assert codigos, "una Orden en REQUERIMIENTO debe ofrecer una accion"
    assert all(
        a["roles"] == ["RECEPCION"]
        for a in orden["acciones_disponibles"]
        if a["roles"]
    )


# --- Errores -----------------------------------------------------------


def test_orden_inexistente_devuelve_404(cliente):
    respuesta = cliente.get("/api/orders/OR-INEXISTENTE")

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["codigo"] == "NO_ENCONTRADO"


def test_comando_sobre_orden_inexistente_devuelve_404(cliente):
    respuesta = cliente.post(
        "/api/orders/OR-INEXISTENTE/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )

    assert respuesta.status_code == 404


@pytest.mark.parametrize(
    ("usuario_id", "descripcion"),
    [
        (TECNICO, "un tecnico no crea Ordenes"),
        (ADMINISTRADOR, "un administrador tampoco"),
    ],
)
def test_rol_incorrecto_devuelve_409(cliente, usuario_id, descripcion):
    respuesta = cliente.post(
        "/api/orders",
        json={
            "usuario_id": usuario_id,
            "cliente": {"nombre": "X", "telefono": "1"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "No carga.",
            },
        },
    )

    assert respuesta.status_code == 409, descripcion
    assert respuesta.json()["error"]["codigo"] == "PRECONDICION_INVALIDA"


def test_rol_incorrecto_al_tomar_la_orden_devuelve_409(cliente):
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": RECEPCION, "estacion_id": ESTACION},
    )

    assert respuesta.status_code == 409


def test_request_mal_formado_devuelve_422(cliente):
    respuesta = cliente.post(
        "/api/orders", json={"usuario_id": RECEPCION, "cliente": {}}
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["codigo"] == "REQUEST_INVALIDO"


def test_entregar_con_saldo_pendiente_devuelve_409(cliente):
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
        json={"usuario_id": RECEPCION},
    )

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/deliver",
        json={"usuario_id": ADMINISTRADOR},
    )

    assert respuesta.status_code == 409


# --- Stock ------------------------------------------------------------


def _hasta_tomada(cliente: TestClient) -> tuple[str, str]:
    """Orden lista para que un tecnico inicie un Detalle."""
    orden_id = _crear_orden(cliente)
    cuerpo = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    assert cuerpo.status_code == 200, cuerpo.text
    detalle_id = cuerpo.json()["reparaciones_detail"][0]["id"]

    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    )
    return orden_id, detalle_id


def test_la_factibilidad_bloquea_cuando_el_stock_ya_esta_reservado(tmp_path):
    """La factibilidad usa el stock GLOBAL: la reserva ajena cuenta.

    EXC-REP-001: ningun Detalle trabajable ya no es un error. La Orden se
    persiste detenida en PROC-REP-100 con el Detalle BLOQUEADO_POR_RECURSOS
    (antes respondia 409 y no guardaba nada).
    """
    with _cliente(tmp_path, stock="1") as cliente:
        _hasta_ejecucion_iniciada(cliente)

        segunda = _crear_orden(cliente)
        respuesta = cliente.post(
            f"/api/orders/{segunda}/details",
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
        )

        assert respuesta.status_code == 200, respuesta.text
        orden = respuesta.json()
        assert orden["current_process"] == "PROC-REP-100"
        assert orden["estado_workflow"] == "REQUERIMIENTO"
        assert orden["reparaciones_detail"][0]["condicion"] == (
            "BLOQUEADO_POR_RECURSOS"
        )
        assert "PROC-REP-140" not in [
            p["referencia_id"] for p in orden["historial"]
        ]


def test_stock_insuficiente_al_iniciar_devuelve_409(tmp_path):
    """Dos Ordenes tomadas, una sola unidad: la segunda falla en 185.

    Ambas pasan la factibilidad (PROC-REP-080 solo consulta y todavia no
    hay nada reservado). Recien al intentar la RESERVA REAL la segunda
    se queda sin stock.
    """
    with _cliente(tmp_path, stock="1") as cliente:
        primera, detalle_primera = _hasta_tomada(cliente)
        segunda, detalle_segunda = _hasta_tomada(cliente)

        ganadora = cliente.post(
            f"/api/orders/{primera}/details/{detalle_primera}/start",
            json={"usuario_id": TECNICO},
        )
        assert ganadora.status_code == 200, ganadora.text

        respuesta = cliente.post(
            f"/api/orders/{segunda}/details/{detalle_segunda}/start",
            json={"usuario_id": TECNICO},
        )

        assert respuesta.status_code == 409
        assert respuesta.json()["error"]["codigo"] == "RECURSO_NO_DISPONIBLE"

        # La segunda no genero reserva parcial ni Ejecucion.
        sin_reservar = cliente.get(f"/api/orders/{segunda}").json()
        assert sin_reservar["ejecuciones"] == []
        assert sin_reservar["estado_workflow"] == "EN_COLA"


def test_dos_reservas_concurrentes_solo_una_gana(tmp_path):
    """Dos tecnicos van por la ultima unidad al mismo tiempo.

    El lock de inventario serializa la seccion critica de PROC-REP-185,
    asi que una reserva y la otra recibe 409. Sin el lock las dos podrian
    leer el mismo stock disponible y reservarlo.
    """
    with _cliente(tmp_path, stock="1") as cliente:
        ordenes = [_hasta_tomada(cliente) for _ in range(2)]

        largada = threading.Barrier(len(ordenes))
        resultados: list[int] = []
        candado = threading.Lock()

        def reservar(orden_id: str, detalle_id: str) -> None:
            largada.wait()
            respuesta = cliente.post(
                f"/api/orders/{orden_id}/details/{detalle_id}/start",
                json={"usuario_id": TECNICO},
            )
            with candado:
                resultados.append(respuesta.status_code)

        hilos = [
            threading.Thread(target=reservar, args=(orden_id, detalle_id))
            for orden_id, detalle_id in ordenes
        ]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=30)

        assert sorted(resultados) == [200, 409], resultados

        # Exactamente una Orden quedo con Ejecucion abierta.
        con_ejecucion = [
            orden_id
            for orden_id, _ in ordenes
            if cliente.get(f"/api/orders/{orden_id}").json()["ejecuciones"]
        ]
        assert len(con_ejecucion) == 1


def test_los_catalogos_demo_versionados_no_se_tocan(cliente, tmp_path):
    """El test corre contra tmp_path, nunca contra app/backend/data."""
    from pathlib import Path

    versionados = Path(__file__).parent.parent / "data" / "catalogs"
    antes = {p.name: p.read_bytes() for p in versionados.glob("*.json")}

    _crear_orden(cliente)

    despues = {p.name: p.read_bytes() for p in versionados.glob("*.json")}
    assert despues == antes
    assert not list(
        (Path(__file__).parent.parent / "data" / "ordenes").glob("*.json")
    )


# --- Insumos previstos del Detalle -------------------------------------


def test_el_detalle_expone_sus_insumos_previstos(cliente):
    """La UI recibe qué insumos confirmar, sin conocer IDs de catálogo."""
    orden_id = _crear_orden(cliente)
    orden = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    ).json()

    previstos = orden["reparaciones_detail"][0]["insumos_previstos"]

    assert len(previstos) == 1
    assert previstos[0] == {
        "insumo_id": INSUMO,
        "codigo": "BAT-IP14",
        "nombre": "Bateria iPhone 14",
        "cantidad_prevista": "1",
    }


def test_los_insumos_previstos_viajan_en_cada_lectura(cliente):
    """Están en el GET, no solo en la respuesta del comando."""
    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )

    orden = cliente.get(f"/api/orders/{orden_id}").json()
    previstos = orden["reparaciones_detail"][0]["insumos_previstos"]

    assert [p["insumo_id"] for p in previstos] == [INSUMO]
    assert previstos[0]["cantidad_prevista"] == "1"


def test_un_tipo_sin_insumos_previstos_devuelve_lista_vacia(tmp_path):
    """Un Tipo sin relación en TipoReparacionInsumos da []."""
    _sembrar_catalogos(tmp_path)
    # Se deja el catálogo de relaciones vacío.
    escribir_json_atomico(
        tmp_path / "catalogs" / "tipo_reparacion_insumos.json", []
    )

    with TestClient(create_app(Settings(data_dir=tmp_path))) as cliente:
        orden_id = _crear_orden(cliente)
        orden = cliente.post(
            f"/api/orders/{orden_id}/details",
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
        ).json()

        assert orden["reparaciones_detail"][0]["insumos_previstos"] == []


def test_los_insumos_previstos_no_se_persisten_en_la_orden(cliente, tmp_path):
    """Son de presentación: el JSON del aggregate no los guarda."""
    import json

    orden_id = _crear_orden(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )

    archivo = tmp_path / "ordenes" / f"{orden_id}.json"
    crudo = json.loads(archivo.read_text(encoding="utf-8"))

    assert "insumos_previstos" not in crudo["reparaciones_detail"][0]


def test_completar_con_los_insumos_previstos_recibidos(cliente):
    """El técnico confirma lo que la API le propuso (PROC-REP-200)."""
    orden_id, _, ejecucion_id = _hasta_ejecucion_iniciada(cliente)
    orden = cliente.get(f"/api/orders/{orden_id}").json()

    previstos = orden["reparaciones_detail"][0]["insumos_previstos"]
    utilizados = [
        {
            "insumo_id": previsto["insumo_id"],
            "cantidad": previsto["cantidad_prevista"],
        }
        for previsto in previstos
    ]

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={"usuario_id": TECNICO, "insumos_utilizados": utilizados},
    )

    assert respuesta.status_code == 200
    ejecucion = respuesta.json()["ejecuciones"][0]
    assert ejecucion["insumos_utilizados"] == [
        {"insumo_id": INSUMO, "cantidad": "1"}
    ]


# --- Catálogo inconsistente --------------------------------------------


def _catalogos_con_insumo_colgado(directorio) -> None:
    """TR-001 prevé INS-999, que no existe en el catálogo de Insumo."""
    _sembrar_catalogos(directorio)
    escribir_json_atomico(
        directorio / "catalogs" / "tipo_reparacion_insumos.json",
        [
            TipoReparacionInsumos(
                tipo_reparacion_id=TIPO,
                insumo_id="INS-999",
                cantidad=Decimal("1"),
            ).model_dump(mode="json")
        ],
    )


def test_una_relacion_a_insumo_inexistente_falla_explicitamente(tmp_path):
    """Un catálogo roto no puede pasar por una lista vacía."""
    from app.application import (
        construir_contexto,
        insumos_previstos_por_detalle,
        obtener_orden,
    )
    from app.repositories import PersistenciaError

    _sembrar_catalogos(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as cliente:
        orden_id = _crear_orden(cliente)
        cliente.post(
            f"/api/orders/{orden_id}/details",
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
        )

    # Recién ahora se rompe el catálogo: la Orden ya tiene su Detalle.
    _catalogos_con_insumo_colgado(tmp_path)

    contexto = construir_contexto(Settings(data_dir=tmp_path))
    orden = obtener_orden(contexto, orden_id)

    with pytest.raises(PersistenciaError) as error:
        insumos_previstos_por_detalle(contexto, orden)

    assert "INS-999" in str(error.value)


def test_un_tipo_sin_relaciones_no_es_un_catalogo_roto(tmp_path):
    """Sin relaciones es válido; con una relación colgada, no."""
    from app.application import (
        construir_contexto,
        insumos_previstos_por_detalle,
        obtener_orden,
    )

    _sembrar_catalogos(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as cliente:
        orden_id = _crear_orden(cliente)
        cliente.post(
            f"/api/orders/{orden_id}/details",
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
        )

    escribir_json_atomico(
        tmp_path / "catalogs" / "tipo_reparacion_insumos.json", []
    )

    contexto = construir_contexto(Settings(data_dir=tmp_path))
    orden = obtener_orden(contexto, orden_id)
    previstos = insumos_previstos_por_detalle(contexto, orden)

    assert previstos == {orden.reparaciones_detail[0].id: []}


def test_el_catalogo_roto_responde_500_sin_filtrar_detalle(tmp_path):
    """La API devuelve el error genérico, nunca el ID ni el catálogo."""
    _sembrar_catalogos(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as cliente:
        orden_id = _crear_orden(cliente)
        cliente.post(
            f"/api/orders/{orden_id}/details",
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
        )

    _catalogos_con_insumo_colgado(tmp_path)

    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        raise_server_exceptions=False,
    ) as cliente:
        respuesta = cliente.get(f"/api/orders/{orden_id}")

    assert respuesta.status_code == 500
    assert respuesta.json() == {
        "error": {
            "codigo": "PERSISTENCIA_ERROR",
            "mensaje": "Ocurrió un error interno al procesar los datos.",
        }
    }

    # Nada del catálogo roto viaja al cliente.
    cuerpo = respuesta.text
    for filtrado in ("INS-999", "TipoReparacionInsumos", str(tmp_path)):
        assert filtrado not in cuerpo
