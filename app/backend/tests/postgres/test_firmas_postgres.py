"""Firmas de documentos sobre PostgreSQL (DEC-MI-06).

Con ``20261113000700_firmas_documentos.sql``: la firma referencia el
documento emitido, se registra tambien con la Orden entregada (sin tocar
la fila de la Orden, que esta cerrada) y no se modifica ni se borra.
"""

from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.storage.fotos import AlmacenFotosMemoria  # noqa: E402
from app.storage.postgres.firmas import PostgresFirmasRepository  # noqa: E402
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402
from tests.test_garantia_checkin import _lista  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


@pytest.fixture
def cliente_firmas(api):
    app, cliente = api
    contexto = app.state.contexto
    app.state.contexto = replace(
        contexto,
        fotos=AlmacenFotosMemoria(),
        firmas=PostgresFirmasRepository(contexto.unidad_de_trabajo),
    )
    return cliente


def test_firma_de_un_documento_con_la_orden_entregada(cliente_firmas, base):
    cliente = cliente_firmas
    orden_id = f.definida(cliente, f.BATERIA)
    _lista(cliente, orden_id, f.BATERIA)
    entregada = f.notificar_pagar_entregar(cliente, orden_id)
    documento = next(
        d
        for d in entregada["documentos_emitidos"]
        if d["tipo"] == "COMPROBANTE_ENTREGA"
    )
    (firma,) = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/documents/{documento['id']}/signatures",
            params={"usuario_id": f.RECEPCION, "forma": "FOTO_DOCUMENTO"},
            content=PNG,
            headers={"Content-Type": "image/png"},
        )
    )
    assert f.ok(cliente.get(f"/api/orders/{orden_id}/signatures")) == [firma]
    assert _sql(
        base,
        """
        select d.codigo, f.forma, u.codigo
          from rma.firma_documento f
          join rma.documento_emitido d on d.id = f.documento_id
          join rma.usuario u on u.id = f.usuario_id
        """,
    ) == [(documento["id"], "FOTO_DOCUMENTO", f.RECEPCION)]
    for sentencia in (
        "update rma.firma_documento set forma = 'PANTALLA'",
        "delete from rma.firma_documento",
    ):
        with pytest.raises(psycopg.Error):
            _sql(base, sentencia)
    assert _sql(base, "select count(*) from rma.verificar_integridad()") == [
        (0,)
    ]
