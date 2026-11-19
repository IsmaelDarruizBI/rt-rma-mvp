"""Configuracion v2, CFG-07 y CFG-08: lo que se oculta de la interfaz se
conserva en el backend (ajuste 8: no se cambian parametros ni se borran
plantillas para ocultarlos).

- CFG-08 (DF-3): la API marca ``visible`` solo Ingreso y Equipo listo para
  retirar; las demas plantillas siguen en la API y siguen preparando
  mensajes (una Orden o un script que las use no se rompe).
- CFG-07: el plazo de retiro sale de la pantalla pero sigue rigiendo en
  el backend con su valor.
"""

import pytest

from app.domain.models.comunicaciones import (
    PLANTILLAS_INICIALES,
    PLANTILLAS_VISIBLES,
)
from app.domain.models.operativa import PARAMETROS_INICIALES
from tests.fixtures import api_salidas as f


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path) as test_client:
        yield test_client


def test_solo_ingreso_y_listo_para_retirar_son_visibles(cliente):
    assert PLANTILLAS_VISIBLES == ("INGRESO", "LISTO_PARA_RETIRAR")
    plantillas = f.ok(cliente.get("/api/communications/templates"))[
        "plantillas"
    ]
    visibles = {p["codigo"]: p["visible"] for p in plantillas}
    # Ninguna se borro ni se desactivo: estan las cinco, activas.
    assert set(visibles) == {p.codigo for p in PLANTILLAS_INICIALES}
    assert all(p["activa"] for p in plantillas)
    assert [c for c, v in visibles.items() if v] == [
        "INGRESO",
        "LISTO_PARA_RETIRAR",
    ]
    assert visibles["RECORDATORIO_RETIRO"] is False


def test_una_plantilla_oculta_sigue_preparando_mensajes(cliente):
    orden_id = f.crear(cliente)
    for codigo in ("AUTORIZACION_PENDIENTE", "RECORDATORIO_RETIRO"):
        preparado = f.ok(
            cliente.get(
                f"/api/orders/{orden_id}/messages/prepare?plantilla={codigo}"
            )
        )
        assert orden_id in preparado["mensaje"]


def test_el_plazo_de_retiro_sigue_en_el_backend():
    # Sin pantalla (CFG-07), con el mismo valor inicial y la misma regla.
    assert PARAMETROS_INICIALES["PLAZO_RETIRO_DIAS"] == "30"
