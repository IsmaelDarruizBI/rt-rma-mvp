"""E4: ninguna escritura sobre una Orden pisa en silencio a otra.

Decision tecnica (auditoria funcional MVP v2, E4): JSON sigue siendo el
almacenamiento de las pruebas funcionales. Dentro de un unico proceso del
backend:

- las operaciones que modifican una Orden se serializan (lectura,
  validacion y escritura dentro de la misma seccion critica);
- el repositorio rechaza guardar una version obsoleta: el historial
  persistido tiene que ser un prefijo del que se guarda (es append-only);
- una colision transitoria de archivos (Windows) no termina en 500;
- un fallo de escritura no deja la Orden y el stock desalineados.

Antes de la correccion, 20 altas de Detalle simultaneas respondian 18 OK
y 2 errores 500, y solo quedaban 12 Detalles guardados.

    HTTP -> router -> application -> services -> repositories -> JSON
"""

import json
import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.repositories import PersistenciaError, RepositoryError
from app.services import registrar_accion_funcional, registrar_paso
from app.storage import JsonCatalogosRepository, JsonOrdenReparacionRepository
from app.storage.json import base as almacenamiento
from tests.fixtures import flujo_mvp
from tests.fixtures.api_definicion import definir_y_finalizar
from tests.fixtures.catalogos_mvp import t
from tests.test_api_hp_rep_002 import (
    COORDINADOR,
    ESTACION,
    INSUMO,
    RECEPCION,
    TECNICO,
    TIPO,
    _sembrar_catalogos,
)


@pytest.fixture
def cliente(tmp_path):
    _sembrar_catalogos(tmp_path, stock="2")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def _crear(cliente: TestClient) -> str:
    respuesta = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "Cliente", "telefono": "341-1"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "No carga.",
            },
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _en_paralelo(cantidad: int, tarea) -> list:
    """Corre ``tarea(i)`` en ``cantidad`` hilos que largan juntos."""
    largada = threading.Barrier(cantidad)
    resultados: list = [None] * cantidad

    def correr(indice: int) -> None:
        largada.wait()
        resultados[indice] = tarea(indice)

    hilos = [
        threading.Thread(target=correr, args=(i,)) for i in range(cantidad)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=60)
    return resultados


def _archivo(tmp_path, orden_id: str) -> bytes:
    return (tmp_path / "ordenes" / f"{orden_id}.json").read_bytes()


# --- Serializacion por HTTP --------------------------------------------------


def test_altas_concurrentes_de_detalles_no_se_pierden(cliente):
    orden_id = _crear(cliente)

    estados = _en_paralelo(
        12,
        lambda _: (
            cliente.post(
                f"/api/orders/{orden_id}/details",
                json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
            ).status_code
        ),
    )

    assert estados == [200] * 12
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    ids = [d["id"] for d in orden["reparaciones_detail"]]
    assert ids == [f"DET-{n:03d}" for n in range(1, 13)]
    assert Decimal(orden["resumen"]["total"]) == Decimal("80000") * 12


def test_pagos_concurrentes_no_se_pierden(cliente):
    orden_id = _crear(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )

    estados = _en_paralelo(
        10,
        lambda i: (
            cliente.post(
                f"/api/orders/{orden_id}/payments",
                json={
                    "usuario_id": RECEPCION,
                    "monto": str(i + 1),
                    "metodo": "EFECTIVO",
                },
            ).status_code
        ),
    )

    assert estados == [200] * 10
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    assert len(orden["pagos"]) == 10
    assert Decimal(orden["resumen"]["pagado"]) == Decimal(sum(range(1, 11)))


def test_lecturas_simultaneas_con_escrituras(cliente):
    orden_id = _crear(cliente)
    cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    errores: list = []

    def escribir() -> None:
        for _ in range(15):
            respuesta = cliente.post(
                f"/api/orders/{orden_id}/payments",
                json={
                    "usuario_id": RECEPCION,
                    "monto": "1",
                    "metodo": "EFECTIVO",
                },
            )
            if respuesta.status_code != 200:
                errores.append(("POST", respuesta.status_code))

    def leer() -> None:
        for _ in range(25):
            for ruta in (f"/api/orders/{orden_id}", "/api/orders"):
                respuesta = cliente.get(ruta)
                if respuesta.status_code != 200:
                    errores.append(("GET", respuesta.status_code))

    hilos = [threading.Thread(target=escribir)] + [
        threading.Thread(target=leer) for _ in range(3)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=60)

    assert errores == []
    assert len(cliente.get(f"/api/orders/{orden_id}").json()["pagos"]) == 15


# --- Version obsoleta (repositorio) ------------------------------------------


def test_dos_modificaciones_sobre_la_misma_orden_no_se_pisan(tmp_path):
    repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    repo.guardar(flujo_mvp.orden_con_detalle())

    # Dos operaciones leen la MISMA version...
    primera = repo.obtener("OR-001")
    segunda = repo.obtener("OR-001")
    primera = registrar_accion_funcional(
        primera, accion_id="ACC-REP-020", accion="PRIMERA", fecha=t(500)
    )
    segunda = registrar_paso(
        segunda, process_id="PROC-REP-080", accion="SEGUNDA", fecha=t(501)
    )

    # ...la primera guarda; la segunda ya es obsoleta y se rechaza.
    repo.guardar(primera)
    archivo = (repo.directorio / "OR-001.json").read_bytes()
    with pytest.raises(RepositoryError) as error:
        repo.guardar(segunda)

    assert type(error.value).__name__ == "ConflictoDeEscrituraError"
    assert "OR-001" in str(error.value)
    assert (repo.directorio / "OR-001.json").read_bytes() == archivo
    assert repo.obtener("OR-001") == primera


def test_guardar_otra_vez_la_misma_orden_no_es_un_conflicto(tmp_path):
    repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    orden = flujo_mvp.orden_con_detalle()

    repo.guardar(orden)
    repo.guardar(orden)
    avanzada = registrar_paso(
        repo.obtener(orden.id),
        process_id="PROC-REP-080",
        accion="AVANZAR",
        fecha=t(500),
    )
    repo.guardar(avanzada)

    assert repo.obtener(orden.id) == avanzada


# --- Archivos ----------------------------------------------------------------


def test_una_colision_transitoria_de_archivos_se_reintenta(
    tmp_path, monkeypatch
):
    """Windows: ``os.replace`` falla si otro hilo tiene el archivo abierto."""
    repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    reemplazar = almacenamiento.os.replace
    fallos = {"pendientes": 2}

    def reemplazo_ocupado(origen, destino):
        if fallos["pendientes"]:
            fallos["pendientes"] -= 1
            raise PermissionError(5, "Acceso denegado")
        return reemplazar(origen, destino)

    monkeypatch.setattr(almacenamiento.os, "replace", reemplazo_ocupado)

    repo.guardar(flujo_mvp.orden_creada())

    assert fallos["pendientes"] == 0
    assert repo.obtener("OR-001") == flujo_mvp.orden_creada()
    assert not list(repo.directorio.glob(".*.tmp"))


def test_un_fallo_de_escritura_no_corrompe_ni_deja_temporales(
    tmp_path, monkeypatch
):
    repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    repo.guardar(flujo_mvp.orden_creada())
    archivo = (repo.directorio / "OR-001.json").read_bytes()

    def disco_lleno(origen, destino):
        raise OSError(28, "No queda espacio en el disco")

    monkeypatch.setattr(almacenamiento.os, "replace", disco_lleno)

    with pytest.raises(PersistenciaError):
        repo.guardar(flujo_mvp.orden_con_detalle())

    assert (repo.directorio / "OR-001.json").read_bytes() == archivo
    assert sorted(p.name for p in repo.directorio.iterdir()) == ["OR-001.json"]


def test_una_orden_en_formato_json_anterior_se_sigue_modificando(
    cliente, tmp_path
):
    """Historial con ``process_id`` y sin campos nuevos: carga y se guarda."""
    orden_id = _crear(cliente)
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    for paso in datos["historial"]:
        paso["process_id"] = paso.pop("referencia_id")
        paso.pop("tipo_referencia")
    for campo in ("orden_origen_id", "detalles_origen_ids", "referencia_rt"):
        datos.pop(campo)
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    respuesta = cliente.post(
        f"/api/orders/{orden_id}/details",
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )

    assert respuesta.status_code == 200, respuesta.text
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    assert [p["referencia_id"] for p in orden["historial"]] == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
    ]


# --- PROC-REP-210: la Orden y el stock no quedan desalineados ----------------


def _con_ejecucion(cliente) -> tuple[str, str]:
    orden_id = _crear(cliente)
    respuesta = definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
    )
    assert respuesta.status_code == 200, respuesta.text
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": TECNICO, "estacion_id": ESTACION},
    )
    iniciada = cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/start",
        json={"usuario_id": TECNICO},
    )
    assert iniciada.status_code == 200, iniciada.text
    return orden_id, iniciada.json()["ejecuciones"][0]["id"]


def _completar(cliente, orden_id, ejecucion_id):
    return cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={
            "usuario_id": TECNICO,
            "insumos_utilizados": [{"insumo_id": INSUMO, "cantidad": "1"}],
        },
    )


def _stock(tmp_path) -> Decimal:
    return (
        JsonCatalogosRepository(tmp_path / "catalogs")
        .obtener_insumo(INSUMO)
        .stock_fisico
    )


def test_si_falla_el_stock_la_orden_no_queda_con_el_consumo(
    cliente, tmp_path, monkeypatch
):
    orden_id, ejecucion_id = _con_ejecucion(cliente)
    archivo = _archivo(tmp_path, orden_id)

    def stock_inaccesible(self, insumo_id, nuevo_stock):
        raise PersistenciaError("insumos.json bloqueado")

    with monkeypatch.context() as parche:
        parche.setattr(
            JsonCatalogosRepository,
            "actualizar_stock_insumo",
            stock_inaccesible,
        )
        respuesta = _completar(cliente, orden_id, ejecucion_id)

    assert respuesta.status_code == 500
    # Nada a medias: la Ejecucion sigue abierta y el stock intacto...
    assert _archivo(tmp_path, orden_id) == archivo
    assert _stock(tmp_path) == Decimal("2")
    # ...asi que el tecnico puede reintentar.
    respuesta = _completar(cliente, orden_id, ejecucion_id)
    assert respuesta.status_code == 200, respuesta.text
    assert _stock(tmp_path) == Decimal("1")


def test_si_falla_guardar_la_orden_el_stock_se_restaura(
    cliente, tmp_path, monkeypatch
):
    orden_id, ejecucion_id = _con_ejecucion(cliente)
    archivo = _archivo(tmp_path, orden_id)

    def orden_inaccesible(self, orden):
        raise PersistenciaError("OR bloqueada")

    with monkeypatch.context() as parche:
        parche.setattr(
            JsonOrdenReparacionRepository, "guardar", orden_inaccesible
        )
        respuesta = _completar(cliente, orden_id, ejecucion_id)

    assert respuesta.status_code == 500
    assert _archivo(tmp_path, orden_id) == archivo
    assert _stock(tmp_path) == Decimal("2")
    respuesta = _completar(cliente, orden_id, ejecucion_id)
    assert respuesta.status_code == 200, respuesta.text
    assert _stock(tmp_path) == Decimal("1")
