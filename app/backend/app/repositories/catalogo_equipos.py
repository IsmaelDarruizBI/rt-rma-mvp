"""Contrato de persistencia de la copia del catalogo de equipos de Ventas.

Pensado para que su implementacion definitiva sea PostgreSQL (tablas
``catalogo_producto`` y ``catalogo_sincronizacion``, ver
``traceability/IMPLEMENTATION.md``): cada operacion es una transaccion.
La implementacion JSON del MVP (``JsonCatalogoEquiposRepository``) cumple
el mismo contrato, pero en Cloud Run su archivo es efimero.

No hay borrado: un producto que Ventas deja de informar queda NO vigente,
nunca se elimina (puede estar referenciado por Ordenes).
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.domain.models import ProductoCatalogo, SincronizacionCatalogo


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
        """Los intentos registrados, del mas antiguo al mas reciente."""
        ...

    def registrar_sincronizacion(
        self, sincronizacion: SincronizacionCatalogo
    ) -> None:
        """Registra un intento que NO cambia el catalogo (fallido o
        rechazado)."""
        ...

    def aplicar_sincronizacion(
        self,
        sincronizacion: SincronizacionCatalogo,
        productos: Sequence[ProductoCatalogo],
    ) -> None:
        """Una sincronizacion exitosa: deja ``productos`` como la copia
        completa y registra el intento, en una sola operacion (o las dos
        cosas, o ninguna). ``productos`` incluye a los no vigentes."""
        ...
