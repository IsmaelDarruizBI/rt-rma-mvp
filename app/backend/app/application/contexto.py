"""Contexto de aplicacion: dependencias que todo caso de uso necesita.

Los casos de uso de ``app.application`` no construyen repositories ni
leen configuracion: reciben este contexto. Asi la API puede armarlo una
vez al arrancar y un test puede armar otro apuntando a ``tmp_path``.

No contiene reglas de negocio: solo los dos repositories, el reloj y la
zona horaria del negocio (para fechas calendario como un vencimiento).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo

from app.core.config import Settings
from app.repositories import CatalogosRepository, OrdenReparacionRepository
from app.storage import JsonCatalogosRepository, JsonOrdenReparacionRepository

# Argentina (UTC-3, sin horario de verano). Se puede cambiar por
# configuracion (``RMA_UTC_OFFSET_HORAS``).
ZONA_HORARIA_NEGOCIO = timezone(timedelta(hours=-3))


def _ahora_utc() -> datetime:
    """Momento actual en UTC, con timezone explicita."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ApplicationContext:
    """Dependencias de infraestructura de los casos de uso."""

    ordenes: OrdenReparacionRepository
    catalogos: CatalogosRepository
    ahora: Callable[[], datetime] = field(default=_ahora_utc)
    zona_horaria: tzinfo = ZONA_HORARIA_NEGOCIO


def construir_contexto(settings: Settings) -> ApplicationContext:
    """Arma el contexto con el almacenamiento JSON configurado.

    Los directorios salen de ``RMA_DATA_DIR``; los repositories los
    crean si faltan.
    """
    return ApplicationContext(
        ordenes=JsonOrdenReparacionRepository(settings.ordenes_dir),
        catalogos=JsonCatalogosRepository(settings.catalogos_dir),
        zona_horaria=timezone(timedelta(hours=settings.utc_offset_horas)),
    )
