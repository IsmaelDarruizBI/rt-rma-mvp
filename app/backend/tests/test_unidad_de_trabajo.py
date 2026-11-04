"""Unidad de trabajo (E1): contrato JSON, limites y servicios externos.

Con JSON, ``contexto.transaccion()`` es la seccion critica de siempre:
exclusion mutua reentrante, sin atomicidad. Estas pruebas fijan que el
reemplazo de ``seccion_critica_*`` no cambio el comportamiento y que
ningun servicio externo (fotos, fuente por DNI, origen del catalogo) se
llama con una transaccion abierta. La implementacion PostgreSQL se
prueba en ``tests/postgres``.
"""

import ast
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errores import registrar_manejadores_de_error
from app.application import (
    LOCK_INVENTARIO,
    UNIDAD_DE_TRABAJO_JSON,
    ApplicationContext,
    UnidadDeTrabajoJson,
    construir_contexto,
)
from app.core.config import Settings
from app.integraciones import EstadoFuente, PersonaExterna, ResultadoFuente
from app.integraciones.catalogo import construir_proveedor_catalogo
from app.main import create_app
from app.repositories import (
    ConflictoDeEscrituraError,
    PersistenciaError,
    PersistenciaNoDisponibleError,
    TransaccionInvalidadaError,
)
from app.storage import AlmacenFotosMemoria
from app.storage.postgres import (
    AjustesPostgres,
    ConfiguracionPersistenciaError,
    ajustes_postgres,
)
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    RECEPCION,
    ok,
    sembrar,
)
from tests.fixtures.catalogo_ventas import escribir_csv
from tests.fixtures.ingreso_inicial import ingresada
from tests.test_fotos_orden import JPEG, _subir

APLICACION = Path(__file__).resolve().parents[1] / "app"
URL_REMOTA = "postgresql://rma_api:x@pooler.ejemplo.invalid:6543/postgres"


# --- Contrato JSON ----------------------------------------------------------


def test_el_contexto_usa_la_seccion_critica_json_por_defecto(tmp_path):
    construido = construir_contexto(
        Settings(_env_file=None, data_dir=tmp_path)
    )
    armado = ApplicationContext(
        ordenes=construido.ordenes, catalogos=construido.catalogos
    )
    # Una sola seccion critica para todos los contextos, como antes de E1.
    assert construido.unidad_de_trabajo is UNIDAD_DE_TRABAJO_JSON
    assert armado.unidad_de_trabajo is UNIDAD_DE_TRABAJO_JSON
    assert UNIDAD_DE_TRABAJO_JSON._lock is LOCK_INVENTARIO


def test_la_transaccion_json_es_reentrante_y_sabe_si_esta_en_curso():
    unidad = UnidadDeTrabajoJson(threading.RLock())
    assert not unidad.en_curso()
    with unidad.transaccion():
        assert unidad.en_curso()
        with unidad.transaccion():
            assert unidad.en_curso()
        assert unidad.en_curso()
    assert not unidad.en_curso()


def test_una_excepcion_cierra_la_transaccion_json_y_libera_el_lock():
    lock = threading.RLock()
    unidad = UnidadDeTrabajoJson(lock)
    with pytest.raises(RuntimeError):
        with unidad.transaccion():
            with unidad.transaccion():
                raise RuntimeError("falla")
    assert not unidad.en_curso()
    liberado = []
    hilo = threading.Thread(
        target=lambda: liberado.append(lock.acquire(timeout=1))
    )
    hilo.start()
    hilo.join()
    assert liberado == [True]


def test_la_transaccion_json_serializa_a_otro_hilo():
    unidad = UnidadDeTrabajoJson(threading.RLock())
    adentro = threading.Event()
    soltar = threading.Event()
    orden = []

    def primero():
        with unidad.transaccion():
            adentro.set()
            soltar.wait(5)
            orden.append("primero")

    def segundo():
        adentro.wait(5)
        with unidad.transaccion():
            # El otro hilo la tiene: este no la ve como propia.
            orden.append("segundo")

    hilos = [
        threading.Thread(target=primero),
        threading.Thread(target=segundo),
    ]
    for hilo in hilos:
        hilo.start()
    adentro.wait(5)
    assert not unidad.en_curso()
    soltar.set()
    for hilo in hilos:
        hilo.join(5)
    assert orden == ["primero", "segundo"]


def test_la_transaccion_json_no_es_atomica():
    """Exclusion mutua no es rollback: lo escrito antes del fallo queda."""
    unidad = UnidadDeTrabajoJson(threading.RLock())
    escrito = []
    with pytest.raises(RuntimeError):
        with unidad.transaccion():
            escrito.append("stock")
            raise RuntimeError("falla al guardar la Orden")
    assert escrito == ["stock"]


# --- Reemplazo de seccion_critica_* -----------------------------------------


def test_no_quedan_secciones_criticas_sueltas():
    sueltas = [
        f"{archivo.relative_to(APLICACION)}:{numero}"
        for archivo in APLICACION.rglob("*.py")
        for numero, linea in enumerate(
            archivo.read_text(encoding="utf-8").splitlines(), 1
        )
        if "seccion_critica" in linea
    ]
    assert sueltas == []


def _abre_transaccion(item: ast.withitem) -> bool:
    llamada = item.context_expr
    if not isinstance(llamada, ast.Call):
        return False
    funcion = llamada.func
    nombre = getattr(funcion, "attr", None) or getattr(funcion, "id", None)
    return nombre in {"transaccion", "orden_para_modificar"}


# Los puertos externos del contexto y los nombres con que los usan los
# casos de uso.
ATRIBUTOS_EXTERNOS = {"fotos", "fuente_personas", "proveedor_catalogo"}
NOMBRES_EXTERNOS = {"almacen", "_almacen", "fuente", "proveedor"}


def test_ningun_bloque_transaccional_nombra_un_servicio_externo():
    encontrados = []
    for archivo in sorted((APLICACION / "application").glob("*.py")):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.With) or not any(
                _abre_transaccion(item) for item in nodo.items
            ):
                continue
            for sub in (s for cuerpo in nodo.body for s in ast.walk(cuerpo)):
                if (
                    isinstance(sub, ast.Attribute)
                    and sub.attr in ATRIBUTOS_EXTERNOS
                ) or (
                    isinstance(sub, ast.Name) and sub.id in NOMBRES_EXTERNOS
                ):
                    encontrados.append(f"{archivo.name}:{sub.lineno}")
    assert encontrados == []


# --- Servicios externos fuera de la transaccion (dinamico) ------------------


class Llamadas:
    """Registra cada llamada externa y si habia una transaccion abierta."""

    def __init__(self):
        self.registro: list[tuple[str, bool]] = []

    def anotar(self, nombre: str) -> None:
        self.registro.append((nombre, UNIDAD_DE_TRABAJO_JSON.en_curso()))

    def nombres(self) -> set[str]:
        return {nombre for nombre, _ in self.registro}

    def dentro_de_una_transaccion(self) -> list[str]:
        return [nombre for nombre, adentro in self.registro if adentro]


class AlmacenVigilado(AlmacenFotosMemoria):
    def __init__(self, llamadas):
        super().__init__()
        self.llamadas = llamadas

    def guardar(self, clave, contenido, tipo):
        self.llamadas.anotar("fotos.guardar")
        super().guardar(clave, contenido, tipo)

    def obtener(self, clave):
        self.llamadas.anotar("fotos.obtener")
        return super().obtener(clave)

    def listar(self, prefijo):
        self.llamadas.anotar("fotos.listar")
        return super().listar(prefijo)

    def eliminar(self, clave):
        self.llamadas.anotar("fotos.eliminar")
        super().eliminar(clave)


class FuenteVigilada:
    nombre = "fuente-vigilada"

    def __init__(self, llamadas):
        self.llamadas = llamadas

    def consultar(self, dni):
        self.llamadas.anotar("fuente.consultar")
        return ResultadoFuente(
            EstadoFuente.ENCONTRADO,
            (PersonaExterna(nombre_apellido="GOMEZ ANA"),),
        )


class ProveedorVigilado:
    def __init__(self, real, llamadas):
        self.real = real
        self.llamadas = llamadas
        self.descripcion = real.descripcion

    def leer(self, filtro):
        self.llamadas.anotar("catalogo.leer")
        return self.real.leer(filtro)


def test_ningun_servicio_externo_se_llama_con_una_transaccion_abierta(
    tmp_path,
):
    sembrar(tmp_path, "10")
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        catalogo_origen="archivo",
        catalogo_archivo=escribir_csv(tmp_path / "tipo_producto.csv"),
    )
    llamadas = Llamadas()
    almacen = AlmacenVigilado(llamadas)
    app = create_app(settings)
    app.state.contexto = replace(
        app.state.contexto,
        fotos=almacen,
        fuente_personas=FuenteVigilada(llamadas),
        proveedor_catalogo=ProveedorVigilado(
            construir_proveedor_catalogo(settings), llamadas
        ),
    )
    huerfana = "ordenes/OR-999999/FOT-HUERFANA.jpg"
    almacen.objetos[huerfana] = (JPEG, "image/jpeg")
    almacen.fechas[huerfana] = datetime.now(timezone.utc) - timedelta(days=2)

    with TestClient(app) as cliente:
        orden_id = ingresada(cliente, BATERIA)
        foto = ok(_subir(cliente, orden_id))["fotos"][0]
        assert (
            cliente.get(
                f"/api/orders/{orden_id}/photos/{foto['id']}"
            ).status_code
            == 200
        )
        limpieza = ok(
            cliente.post(
                "/api/maintenance/photos/cleanup",
                params={"usuario_id": ADMINISTRADOR, "aplicar": True},
            )
        )
        assert limpieza["eliminadas"] == [huerfana]
        busqueda = ok(
            cliente.get(
                "/api/clients/lookup",
                params={"dni": "30123456", "usuario_id": RECEPCION},
            )
        )
        assert busqueda["estado"] == "ENCONTRADO"
        ok(
            cliente.post(
                "/api/catalogs/equipment/sync",
                params={"usuario_id": ADMINISTRADOR},
            )
        )

    assert llamadas.nombres() == {
        "fotos.guardar",
        "fotos.obtener",
        "fotos.listar",
        "fotos.eliminar",
        "fuente.consultar",
        "catalogo.leer",
    }
    assert llamadas.dentro_de_una_transaccion() == []


# --- Errores de persistencia por HTTP ---------------------------------------


@pytest.fixture
def api_de_errores():
    app = FastAPI()
    registrar_manejadores_de_error(app)
    errores = {
        "agotado": PersistenciaNoDisponibleError("sin conexion libre"),
        "conflicto": ConflictoDeEscrituraError("cambio"),
        "invalidada": TransaccionInvalidadaError("se atrapo un fallo"),
        "fallo": PersistenciaError("SQLSTATE 08006"),
    }

    @app.get("/{caso}")
    def lanzar(caso: str):
        raise errores[caso]

    with TestClient(app) as cliente:
        yield cliente


def test_el_pool_agotado_es_503_y_no_un_conflicto(api_de_errores):
    respuesta = api_de_errores.get("/agotado")
    assert respuesta.status_code == 503
    error = respuesta.json()["error"]
    assert error["codigo"] == "PERSISTENCIA_NO_DISPONIBLE"
    assert "no se guardó nada" in error["mensaje"]
    assert "sin conexion libre" not in error["mensaje"]


@pytest.mark.parametrize(
    ("caso", "status", "codigo"),
    [
        ("conflicto", 409, "CONFLICTO_CONCURRENTE"),
        ("invalidada", 500, "PERSISTENCIA_ERROR"),
        ("fallo", 500, "PERSISTENCIA_ERROR"),
    ],
)
def test_los_demas_errores_de_persistencia_no_cambian(
    api_de_errores, caso, status, codigo
):
    respuesta = api_de_errores.get(f"/{caso}")
    assert respuesta.status_code == status
    assert respuesta.json()["error"]["codigo"] == codigo


# --- Ajustes del pool y de las transacciones --------------------------------


def test_los_ajustes_iniciales_son_conservadores():
    ajustes = ajustes_postgres(Settings(_env_file=None))
    assert ajustes == AjustesPostgres(
        pool_min=1,
        pool_max=4,
        pool_espera_s=5.0,
        lock_timeout_ms=5000,
        statement_timeout_ms=15000,
    )


def test_los_ajustes_se_leen_del_entorno(monkeypatch):
    monkeypatch.setenv("RMA_DB_POOL_MAX", "8")
    monkeypatch.setenv("RMA_DB_POOL_ESPERA_S", "2.5")
    monkeypatch.setenv("RMA_DB_LOCK_TIMEOUT_MS", "1000")
    ajustes = ajustes_postgres(Settings(_env_file=None))
    assert ajustes.pool_max == 8
    assert ajustes.pool_espera_s == 2.5
    assert ajustes.lock_timeout_ms == 1000


@pytest.mark.parametrize(
    ("valores", "motivo"),
    [
        ({"db_pool_min": 5, "db_pool_max": 2}, "RMA_DB_POOL_MIN"),
        ({"db_pool_max": 0}, "RMA_DB_POOL_MAX"),
        ({"db_pool_min": -1}, "RMA_DB_POOL_MIN"),
        ({"db_pool_espera_s": 0}, "RMA_DB_POOL_ESPERA_S"),
        ({"db_lock_timeout_ms": 0}, "RMA_DB_LOCK_TIMEOUT_MS"),
        ({"db_statement_timeout_ms": 0}, "RMA_DB_STATEMENT_TIMEOUT_MS"),
    ],
)
def test_un_ajuste_imposible_detiene_el_arranque(tmp_path, valores, motivo):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        persistencia="postgres",
        database_url=URL_REMOTA,
        **valores,
    )
    with pytest.raises(ConfiguracionPersistenciaError, match=motivo):
        create_app(settings)


def test_postgres_valido_sigue_deteniendo_el_arranque(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        persistencia="postgres",
        database_url=URL_REMOTA,
    )
    with pytest.raises(
        ConfiguracionPersistenciaError, match="todavia no esta disponible"
    ):
        create_app(settings)
