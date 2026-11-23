"""Bloque 2 de ajustes funcionales (entrega) sobre PostgreSQL.

- DEC-AJ-04 (migracion ``20261123000100``): el check-in registrado en la
  misma confirmacion de la entrega deja el paso PROC-REP-269, que se guarda
  como "Check-in registrado" y se relee igual.
- DEC-AJ-03: la entrega sin aviso (250 y 265 en la misma operacion) se
  guarda y se relee igual.
- DEC-AJ-09 (P-05): quien retiro se guarda en ``rma.salida`` (titular u
  otra persona, con su telefono) y se relee igual.
- DEC-AJ-04: un solo comprobante de entrega, sin certificado aparte.
"""

import pytest

pytest.importorskip("psycopg_pool")

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


def _lista_y_pagada(cliente) -> str:
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    it.pagar(cliente, orden_id, "80000")
    return orden_id


def _salida(url, orden_id):
    return _sql(
        url,
        "select s.retira_nombre, s.retira_telefono, s.retira_vinculo, "
        "s.retira_identificacion from rma.salida s "
        "join rma.orden o on o.id = s.orden_id where o.codigo = %s",
        (orden_id,),
    )


def test_checkin_en_la_entrega_y_otra_persona_se_guardan(api, base):
    _, cliente = api
    orden_id = _lista_y_pagada(cliente)

    entregada = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={
                "usuario_id": f.RECEPCION,
                "checkin": True,
                "retira_otra_persona": True,
                "retira_nombre": "Ana",
                "retira_apellido": "Lopez",
                "retira_telefono": "341-555-0199",
            },
        )
    )

    assert f.ids(entregada)[-5:] == [
        "PROC-REP-250",
        "PROC-REP-269",
        "PROC-REP-265",
        "PROC-REP-280",
        "PROC-REP-270",
    ]
    leida = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert leida["historial"] == entregada["historial"]
    assert leida["entrega"] == entregada["entrega"]
    assert leida["entrega"]["retira_otra_persona"] is True
    assert leida["recepcion"]["registros_checkin"][0]["realizado"] is True
    assert _salida(base, orden_id) == [
        ("Ana Lopez", "341-555-0199", "TERCERO", None)
    ]
    # El paso 269 queda como "Check-in registrado".
    assert _sql(
        base,
        "select t.codigo from rma.evento_negocio e "
        "join rma.tipo_evento t on t.id = e.tipo_evento_id "
        "join rma.orden o on o.id = e.orden_id "
        "where o.codigo = %s and e.historial_referencia_id = 'PROC-REP-269'",
        (orden_id,),
    ) == [("EV-REP-033",)]
    tipos = [
        d["tipo"]
        for d in f.ok(cliente.get(f"/api/orders/{orden_id}/documents"))[
            "emitidos"
        ]
    ]
    assert tipos == ["COMPROBANTE_INGRESO", "COMPROBANTE_ENTREGA"]


def test_retira_el_titular_se_guarda(api, base):
    _, cliente = api
    orden_id = _lista_y_pagada(cliente)

    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": f.ADMINISTRADOR, "checkin": False},
        )
    )

    leida = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert leida["entrega"]["retira_otra_persona"] is False
    assert leida["entrega"]["telefono_receptor"] is None
    ((nombre, telefono, vinculo, identificacion),) = _salida(base, orden_id)
    assert (nombre, telefono, vinculo, identificacion) == (
        leida["cliente"]["nombre_apellido"],
        None,
        "TITULAR",
        None,
    )
