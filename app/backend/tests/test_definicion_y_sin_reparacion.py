"""Services de la definicion de Detalles y de SIN_REPARACION (sin HTTP).

Ambos cierres se derivan del historial, sin flags ni estados nuevos:

- ``definicion_finalizada``: la factibilidad (PROC-REP-080) ya se valido.
- ``finalizada_sin_reparacion``: existe PROC-REP-069.
- ``lista_para_cierre``: REPARACION_LISTA (240) o SIN_REPARACION (069).
"""

import pytest

from app.domain.models import EstadoWorkflow
from app.services import (
    PrecondicionInvalidaError,
    definicion_finalizada,
    exigir_definicion_finalizable,
    finalizada_sin_reparacion,
    lista_para_cierre,
    registrar_finalizacion_sin_reparacion,
)
from tests.fixtures import flujo_mvp
from tests.fixtures.catalogos_mvp import (
    ADMINISTRADOR,
    RECEPCION,
    TECNICO,
    t,
)
from tests.test_var_rep_001_002 import _definir, _en_revision, _revisada

MOTIVO = "No corresponde reparar."


def _sin_reparacion(orden, usuario=RECEPCION, motivo=MOTIVO, **extra):
    return registrar_finalizacion_sin_reparacion(
        orden, usuario=usuario, motivo=motivo, fecha=t(10), **extra
    )


# --- Definicion -----------------------------------------------------------


def test_la_definicion_se_finaliza_al_validar_la_factibilidad():
    assert definicion_finalizada(flujo_mvp.orden_con_detalle()) is False
    assert definicion_finalizada(flujo_mvp.orden_con_factibilidad()) is True
    assert definicion_finalizada(flujo_mvp.orden_entregada()) is True


def test_finalizar_exige_recepcion_un_detalle_y_definicion_abierta():
    con_detalle = flujo_mvp.orden_con_detalle()
    exigir_definicion_finalizable(con_detalle, usuario=RECEPCION)  # ok

    for usuario in (TECNICO, ADMINISTRADOR):
        with pytest.raises(PrecondicionInvalidaError):
            exigir_definicion_finalizable(con_detalle, usuario=usuario)
    with pytest.raises(PrecondicionInvalidaError, match="Detalle"):
        exigir_definicion_finalizable(
            flujo_mvp.orden_creada(), usuario=RECEPCION
        )
    with pytest.raises(PrecondicionInvalidaError):
        exigir_definicion_finalizable(
            flujo_mvp.orden_con_factibilidad(), usuario=RECEPCION
        )


def test_finalizar_desde_revision_exige_el_065_y_un_detalle():
    with pytest.raises(PrecondicionInvalidaError):
        exigir_definicion_finalizable(
            _en_revision(flujo_mvp.orden_creada()), usuario=RECEPCION
        )
    with pytest.raises(PrecondicionInvalidaError, match="Detalle"):
        exigir_definicion_finalizable(
            _revisada(flujo_mvp.orden_creada()), usuario=RECEPCION
        )
    exigir_definicion_finalizable(
        _definir(_revisada(flujo_mvp.orden_creada())), usuario=RECEPCION
    )


# --- SIN_REPARACION (068 No -> 069) ---------------------------------------


def test_sin_reparacion_registra_068_no_y_069_sin_detalles_ni_estado_nuevo():
    revisada = _revisada(flujo_mvp.orden_creada())
    foto = revisada.model_copy(deep=True)

    orden = _sin_reparacion(revisada, observaciones="  Aviso al cliente.  ")

    paso_068, paso_069 = orden.historial[-2:]
    assert (paso_068.referencia_id, paso_068.observacion) == (
        "PROC-REP-068",
        "No",
    )
    assert paso_068.usuario_id == RECEPCION.id
    assert paso_069.referencia_id == "PROC-REP-069"
    assert paso_069.usuario_id == RECEPCION.id
    assert paso_069.fecha == t(10)
    assert paso_069.observacion == (
        f"SIN_REPARACION · Motivo: {MOTIVO} · Observaciones: Aviso al cliente."
    )
    assert orden.current_process == "PROC-REP-069"
    assert orden.estado_workflow is EstadoWorkflow.EN_REVISION
    assert orden.reparaciones_detail == []
    assert orden.total == 0
    assert finalizada_sin_reparacion(orden) is True
    assert lista_para_cierre(orden) is True
    assert definicion_finalizada(orden) is False
    assert revisada == foto  # la Orden original no se modifica


def test_sin_reparacion_sin_observaciones():
    orden = _sin_reparacion(_revisada(flujo_mvp.orden_creada()))
    assert (
        orden.historial[-1].observacion == f"SIN_REPARACION · Motivo: {MOTIVO}"
    )


@pytest.mark.parametrize("motivo", ["", "   ", "\n"])
def test_sin_reparacion_exige_motivo(motivo):
    with pytest.raises(PrecondicionInvalidaError, match="motivo"):
        _sin_reparacion(_revisada(flujo_mvp.orden_creada()), motivo=motivo)


def test_sin_reparacion_guards():
    revisada = _revisada(flujo_mvp.orden_creada())
    with pytest.raises(PrecondicionInvalidaError):  # actor
        _sin_reparacion(revisada, usuario=TECNICO)
    with pytest.raises(PrecondicionInvalidaError):  # sin revision
        _sin_reparacion(flujo_mvp.orden_creada())
    with pytest.raises(PrecondicionInvalidaError):  # antes de 065
        _sin_reparacion(_en_revision(flujo_mvp.orden_creada()))
    with pytest.raises(PrecondicionInvalidaError):  # ya con Detalles
        _sin_reparacion(_definir(revisada))
    with pytest.raises(PrecondicionInvalidaError):  # una sola vez
        _sin_reparacion(_sin_reparacion(revisada))


def test_lista_para_cierre_sin_069_sigue_siendo_reparacion_lista():
    assert lista_para_cierre(flujo_mvp.orden_reparacion_lista()) is True
    assert lista_para_cierre(flujo_mvp.orden_con_factibilidad()) is False
    assert lista_para_cierre(_revisada(flujo_mvp.orden_creada())) is False
