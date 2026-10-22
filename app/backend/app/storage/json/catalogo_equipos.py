"""Copia del catalogo de equipos de Ventas en un archivo JSON.

Un unico archivo, ``catalogo_equipos.json``, con los productos y los
ultimos intentos de sincronizacion:

    {"productos": [...], "sincronizaciones": [...]}

Uno solo a proposito: el reemplazo atomico deja productos y registro
consistentes (o la version anterior completa, o la nueva). Se guardan los
ultimos ``MAX_SINCRONIZACIONES`` intentos.

Para no reparsear ~1.500 productos en cada alta, lo leido se conserva en
memoria mientras el archivo no cambie (misma fecha de modificacion y
tamano).

LIMITACION: en Cloud Run el disco es efimero; un redespliegue o un
reinicio de la instancia borra la copia y hay que volver a sincronizar.
Las Ordenes no pierden nada: cada Equipo guarda su ``tp_id`` y una copia
de sus caracteristicas comerciales. La copia persistente es PostgreSQL.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.domain.models import ProductoCatalogo, SincronizacionCatalogo
from app.repositories.exceptions import PersistenciaError

from .base import (
    acceso_exclusivo,
    asegurar_directorio,
    escribir_json_atomico,
    leer_json,
)

ARCHIVO_CATALOGO_EQUIPOS = "catalogo_equipos.json"
MAX_SINCRONIZACIONES = 100


class JsonCatalogoEquiposRepository:
    """Implementa ``CatalogoEquiposRepository`` sobre el filesystem."""

    def __init__(self, directorio: Path) -> None:
        self._directorio = asegurar_directorio(Path(directorio))
        self._firma: tuple[int, int] | None = None
        self._productos: list[ProductoCatalogo] = []
        self._por_id: dict[str, ProductoCatalogo] = {}
        self._sincronizaciones: list[SincronizacionCatalogo] = []

    @property
    def ruta(self) -> Path:
        return self._directorio / ARCHIVO_CATALOGO_EQUIPOS

    def listar_productos(self) -> list[ProductoCatalogo]:
        with acceso_exclusivo():
            self._cargar()
            return list(self._productos)

    def obtener_producto(
        self, tipo_producto_id: str
    ) -> ProductoCatalogo | None:
        with acceso_exclusivo():
            self._cargar()
            return self._por_id.get(tipo_producto_id)

    def listar_sincronizaciones(self) -> list[SincronizacionCatalogo]:
        with acceso_exclusivo():
            self._cargar()
            return list(self._sincronizaciones)

    def registrar_sincronizacion(
        self, sincronizacion: SincronizacionCatalogo
    ) -> None:
        with acceso_exclusivo():
            self._cargar()
            self._escribir(self._productos, sincronizacion)

    def aplicar_sincronizacion(
        self,
        sincronizacion: SincronizacionCatalogo,
        productos: Sequence[ProductoCatalogo],
    ) -> None:
        with acceso_exclusivo():
            self._cargar()
            self._escribir(list(productos), sincronizacion)

    # --- Internos ---

    def _escribir(
        self,
        productos: list[ProductoCatalogo],
        sincronizacion: SincronizacionCatalogo,
    ) -> None:
        sincronizaciones = [*self._sincronizaciones, sincronizacion][
            -MAX_SINCRONIZACIONES:
        ]
        escribir_json_atomico(
            self.ruta,
            {
                "productos": [
                    producto.model_dump(mode="json") for producto in productos
                ],
                "sincronizaciones": [
                    registro.model_dump(mode="json")
                    for registro in sincronizaciones
                ],
            },
        )
        self._firma = None  # se relee (y valida) en la proxima consulta

    def _cargar(self) -> None:
        """Lee el archivo si cambio desde la ultima lectura."""
        ruta = self.ruta
        if not ruta.exists():
            self._firma = None
            self._productos, self._por_id, self._sincronizaciones = [], {}, []
            return
        estado = ruta.stat()
        firma = (estado.st_mtime_ns, estado.st_size)
        if firma == self._firma:
            return
        contenido: Any = leer_json(ruta)
        if not isinstance(contenido, dict):
            raise PersistenciaError(
                f"El archivo {ruta} no tiene el formato esperado."
            )
        try:
            productos = [
                ProductoCatalogo.model_validate(dato)
                for dato in contenido.get("productos", [])
            ]
            sincronizaciones = [
                SincronizacionCatalogo.model_validate(dato)
                for dato in contenido.get("sincronizaciones", [])
            ]
        except ValidationError as error:
            raise PersistenciaError(
                f"El archivo {ruta} tiene datos invalidos: {error}"
            ) from error
        self._productos = productos
        self._por_id = {
            producto.tipo_producto_id: producto for producto in productos
        }
        self._sincronizaciones = sincronizaciones
        self._firma = firma
