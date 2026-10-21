"""Integraciones con servicios externos (fuentes de datos de terceros)."""

from .personas import (
    EstadoFuente,
    FuentePersonas,
    LimitadorConsultas,
    PersonaExterna,
    ResultadoFuente,
)

__all__ = [
    "EstadoFuente",
    "FuentePersonas",
    "LimitadorConsultas",
    "PersonaExterna",
    "ResultadoFuente",
]
