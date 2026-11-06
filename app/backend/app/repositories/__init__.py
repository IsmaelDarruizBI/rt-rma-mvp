"""Capa de repositorios: contratos/interfaces de acceso a datos.

Define QUE se necesita persistir o recuperar, nunca COMO. Las
implementaciones concretas viven en ``app.storage``.

Los services dependen de estos contratos, no de ninguna implementacion:
esa es la frontera que permite reemplazar el almacenamiento JSON del MVP
por Cloud Storage, PostgreSQL u otro backend sin tocar el dominio.
"""

from .catalogo_equipos import CatalogoEquiposRepository
from .catalogos import CatalogosRepository
from .exceptions import (
    ConflictoDeEscrituraError,
    DatosInvalidosError,
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
    PersistenciaNoDisponibleError,
    PersistenciaSinConexionError,
    RepositoryError,
    RestriccionDeIntegridadError,
    TransaccionInvalidadaError,
)
from .modelos_equipo import ModelosEquipoRepository
from .ordenes import OrdenReparacionRepository
from .unidad_de_trabajo import UnidadDeTrabajo

__all__ = [
    "CatalogoEquiposRepository",
    "CatalogosRepository",
    "ConflictoDeEscrituraError",
    "DatosInvalidosError",
    "EntidadPersistidaNoEncontradaError",
    "ModelosEquipoRepository",
    "OrdenReparacionRepository",
    "PersistenciaError",
    "PersistenciaNoDisponibleError",
    "PersistenciaSinConexionError",
    "RepositoryError",
    "RestriccionDeIntegridadError",
    "TransaccionInvalidadaError",
    "UnidadDeTrabajo",
]
