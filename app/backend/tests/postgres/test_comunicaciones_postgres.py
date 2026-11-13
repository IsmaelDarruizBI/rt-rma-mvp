"""Comunicaciones y consentimiento sobre PostgreSQL (DEC-MI-08).

Con ``20261113000600_comunicaciones.sql``: plantillas administradas con
auditoria, intentos y confirmaciones inmutables, y el historial de
consentimiento; un mensaje comercial exige el consentimiento expreso.
"""

from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.storage.postgres.consentimientos import (  # noqa: E402
    PostgresConsentimientosRepository,
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
def cliente_com(api):
    app, cliente = api
    contexto = app.state.contexto
    unidad = contexto.unidad_de_trabajo
    app.state.contexto = replace(
        contexto,
        operativa=PostgresConfiguracionOperativa(unidad),
        consentimientos=PostgresConsentimientosRepository(unidad),
    )
    return cliente


def _consentir(cliente, cliente_id, finalidad, otorgado):
    return cliente.post(
        f"/api/clients/{cliente_id}/consents",
        json={
            "usuario_id": f.RECEPCION,
            "finalidad": finalidad,
            "otorgado": otorgado,
            "origen": "Firmado en el mostrador",
        },
    )


def test_plantilla_comercial_exige_consentimiento(cliente_com, base):
    cliente = cliente_com
    datos = f.ok(cliente.get("/api/admin/message-templates"))
    assert datos["editable"] is True
    assert len(datos["plantillas"]) == 5
    assert "Variables desconocidas" in f.conflicto(
        cliente.post(
            "/api/admin/message-templates",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "codigo": "PROMO",
                "nombre": "Promocion",
                "finalidad": "COMERCIAL",
                "texto": "Hola {cliente}, {descuento}!",
            },
        )
    )
    f.ok(
        cliente.post(
            "/api/admin/message-templates",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "codigo": "PROMO",
                "nombre": "Promocion",
                "finalidad": "COMERCIAL",
                "texto": "Hola {cliente}! Tenemos fundas para tu {equipo}.",
            },
        )
    )
    f.conflicto(
        cliente.put(
            "/api/admin/message-templates/PROMO",
            json={
                "usuario_id": f.RECEPCION,
                "nombre": "Promocion",
                "finalidad": "COMERCIAL",
                "texto": "x",
            },
        )
    )

    orden_id = f.definida(cliente, f.BATERIA)
    cliente_id = f.ok(cliente.get(f"/api/orders/{orden_id}"))["cliente"]["id"]
    preparado = f.ok(
        cliente.get(f"/api/orders/{orden_id}/messages/prepare?plantilla=PROMO")
    )
    assert "consentimiento expreso" in preparado["impedimento"]
    intento = {
        "usuario_id": f.RECEPCION,
        "plantilla_codigo": "PROMO",
        "mensaje": preparado["mensaje"],
    }
    assert "consentimiento expreso" in f.conflicto(
        cliente.post(f"/api/orders/{orden_id}/messages", json=intento)
    )
    f.ok(_consentir(cliente, cliente_id, "COMERCIAL", True))
    f.ok(cliente.post(f"/api/orders/{orden_id}/messages", json=intento))
    # Revocado: ya no.
    estado = f.ok(_consentir(cliente, cliente_id, "COMERCIAL", False))
    assert estado["vigentes"]["COMERCIAL"] is False
    f.conflicto(cliente.post(f"/api/orders/{orden_id}/messages", json=intento))

    assert _sql(
        base,
        """
        select k.codigo, c.finalidad, c.otorgado, u.codigo
          from rma.consentimiento_comunicacion c
          join rma.cliente k on k.id = c.cliente_id
          join rma.usuario u on u.id = c.usuario_id
         order by c.registrado_en
        """,
    ) == [
        (cliente_id, "COMERCIAL", True, f.RECEPCION),
        (cliente_id, "COMERCIAL", False, f.RECEPCION),
    ]
    auditoria = _sql(
        base,
        """
        select clave, campo, valor_nuevo from rma.cambio_configuracion
         where entidad = 'PLANTILLA' order by id
        """,
    )
    assert ("PROMO", "finalidad", "COMERCIAL") in auditoria


def test_intento_y_confirmacion_se_guardan_inmutables(cliente_com, base):
    cliente = cliente_com
    orden_id = f.definida(cliente, f.BATERIA)
    for mensaje in ("Primero", "Segundo"):
        f.ok(
            cliente.post(
                f"/api/orders/{orden_id}/messages",
                json={
                    "usuario_id": f.RECEPCION,
                    "plantilla_codigo": "INGRESO",
                    "mensaje": mensaje,
                },
            )
        )
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/messages/COM-002/confirm",
            json={
                "usuario_id": f.RECEPCION,
                "enviado": False,
                "nota": "No tenia WhatsApp.",
            },
        )
    )
    assert [
        (
            c["id"],
            c["mensaje"],
            c["confirmacion"] and c["confirmacion"]["enviado"],
        )
        for c in orden["comunicaciones"]
    ] == [("COM-001", "Primero", None), ("COM-002", "Segundo", False)]
    # Releida de la base, igual.
    assert (
        f.ok(cliente.get(f"/api/orders/{orden_id}"))["comunicaciones"]
        == (orden["comunicaciones"])
    )
    assert _sql(
        base,
        """
        select c.codigo, k.enviado, k.nota
          from rma.comunicacion_cliente c
          left join rma.comunicacion_confirmacion k on k.comunicacion_id = c.id
         order by c.posicion
        """,
    ) == [("COM-001", None, None), ("COM-002", False, "No tenia WhatsApp.")]
    for sentencia in (
        "update rma.comunicacion_cliente set mensaje = 'x'",
        "delete from rma.comunicacion_confirmacion",
        "update rma.comunicacion_confirmacion set enviado = true",
    ):
        with pytest.raises(psycopg.Error):
            _sql(base, sentencia)
    assert _sql(base, "select count(*) from rma.verificar_integridad()") == [
        (0,)
    ]
