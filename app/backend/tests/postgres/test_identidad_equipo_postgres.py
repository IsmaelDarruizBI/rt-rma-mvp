"""Identidad del Equipo sobre PostgreSQL (DEC-MI-11).

Dos ingresos con la misma identidad comparten la fila de ``rma.equipo``; la
correccion de la vinculacion pasa la Orden a otra identidad y queda en
``rma.correccion_vinculo_equipo``, inmutable.
"""

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402
from tests.test_identidad_equipo import _ingresar  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api


def test_identidad_compartida_y_correccion_en_postgres(api, base):
    _, cliente = api
    primera = f.ok(_ingresar(cliente, imei="356111"))
    equipo_id = primera["equipo"]["id"]
    segunda = f.ok(_ingresar(cliente, id=equipo_id, imei="356111"))
    assert _sql(
        base,
        """
        select count(distinct o.equipo_id) from rma.orden o
         where o.codigo = any(%s)
        """,
        ([primera["id"], segunda["id"]],),
    ) == [(1,)]
    identificado = f.ok(
        cliente.get("/api/equipment/identify", params={"imei": "356111"})
    )
    assert identificado["candidatos"][0]["ordenes"] == [
        primera["id"],
        segunda["id"],
    ]

    orden = f.ok(
        cliente.post(
            f"/api/orders/{segunda['id']}/equipment-link",
            json={"usuario_id": f.RECEPCION, "motivo": "Otro equipo."},
        )
    )
    nuevo = orden["equipo"]["id"]
    assert (
        f.ok(cliente.get(f"/api/orders/{segunda['id']}"))[
            "correcciones_equipo"
        ]
        == orden["correcciones_equipo"]
    )
    assert [
        o["orden_id"]
        for o in f.ok(cliente.get(f"/api/equipment/{nuevo}/orders"))["ordenes"]
    ] == [segunda["id"]]
    assert _sql(
        base,
        """
        select equipo_anterior_codigo, equipo_nuevo_codigo, motivo
          from rma.correccion_vinculo_equipo
        """,
    ) == [(equipo_id, nuevo, "Otro equipo.")]
    with pytest.raises(psycopg.Error):
        _sql(base, "update rma.correccion_vinculo_equipo set motivo = 'x'")
    assert _sql(base, "select count(*) from rma.verificar_integridad()") == [
        (0,)
    ]
