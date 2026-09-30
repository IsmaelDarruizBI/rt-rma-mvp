"""PROC-REP-212 ("¿Iniciar un Detalle de reparacion?"): se registra
antes de PROC-REP-181 SOLO cuando la Orden realmente viene de esa
decision -``current_process`` es PROC-REP-180 (recien tomada) o
PROC-REP-211 (tras completar otro Detalle, ABIERTA_TRABAJABLE)-, nunca
por inferencia de Scenario ni con un flag persistido nuevo.

Los casos "212 [Si] desde 180" y "212 [Si] desde 211" (con 2 Detalles
reales) ya quedan demostrados end-to-end por
``test_multidetalle.py::test_multidetalle_dos_detalles_end_to_end_por_http``
(Casos B y C). Este archivo agrega la pieza que todavia no tenia
cobertura: que una reentrada a ``seleccionar_detalle`` sin haber vuelto
a pasar por 180 o 211 NO inventa una segunda 212.
"""

from app.services import (
    seleccionar_detalle,
    tomar_orden,
    validar_estacion_trabajo,
)

from .fixtures import flujo_mvp
from .fixtures.catalogos_mvp import (
    COMPATIBILIDADES,
    ESTACION,
    ESTACIONES,
    TECNICO,
    t,
)


def _process_ids(historial):
    return [paso.process_id for paso in historial]


def test_212_se_registra_al_seleccionar_justo_despues_de_tomar():
    """180 -> seleccionar Detalle => historial termina 180, 212 [Si], 181."""
    orden, valida = validar_estacion_trabajo(
        flujo_mvp.orden_en_cola(),
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )
    assert valida is True
    orden = tomar_orden(
        orden, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )
    assert orden.current_process == "PROC-REP-180"

    orden = seleccionar_detalle(
        orden, detalle_id=flujo_mvp.DETALLE_ID, usuario=TECNICO, fecha=t(62)
    )

    assert _process_ids(orden.historial)[-3:] == [
        "PROC-REP-180",
        "PROC-REP-212",
        "PROC-REP-181",
    ]
    paso_212 = next(
        p for p in reversed(orden.historial) if p.process_id == "PROC-REP-212"
    )
    assert paso_212.observacion == "Si"


def test_seleccionar_detalle_no_duplica_212_si_se_reintenta():
    """Reentrar a seleccionar_detalle() sin pasar de nuevo por 180/211
    no vuelve a registrar PROC-REP-212 -por ejemplo, un reintento tras
    un fallo posterior que no llego a persistirse-.
    """
    orden, valida = validar_estacion_trabajo(
        flujo_mvp.orden_en_cola(),
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )
    assert valida is True
    orden = tomar_orden(
        orden, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )

    orden = seleccionar_detalle(
        orden, detalle_id=flujo_mvp.DETALLE_ID, usuario=TECNICO, fecha=t(62)
    )
    assert orden.current_process == "PROC-REP-181"
    ocurrencias_212 = [
        p for p in orden.historial if p.process_id == "PROC-REP-212"
    ]
    assert len(ocurrencias_212) == 1

    # Reintento: current_process ya es PROC-REP-181, no 180 ni 211.
    orden = seleccionar_detalle(
        orden, detalle_id=flujo_mvp.DETALLE_ID, usuario=TECNICO, fecha=t(63)
    )

    ocurrencias_212 = [
        p for p in orden.historial if p.process_id == "PROC-REP-212"
    ]
    assert len(ocurrencias_212) == 1
    ocurrencias_181 = [
        p for p in orden.historial if p.process_id == "PROC-REP-181"
    ]
    assert len(ocurrencias_181) == 2
