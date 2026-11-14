"""Contrato de la configuracion operativa: motivos y parametros
(DEC-MI-13, 14 y 15). En JSON es de solo lectura (los valores iniciales);
en PostgreSQL se administra con auditoria."""

from collections.abc import Sequence
from typing import Protocol

from app.domain.models import CambioConfiguracion, Insumo
from app.domain.models.checklist import PreguntaChecklist, TipoEquipo
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

    # DEC-MI-13: alta y edicion de insumos (sin tocar el stock).
    def guardar_insumo(
        self,
        insumo: Insumo,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...

    # DC12: tipos de equipo y preguntas del checklist.
    def listar_tipos_equipo(self) -> list[TipoEquipo]: ...

    def guardar_tipo_equipo(
        self,
        tipo: TipoEquipo,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...

    def listar_preguntas_checklist(self) -> list[PreguntaChecklist]: ...

    def guardar_pregunta_checklist(
        self,
        pregunta: PreguntaChecklist,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
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
