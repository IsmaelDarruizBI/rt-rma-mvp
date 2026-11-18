# ruff: noqa: E501  (SQL)
"""Bloque C (C4): la copia del catalogo de Ventas en PostgreSQL.

Con la API real, ``RMA_PERSISTENCIA=postgres`` y el rol minimo de la API
(miembro de ``rma_backend``). Cada prueba usa una base propia, clonada de
una plantilla con todas las migraciones y las cargas de desarrollo (las
filas de la copia no se borran). Diseño: docs/persistencia-catalogos.md,
seccion 6.2.
"""

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("psycopg_pool")

from fastapi.testclient import TestClient  # noqa: E402

from app.application import sincronizar_catalogo_equipos  # noqa: E402
from app.application.sincronizacion_origen import (  # noqa: E402
    MENSAJE_APLICACION,
)
from app.core.config import Settings  # noqa: E402
from app.domain.models import ProductoInformado  # noqa: E402
from app.integraciones.catalogo import (  # noqa: E402
    CatalogoOrigenNoDisponibleError,
    LecturaCatalogo,
)
from app.main import create_app  # noqa: E402
from app.services import SincronizacionEnCursoError  # noqa: E402
from app.storage.postgres.catalogo_equipos import (  # noqa: E402
    PostgresCatalogoEquiposRepository,
)
from tests.fixtures.api_salidas import (  # noqa: E402
    ADMINISTRADOR,
    COORDINADOR,
    RECEPCION,
    conflicto,
    crear,
    ok,
)
from tests.fixtures.catalogo_ventas import (  # noqa: E402
    ID_12_NEGRO,
    ID_12_PRO_MAX_VIOLETA,
    escribir_csv,
    filas_base,
)
from tests.postgres.base_local import (  # noqa: E402
    VARIABLE,
    borrar_base,
    clonar_base,
    crear_base,
    url_admin_local,
)

pytestmark = pytest.mark.postgres

ROL = "rma_api_prueba"
RAIZ_BACKEND = Path(__file__).resolve().parents[2]
IMEI = "356000000000017"  # ficticio


def _como_rol(url: str) -> str:
    partes = urlsplit(url)
    return urlunsplit(
        partes._replace(netloc=f"{ROL}@{partes.hostname}:{partes.port}")
    )


@pytest.fixture(scope="module")
def plantilla():
    url = os.environ.get(VARIABLE)
    if not url:
        pytest.skip(f"{VARIABLE} no esta definida: sin PostgreSQL local.")
    admin = url_admin_local(url)
    base = crear_base(admin)
    with psycopg.connect(base, autocommit=True) as conexion:
        if not conexion.execute(
            "select 1 from pg_roles where rolname = %s", (ROL,)
        ).fetchone():
            conexion.execute(
                f"create role {ROL} login inherit in role rma_backend"
            )
    nombre = urlsplit(base).path.lstrip("/")
    yield admin, nombre
    borrar_base(admin, nombre)


@pytest.fixture
def base(plantilla):
    admin, nombre = plantilla
    url = clonar_base(admin, nombre)
    yield url
    borrar_base(admin, urlsplit(url).path.lstrip("/"))


@pytest.fixture
def csv(tmp_path):
    return escribir_csv(tmp_path / "tipo_producto.csv")


def _ajustes(base, data_dir, csv, **otros) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=data_dir,
        fotos_dir=data_dir / "fotos",
        persistencia="postgres",
        database_url=_como_rol(base),
        catalogo_origen="archivo",
        catalogo_archivo=csv,
        **otros,
    )


@pytest.fixture
def abrir(base, csv, tmp_path):
    """Abre una instancia de la API (cada una con su pool y su carpeta)."""
    abiertas = []

    def _abrir(nombre="a", **otros):
        carpeta = tmp_path / f"instancia-{nombre}"
        carpeta.mkdir(exist_ok=True)
        app = create_app(_ajustes(base, carpeta, csv, **otros))
        cliente = TestClient(app)
        cliente.__enter__()
        abiertas.append(cliente)
        return cliente, app

    yield _abrir
    for cliente in abiertas:
        cliente.__exit__(None, None, None)


def _cerrar(cliente) -> None:
    cliente.__exit__(None, None, None)


def _sincronizar(cliente, usuario=ADMINISTRADOR):
    return cliente.post(
        "/api/catalogs/equipment/sync", params={"usuario_id": usuario}
    )


def _catalogo(cliente) -> dict:
    return ok(cliente.get("/api/catalogs/equipment"))


def _ofrecidos(catalogo: dict) -> set[str]:
    return {
        color["tipo_producto_id"]
        for modelo in catalogo["modelos"]
        for variante in modelo["variantes"]
        for capacidad in variante["capacidades"]
        for color in capacidad["colores"]
    }


def _huella(base) -> tuple:
    with psycopg.connect(base) as conexion:
        return conexion.execute(
            "select count(*), md5(coalesce(string_agg(t::text, '|' order by"
            " t.tipo_producto_id), '')) from rma.catalogo_producto t"
        ).fetchone()


def _intentos(base) -> list[tuple]:
    with psycopg.connect(base) as conexion:
        return conexion.execute(
            "select id, resultado from rma.sincronizacion_origen order by iniciada_en, id"
        ).fetchall()


class ProveedorSimulado:
    descripcion = "Proveedor simulado"

    def __init__(self, resultado=None, error=None, bloqueo=None):
        self.resultado, self.error, self.bloqueo = resultado, error, bloqueo
        self.llamadas = 0

    def leer(self, filtro):
        self.llamadas += 1
        if self.bloqueo:
            self.bloqueo.wait(10)
        if self.error:
            raise self.error
        return self.resultado


def _con_proveedor(app, proveedor) -> None:
    app.state.contexto = replace(
        app.state.contexto, proveedor_catalogo=proveedor
    )


# --- Persistencia ------------------------------------------------------------


def test_la_copia_sobrevive_al_reinicio_y_no_depende_del_disco(
    abrir, base, tmp_path
):
    cliente, _ = abrir("a")
    exitosa = ok(_sincronizar(cliente))
    assert (exitosa["resultado"], exitosa["nuevos"], exitosa["vigentes"]) == (
        "EXITOSA",
        12,
        12,
    )
    antes = _catalogo(cliente)
    _cerrar(cliente)
    # Otra instancia, con otra carpeta de datos vacia: todo sale de la base.
    nuevo, app = abrir("b")
    despues = _catalogo(nuevo)
    assert despues["estado"]["ultima_exitosa"]["id"] == exitosa["id"]
    assert (despues["estado"]["vigentes"], despues["estado"]["elegibles"]) == (
        12,
        10,
    )
    assert _ofrecidos(despues) == _ofrecidos(antes)
    assert not (
        tmp_path / "instancia-b" / "catalogo_equipos" / "catalogo_equipos.json"
    ).exists()
    assert isinstance(
        app.state.contexto.catalogo_equipos, PostgresCatalogoEquiposRepository
    )


def test_la_copia_sobrevive_en_otro_proceso(abrir, base, csv, tmp_path):
    """Como un arranque en frio: otro proceso de Python lee la copia."""
    cliente, _ = abrir("a")
    exitosa = ok(_sincronizar(cliente))
    _cerrar(cliente)
    carpeta = tmp_path / "proceso"
    carpeta.mkdir()
    codigo = (
        "import json\n"
        "from fastapi.testclient import TestClient\n"
        "from app.main import create_app\n"
        "with TestClient(create_app()) as c:\n"
        "    r = c.get('/api/catalogs/equipment')\n"
        "    print(json.dumps({'status': r.status_code, 'estado': r.json()['estado']}))\n"
    )
    entorno = {
        **{k: v for k, v in os.environ.items() if not k.startswith("RMA_")},
        "PYTHONPATH": str(RAIZ_BACKEND),
        "RMA_PERSISTENCIA": "postgres",
        "RMA_DATABASE_URL": _como_rol(base),
        "RMA_DATA_DIR": str(carpeta),
        "RMA_CATALOGO_ORIGEN": "archivo",
        "RMA_CATALOGO_ARCHIVO": str(csv),
    }
    salida = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=carpeta,  # sin .env
        env=entorno,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert salida.returncode == 0, salida.stderr[-2000:]
    resultado = json.loads(salida.stdout.strip().splitlines()[-1])
    assert resultado["status"] == 200
    assert resultado["estado"]["ultima_exitosa"]["id"] == exitosa["id"]
    assert resultado["estado"]["vigentes"] == 12


def test_repetir_no_duplica_y_las_bajas_no_borran(abrir, base, csv):
    cliente, app = abrir()
    ok(_sincronizar(cliente))
    segunda = ok(_sincronizar(cliente, COORDINADOR))
    assert (segunda["nuevos"], segunda["sin_cambios"]) == (0, 12)
    escribir_csv(csv, [f for f in filas_base() if ID_12_NEGRO not in f])
    tercera = ok(_sincronizar(cliente))
    assert tercera["dados_de_baja"] == 1
    productos = {
        p.tipo_producto_id: p
        for p in app.state.contexto.catalogo_equipos.listar_productos()
    }
    assert len(productos) == 12
    assert productos[ID_12_NEGRO].vigente is False
    assert productos[ID_12_NEGRO].motivo_baja.value == "NO_INFORMADO"
    assert [r for _, r in _intentos(base)] == ["EXITOSA"] * 3


# --- Fallos: la ultima copia valida se conserva -------------------------------


def test_si_el_origen_falla_se_conserva_la_copia(abrir, base):
    cliente, app = abrir()
    exitosa = ok(_sincronizar(cliente))
    huella = _huella(base)
    _con_proveedor(
        app,
        ProveedorSimulado(
            error=CatalogoOrigenNoDisponibleError(
                "No se pudo conectar con Google Sheets."
            )
        ),
    )
    respuesta = _sincronizar(cliente)
    assert respuesta.status_code == 503
    assert (
        "Se conserva el catálogo anterior"
        in respuesta.json()["error"]["mensaje"]
    )
    assert _huella(base) == huella
    estado = _catalogo(cliente)["estado"]
    assert estado["ultima"]["resultado"] == "FALLIDA"
    assert (
        estado["ultima"]["mensaje"] == "No se pudo conectar con Google Sheets."
    )
    assert estado["ultima_exitosa"]["id"] == exitosa["id"]


def test_datos_no_confiables_se_rechazan_sin_tocar_la_copia(abrir, base, csv):
    cliente, _ = abrir()
    ok(_sincronizar(cliente))
    huella = _huella(base)
    csv.write_text("tp_id,tp_modelo\nx,y\n", encoding="utf-8")
    assert "faltan columnas" in conflicto(
        _sincronizar(cliente), "CATALOGO_ORIGEN_INVALIDO"
    )
    assert _huella(base) == huella
    assert [r for _, r in _intentos(base)] == ["EXITOSA", "RECHAZADA"]


def test_un_fallo_a_mitad_de_la_aplicacion_no_deja_nada(
    abrir, base, csv, monkeypatch
):
    """El upsert ya escribio filas cuando falla el cierre del intento: la
    transaccion se revierte entera y el intento queda FALLIDA."""
    cliente, app = abrir()
    exitosa = ok(_sincronizar(cliente))
    huella = _huella(base)
    escribir_csv(csv, [f for f in filas_base() if ID_12_NEGRO not in f])
    original = PostgresCatalogoEquiposRepository._finalizar

    def falla_al_cerrar(ejecutor, sincronizacion, reserva):
        if sincronizacion.resultado.value == "EXITOSA":
            raise RuntimeError("se corto a mitad")
        original(ejecutor, sincronizacion, reserva)

    monkeypatch.setattr(
        PostgresCatalogoEquiposRepository,
        "_finalizar",
        staticmethod(falla_al_cerrar),
    )
    with pytest.raises(RuntimeError, match="se corto a mitad"):
        sincronizar_catalogo_equipos(
            app.state.contexto, usuario_id=ADMINISTRADOR
        )
    monkeypatch.undo()
    assert _huella(base) == huella
    estado = _catalogo(cliente)["estado"]
    assert estado["ultima"]["resultado"] == "FALLIDA"
    assert estado["ultima"]["mensaje"] == MENSAJE_APLICACION
    assert estado["ultima_exitosa"]["id"] == exitosa["id"]
    # Y la siguiente funciona.
    assert ok(_sincronizar(cliente))["dados_de_baja"] == 1


def test_una_instancia_caida_a_mitad_no_bloquea_para_siempre(abrir, base):
    """Una reserva que nadie termino (la instancia se apago) vence; la
    sincronizacion siguiente la marca INTERRUMPIDA y aplica."""
    cliente, app = abrir()
    caida = app.state.contexto.catalogo_equipos.reservar_sincronizacion(
        id="SINC-0000000000ca",
        usuario_id=ADMINISTRADOR,
        origen="instancia caida",
        filtro="",
        duracion=timedelta(seconds=1),
        propietario="c" * 64,
    )
    assert conflicto(_sincronizar(cliente), "SINCRONIZACION_EN_CURSO")
    time.sleep(1.3)
    assert ok(_sincronizar(cliente))["resultado"] == "EXITOSA"
    resultados = dict(_intentos(base))
    assert resultados[caida.id] == "INTERRUMPIDA"
    estado = _catalogo(cliente)["estado"]
    assert estado["ultima"]["resultado"] == "EXITOSA"


# --- Concurrencia entre instancias ----------------------------------------------


def test_dos_instancias_no_sincronizan_a_la_vez(abrir, base):
    cliente_a, app_a = abrir("a")
    cliente_b, _ = abrir("b")
    bloqueo = threading.Event()
    lento = ProveedorSimulado(
        resultado=LecturaCatalogo(
            productos=(
                ProductoInformado(
                    tipo_producto_id="A",
                    descripcion="A",
                    marca="Apple",
                    modelo="iPhone 12",
                    capacidad="128 GB",
                    color="Black",
                ),
            ),
            leidos=1,
            filtrados=1,
        ),
        bloqueo=bloqueo,
    )
    _con_proveedor(app_a, lento)
    resultado = {}

    def en_a():
        resultado["a"] = sincronizar_catalogo_equipos(
            app_a.state.contexto, usuario_id=ADMINISTRADOR
        )

    hilo = threading.Thread(target=en_a)
    hilo.start()
    while lento.llamadas == 0:
        time.sleep(0.01)
    # Otra instancia (otro pool, como otra revision de Cloud Run).
    assert "en curso" in conflicto(
        _sincronizar(cliente_b), "SINCRONIZACION_EN_CURSO"
    )
    with pytest.raises(SincronizacionEnCursoError):
        sincronizar_catalogo_equipos(
            app_a.state.contexto, usuario_id=ADMINISTRADOR
        )
    bloqueo.set()
    hilo.join(15)
    assert resultado["a"].resultado.value == "EXITOSA"
    assert [
        p.tipo_producto_id
        for p in app_a.state.contexto.catalogo_equipos.listar_productos()
    ] == ["A"]
    assert ok(_sincronizar(cliente_b))["resultado"] == "EXITOSA"


def test_una_aplicacion_tardia_responde_409_y_no_toca_la_copia(abrir, base):
    """QA C fase B, menor 2: A tarda mas que su reserva; B la toma y aplica;
    A recibe 409 y la copia es la de B."""
    cliente_a, app_a = abrir("a")
    cliente_b, _ = abrir("b")
    bloqueo = threading.Event()

    def lectura(tipo):
        return LecturaCatalogo(
            productos=(
                ProductoInformado(
                    tipo_producto_id=tipo,
                    descripcion=tipo,
                    marca="Apple",
                    modelo="iPhone 12",
                    capacidad="128 GB",
                    color="Black",
                ),
            ),
            leidos=1,
            filtrados=1,
        )

    lento = ProveedorSimulado(resultado=lectura("A-LENTA"), bloqueo=bloqueo)
    app_a.state.contexto = replace(
        app_a.state.contexto,
        proveedor_catalogo=lento,
        reserva_sincronizacion=timedelta(seconds=1),
    )
    resultado = {}

    def en_a():
        try:
            sincronizar_catalogo_equipos(
                app_a.state.contexto, usuario_id=ADMINISTRADOR
            )
            resultado["a"] = "aplico"
        except SincronizacionEnCursoError as error:
            resultado["a"] = str(error)

    hilo = threading.Thread(target=en_a)
    hilo.start()
    while lento.llamadas == 0:
        time.sleep(0.01)
    time.sleep(1.3)  # vence la reserva de A
    assert ok(_sincronizar(cliente_b))["resultado"] == "EXITOSA"
    huella = _huella(base)
    bloqueo.set()
    hilo.join(15)
    assert "tardó más que su reserva" in resultado["a"]
    assert _huella(base) == huella
    assert "A-LENTA" not in {
        p.tipo_producto_id
        for p in app_a.state.contexto.catalogo_equipos.listar_productos()
    }
    assert [r for _, r in _intentos(base)] == ["INTERRUMPIDA", "EXITOSA"]


def test_las_fechas_salen_en_utc_aunque_la_sesion_no_lo_este(
    abrir, base, plantilla
):
    """QA C fase B, menor 1."""
    admin, _ = plantilla
    nombre = urlsplit(base).path.lstrip("/")
    with psycopg.connect(base, autocommit=True) as conexion:
        conexion.execute(
            f"alter database {nombre} set timezone = 'America/Argentina/Buenos_Aires'"
        )
    cliente, app = abrir()
    respuesta = ok(_sincronizar(cliente))
    estado = _catalogo(cliente)["estado"]
    for momento in (
        estado["ultima"]["iniciada_en"],
        estado["ultima"]["finalizada_en"],
        respuesta["iniciada_en"],
    ):
        assert momento.endswith("Z") or momento.endswith("+00:00"), momento
    producto = app.state.contexto.catalogo_equipos.listar_productos()[0]
    assert producto.primera_sincronizacion.utcoffset() == timedelta(0)


# --- El alta, con y sin copia -----------------------------------------------------


def test_el_alta_funciona_con_la_copia_vacia_y_con_la_copia(abrir):
    cliente, _ = abrir()
    assert _catalogo(cliente)["modelos"] == []
    assert crear(cliente)  # carga manual, como hoy
    ok(_sincronizar(cliente))
    orden = ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": RECEPCION,
                "cliente": {"nombre_apellido": "Cliente", "telefono": "341-1"},
                "equipo": {
                    "falla_reportada": "No carga.",
                    "tipo_producto_id": ID_12_PRO_MAX_VIOLETA,
                    "imei": IMEI,
                },
            },
        )
    )
    assert orden["equipo"]["tipo_producto_id"] == ID_12_PRO_MAX_VIOLETA
    assert orden["equipo"]["capacidad"] == "256 GB"


def test_sin_permiso_no_se_registra_ningun_intento(abrir, base):
    cliente, _ = abrir()
    conflicto(_sincronizar(cliente, RECEPCION))
    assert _intentos(base) == []
