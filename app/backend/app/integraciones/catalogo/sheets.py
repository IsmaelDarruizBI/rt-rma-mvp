"""Adaptador del catalogo de Ventas sobre Google Sheets (solo lectura).

Lee la hoja configurada con el lector comun (``integraciones/sheets.py``,
``values.get`` con un token de alcance ``spreadsheets.readonly``). La API no
filtra por valor: se lee la hoja completa y el filtro se aplica en memoria.
De la respuesta solo se conservan las columnas que usa RMA
(``ventas.COLUMNAS``); el resto (precios, emails de quien elimino un
producto) no sale de esta funcion.

Sin dependencias nuevas: HTTP con ``urllib`` (``abrir`` se reemplaza en los
tests por una respuesta simulada).
"""

import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from app.integraciones.sheets import LectorSheets

from .puerto import (
    CatalogoOrigenInvalidoError,
    CatalogoOrigenNoDisponibleError,
    FiltroCatalogo,
    LecturaCatalogo,
)
from .ventas import lectura_desde_tabla


class ProveedorCatalogoSheets:
    """``ProveedorCatalogo`` para una hoja de Google Sheets."""

    def __init__(
        self,
        *,
        planilla_id: str,
        hoja: str,
        credencial: Callable[[], str],
        marcas: Mapping[str, str],
        abrir: Callable[..., Any] = urllib.request.urlopen,
        timeout: float = 30.0,
    ) -> None:
        self._hoja = hoja
        self._marcas = dict(marcas)
        # La credencial configurada (la usa el lector; queda a la vista para
        # verificar que configuracion eligio).
        self._credencial = credencial
        self._lector = LectorSheets(
            planilla_id=planilla_id,
            credencial=credencial,
            nombre="la planilla del catálogo",
            abrir=abrir,
            timeout=timeout,
            errores=(
                CatalogoOrigenNoDisponibleError,
                CatalogoOrigenInvalidoError,
            ),
        )

    @property
    def descripcion(self) -> str:
        return f"Google Sheets (hoja {self._hoja})"

    def leer(self, filtro: FiltroCatalogo) -> LecturaCatalogo:
        valores = self._lector.valores(self._hoja)
        if not valores or not isinstance(valores[0], list):
            raise CatalogoOrigenInvalidoError(
                f"La hoja {self._hoja} está vacía: no tiene encabezados."
            )
        return lectura_desde_tabla(
            valores[0], valores[1:], filtro, marcas=self._marcas
        )
