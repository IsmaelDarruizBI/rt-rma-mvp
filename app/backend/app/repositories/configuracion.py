"""Contrato de la administracion de catalogos (DC23, DC23AUD).

Cada escritura guarda el catalogo y su auditoria en la misma transaccion
(diseno logico V1.4, seccion 4). Solo la implementa PostgreSQL: DC23 pide
la administracion sobre la persistencia definitiva, no sobre los JSON.
"""

from collections.abc import Collection, Sequence
from typing import Protocol

from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    TipoReparacion,
)


class ConfiguracionRepository(Protocol):
    def guardar_tipo_reparacion(
        self,
        tipo: TipoReparacion,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        """Alta o edicion del Tipo, con sus cambios auditados."""
        ...

    def guardar_tipos_de_mesa(
        self,
        estacion_id: str,
        tipo_ids: Collection[str],
        cambio: CambioConfiguracion,
    ) -> None:
        """Reemplaza los Tipos habilitados de la Mesa, con su auditoria."""
        ...

    def listar_cambios(
        self,
        *,
        entidad: EntidadConfiguracion | None = None,
        clave: str | None = None,
    ) -> list[CambioConfiguracion]:
        """La auditoria, de la mas vieja a la mas nueva."""
        ...
