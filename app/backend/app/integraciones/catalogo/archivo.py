"""Adaptador del catalogo sobre un CSV con las columnas de TipoProducto.

Para desarrollo y pruebas (por ejemplo, la prueba de punta a punta con un
catalogo ficticio): la primera fila son los encabezados (``tp_id``,
``tp_subcat_1``, ...), igual que la hoja de Ventas. Tambien muestra que la
sincronizacion no depende de Sheets: es otro adaptador del mismo puerto.
"""

import csv
from collections.abc import Mapping
from pathlib import Path

from .puerto import (
    CatalogoOrigenInvalidoError,
    CatalogoOrigenNoDisponibleError,
    FiltroCatalogo,
    LecturaCatalogo,
)
from .ventas import lectura_desde_tabla


class ProveedorCatalogoArchivo:
    """``ProveedorCatalogo`` para un archivo CSV (UTF-8)."""

    def __init__(self, ruta: Path, *, marcas: Mapping[str, str]) -> None:
        self._ruta = Path(ruta)
        self._marcas = dict(marcas)

    @property
    def descripcion(self) -> str:
        return f"Archivo CSV ({self._ruta.name})"

    def leer(self, filtro: FiltroCatalogo) -> LecturaCatalogo:
        try:
            with self._ruta.open(encoding="utf-8-sig", newline="") as archivo:
                filas = list(csv.reader(archivo))
        except OSError as error:
            raise CatalogoOrigenNoDisponibleError(
                f"No se pudo leer el archivo {self._ruta.name}."
            ) from error
        except (UnicodeDecodeError, csv.Error) as error:
            raise CatalogoOrigenInvalidoError(
                f"El archivo {self._ruta.name} no es un CSV UTF-8 válido."
            ) from error
        if not filas:
            raise CatalogoOrigenInvalidoError(
                f"El archivo {self._ruta.name} está vacío."
            )
        return lectura_desde_tabla(
            filas[0], filas[1:], filtro, marcas=self._marcas
        )
