"""DEC-UX-13 (ABI-45) y DEC-UX-14 (ABI-44), modo JSON (HTTP).

ABI-45: el recargo de cada cobro se reparte entre los Detalles elegibles
(no cancelados, con importe) en proporcion a sus importes; el comprobante
de cobro presenta cada trabajo con su importe final (precio + su parte del
recargo) y el total cobrado, sin una linea aparte de recargo. El saldo de
la Orden sigue sobre los importes base.

ABI-44: al devolver dinero se devuelve tambien la parte proporcional del
recargo cobrado en ese pago (todo lo que queda al completarlo); nunca mas
de lo cobrado.
"""

from decimal import Decimal

import pytest

from app.domain.models import (
    EstacionTrabajo,
    TipoReparacion,
    TipoReparacionEstacion,
)
from app.domain.recargos import distribuir, recargo_a_devolver
from app.storage.json.base import escribir_json_atomico
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    ESTACION,
    RECEPCION,
    cancelar_detalle,
    cliente_http,
    conflicto,
    ok,
)
from tests.fixtures.custodia import entregar
from tests.fixtures.ingreso_inicial import del_tipo
from tests.test_pagos_devoluciones import (
    _autorizada,
    _hasta_reparacion_lista,
    pagar,
    reintegrar,
)

A100, B050, C100, D100 = "TR-A100", "TR-B050", "TR-C100", "TR-D100"
_PRECIOS = {A100: "100000", B050: "50000", C100: "100000", D100: "100000"}


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        catalogos = tmp_path / "catalogs"
        escribir_json_atomico(
            catalogos / "tipos_reparacion.json",
            [
                TipoReparacion(
                    id=tipo,
                    nombre=f"Trabajo {tipo}",
                    precio=Decimal(precio),
                    puntaje=1,
                    garantia_dias=30,
                ).model_dump(mode="json")
                for tipo, precio in _PRECIOS.items()
            ],
        )
        escribir_json_atomico(catalogos / "tipo_reparacion_insumos.json", [])
        escribir_json_atomico(
            catalogos / "estaciones.json",
            [EstacionTrabajo(id=ESTACION, nombre="Mesa 1").model_dump()],
        )
        escribir_json_atomico(
            catalogos / "tipo_reparacion_estaciones.json",
            [
                TipoReparacionEstacion(
                    tipo_reparacion_id=tipo, estacion_id=ESTACION
                ).model_dump()
                for tipo in _PRECIOS
            ],
        )
        yield test_client


def _d(valor) -> Decimal:
    return Decimal(str(valor))


def _reparto(pago: dict) -> dict[str, Decimal]:
    return {
        a["detalle_id"]: _d(a["importe"]) for a in pago["recargo_distribucion"]
    }


def _por_detalle(orden: dict) -> dict[str, Decimal]:
    return {
        k: _d(v) for k, v in orden["resumen"]["recargo_por_detalle"].items()
    }


def _entregada(cliente, orden_id, *detalles) -> dict:
    """Reparada, avisada y entregada (con el saldo ya en cero)."""
    _hasta_reparacion_lista(cliente, orden_id, *detalles)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )
    return ok(entregar(cliente, orden_id, ADMINISTRADOR))


def _comprobante_de_cobro(cliente, orden_id) -> dict:
    (documento,) = del_tipo(cliente, orden_id, "COMPROBANTE_ENTREGA")
    return documento["contenido"]


def _presentado(contenido: dict) -> dict:
    """Lo que el comprobante presenta al cliente (importes finales)."""
    return {
        "trabajos": [
            _d(t["precio"]) + _d(t["recargo"])
            for t in contenido["trabajos_realizados"]
        ],
        "total": _d(contenido["total"]) + _d(contenido["recargo_incorporado"]),
        "cobrado": _d(contenido["pagado"]) + _d(contenido["recargo_cobrado"]),
        "devuelto": _d(contenido["devuelto"])
        + _d(contenido["recargo_devuelto"]),
        "saldo": _d(contenido["saldo"]),
    }


# --- Reparto (funcion pura) --------------------------------------------------


@pytest.mark.parametrize(
    ("importe", "pesos", "esperado"),
    [
        (
            "3000",
            [("A", "100000"), ("B", "50000")],
            [("A", "2000"), ("B", "1000")],
        ),
        (
            "2000",
            [("A", "100000"), ("B", "100000")],
            [("A", "1000"), ("B", "1000")],
        ),
        # 2 pesos entre tres iguales: el centavo de mas, al primero.
        (
            "2",
            [("A", "1"), ("B", "1"), ("C", "1")],
            [("A", "0.67"), ("B", "0.67"), ("C", "0.66")],
        ),
        ("0.01", [("A", "1"), ("B", "1")], [("A", "0.01")]),
        ("10", [("A", "0"), ("B", "5")], [("B", "10")]),
        ("10", [], []),
        ("0", [("A", "1")], []),
    ],
)
def test_reparto_exacto_y_deterministico(importe, pesos, esperado):
    resultado = distribuir(_d(importe), [(k, _d(p)) for k, p in pesos])
    assert resultado == [(k, _d(v)) for k, v in esperado]
    if resultado:
        assert sum(v for _, v in resultado) == _d(importe)


def test_recargo_a_devolver_proporcional_y_completo():
    base = {"monto_pago": _d(100000), "recargo_pago": _d(2000)}
    mitad = recargo_a_devolver(
        **base,
        devuelto_antes=_d(0),
        recargo_devuelto_antes=_d(0),
        monto=_d(50000),
    )
    assert mitad == _d(1000)
    resto = recargo_a_devolver(
        **base,
        devuelto_antes=_d(50000),
        recargo_devuelto_antes=_d(1000),
        monto=_d(50000),
    )
    assert resto == _d(1000)
    # Un tercio y despues el resto: nunca mas de lo cobrado.
    tercio = recargo_a_devolver(
        **base,
        devuelto_antes=_d(0),
        recargo_devuelto_antes=_d(0),
        monto=_d("33333.33"),
    )
    assert tercio == _d("666.67")
    final = recargo_a_devolver(
        **base,
        devuelto_antes=_d("33333.33"),
        recargo_devuelto_antes=tercio,
        monto=_d("66666.67"),
    )
    assert tercio + final == _d(2000)
    assert (
        recargo_a_devolver(
            monto_pago=_d(10),
            recargo_pago=_d(0),
            devuelto_antes=_d(0),
            recargo_devuelto_antes=_d(0),
            monto=_d(5),
        )
        == 0
    )


# --- ABI-45: recargo incorporado a los Detalles ------------------------------


def test_un_trabajo_un_pago(cliente):
    orden_id = _autorizada(cliente, A100)
    orden = ok(pagar(cliente, orden_id, "100000", metodo="TRANSFERENCIA"))
    assert _reparto(orden["pagos"][-1]) == {"DET-001": _d(2000)}
    assert _por_detalle(orden) == {"DET-001": _d(2000)}
    assert _d(orden["resumen"]["saldo"]) == 0
    entregada = _entregada(cliente, orden_id, "DET-001")
    assert entregada["estado_workflow"] == "ENTREGADA"
    contenido = _comprobante_de_cobro(cliente, orden_id)
    assert _presentado(contenido) == {
        "trabajos": [_d(102000)],
        "total": _d(102000),
        "cobrado": _d(102000),
        "devuelto": _d(0),
        "saldo": _d(0),
    }


def test_ejemplo_varios_trabajos_pago_completo(cliente):
    """A 100.000 y B 50.000, pago completo por transferencia (2 %)."""
    orden_id = _autorizada(cliente, A100, B050)
    orden = ok(pagar(cliente, orden_id, "150000", metodo="TRANSFERENCIA"))
    assert _reparto(orden["pagos"][-1]) == {
        "DET-001": _d(2000),
        "DET-002": _d(1000),
    }
    _entregada(cliente, orden_id, "DET-001", "DET-002")
    contenido = _comprobante_de_cobro(cliente, orden_id)
    presentado = _presentado(contenido)
    assert presentado["trabajos"] == [_d(102000), _d(51000)]
    assert presentado["total"] == presentado["cobrado"] == _d(153000)
    assert presentado["saldo"] == 0
    # Sin linea de recargo: el recargo solo existe incorporado a los trabajos.
    assert sum(presentado["trabajos"]) == presentado["total"]
    assert [_d(p["monto"]) + _d(p["recargo"]) for p in contenido["pagos"]] == [
        _d(153000)
    ]


def test_ejemplo_pagos_parciales_y_varios_medios(cliente):
    """A y B de 100.000: 100.000 en efectivo y 100.000 por transferencia."""
    orden_id = _autorizada(cliente, C100, D100)
    efectivo = ok(pagar(cliente, orden_id, "100000"))
    assert _reparto(efectivo["pagos"][-1]) == {}
    assert _d(efectivo["resumen"]["saldo"]) == _d(100000)
    orden = ok(pagar(cliente, orden_id, "100000", metodo="TRANSFERENCIA"))
    # El recargo de la transferencia se reparte entre los dos, no a uno solo.
    assert _reparto(orden["pagos"][-1]) == {
        "DET-001": _d(1000),
        "DET-002": _d(1000),
    }
    _entregada(cliente, orden_id, "DET-001", "DET-002")
    presentado = _presentado(_comprobante_de_cobro(cliente, orden_id))
    assert presentado["trabajos"] == [_d(101000), _d(101000)]
    assert presentado["total"] == presentado["cobrado"] == _d(202000)


def test_anticipo_parcial_solo_reparte_lo_cobrado(cliente):
    orden_id = _autorizada(cliente, A100, B050)
    orden = ok(pagar(cliente, orden_id, "30000", metodo="TRANSFERENCIA"))
    assert _reparto(orden["pagos"][-1]) == {
        "DET-001": _d(400),
        "DET-002": _d(200),
    }
    # Lo que falta cobrar no lleva recargo; el saldo sigue sobre el base.
    assert _d(orden["resumen"]["saldo"]) == _d(120000)
    assert _d(orden["resumen"]["recargo_cobrado"]) == _d(600)


def test_recargo_cero_no_reparte(cliente):
    orden_id = _autorizada(cliente, A100, B050)
    orden = ok(pagar(cliente, orden_id, "150000", metodo="TARJETA_DEBITO"))
    assert _reparto(orden["pagos"][-1]) == {}
    assert _por_detalle(orden) == {}


def test_cambio_posterior_del_porcentaje_no_toca_lo_cobrado(cliente, tmp_path):
    orden_id = _autorizada(cliente, C100, D100)
    ok(pagar(cliente, orden_id, "100000", metodo="TRANSFERENCIA"))
    escribir_json_atomico(
        tmp_path / "catalogs" / "medios_pago.json",
        [
            {"id": "EFECTIVO", "nombre": "Efectivo"},
            {
                "id": "TRANSFERENCIA",
                "nombre": "Transferencia",
                "recargo_porcentaje": "5",
            },
        ],
    )
    orden = ok(pagar(cliente, orden_id, "100000", metodo="TRANSFERENCIA"))
    assert [_reparto(p) for p in orden["pagos"]] == [
        {"DET-001": _d(1000), "DET-002": _d(1000)},
        {"DET-001": _d(2500), "DET-002": _d(2500)},
    ]
    assert _por_detalle(orden) == {"DET-001": _d(3500), "DET-002": _d(3500)}


def test_redondeo_reparte_los_centavos_sin_alterar_el_total(cliente):
    orden_id = _autorizada(cliente, A100, C100, D100)
    orden = ok(pagar(cliente, orden_id, "1000", metodo="TRANSFERENCIA"))
    reparto = _reparto(orden["pagos"][-1])
    assert reparto == {
        "DET-001": _d("6.67"),
        "DET-002": _d("6.67"),
        "DET-003": _d("6.66"),
    }
    assert sum(reparto.values()) == _d(20)


def test_descuento_del_trabajo_cambia_su_peso_y_el_de_la_orden_no(cliente):
    orden_id = _autorizada(cliente, C100, D100)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/discount",
            json={
                "usuario_id": RECEPCION,
                "tipo": "PORCENTAJE",
                "valor": "50",
                "motivo": "Cliente frecuente.",
                "detalle_id": "DET-001",
            },
        )
    )
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/discount",
            json={
                "usuario_id": RECEPCION,
                "tipo": "IMPORTE",
                "valor": "30000",
                "motivo": "Promocion.",
            },
        )
    )
    orden = ok(pagar(cliente, orden_id, "120000", metodo="TRANSFERENCIA"))
    # Pesos 50.000 y 100.000 (el ajuste de la Orden no se prorratea).
    assert _reparto(orden["pagos"][-1]) == {
        "DET-001": _d(800),
        "DET-002": _d(1600),
    }
    assert _d(orden["resumen"]["saldo"]) == 0
    _entregada(cliente, orden_id, "DET-001", "DET-002")
    contenido = _comprobante_de_cobro(cliente, orden_id)
    presentado = _presentado(contenido)
    assert presentado["trabajos"] == [_d(100800), _d(101600)]
    # Total = subtotal final - descuentos = lo cobrado; saldo cero.
    assert presentado["total"] == presentado["cobrado"] == _d(122400)
    assert presentado["saldo"] == 0


def test_cortesia_total_del_trabajo_lo_saca_del_reparto(cliente):
    orden_id = _autorizada(cliente, C100, D100)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/discount",
            json={
                "usuario_id": ADMINISTRADOR,
                "tipo": "PORCENTAJE",
                "valor": "100",
                "motivo": "Garantia comercial.",
                "clase": "CORTESIA",
                "detalle_id": "DET-002",
            },
        )
    )
    orden = ok(pagar(cliente, orden_id, "100000", metodo="TRANSFERENCIA"))
    assert _reparto(orden["pagos"][-1]) == {"DET-001": _d(2000)}


def test_anular_el_pago_quita_su_recargo(cliente):
    orden_id = _autorizada(cliente, A100)
    pago_id = ok(pagar(cliente, orden_id, "50000", metodo="TRANSFERENCIA"))[
        "pagos"
    ][-1]["id"]
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments/{pago_id}/void",
            json={"usuario_id": ADMINISTRADOR, "motivo": "Cargado dos veces."},
        )
    )
    assert _d(orden["resumen"]["recargo_cobrado"]) == 0
    assert _por_detalle(orden) == {}
    # La copia del pago anulado no cambia.
    assert _reparto(orden["pagos"][-1]) == {"DET-001": _d(1000)}


# --- ABI-44: devoluciones ----------------------------------------------------


def _con_credito(cliente, monto="100000", metodo="TRANSFERENCIA"):
    """A 100.000 pagado y despues cancelado: todo queda a favor."""
    orden_id = _autorizada(cliente, A100)
    pago_id = ok(pagar(cliente, orden_id, monto, metodo=metodo))["pagos"][-1][
        "id"
    ]
    ok(cancelar_detalle(cliente, orden_id, "DET-001"))
    return orden_id, pago_id


def test_devolucion_total_incluye_todo_el_recargo(cliente):
    orden_id, pago_id = _con_credito(cliente)
    orden = ok(
        reintegrar(cliente, orden_id, pago_id, "100000", "TRANSFERENCIA")
    )
    (devolucion,) = orden["devoluciones_dinero"]
    assert (
        _d(devolucion["recargo_importe"]),
        _d(devolucion["total_reintegrado"]),
    ) == (
        _d(2000),
        _d(102000),
    )
    assert _d(orden["resumen"]["saldo"]) == 0
    assert _d(orden["resumen"]["recargo_devuelto"]) == _d(2000)
    assert _por_detalle(orden) == {}
    assert (
        "+ recargo $2000 (total $102000)"
        in orden["historial"][-1]["observacion"]
    )


def test_devoluciones_parciales_y_sucesivas(cliente):
    orden_id, pago_id = _con_credito(cliente)
    orden = ok(reintegrar(cliente, orden_id, pago_id, "50000"))
    assert _d(orden["devoluciones_dinero"][-1]["total_reintegrado"]) == _d(
        51000
    )
    assert _d(orden["pagos"][0]["recargo_devuelto"]) == _d(1000)
    orden = ok(reintegrar(cliente, orden_id, pago_id, "20000"))
    assert _d(orden["devoluciones_dinero"][-1]["recargo_importe"]) == _d(400)
    orden = ok(reintegrar(cliente, orden_id, pago_id, "30000"))
    # La ultima completa el pago: devuelve todo lo que quedaba.
    assert _d(orden["devoluciones_dinero"][-1]["recargo_importe"]) == _d(600)
    assert sum(
        _d(d["recargo_importe"]) for d in orden["devoluciones_dinero"]
    ) == _d(2000)
    assert _d(orden["resumen"]["saldo"]) == 0


def test_varios_pagos_y_medios_cada_devolucion_con_su_pago(cliente):
    orden_id = _autorizada(cliente, A100)
    efectivo = ok(pagar(cliente, orden_id, "40000"))["pagos"][-1]["id"]
    transferencia = ok(
        pagar(cliente, orden_id, "60000", metodo="TRANSFERENCIA")
    )["pagos"][-1]["id"]
    ok(cancelar_detalle(cliente, orden_id, "DET-001"))
    orden = ok(reintegrar(cliente, orden_id, efectivo, "40000"))
    assert _d(orden["devoluciones_dinero"][-1]["recargo_importe"]) == 0
    orden = ok(
        reintegrar(cliente, orden_id, transferencia, "60000", "TRANSFERENCIA")
    )
    assert _d(orden["devoluciones_dinero"][-1]["total_reintegrado"]) == _d(
        61200
    )
    assert _d(orden["resumen"]["saldo"]) == 0


def test_no_se_devuelve_mas_de_lo_cobrado_ni_dos_veces(cliente):
    orden_id, pago_id = _con_credito(cliente)
    assert "supera" in conflicto(
        reintegrar(cliente, orden_id, pago_id, "100000.01")
    )
    primera = reintegrar(
        cliente, orden_id, pago_id, "10000", operacion_id="OP-1"
    )
    ok(primera)
    assert "no se duplica" in conflicto(
        reintegrar(cliente, orden_id, pago_id, "10000", operacion_id="OP-1")
    )
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    assert len(orden["devoluciones_dinero"]) == 1
    assert _d(orden["resumen"]["saldo"]) == _d(-90000)


def test_devolucion_parcial_con_trabajo_vigente_mantiene_la_coherencia(
    cliente,
):
    """A 100.000 y B 50.000 pagados por transferencia; B se cancela: se
    devuelven 50.000 + 1.000 y A queda en 102.000 en el comprobante."""
    orden_id = _autorizada(cliente, A100, B050)
    pago_id = ok(pagar(cliente, orden_id, "150000", metodo="TRANSFERENCIA"))[
        "pagos"
    ][-1]["id"]
    ok(cancelar_detalle(cliente, orden_id, "DET-002"))
    orden = ok(
        reintegrar(cliente, orden_id, pago_id, "50000", "TRANSFERENCIA")
    )
    assert _d(orden["devoluciones_dinero"][-1]["total_reintegrado"]) == _d(
        51000
    )
    assert _por_detalle(orden) == {"DET-001": _d(2000)}
    _entregada(cliente, orden_id, "DET-001")
    presentado = _presentado(_comprobante_de_cobro(cliente, orden_id))
    assert presentado["trabajos"] == [_d(102000)]
    assert presentado["total"] == _d(102000)
    assert presentado["cobrado"] == _d(153000)
    assert presentado["devuelto"] == _d(51000)
    assert (
        presentado["total"] - presentado["cobrado"] + presentado["devuelto"]
        == presentado["saldo"]
        == 0
    )
