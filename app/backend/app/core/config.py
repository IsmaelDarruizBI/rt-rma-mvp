"""Configuracion tecnica transversal del backend MVP.

Parametrizable por variables de entorno con prefijo ``RMA_`` (por
ejemplo ``RMA_CORS_ALLOW_ORIGINS`` o ``RMA_DATA_DIR``). No contiene
reglas de negocio.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# ``app/backend/data``: el directorio versionado con los catalogos DEMO
# y las Ordenes de desarrollo local.
DATA_DIR_POR_DEFECTO = Path(__file__).resolve().parents[2] / "data"


class Settings(BaseSettings):
    """Ajustes de la aplicacion, con valores por defecto de desarrollo."""

    model_config = SettingsConfigDict(
        env_prefix="RMA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Rosario Tecno RMA API"
    app_version: str = "0.1.0"

    # Origenes permitidos para el frontend Vite en desarrollo local.
    cors_allow_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Raiz del almacenamiento JSON. Debajo cuelgan ``ordenes/`` y
    # ``catalogs/``. Los tests siempre apuntan a un ``tmp_path``, nunca
    # a este default, para no tocar los JSON DEMO versionados.
    data_dir: Path = DATA_DIR_POR_DEFECTO

    # Desfasaje horario del negocio respecto de UTC, en horas. Las fechas
    # se guardan en UTC; este valor solo fija el dia calendario local (por
    # ejemplo, el vencimiento de una garantia). Argentina: -3, sin horario
    # de verano. Fijo a proposito: no depende de la base de zonas horarias
    # del sistema operativo.
    utc_offset_horas: int = -3

    @property
    def ordenes_dir(self) -> Path:
        """Directorio de las Ordenes persistidas."""
        return self.data_dir / "ordenes"

    @property
    def catalogos_dir(self) -> Path:
        """Directorio de los catalogos persistidos."""
        return self.data_dir / "catalogs"


@lru_cache
def get_settings() -> Settings:
    """Devuelve los ajustes cacheados para toda la vida del proceso."""
    return Settings()
