"""Lector de Google Sheets de solo lectura, comun a los origenes externos.

Lo usan el catalogo de Ventas (``integraciones/catalogo/sheets.py``) y, en
Reparacion RT, los Productos de Gestion RT. Habla con la API de Sheets v4
con un token de alcance ``spreadsheets.readonly`` (``credencial``: ver
``integraciones/catalogo/credenciales.py``):

    valores(hoja)                  ``values.get`` de la hoja completa
    encabezado(hoja)               ``values.get`` de la fila 1 sola
    valores_por_columnas(hoja, c)  ``values:batchGet`` SOLO de las columnas
                                   pedidas (por letra): lo demas, incluido
                                   un dato sensible, nunca sale de Google
    nombre_de_hoja(gid)            el nombre actual de la hoja con ese GID
                                   (``spreadsheets.get``, solo propiedades)

Sin dependencias nuevas: HTTP con ``urllib`` (``abrir`` se reemplaza en las
pruebas). Los tokens nunca se registran ni se incluyen en un mensaje de
error. Los errores son los del origen que lo usa (``errores``), para que
cada copia conserve los suyos.
"""

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import quote, urlencode

from .origen import OrigenInvalidoError, OrigenNoDisponibleError

URL_PLANILLA = "https://sheets.googleapis.com/v4/spreadsheets/{planilla}"
URL_VALORES = URL_PLANILLA + "/values/{rango}"
URL_VALORES_LOTE = URL_PLANILLA + "/values:batchGet"
_COLUMNA = re.compile(r"^[A-Z]{1,3}$")


def letra_de_columna(indice: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA (notacion A1)."""
    if indice < 0:
        raise ValueError("El indice de columna no puede ser negativo.")
    letras = ""
    numero = indice + 1
    while numero:
        numero, resto = divmod(numero - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return letras


class LectorSheets:
    """Lecturas de solo lectura de una planilla."""

    def __init__(
        self,
        *,
        planilla_id: str,
        credencial: Callable[[], str],
        nombre: str = "la planilla",
        abrir: Callable[..., Any] = urllib.request.urlopen,
        timeout: float = 30.0,
        errores: tuple[type[Exception], type[Exception]] = (
            OrigenNoDisponibleError,
            OrigenInvalidoError,
        ),
    ) -> None:
        self._planilla = planilla_id
        self._credencial = credencial
        self._nombre = nombre
        self._abrir = abrir
        self._timeout = timeout
        self._no_disponible, self._invalido = errores

    # --- Lecturas -----------------------------------------------------

    def valores(self, hoja: str) -> list[Any]:
        """Todas las filas de ``hoja`` (encabezado incluido)."""
        cuerpo = self._pedir(
            URL_VALORES.format(
                planilla=quote(self._planilla, safe=""),
                rango=quote(f"'{hoja}'", safe=""),
            ),
            {
                "valueRenderOption": "UNFORMATTED_VALUE",
                "majorDimension": "ROWS",
            },
            hoja=hoja,
        )
        valores = cuerpo.get("values", [])
        if not isinstance(valores, list):
            raise self._invalido(
                "Google Sheets respondió con un formato inesperado."
            )
        return valores

    def encabezado(self, hoja: str) -> list[Any]:
        """Solo la fila 1 de ``hoja``: los nombres de las columnas, sin
        ningun dato. Vacia si la hoja no tiene encabezado."""
        cuerpo = self._pedir(
            URL_VALORES.format(
                planilla=quote(self._planilla, safe=""),
                rango=quote(f"'{hoja}'!1:1", safe=""),
            ),
            {
                "valueRenderOption": "UNFORMATTED_VALUE",
                "majorDimension": "ROWS",
            },
            hoja=hoja,
        )
        valores = cuerpo.get("values", [])
        if not isinstance(valores, list) or len(valores) > 1:
            raise self._invalido(
                "Google Sheets respondió con un formato inesperado."
            )
        fila = valores[0] if valores else []
        if not isinstance(fila, list):
            raise self._invalido(
                "Google Sheets respondió con un formato inesperado."
            )
        return fila

    def valores_por_columnas(
        self, hoja: str, columnas: Sequence[str]
    ) -> list[list[Any]]:
        """Los valores de cada columna pedida (por letra), en orden y desde
        la fila 1: ``[[col_A...], [col_F...]]``. Solo esas columnas viajan."""
        if not columnas or any(not _COLUMNA.match(c) for c in columnas):
            raise ValueError("Las columnas se piden por letra (A, F, AB...).")
        rangos = [f"'{hoja}'!{c}:{c}" for c in columnas]
        cuerpo = self._pedir(
            URL_VALORES_LOTE.format(planilla=quote(self._planilla, safe="")),
            [
                ("valueRenderOption", "UNFORMATTED_VALUE"),
                ("dateTimeRenderOption", "SERIAL_NUMBER"),
                ("majorDimension", "COLUMNS"),
                *(("ranges", r) for r in rangos),
            ],
            hoja=hoja,
        )
        rangos_respuesta = cuerpo.get("valueRanges")
        if not isinstance(rangos_respuesta, list) or len(
            rangos_respuesta
        ) != len(rangos):
            raise self._invalido(
                "Google Sheets respondió con un formato inesperado."
            )
        resultado: list[list[Any]] = []
        for rango in rangos_respuesta:
            valores = (
                rango.get("values", []) if isinstance(rango, dict) else None
            )
            if not isinstance(valores, list) or len(valores) > 1:
                raise self._invalido(
                    "Google Sheets respondió con un formato inesperado."
                )
            columna = valores[0] if valores else []
            if not isinstance(columna, list):
                raise self._invalido(
                    "Google Sheets respondió con un formato inesperado."
                )
            resultado.append(columna)
        return resultado

    def nombre_de_hoja(self, gid: int) -> str:
        """El nombre actual de la hoja con ese GID (``sheetId``)."""
        cuerpo = self._pedir(
            URL_PLANILLA.format(planilla=quote(self._planilla, safe="")),
            {"fields": "sheets.properties(sheetId,title)"},
            hoja=f"GID {gid}",
        )
        hojas = cuerpo.get("sheets", [])
        if not isinstance(hojas, list):
            raise self._invalido(
                "Google Sheets respondió con un formato inesperado."
            )
        for hoja in hojas:
            propiedades = (
                hoja.get("properties") if isinstance(hoja, dict) else None
            )
            if not isinstance(propiedades, dict):
                raise self._invalido(
                    "Google Sheets respondió con un formato inesperado."
                )
            if propiedades.get("sheetId") == gid:
                titulo = propiedades.get("title")
                if isinstance(titulo, str) and titulo:
                    return titulo
        raise self._invalido(f"La planilla no tiene la hoja con GID {gid}.")

    # --- Internos -----------------------------------------------------

    def _pedir(self, url: str, parametros, *, hoja: str) -> dict[str, Any]:
        token = self._credencial()
        pedido = urllib.request.Request(
            url + f"?{urlencode(parametros)}",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with self._abrir(pedido, timeout=self._timeout) as respuesta:
                cuerpo = json.load(respuesta)
        except urllib.error.HTTPError as error:
            raise self._no_disponible(
                self._mensaje_http(error.code, hoja)
            ) from error
        except (OSError, TimeoutError) as error:
            raise self._no_disponible(
                "No se pudo conectar con Google Sheets."
            ) from error
        except ValueError as error:
            raise self._invalido(
                "Google Sheets respondió algo que no es JSON."
            ) from error
        if not isinstance(cuerpo, dict):
            raise self._invalido(
                "Google Sheets respondió con un formato inesperado."
            )
        return cuerpo

    def _mensaje_http(self, codigo: int, hoja: str) -> str:
        if codigo in (401, 403):
            return (
                "La cuenta de servicio no tiene permiso de lectura sobre "
                f"{self._nombre} (HTTP {codigo})."
            )
        if codigo == 404:
            return f"No se encontró {self._nombre} (HTTP 404)."
        if codigo == 400:
            return f"La planilla no tiene la hoja {hoja} (HTTP 400)."
        if codigo == 429:
            return (
                "Google Sheets limitó las consultas (HTTP 429). Probá más "
                "tarde."
            )
        return f"Google Sheets no respondió correctamente (HTTP {codigo})."
