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

Solo para el modo JSON (desarrollo local): con ``RMA_PERSISTENCIA=postgres``
la copia va a la base (``PostgresCatalogoEquiposRepository``), porque en
Cloud Run el disco es efimero. La reserva de una sincronizacion es un
candado del proceso por archivo: no hay otra instancia que coordinar, y si
el proceso termina, el candado termina con el.
"""

import threading
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.domain.models import (
    ProductoCatalogo,
    ReservaSincronizacion,
    SincronizacionCatalogo,
)
from app.repositories.exceptions import PersistenciaError, ReservaOcupadaError

from .base import (
    acceso_exclusivo,
    asegurar_directorio,
    escribir_json_atomico,
    leer_json,
)

ARCHIVO_CATALOGO_EQUIPOS = "catalogo_equipos.json"
MAX_SINCRONIZACIONES = 100
COPIA = "CATALOGO_VENTAS"

# Una sincronizacion por vez por archivo, en todo el proceso (como el
# candado de la aplicacion de antes): la segunda se rechaza, no espera.
# Como en PostgreSQL, la reserva VENCE: si quien la tomo no la libero (un
# error antes de llegar al repositorio), la siguiente la toma pasado
# ``vence_en`` y la vieja ya no puede escribir (QA C fase A, M1).
_GUARDA = threading.Lock()
_CANDADOS: dict[Path, threading.Lock] = {}
# Por archivo: (id de la reserva vigente, hasta cuando vale).
_TITULARES: dict[Path, tuple[str, datetime]] = {}


def _candado(ruta: Path) -> threading.Lock:
    with _GUARDA:
        return _CANDADOS.setdefault(ruta.resolve(), threading.Lock())


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

    def reservar_sincronizacion(
        self,
        *,
        id: str,
        usuario_id: str,
        origen: str,
        filtro: str,
        duracion: timedelta,
        propietario: str,
    ) -> ReservaSincronizacion:
        ruta = self.ruta.resolve()
        candado = _candado(ruta)
        iniciada = datetime.now(timezone.utc)
        vence = iniciada + duracion
        if candado.acquire(blocking=False):
            try:
                with _GUARDA:
                    _TITULARES[ruta] = (id, vence)
            except BaseException:
                candado.release()
                raise
        else:
            with _GUARDA:
                titular = _TITULARES.get(ruta)
                if titular is None or titular[1] > iniciada:
                    raise ReservaOcupadaError(
                        "Ya hay una sincronización del catálogo en curso."
                    )
                # La reserva anterior vencio sin liberarse: se toma (el
                # candado sigue tomado, ahora a nombre de esta).
                _TITULARES[ruta] = (id, vence)
        return ReservaSincronizacion(
            id=id,
            copia=COPIA,
            usuario_id=usuario_id,
            origen=origen,
            filtro=filtro,
            iniciada_en=iniciada,
            vence_en=vence,
            propietario=propietario,
        )

    def registrar_sincronizacion(
        self,
        sincronizacion: SincronizacionCatalogo,
        reserva: ReservaSincronizacion | None = None,
    ) -> None:
        try:
            self._exigir_vigente(reserva)
            with acceso_exclusivo():
                self._cargar()
                self._escribir(self._productos, sincronizacion)
        finally:
            self._liberar(reserva)

    def aplicar_sincronizacion(
        self,
        sincronizacion: SincronizacionCatalogo,
        productos: Sequence[ProductoCatalogo],
        reserva: ReservaSincronizacion | None = None,
    ) -> None:
        try:
            self._exigir_vigente(reserva)
            with acceso_exclusivo():
                self._cargar()
                self._escribir(list(productos), sincronizacion)
        finally:
            self._liberar(reserva)

    # --- Internos ---

    def _exigir_vigente(self, reserva: ReservaSincronizacion | None) -> None:
        """Con reserva, solo escribe la vigente: una que vencio y otra tomo
        ya no finaliza (como en PostgreSQL)."""
        if reserva is None:
            return
        with _GUARDA:
            titular = _TITULARES.get(self.ruta.resolve())
        if titular is None or titular[0] != reserva.id:
            raise PersistenciaError(
                f"El intento {reserva.id} ya no está en curso: no se "
                "finalizó (su reserva venció y otra sincronización la tomó)."
            )

    def _liberar(self, reserva: ReservaSincronizacion | None) -> None:
        """Libera la reserva si es la vigente (liberar dos veces, o una
        reserva que otra ya tomo, no hace nada)."""
        if reserva is None:
            return
        ruta = self.ruta.resolve()
        with _GUARDA:
            titular = _TITULARES.get(ruta)
            if titular is None or titular[0] != reserva.id:
                return
            del _TITULARES[ruta]
        _candado(ruta).release()

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
