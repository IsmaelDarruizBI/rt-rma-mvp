"""Persistencia PostgreSQL (en preparacion).

E0: configuracion de la conexion y traduccion de errores. E1: la unidad
de trabajo (``app.storage.postgres.transaccion``), que requiere psycopg y
por eso no se importa desde aca. Los repositories llegan en etapas
siguientes; mientras tanto ``RMA_PERSISTENCIA=postgres`` detiene el
arranque con un error explicito.
"""

from .ajustes import AjustesPostgres, ajustes_postgres
from .conexion import (
    ConfiguracionPersistenciaError,
    ConfiguracionPostgres,
    conectar,
    configuracion_postgres,
    servidor_unico,
)
from .errores import es_reintentable, sqlstate, traducir_error

__all__ = [
    "AjustesPostgres",
    "ConfiguracionPersistenciaError",
    "ConfiguracionPostgres",
    "ajustes_postgres",
    "conectar",
    "configuracion_postgres",
    "es_reintentable",
    "servidor_unico",
    "sqlstate",
    "traducir_error",
]
