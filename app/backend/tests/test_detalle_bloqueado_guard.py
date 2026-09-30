"""Un Detalle bloqueado no se puede seleccionar ni iniciar, ni por API.

``application/acciones.py`` ya deja de OFRECER estas acciones para un
Detalle DEFINIDO pero bloqueado (``REQUIERE_DEFINICION`` o
``BLOQUEADO_POR_RECURSOS``, ver ``test_acciones_disponibles.py``). Pero
ocultar el boton es UX, no autorizacion: estos tests comprueban que los
services de backend RECHAZAN el intento aunque venga directo, sin pasar
por ``acciones_disponibles`` (por ejemplo, una llamada de API hecha a
mano con un ``detalle_id`` que la UI nunca hubiera ofrecido).

Solo ``DEFINIDO + SIN_BLOQUEO`` es trabajable -consistente con
``services.resolucion._es_trabajable`` y con
``application.acciones.detalles_trabajables``-.
"""

import pytest

from app.domain.models import CondicionReparacionDetail
from app.services import (
    PrecondicionInvalidaError,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
    tomar_orden,
    validar_estacion_trabajo,
)

from .fixtures import flujo_mvp
from .fixtures.catalogos_mvp import (
    COMPATIBILIDADES,
    ESTACION,
    ESTACIONES,
    INSUMOS,
    INSUMOS_PREVISTOS,
    TECNICO,
    t,
)

CONDICIONES_BLOQUEADAS = [
    CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS,
    CondicionReparacionDetail.REQUIERE_DEFINICION,
]


def _orden_tomada_sin_seleccionar():
    """Orden EN_COLA -> tomada, pero SIN pasar por seleccionar_detalle.

    A diferencia de ``flujo_mvp.orden_tomada()`` (que ya selecciono y
    validado el Detalle), esto deja el Detalle intacto para poder
    mutarle la condicion ANTES de intentar seleccionarlo.
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
    return tomar_orden(
        orden, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )


@pytest.mark.parametrize("condicion", CONDICIONES_BLOQUEADAS)
def test_seleccionar_detalle_rechaza_detalle_bloqueado(condicion):
    orden = _orden_tomada_sin_seleccionar()
    orden.reparaciones_detail[0].condicion = condicion

    with pytest.raises(PrecondicionInvalidaError):
        seleccionar_detalle(
            orden,
            detalle_id=flujo_mvp.DETALLE_ID,
            usuario=TECNICO,
            fecha=t(62),
        )


def test_seleccionar_detalle_permite_sin_bloqueo():
    """Control: la misma Orden, sin mutar, SI se puede seleccionar."""
    orden = _orden_tomada_sin_seleccionar()

    orden = seleccionar_detalle(
        orden,
        detalle_id=flujo_mvp.DETALLE_ID,
        usuario=TECNICO,
        fecha=t(62),
    )

    assert orden.current_process == "PROC-REP-181"


@pytest.mark.parametrize("condicion", CONDICIONES_BLOQUEADAS)
def test_reservar_insumos_rechaza_detalle_bloqueado(condicion):
    """El guard tambien aplica a PROC-REP-185, independiente de 181.

    Simula una llamada directa (por ejemplo, de API) que se salteara
    ``seleccionar_detalle``: el service de reserva no debe confiar en
    que el caller ya filtro por condicion.
    """
    orden = flujo_mvp.orden_tomada()
    orden.reparaciones_detail[0].condicion = condicion

    with pytest.raises(PrecondicionInvalidaError):
        reservar_insumos_e_iniciar_ejecucion(
            orden,
            detalle_id=flujo_mvp.DETALLE_ID,
            usuario=TECNICO,
            insumos=INSUMOS,
            insumos_previstos=INSUMOS_PREVISTOS,
            fecha=t(65),
        )


@pytest.mark.parametrize("condicion", CONDICIONES_BLOQUEADAS)
def test_validar_estacion_trabajo_rechaza_si_el_unico_detalle_esta_bloqueado(
    condicion,
):
    orden = flujo_mvp.orden_en_cola()
    orden.reparaciones_detail[0].condicion = condicion

    _, valida = validar_estacion_trabajo(
        orden,
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )

    assert valida is False
