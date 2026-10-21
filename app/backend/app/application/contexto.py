"""Contexto de aplicacion: dependencias que todo caso de uso necesita.

Los casos de uso de ``app.application`` no construyen repositories ni
leen configuracion: reciben este contexto. Asi la API puede armarlo una
vez al arrancar y un test puede armar otro apuntando a ``tmp_path``.

No contiene reglas de negocio: solo los dos repositories, el reloj, la
zona horaria del negocio (para fechas calendario como un vencimiento) y,
desde UAT-010, el almacenamiento de fotos y la fuente externa de datos por
DNI (ambos opcionales: sin ellos, esas funciones quedan deshabilitadas).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo

from app.core.config import Settings
from app.integraciones import FuentePersonas, LimitadorConsultas
from app.repositories import CatalogosRepository, OrdenReparacionRepository
from app.storage import (
    AlmacenFotos,
    AlmacenFotosDirectorio,
    AlmacenFotosGcs,
    JsonCatalogosRepository,
    JsonOrdenReparacionRepository,
)

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
    fotos: AlmacenFotos | None = None
    fuente_personas: FuentePersonas | None = None
    limitador_personas: LimitadorConsultas = field(
        default_factory=LimitadorConsultas
    )


def _almacen_de_fotos(settings: Settings) -> AlmacenFotos | None:
    """El bucket privado si esta configurado; un directorio, solo en
    desarrollo; si no, ninguno (fotos deshabilitadas)."""
    if settings.fotos_bucket:
        return AlmacenFotosGcs(settings.fotos_bucket)
    if settings.fotos_dir:
        return AlmacenFotosDirectorio(settings.fotos_dir)
    return None


def construir_contexto(settings: Settings) -> ApplicationContext:
    """Arma el contexto con el almacenamiento JSON configurado.

    Los directorios salen de ``RMA_DATA_DIR``; los repositories los
    crean si faltan.
    """
    return ApplicationContext(
        ordenes=JsonOrdenReparacionRepository(settings.ordenes_dir),
        catalogos=JsonCatalogosRepository(settings.catalogos_dir),
        zona_horaria=timezone(timedelta(hours=settings.utc_offset_horas)),
        fotos=_almacen_de_fotos(settings),
        limitador_personas=LimitadorConsultas(
            intervalo_minimo=settings.consulta_dni_intervalo_s,
            maximo_por_minuto=settings.consulta_dni_max_por_minuto,
        ),
    )
