"""Contrato de la configuracion operativa: motivos y parametros
(DEC-MI-13, 14 y 15). En JSON es de solo lectura (los valores iniciales);
en PostgreSQL se administra con auditoria."""

from collections.abc import Sequence
from typing import Protocol

from app.domain.models import CambioConfiguracion
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
