"""Identificadores legibles que la aplicacion asigna a lo que crea.

``app.services.identificadores`` genera IDs opacos para entidades
internas (tomas, ejecuciones, movimientos, pagos). Estos, en cambio, son
los que una persona lee y dicta por telefono: el numero de Orden y el
numero de Detalle dentro de ella.

El numero de Orden lo reserva el repository (``reservar_codigo``, E2):
en JSON, el maximo persistido mas uno; en PostgreSQL, una secuencia.
Exige la transaccion del alta, para que dos altas simultaneas no reciban
el mismo numero.
"""

import re

from app.domain.models import OrdenReparacion
from app.repositories import OrdenReparacionRepository

PREFIJO_DETALLE = "DET"

_PATRON_DETALLE = re.compile(rf"^{PREFIJO_DETALLE}-(\d+)$")


def siguiente_orden_id(ordenes: OrdenReparacionRepository) -> str:
    """Proximo numero de Orden libre, con formato ``OR-000001``.

    Ignora los IDs que no siguen el patron: una Orden importada con otro
    formato no rompe la numeracion.
    """
    return ordenes.reservar_codigo()


def siguiente_detalle_id(orden: OrdenReparacion) -> str:
    """Proximo numero de Detalle dentro de la Orden (``DET-001``)."""
    maximo = 0
    for detalle in orden.reparaciones_detail:
        encontrado = _PATRON_DETALLE.match(detalle.id)
        if encontrado:
            maximo = max(maximo, int(encontrado.group(1)))
    return f"{PREFIJO_DETALLE}-{maximo + 1:03d}"


def siguientes_detalle_ids(orden: OrdenReparacion, cantidad: int) -> list[str]:
    """Los ``cantidad`` proximos numeros de Detalle, consecutivos."""
    primero = int(siguiente_detalle_id(orden).rsplit("-", 1)[1])
    return [
        f"{PREFIJO_DETALLE}-{numero:03d}"
        for numero in range(primero, primero + cantidad)
    ]
