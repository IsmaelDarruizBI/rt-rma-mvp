# ruff: noqa: E501  (SQL)
"""Reparacion RT, etapa 1: la copia de Productos de Gestion RT en
PostgreSQL, de punta a punta por la API.

Con ``RMA_PERSISTENCIA=postgres``, el rol minimo de la API (miembro de
``rma_backend``) y el origen ``archivo`` con los productos ficticios
(``tests/fixtures/productos_rt.py``). Cada prueba usa una base propia,
clonada de una plantilla con todas las migraciones y las cargas de
desarrollo. Diseño: docs/reparacion-rt-discovery.md, secciones 2, 5, 6 y 8.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("psycopg_pool")

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.seguridad import Autenticacion  # noqa: E402
from app.core.autenticacion import (  # noqa: E402
    VerificadorDeTokens,
    parametros_de,
)
from app.core.config import Settings  # noqa: E402
from app.integraciones.gestion_rt import COLUMNAS  # noqa: E402
from app.main import create_app  # noqa: E402
from app.storage.postgres.productos_rt import (  # noqa: E402
    PostgresProductosRtRepository,
)
from tests.fixtures import productos_rt as ficticios  # noqa: E402
from tests.fixtures.api_salidas import (  # noqa: E402
    ADMINISTRADOR,
    COORDINADOR,
    RECEPCION,
    TECNICO,
    ok,
)
from tests.fixtures.catalogo_ventas import escribir_csv as escribir_catalogo  # noqa: E402
from tests.fixtures.productos_rt import imei_ficticio, producto  # noqa: E402
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
RUTA = "/api/rt-products"


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
def archivos(tmp_path):
    """Producto y TipoProducto ficticios; ``escribir(filas)`` cambia el
    origen para la sincronizacion siguiente."""

    class Archivos:
        productos = ficticios.escribir_csv(tmp_path / "producto.csv")
        tipos = ficticios.escribir_tipos(tmp_path / "tipo_producto.csv")

        def escribir(self, filas):
            ficticios.escribir_csv(self.productos, filas)

    return Archivos()


def _ajustes(base, data_dir, archivos, **otros) -> Settings:
    valores = {
        "persistencia": "postgres",
        "database_url": _como_rol(base),
        "productos_rt_origen": "archivo",
        "productos_rt_archivo": archivos.productos,
        "productos_rt_tipos_archivo": archivos.tipos,
        **otros,
    }
    return Settings(
        _env_file=None,
        data_dir=data_dir,
        fotos_dir=data_dir / "fotos",
        **valores,
    )


@pytest.fixture
def abrir(base, archivos, tmp_path):
    """Abre una instancia de la API (cada una con su pool y su carpeta)."""
    abiertas = []

    def _abrir(nombre="a", **otros):
        carpeta = tmp_path / f"instancia-{nombre}"
        carpeta.mkdir(exist_ok=True)
        app = create_app(_ajustes(base, carpeta, archivos, **otros))
        cliente = TestClient(app)
        cliente.__enter__()
        abiertas.append(cliente)
        return cliente, app

    yield _abrir
    for cliente in abiertas:
        cliente.__exit__(None, None, None)


def _sincronizar(cliente, usuario=ADMINISTRADOR, **cabeceras):
    return cliente.post(
        f"{RUTA}/sync", params={"usuario_id": usuario}, headers=cabeceras
    )


def _listar(cliente, **parametros) -> dict:
    return ok(cliente.get(RUTA, params=parametros))


def _ids(listado: dict) -> list[str]:
    return [p["producto_id"] for p in listado["productos"]]


def _sql(base, sentencia, parametros=()):
    with psycopg.connect(base, autocommit=True) as conexion:
        return conexion.execute(sentencia, parametros).fetchall()


def _huella(base) -> tuple:
    return _sql(
        base,
        "select count(*), md5(coalesce(string_agg(t::text, '|' order by"
        " t.producto_id), '')) from rma.producto_rt t",
    )[0]


def _intentos(base, copia="PRODUCTOS_RT") -> list[tuple]:
    return _sql(
        base,
        "select id, resultado from rma.sincronizacion_origen where copia = %s"
        " order by iniciada_en, id",
        (copia,),
    )


def _con_cambios(cambios: dict[str, dict], quitar=()) -> list[list]:
    filas = []
    for fila in ficticios.productos_base():
        pid = fila[COLUMNAS.index("producto_id")]
        if pid in quitar:
            continue
        for columna, valor in cambios.get(pid, {}).items():
            fila[COLUMNAS.index(columna)] = valor
        filas.append(fila)
    return filas


# --- Esquema y escritura protegida -------------------------------------------


def test_migracion_aditiva_y_permisos(base):
    restricciones = dict(
        _sql(
            base,
            "select conname, pg_get_constraintdef(oid) from pg_constraint"
            " where conrelid = 'rma.sincronizacion_origen'::regclass and contype = 'c'",
        )
    )
    assert "sincronizacion_origen_copia_check" not in restricciones
    assert "PRODUCTOS_RT" in restricciones["sincronizacion_origen_copia"]
    privilegios = {
        fila[0]
        for fila in _sql(
            base,
            "select privilege_type from information_schema.role_table_grants"
            " where table_schema = 'rma' and table_name = 'producto_rt'"
            " and grantee = 'rma_backend'",
        )
    }
    assert privilegios == {"SELECT", "INSERT"}
    columnas = {
        fila[0]
        for fila in _sql(
            base,
            "select column_name from information_schema.column_privileges"
            " where table_schema = 'rma' and table_name = 'producto_rt'"
            " and grantee = 'rma_backend' and privilege_type = 'UPDATE'",
        )
    }
    assert "producto_id" not in columnas
    assert "primera_vez_visto_en" not in columnas
    assert "creado_en" not in columnas
    assert {"en_reparacion", "propietario", "sincronizacion_id"} <= columnas
    for rol in ("anon", "authenticated"):
        if _sql(base, "select 1 from pg_roles where rolname = %s", (rol,)):
            assert not _sql(
                base,
                "select 1 from information_schema.role_table_grants"
                " where table_schema = 'rma' and table_name = 'producto_rt'"
                " and grantee = %s",
                (rol,),
            )


def test_la_copia_solo_se_escribe_dentro_de_su_sincronizacion(abrir, base):
    cliente, _ = abrir()
    exitosa = ok(_sincronizar(cliente))
    fila = (
        "insert into rma.producto_rt (producto_id, estado_gestion_rt, en_reparacion,"
        " en_reparacion_desde, texto_busqueda, huella, primera_vez_visto_en,"
        " sincronizado_en, sincronizacion_id, propietario)"
        " values ('X1', 'Reparacion', true, now(), 'x1', repeat('a', 64), now(),"
        " now(), %s, %s)"
    )
    # Un intento terminado no escribe, aun con un secreto.
    with pytest.raises(psycopg.errors.RestrictViolation):
        _sql(base, fila, (exitosa["id"], "s" * 64))
    # Un intento de la otra copia tampoco.
    catalogo = _sql(
        base,
        "select id from rma.reservar_sincronizacion('SINC-0000000000c1',"
        " 'CATALOGO_VENTAS', (select id from rma.usuario where codigo = %s),"
        " 'prueba', '', interval '1 minute', %s)",
        (ADMINISTRADOR, "c" * 64),
    )[0][0]
    with pytest.raises(psycopg.errors.RestrictViolation):
        _sql(base, fila, (catalogo, "c" * 64))
    # El propio, sin el secreto, tampoco.
    propio = _sql(
        base,
        "select id from rma.reservar_sincronizacion('SINC-0000000000a1',"
        " 'PRODUCTOS_RT', (select id from rma.usuario where codigo = %s),"
        " 'prueba', '', interval '1 minute', %s)",
        (ADMINISTRADOR, "p" * 64),
    )[0][0]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _sql(base, fila, (propio, "otro" * 16))
    # Nunca se borra ni cambia su identificador.
    with pytest.raises(psycopg.errors.RestrictViolation):
        _sql(base, "delete from rma.producto_rt where producto_id = '900001'")
    assert not _sql(
        base, "select 1 from rma.producto_rt where propietario is not null"
    )
    assert not _sql(
        base,
        "select 1 from rma.sincronizacion_origen where propietario is not null",
    )


# --- Primera sincronizacion y listado ----------------------------------------


def test_primera_sincronizacion_y_listado(abrir, base):
    cliente, app = abrir()
    assert isinstance(
        app.state.contexto.productos_rt, PostgresProductosRtRepository
    )
    vacio = _listar(cliente)
    assert vacio["copia"]["habilitado"] and vacio["copia"]["sincronizable"]
    assert vacio["copia"]["datos_del"] is None
    assert vacio["copia"]["desactualizada"]
    assert vacio["total"] == 0

    exitosa = ok(_sincronizar(cliente))
    assert exitosa["resultado"] == "EXITOSA"
    assert exitosa["origen"] == "Archivo CSV (producto.csv)"
    assert exitosa["filtro"] == "producto_status = Reparacion"
    c = exitosa["contadores"]
    assert (c["leidos"], c["descartados"], c["duplicados"]) == (22, 1, 1)
    assert (c["nuevos"], c["en_reparacion"], c["imei_repetidos"]) == (
        14,
        14,
        2,
    )
    assert any("900018" in aviso for aviso in exitosa["avisos"])

    listado = _listar(cliente)
    assert listado["total"] == ficticios.EN_REPARACION
    # La fecha de los datos es la de la base al finalizar el intento.
    copia = listado["copia"]
    assert copia["ultima_exitosa"]["id"] == exitosa["id"]
    assert copia["datos_del"] == copia["ultima_exitosa"]["finalizada_en"]
    assert copia["ultima"]["id"] == exitosa["id"]
    assert not listado["copia"]["desactualizada"]
    sedes = {
        s["sede"]: (s["cantidad"], s["confirmada"]) for s in listado["sedes"]
    }
    for sede, cantidad in ficticios.EN_REPARACION_POR_SEDE.items():
        assert sedes[sede][0] == cantidad
    assert sedes["Rosario Norte"] == (1, False)
    assert sedes["Alippi"][1] is True
    assert len(_intentos(base)) == 1
    assert _sql(base, "select count(*) from rma.producto_rt")[0][0] == 14


def test_repetir_la_sincronizacion_no_duplica(abrir, base):
    cliente, _ = abrir()
    ok(_sincronizar(cliente))
    antes = _huella(base)
    segunda = ok(_sincronizar(cliente))
    assert segunda["contadores"]["nuevos"] == 0
    assert segunda["contadores"]["actualizados"] == 0
    assert segunda["contadores"]["sin_cambios"] == 14
    assert _huella(base)[0] == antes[0]


def test_busqueda_y_filtros(abrir):
    cliente, _ = abrir()
    ok(_sincronizar(cliente))
    assert _ids(_listar(cliente, q="900002")) == ["900002"]
    assert _ids(_listar(cliente, q=imei_ficticio(3))) == ["900003"]
    # Ultimos 4 digitos del IMEI.
    assert "900003" in _ids(_listar(cliente, q=imei_ficticio(3)[-4:]))
    # Modelo por palabras, sin mayusculas ni tildes.
    pro_max = _ids(_listar(cliente, q="PRO máx"))
    assert set(pro_max) == {"900002", "900003", "900021", "900022"}
    assert _ids(_listar(cliente, q="iphone 12 pro max")) == [
        "900002",
        "900022",
    ]
    assert _listar(cliente, q="no existe nada")["total"] == 0
    # Sede (repetible) y sin sede.
    centro = _listar(cliente, sede=["Centro"])
    assert set(_ids(centro)) == {"900003", "900004", "900005"}
    # Las cantidades por sede no dependen del filtro de sede.
    assert sum(s["cantidad"] for s in centro["sedes"]) == 14
    dos = _listar(cliente, sede=["Alippi", "Rosario Norte"])
    assert set(_ids(dos)) == {"900001", "900002", "900012"}
    assert _listar(cliente, sede=[""])["total"] == 0
    # Paginas.
    primera = _listar(cliente, tamano=5, pagina=1)
    tercera = _listar(cliente, tamano=5, pagina=3)
    assert (len(primera["productos"]), len(tercera["productos"])) == (5, 4)
    assert primera["total"] == tercera["total"] == 14
    assert not set(_ids(primera)) & set(_ids(tercera))
    assert cliente.get(RUTA, params={"tamano": 101}).status_code == 422


def test_cambios_de_estado_entre_sincronizaciones(abrir, archivos):
    cliente, _ = abrir()
    ok(_sincronizar(cliente))
    archivos.escribir(
        _con_cambios(
            {
                "900001": {"producto_status": "Stock"},
                "900003": {"producto_eliminado": "yes"},
            },
            quitar=("900002",),
        )
    )
    cambios = ok(_sincronizar(cliente))["contadores"]
    assert (
        cambios["salieron"],
        cambios["eliminados"],
        cambios["ausentes"],
    ) == (
        1,
        1,
        1,
    )
    assert cambios["en_reparacion"] == 11
    visibles = _ids(_listar(cliente))
    for pid in ("900001", "900002", "900003"):
        assert pid not in visibles
    todos = _listar(cliente, incluir_fuera="true")
    assert todos["total"] == 14
    fuera = {p["producto_id"]: p for p in todos["productos"]}
    assert "FUERA_DE_REPARACION" in fuera["900001"]["avisos"]
    assert fuera["900001"]["estado_gestion_rt"] == "Stock"
    assert "ELIMINADO_EN_ORIGEN" in fuera["900003"]["avisos"]
    assert "AUSENTE_DEL_ORIGEN" in fuera["900002"]["avisos"]

    archivos.escribir(ficticios.productos_base())
    vuelta = ok(_sincronizar(cliente))["contadores"]
    assert vuelta["volvieron"] == 1
    ficha = ok(cliente.get(f"{RUTA}/900001"))["producto"]
    assert ficha["en_reparacion"] and ficha["salio_de_reparacion_en"] is None
    assert ficha["en_reparacion_desde"] > ficha["primera_vez_visto_en"]


# --- Coincidencias sugeridas (seccion 5) -------------------------------------


def _crear_orden_cliente(cliente, imei: str) -> str:
    return ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": RECEPCION,
                "cliente": {
                    "nombre_apellido": "Cliente ficticio",
                    "telefono": "341-1",
                },
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 12",
                    "falla_reportada": "No carga (ficticio).",
                    "imei": imei,
                },
            },
        )
    )["id"]


def _crear_orden_rt(cliente, referencia: str, imei: str | None = None) -> str:
    return ok(
        cliente.post(
            "/api/orders/rt-interno",
            json={
                "usuario_id": RECEPCION,
                "referencia_rt": referencia,
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 12",
                    "falla_reportada": "Ingreso RT manual (ficticio).",
                    "imei": imei,
                },
            },
        )
    )["id"]


def test_coincidencias_sugeridas_nunca_son_vinculos(abrir, base):
    cliente, _ = abrir()
    ok(_sincronizar(cliente))
    antes = _huella(base)
    rt = _crear_orden_rt(cliente, f"  {ficticios.ID_CON_REFERENCIA} ")
    con_imei = _crear_orden_cliente(
        cliente,
        " ".join(ficticios.IMEI_CON_ORDEN[i : i + 5] for i in (0, 5, 10)),
    )
    # Una Orden que coincide por los dos criterios aparece una vez.
    ambas = _crear_orden_rt(cliente, "900003", imei=imei_ficticio(3))
    # IMEI repetido o invalido: nunca sugieren.
    _crear_orden_cliente(cliente, ficticios.IMEI_REPETIDO)
    _crear_orden_cliente(cliente, "12345")
    # La referencia RT de una Orden de cliente no cuenta.
    assert _huella(base) == antes  # crear Ordenes no toca la copia

    ficha = ok(cliente.get(f"{RUTA}/{ficticios.ID_CON_REFERENCIA}"))[
        "producto"
    ]
    sugeridas = {c["orden_id"]: c for c in ficha["coincidencias_sugeridas"]}
    assert set(sugeridas) == {rt, con_imei}
    assert sugeridas[rt]["criterios"] == ["REFERENCIA_RT"]
    assert sugeridas[rt]["origen"] == "RT_INTERNO"
    assert sugeridas[con_imei]["criterios"] == ["IMEI"]
    assert sugeridas[con_imei]["origen"] == "CLIENTE_EXTERNO"
    assert not sugeridas[rt]["cerrada"]
    # Nada se presenta como vinculo, Orden activa ni historial.
    for clave in ("vinculos", "orden_activa", "historial", "orden_id"):
        assert clave not in ficha

    tres = ok(cliente.get(f"{RUTA}/900003"))["producto"]
    assert [
        (c["orden_id"], c["criterios"])
        for c in tres["coincidencias_sugeridas"]
    ] == [(ambas, ["IMEI", "REFERENCIA_RT"])]
    for pid in ("900009", "900010", "900005"):
        assert (
            ok(cliente.get(f"{RUTA}/{pid}"))["producto"][
                "coincidencias_sugeridas"
            ]
            == []
        )

    con = _listar(cliente, orden_rma="CON_SUGERENCIAS")
    assert set(_ids(con)) == {ficticios.ID_CON_REFERENCIA, "900003"}
    sin = _listar(cliente, orden_rma="SIN_COINCIDENCIAS")
    assert sin["total"] == 12 and not set(_ids(sin)) & set(_ids(con))
    en_listado = {p["producto_id"]: p for p in con["productos"]}
    assert len(en_listado["900022"]["coincidencias_sugeridas"]) == 2
    # Ninguna Orden ni Equipo cambio por la sincronizacion.
    ordenes = _sql(
        base, "select codigo, version from rma.orden order by codigo"
    )
    ok(_sincronizar(cliente))
    assert (
        _sql(base, "select codigo, version from rma.orden order by codigo")
        == ordenes
    )


def test_ficha_y_avisos(abrir):
    cliente, _ = abrir()
    ok(_sincronizar(cliente))
    respuesta = cliente.get(f"{RUTA}/no-existe")
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["codigo"] == "NO_ENCONTRADO"
    ficha = ok(cliente.get(f"{RUTA}/900002"))
    p = ficha["producto"]
    assert ficha["copia"]["datos_del"] is not None
    assert (p["modelo"], p["capacidad"], p["color"]) == (
        "iPhone 12 Pro Max",
        "256 GB",
        "Deep Purple",
    )
    assert p["bateria"] == "87" and p["toma_rt"] == "TOMA"
    assert p["tipo_reparacion_origen"] == "Pantalla"
    assert p["imei_luhn_valido"] is True and p["avisos"] == []
    for clave in ("texto_busqueda", "huella"):
        assert clave not in p
    avisos = {
        pid: set(ok(cliente.get(f"{RUTA}/{pid}"))["producto"]["avisos"])
        for pid in ("900004", "900005", "900007", "900008", "900009", "900012")
    }
    assert avisos["900004"] == {"SIN_IMEI"}
    assert avisos["900005"] == {"IMEI_INVALIDO"}
    assert avisos["900007"] == {"TIPO_NO_ENCONTRADO"}
    assert avisos["900008"] == {"TIPO_ELIMINADO"}
    assert avisos["900009"] == {"IMEI_REPETIDO"}
    assert avisos["900012"] == {"SEDE_NO_CONFIRMADA"}


# --- Sincronizaciones fallidas (seccion 2.9) ---------------------------------


def test_origen_no_disponible_conserva_la_copia(abrir, base, archivos):
    cliente, _ = abrir()
    exitosa = ok(_sincronizar(cliente))
    antes = _huella(base)
    archivos.productos.unlink()
    respuesta = _sincronizar(cliente)
    assert respuesta.status_code == 503, respuesta.text
    assert (
        respuesta.json()["error"]["codigo"]
        == "PRODUCTOS_RT_ORIGEN_NO_DISPONIBLE"
    )
    assert "producto.csv" in respuesta.json()["error"]["mensaje"]
    assert _huella(base) == antes
    assert [r for _, r in _intentos(base)] == ["EXITOSA", "FALLIDA"]
    listado = _listar(cliente)
    assert listado["total"] == 14
    assert listado["copia"]["ultima"]["resultado"] == "FALLIDA"
    assert listado["copia"]["ultima_exitosa"]["id"] == exitosa["id"]


def test_estructura_invalida_rechazada_sin_cambios(abrir, base, archivos):
    cliente, _ = abrir()
    ok(_sincronizar(cliente))
    antes = _huella(base)
    columnas = [c for c in COLUMNAS if c != "producto_sede"]
    archivos.productos.write_text(",".join(columnas) + "\n", encoding="utf-8")
    respuesta = _sincronizar(cliente)
    assert respuesta.status_code == 409, respuesta.text
    error = respuesta.json()["error"]
    assert error["codigo"] == "PRODUCTOS_RT_ORIGEN_INVALIDO"
    assert "producto_sede" in error["mensaje"]
    assert _huella(base) == antes
    assert [r for _, r in _intentos(base)] == ["EXITOSA", "RECHAZADA"]


def test_lectura_truncada_rechazada_sin_cambios(abrir, base, archivos):
    cliente, _ = abrir()
    ok(_sincronizar(cliente))
    antes = _huella(base)
    archivos.escribir(ficticios.productos_base()[:3])
    respuesta = _sincronizar(cliente)
    assert respuesta.status_code == 409, respuesta.text
    assert "incompleta" in respuesta.json()["error"]["mensaje"]
    assert _huella(base) == antes
    ultimo = ok(cliente.get(f"{RUTA}/syncs"))[0]
    assert ultimo["resultado"] == "RECHAZADA"
    assert ultimo["contadores"]["leidos"] == 3


def test_error_al_aplicar_conserva_la_copia(abrir, base, monkeypatch):
    _, app = abrir()
    cliente = TestClient(app, raise_server_exceptions=False)
    ok(_sincronizar(cliente))
    antes = _huella(base)

    def falla(*args, **kwargs):
        raise RuntimeError("falla simulada al aplicar")

    monkeypatch.setattr(
        PostgresProductosRtRepository, "aplicar_sincronizacion", falla
    )
    respuesta = _sincronizar(cliente)
    assert respuesta.status_code == 500
    assert _huella(base) == antes
    assert [r for _, r in _intentos(base)][-1] == "FALLIDA"


# --- Concurrencia, reinicio y escalado a cero --------------------------------


class ProveedorBloqueado:
    descripcion = "Proveedor bloqueado"

    def __init__(
        self, real, liberar: threading.Event, leyendo: threading.Event
    ):
        self.real, self.liberar, self.leyendo = real, liberar, leyendo

    def leer(self):
        self.leyendo.set()
        self.liberar.wait(20)
        return self.real.leer()


def test_una_sincronizacion_por_vez_entre_instancias(abrir, base):
    a, app_a = abrir("a")
    b, _ = abrir("b")
    liberar, leyendo = threading.Event(), threading.Event()
    app_a.state.contexto = replace(
        app_a.state.contexto,
        proveedor_productos_rt=ProveedorBloqueado(
            app_a.state.contexto.proveedor_productos_rt, liberar, leyendo
        ),
    )
    resultado = {}
    hilo = threading.Thread(
        target=lambda: resultado.setdefault("a", _sincronizar(a))
    )
    hilo.start()
    assert leyendo.wait(20)
    segunda = _sincronizar(b)
    assert segunda.status_code == 409, segunda.text
    assert segunda.json()["error"]["codigo"] == "SINCRONIZACION_EN_CURSO"
    # El catalogo de Ventas es otra copia: no lo bloquea.
    assert (
        _sql(
            base,
            "select count(*) from rma.sincronizacion_origen where resultado = 'EN_CURSO'",
        )[0][0]
        == 1
    )
    liberar.set()
    hilo.join(30)
    assert resultado["a"].status_code == 200, resultado["a"].text
    assert [r for _, r in _intentos(base)] == ["EXITOSA"]


def test_la_copia_sobrevive_al_reinicio_y_al_arranque_en_frio(
    abrir, base, archivos, tmp_path
):
    cliente, _ = abrir("a")
    exitosa = ok(_sincronizar(cliente))
    antes = _listar(cliente)
    cliente.__exit__(None, None, None)
    nuevo, _ = abrir("b", productos_rt_origen="ninguno")
    despues = _listar(nuevo)
    assert despues["copia"]["ultima_exitosa"]["id"] == exitosa["id"]
    assert not despues["copia"]["sincronizable"]
    assert _ids(despues) == _ids(antes)
    assert despues["sedes"] == antes["sedes"]
    assert list((tmp_path / "instancia-b").rglob("*producto*")) == []

    # Otro proceso de Python, sin origen: como una instancia nueva tras el
    # escalado a cero.
    carpeta = tmp_path / "proceso"
    carpeta.mkdir()
    codigo = (
        "import json\n"
        "from fastapi.testclient import TestClient\n"
        "from app.main import create_app\n"
        "with TestClient(create_app()) as c:\n"
        "    r = c.get('/api/rt-products')\n"
        "    d = r.json()\n"
        "    print(json.dumps({'status': r.status_code, 'total': d['total'],"
        " 'id': d['copia']['ultima_exitosa']['id']}))\n"
    )
    entorno = {
        **{k: v for k, v in os.environ.items() if not k.startswith("RMA_")},
        "PYTHONPATH": str(RAIZ_BACKEND),
        "RMA_PERSISTENCIA": "postgres",
        "RMA_DATABASE_URL": _como_rol(base),
        "RMA_DATA_DIR": str(carpeta),
    }
    salida = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=RAIZ_BACKEND,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert salida.returncode == 0, salida.stderr
    resultado = json.loads(salida.stdout.strip().splitlines()[-1])
    assert resultado == {"status": 200, "total": 14, "id": exitosa["id"]}


def test_el_catalogo_de_ventas_sigue_igual(abrir, base, tmp_path):
    catalogo = escribir_catalogo(tmp_path / "catalogo.csv")
    cliente, _ = abrir(catalogo_origen="archivo", catalogo_archivo=catalogo)
    ventas = ok(
        cliente.post(
            "/api/catalogs/equipment/sync",
            params={"usuario_id": ADMINISTRADOR},
        )
    )
    productos = ok(_sincronizar(cliente))
    assert ventas["resultado"] == productos["resultado"] == "EXITOSA"
    assert _intentos(base, "CATALOGO_VENTAS") == [(ventas["id"], "EXITOSA")]
    assert _intentos(base) == [(productos["id"], "EXITOSA")]
    estado = ok(cliente.get("/api/catalogs/equipment"))["estado"]
    assert estado["ultima"]["id"] == ventas["id"]
    assert [s["id"] for s in ok(cliente.get(f"{RUTA}/syncs"))] == [
        productos["id"]
    ]


# --- Datos sensibles (seccion 2.8) -------------------------------------------


def test_nada_sensible_en_la_base_las_respuestas_ni_los_registros(
    abrir, base, caplog
):
    caplog.set_level(logging.DEBUG)
    cliente, _ = abrir()
    respuestas = [
        _sincronizar(cliente).text,
        cliente.get(f"{RUTA}/syncs").text,
    ]
    respuestas.append(cliente.get(RUTA, params={"incluir_fuera": "true"}).text)
    respuestas += [
        cliente.get(f"{RUTA}/{pid}").text for pid in ("900001", "900022")
    ]
    tabla = _sql(
        base, "select string_agg(t::text, '|') from rma.producto_rt t"
    )[0][0]
    intentos = _sql(
        base,
        "select string_agg(t::text, '|') from rma.sincronizacion_origen t",
    )[0][0]
    for texto in (*respuestas, tabla, intentos, caplog.text):
        assert ficticios.VALOR_SENSIBLE not in texto
    # Los registros y los avisos nunca llevan IMEI.
    registro_y_avisos = caplog.text + intentos
    for numero in range(1, 23):
        assert imei_ficticio(numero) not in registro_y_avisos


# --- Permisos con sesion real (seccion 6.3) ----------------------------------

PROYECTO = "https://proyecto-prueba.supabase.co"
CLAVE = ec.generate_private_key(ec.SECP256R1())


def _token(identidad: str) -> str:
    ahora = int(time.time())
    return jwt.encode(
        {
            "sub": identidad,
            "iss": f"{PROYECTO}/auth/v1",
            "aud": "authenticated",
            "role": "authenticated",
            "iat": ahora,
            "exp": ahora + 600,
        },
        CLAVE,
        algorithm="ES256",
    )


def test_permisos_por_rol(abrir, base):
    cliente, app = abrir(auth_modo="supabase", auth_supabase_url=PROYECTO)
    identidades = {}
    for codigo in (RECEPCION, COORDINADOR, TECNICO, ADMINISTRADOR):
        identidades[codigo] = str(uuid.uuid4())
        _sql(
            base,
            "update rma.usuario set auth_user_id = %s where codigo = %s"
            " returning codigo",
            (identidades[codigo], codigo),
        )
    ajustes = Settings(
        _env_file=None, auth_modo="supabase", auth_supabase_url=PROYECTO
    )
    app.state.autenticacion = Autenticacion(
        VerificadorDeTokens(
            parametros_de(ajustes), lambda _: CLAVE.public_key()
        )
    )

    def sesion(codigo):
        return {"Authorization": f"Bearer {_token(identidades[codigo])}"}

    assert cliente.get(RUTA).status_code == 401
    assert _sincronizar(cliente).status_code == 401
    # Solo Administracion sincroniza (DEC-RT-05).
    for codigo in (RECEPCION, COORDINADOR, TECNICO):
        respuesta = _sincronizar(cliente, codigo, **sesion(codigo))
        assert respuesta.status_code == 403, (codigo, respuesta.text)
        assert (
            cliente.get(f"{RUTA}/syncs", headers=sesion(codigo)).status_code
            == 403
        )
    assert ok(_sincronizar(cliente, ADMINISTRADOR, **sesion(ADMINISTRADOR)))
    # Consultan Recepcion, Coordinacion RMA y Administracion (DEC-RT-07).
    for codigo in (RECEPCION, COORDINADOR, ADMINISTRADOR):
        listado = cliente.get(RUTA, headers=sesion(codigo))
        assert listado.status_code == 200, (codigo, listado.text)
        assert (
            cliente.get(f"{RUTA}/900001", headers=sesion(codigo)).status_code
            == 200
        )
    for ruta in (RUTA, f"{RUTA}/900001"):
        assert cliente.get(ruta, headers=sesion(TECNICO)).status_code == 403
    # Configurable: Administracion habilita la consulta al Tecnico.
    _sql(
        base,
        "insert into rma.permiso (codigo, roles) values ('PRODUCTOS_RT_CONSULTAR',"
        " array['RECEPCION', 'COORDINADOR_RMA', 'ADMINISTRADOR', 'TECNICO'])"
        " returning codigo",
    )
    assert cliente.get(RUTA, headers=sesion(TECNICO)).status_code == 200
    # Con sesion, el usuario_id es el de la sesion: Administracion no
    # sincroniza en nombre de otro.
    ajena = _sincronizar(cliente, RECEPCION, **sesion(ADMINISTRADOR))
    assert ajena.status_code == 403, ajena.text
    assert (
        len(ok(cliente.get(f"{RUTA}/syncs", headers=sesion(ADMINISTRADOR))))
        == 1
    )


# --- Modo sin origen ---------------------------------------------------------


def test_sin_origen_no_se_sincroniza(abrir, base):
    cliente, _ = abrir(productos_rt_origen="ninguno")
    respuesta = _sincronizar(cliente)
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["codigo"] == "PRODUCTOS_RT_NO_HABILITADO"
    assert _intentos(base) == []
    listado = _listar(cliente)
    assert (
        listado["copia"]["habilitado"]
        and not listado["copia"]["sincronizable"]
    )


def test_una_columna_opcional_faltante_avisa(abrir, archivos):
    cliente, _ = abrir()
    columnas = [c for c in COLUMNAS if c != "producto_repuesto"]
    filas = [
        [
            v
            for c, v in zip(COLUMNAS, fila, strict=True)
            if c != "producto_repuesto"
        ]
        for fila in ficticios.productos_base()
    ]
    archivos.productos.write_text(
        "\n".join(
            ",".join(str(v) for v in fila) for fila in [columnas, *filas]
        )
        + "\n",
        encoding="utf-8",
    )
    exitosa = ok(_sincronizar(cliente))
    assert any("producto_repuesto" in aviso for aviso in exitosa["avisos"])
    assert ok(cliente.get(f"{RUTA}/900001"))["producto"]["repuesto"] is None


def test_un_producto_nuevo_en_el_origen_aparece(abrir, archivos):
    cliente, _ = abrir()
    ok(_sincronizar(cliente))
    archivos.escribir(
        [
            *ficticios.productos_base(),
            producto("900099", imei=imei_ficticio(99), sede="RMA"),
        ]
    )
    contadores = ok(_sincronizar(cliente))["contadores"]
    assert contadores["nuevos"] == 1 and contadores["en_reparacion"] == 15
    assert "900099" in _ids(_listar(cliente, sede=["RMA"]))


# --- Correcciones del QA de la etapa 1 ---------------------------------------


def test_la_normalizacion_del_imei_en_sql_es_la_de_python(base):
    """QA, menor 2: todo caracter que ``str.split()`` toma como espacio lo
    quita tambien el SQL de las coincidencias (y nada mas)."""
    from app.domain.identidad import normalizar
    from app.storage.postgres.productos_rt import _COINCIDENCIAS

    sql = _COINCIDENCIAS.sql
    inicio = sql.index("regexp_replace(coalesce(o.equipo_imei, ''), ") + len(
        "regexp_replace(coalesce(o.equipo_imei, ''), "
    )
    patron = sql[inicio : sql.index(", '', 'g')", inicio)]
    espacios = [chr(c) for c in range(0x3001) if chr(c).isspace()]
    for caracter in [*espacios, "-", ".", "​", "a"]:
        valor = f"35999{caracter}9000000224"
        obtenido = _sql(
            base,
            f"select upper(regexp_replace(%s, {patron}, '', 'g'))",
            (valor,),
        )[0][0]
        assert obtenido == normalizar(valor), hex(ord(caracter))


def test_coincidencia_por_imei_con_espacio_duro(abrir):
    cliente, _ = abrir()
    ok(_sincronizar(cliente))
    imei = ficticios.IMEI_CON_ORDEN
    orden = _crear_orden_cliente(cliente, f"{imei[:5]} {imei[5:]}")
    ficha = ok(cliente.get(f"{RUTA}/{ficticios.ID_CON_REFERENCIA}"))[
        "producto"
    ]
    assert [
        (c["orden_id"], c["criterios"])
        for c in ficha["coincidencias_sugeridas"]
    ] == [(orden, ["IMEI"])]


def test_sin_sede_tiene_su_aviso(abrir, archivos):
    cliente, _ = abrir()
    archivos.escribir(
        [
            *ficticios.productos_base(),
            producto("900070", imei=imei_ficticio(70), sede=""),
        ]
    )
    exitosa = ok(_sincronizar(cliente))
    assert any("no tienen sede" in a for a in exitosa["avisos"])
    p = ok(cliente.get(f"{RUTA}/900070"))["producto"]
    assert p["sede"] is None and p["avisos"] == ["SIN_SEDE"]
    assert _ids(_listar(cliente, sede=[""])) == ["900070"]
    sedes = {s["sede"]: s for s in _listar(cliente)["sedes"]}
    assert sedes[None]["cantidad"] == 1 and not sedes[None]["confirmada"]


def test_una_hoja_sin_filas_se_rechaza_con_una_copia_chica(
    abrir, base, archivos
):
    cliente, _ = abrir()
    archivos.escribir(ficticios.productos_base()[:2])
    ok(_sincronizar(cliente))
    antes = _huella(base)
    archivos.escribir([])
    respuesta = _sincronizar(cliente)
    assert respuesta.status_code == 409, respuesta.text
    assert (
        respuesta.json()["error"]["codigo"] == "PRODUCTOS_RT_ORIGEN_INVALIDO"
    )
    assert _huella(base) == antes
    assert _listar(cliente)["total"] == 2
