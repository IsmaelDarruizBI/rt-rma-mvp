# ruff: noqa: E501  (SQL)
"""Configuracion v2, CFG-02 y CFG-03: permisos con sesion real (JWT) sobre
PostgreSQL.

* Toda ruta salvo ``/health`` exige sesion (401).
* Toda ruta con permiso en la API (``tests/test_matriz_permisos.py``)
  responde 403 a quien no lo tiene y deja pasar a quien si: se configura
  cada permiso solo para Administracion y se prueba con el Tecnico.
* Los permisos operativos se delegan desde Configuracion y rigen desde el
  pedido siguiente: Recepcion administra insumos sin precio; el precio
  exige ``PRECIOS_GESTIONAR``; la auditoria de una entidad la ve quien la
  administra y la completa, solo Administracion.
* Las dependencias: la API rechaza dejar una accion sin su consulta.
* El alias ``COMPRAS_GESTIONAR`` para el frontend publicado.
* La migracion ``20261120000200`` copia lo configurado de
  ``COMPRAS_GESTIONAR`` a los permisos nuevos sin borrar la fila anterior.
"""

import os
import re
import time
import uuid
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
from app.main import create_app  # noqa: E402
from app.services import permisos  # noqa: E402
from tests.fixtures.api_salidas import (  # noqa: E402
    ADMINISTRADOR,
    COORDINADOR,
    RECEPCION,
    TECNICO,
)
from tests.postgres.base_local import (  # noqa: E402
    VARIABLE,
    archivos_sql,
    borrar_base,
    clonar_base,
    crear_base,
    url_admin_local,
)
from tests.test_matriz_permisos import API, MATRIZ, PUBLICA  # noqa: E402

pytestmark = pytest.mark.postgres

ROL = "rma_api_prueba"
PROYECTO = "https://proyecto-prueba.supabase.co"
CLAVE = ec.generate_private_key(ec.SECP256R1())
MIGRACION = "20261120000200_permisos_operativos.sql"


def _admin() -> str:
    url = os.environ.get(VARIABLE)
    if not url:
        pytest.skip(f"{VARIABLE} no esta definida: sin PostgreSQL local.")
    return url_admin_local(url)


def _como_rol(url: str) -> str:
    partes = urlsplit(url)
    return urlunsplit(
        partes._replace(netloc=f"{ROL}@{partes.hostname}:{partes.port}")
    )


def _sql(base, sentencia, parametros=()):
    with psycopg.connect(base, autocommit=True) as conexion:
        cursor = conexion.execute(sentencia, parametros)
        return cursor.fetchall() if cursor.description else []


@pytest.fixture(scope="module")
def plantilla():
    admin = _admin()
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


@pytest.fixture
def api(base, tmp_path):
    """La API con PostgreSQL y sesion real; ``sesion(codigo)`` da las
    cabeceras de ese usuario."""
    ajustes = Settings(
        _env_file=None,
        data_dir=tmp_path,
        fotos_dir=tmp_path / "fotos",
        persistencia="postgres",
        database_url=_como_rol(base),
        auth_modo="supabase",
        auth_supabase_url=PROYECTO,
    )
    app = create_app(ajustes)
    identidades = {}
    for codigo in (RECEPCION, COORDINADOR, TECNICO, ADMINISTRADOR):
        identidades[codigo] = str(uuid.uuid4())
        _sql(
            base,
            "update rma.usuario set auth_user_id = %s where codigo = %s",
            (identidades[codigo], codigo),
        )
    with TestClient(app, raise_server_exceptions=False) as cliente:
        app.state.autenticacion = Autenticacion(
            VerificadorDeTokens(
                parametros_de(ajustes), lambda _: CLAVE.public_key()
            )
        )

        def sesion(codigo):
            return {"Authorization": f"Bearer {_token(identidades[codigo])}"}

        yield cliente, sesion


def _llamar(cliente, metodo, ruta, **cabeceras):
    url = re.sub(r"\{[^}]+\}", "X-1", ruta)
    if metodo == "GET":
        return cliente.get(url, headers=cabeceras)
    return cliente.request(metodo, url, json={}, headers=cabeceras)


def test_toda_ruta_salvo_health_exige_sesion(api):
    cliente, _ = api
    for (metodo, ruta), clase in MATRIZ.items():
        respuesta = _llamar(cliente, metodo, ruta)
        if clase == PUBLICA:
            assert respuesta.status_code == 200, (metodo, ruta)
        else:
            assert respuesta.status_code == 401, (metodo, ruta, respuesta.text)


def test_cada_permiso_de_la_api_corta_con_403(api, base):
    cliente, sesion = api
    # Cada permiso de la API, solo para Administracion: el Tecnico no tiene
    # ninguno y Administracion los tiene todos.
    codigos = sorted(
        {
            c
            for clase in MATRIZ.values()
            if isinstance(clase, API)
            for c in clase
        }
    )
    for codigo in codigos:
        if permisos.REGISTRO[codigo].configurable:
            _sql(
                base,
                "insert into rma.permiso (codigo, roles) values (%s, array['ADMINISTRADOR'])"
                " on conflict (codigo) do update set roles = excluded.roles",
                (codigo,),
            )
    for (metodo, ruta), clase in MATRIZ.items():
        if not isinstance(clase, API):
            continue
        negada = _llamar(cliente, metodo, ruta, **sesion(TECNICO))
        assert negada.status_code == 403, (metodo, ruta, negada.text)
        assert negada.json()["error"]["codigo"] == "ROL_NO_AUTORIZADO"
        permitida = _llamar(cliente, metodo, ruta, **sesion(ADMINISTRADOR))
        assert permitida.status_code != 403, (metodo, ruta, permitida.text)
        assert permitida.status_code < 500, (metodo, ruta, permitida.text)


def _configurar(cliente, sesion, codigo, roles):
    return cliente.put(
        f"/api/admin/permissions/{codigo}",
        json={"usuario_id": ADMINISTRADOR, "roles": roles},
        headers=sesion(ADMINISTRADOR),
    )


def test_administracion_delega_insumos_y_el_precio_queda_aparte(api):
    cliente, sesion = api
    recepcion = sesion(RECEPCION)
    alta = {
        "usuario_id": RECEPCION,
        "nombre": "Flex de carga",
        "unidad": "unidad",
    }
    # D2: por defecto Recepcion no administra insumos.
    assert (
        cliente.get("/api/admin/supplies", headers=recepcion).status_code
        == 403
    )
    assert (
        cliente.post(
            "/api/admin/supplies", json=alta, headers=recepcion
        ).status_code
        == 403
    )
    configurado = _configurar(
        cliente, sesion, "INSUMO_GESTIONAR", ["ADMINISTRADOR", "RECEPCION"]
    )
    assert configurado.status_code == 200, configurado.text
    # Rige desde el pedido siguiente.
    assert (
        cliente.get("/api/admin/supplies", headers=recepcion).status_code
        == 200
    )
    creado = cliente.post("/api/admin/supplies", json=alta, headers=recepcion)
    assert creado.status_code == 200, creado.text
    clave = creado.json()["id"]
    # D3: el precio exige PRECIOS_GESTIONAR (el servicio lo controla).
    con_precio = cliente.put(
        f"/api/admin/supplies/{clave}",
        json={**alta, "precio": "1500"},
        headers=recepcion,
    )
    assert con_precio.status_code == 409, con_precio.text
    assert (
        _configurar(
            cliente,
            sesion,
            "PRECIOS_GESTIONAR",
            ["ADMINISTRADOR", "RECEPCION"],
        ).status_code
        == 200
    )
    assert (
        cliente.put(
            f"/api/admin/supplies/{clave}",
            json={**alta, "precio": "1500"},
            headers=recepcion,
        ).status_code
        == 200
    )
    # La auditoria de insumos la ve quien los administra; la completa no.
    historial = cliente.get(
        "/api/admin/config-changes",
        params={"entidad": "INSUMO", "clave": clave},
        headers=recepcion,
    )
    assert historial.status_code == 200, historial.text
    assert {c["campo"] for c in historial.json()} >= {"nombre", "precio"}
    assert (
        cliente.get("/api/admin/config-changes", headers=recepcion).status_code
        == 403
    )
    assert (
        cliente.get(
            "/api/admin/config-changes",
            params={"entidad": "PERMISO"},
            headers=recepcion,
        ).status_code
        == 403
    )
    assert (
        cliente.get(
            "/api/admin/config-changes", headers=sesion(ADMINISTRADOR)
        ).status_code
        == 200
    )
    # Lo sensible sigue siendo de Administracion.
    for ruta in (
        "/api/admin/users",
        "/api/admin/permissions",
        "/api/admin/parameters",
    ):
        assert cliente.get(ruta, headers=recepcion).status_code == 403, ruta


def test_las_dependencias_y_los_permisos_fijos_se_validan_en_la_api(api):
    cliente, sesion = api
    sin_consulta = _configurar(
        cliente, sesion, "OC_CREAR", ["ADMINISTRADOR", "TECNICO"]
    )
    assert sin_consulta.status_code == 409
    assert "COMPRAS_CONSULTAR" in sin_consulta.json()["error"]["mensaje"]
    quitar = _configurar(
        cliente, sesion, "COMPRAS_CONSULTAR", ["ADMINISTRADOR"]
    )
    assert quitar.status_code == 409
    vacio = _configurar(cliente, sesion, "DESCUENTO", [])
    assert vacio.status_code == 409
    fijo = _configurar(
        cliente, sesion, "ROLES_ADMINISTRAR", ["ADMINISTRADOR", "RECEPCION"]
    )
    assert fijo.status_code == 409


def test_el_alias_de_compras_llega_al_frontend_publicado(api):
    cliente, sesion = api
    for codigo, esperado in ((RECEPCION, True), (TECNICO, False)):
        respuesta = cliente.get("/api/me", headers=sesion(codigo))
        assert respuesta.status_code == 200, respuesta.text
        permisos_usuario = respuesta.json()["permisos"]
        assert ("COMPRAS_GESTIONAR" in permisos_usuario) is esperado
        assert ("OC_CREAR" in permisos_usuario) is esperado


# --- Migracion de los permisos de Compras ------------------------------------


def _base_anterior(admin: str) -> str:
    anteriores = [
        a
        for a in archivos_sql()
        if "migrations" in a.parts and a.name < MIGRACION
    ]
    return crear_base(admin, anteriores)


def _migracion() -> str:
    archivo = next(a for a in archivos_sql() if a.name == MIGRACION)
    return archivo.read_text(encoding="utf-8")


def test_la_migracion_copia_lo_configurado_de_compras_gestionar():
    admin = _admin()
    url = _base_anterior(admin)
    try:
        with psycopg.connect(url, autocommit=True) as conexion:
            usuario = conexion.execute(
                "insert into rma.usuario (codigo, nombre) values ('ADMIN-X', 'Admin') returning id"
            ).fetchone()[0]
            conexion.execute(
                "insert into rma.permiso (codigo, roles) values"
                " ('COMPRAS_GESTIONAR', array['ADMINISTRADOR', 'COORDINADOR_RMA'])"
            )
            conexion.execute(
                "insert into rma.cambio_configuracion (entidad, clave, campo, valor_anterior,"
                " valor_nuevo, usuario_id, registrado_en) values ('PERMISO', 'COMPRAS_GESTIONAR',"
                " 'roles', 'x', 'ADMINISTRADOR, COORDINADOR_RMA', %s, now())",
                (usuario,),
            )
            # Un permiso nuevo ya configurado no se pisa.
            conexion.execute(
                "insert into rma.permiso (codigo, roles) values ('OC_CANCELAR', array['ADMINISTRADOR'])"
            )
            conexion.execute(_migracion())
            filas = dict(
                conexion.execute(
                    "select codigo, roles from rma.permiso"
                ).fetchall()
            )
            for codigo in (
                "COMPRA_SOLICITAR",
                "OC_CREAR",
                "OC_CONFIRMAR",
                "COMPRA_RECIBIR",
            ):
                assert filas[codigo] == ["ADMINISTRADOR", "COORDINADOR_RMA"], (
                    codigo
                )
            assert filas["OC_CANCELAR"] == ["ADMINISTRADOR"]
            # La fila anterior queda para un backend anterior.
            assert filas["COMPRAS_GESTIONAR"] == [
                "ADMINISTRADOR",
                "COORDINADOR_RMA",
            ]
            auditados = conexion.execute(
                "select clave from rma.cambio_configuracion"
                " where entidad = 'PERMISO' and valor_nuevo like '%%copiado%%' order by clave"
            ).fetchall()
            assert [a[0] for a in auditados] == [
                "COMPRA_RECIBIR",
                "COMPRA_SOLICITAR",
                "OC_CONFIRMAR",
                "OC_CREAR",
            ]
            # Idempotente.
            conexion.execute(_migracion())
            assert (
                conexion.execute(
                    "select count(*) from rma.cambio_configuracion where valor_nuevo like '%%copiado%%'"
                ).fetchone()[0]
                == 4
            )
    finally:
        borrar_base(admin, urlsplit(url).path.lstrip("/"))


def test_sin_configuracion_previa_la_migracion_no_agrega_filas():
    admin = _admin()
    url = _base_anterior(admin)
    try:
        with psycopg.connect(url, autocommit=True) as conexion:
            conexion.execute(_migracion())
            assert (
                conexion.execute(
                    "select count(*) from rma.permiso"
                ).fetchone()[0]
                == 0
            )
    finally:
        borrar_base(admin, urlsplit(url).path.lstrip("/"))
