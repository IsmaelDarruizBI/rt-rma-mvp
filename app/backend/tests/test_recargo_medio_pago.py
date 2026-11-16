"""UX-08: recargo porcentual por medio de pago (modo JSON, HTTP).

El importe del pago (``monto``) es lo que se imputa al saldo de la Orden,
como siempre; el recargo del medio se calcula al cobrar, se cobra aparte y
queda como copia en el pago (porcentaje e importe). Configuracion inicial:
Transferencia 2 %. Los pagos anteriores, sin recargo, no se recalculan.
"""

from decimal import Decimal

import pytest

from app.domain.models import Pago
from app.services.pagos import recargo_de
from app.storage.json.base import escribir_json_atomico
from tests.fixtures.api_salidas import ADMINISTRADOR, conflicto, ok
from tests.test_pagos_devoluciones import (
    T100,
    _autorizada,
    _orden,
    _resumen,
    _ultimo_pago,
    anular,
    cliente,  # noqa: F401  (fixture)
    pagar,
)


def test_el_catalogo_informa_el_recargo_inicial(cliente):  # noqa: F811
    medios = {
        m["id"]: Decimal(m["recargo_porcentaje"])
        for m in ok(cliente.get("/api/catalogs/payment-methods"))
    }
    assert medios == {
        "EFECTIVO": 0,
        "TRANSFERENCIA": 2,
        "TARJETA_DEBITO": 0,
        "TARJETA_CREDITO": 0,
        "OTRO": 0,
    }


def test_transferencia_cobra_el_recargo_aparte_del_saldo(cliente):  # noqa: F811
    orden_id = _autorizada(cliente, T100)

    orden = ok(pagar(cliente, orden_id, "10000", metodo="TRANSFERENCIA"))

    pago = _ultimo_pago(orden)
    assert (
        pago["monto"],
        Decimal(pago["recargo_porcentaje"]),
        pago["recargo_importe"],
        pago["total_cobrado"],
    ) == ("10000", Decimal("2"), "200", "10200")
    # Al saldo se imputa el importe, no el recargo.
    assert _resumen(orden) == (
        Decimal("100000"),
        Decimal("10000"),
        Decimal("0"),
        Decimal("90000"),
    )
    # El historial del cobro deja el recargo y el total.
    assert (
        "recargo 2% $200 (total $10200)"
        in (orden["historial"][-1]["observacion"])
    )


def test_efectivo_no_tiene_recargo(cliente):  # noqa: F811
    orden_id = _autorizada(cliente, T100)
    pago = _ultimo_pago(ok(pagar(cliente, orden_id, "10000")))
    assert (pago["recargo_importe"], pago["total_cobrado"]) == ("0", "10000")


def test_pagos_parciales_con_varios_medios(cliente):  # noqa: F811
    """Cada pago lleva su propio recargo; el saldo suma solo importes."""
    orden_id = _autorizada(cliente, T100)
    ok(pagar(cliente, orden_id, "30000"))
    ok(pagar(cliente, orden_id, "333.33", metodo="TRANSFERENCIA"))
    orden = ok(pagar(cliente, orden_id, "50000", metodo="TRANSFERENCIA"))
    assert [
        (p["metodo"], p["recargo_importe"], p["total_cobrado"])
        for p in orden["pagos"]
    ] == [
        ("EFECTIVO", "0", "30000"),
        # 333.33 x 2 % = 6.6666: se redondea al centavo.
        ("TRANSFERENCIA", "6.67", "340.00"),
        ("TRANSFERENCIA", "1000", "51000"),
    ]
    assert _resumen(orden)[3] == Decimal("100000") - Decimal("80333.33")


def test_no_se_cobra_de_mas_por_el_importe_no_por_el_recargo(cliente):  # noqa: F811
    """El tope del cobro sigue siendo el saldo: un pago por el saldo exacto
    con Transferencia se acepta aunque el total cobrado lo supere."""
    orden_id = _autorizada(cliente, T100)
    orden = ok(pagar(cliente, orden_id, "100000", metodo="TRANSFERENCIA"))
    assert _resumen(orden)[3] == Decimal("0")
    assert _ultimo_pago(orden)["total_cobrado"] == "102000"


def test_la_anulacion_conserva_la_copia_del_recargo(cliente):  # noqa: F811
    orden_id = _autorizada(cliente, T100)
    pago_id = _ultimo_pago(
        ok(pagar(cliente, orden_id, "10000", metodo="TRANSFERENCIA"))
    )["id"]
    orden = ok(anular(cliente, orden_id, pago_id))
    pago = _ultimo_pago(orden)
    assert pago["vigente"] is False
    assert (pago["recargo_importe"], pago["total_cobrado"]) == ("200", "10200")
    assert _resumen(orden)[1] == Decimal("0")


def test_cambiar_el_recargo_no_recalcula_pagos_anteriores(cliente, tmp_path):  # noqa: F811
    orden_id = _autorizada(cliente, T100)
    ok(pagar(cliente, orden_id, "10000", metodo="TRANSFERENCIA"))
    escribir_json_atomico(
        tmp_path / "catalogs" / "medios_pago.json",
        [
            {"id": "EFECTIVO", "nombre": "Efectivo"},
            {
                "id": "TRANSFERENCIA",
                "nombre": "Transferencia",
                "recargo_porcentaje": "3.5",
            },
        ],
    )
    orden = ok(pagar(cliente, orden_id, "10000", metodo="TRANSFERENCIA"))
    assert [
        (Decimal(p["recargo_porcentaje"]), p["recargo_importe"])
        for p in orden["pagos"]
    ] == [(Decimal("2"), "200"), (Decimal("3.5"), "350")]
    assert [
        (Decimal(p["recargo_porcentaje"]), p["recargo_importe"])
        for p in _orden(cliente, orden_id)["pagos"]
    ] == [(Decimal("2"), "200"), (Decimal("3.5"), "350")]


def test_un_pago_anterior_sin_recargo_se_lee_en_cero():
    pago = Pago.model_validate(
        {
            "id": "PAG-1",
            "monto": "5000",
            "tipo_pago": "ANTICIPO",
            "metodo": "TRANSFERENCIA",
            "usuario_id": "USR-1",
            "fecha": "2026-11-01T10:00:00Z",
        }
    )
    assert (pago.recargo_porcentaje, pago.recargo_importe) == (0, 0)
    assert pago.total_cobrado == Decimal("5000")


@pytest.mark.parametrize(
    ("monto", "porcentaje", "esperado"),
    [
        ("10000", "2", "200"),
        ("333.33", "2", "6.67"),
        ("0.25", "2", "0.01"),  # 0.005: mitad hacia arriba
        ("0.24", "2", "0"),
        ("1000", "0", "0"),
        ("1000", "2.5", "25"),
    ],
)
def test_calculo_del_recargo(monto, porcentaje, esperado):
    assert str(recargo_de(Decimal(monto), Decimal(porcentaje))) == esperado


def test_en_json_la_configuracion_del_recargo_es_de_solo_lectura(cliente):  # noqa: F811
    listado = ok(cliente.get("/api/admin/payment-methods"))
    assert listado["editable"] is False
    assert "solo lectura" in conflicto(
        cliente.put(
            "/api/admin/payment-methods/TRANSFERENCIA",
            json={"usuario_id": ADMINISTRADOR, "recargo_porcentaje": "3"},
        )
    )
