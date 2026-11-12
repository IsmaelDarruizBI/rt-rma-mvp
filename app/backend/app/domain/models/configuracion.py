"""Auditoria de la configuracion (DC23AUD, BR-REP-040).

Un ``CambioConfiguracion`` por campo cambiado de un catalogo, con el valor
anterior y el nuevo como texto, el usuario y la fecha/hora. El historial de
precios de un Tipo de Reparacion son sus cambios del campo ``precio``.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EntidadConfiguracion(str, Enum):
    TIPO_REPARACION = "TIPO_REPARACION"
    MESA_TRABAJO = "MESA_TRABAJO"


class CambioConfiguracion(BaseModel):
    entidad: EntidadConfiguracion
    clave: str = Field(min_length=1)
    campo: str = Field(min_length=1)
    valor_anterior: str | None = None
    valor_nuevo: str | None = None
    usuario_id: str = Field(min_length=1)
    fecha: datetime
