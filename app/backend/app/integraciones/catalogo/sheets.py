"""Adaptador del catalogo de Ventas sobre Google Sheets (solo lectura).

Lee la hoja configurada con la API de Sheets v4 (``values.get``), con un
token de alcance ``spreadsheets.readonly``. La API no filtra por valor:
se lee la hoja completa y el filtro se aplica en memoria. De la respuesta
solo se conservan las columnas que usa RMA (``ventas.COLUMNAS``); el resto
(precios, emails de quien elimino un producto) no sale de esta funcion.

Sin dependencias nuevas: HTTP con ``urllib`` (``abrir`` se reemplaza en los
tests por una respuesta simulada).
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote, urlencode

from .puerto import (
    CatalogoOrigenInvalidoError,
    CatalogoOrigenNoDisponibleError,
    FiltroCatalogo,
    LecturaCatalogo,
)
from .ventas import lectura_desde_tabla

URL_VALORES = (
    "https://sheets.googleapis.com/v4/spreadsheets/{planilla}/values/{rango}"
)


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
        self._planilla = planilla_id
        self._hoja = hoja
        self._credencial = credencial
        self._marcas = dict(marcas)
        self._abrir = abrir
        self._timeout = timeout

    @property
    def descripcion(self) -> str:
        return f"Google Sheets (hoja {self._hoja})"

    def leer(self, filtro: FiltroCatalogo) -> LecturaCatalogo:
        valores = self._valores()
        if not valores or not isinstance(valores[0], list):
            raise CatalogoOrigenInvalidoError(
                f"La hoja {self._hoja} está vacía: no tiene encabezados."
            )
        return lectura_desde_tabla(
            valores[0], valores[1:], filtro, marcas=self._marcas
        )

    def _valores(self) -> list[Any]:
        token = self._credencial()
        rango = quote(f"'{self._hoja}'", safe="")
        parametros = urlencode(
            {
                "valueRenderOption": "UNFORMATTED_VALUE",
                "majorDimension": "ROWS",
            }
        )
        pedido = urllib.request.Request(
            URL_VALORES.format(
                planilla=quote(self._planilla, safe=""), rango=rango
            )
            + f"?{parametros}",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with self._abrir(pedido, timeout=self._timeout) as respuesta:
                cuerpo = json.load(respuesta)
        except urllib.error.HTTPError as error:
            raise CatalogoOrigenNoDisponibleError(
                _mensaje_http(error.code, self._hoja)
            ) from error
        except (OSError, TimeoutError) as error:
            raise CatalogoOrigenNoDisponibleError(
                "No se pudo conectar con Google Sheets."
            ) from error
        except ValueError as error:
            raise CatalogoOrigenInvalidoError(
                "Google Sheets respondió algo que no es JSON."
            ) from error
        if not isinstance(cuerpo, dict):
            raise CatalogoOrigenInvalidoError(
                "Google Sheets respondió con un formato inesperado."
            )
        valores = cuerpo.get("values", [])
        if not isinstance(valores, list):
            raise CatalogoOrigenInvalidoError(
                "Google Sheets respondió con un formato inesperado."
            )
        return valores


def _mensaje_http(codigo: int, hoja: str) -> str:
    if codigo in (401, 403):
        return (
            "La cuenta de servicio no tiene permiso de lectura sobre la "
            f"planilla del catálogo (HTTP {codigo})."
        )
    if codigo == 404:
        return "No se encontró la planilla del catálogo (HTTP 404)."
    if codigo == 400:
        return f"La planilla no tiene la hoja {hoja} (HTTP 400)."
    if codigo == 429:
        return (
            "Google Sheets limitó las consultas (HTTP 429). Probá más tarde."
        )
    return f"Google Sheets no respondió correctamente (HTTP {codigo})."
