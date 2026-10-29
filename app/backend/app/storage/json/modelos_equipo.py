"""Catalogo tecnico de modelos de equipo en un archivo JSON de solo lectura.

Una lista de modelos (``ModeloEquipo``). Por defecto es el archivo
versionado con el codigo (``app/datos/modelos_equipo.json``): viaja con la
aplicacion y no depende de ``RMA_DATA_DIR``. Sin el archivo, el catalogo
esta vacio y el alta sigue con la carga manual.

Se relee solo si el archivo cambio (misma fecha de modificacion y
tamano: se conserva lo leido).
"""

from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from app.domain.models import ModeloEquipo
from app.repositories.exceptions import PersistenciaError

from .base import leer_json

_LISTA = TypeAdapter(list[ModeloEquipo])


class JsonModelosEquipoRepository:
    """Implementa ``ModelosEquipoRepository`` sobre un archivo JSON."""

    def __init__(self, ruta: Path) -> None:
        self._ruta = Path(ruta)
        self._firma: tuple[int, int] | None = None
        self._modelos: list[ModeloEquipo] = []
        self._por_id: dict[str, ModeloEquipo] = {}

    def listar_modelos(self) -> list[ModeloEquipo]:
        self._cargar()
        return list(self._modelos)

    def obtener_modelo(self, modelo_id: str) -> ModeloEquipo | None:
        self._cargar()
        return self._por_id.get(modelo_id)

    def _cargar(self) -> None:
        try:
            estado = self._ruta.stat()
        except FileNotFoundError:
            self._firma, self._modelos, self._por_id = None, [], {}
            return
        firma = (estado.st_mtime_ns, estado.st_size)
        if firma == self._firma:
            return
        try:
            modelos = _LISTA.validate_python(leer_json(self._ruta))
        except ValidationError as error:
            raise PersistenciaError(
                f"El archivo {self._ruta} no es valido: {error}"
            ) from error
        por_id = {modelo.id: modelo for modelo in modelos}
        if len(por_id) != len(modelos):
            raise PersistenciaError(
                f"El archivo {self._ruta} repite IDs de modelo."
            )
        self._firma, self._modelos, self._por_id = firma, modelos, por_id
