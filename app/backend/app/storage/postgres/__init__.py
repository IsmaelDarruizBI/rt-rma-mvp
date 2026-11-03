"""Persistencia PostgreSQL (en preparacion, etapa E0).

Por ahora solo la configuracion de la conexion y la traduccion de
errores. Los repositories llegan en etapas siguientes; mientras tanto
``RMA_PERSISTENCIA=postgres`` detiene el arranque con un error explicito.
"""

from .conexion import (
    ConfiguracionPersistenciaError,
    ConfiguracionPostgres,
    conectar,
    configuracion_postgres,
    servidor_unico,
)
from .errores import es_reintentable, sqlstate, traducir_error

__all__ = [
    "ConfiguracionPersistenciaError",
    "ConfiguracionPostgres",
    "conectar",
    "configuracion_postgres",
    "es_reintentable",
    "servidor_unico",
    "sqlstate",
    "traducir_error",
]
