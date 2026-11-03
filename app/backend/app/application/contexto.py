"""Contexto de aplicacion: dependencias que todo caso de uso necesita.

Los casos de uso de ``app.application`` no construyen repositories ni
leen configuracion: reciben este contexto. Asi la API puede armarlo una
vez al arrancar y un test puede armar otro apuntando a ``tmp_path``.

No contiene reglas de negocio: solo los dos repositories, el reloj, la
zona horaria del negocio (para fechas calendario como un vencimiento) y,
desde UAT-010, el almacenamiento de fotos y la fuente externa de datos por
DNI (ambos opcionales: sin ellos, esas funciones quedan deshabilitadas).

Catalogo de equipos de Ventas: ``catalogo_equipos`` es la copia local
(sin ella, el alta solo admite carga manual); ``proveedor_catalogo`` es el
origen que se lee al sincronizar, a traves del puerto ``ProveedorCatalogo``
(sin el, no se sincroniza); ``filtro_catalogo``, que parte se copia.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from typing import NoReturn

from app.core.config import Settings
from app.integraciones import FuentePersonas, LimitadorConsultas
from app.integraciones.catalogo import (
    FiltroCatalogo,
    ProveedorCatalogo,
    construir_proveedor_catalogo,
    filtro_catalogo,
)
from app.repositories import (
    CatalogoEquiposRepository,
    CatalogosRepository,
    ModelosEquipoRepository,
    OrdenReparacionRepository,
)
from app.storage import (
    AlmacenFotos,
    AlmacenFotosDirectorio,
    AlmacenFotosGcs,
    JsonCatalogoEquiposRepository,
    JsonCatalogosRepository,
    JsonModelosEquipoRepository,
    JsonOrdenReparacionRepository,
)
from app.storage.postgres import (
    ConfiguracionPersistenciaError,
    configuracion_postgres,
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
    catalogo_equipos: CatalogoEquiposRepository | None = None
    proveedor_catalogo: ProveedorCatalogo | None = None
    filtro_catalogo: FiltroCatalogo = FiltroCatalogo(("IPHONE USADOS",))
    # Catalogo tecnico de modelos (propio de RMA, solo lectura).
    modelos_equipo: ModelosEquipoRepository | None = None


def _almacen_de_fotos(settings: Settings) -> AlmacenFotos | None:
    """El bucket privado si esta configurado; un directorio, solo en
    desarrollo; si no, ninguno (fotos deshabilitadas)."""
    if settings.fotos_bucket:
        return AlmacenFotosGcs(settings.fotos_bucket)
    if settings.fotos_dir:
        return AlmacenFotosDirectorio(settings.fotos_dir)
    return None


def _rechazar_postgres(settings: Settings) -> NoReturn:
    """PostgreSQL esta en preparacion: la app nunca arranca a medias.

    Primero valida la configuracion, para que un error de URL o de TLS
    se vea ya; despues se detiene, porque todavia no hay repositories.
    """
    configuracion_postgres(settings)
    raise ConfiguracionPersistenciaError(
        "RMA_PERSISTENCIA=postgres todavia no esta disponible: la "
        "integracion esta en preparacion. Usar RMA_PERSISTENCIA=json."
    )


def construir_contexto(settings: Settings) -> ApplicationContext:
    """Arma el contexto con la persistencia configurada.

    JSON (por defecto): los directorios salen de ``RMA_DATA_DIR``; los
    repositories los crean si faltan.
    """
    if settings.persistencia == "postgres":
        _rechazar_postgres(settings)
    return ApplicationContext(
        ordenes=JsonOrdenReparacionRepository(settings.ordenes_dir),
        catalogos=JsonCatalogosRepository(settings.catalogos_dir),
        zona_horaria=timezone(timedelta(hours=settings.utc_offset_horas)),
        fotos=_almacen_de_fotos(settings),
        limitador_personas=LimitadorConsultas(
            intervalo_minimo=settings.consulta_dni_intervalo_s,
            maximo_por_minuto=settings.consulta_dni_max_por_minuto,
        ),
        catalogo_equipos=JsonCatalogoEquiposRepository(
            settings.catalogo_equipos_dir
        ),
        proveedor_catalogo=construir_proveedor_catalogo(settings),
        filtro_catalogo=filtro_catalogo(settings),
        modelos_equipo=JsonModelosEquipoRepository(
            settings.modelos_equipo_archivo
        ),
    )
