"""E8: la aplicacion funciona con los permisos minimos de ``rma_backend``.

En Supabase la API conecta con un rol de login miembro de ``rma_backend``
(``rma_api``), nunca como superusuario. Aca un rol de login local con esa
membresia corre los recorridos reales por HTTP: altas, recepcion, fotos,
reservas, consumo, pagos, descuentos, devoluciones, ingresos y ajustes,
idempotencia. Cualquier permiso faltante (incluido el UPDATE que exige un
``FOR UPDATE`` o un ``FOR NO KEY UPDATE``) haria fallar un comando.
"""

from urllib.parse import urlsplit, urlunsplit

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_bloque_a_postgres import _recorridos  # noqa: E402

base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla

ROL = "rma_api_prueba"


def _como_rol(url: str) -> str:
    partes = urlsplit(url)
    return urlunsplit(
        partes._replace(netloc=f"{ROL}@{partes.hostname}:{partes.port}")
    )


@pytest.fixture
def url_rma_backend(base):
    with psycopg.connect(base, autocommit=True) as admin:
        existe = admin.execute(
            "select 1 from pg_roles where rolname = %s", (ROL,)
        ).fetchone()
        if not existe:
            admin.execute(
                f"create role {ROL} login inherit in role rma_backend"
            )
        assert admin.execute(
            "select rolsuper from pg_roles where rolname = %s", (ROL,)
        ).fetchone() == (False,)
    return _como_rol(base)


def test_e8_los_recorridos_reales_con_rma_backend(url_rma_backend, tmp_path):
    f.sembrar(tmp_path)
    app = create_app(
        Settings(
            _env_file=None,
            data_dir=tmp_path,
            fotos_dir=tmp_path / "fotos",
            persistencia="postgres",
            database_url=url_rma_backend,
        )
    )
    with TestClient(app) as cliente:
        _recorridos(cliente)
        orden_id = f.crear(cliente)
        foto = cliente.post(
            f"/api/orders/{orden_id}/photos",
            params={"usuario_id": f.RECEPCION},
            content=b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\x00" * 200,
            headers={"Idempotency-Key": "foto-permisos"},
        )
        assert foto.status_code == 200, foto.text
    with psycopg.connect(url_rma_backend) as conexion:
        usuario = conexion.execute("select current_user").fetchone()[0]
        integridad = conexion.execute(
            "select * from rma.verificar_integridad()"
        ).fetchall()
    assert usuario == ROL and integridad == []


def test_e8_rma_backend_no_puede_borrar_ni_reescribir_historia(
    url_rma_backend,
):
    with psycopg.connect(url_rma_backend, autocommit=True) as conexion:
        for sentencia in (
            "delete from rma.orden",
            "delete from rma.movimiento_inventario",
            "update rma.pago set monto = 1",
            "update rma.insumo set stock_fisico = 99",
            "truncate rma.evento_negocio",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conexion.execute(sentencia)
