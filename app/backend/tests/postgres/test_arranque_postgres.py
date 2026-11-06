"""B4/B6: la app arranca sobre PostgreSQL local, sin modo mixto."""

import pytest

pytest.importorskip("psycopg_pool")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.storage.postgres.conexion import (  # noqa: E402
    ConfiguracionPersistenciaError,
)
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402

base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla


def _settings(url, tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        persistencia="postgres",
        database_url=url,
    )


def test_la_app_sirve_desde_postgres_y_cierra_su_pool(base, tmp_path):
    app = create_app(_settings(base, tmp_path))
    contexto = app.state.contexto
    assert contexto.acciones is not None and contexto.cerrar is not None
    with TestClient(app) as cliente:
        assert cliente.get("/health").json() == {"status": "ok"}
        assert cliente.get("/api/catalogs/repair-types").status_code == 200
    # Sin JSON de dominio: la base es la unica fuente.
    assert not (tmp_path / "ordenes").exists() or not list(
        (tmp_path / "ordenes").glob("*.json")
    )


def test_sin_base_no_arranca_ni_cae_a_json(tmp_path):
    with pytest.raises(ConfiguracionPersistenciaError, match="fallback"):
        create_app(
            _settings(
                "postgresql://postgres@127.0.0.1:1/rma_inexistente", tmp_path
            )
        )
