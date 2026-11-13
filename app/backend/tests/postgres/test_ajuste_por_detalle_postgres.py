"""Ajuste Comercial por Detalle sobre PostgreSQL (DEC-MI-03).

Con ``20261113000200_ajuste_por_detalle.sql``: el ajuste de un trabajo queda
en ``rma.descuento.detalle_id``, la relectura devuelve lo mismo y la vista
``rma.v_orden_saldo`` calcula el mismo total que la aplicacion (el de la
Orden sobre lo que queda despues de los trabajos, sin prorrateo).
"""

from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api


def _ajustar(cliente, orden_id, tipo, valor, detalle_id=None):
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/discount",
            json={
                "usuario_id": f.COORDINADOR,
                "tipo": tipo,
                "valor": valor,
                "motivo": "Acuerdo.",
                "detalle_id": detalle_id,
            },
        )
    )


def test_ajuste_por_detalle_se_guarda_y_la_vista_coincide(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    _ajustar(cliente, orden_id, "PORCENTAJE", "10", "DET-002")
    orden = _ajustar(cliente, orden_id, "IMPORTE", "5000")

    assert _sql(
        base,
        """
        select x.codigo, d.tipo, d.valor
        from rma.descuento d
        join rma.orden o on o.id = d.orden_id
        left join rma.detalle x on x.id = d.detalle_id
        where o.codigo = %s order by d.posicion
        """,
        (orden_id,),
    ) == [
        ("DET-002", "PORCENTAJE", Decimal("10.00")),
        (None, "IMPORTE", Decimal("5000.00")),
    ]
    ((total, aplicado, saldo),) = _sql(
        base,
        """
        select v.total, v.descuento_aplicado, v.saldo
        from rma.v_orden_saldo v join rma.orden o on o.id = v.orden_id
        where o.codigo = %s
        """,
        (orden_id,),
    )
    assert (total, aplicado, saldo) == (
        Decimal("120000.00"),
        Decimal("10000.00"),
        Decimal("120000.00"),
    )
    assert Decimal(orden["resumen"]["total"]) == total
    releida = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert releida == {k: v for k, v in orden.items() if k != "puede_entregar"}
    assert _sql(base, "select count(*) from rma.verificar_integridad()") == [
        (0,)
    ]
