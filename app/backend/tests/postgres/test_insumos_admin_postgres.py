"""Alta y edicion de insumos sobre PostgreSQL (DEC-MI-13).

Administracion da de alta y edita insumos con auditoria; el stock de un
insumo nuevo empieza en cero y no se edita desde la configuracion.
"""

from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

from app.storage.postgres.catalogos import (  # noqa: E402
    PostgresCatalogosRepository,
)
from app.storage.postgres.operativa import (  # noqa: E402
    PostgresConfiguracionOperativa,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api


@pytest.fixture
def cliente_insumos(api):
    app, cliente = api
    contexto = app.state.contexto
    unidad = contexto.unidad_de_trabajo
    app.state.contexto = replace(
        contexto,
        catalogos=PostgresCatalogosRepository(unidad),
        operativa=PostgresConfiguracionOperativa(unidad),
    )
    return cliente


def test_alta_y_edicion_de_un_insumo_auditadas(cliente_insumos, base):
    cliente = cliente_insumos
    alta = {
        "usuario_id": f.ADMINISTRADOR,
        "clave": "INS-900",
        "codigo": "FLEX-A54",
        "nombre": "Flex de carga A54",
        "unidad": "unidad",
    }
    f.conflicto(
        cliente.post(
            "/api/admin/supplies", json={**alta, "usuario_id": f.RECEPCION}
        )
    )
    insumo = f.ok(cliente.post("/api/admin/supplies", json=alta))
    assert insumo["stock_fisico"] in ("0", 0, "0.000")
    assert "Ya existe" in f.conflicto(
        cliente.post("/api/admin/supplies", json=alta)
    )
    assert "codigo" in f.conflicto(
        cliente.post(
            "/api/admin/supplies",
            json={**alta, "clave": "INS-901"},
        )
    )
    f.ok(
        cliente.put(
            "/api/admin/supplies/INS-900",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "codigo": "FLEX-A54",
                "nombre": "Flex de carga Samsung A54",
                "unidad": "unidad",
                "activo": False,
            },
        )
    )
    listado = f.ok(cliente.get("/api/admin/supplies"))
    (editado,) = [i for i in listado["insumos"] if i["id"] == "INS-900"]
    assert (editado["nombre"], editado["activo"]) == (
        "Flex de carga Samsung A54",
        False,
    )
    assert _sql(
        base,
        "select stock_fisico, stock_reservado from rma.insumo "
        "where clave = 'INS-900'",
    ) == [(0, 0)]
    auditoria = _sql(
        base,
        """
        select campo, valor_anterior, valor_nuevo
          from rma.cambio_configuracion
         where entidad = 'INSUMO' and clave = 'INS-900'
         order by id
        """,
    )
    assert ("nombre", None, "Flex de carga A54") in auditoria
    assert ("activo", "true", "false") in auditoria
    assert "no cambia" in f.conflicto(
        cliente.put(
            "/api/admin/supplies/INS-900",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "codigo": "OTRO",
                "nombre": "Flex",
            },
        )
    )
