"""Puerto de los Productos de Gestion RT: lo que RMA necesita del origen.

``ProveedorProductosRt`` es el UNICO contrato que conoce la sincronizacion
de la copia ``PRODUCTOS_RT``. Un adaptador lo implementa para un
almacenamiento concreto:

    ProveedorProductosRtSheets   la hoja Producto (por GID) de Google
                                 Sheets y la hoja raw_TipoProducto
    ProveedorProductosRtArchivo  dos CSV con las mismas columnas
                                 (desarrollo, pruebas y E2E ficticio)

Cambiar el origen (BigQuery u otro) es escribir otro adaptador. Nada fuera
del adaptador sabe de URLs, tokens ni posiciones de columna. RMA nunca
escribe en Gestion RT (DEC-RT-01): el puerto solo lee.
"""

from dataclasses import dataclass
from typing import Protocol

from app.domain.models import ProductoInformado
from app.integraciones.origen import (
    OrigenExternoError,
    OrigenInvalidoError,
    OrigenNoDisponibleError,
)

from .contrato import FilaProducto


class ProductosRtOrigenError(OrigenExternoError):
    """El origen de los Productos de Gestion RT no dio un resultado
    confiable. El mensaje es apto para mostrar: sin tokens, credenciales ni
    datos del origen."""


class ProductosRtOrigenNoDisponibleError(
    ProductosRtOrigenError, OrigenNoDisponibleError
):
    """No se pudo leer: red, permisos, credencial, cuota o servicio caido."""


class ProductosRtOrigenInvalidoError(
    ProductosRtOrigenError, OrigenInvalidoError
):
    """Se leyo, pero la estructura no es la esperada (columnas, hoja vacia,
    formato de la respuesta)."""


@dataclass(frozen=True)
class LecturaProductosRt:
    """Una lectura completa del origen.

    ``filas``: TODAS las filas de Producto con ``producto_id`` (de cualquier
    estado): la sincronizacion decide cuales aplica. ``tipos``: la tabla
    TipoProducto completa, por ``tp_id``."""

    filas: tuple[FilaProducto, ...]
    tipos: dict[str, ProductoInformado]
    leidos: int
    descartados: int = 0
    # Columnas opcionales que el origen no tiene (cada una, un aviso).
    faltantes: tuple[str, ...] = ()


class ProveedorProductosRt(Protocol):
    """Un origen de datos de los Productos de Gestion RT."""

    @property
    def descripcion(self) -> str:
        """Que origen es, para el registro de la sincronizacion. Sin
        secretos: por ejemplo «Google Sheets (hoja con GID 1030788425)»."""
        ...

    def leer(self) -> LecturaProductosRt:
        """Lee Producto y TipoProducto completos.

        Lanza ``ProductosRtOrigenNoDisponibleError`` si no pudo leer y
        ``ProductosRtOrigenInvalidoError`` si lo leido no tiene la
        estructura esperada. Nunca devuelve un resultado parcial."""
        ...
