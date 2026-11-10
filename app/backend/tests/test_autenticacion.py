"""Autenticacion con Supabase Auth y autorizacion en FastAPI.

Los tokens se firman aca con una clave ES256 propia (la del proyecto
Supabase nunca se usa en tests); el verificador recibe su clave publica
en lugar de descargar el JWKS. Persistencia JSON: el vinculo con la
identidad es el campo ``auth_user_id`` de ``usuarios.json``.
"""

import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.api.seguridad import Autenticacion
from app.core.autenticacion import (
    ConfiguracionAutenticacionError,
    VerificadorDeTokens,
    exigir_modo_seguro,
    parametros_de,
)
from app.core.config import Settings
from app.main import construir_autenticacion, create_app
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    COORDINADOR,
    INSUMO_BATERIA,
    RECEPCION,
    TECNICO,
    crear,
    sembrar,
)

PROYECTO = "https://proyecto-prueba.supabase.co"
EMISOR = f"{PROYECTO}/auth/v1"
CLAVE = ec.generate_private_key(ec.SECP256R1())
OTRA_CLAVE = ec.generate_private_key(ec.SECP256R1())

IDENTIDAD = {
    RECEPCION: str(uuid.uuid4()),
    COORDINADOR: str(uuid.uuid4()),
    TECNICO: str(uuid.uuid4()),
    ADMINISTRADOR: str(uuid.uuid4()),
}
INACTIVO = "RECEP-099"
IDENTIDAD_INACTIVO = str(uuid.uuid4())
SIN_VINCULO = str(uuid.uuid4())


def token(
    identidad: str,
    *,
    clave=CLAVE,
    algoritmo: str = "ES256",
    vence_en: int = 3600,
    **cambios,
) -> str:
    ahora = int(time.time())
    datos = {
        "sub": identidad,
        "iss": EMISOR,
        "aud": "authenticated",
        "role": "authenticated",
        "iat": ahora,
        "exp": ahora + vence_en,
        "email": "persona@ejemplo.com",
    }
    datos.update(cambios)
    datos = {k: v for k, v in datos.items() if v is not None}
    return jwt.encode(
        datos, clave, algorithm=algoritmo, headers={"kid": "prueba"}
    )


def sesion(usuario_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(IDENTIDAD[usuario_id])}"}


def _settings(directorio, **cambios) -> Settings:
    datos = {"auth_modo": "supabase", "auth_supabase_url": PROYECTO}
    datos.update(cambios)
    return Settings(data_dir=directorio, **datos)


@pytest.fixture
def app_supabase(tmp_path):
    sembrar(tmp_path)
    ruta = tmp_path / "catalogs" / "usuarios.json"
    usuarios = json.loads(ruta.read_text("utf-8"))
    for usuario in usuarios:
        if usuario["id"] in IDENTIDAD:
            usuario["auth_user_id"] = IDENTIDAD[usuario["id"]]
    usuarios.append(
        {
            "id": INACTIVO,
            "nombre": "Recepcion Inactiva",
            "rol": "RECEPCION",
            "activo": False,
            "auth_user_id": IDENTIDAD_INACTIVO,
        }
    )
    ruta.write_text(json.dumps(usuarios), "utf-8")
    settings = _settings(tmp_path)
    aplicacion = create_app(settings)
    # La clave publica de prueba en lugar del JWKS del proyecto.
    aplicacion.state.autenticacion = Autenticacion(
        VerificadorDeTokens(
            parametros_de(settings), lambda _: CLAVE.public_key()
        ),
    )
    return aplicacion


@pytest.fixture
def cliente(app_supabase):
    return TestClient(app_supabase)


def _error(respuesta, estado: int, codigo: str) -> None:
    assert respuesta.status_code == estado, respuesta.text
    assert respuesta.json()["error"]["codigo"] == codigo


# --- 401: sin sesion valida ----------------------------------------------


def test_health_es_publico_y_el_resto_exige_sesion(cliente):
    assert cliente.get("/health").status_code == 200
    for ruta in (
        "/api/orders",
        "/api/catalogs/users",
        "/api/inventory",
        f"/api/work/inbox?usuario_id={RECEPCION}",
        "/api/me",
    ):
        respuesta = cliente.get(ruta)
        _error(respuesta, 401, "NO_AUTENTICADO")
        assert respuesta.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "encabezado",
    [
        "Bearer",
        "Basic dXNlcjpwYXNz",
        "Bearer no-es-un-jwt",
        "Bearer " + token(IDENTIDAD[RECEPCION], clave=OTRA_CLAVE),
        "Bearer " + token(IDENTIDAD[RECEPCION], iss="https://otro/auth/v1"),
        "Bearer " + token(IDENTIDAD[RECEPCION], aud="otra"),
        "Bearer " + token(IDENTIDAD[RECEPCION], role="anon"),
        "Bearer " + token(IDENTIDAD[RECEPCION], exp=None),
        "Bearer " + token(IDENTIDAD[RECEPCION], sub=None),
        "Bearer "
        + token(IDENTIDAD[RECEPCION], clave="secreto", algoritmo="HS256"),
        "Bearer " + token(IDENTIDAD[RECEPCION], vence_en=-120),
    ],
    ids=[
        "sin-token",
        "otro-esquema",
        "basura",
        "otra-firma",
        "otro-emisor",
        "otra-audiencia",
        "rol-anon",
        "sin-exp",
        "sin-sub",
        "hs256",
        "vencido",
    ],
)
def test_token_invalido_o_vencido_es_401(cliente, encabezado):
    respuesta = cliente.get(
        "/api/orders", headers={"Authorization": encabezado}
    )
    _error(respuesta, 401, "NO_AUTENTICADO")


def test_token_sin_firma_alg_none_es_401(cliente):
    sin_firma = jwt.encode(
        {"sub": IDENTIDAD[RECEPCION], "iss": EMISOR, "aud": "authenticated"},
        None,
        algorithm="none",
    )
    respuesta = cliente.get(
        "/api/orders", headers={"Authorization": f"Bearer {sin_firma}"}
    )
    _error(respuesta, 401, "NO_AUTENTICADO")


# --- 403: identidad sin usuario habilitado ------------------------------


def test_identidad_sin_usuario_de_rma_es_403(cliente):
    respuesta = cliente.get(
        "/api/orders",
        headers={"Authorization": f"Bearer {token(SIN_VINCULO)}"},
    )
    _error(respuesta, 403, "USUARIO_NO_HABILITADO")


def test_usuario_inactivo_es_403(cliente):
    respuesta = cliente.get(
        "/api/orders",
        headers={"Authorization": f"Bearer {token(IDENTIDAD_INACTIVO)}"},
    )
    _error(respuesta, 403, "USUARIO_INACTIVO")


# --- Sesion valida ---------------------------------------------------------


def test_me_devuelve_el_usuario_de_la_sesion(cliente):
    for usuario_id in IDENTIDAD:
        datos = cliente.get("/api/me", headers=sesion(usuario_id)).json()
        assert datos["id"] == usuario_id
        assert datos["activo"] is True


def test_recorrido_con_sesion_conserva_las_reglas(cliente):
    cliente.headers.update(sesion(RECEPCION))
    orden_id = crear(cliente)
    assert cliente.get(f"/api/orders/{orden_id}").status_code == 200
    # La regla de negocio sigue igual: Recepcion no prioriza (409, no 403).
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": RECEPCION, "prioridad": "ALTA"},
    )
    assert respuesta.status_code in (409, 422), respuesta.text


# --- Suplantacion por usuario_id ---------------------------------------------


def test_usuario_id_del_cuerpo_distinto_al_de_la_sesion_es_403(cliente):
    respuesta = cliente.post(
        "/api/orders",
        headers=sesion(RECEPCION),
        json={
            "usuario_id": ADMINISTRADOR,
            "cliente": {"nombre_apellido": "Cliente", "telefono": "341-1"},
            "equipo": {"marca": "Apple", "modelo": "iPhone 14"},
        },
    )
    _error(respuesta, 403, "IDENTIDAD_NO_COINCIDE")


def test_usuario_id_de_la_consulta_distinto_al_de_la_sesion_es_403(cliente):
    respuesta = cliente.get(
        f"/api/work/inbox?usuario_id={TECNICO}", headers=sesion(RECEPCION)
    )
    _error(respuesta, 403, "IDENTIDAD_NO_COINCIDE")
    propia = cliente.get(
        f"/api/work/inbox?usuario_id={RECEPCION}", headers=sesion(RECEPCION)
    )
    assert propia.status_code == 200, propia.text


def test_usuario_id_repetido_en_la_consulta_no_esquiva_el_control(cliente):
    respuesta = cliente.get(
        f"/api/work/inbox?usuario_id={RECEPCION}&usuario_id={TECNICO}",
        headers=sesion(RECEPCION),
    )
    _error(respuesta, 403, "IDENTIDAD_NO_COINCIDE")


# --- Rutas administrativas por rol -------------------------------------------


def _ingreso(cliente, usuario_id):
    return cliente.post(
        f"/api/inventory/{INSUMO_BATERIA}/receipts",
        headers=sesion(usuario_id),
        json={"usuario_id": usuario_id, "cantidad": "1", "motivo": "Compra"},
    )


def test_inventario_solo_gestion_de_stock(cliente):
    _error(_ingreso(cliente, TECNICO), 403, "ROL_NO_AUTORIZADO")
    _error(_ingreso(cliente, RECEPCION), 403, "ROL_NO_AUTORIZADO")
    assert _ingreso(cliente, COORDINADOR).status_code == 200
    ajuste = cliente.post(
        f"/api/inventory/{INSUMO_BATERIA}/adjustments",
        headers=sesion(TECNICO),
        json={"usuario_id": TECNICO, "diferencia": "1", "motivo": "Conteo"},
    )
    _error(ajuste, 403, "ROL_NO_AUTORIZADO")
    revalidar = cliente.post(
        "/api/inventory/revalidate-orders",
        headers=sesion(RECEPCION),
        json={"usuario_id": RECEPCION},
    )
    _error(revalidar, 403, "ROL_NO_AUTORIZADO")


@pytest.mark.parametrize(
    ("metodo", "ruta", "permitido"),
    [
        ("post", "/api/maintenance/photos/cleanup", ADMINISTRADOR),
        ("post", "/api/catalogs/equipment/sync", COORDINADOR),
        ("get", "/api/clients/lookup?dni=30111222", RECEPCION),
    ],
)
def test_rutas_administrativas_rechazan_otros_roles(
    cliente, metodo, ruta, permitido
):
    separador = "&" if "?" in ruta else "?"
    for usuario_id in IDENTIDAD:
        respuesta = getattr(cliente, metodo)(
            f"{ruta}{separador}usuario_id={usuario_id}",
            headers=sesion(usuario_id),
        )
        if usuario_id == permitido:
            assert respuesta.status_code != 403, respuesta.text
        elif respuesta.status_code == 403:
            assert respuesta.json()["error"]["codigo"] == "ROL_NO_AUTORIZADO"
    tecnico = getattr(cliente, metodo)(
        f"{ruta}{separador}usuario_id={TECNICO}", headers=sesion(TECNICO)
    )
    _error(tecnico, 403, "ROL_NO_AUTORIZADO")


# --- Modo demo y arranque ----------------------------------------------------


def test_modo_demo_no_cambia_la_api(tmp_path):
    sembrar(tmp_path)
    cliente = TestClient(create_app(Settings(data_dir=tmp_path)))
    assert cliente.get("/api/orders").status_code == 200
    _error(cliente.get("/api/me"), 403, "AUTENTICACION_DEMO")


@pytest.mark.parametrize(
    ("cambios", "entorno"),
    [
        ({}, {"K_SERVICE": "rt-rma-uat-api"}),
        ({"db_remoto_habilitado": True}, {}),
    ],
    ids=["cloud-run", "base-remota"],
)
def test_demo_no_arranca_en_uat(tmp_path, cambios, entorno):
    settings = Settings(data_dir=tmp_path, **cambios)
    with pytest.raises(ConfiguracionAutenticacionError, match="supabase"):
        exigir_modo_seguro(settings, entorno)


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"auth_supabase_url": None}, "RMA_AUTH_SUPABASE_URL"),
        ({"auth_supabase_url": "http://inseguro.supabase.co"}, "https"),
        ({"auth_algoritmos": ["HS256"]}, "asimetricos"),
        ({"auth_algoritmos": ["ES256", "none"]}, "asimetricos"),
    ],
)
def test_supabase_sin_configuracion_segura_no_arranca(
    tmp_path, cambios, mensaje
):
    with pytest.raises(ConfiguracionAutenticacionError, match=mensaje):
        construir_autenticacion(_settings(tmp_path, **cambios), {})


def test_supabase_en_cloud_run_arranca(tmp_path):
    autenticacion = construir_autenticacion(
        _settings(tmp_path), {"K_SERVICE": "rt-rma-uat-api"}
    )
    assert autenticacion.activa


def test_desactivar_corta_el_acceso_en_el_pedido_siguiente(cliente, tmp_path):
    """Sin memoria entre pedidos: la base manda en cada uno."""
    ruta = tmp_path / "catalogs" / "usuarios.json"
    assert (
        cliente.get("/api/orders", headers=sesion(TECNICO)).status_code == 200
    )
    usuarios = json.loads(ruta.read_text("utf-8"))
    for usuario in usuarios:
        if usuario["id"] == TECNICO:
            usuario["activo"] = False
    ruta.write_text(json.dumps(usuarios), "utf-8")
    _error(
        cliente.get("/api/orders", headers=sesion(TECNICO)),
        403,
        "USUARIO_INACTIVO",
    )
    # El rol tambien vale desde el pedido siguiente.
    for usuario in usuarios:
        if usuario["id"] == COORDINADOR:
            usuario["rol"] = "TECNICO"
    ruta.write_text(json.dumps(usuarios), "utf-8")
    _error(_ingreso(cliente, COORDINADOR), 403, "ROL_NO_AUTORIZADO")
