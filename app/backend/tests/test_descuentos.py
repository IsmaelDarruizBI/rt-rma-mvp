"""Descuento comercial por Recepcion (iteracion 1 del UAT).

Porcentaje o importe fijo, con motivo. Total = Subtotal - descuento; el
precio de cada trabajo (snapshot del catalogo) no cambia. Queda quien,
cuando y por que. No supera su base ni deja el total por debajo de lo ya
cobrado. Se refleja en los comprobantes y no altera los Pagos.
"""

from decimal import Decimal

import pytest

from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    PANTALLA,
    RECEPCION,
    TECNICO,
    agregar,
    aprobar,
    archivo,
    cliente_http,
    conflicto,
    detalle,
    ejecutar,
    ok,
    tomar,
)
from tests.fixtures.custodia import entregar
from tests.fixtures.ingreso_inicial import (
    crear_con_recepcion,
    del_tipo,
    generar_ingreso,
    ingresada,
)

MOTIVO = "Promocion de octubre"


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def _descontar(
    cliente, orden_id, tipo, valor, motivo=MOTIVO, usuario=RECEPCION
):
    return cliente.post(
        f"/api/orders/{orden_id}/discount",
        json={
            "usuario_id": usuario,
            "tipo": tipo,
            "valor": valor,
            "motivo": motivo,
        },
    )


def _pagar(cliente, orden_id, monto):
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": RECEPCION,
                "monto": monto,
                "metodo": "EFECTIVO",
            },
        )
    )


def _resumen(orden) -> dict[str, Decimal]:
    resumen = orden["resumen"]
    return {
        clave: Decimal(resumen[clave])
        for clave in ("subtotal", "descuento_aplicado", "total", "saldo")
    }


def test_porcentaje(cliente):
    orden_id = ingresada(cliente, BATERIA, PANTALLA)

    orden = ok(_descontar(cliente, orden_id, "PORCENTAJE", "10"))

    assert _resumen(orden) == {
        "subtotal": Decimal("130000"),
        "descuento_aplicado": Decimal("13000"),
        "total": Decimal("117000"),
        "saldo": Decimal("117000"),
    }
    # El precio de cada trabajo no cambia.
    assert detalle(orden, "DET-001")["precio"] == "80000"
    assert detalle(orden, "DET-002")["precio"] == "50000"
    vigente = orden["resumen"]["descuento"]
    assert vigente["tipo"] == "PORCENTAJE"
    assert vigente["descripcion"] == "10 %"
    assert vigente["motivo"] == MOTIVO
    assert vigente["usuario_id"] == RECEPCION
    assert vigente["fecha"] is not None
    (registro,) = orden["descuentos"]
    assert registro["usuario_id"] == RECEPCION


def test_importe_fijo_cambio_y_retiro(cliente):
    orden_id = ingresada(cliente)

    fijo = ok(_descontar(cliente, orden_id, "IMPORTE", "5000"))
    assert _resumen(fijo)["total"] == Decimal("75000")
    assert fijo["resumen"]["descuento"]["descripcion"] == "$ 5000.00"

    cambiado = ok(_descontar(cliente, orden_id, "PORCENTAJE", "12.5"))
    assert _resumen(cambiado)["descuento_aplicado"] == Decimal("10000")

    quitado = ok(
        _descontar(cliente, orden_id, None, None, motivo="Fin de la promo")
    )
    assert quitado["resumen"]["descuento"] is None
    assert _resumen(quitado)["total"] == Decimal("80000")
    # La historia completa se conserva: quien, cuando y por que.
    assert [r["tipo"] for r in quitado["descuentos"]] == [
        "IMPORTE",
        "PORCENTAJE",
        None,
    ]
    assert quitado["descuentos"][-1]["motivo"] == "Fin de la promo"


@pytest.mark.parametrize(
    ("tipo", "valor", "texto"),
    [
        ("IMPORTE", "80000.01", "subtotal"),
        ("PORCENTAJE", "100.5", "100"),
        ("PORCENTAJE", None, "mayor que cero"),
    ],
)
def test_no_supera_su_base(cliente, tmp_path, tipo, valor, texto):
    orden_id = ingresada(cliente)
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(_descontar(cliente, orden_id, tipo, valor))

    assert texto in mensaje
    assert archivo(tmp_path, orden_id) == antes


def test_motivo_obligatorio_y_rol(cliente, tmp_path):
    orden_id = ingresada(cliente)
    antes = archivo(tmp_path, orden_id)

    respuesta = _descontar(cliente, orden_id, "IMPORTE", "100", motivo="")
    assert respuesta.status_code == 422, respuesta.text
    conflicto(_descontar(cliente, orden_id, "IMPORTE", "100", motivo="   "))
    conflicto(_descontar(cliente, orden_id, "IMPORTE", "100", usuario=TECNICO))
    assert archivo(tmp_path, orden_id) == antes

    # Administracion tambien puede.
    ok(_descontar(cliente, orden_id, "IMPORTE", "100", usuario=ADMINISTRADOR))


def test_saldo_con_pagos_parciales_y_bloqueo(cliente, tmp_path):
    orden_id = ingresada(cliente)
    con_pago = _pagar(cliente, orden_id, "50000")
    pagos_antes = con_pago["pagos"]

    orden = ok(_descontar(cliente, orden_id, "PORCENTAJE", "10"))

    assert _resumen(orden)["total"] == Decimal("72000")
    assert _resumen(orden)["saldo"] == Decimal("22000")
    # Los Pagos no se tocan.
    assert orden["pagos"] == pagos_antes
    # Un descuento que dejaria el total debajo de lo cobrado se rechaza.
    antes = archivo(tmp_path, orden_id)
    mensaje = conflicto(_descontar(cliente, orden_id, "IMPORTE", "40000"))
    assert "ya cobrado" in mensaje
    assert archivo(tmp_path, orden_id) == antes
    # Hasta igualar lo cobrado si se puede.
    saldado = ok(_descontar(cliente, orden_id, "IMPORTE", "30000"))
    assert _resumen(saldado)["saldo"] == Decimal("0")


def test_figura_en_el_comprobante_de_ingreso(cliente):
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id)
    ok(_descontar(cliente, orden_id, "IMPORTE", "8000"))

    ok(generar_ingreso(cliente, orden_id))

    (ingreso,) = del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")
    contenido = ingreso["contenido"]
    assert contenido["subtotal"] == "80000"
    descuento = contenido["descuento"]
    assert descuento["descripcion"] == "$ 8000.00"
    assert descuento["motivo"] == MOTIVO
    assert Decimal(descuento["importe"]) == Decimal("8000")
    assert Decimal(contenido["total"]) == Decimal("72000")
    assert contenido["trabajos"][0]["precio"] == "80000"


def test_un_cambio_posterior_pide_otro_comprobante_de_autorizacion(cliente):
    orden_id = ingresada(cliente)

    orden = ok(_descontar(cliente, orden_id, "PORCENTAJE", "10"))

    assert "EMITIR_COMPROBANTE_AUTORIZACION" in [
        a["codigo"] for a in orden["acciones_autorizacion"]
    ]
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/documents/authorization-receipt",
            json={"usuario_id": RECEPCION},
        )
    )
    (autorizacion,) = del_tipo(cliente, orden_id, "COMPROBANTE_AUTORIZACION")
    contenido = autorizacion["contenido"]
    assert Decimal(contenido["subtotal_autorizado"]) == Decimal("80000")
    assert contenido["descuento"]["descripcion"] == "10 %"
    assert Decimal(contenido["total_autorizado"]) == Decimal("72000")
    assert "descuento" in autorizacion["motivo"]
    # El de ingreso se conserva tal cual.
    (ingreso,) = del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")
    assert ingreso["contenido"]["descuento"] is None


def test_en_la_entrega_y_despues_ya_no_se_edita(cliente, tmp_path):
    orden_id = ingresada(cliente)
    ok(_descontar(cliente, orden_id, "IMPORTE", "10000"))
    tomar(cliente, orden_id, TECNICO)
    ejecutar(cliente, orden_id)
    ok(aprobar(cliente, orden_id, "DET-001"))
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )
    _pagar(cliente, orden_id, "70000")

    entregada = ok(entregar(cliente, orden_id, ADMINISTRADOR))

    assert entregada["estado_workflow"] == "ENTREGADA"
    assert "APLICAR_DESCUENTO" not in [
        a["codigo"] for a in entregada["acciones_financieras"]
    ]
    (comprobante,) = del_tipo(cliente, orden_id, "COMPROBANTE_ENTREGA")
    contenido = comprobante["contenido"]
    assert Decimal(contenido["subtotal"]) == Decimal("80000")
    assert Decimal(contenido["descuento"]["importe"]) == Decimal("10000")
    assert Decimal(contenido["total"]) == Decimal("70000")
    antes = archivo(tmp_path, orden_id)
    conflicto(
        _descontar(cliente, orden_id, "IMPORTE", "1000"), "ORDEN_CERRADA"
    )
    assert archivo(tmp_path, orden_id) == antes


def test_se_ofrece_a_recepcion_en_una_orden_cobrable(cliente):
    orden_id = ingresada(cliente)

    orden = ok(cliente.get(f"/api/orders/{orden_id}"))

    (accion,) = [
        a
        for a in orden["acciones_financieras"]
        if a["codigo"] == "APLICAR_DESCUENTO"
    ]
    assert set(accion["roles"]) == {"RECEPCION", "ADMINISTRADOR"}


def test_cuentas_documentos_e_historia_consistentes(cliente):
    """Precio original intacto, descuento aparte, cuentas coherentes en la
    Orden y en finanzas, pagos sin tocar y la historia de cada cambio."""
    orden_id = ingresada(cliente, BATERIA, PANTALLA)
    con_pago = _pagar(cliente, orden_id, "30000")
    pago = con_pago["pagos"][0]
    ok(_descontar(cliente, orden_id, "IMPORTE", "10000"))
    orden = ok(
        _descontar(
            cliente,
            orden_id,
            "PORCENTAJE",
            "20",
            motivo="Convenio empresa",
            usuario=ADMINISTRADOR,
        )
    )

    resumen = orden["resumen"]
    subtotal = Decimal(resumen["subtotal"])
    descuento = Decimal(resumen["descuento_aplicado"])
    total = Decimal(resumen["total"])
    pagado = Decimal(resumen["pagado"])
    assert [d["precio"] for d in orden["reparaciones_detail"]] == [
        "80000",
        "50000",
    ]
    assert (subtotal, descuento, total) == (
        Decimal("130000"),
        Decimal("26000"),
        Decimal("104000"),
    )
    assert pagado == Decimal("30000")
    assert Decimal(resumen["saldo"]) == total - pagado
    # Finanzas dice lo mismo, y el descuento no es un movimiento de dinero.
    finanzas = ok(cliente.get(f"/api/orders/{orden_id}/finances"))
    assert finanzas["resumen"] == resumen
    assert [m["tipo"] for m in finanzas["movimientos"]] == ["PAGO"]
    # El pago parcial no se modifico.
    assert orden["pagos"] == [pago]
    # Quien, cuando y por que, de cada cambio.
    historia = [
        (r["tipo"], Decimal(r["valor"]), r["motivo"], r["usuario_id"])
        for r in orden["descuentos"]
    ]
    assert historia == [
        ("IMPORTE", Decimal("10000"), MOTIVO, RECEPCION),
        ("PORCENTAJE", Decimal("20"), "Convenio empresa", ADMINISTRADOR),
    ]
    assert all(r["fecha"] for r in orden["descuentos"])
    # El documento que se emita refleja el vigente.
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/documents/authorization-receipt",
            json={"usuario_id": RECEPCION},
        )
    )
    (autorizacion,) = del_tipo(cliente, orden_id, "COMPROBANTE_AUTORIZACION")
    assert autorizacion["contenido"]["descuento"]["descripcion"] == "20 %"
    assert Decimal(autorizacion["contenido"]["total_autorizado"]) == total
