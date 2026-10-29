"""Contrato de lectura del catalogo tecnico de modelos de equipo.

Solo lectura: el MVP no administra el catalogo (se versiona con el
codigo). Los modelos inactivos se siguen devolviendo: una Orden puede
referenciarlos.
"""

from typing import Protocol, runtime_checkable

from app.domain.models import ModeloEquipo


@runtime_checkable
class ModelosEquipoRepository(Protocol):
    """Acceso al catalogo tecnico de modelos."""

    def listar_modelos(self) -> list[ModeloEquipo]:
        """Todos los modelos (activos o no), en el orden del catalogo."""
        ...

    def obtener_modelo(self, modelo_id: str) -> ModeloEquipo | None:
        """El modelo con ese ID, o ``None``."""
        ...
