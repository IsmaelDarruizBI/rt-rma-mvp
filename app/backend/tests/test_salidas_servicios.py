"""Salidas del proceso a nivel de services y resolver (sin HTTP).

Cancelacion (PROC-REP-300/305), rechazo del control (PROC-REP-235) y E14,
con las mismas fixtures puras del Happy Path. Los services devuelven una
Orden nueva y nunca modifican la recibida, tampoco cuando fallan.
"""

from decimal import Decimal

import pytest

from app.domain.models import (
    CondicionReparacionDetail,
    EstadoControl,
    EstadoReparacionDetail,
    ReparacionDetail,
    ResultadoControl,
)
from app.services import (
    PrecondicionInvalidaError,
    ResultadoEvaluacionOrden,
    aprobar_control_tecnico,
    cancelar_detalle,
    rechazar_control_tecnico,
    resolver_situacion_orden,
)
from tests.fixtures import flujo_mvp
from tests.fixtures.catalogos_mvp import RECEPCION, TECNICO, t


def _detalle(detalle_id, estado, condicion=None):
    return ReparacionDetail(
        id=detalle_id,
        tipo_reparacion_id="TR-001",
        precio=Decimal("100"),
        puntaje=1,
        garantia_dias=30,
        estado=estado,
        condicion=condicion or CondicionReparacionDetail.SIN_BLOQUEO,
    )


CANCELADO = EstadoReparacionDetail.CANCELADO
COMPLETO = EstadoReparacionDetail.COMPLETO
DEFINIDO = EstadoReparacionDetail.DEFINIDO


@pytest.mark.parametrize(
    ("detalles", "esperado"),
    [
        (
            [_detalle("A", CANCELADO), _detalle("B", CANCELADO)],
            ResultadoEvaluacionOrden.TODO_CANCELADO,
        ),
        (
            [_detalle("A", COMPLETO), _detalle("B", CANCELADO)],
            ResultadoEvaluacionOrden.COMPLETA,
        ),
        (
            [_detalle("A", CANCELADO), _detalle("B", DEFINIDO)],
            ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE,
        ),
        (
            [
                _detalle("A", CANCELADO),
                _detalle(
                    "B",
                    DEFINIDO,
                    CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS,
                ),
            ],
            ResultadoEvaluacionOrden.PENDIENTE_RECURSOS,
        ),
        (
            [
                _detalle("A", CANCELADO),
                _detalle(
                    "B",
                    DEFINIDO,
                    CondicionReparacionDetail.REQUIERE_DEFINICION,
                ),
            ],
            ResultadoEvaluacionOrden.REQUIERE_REVISION,
        ),
    ],
    ids=[
        "todos_cancelados",
        "completo_y_cancelado",
        "cancelado_y_trabajable",
        "cancelado_y_sin_recursos",
        "cancelado_y_por_redefinir",
    ],
)
def test_el_resolver_clasifica_los_detalles_cancelados(detalles, esperado):
    assert resolver_situacion_orden(detalles) is esperado


def test_un_detalle_cancelado_no_suma_al_total():
    orden = flujo_mvp.orden_con_detalle()
    assert orden.total == Decimal("80000")

    cancelada = cancelar_detalle(
        orden,
        detalle_id=flujo_mvp.DETALLE_ID,
        usuario=RECEPCION,
        motivo="Desiste.",
        fecha=t(30),
    )

    assert cancelada.total == Decimal("0")
    (detalle,) = cancelada.reparaciones_detail
    assert detalle.estado is CANCELADO
    assert detalle.cancelacion.motivo == "Desiste."
    assert detalle.cancelacion.usuario_id == RECEPCION.id
    assert detalle.cancelacion.fecha == t(30)
    # La Orden recibida no cambio.
    assert orden.reparaciones_detail[0].estado is DEFINIDO


def test_cancelar_detalle_valida_rol_y_estado_sin_mutar():
    con_ejecucion = flujo_mvp.orden_con_ejecucion_iniciada()
    antes = con_ejecucion.model_dump(mode="json")

    with pytest.raises(PrecondicionInvalidaError):
        cancelar_detalle(
            con_ejecucion,
            detalle_id=flujo_mvp.DETALLE_ID,
            usuario=RECEPCION,
            motivo="x",
            fecha=t(80),
        )
    with pytest.raises(PrecondicionInvalidaError):
        cancelar_detalle(
            flujo_mvp.orden_con_detalle(),
            detalle_id=flujo_mvp.DETALLE_ID,
            usuario=TECNICO,
            motivo="x",
            fecha=t(80),
        )

    assert con_ejecucion.model_dump(mode="json") == antes


def test_e14_aprobar_dos_veces_falla_sin_tocar_la_primera():
    aprobada = flujo_mvp.orden_controlada()
    (detalle,) = aprobada.reparaciones_detail
    antes = aprobada.model_dump(mode="json")

    with pytest.raises(PrecondicionInvalidaError, match="ya fue aprobado"):
        aprobar_control_tecnico(
            aprobada,
            usuario=RECEPCION,
            fecha=t(999),
            detalle_id=detalle.id,
        )

    assert aprobada.model_dump(mode="json") == antes
    assert [c.resultado for c in detalle.controles] == [
        ResultadoControl.APROBADO
    ]


def test_rechazar_reabre_el_detalle_y_conserva_la_ejecucion():
    evaluada = flujo_mvp.orden_evaluada()
    ejecucion = evaluada.ejecuciones[0]

    rechazada = rechazar_control_tecnico(
        evaluada,
        detalle_id=flujo_mvp.DETALLE_ID,
        usuario=RECEPCION,
        motivo="No funciona.",
        fecha=t(160),
    )

    (detalle,) = rechazada.reparaciones_detail
    assert detalle.estado is DEFINIDO
    assert detalle.condicion is CondicionReparacionDetail.SIN_BLOQUEO
    assert detalle.control_estado is EstadoControl.PENDIENTE
    (control,) = detalle.controles
    assert control.resultado is ResultadoControl.RECHAZADO
    assert control.ejecucion_id == ejecucion.id
    assert rechazada.ejecuciones == evaluada.ejecuciones
    assert rechazada.movimientos_insumo == evaluada.movimientos_insumo
    assert [p.process_id for p in rechazada.historial][-3:] == [
        "PROC-REP-220",
        "PROC-REP-230",
        "PROC-REP-235",
    ]
    # La Orden recibida no cambio.
    assert evaluada.reparaciones_detail[0].estado is COMPLETO


def test_rechazar_exige_motivo_y_recepcion():
    evaluada = flujo_mvp.orden_evaluada()

    for usuario, motivo in ((RECEPCION, "  "), (TECNICO, "No funciona.")):
        with pytest.raises(PrecondicionInvalidaError):
            rechazar_control_tecnico(
                evaluada,
                detalle_id=flujo_mvp.DETALLE_ID,
                usuario=usuario,
                motivo=motivo,
                fecha=t(160),
            )
