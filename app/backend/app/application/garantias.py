"""Garantia por Detalle: ajuste manual del plazo (MVP v2).

ajustar_garantia   Recepcion o Coordinacion cambia el plazo definitivo
                   de UN Detalle, con motivo (el sugerido se conserva)
"""

from app.domain.models import OrdenReparacion
from app.services import ajustar_garantia_detalle

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar


def ajustar_garantia(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
    usuario_id: str,
    dias: int,
    motivo: str,
) -> OrdenReparacion:
    """Cambia el plazo de garantia de un Detalle antes de la entrega."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = ajustar_garantia_detalle(
            orden,
            detalle_id=detalle_id,
            dias=dias,
            motivo=motivo,
            usuario=usuario,
            fecha=fecha,
        )
        contexto.ordenes.guardar(orden)
    return orden
