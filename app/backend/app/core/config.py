"""Configuracion tecnica transversal del backend MVP.

Parametrizable por variables de entorno con prefijo ``RMA_`` (por
ejemplo ``RMA_CORS_ALLOW_ORIGINS`` o ``RMA_DATA_DIR``). No contiene
reglas de negocio.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

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

    # Fotos del equipo (UAT-010). En Cloud Run: un bucket PRIVADO de
    # Cloud Storage (``RMA_FOTOS_BUCKET``). ``RMA_FOTOS_DIR`` es solo para
    # desarrollo local. Sin ninguno de los dos, las fotos estan
    # deshabilitadas: nunca se guardan en el disco efimero del servidor.
    fotos_bucket: str | None = None
    fotos_dir: Path | None = None

    # Consulta externa de datos por DNI: limites (solo si hay una fuente
    # autorizada configurada; hoy ninguna).
    consulta_dni_intervalo_s: float = 2.0
    consulta_dni_max_por_minuto: int = 10

    # Catalogo de equipos de Gestion de Ventas. RMA guarda una copia y la
    # actualiza a pedido (sincronizacion manual); el alta de una Orden
    # nunca consulta el origen. Toda la configuracion del origen esta aca
    # y la traduce a un adaptador ``integraciones.catalogo.configuracion``.
    #   ninguno        sin origen: no se sincroniza
    #   google_sheets  la hoja de Ventas (solo lectura)
    #   archivo        un CSV con las mismas columnas (desarrollo)
    catalogo_origen: Literal["ninguno", "google_sheets", "archivo"] = "ninguno"
    # Que parte del catalogo se copia (``tp_subcat_1``).
    catalogo_subcategorias: list[str] = ["IPHONE USADOS"]
    # Marca por ``tp_categoria`` (Ventas no tiene columna de marca). Una
    # categoria sin marca deja sus productos fuera del selector.
    catalogo_marcas: dict[str, str] = {"IPHONE": "Apple"}
    catalogo_sheets_planilla: str | None = None
    catalogo_sheets_hoja: str = "raw_TipoProducto"
    # cloud_run: la identidad del servicio (o, con ``cuenta``, la cuenta
    # que esa identidad impersona). gcloud: solo desarrollo local.
    catalogo_sheets_credencial: Literal["cloud_run", "gcloud"] = "cloud_run"
    catalogo_sheets_cuenta: str | None = None
    catalogo_archivo: Path | None = None
    catalogo_timeout_s: float = 30.0

    @property
    def ordenes_dir(self) -> Path:
        """Directorio de las Ordenes persistidas."""
        return self.data_dir / "ordenes"

    @property
    def catalogos_dir(self) -> Path:
        """Directorio de los catalogos persistidos."""
        return self.data_dir / "catalogs"

    @property
    def catalogo_equipos_dir(self) -> Path:
        """Copia del catalogo de equipos de Ventas y sus sincronizaciones.

        Aparte de ``catalogs/`` (los catalogos DEMO versionados): la
        sincronizacion nunca los toca.
        """
        return self.data_dir / "catalogo_equipos"


@lru_cache
def get_settings() -> Settings:
    """Devuelve los ajustes cacheados para toda la vida del proceso."""
    return Settings()
