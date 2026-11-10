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
