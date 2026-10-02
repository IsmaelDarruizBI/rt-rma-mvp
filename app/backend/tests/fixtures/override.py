"""Override de recursos desde PROC-REP-100, compuesto como la aplicacion.

El override es una capacidad transversal (ACC-REP-049,
``autorizar_override_recursos``). Solo con la Orden detenida en
PROC-REP-100 el proceso continua 110 "Si" -> 130
(``continuar_por_override``); la habilitacion (140) la agrega cada test.
"""

from datetime import datetime

from app.domain.models import OrdenReparacion, Usuario
from app.services import autorizar_override_recursos, continuar_por_override


def override_en_100(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
) -> OrdenReparacion:
    """Autoriza el Detalle y continua el circuito de PROC-REP-100."""
    orden = autorizar_override_recursos(
        orden,
        detalle_id=detalle_id,
        usuario=usuario,
        motivo=motivo,
        fecha=fecha,
    )
    return continuar_por_override(
        orden, detalle_id=detalle_id, usuario=usuario, fecha=fecha
    )
