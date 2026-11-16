"""UX-08: recargo por medio de pago sobre PostgreSQL.

- La carga inicial deja Transferencia en 2 % y los demas en 0.
- El pago guarda la copia del porcentaje y del importe; el saldo de la
  vista (``v_orden_saldo``) solo suma importes.
- Administracion cambia el recargo con auditoria (``MEDIO_PAGO``); los
  pagos registrados no cambian. Otros roles no pueden.
- La copia del recargo es inmutable como el resto del pago.
"""

from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

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
def cliente_pg(api):
    app, cliente = api
    contexto = app.state.contexto
    unidad = contexto.unidad_de_trabajo
    app.state.contexto = replace(
        contexto,
        catalogos=PostgresCatalogosRepository(unidad),
        operativa=PostgresConfiguracionOperativa(unidad),
    )
    return cliente


def _pagar(cliente, orden_id, monto, metodo):
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={"usuario_id": f.RECEPCION, "monto": monto, "metodo": metodo},
        )
    )


def _recargo(cliente, codigo, porcentaje, usuario=f.ADMINISTRADOR):
    return cliente.put(
        f"/api/admin/payment-methods/{codigo}",
        json={"usuario_id": usuario, "recargo_porcentaje": porcentaje},
    )


def test_carga_inicial_transferencia_dos_por_ciento(cliente_pg, base):
    assert _sql(
        base,
        "select codigo, recargo_porcentaje::text from rma.medio_pago "
        "order by orden",
    ) == [
        ("EFECTIVO", "0.00"),
        ("TRANSFERENCIA", "2.00"),
        ("TARJETA_DEBITO", "0.00"),
        ("TARJETA_CREDITO", "0.00"),
        ("OTRO", "0.00"),
    ]
    medios = {
        m["id"]: m["recargo_porcentaje"]
        for m in f.ok(cliente_pg.get("/api/catalogs/payment-methods"))
    }
    assert medios["TRANSFERENCIA"] == "2" and medios["EFECTIVO"] == "0"


def test_el_pago_guarda_la_copia_y_el_saldo_solo_el_importe(cliente_pg, base):
    orden_id = f.definida(cliente_pg, f.BATERIA)
    orden = _pagar(cliente_pg, orden_id, "10000", "TRANSFERENCIA")
    pago = orden["pagos"][-1]
    assert (
        pago["recargo_porcentaje"],
        pago["recargo_importe"],
        pago["total_cobrado"],
    ) == ("2", "200", "10200")
    assert _sql(
        base,
        "select monto::text, recargo_porcentaje::text, recargo_importe::text "
        "from rma.pago",
    ) == [("10000.00", "2.00", "200.00")]
    pagado = _sql(base, "select pagado::text from rma.v_orden_saldo")
    assert pagado == [("10000.00",)]
    leida = f.ok(cliente_pg.get(f"/api/orders/{orden_id}"))
    assert leida["pagos"][-1]["total_cobrado"] == "10200"


def test_administracion_cambia_el_recargo_con_auditoria(cliente_pg, base):
    orden_id = f.definida(cliente_pg, f.BATERIA)
    _pagar(cliente_pg, orden_id, "10000", "TRANSFERENCIA")

    f.conflicto(_recargo(cliente_pg, "TRANSFERENCIA", "3", f.RECEPCION))
    assert "no hay cambios" in f.conflicto(
        _recargo(cliente_pg, "TRANSFERENCIA", "2")
    )
    assert "dos decimales" in f.conflicto(
        _recargo(cliente_pg, "TRANSFERENCIA", "2.555")
    )
    assert _recargo(cliente_pg, "TRANSFERENCIA", "101").status_code == 422
    assert _recargo(cliente_pg, "CHEQUE", "1").status_code == 404

    medio = f.ok(_recargo(cliente_pg, "TRANSFERENCIA", "3.5"))
    assert medio["recargo_porcentaje"] == "3.5"
    listado = f.ok(cliente_pg.get("/api/admin/payment-methods"))
    assert listado["editable"] is True
    assert {m["id"]: m["recargo_porcentaje"] for m in listado["medios"]}[
        "TRANSFERENCIA"
    ] == "3.5"
    assert _sql(
        base,
        """
        select clave, campo, valor_anterior, valor_nuevo
          from rma.cambio_configuracion where entidad = 'MEDIO_PAGO'
        """,
    ) == [("TRANSFERENCIA", "recargo_porcentaje", "2.00", "3.50")]

    # El pago anterior conserva su copia; el siguiente usa el nuevo valor.
    orden = _pagar(cliente_pg, orden_id, "10000", "TRANSFERENCIA")
    assert [
        (p["recargo_porcentaje"], p["recargo_importe"]) for p in orden["pagos"]
    ] == [("2", "200"), ("3.5", "350")]


def test_la_copia_del_recargo_es_inmutable(cliente_pg, base):
    orden_id = f.definida(cliente_pg, f.BATERIA)
    _pagar(cliente_pg, orden_id, "10000", "TRANSFERENCIA")
    with (
        pytest.raises(psycopg.errors.RestrictViolation),
        psycopg.connect(base) as conexion,
    ):
        conexion.execute(
            "update rma.pago set recargo_importe = 0, "
            "anulado_en = now(), anulacion_motivo = 'x'"
        )
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        psycopg.connect(base) as conexion,
    ):
        conexion.execute(
            "update rma.medio_pago set recargo_porcentaje = -1 "
            "where codigo = 'EFECTIVO'"
        )
    assert _sql(base, "select recargo_importe::text from rma.pago") == [
        ("200.00",)
    ]
