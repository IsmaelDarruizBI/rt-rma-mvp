"""Comprobantes con el Ajuste Comercial por trabajo (DEC-AJ-10, D-10.5).

Por trabajo: precio original, ajuste (con su clase: la cortesia se imprime
como cortesia) y precio final; el de la Orden en una linea aparte. Motivo,
usuario y fecha quedan en el registro interno. Los emitidos antes conservan
su presentacion; un cambio de clase ofrece otra version del comprobante de
autorizacion.
"""

from datetime import timezone
from decimal import Decimal

import pytest

from app.application.documentos_pdf import pdf_comprobante_autorizacion
from app.domain.models import DocumentoEmitido
from tests.fixtures import api_salidas as f
from tests.fixtures.ingreso_inicial import del_tipo, ingresada
from tests.test_ajuste_comercial_dec_aj_10 import _ajustar

ARGENTINA = timezone.utc


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path) as test_client:
        yield test_client


# --- D-10.5: comprobantes --------------------------------------------------


def test_el_comprobante_muestra_el_ajuste_por_trabajo(cliente):
    orden_id = ingresada(cliente, f.BATERIA, f.PANTALLA)
    f.ok(
        _ajustar(
            cliente,
            orden_id,
            "PORCENTAJE",
            "10",
            detalle_id="DET-002",
            clase="CORTESIA",
            motivo="Cliente frecuente (interno).",
        )
    )
    orden = f.ok(_ajustar(cliente, orden_id, "IMPORTE", "5000"))
    assert "EMITIR_COMPROBANTE_AUTORIZACION" in [
        a["codigo"] for a in orden["acciones_autorizacion"]
    ]
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/documents/authorization-receipt",
            json={"usuario_id": f.RECEPCION},
        )
    )
    (documento,) = del_tipo(cliente, orden_id, "COMPROBANTE_AUTORIZACION")
    contenido = documento["contenido"]

    assert contenido["ajustes_por_trabajo"] is True
    bateria, pantalla = contenido["trabajos"]
    assert bateria["ajuste"] is None
    assert bateria["precio_final"] == "80000"
    assert pantalla["precio"] == "50000"
    assert pantalla["ajuste"] == {
        "clase": "CORTESIA",
        "descripcion": "10 %",
        "importe": "5000.00",
    }
    assert Decimal(pantalla["precio_final"]) == Decimal("45000")
    assert contenido["ajuste_orden"]["clase"] == "DESCUENTO"
    assert Decimal(contenido["ajuste_orden"]["importe"]) == Decimal("5000")
    assert Decimal(contenido["total_autorizado"]) == Decimal("120000")
    # Ni motivo ni usuario del ajuste en los datos del ajuste por trabajo.
    assert "motivo" not in pantalla["ajuste"]

    pdf = pdf_comprobante_autorizacion(
        DocumentoEmitido.model_validate(documento), zona_horaria=ARGENTINA
    ).decode("cp1252")
    assert "Cortesía 10 %" in pdf
    assert "Precio final $ 45.000,00" in pdf
    assert "Descuento $ 5000.00 sobre la Orden" in pdf
    assert "Cliente frecuente" not in pdf

    # Cambiar solo la clase del ajuste ofrece una version nueva.
    cambiada = f.ok(
        _ajustar(
            cliente,
            orden_id,
            "PORCENTAJE",
            "10",
            detalle_id="DET-002",
            motivo="Era un descuento.",
        )
    )
    assert "EMITIR_COMPROBANTE_AUTORIZACION" in [
        a["codigo"] for a in cambiada["acciones_autorizacion"]
    ]


def test_el_comprobante_de_entrega_lleva_el_ajuste_por_trabajo(cliente):
    orden_id = ingresada(cliente)
    f.ok(
        _ajustar(
            cliente,
            orden_id,
            "IMPORTE",
            "10000",
            detalle_id="DET-001",
            clase="CORTESIA",
        )
    )
    f.tomar(cliente, orden_id, f.TECNICO)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    f.notificar_pagar_entregar(cliente, orden_id)

    (comprobante,) = del_tipo(cliente, orden_id, "COMPROBANTE_ENTREGA")
    contenido = comprobante["contenido"]
    (trabajo,) = contenido["trabajos_realizados"]
    assert trabajo["ajuste"]["clase"] == "CORTESIA"
    assert Decimal(trabajo["precio_final"]) == Decimal("70000")
    assert contenido["ajuste_orden"] is None
    assert contenido["ajustes_por_trabajo"] is True
