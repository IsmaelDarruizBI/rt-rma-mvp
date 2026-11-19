"""Productos de Gestion RT sobre Google Sheets (solo lectura).

Con el lector comun (``integraciones/sheets.py``) y un token de alcance
``spreadsheets.readonly``:

1. el nombre actual de la hoja Producto, desde su GID (un cambio de nombre
   no rompe la lectura);
2. su fila 1 (solo nombres de columna);
3. ``values:batchGet`` SOLO de las columnas de ``contrato.COPIAR``, una por
   rango: ``producto_passcode`` y las demas columnas no copiadas nunca
   salen de Google (seccion 2.8);
4. la hoja raw_TipoProducto completa (no es sensible; la misma que lee el
   catalogo de Ventas), para resolver ``producto_tp``.

Cada columna pedida vuelve con su encabezado: si no coincide con el de la
fila 1 (alguien movio columnas entre los dos pedidos) se rechaza la
lectura, nunca se mezclan columnas.
"""

import urllib.request
from collections.abc import Callable, Mapping
from datetime import tzinfo
from typing import Any

from app.integraciones.catalogo.ventas import (
    texto_de_celda,
    tipos_producto_desde_tabla,
)
from app.integraciones.sheets import LectorSheets, letra_de_columna

from .contrato import columnas_a_leer, tabla_desde_columnas
from .puerto import (
    LecturaProductosRt,
    ProductosRtOrigenInvalidoError,
    ProductosRtOrigenNoDisponibleError,
)

_ERRORES = (
    ProductosRtOrigenNoDisponibleError,
    ProductosRtOrigenInvalidoError,
)


class ProveedorProductosRtSheets:
    """``ProveedorProductosRt`` para la hoja Producto de Gestion RT."""

    def __init__(
        self,
        *,
        planilla_id: str,
        gid: int,
        planilla_tipos_id: str,
        hoja_tipos: str,
        credencial: Callable[[], str],
        marcas: Mapping[str, str],
        zona: tzinfo,
        abrir: Callable[..., Any] = urllib.request.urlopen,
        timeout: float = 30.0,
    ) -> None:
        self._gid = gid
        self._hoja_tipos = hoja_tipos
        self._marcas = dict(marcas)
        self._zona = zona
        self._credencial = credencial
        self._productos = LectorSheets(
            planilla_id=planilla_id,
            credencial=credencial,
            nombre="la planilla de Productos de Gestión RT",
            abrir=abrir,
            timeout=timeout,
            errores=_ERRORES,
        )
        self._tipos = LectorSheets(
            planilla_id=planilla_tipos_id,
            credencial=credencial,
            nombre="la planilla del catálogo de Ventas",
            abrir=abrir,
            timeout=timeout,
            errores=_ERRORES,
        )

    @property
    def descripcion(self) -> str:
        return f"Google Sheets (hoja con GID {self._gid})"

    def leer(self) -> LecturaProductosRt:
        hoja = self._productos.nombre_de_hoja(self._gid)
        encabezado = self._productos.encabezado(hoja)
        if not any(texto_de_celda(celda) for celda in encabezado):
            raise ProductosRtOrigenInvalidoError(
                f"La hoja {hoja} está vacía: no tiene encabezados."
            )
        indices, faltantes = columnas_a_leer(
            encabezado, error=ProductosRtOrigenInvalidoError
        )
        nombres = list(indices)
        columnas = self._productos.valores_por_columnas(
            hoja, [letra_de_columna(indices[nombre]) for nombre in nombres]
        )
        datos: dict[str, list[Any]] = {}
        for nombre, celdas in zip(nombres, columnas, strict=True):
            if not celdas or texto_de_celda(celdas[0]) != nombre:
                raise ProductosRtOrigenInvalidoError(
                    f"La hoja {hoja} cambió mientras se leía (la columna "
                    f"{nombre} se movió). Probá de nuevo."
                )
            datos[nombre] = list(celdas[1:])
        tabla = tabla_desde_columnas(
            datos, faltantes=faltantes, zona=self._zona
        )

        valores = self._tipos.valores(self._hoja_tipos)
        if not valores or not isinstance(valores[0], list):
            raise ProductosRtOrigenInvalidoError(
                f"La hoja {self._hoja_tipos} está vacía: no tiene encabezados."
            )
        tipos = tipos_producto_desde_tabla(
            valores[0],
            valores[1:],
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
