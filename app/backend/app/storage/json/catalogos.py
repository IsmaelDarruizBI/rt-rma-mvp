"""Persistencia de los catalogos del MVP en archivos JSON.

Un archivo por catalogo, cada uno con un array JSON:

    tipos_reparacion.json
    insumos.json
    tipo_reparacion_insumos.json
    estaciones.json
    tipo_reparacion_estaciones.json
    usuarios.json
    medios_pago.json        (opcional: sin el archivo, los predeterminados)

Los catalogos se releen en cada consulta: son chicos y asi dos procesos
no trabajan sobre una copia en memoria desactualizada. Cuando el volumen
lo justifique, cachear es un cambio local a esta clase.
"""

from decimal import Decimal
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.domain.models import (
    MEDIOS_PAGO_PREDETERMINADOS,
    EstacionTrabajo,
    Insumo,
    MedioPago,
    TipoReparacion,
    TipoReparacionEstacion,
    TipoReparacionInsumos,
    Usuario,
)
from app.repositories.exceptions import (
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .base import asegurar_directorio, escribir_json_atomico, leer_json

ARCHIVO_TIPOS_REPARACION = "tipos_reparacion.json"
ARCHIVO_INSUMOS = "insumos.json"
ARCHIVO_TIPO_REPARACION_INSUMOS = "tipo_reparacion_insumos.json"
ARCHIVO_ESTACIONES = "estaciones.json"
ARCHIVO_TIPO_REPARACION_ESTACIONES = "tipo_reparacion_estaciones.json"
ARCHIVO_USUARIOS = "usuarios.json"
ARCHIVO_MEDIOS_PAGO = "medios_pago.json"

ModeloT = TypeVar("ModeloT", bound=BaseModel)


class JsonCatalogosRepository:
    """Implementa ``CatalogosRepository`` sobre el filesystem."""

    def __init__(self, directorio: Path) -> None:
        self._directorio = asegurar_directorio(Path(directorio))

    @property
    def directorio(self) -> Path:
        """Directorio donde viven los archivos de catalogo."""
        return self._directorio

    # --- Tipos de Reparacion ---

    def listar_tipos_reparacion(self) -> list[TipoReparacion]:
        return self._listar(ARCHIVO_TIPOS_REPARACION, TipoReparacion)

    def obtener_tipo_reparacion(self, tipo_id: str) -> TipoReparacion:
        return self._buscar_por_id(
            self.listar_tipos_reparacion(), tipo_id, "Tipo de Reparacion"
        )

    # --- Insumos ---

    def listar_insumos(self) -> list[Insumo]:
        return self._listar(ARCHIVO_INSUMOS, Insumo)

    def obtener_insumo(self, insumo_id: str) -> Insumo:
        return self._buscar_por_id(self.listar_insumos(), insumo_id, "Insumo")

    def actualizar_stock_insumo(
        self,
        insumo_id: str,
        nuevo_stock: Decimal,
    ) -> Insumo:
        """Reescribe el catalogo de insumos con el stock actualizado."""
        insumos = self.listar_insumos()
        posicion = next(
            (i for i, insumo in enumerate(insumos) if insumo.id == insumo_id),
            None,
        )
        if posicion is None:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el Insumo {insumo_id}"
            )

        actualizado = insumos[posicion].model_copy(
            update={"stock_fisico": nuevo_stock}
        )
        insumos[posicion] = actualizado
        self._guardar(ARCHIVO_INSUMOS, insumos)
        return actualizado

    # --- Insumos previstos por Tipo de Reparacion ---

    def listar_tipo_reparacion_insumos(self) -> list[TipoReparacionInsumos]:
        return self._listar(
            ARCHIVO_TIPO_REPARACION_INSUMOS, TipoReparacionInsumos
        )

    # --- Estaciones de trabajo ---

    def listar_estaciones(self) -> list[EstacionTrabajo]:
        return self._listar(ARCHIVO_ESTACIONES, EstacionTrabajo)

    def obtener_estacion(self, estacion_id: str) -> EstacionTrabajo:
        return self._buscar_por_id(
            self.listar_estaciones(), estacion_id, "Estacion de Trabajo"
        )

    def listar_tipo_reparacion_estaciones(
        self,
    ) -> list[TipoReparacionEstacion]:
        return self._listar(
            ARCHIVO_TIPO_REPARACION_ESTACIONES, TipoReparacionEstacion
        )

    # --- Usuarios ---

    def listar_usuarios(self) -> list[Usuario]:
        return self._listar(ARCHIVO_USUARIOS, Usuario)

    def obtener_usuario(self, usuario_id: str) -> Usuario:
        return self._buscar_por_id(
            self.listar_usuarios(), usuario_id, "Usuario"
        )

    # --- Medios de pago ---

    def listar_medios_pago(self) -> list[MedioPago]:
        if not (self._directorio / ARCHIVO_MEDIOS_PAGO).is_file():
            return list(MEDIOS_PAGO_PREDETERMINADOS)
        return self._listar(ARCHIVO_MEDIOS_PAGO, MedioPago)

    def obtener_medio_pago(self, medio_id: str) -> MedioPago:
        return self._buscar_por_id(
            self.listar_medios_pago(), medio_id, "Medio de pago"
        )

    # --- Interno ---

    def _listar(
        self,
        archivo: str,
        modelo: type[ModeloT],
    ) -> list[ModeloT]:
        """Carga un catalogo completo. Si no existe, esta vacio."""
        ruta = self._directorio / archivo
        if not ruta.is_file():
            return []

        datos = leer_json(ruta)
        if not isinstance(datos, list):
            raise PersistenciaError(
                f"El catalogo {ruta} deberia ser un array JSON."
            )

        try:
            return [modelo.model_validate(fila) for fila in datos]
        except ValidationError as error:
            raise PersistenciaError(
                f"El catalogo {ruta} tiene filas invalidas: {error}"
            ) from error

    def _guardar(self, archivo: str, entidades: list[ModeloT]) -> None:
        escribir_json_atomico(
            self._directorio / archivo,
            [entidad.model_dump(mode="json") for entidad in entidades],
        )

    @staticmethod
    def _buscar_por_id(
        entidades: list[ModeloT],
        entidad_id: str,
        etiqueta: str,
    ) -> ModeloT:
        for entidad in entidades:
            if getattr(entidad, "id", None) == entidad_id:
                return entidad
        raise EntidadPersistidaNoEncontradaError(
            f"No existe el {etiqueta} {entidad_id}"
        )
