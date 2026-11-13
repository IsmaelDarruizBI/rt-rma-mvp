"""Contrato de la configuracion operativa: motivos y parametros
(DEC-MI-13, 14 y 15). En JSON es de solo lectura (los valores iniciales);
en PostgreSQL se administra con auditoria."""

from collections.abc import Sequence
from typing import Protocol

from app.domain.models import CambioConfiguracion
from app.domain.models.comunicaciones import (
    ConsentimientoComunicacion,
    PlantillaMensaje,
)
from app.domain.models.firmas import FirmaDocumento
from app.domain.models.operativa import MotivoOperativo, TipoMotivo


class ConfiguracionOperativaRepository(Protocol):
    editable: bool

    def listar_motivos(
        self, tipo: TipoMotivo | None = None
    ) -> list[MotivoOperativo]: ...

    def guardar_motivo(
        self,
        motivo: MotivoOperativo,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...

    def parametros(self) -> dict[str, str]: ...

    def guardar_parametro(
        self, clave: str, valor: str, cambio: CambioConfiguracion
    ) -> None: ...

    # DEC-MI-08: plantillas de WhatsApp.
    def listar_plantillas(self) -> list[PlantillaMensaje]: ...

    def guardar_plantilla(
        self,
        plantilla: PlantillaMensaje,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...


class ConsentimientosRepository(Protocol):
    """Historial de consentimiento por cliente (DEC-MI-08): solo crece."""

    def listar(self, cliente_id: str) -> list[ConsentimientoComunicacion]: ...

    def agregar(self, registro: ConsentimientoComunicacion) -> None: ...


class FirmasRepository(Protocol):
    """Firmas de documentos emitidos (DEC-MI-06): solo crecen."""

    def de_la_orden(self, orden_id: str) -> list[FirmaDocumento]: ...

    def agregar(self, firma: FirmaDocumento) -> None: ...
