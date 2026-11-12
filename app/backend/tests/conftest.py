"""Fixtures compartidas por los tests del dominio."""

import pytest

from app.domain.models import OrdenReparacion
from app.services import reparaciones
from tests.fixtures.hp_rep_001 import construir_orden_hp_rep_001


@pytest.fixture
def orden_hp_rep_001() -> OrdenReparacion:
    """Orden en el estado final del escenario HP-REP-001."""
    return construir_orden_hp_rep_001()


@pytest.fixture(autouse=True)
def diagnostico_anterior_a_la_evaluacion(request, monkeypatch):
    """BR-REP-035 (evaluacion tecnica) llego despues de estos tests.

    Sin la marca ``v14_evaluacion``, los Detalles se crean sin
    ``origen_diagnostico``: es como el producto trata los datos
    anteriores a la evaluacion (no la exigen). Los tests de la evaluacion
    llevan la marca y ejercitan el recorrido V1.4 completo
    (181 -> 182 -> 183 -> 184 -> 182 -> 174).
    """
    if request.node.get_closest_marker("v14_evaluacion"):
        return
    original = reparaciones._detalle_con_snapshot

    def sin_origen(*args, **kwargs):
        detalle = original(*args, **kwargs)
        detalle.origen_diagnostico = None
        return detalle

    monkeypatch.setattr(reparaciones, "_detalle_con_snapshot", sin_origen)
