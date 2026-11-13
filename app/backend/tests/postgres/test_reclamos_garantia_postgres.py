"""Reclamos de garantia rechazados sobre PostgreSQL (DEC-MI-02).

Con ``20261113000400_reclamos_garantia.sql``: el reclamo queda en
``rma.reclamo_garantia``, su continuacion se completa una sola vez y la
tabla no admite otra modificacion ni borrado.
"""

from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.storage.postgres.reclamos import PostgresReclamosRepository  # noqa: E402
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.fixtures import iteracion1 as it  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api


def test_reclamo_rechazado_y_continuacion_en_postgres(api, base):
    app, cliente = api
    contexto = app.state.contexto
    app.state.contexto = replace(
        contexto,
        reclamos=PostgresReclamosRepository(contexto.unidad_de_trabajo),
    )
    reloj = it.instalar_reloj(cliente)
    origen = it.entregada_hace(cliente, reloj, 200)

    respuesta = it.iniciar_garantia(cliente, origen)
    assert respuesta.status_code == 409, respuesta.text
    reclamo_id = respuesta.json()["error"]["reclamo_id"]

    continuado = f.ok(
        cliente.post(
            f"/api/warranty-claims/{reclamo_id}/continue",
            json={"usuario_id": f.RECEPCION, "confirmado": True},
        )
    )
    assert _sql(
        base,
        """
        select r.codigo, o.codigo, r.detalles, r.resultado, oc.codigo
        from rma.reclamo_garantia r
        join rma.orden o on o.id = r.orden_origen_id
        left join rma.orden oc on oc.id = r.orden_continuacion_id
        """,
    ) == [
        (reclamo_id, origen, ["DET-001"], "RECHAZADO", continuado["orden_id"])
    ]
    assert (
        f.ok(cliente.get(f"/api/warranty-claims/{reclamo_id}"))[
            "orden_continuacion_id"
        ]
        == continuado["orden_id"]
    )
    for sentencia in (
        "update rma.reclamo_garantia set motivo = 'x'",
        "update rma.reclamo_garantia set orden_continuacion_id = null,"
        " continuado_por = null, continuado_en = null",
        "delete from rma.reclamo_garantia",
    ):
        with pytest.raises(psycopg.Error):
            _sql(base, sentencia)
    assert _sql(base, "select count(*) from rma.verificar_integridad()") == [
        (0,)
    ]
