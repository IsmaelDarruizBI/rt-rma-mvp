"""Reserva de una sincronizacion de una copia de un origen externo.

Una copia (el catalogo de Ventas; despues, los Productos de Gestion RT) se
sincroniza de a una vez por copia, entre todas las instancias. Quien
reserva recibe ``propietario``: un secreto aleatorio que solo conoce esa
sincronizacion. La base guarda su hash y exige el secreto para escribir la
copia y para finalizar el intento (QA C1, M3): nadie mas puede hacerlo.

``propietario`` nunca se registra ni se muestra (fuera de ``repr``).
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ReservaSincronizacion:
    id: str
    copia: str
    usuario_id: str
    origen: str
    filtro: str
    iniciada_en: datetime
    vence_en: datetime
    propietario: str = field(repr=False)
