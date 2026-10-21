"""Capa de storage: implementaciones concretas de persistencia.

En el MVP la implementacion es file-based (JSON bajo ``data/``), en
``app.storage.json``. Cumple los contratos de ``app.repositories`` y
puede reemplazarse -por Cloud Storage, una base de datos u otro backend-
sin tocar ``domain`` ni ``services``.
"""

from .fotos import (
    AlmacenFotos,
    AlmacenFotosDirectorio,
    AlmacenFotosError,
    AlmacenFotosGcs,
    AlmacenFotosMemoria,
    ObjetoFoto,
)
from .json import JsonCatalogosRepository, JsonOrdenReparacionRepository

__all__ = [
    "AlmacenFotos",
    "AlmacenFotosDirectorio",
    "AlmacenFotosError",
    "AlmacenFotosGcs",
    "AlmacenFotosMemoria",
    "ObjetoFoto",
    "JsonCatalogosRepository",
    "JsonOrdenReparacionRepository",
]
