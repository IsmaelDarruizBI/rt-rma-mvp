"""``application.acciones``: consistencia con el resolver de BR-REP-012.

Un Detalle DEFINIDO pero bloqueado no es trabajable: ni para el
resolver (``services.resolucion._es_trabajable``) ni para la accion
INICIAR_DETALLE que la Orden ofrece.
"""

from app.application.acciones import (
    ACCION_INICIAR_DETALLE,
    acciones_disponibles,
    detalle_trabajable,
)
from app.domain.models import CondicionReparacionDetail

from .fixtures import flujo_mvp


def test_un_detalle_bloqueado_por_recursos_no_es_trabajable():
    orden = flujo_mvp.orden_tomada()
    orden.reparaciones_detail[0].condicion = (
        CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    )

    assert detalle_trabajable(orden) is None


def test_un_detalle_bloqueado_por_recursos_no_ofrece_iniciar_detalle():
    orden = flujo_mvp.orden_tomada()
    orden.reparaciones_detail[0].condicion = (
        CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    )

    codigos = [accion.codigo for accion in acciones_disponibles(orden)]

    assert ACCION_INICIAR_DETALLE not in codigos
