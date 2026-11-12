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

Desde E1, ``unidad_de_trabajo`` fija el limite transaccional de los
comandos (``contexto.transaccion()``). Por defecto es la seccion critica
JSON de siempre; la de PostgreSQL todavia no se usa.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo

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
    RegistroDeAcciones,
    UnidadDeTrabajo,
)
from app.repositories.configuracion import ConfiguracionRepository
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
    ajustes_postgres,
    configuracion_postgres,
)

from .concurrencia import UNIDAD_DE_TRABAJO_JSON

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
    # Limite transaccional de los comandos (E1). Por defecto, el lock de
    # proceso compartido por todos los contextos, como antes.
    unidad_de_trabajo: UnidadDeTrabajo = UNIDAD_DE_TRABAJO_JSON
    # Idempotencia (E6, B1): solo PostgreSQL registra acciones con clave.
    # En JSON es ``None`` y la clave del encabezado se ignora.
    acciones: RegistroDeAcciones | None = None
    # Administracion de catalogos con auditoria (DC23): solo PostgreSQL.
    configuracion: ConfiguracionRepository | None = None
    # Cierre de los recursos de la persistencia (el pool de PostgreSQL).
    cerrar: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        # E2 (DE-2): el repository JSON exige que las lecturas para
        # modificar y la numeracion ocurran dentro de la transaccion de
        # ESTA unidad de trabajo.
        vincular = getattr(self.ordenes, "exigir_transaccion_con", None)
        if vincular is not None:
            vincular(self.unidad_de_trabajo.en_curso)

    def transaccion(self) -> AbstractContextManager[None]:
        """Abre la transaccion de un comando (o se une a la que esta en
        curso). Solo desde la capa de aplicacion."""
        return self.unidad_de_trabajo.transaccion()

    def lectura(self) -> AbstractContextManager[None]:
        """Abre una lectura de varios pasos: todo lo que lea el bloque se ve
        en un solo instante. Solo lectura y solo desde la capa de
        aplicacion."""
        return self.unidad_de_trabajo.lectura_consistente()


def _almacen_de_fotos(settings: Settings) -> AlmacenFotos | None:
    """El bucket privado si esta configurado; un directorio, solo en
    desarrollo; si no, ninguno (fotos deshabilitadas)."""
    if settings.fotos_bucket:
        return AlmacenFotosGcs(settings.fotos_bucket)
    if settings.fotos_dir:
        return AlmacenFotosDirectorio(settings.fotos_dir)
    return None


def _contexto_postgres(settings: Settings) -> ApplicationContext:
    """B4: la app entera sobre PostgreSQL, sin modo mixto ni fallback.

    Un servidor remoto (Supabase) solo con ``RMA_DB_REMOTO_HABILITADO``
    (E8), con TLS ``verify-full``. Una sola unidad de trabajo por pool,
    compartida por todos los repositories (QA-E3-4). Si la base no
    responde, la app no arranca (nunca cae a JSON). Los datos de
    dominio -Ordenes, catalogos, acciones y modelos tecnicos- van a la
    base; la copia local del catalogo de Ventas y las
    fotos conservan su almacenamiento propio.
    """
    from app.storage.postgres.acciones import PostgresRegistroDeAcciones
    from app.storage.postgres.catalogos import PostgresCatalogosRepository
    from app.storage.postgres.conexion import HOSTS_LOCALES, servidor_unico
    from app.storage.postgres.configuracion import (
        PostgresConfiguracionRepository,
    )
    from app.storage.postgres.modelos_equipo import (
        PostgresModelosEquipoRepository,
    )
    from app.storage.postgres.ordenes import PostgresOrdenReparacionRepository
    from app.storage.postgres.transaccion import (
        UnidadDeTrabajoPostgres,
        abrir_pool,
        cerrar_pool,
    )

    configuracion = configuracion_postgres(settings)
    ajustes = ajustes_postgres(settings)
    remoto = (
        servidor_unico(configuracion.conninfo.get_secret_value())
        not in HOSTS_LOCALES
    )
    if remoto and not settings.db_remoto_habilitado:
        raise ConfiguracionPersistenciaError(
            "RMA_PERSISTENCIA=postgres solo arranca contra un servidor "
            "local: la conexion remota (Supabase) exige "
            "RMA_DB_REMOTO_HABILITADO=true (E8)."
        )
    pool = abrir_pool(configuracion, ajustes)
    try:
        pool.wait(timeout=ajustes.pool_espera_s)
    except Exception:
        cerrar_pool(pool)
        raise ConfiguracionPersistenciaError(
            "No se pudo conectar a PostgreSQL: la app no arranca sin su "
            "base (no hay fallback a JSON)."
        ) from None
    unidad = UnidadDeTrabajoPostgres(pool, ajustes)
    return ApplicationContext(
        ordenes=PostgresOrdenReparacionRepository(unidad),
        catalogos=PostgresCatalogosRepository(unidad),
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
        modelos_equipo=PostgresModelosEquipoRepository(unidad),
        unidad_de_trabajo=unidad,
        acciones=PostgresRegistroDeAcciones(unidad),
        configuracion=PostgresConfiguracionRepository(unidad),
        cerrar=lambda: cerrar_pool(pool),
    )


def construir_contexto(settings: Settings) -> ApplicationContext:
    """Arma el contexto con la persistencia configurada.

    JSON (por defecto): los directorios salen de ``RMA_DATA_DIR``; los
    repositories los crean si faltan.
    """
    if settings.persistencia == "postgres":
        return _contexto_postgres(settings)
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
