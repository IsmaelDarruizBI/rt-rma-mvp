"""Ajuste Comercial por Orden o por Detalle (DC09, DEC-MI-03).

- Descuento y cortesia sobre un trabajo o sobre la Orden; el de la Orden se
  aplica sobre lo que queda despues de los ajustes de los trabajos y no se
  prorratea entre ellos.
- Los aplican Recepcion, Coordinacion RMA y Administracion.
- Por debajo de lo cobrado: saldo a favor, devolucion antes de entregar,
  sin devolver dos veces.
"""

from decimal import Decimal

import pytest

from app.services.documentos import _descuento_en_documento
from tests.fixtures import api_salidas as f
from tests.fixtures import iteracion1 as it


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _ajustar(
    cliente,
    orden_id,
    tipo,
    valor,
    *,
    detalle_id=None,
    clase="DESCUENTO",
    usuario=f.RECEPCION,
):
    return cliente.post(
        f"/api/orders/{orden_id}/discount",
        json={
            "usuario_id": usuario,
            "tipo": tipo,
            "valor": valor,
            "motivo": "Acuerdo comercial.",
            "clase": clase,
            "detalle_id": detalle_id,
        },
    )


def _resumen(orden):
    return {
        clave: Decimal(orden["resumen"][clave])
        for clave in ("subtotal", "descuento_aplicado", "total", "saldo")
    }


def test_ajuste_de_un_trabajo_y_de_la_orden_sin_prorrateo(cliente, tmp_path):
    # DET-001 bateria 80000, DET-002 pantalla 50000.
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    orden = f.ok(
        _ajustar(cliente, orden_id, "PORCENTAJE", "10", detalle_id="DET-002")
    )
    assert _resumen(orden)["total"] == Decimal("125000")
    (ajuste,) = orden["resumen"]["ajustes_detalle"]
    assert (ajuste["detalle_id"], Decimal(ajuste["importe"])) == (
        "DET-002",
        Decimal("5000"),
    )
    assert orden["resumen"]["descuento"] is None

    # El de la Orden, sobre lo que queda (125000), no sobre 130000.
    orden = f.ok(
        _ajustar(cliente, orden_id, "PORCENTAJE", "10", usuario=f.COORDINADOR)
    )
    assert _resumen(orden) == {
        "subtotal": Decimal("130000"),
        "descuento_aplicado": Decimal("17500"),
        "total": Decimal("112500"),
        "saldo": Decimal("112500"),
    }
    assert Decimal(orden["resumen"]["descuento"]["importe"]) == Decimal(
        "12500"
    )
    # El precio de cada trabajo no cambia.
    assert [d["precio"] for d in orden["reparaciones_detail"]] == [
        "80000",
        "50000",
    ]

    documento = _descuento_en_documento(
        f.repo_ordenes(tmp_path).obtener(orden_id),
        [("DET-001", Decimal("80000")), ("DET-002", Decimal("50000"))],
    )
    assert documento.importe == Decimal("17500")
    assert "(DET-002)" in documento.descripcion
    assert "sobre la Orden" in documento.descripcion

    # Quitar el ajuste del trabajo deja solo el de la Orden.
    quitado = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/discount",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "tipo": None,
                "motivo": "Se revisa.",
                "detalle_id": "DET-002",
            },
        )
    )
    assert quitado["resumen"]["ajustes_detalle"] == []
    assert _resumen(quitado)["total"] == Decimal("117000")


def test_reglas_del_ajuste_de_un_trabajo(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    assert "precio del trabajo" in f.conflicto(
        _ajustar(cliente, orden_id, "IMPORTE", "50001", detalle_id="DET-002")
    )
    assert "DET-009" in f.conflicto(
        _ajustar(cliente, orden_id, "IMPORTE", "1", detalle_id="DET-009")
    )
    f.conflicto(
        _ajustar(
            cliente,
            orden_id,
            "IMPORTE",
            "1",
            detalle_id="DET-001",
            usuario=f.TECNICO,
        )
    )
    # Cortesia de un trabajo.
    orden = f.ok(
        _ajustar(
            cliente,
            orden_id,
            "PORCENTAJE",
            "100",
            detalle_id="DET-002",
            clase="CORTESIA",
        )
    )
    (ajuste,) = orden["resumen"]["ajustes_detalle"]
    assert ajuste["clase"] == "CORTESIA"
    assert _resumen(orden)["total"] == Decimal("80000")

    # Un trabajo cancelado no se cobra: su ajuste deja de contar.
    f.ok(f.cancelar_detalle(cliente, orden_id, "DET-002"))
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert orden["resumen"]["ajustes_detalle"] == []
    assert _resumen(orden)["total"] == Decimal("80000")
    assert "cancelado" in f.conflicto(
        _ajustar(cliente, orden_id, "IMPORTE", "1", detalle_id="DET-002")
    )


def test_bajo_lo_cobrado_queda_saldo_a_favor_y_se_devuelve_una_vez(cliente):
    orden_id = f.definida(cliente, f.BATERIA)
    pago = it.pagar(cliente, orden_id, "80000")["pagos"][0]
    orden = f.ok(
        _ajustar(cliente, orden_id, "IMPORTE", "10000", detalle_id="DET-001")
    )
    assert _resumen(orden)["saldo"] == Decimal("-10000")
    assert orden["resumen"]["situacion_financiera"] == "SALDO_A_FAVOR"

    devuelta = f.ok(it.devolver_dinero(cliente, orden_id, pago["id"], "10000"))
    assert Decimal(devuelta["resumen"]["saldo"]) == 0
    # Sin saldo a favor no hay otra devolucion.
    f.conflicto(
        it.devolver_dinero(
            cliente, orden_id, pago["id"], "1", operacion_id="otra"
        )
    )
