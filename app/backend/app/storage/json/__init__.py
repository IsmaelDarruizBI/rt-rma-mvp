"""Implementacion JSON/file-based del almacenamiento del MVP.

Pese al nombre del paquete, ``import json`` dentro de estos modulos
resuelve al modulo estandar: Python 3 usa imports absolutos.
"""

from .base import asegurar_directorio, escribir_json_atomico, leer_json
from .catalogo_equipos import JsonCatalogoEquiposRepository
from .catalogos import JsonCatalogosRepository
from .ordenes import JsonOrdenReparacionRepository

__all__ = [
    "JsonCatalogoEquiposRepository",
    "JsonCatalogosRepository",
    "JsonOrdenReparacionRepository",
    "asegurar_directorio",
    "escribir_json_atomico",
    "leer_json",
]
