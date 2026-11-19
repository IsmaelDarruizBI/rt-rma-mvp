"""Contrato de persistencia de la copia de Productos de Gestion RT.

Solo PostgreSQL (``PostgresProductosRtRepository``): tablas
``rma.producto_rt`` y ``rma.sincronizacion_origen`` (copia
``PRODUCTOS_RT``, migracion ``20261119000100``). En el modo JSON la copia
no existe (como Compras): la pantalla lo informa.

No hay borrado: lo que sale de Reparacion, se elimina en Gestion RT o deja
de aparecer queda marcado. El ciclo de una sincronizacion es el del motor
comun (``application.sincronizacion_origen``), igual que el catalogo de
Ventas: reservar -> leer fuera de toda transaccion -> aplicar (EXITOSA) o
registrar (FALLIDA o RECHAZADA). Solo quien reservo finaliza.

Las coincidencias sugeridas con Ordenes se calculan al consultar (no se
guardan): una sugerencia nunca es un vinculo (DEC-RT-03).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Protocol, runtime_checkable

from app.domain.models import (
    CoincidenciaSugerida,
    ProductoRt,
    ReservaSincronizacion,
    SincronizacionProductosRt,
)


class FiltroOrdenRma(str, Enum):
    """Filtro por coincidencias con Ordenes (etapa 1: solo sugerencias)."""

    SIN_COINCIDENCIAS = "SIN_COINCIDENCIAS"
    CON_SUGERENCIAS = "CON_SUGERENCIAS"


@dataclass(frozen=True)
class FiltroProductosRt:
    # Cada palabra debe aparecer en el ID, el IMEI o el equipo (ya
    # normalizadas: ``services.productos_rt.terminos_de_busqueda``).
    terminos: tuple[str, ...] = ()
    # Sedes exactas; ``None`` dentro de la tupla: sin sede.
    sedes: tuple[str | None, ...] = ()
    orden_rma: FiltroOrdenRma | None = None
    # Tambien los que salieron de Reparacion, los eliminados y los ausentes.
    incluir_fuera: bool = False
    pagina: int = 1
    tamano: int = 50


@dataclass(frozen=True)
class ProductoListado:
    producto: ProductoRt
    coincidencias: tuple[CoincidenciaSugerida, ...]


@dataclass(frozen=True)
class PaginaProductosRt:
    # Cantidad por sede con los demas filtros (sin el de sede).
    sedes: tuple[tuple[str | None, int], ...]
    total: int
    productos: tuple[ProductoListado, ...]


@runtime_checkable
class ProductosRtRepository(Protocol):
    """Acceso a la copia de Productos RT y a sus sincronizaciones."""

    def listar_productos(self) -> list[ProductoRt]:
        """Toda la copia (para la fusion de una sincronizacion)."""
        ...

    def obtener_producto(self, producto_id: str) -> ProductoRt | None: ...

    def buscar(self, filtro: FiltroProductosRt) -> PaginaProductosRt:
        """Una pagina del listado, con las coincidencias de cada producto."""
        ...

    def coincidencias(
        self, producto_id: str
    ) -> tuple[CoincidenciaSugerida, ...]:
        """Las Ordenes que coinciden con el producto (solo sugerencias)."""
        ...

    def listar_sincronizaciones(
        self, limite: int = 10
    ) -> list[SincronizacionProductosRt]:
        """Los ultimos intentos terminados, del mas reciente al mas viejo."""
        ...

    def ultima_exitosa(self) -> SincronizacionProductosRt | None: ...

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
        """``ReservaOcupadaError`` si hay otra en curso; una vencida se da
        por INTERRUMPIDA y deja lugar a esta."""
        ...

    def registrar_sincronizacion(
        self,
        sincronizacion: SincronizacionProductosRt,
        reserva: ReservaSincronizacion,
    ) -> None:
        """Finaliza un intento que NO cambia la copia."""
        ...

    def aplicar_sincronizacion(
        self,
        sincronizacion: SincronizacionProductosRt,
        productos: Sequence[ProductoRt],
        reserva: ReservaSincronizacion,
    ) -> None:
        """La copia completa y el intento EXITOSA, en una sola operacion."""
        ...
