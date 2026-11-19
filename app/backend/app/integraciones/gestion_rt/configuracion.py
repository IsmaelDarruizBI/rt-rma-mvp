"""Unico lugar que traduce la configuracion en un adaptador de Productos RT.

Sin secretos (docs/reparacion-rt-discovery.md, seccion 3.2):

    RMA_PRODUCTOS_RT_ORIGEN        ninguno (por defecto), google_sheets o
                                   archivo
    RMA_PRODUCTOS_RT_PLANILLA      planilla de Producto (google_sheets)
    RMA_PRODUCTOS_RT_GID           GID de la hoja Producto (google_sheets)
    RMA_PRODUCTOS_RT_ARCHIVO       CSV de Producto (archivo)
    RMA_PRODUCTOS_RT_TIPOS_ARCHIVO CSV de TipoProducto (archivo); por
                                   defecto, RMA_CATALOGO_ARCHIVO
    RMA_PRODUCTOS_RT_TIPOS_PLANILLA planilla de TipoProducto (google_sheets);
                                   por defecto, RMA_CATALOGO_SHEETS_PLANILLA
    RMA_PRODUCTOS_RT_TIPOS_HOJA    hoja de TipoProducto (google_sheets); por
                                   defecto, RMA_CATALOGO_SHEETS_HOJA

La credencial es la del catalogo de Ventas (``RMA_CATALOGO_SHEETS_*``), y
por defecto tambien la hoja de TipoProducto. En el UAT, la planilla de
Producto es una planilla de PRUEBA con filas ficticias: nunca la real
(seccion 3.3); su hoja de TipoProducto ficticia se indica con
``RMA_PRODUCTOS_RT_TIPOS_*``, asi los productos de prueba no se mezclan con
el catalogo real.
"""

from datetime import timedelta, timezone

from app.core.config import Settings
from app.integraciones.catalogo.configuracion import credencial_sheets

from .archivo import ProveedorProductosRtArchivo
from .puerto import ProveedorProductosRt
from .sheets import ProveedorProductosRtSheets

ORIGEN_NINGUNO = "ninguno"
ORIGEN_GOOGLE_SHEETS = "google_sheets"
ORIGEN_ARCHIVO = "archivo"


class ConfiguracionProductosRtError(ValueError):
    """La configuracion del origen esta incompleta: el backend no arranca
    (mejor que descubrirlo al sincronizar)."""


def construir_proveedor_productos_rt(
    settings: Settings,
) -> ProveedorProductosRt | None:
    """El adaptador configurado, o ``None`` (sin origen: no se sincroniza y
    la pantalla muestra la copia que haya)."""
    origen = settings.productos_rt_origen
    zona = timezone(timedelta(hours=settings.utc_offset_horas))
    if origen == ORIGEN_NINGUNO:
        return None
    if origen == ORIGEN_GOOGLE_SHEETS:
        planilla_tipos = (
            settings.productos_rt_tipos_planilla
            or settings.catalogo_sheets_planilla
        )
        hoja_tipos = (
            settings.productos_rt_tipos_hoja or settings.catalogo_sheets_hoja
        )
        faltan = [
            variable
            for variable, valor in (
                ("RMA_PRODUCTOS_RT_PLANILLA", settings.productos_rt_planilla),
                ("RMA_PRODUCTOS_RT_GID", settings.productos_rt_gid),
                (
                    "RMA_PRODUCTOS_RT_TIPOS_PLANILLA o "
                    "RMA_CATALOGO_SHEETS_PLANILLA",
                    planilla_tipos,
                ),
            )
            if valor in (None, "")
        ]
        if faltan:
            raise ConfiguracionProductosRtError(
                "Faltan datos del origen de Productos RT: "
                + ", ".join(faltan)
                + "."
            )
        return ProveedorProductosRtSheets(
            planilla_id=settings.productos_rt_planilla,
            gid=settings.productos_rt_gid,
            planilla_tipos_id=planilla_tipos,
            hoja_tipos=hoja_tipos,
            credencial=credencial_sheets(settings),
            marcas=settings.catalogo_marcas,
            zona=zona,
            timeout=settings.catalogo_timeout_s,
        )
    if origen == ORIGEN_ARCHIVO:
        tipos = (
            settings.productos_rt_tipos_archivo or settings.catalogo_archivo
        )
        if settings.productos_rt_archivo is None or tipos is None:
            raise ConfiguracionProductosRtError(
                "Faltan los archivos de Productos RT "
                "(RMA_PRODUCTOS_RT_ARCHIVO y RMA_PRODUCTOS_RT_TIPOS_ARCHIVO "
                "o RMA_CATALOGO_ARCHIVO)."
            )
        return ProveedorProductosRtArchivo(
            settings.productos_rt_archivo,
            tipos,
            marcas=settings.catalogo_marcas,
            zona=zona,
        )
    raise ConfiguracionProductosRtError(
        f"Origen de Productos RT desconocido: {origen!r} "
        "(RMA_PRODUCTOS_RT_ORIGEN)."
    )
