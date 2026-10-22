"""Catalogo de equipos de Gestion de Ventas: puerto y adaptadores.

puerto.py         ProveedorCatalogo (el contrato), filtro y errores
ventas.py         formato de la tabla TipoProducto de Ventas
sheets.py         adaptador Google Sheets (hoy)
archivo.py        adaptador CSV (desarrollo y pruebas)
credenciales.py   tokens de Google sin claves JSON
configuracion.py  configuracion -> adaptador (unico lugar)
"""

from .archivo import ProveedorCatalogoArchivo
from .configuracion import (
    ConfiguracionCatalogoError,
    construir_proveedor_catalogo,
    filtro_catalogo,
)
from .puerto import (
    CatalogoOrigenError,
    CatalogoOrigenInvalidoError,
    CatalogoOrigenNoDisponibleError,
    FiltroCatalogo,
    LecturaCatalogo,
    ProveedorCatalogo,
)
from .sheets import ProveedorCatalogoSheets

__all__ = [
    "CatalogoOrigenError",
    "CatalogoOrigenInvalidoError",
    "CatalogoOrigenNoDisponibleError",
    "ConfiguracionCatalogoError",
    "FiltroCatalogo",
    "LecturaCatalogo",
    "ProveedorCatalogo",
    "ProveedorCatalogoArchivo",
    "ProveedorCatalogoSheets",
    "construir_proveedor_catalogo",
    "filtro_catalogo",
]
