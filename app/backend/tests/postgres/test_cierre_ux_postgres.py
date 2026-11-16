"""Cierre de la iteracion de UX sobre PostgreSQL (migracion
``20261116000200``).

- DEC-UX-13: el reparto del recargo se guarda en el pago, se lee igual y no
  se puede alterar.
- DEC-UX-14: la devolucion guarda el recargo reintegrado; la base rechaza
  devolver mas recargo que el cobrado.
- DEC-UX-03: la marca del texto unico se guarda y se lee; sin copia al
  estado fisico.
- DEC-UX-04: el alta con trabajo inicial es una sola transaccion; si el
  trabajo falla no queda nada, y un reintento con la misma clave no
  duplica.
"""

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api

TEXTO = "No carga. Rayon en la tapa."


def _pagar(cliente, orden_id, monto, metodo="TRANSFERENCIA"):
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={"usuario_id": f.RECEPCION, "monto": monto, "metodo": metodo},
        )
    )


def _alta(trabajo=None) -> dict:
    cuerpo = {
        "usuario_id": f.RECEPCION,
        "cliente": {"nombre_apellido": "Ana Prueba", "telefono": "341-1"},
        "equipo": {
            "marca": "Apple",
            "modelo": "iPhone 14",
            "falla_reportada": TEXTO,
        },
        "recepcion": {
            "observaciones": TEXTO,
            "observaciones_unificadas": True,
        },
    }
    if trabajo:
        cuerpo["trabajo_inicial"] = trabajo
    return cuerpo


def test_reparto_del_recargo_se_guarda_y_es_inmutable(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    orden = _pagar(cliente, orden_id, "10000")
    pago = orden["pagos"][-1]
    assert pago["recargo_distribucion"]
    assert (
        sum(float(a["importe"]) for a in pago["recargo_distribucion"]) == 200
    )
    leida = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert (
        leida["pagos"][-1]["recargo_distribucion"]
        == (pago["recargo_distribucion"])
    )
    assert _sql(
        base,
        "select jsonb_array_length(recargo_distribucion) from rma.pago",
    ) == [(len(pago["recargo_distribucion"]),)]
    with (
        pytest.raises(psycopg.errors.RestrictViolation),
        psycopg.connect(base) as conexion,
    ):
        conexion.execute(
            "update rma.pago set recargo_distribucion = '[]'::jsonb, "
            "anulado_en = now(), anulacion_motivo = 'x'"
        )


def test_devolucion_guarda_el_recargo_y_la_base_pone_el_tope(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    total = f.ok(cliente.get(f"/api/orders/{orden_id}"))["resumen"]["total"]
    pago_id = _pagar(cliente, orden_id, total)["pagos"][-1]["id"]
    f.ok(f.cancelar_detalle(cliente, orden_id, "DET-001"))
    mitad = str(int(float(total)) // 2)
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/refunds",
            json={
                "usuario_id": f.RECEPCION,
                "pago_id": pago_id,
                "monto": mitad,
                "medio": "TRANSFERENCIA",
                "motivo": "Se cancelo el trabajo.",
            },
        )
    )
    devolucion = orden["devoluciones_dinero"][-1]
    assert float(devolucion["recargo_importe"]) > 0
    leida = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert (
        leida["devoluciones_dinero"][-1]["recargo_importe"]
        == (devolucion["recargo_importe"])
    )
    # Directo en la base: un recargo mayor que lo que queda se rechaza.
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        psycopg.connect(base) as conexion,
    ):
        conexion.execute(
            """
            insert into rma.devolucion_dinero
                (codigo, orden_id, pago_id, monto, medio_pago_id, motivo,
                 usuario_id, posicion, recargo_importe)
            select 'DEV-X', d.orden_id, d.pago_id, 1, d.medio_pago_id, 'x',
                   d.usuario_id, 99, p.recargo_importe
              from rma.devolucion_dinero d join rma.pago p on p.id = d.pago_id
            """
        )


def test_marca_del_texto_unico_se_guarda_sin_copiar_al_estado(api, base):
    _, cliente = api
    orden = f.ok(cliente.post("/api/orders", json=_alta()))
    assert _sql(
        base,
        "select r.observaciones, r.estado_fisico, r.observaciones_unificadas "
        "from rma.recepcion r join rma.orden o on o.id = r.orden_id "
        "where o.codigo = %s",
        (orden["id"],),
    ) == [(TEXTO, None, True)]
    leida = f.ok(cliente.get(f"/api/orders/{orden['id']}"))
    assert leida["recepcion"]["datos"]["observaciones_unificadas"] is True


def test_alta_con_trabajo_inicial_atomica_e_idempotente(api, base):
    _, cliente = api
    antes = _sql(base, "select count(*) from rma.orden")[0][0]
    fallida = cliente.post("/api/orders", json=_alta("TR-INEXISTENTE"))
    assert fallida.status_code in (404, 409), fallida.text
    assert _sql(base, "select count(*) from rma.orden") == [(antes,)]

    clave = {idem.CLAVE: "alta-ux-04"}
    primera = cliente.post("/api/orders", json=_alta(f.BATERIA), headers=clave)
    assert primera.status_code == 201, primera.text
    segunda = cliente.post("/api/orders", json=_alta(f.BATERIA), headers=clave)
    assert segunda.status_code == 201
    assert segunda.json()["id"] == primera.json()["id"]
    assert _sql(base, "select count(*) from rma.orden") == [(antes + 1,)]
    assert _sql(
        base,
        "select count(*) from rma.detalle d join rma.orden o "
        "on o.id = d.orden_id where o.codigo = %s",
        (primera.json()["id"],),
    ) == [(1,)]
