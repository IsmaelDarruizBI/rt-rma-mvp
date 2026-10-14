"""Contrato de persistencia de los catalogos del MVP.

Un unico contrato cohesivo en vez de seis repositories separados: las
seis entidades se consultan siempre juntas para resolver una misma
pregunta operativa (que reparacion, con que insumos, en que estacion,
por quien).

No es un CRUD generico: solo estan las operaciones que el flujo de
HP-REP-001 necesita. La unica escritura es la del stock fisico, que
cambia cuando un CONSUMO se materializa (PROC-REP-210).
"""

from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.domain.models import (
    DatosEmpresa,
    EstacionTrabajo,
    Insumo,
    MedioPago,
    TipoReparacion,
    TipoReparacionEstacion,
    TipoReparacionInsumos,
    Usuario,
)


@runtime_checkable
class CatalogosRepository(Protocol):
    """Acceso a los catalogos que las Ordenes referencian por ID."""

    # --- Tipos de Reparacion ---

    def obtener_tipo_reparacion(self, tipo_id: str) -> TipoReparacion:
        """Lanza ``EntidadPersistidaNoEncontradaError`` si no existe."""
        ...

    def listar_tipos_reparacion(self) -> list[TipoReparacion]:
        ...

    # --- Insumos ---

    def obtener_insumo(self, insumo_id: str) -> Insumo:
        """Lanza ``EntidadPersistidaNoEncontradaError`` si no existe."""
        ...

    def listar_insumos(self) -> list[Insumo]:
        ...

    def actualizar_stock_insumo(
        self,
        insumo_id: str,
        nuevo_stock: Decimal,
    ) -> Insumo:
        """Fija el stock fisico del insumo y devuelve como quedo.

        Unica escritura del contrato. Quien la invoca ya valido que el
        nuevo stock sea coherente; aqui no hay regla de negocio.
        """
        ...

    # --- Insumos previstos por Tipo de Reparacion ---

    def listar_tipo_reparacion_insumos(self) -> list[TipoReparacionInsumos]:
        ...

    # --- Estaciones de trabajo ---

    def obtener_estacion(self, estacion_id: str) -> EstacionTrabajo:
        """Lanza ``EntidadPersistidaNoEncontradaError`` si no existe."""
        ...

    def listar_estaciones(self) -> list[EstacionTrabajo]:
        ...

    def listar_tipo_reparacion_estaciones(
        self,
    ) -> list[TipoReparacionEstacion]:
        ...

    # --- Usuarios ---

    def obtener_usuario(self, usuario_id: str) -> Usuario:
        """Lanza ``EntidadPersistidaNoEncontradaError`` si no existe."""
        ...

    def listar_usuarios(self) -> list[Usuario]:
        ...

    # --- Medios de pago ---

    def listar_medios_pago(self) -> list[MedioPago]:
        """Medios configurados (o los predeterminados si no hay)."""
        ...

    def obtener_medio_pago(self, medio_id: str) -> MedioPago:
        """Lanza ``EntidadPersistidaNoEncontradaError`` si no existe."""
        ...

    # --- Identificacion de la empresa en los documentos ---

    def obtener_datos_empresa(self) -> DatosEmpresa:
        """Datos configurados (o los predeterminados si no hay)."""
        ...
