"""Contrato de Compras (DEC-MI-09). Solo sobre PostgreSQL (DC23): en la demo
JSON el contexto no tiene repositorio de compras."""

from collections.abc import Sequence
from typing import Protocol

from app.domain.models import CambioConfiguracion
from app.domain.models.compras import (
    OrdenCompra,
    Proveedor,
    RecepcionCompra,
    SolicitudCompra,
)


class ComprasRepository(Protocol):
    def siguiente_codigo(self, prefijo: str) -> str:
        """El proximo codigo de PRV, SC u OC."""
        ...

    def listar_proveedores(self) -> list[Proveedor]: ...

    def guardar_proveedor(
        self,
        proveedor: Proveedor,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...

    def listar_solicitudes(self) -> list[SolicitudCompra]: ...

    def obtener_solicitud(self, codigo: str) -> SolicitudCompra: ...

    def agregar_solicitud(self, solicitud: SolicitudCompra) -> None: ...

    def actualizar_solicitud(self, solicitud: SolicitudCompra) -> None: ...

    def listar_ordenes(self) -> list[OrdenCompra]: ...

    def obtener_orden(
        self, codigo: str, *, bloquear: bool = False
    ) -> OrdenCompra:
        """Con ``bloquear``, nadie mas la modifica hasta el final de la
        transaccion (dos recepciones a la vez se aplican de a una)."""
        ...

    def agregar_orden(self, orden: OrdenCompra) -> None: ...

    def actualizar_orden(self, orden: OrdenCompra) -> None:
        """Confirmacion o cancelacion."""
        ...

    def agregar_recepcion(
        self, orden_id: str, recepcion: RecepcionCompra
    ) -> None: ...
