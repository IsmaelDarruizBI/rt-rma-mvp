"""Productos de Gestion RT (Reparacion RT): contrato, puerto y adaptadores.

contrato.py       las 31 columnas de Producto, la lista permitida y las
                  celdas (``producto_passcode`` nunca se lee)
puerto.py         ProveedorProductosRt (el contrato), lectura y errores
sheets.py         adaptador Google Sheets (por GID; batchGet por columna)
archivo.py        adaptador CSV (desarrollo, pruebas y E2E ficticio)
configuracion.py  configuracion -> adaptador (unico lugar)

Solo lectura: RMA nunca escribe en Gestion RT (DEC-RT-01).
"""

from .archivo import ProveedorProductosRtArchivo
from .configuracion import (
    ConfiguracionProductosRtError,
    construir_proveedor_productos_rt,
)
from .contrato import COLUMNAS, COPIAR, NUNCA, FilaProducto
from .puerto import (
    LecturaProductosRt,
    ProductosRtOrigenError,
    ProductosRtOrigenInvalidoError,
    ProductosRtOrigenNoDisponibleError,
    ProveedorProductosRt,
)
from .sheets import ProveedorProductosRtSheets

__all__ = [
    "COLUMNAS",
    "COPIAR",
    "NUNCA",
    "ConfiguracionProductosRtError",
    "FilaProducto",
    "LecturaProductosRt",
    "ProductosRtOrigenError",
    "ProductosRtOrigenInvalidoError",
    "ProductosRtOrigenNoDisponibleError",
    "ProveedorProductosRt",
    "ProveedorProductosRtArchivo",
    "ProveedorProductosRtSheets",
    "construir_proveedor_productos_rt",
]
