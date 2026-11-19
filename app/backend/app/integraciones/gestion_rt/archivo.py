"""Productos de Gestion RT desde dos CSV (desarrollo, pruebas y E2E).

``productos``: la tabla Producto con sus 31 columnas (la primera fila son
los encabezados, como en Gestion RT). ``tipos``: la tabla TipoProducto (el
mismo formato que el catalogo de Ventas). Los CSV ficticios los genera
``supabase/scripts/validacion_uat/generar_productos_rt_ficticios.py``.

Un CSV trae la fila completa: las columnas que no se copian (incluida
``producto_passcode``) se descartan en ``contrato.tabla_desde_filas``,
antes de salir del adaptador. Tambien muestra que la sincronizacion no
depende de Sheets: es otro adaptador del mismo puerto.
"""

import csv
from collections.abc import Mapping
from datetime import tzinfo
from pathlib import Path

from app.integraciones.catalogo.ventas import tipos_producto_desde_tabla

from .contrato import tabla_desde_filas
from .puerto import (
    LecturaProductosRt,
    ProductosRtOrigenInvalidoError,
    ProductosRtOrigenNoDisponibleError,
)


class ProveedorProductosRtArchivo:
    """``ProveedorProductosRt`` para dos archivos CSV (UTF-8)."""

    def __init__(
        self,
        productos: Path,
        tipos: Path,
        *,
        marcas: Mapping[str, str],
        zona: tzinfo,
    ) -> None:
        self._productos = Path(productos)
        self._tipos = Path(tipos)
        self._marcas = dict(marcas)
        self._zona = zona

    @property
    def descripcion(self) -> str:
        return f"Archivo CSV ({self._productos.name})"

    def leer(self) -> LecturaProductosRt:
        filas = _leer_csv(self._productos)
        tabla = tabla_desde_filas(
            filas[0],
            filas[1:],
            zona=self._zona,
            error=ProductosRtOrigenInvalidoError,
        )
        tipos_filas = _leer_csv(self._tipos)
        tipos = tipos_producto_desde_tabla(
            tipos_filas[0],
            tipos_filas[1:],
            marcas=self._marcas,
            error=ProductosRtOrigenInvalidoError,
        )
        return LecturaProductosRt(
            filas=tabla.filas,
            tipos=tipos,
            leidos=tabla.leidos,
            descartados=tabla.descartados,
            faltantes=tabla.faltantes,
        )


def _leer_csv(ruta: Path) -> list[list[str]]:
    try:
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            filas = list(csv.reader(archivo))
    except OSError as error:
        raise ProductosRtOrigenNoDisponibleError(
            f"No se pudo leer el archivo {ruta.name}."
        ) from error
    except (UnicodeDecodeError, csv.Error) as error:
        raise ProductosRtOrigenInvalidoError(
            f"El archivo {ruta.name} no es un CSV UTF-8 válido."
        ) from error
    if not filas or not any(celda.strip() for celda in filas[0]):
        raise ProductosRtOrigenInvalidoError(
            f"El archivo {ruta.name} está vacío: no tiene encabezados."
        )
    return filas
