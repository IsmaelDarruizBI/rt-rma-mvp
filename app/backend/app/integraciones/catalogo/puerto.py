"""Puerto del catalogo de equipos: lo que RMA necesita de un origen.

``ProveedorCatalogo`` es el UNICO contrato que conoce la sincronizacion.
Un adaptador lo implementa para un almacenamiento concreto:

    ProveedorCatalogoSheets    hoja de Google Sheets (hoy)
    ProveedorCatalogoArchivo   CSV exportado con las mismas columnas
                               (desarrollo y pruebas)
    (futuro)                   Cloud SQL o BigQuery, cuando Ventas migre

El adaptador lee, aplica el filtro (en el origen, si puede; en memoria, si
no) y devuelve ``ProductoInformado`` del dominio, con el ``tp_id`` tal como
viene. Nada fuera del adaptador sabe de URLs, tokens, columnas ni SQL.
"""

from dataclasses import dataclass
from typing import Protocol

from app.domain.models import ProductoInformado


class CatalogoOrigenError(Exception):
    """El origen del catalogo no pudo dar un resultado confiable.

    El mensaje es apto para mostrar: nunca incluye tokens, credenciales ni
    el contenido de la respuesta del origen.
    """


class CatalogoOrigenNoDisponibleError(CatalogoOrigenError):
    """No se pudo leer: red, permisos, credencial o servicio caido."""


class CatalogoOrigenInvalidoError(CatalogoOrigenError):
    """Se leyo, pero la estructura no es la esperada (faltan columnas,
    respuesta vacia o con otro formato)."""


@dataclass(frozen=True)
class FiltroCatalogo:
    """Que parte del catalogo de Ventas copia RMA.

    Por subcategoria (``tp_subcat_1``), sin distinguir mayusculas ni
    espacios al borde. Se configura con ``RMA_CATALOGO_SUBCATEGORIAS``.
    """

    subcategorias: tuple[str, ...]

    def admite(self, subcategoria: str | None) -> bool:
        clave = (subcategoria or "").strip().casefold()
        return any(
            clave == valor.strip().casefold() for valor in self.subcategorias
        )

    @property
    def descripcion(self) -> str:
        return "subcategoría: " + ", ".join(self.subcategorias)


@dataclass(frozen=True)
class LecturaCatalogo:
    """Lo que devolvio el origen para un filtro.

    ``leidos``: registros con datos que tenia el origen; ``filtrados``: los
    que pasaron el filtro; ``descartados``: de esos, los que no tienen
    ``tp_id`` (no se pueden referenciar). ``productos`` son los demas.
    """

    productos: tuple[ProductoInformado, ...]
    leidos: int
    filtrados: int
    descartados: int = 0


class ProveedorCatalogo(Protocol):
    """Un origen de datos del catalogo de equipos de Ventas."""

    @property
    def descripcion(self) -> str:
        """Que origen es, para el registro de la sincronizacion. Sin
        secretos: por ejemplo «Google Sheets (hoja raw_TipoProducto)»."""
        ...

    def leer(self, filtro: FiltroCatalogo) -> LecturaCatalogo:
        """Lee el catalogo completo para ``filtro``.

        Lanza ``CatalogoOrigenNoDisponibleError`` si no pudo leer y
        ``CatalogoOrigenInvalidoError`` si lo leido no tiene la estructura
        esperada. Nunca devuelve un resultado parcial.
        """
        ...
