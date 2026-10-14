"""Capa de repositorios: contratos/interfaces de acceso a datos.

Define QUE se necesita persistir o recuperar, nunca COMO. Las
implementaciones concretas viven en ``app.storage``.

Los services dependen de estos contratos, no de ninguna implementacion:
esa es la frontera que permite reemplazar el almacenamiento JSON del MVP
por Cloud Storage, PostgreSQL u otro backend sin tocar el dominio.
"""

from .catalogos import CatalogosRepository
from .exceptions import (
    ConflictoDeEscrituraError,
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
    RepositoryError,
)
from .ordenes import OrdenReparacionRepository

__all__ = [
    "CatalogosRepository",
    "ConflictoDeEscrituraError",
    "EntidadPersistidaNoEncontradaError",
    "OrdenReparacionRepository",
    "PersistenciaError",
    "RepositoryError",
]
