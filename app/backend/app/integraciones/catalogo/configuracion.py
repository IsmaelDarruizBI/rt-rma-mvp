"""Unico lugar que traduce la configuracion en un adaptador del catalogo.

Cambiar el origen (por ejemplo, cuando Ventas pase de Google Sheets a una
base de datos) es: escribir el adaptador nuevo, agregar su caso aca y
cambiar ``RMA_CATALOGO_ORIGEN``. La sincronizacion, el almacenamiento de la
copia, el Equipo y el selector no cambian.
"""

from app.core.config import Settings

from .archivo import ProveedorCatalogoArchivo
from .credenciales import (
    ALCANCE_CLOUD_PLATFORM,
    CredencialCloudRun,
    CredencialGcloud,
    CredencialImpersonada,
)
from .puerto import FiltroCatalogo, ProveedorCatalogo
from .sheets import ProveedorCatalogoSheets

ORIGEN_NINGUNO = "ninguno"
ORIGEN_GOOGLE_SHEETS = "google_sheets"
ORIGEN_ARCHIVO = "archivo"


class ConfiguracionCatalogoError(ValueError):
    """La configuracion del origen esta incompleta: el backend no arranca
    (mejor que descubrirlo al sincronizar)."""


def filtro_catalogo(settings: Settings) -> FiltroCatalogo:
    """El filtro configurado (``RMA_CATALOGO_SUBCATEGORIAS``)."""
    subcategorias = tuple(
        valor.strip()
        for valor in settings.catalogo_subcategorias
        if valor.strip()
    )
    if not subcategorias:
        raise ConfiguracionCatalogoError(
            "RMA_CATALOGO_SUBCATEGORIAS no puede quedar vacío."
        )
    return FiltroCatalogo(subcategorias)


def _credencial_sheets(settings: Settings):
    cuenta = settings.catalogo_sheets_cuenta
    if settings.catalogo_sheets_credencial == "gcloud":
        if not cuenta:
            raise ConfiguracionCatalogoError(
                "Con RMA_CATALOGO_SHEETS_CREDENCIAL=gcloud hay que indicar "
                "la cuenta de servicio (RMA_CATALOGO_SHEETS_CUENTA)."
            )
        return CredencialGcloud(cuenta)
    if cuenta:
        return CredencialImpersonada(
            cuenta, CredencialCloudRun((ALCANCE_CLOUD_PLATFORM,))
        )
    return CredencialCloudRun()


def construir_proveedor_catalogo(
    settings: Settings,
) -> ProveedorCatalogo | None:
    """El adaptador configurado, o ``None`` (sin origen: el catalogo no se
    sincroniza y el alta usa la copia que haya, o la carga manual)."""
    origen = settings.catalogo_origen
    if origen == ORIGEN_NINGUNO:
        return None
    if origen == ORIGEN_GOOGLE_SHEETS:
        if not settings.catalogo_sheets_planilla:
            raise ConfiguracionCatalogoError(
                "Falta el ID de la planilla del catálogo "
                "(RMA_CATALOGO_SHEETS_PLANILLA)."
            )
        return ProveedorCatalogoSheets(
            planilla_id=settings.catalogo_sheets_planilla,
            hoja=settings.catalogo_sheets_hoja,
            credencial=_credencial_sheets(settings),
            marcas=settings.catalogo_marcas,
            timeout=settings.catalogo_timeout_s,
        )
    if origen == ORIGEN_ARCHIVO:
        if settings.catalogo_archivo is None:
            raise ConfiguracionCatalogoError(
                "Falta el archivo del catálogo (RMA_CATALOGO_ARCHIVO)."
            )
        return ProveedorCatalogoArchivo(
            settings.catalogo_archivo, marcas=settings.catalogo_marcas
        )
    raise ConfiguracionCatalogoError(
        f"Origen del catálogo desconocido: {origen!r} (RMA_CATALOGO_ORIGEN)."
    )
