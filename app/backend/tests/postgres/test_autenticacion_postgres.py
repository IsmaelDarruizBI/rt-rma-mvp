"""Autenticacion sobre PostgreSQL: identidad por ``auth_user_id`` y claves
de idempotencia aisladas por identidad.

La Orden se prepara sin sesion (como en las demas pruebas) y despues se
activa el verificador con una clave ES256 de prueba.
"""

import time
import uuid
from dataclasses import replace

import pytest

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
from app.storage.postgres.acciones import (  # noqa: E402
    PostgresRegistroDeAcciones,
)
from app.storage.postgres.catalogos import (  # noqa: E402
    PostgresCatalogosRepository,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla

PROYECTO = "https://proyecto-prueba.supabase.co"
CLAVE = ec.generate_private_key(ec.SECP256R1())
IDENTIDAD = {
    f.RECEPCION: str(uuid.uuid4()),
    f.ADMINISTRADOR: str(uuid.uuid4()),
    f.TECNICO: str(uuid.uuid4()),
}


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


def _sesion(usuario_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(IDENTIDAD[usuario_id])}"}


@pytest.fixture
def api(armar, base, tmp_path):
    f.sembrar(tmp_path)
    settings = Settings(
        data_dir=tmp_path,
        auth_modo="supabase",
        auth_supabase_url=PROYECTO,
    )
    app = create_app(settings)
    repo, unidad = armar(pool_max=4)
    app.state.contexto = replace(
        app.state.contexto,
        ordenes=repo,
        catalogos=PostgresCatalogosRepository(unidad),
        unidad_de_trabajo=unidad,
        acciones=PostgresRegistroDeAcciones(unidad),
    )
    for codigo, identidad in IDENTIDAD.items():
        _sql(
            base,
            "update rma.usuario set auth_user_id = %s where codigo = %s "
            "returning codigo",
            (identidad, codigo),
        )
    verificador = Autenticacion(
        VerificadorDeTokens(
            parametros_de(settings), lambda _: CLAVE.public_key()
        ),
    )
    app.state.autenticacion = Autenticacion(None)
    with TestClient(app) as cliente:
        yield app, cliente, verificador


def _activar(app, verificador) -> None:
    app.state.autenticacion = verificador


def test_identidad_desde_auth_user_id(api):
    app, cliente, verificador = api
    _activar(app, verificador)
    me = cliente.get("/api/me", headers=_sesion(f.RECEPCION))
    assert me.status_code == 200, me.text
    assert me.json()["id"] == f.RECEPCION
    for sub in (str(uuid.uuid4()), "no-es-un-uuid"):
        respuesta = cliente.get(
            "/api/me", headers={"Authorization": f"Bearer {_token(sub)}"}
        )
        assert respuesta.status_code == 403, respuesta.text
        assert respuesta.json()["error"]["codigo"] == "USUARIO_NO_HABILITADO"


def _pagar(cliente, orden_id, usuario_id, clave):
    return cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={"usuario_id": usuario_id, "monto": "1000", "metodo": "EFECTIVO"},
        headers={"Idempotency-Key": clave, **_sesion(usuario_id)},
    )


def test_la_misma_clave_de_otro_usuario_no_reutiliza_su_respuesta(api, base):
    app, cliente, verificador = api
    orden_id = f.definida(cliente, f.BATERIA)
    _activar(app, verificador)

    primera = _pagar(cliente, orden_id, f.RECEPCION, "pago-compartido")
    assert primera.status_code == 200, primera.text
    otra = _pagar(cliente, orden_id, f.ADMINISTRADOR, "pago-compartido")
    assert otra.status_code == 200, otra.text
    # Cada identidad tiene su clave: dos pagos, no una respuesta repetida.
    assert _sql(base, "select count(*) from rma.pago") == [(2,)]
    assert _sql(
        base,
        "select u.codigo from rma.accion_usuario a "
        "join rma.usuario u on u.id = a.usuario_id "
        "where a.clave_idempotencia = 'pago-compartido' order by 1",
    ) == [(f.ADMINISTRADOR,), (f.RECEPCION,)]

    # Nadie recupera la respuesta de otro declarando su usuario_id.
    ajena = cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": f.RECEPCION,
            "monto": "1000",
            "metodo": "EFECTIVO",
        },
        headers={
            "Idempotency-Key": "pago-compartido",
            **_sesion(f.ADMINISTRADOR),
        },
    )
    assert ajena.status_code == 403, ajena.text
    assert ajena.json()["error"]["codigo"] == "IDENTIDAD_NO_COINCIDE"
    assert _sql(base, "select count(*) from rma.pago") == [(2,)]


def test_la_consulta_de_ordenes_es_un_permiso_configurable(api):
    """DC27B: por defecto la consulta queda como estaba (todos los roles);
    si Administracion la restringe, rige desde el pedido siguiente."""
    from app.storage.postgres.configuracion import (
        PostgresConfiguracionRepository,
    )

    app, cliente, verificador = api
    contexto = app.state.contexto
    app.state.contexto = replace(
        contexto,
        configuracion=PostgresConfiguracionRepository(
            contexto.unidad_de_trabajo
        ),
    )
    _activar(app, verificador)
    recepcion, admin = _sesion(f.RECEPCION), _sesion(f.ADMINISTRADOR)
    assert cliente.get("/api/orders", headers=recepcion).status_code == 200
    assert cliente.get("/api/inventory", headers=recepcion).status_code == 200

    respuesta = cliente.put(
        "/api/admin/permissions/ORDENES_CONSULTAR",
        json={"usuario_id": f.ADMINISTRADOR, "roles": ["ADMINISTRADOR"]},
        headers=admin,
    )
    assert respuesta.status_code == 200, respuesta.text
    negada = cliente.get("/api/orders", headers=recepcion)
    assert negada.status_code == 403, negada.text
    assert cliente.get("/api/orders", headers=admin).status_code == 200
    # El inventario es otro permiso: no cambio.
    assert cliente.get("/api/inventory", headers=recepcion).status_code == 200


def test_seguridad_de_roles_compras_y_configuracion(api, base):
    """Macroiteracion integral con sesion real: nadie se da permisos de
    administracion a si mismo ni actua en nombre de otro; compras, costos,
    roles, permisos y la copia del catalogo de Ventas (DC12) quedan para
    quien tiene el permiso; consultar no habilita escribir; nunca queda el
    sistema sin Administrador."""
    from app.storage.postgres.compras import PostgresComprasRepository
    from app.storage.postgres.configuracion import (
        PostgresConfiguracionRepository,
    )
    from app.storage.postgres.operativa import PostgresConfiguracionOperativa

    app, cliente, verificador = api
    contexto = app.state.contexto
    unidad = contexto.unidad_de_trabajo
    app.state.contexto = replace(
        contexto,
        configuracion=PostgresConfiguracionRepository(unidad),
        compras=PostgresComprasRepository(unidad),
        operativa=PostgresConfiguracionOperativa(unidad),
    )
    _activar(app, verificador)
    recepcion = _sesion(f.RECEPCION)
    tecnico = _sesion(f.TECNICO)
    admin = _sesion(f.ADMINISTRADOR)

    def codigo(respuesta) -> str:
        return respuesta.json()["error"]["codigo"]

    # 1. Darse permisos de administracion: rechazado (403) antes de ejecutar.
    propia = cliente.put(
        f"/api/admin/users/{f.RECEPCION}/roles",
        json={"usuario_id": f.RECEPCION, "roles": ["ADMINISTRADOR"]},
        headers=recepcion,
    )
    assert propia.status_code == 403, propia.text
    permiso = cliente.put(
        "/api/admin/permissions/COMPRAS_GESTIONAR",
        json={"usuario_id": f.TECNICO, "roles": ["TECNICO"]},
        headers=tecnico,
    )
    assert permiso.status_code == 403, permiso.text
    # ... ni declarando ser el Administrador en el cuerpo.
    suplantada = cliente.put(
        f"/api/admin/users/{f.RECEPCION}/roles",
        json={"usuario_id": f.ADMINISTRADOR, "roles": ["ADMINISTRADOR"]},
        headers=recepcion,
    )
    assert suplantada.status_code == 403
    assert codigo(suplantada) == "IDENTIDAD_NO_COINCIDE"
    roles = _sql(
        base,
        "select o.codigo from rma.usuario_rol r "
        "join rma.usuario u on u.id = r.usuario_id "
        "join rma.rol o on o.id = r.rol_id where u.codigo = %s",
        (f.RECEPCION,),
    )
    assert roles == [("RECEPCION",)]

    # 2. Configuracion y la copia del catalogo de Ventas: solo
    # Administracion.
    for metodo, ruta, cuerpo in (
        ("get", "/api/admin/checklist", None),
        ("get", "/api/admin/users", None),
        ("get", "/api/admin/permissions", None),
        ("get", "/api/admin/suppliers", None),
        ("post", "/api/admin/equipment-types/sync", {"usuario_id": f.TECNICO}),
        (
            "post",
            "/api/admin/checklist-questions",
            {
                "usuario_id": f.TECNICO,
                "tipo_equipo_id": "x",
                "texto": "x",
                "opciones": ["a", "b"],
            },
        ),
    ):
        respuesta = getattr(cliente, metodo)(
            ruta, headers=tecnico, **({"json": cuerpo} if cuerpo else {})
        )
        assert respuesta.status_code == 403, (ruta, respuesta.text)
    assert (
        cliente.get("/api/admin/checklist", headers=admin).status_code == 200
    )

    # 3. Compras y costos: el Tecnico no consulta ni gestiona.
    assert (
        cliente.get("/api/purchases/costs", headers=tecnico).status_code == 403
    )
    assert (
        cliente.get("/api/purchases/orders", headers=tecnico).status_code
        == 403
    )
    solicitud = {
        "usuario_id": f.TECNICO,
        "insumo_id": f.INSUMO_BATERIA,
        "cantidad": "1",
        "motivo": "x",
    }
    escrita = cliente.post(
        "/api/purchases/requests", json=solicitud, headers=tecnico
    )
    assert escrita.status_code in (403, 409), escrita.text
    assert _sql(base, "select count(*) from rma.solicitud_compra") == [(0,)]
    assert (
        cliente.get("/api/purchases/costs", headers=recepcion).status_code
        == 200
    )

    # 4. Consultar no habilita escribir: con COMPRAS_CONSULTAR el Tecnico
    # lee, pero sigue sin poder crear una solicitud.
    habilitada = cliente.put(
        "/api/admin/permissions/COMPRAS_CONSULTAR",
        json={
            "usuario_id": f.ADMINISTRADOR,
            "roles": [
                "RECEPCION",
                "COORDINADOR_RMA",
                "ADMINISTRADOR",
                "TECNICO",
            ],
        },
        headers=admin,
    )
    assert habilitada.status_code == 200, habilitada.text
    assert (
        cliente.get("/api/purchases/costs", headers=tecnico).status_code == 200
    )
    escrita = cliente.post(
        "/api/purchases/requests", json=solicitud, headers=tecnico
    )
    assert escrita.status_code in (403, 409), escrita.text
    assert _sql(base, "select count(*) from rma.solicitud_compra") == [(0,)]

    # 5. Nunca sin Administrador: el unico no puede quitarse el rol.
    sin_admin = cliente.put(
        f"/api/admin/users/{f.ADMINISTRADOR}/roles",
        json={"usuario_id": f.ADMINISTRADOR, "roles": ["RECEPCION"]},
        headers=admin,
    )
    assert sin_admin.status_code == 409, sin_admin.text
    assert "Administrador" in sin_admin.json()["error"]["mensaje"]
