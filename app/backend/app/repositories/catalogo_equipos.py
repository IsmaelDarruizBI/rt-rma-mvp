"""Contrato de persistencia de la copia del catalogo de equipos de Ventas.

Dos implementaciones con el mismo contrato:

- ``PostgresCatalogoEquiposRepository`` (``RMA_PERSISTENCIA=postgres``):
  tablas ``rma.catalogo_producto`` y ``rma.sincronizacion_origen``
  (migracion ``20261117000100``). La copia sobrevive a reinicios y al
  escalado a cero, y la reserva vale entre instancias.
- ``JsonCatalogoEquiposRepository`` (modo JSON, desarrollo local): un
  archivo, con la reserva como candado del proceso.

No hay borrado: un producto que Ventas deja de informar queda NO vigente,
nunca se elimina (puede estar referenciado por Ordenes).

Ciclo de una sincronizacion (lo ejecuta ``application.sincronizacion_origen``):
``reservar_sincronizacion`` -> leer el origen (fuera de toda transaccion) ->
``aplicar_sincronizacion`` (EXITOSA) o ``registrar_sincronizacion``
(FALLIDA o RECHAZADA). Solo quien reservo finaliza: la reserva lleva el
secreto que lo prueba.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol, runtime_checkable

from app.domain.models import (
    ProductoCatalogo,
    ReservaSincronizacion,
    SincronizacionCatalogo,
)


@runtime_checkable
class CatalogoEquiposRepository(Protocol):
    """Acceso a la copia del catalogo y al registro de sincronizaciones."""

    def listar_productos(self) -> list[ProductoCatalogo]:
        """Todos los productos de la copia (vigentes o no)."""
        ...

    def obtener_producto(
        self, tipo_producto_id: str
    ) -> ProductoCatalogo | None:
        """El producto con ese ``tp_id``, o ``None``."""
        ...

    def listar_sincronizaciones(self) -> list[SincronizacionCatalogo]:
        """Los intentos terminados, del mas antiguo al mas reciente."""
        ...

    def reservar_sincronizacion(
        self,
        *,
        id: str,
        usuario_id: str,
        origen: str,
        filtro: str,
        duracion: timedelta,
        propietario: str,
    ) -> ReservaSincronizacion:
        """Reserva la sincronizacion de la copia por ``duracion``.

        Lanza ``ReservaOcupadaError`` si hay otra en curso. Una reserva
        vencida (instancia apagada a mitad) se da por INTERRUMPIDA y deja
        lugar a esta. ``propietario`` es el secreto de quien reserva."""
        ...

    def registrar_sincronizacion(
        self,
        sincronizacion: SincronizacionCatalogo,
        reserva: ReservaSincronizacion | None = None,
    ) -> None:
        """Finaliza un intento que NO cambia el catalogo (FALLIDA o
        RECHAZADA). Con ``reserva``, la libera."""
        ...

    def aplicar_sincronizacion(
        self,
        sincronizacion: SincronizacionCatalogo,
        productos: Sequence[ProductoCatalogo],
        reserva: ReservaSincronizacion | None = None,
    ) -> None:
        """Una sincronizacion exitosa: deja ``productos`` como la copia
        completa y registra el intento, en una sola operacion (o las dos
        cosas, o ninguna). ``productos`` incluye a los no vigentes. Con
        ``reserva``, la libera."""
        ...
