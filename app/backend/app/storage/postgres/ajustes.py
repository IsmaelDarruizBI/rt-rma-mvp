"""Ajustes del pool y de las transacciones de PostgreSQL (E1, E3).

Se validan sin psycopg, junto con la URL, para que un valor imposible
detenga el arranque en vez de aparecer en el primer comando.
"""

import math
from dataclasses import dataclass

from app.core.config import Settings

from .conexion import ConfiguracionPersistenciaError

# Topes (E3, L1). Los milisegundos van a ``SET LOCAL``, que acepta un
# entero de 32 bits: un valor mayor rompe cada transaccion. El pool no
# supera el limite de conexiones del rol de la aplicacion.
MAXIMO_MS = 2_147_483_647
MAXIMO_POOL = 20


@dataclass(frozen=True)
class AjustesPostgres:
    """Tamano del pool, espera por una conexion y limites por transaccion."""

    pool_min: int = 1
    pool_max: int = 4
    pool_espera_s: float = 5.0
    lock_timeout_ms: int = 5000
    statement_timeout_ms: int = 15000
    pool_max_idle_s: float = 300.0


def ajustes_postgres(settings: Settings) -> AjustesPostgres:
    """Los ``RMA_DB_*`` del pool y de las transacciones, validados."""
    ajustes = AjustesPostgres(
        pool_min=settings.db_pool_min,
        pool_max=settings.db_pool_max,
        pool_espera_s=settings.db_pool_espera_s,
        lock_timeout_ms=settings.db_lock_timeout_ms,
        statement_timeout_ms=settings.db_statement_timeout_ms,
        pool_max_idle_s=settings.db_pool_max_idle_s,
    )
    validar_ajustes(ajustes)
    return ajustes


def validar_ajustes(ajustes: AjustesPostgres) -> None:
    """ConfiguracionPersistenciaError si algun valor no es utilizable."""
    if ajustes.pool_min < 0 or ajustes.pool_max < 1:
        raise ConfiguracionPersistenciaError(
            "RMA_DB_POOL_MIN no puede ser negativo y RMA_DB_POOL_MAX debe "
            "ser al menos 1."
        )
    if ajustes.pool_min > ajustes.pool_max:
        raise ConfiguracionPersistenciaError(
            "RMA_DB_POOL_MIN no puede superar a RMA_DB_POOL_MAX."
        )
    if ajustes.pool_max > MAXIMO_POOL:
        raise ConfiguracionPersistenciaError(
            f"RMA_DB_POOL_MAX no puede superar {MAXIMO_POOL}: es el limite "
            "de conexiones del rol de la aplicacion."
        )
    if not _positivo_finito(ajustes.pool_espera_s):
        raise ConfiguracionPersistenciaError(
            "RMA_DB_POOL_ESPERA_S debe ser mayor que cero."
        )
    if not _positivo_finito(ajustes.pool_max_idle_s):
        raise ConfiguracionPersistenciaError(
            "RMA_DB_POOL_MAX_IDLE_S debe ser mayor que cero."
        )
    # Cero desactivaria el limite: una transaccion podria quedar
    # esperando sin fin.
    if ajustes.lock_timeout_ms < 1 or ajustes.statement_timeout_ms < 1:
        raise ConfiguracionPersistenciaError(
            "RMA_DB_LOCK_TIMEOUT_MS y RMA_DB_STATEMENT_TIMEOUT_MS deben ser "
            "de al menos 1 ms."
        )
    if max(ajustes.lock_timeout_ms, ajustes.statement_timeout_ms) > (
        MAXIMO_MS
    ):
        raise ConfiguracionPersistenciaError(
            "RMA_DB_LOCK_TIMEOUT_MS y RMA_DB_STATEMENT_TIMEOUT_MS no pueden "
            f"superar {MAXIMO_MS} ms."
        )


def _positivo_finito(valor: float) -> bool:
    return math.isfinite(valor) and valor > 0
