"""Reclamos de garantia rechazados (DEC-MI-02; cierra ABI-35 y ABI-34).

Cuando un reclamo de garantia no se admite (PROC-REP-036 -> EVT-REP-998:
algun Detalle vencido sin excepcion) no se crea la Orden de garantia, pero
el intento queda registrado aparte: la Orden original entregada no se
modifica. Desde el reclamo, Recepcion puede continuar como una reparacion
paga de CLIENTE_EXTERNO, vinculada al reclamo y una sola vez.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from .equipos import Equipo
from .orden_reparacion import VigenciaGarantiaOrigen


class ResultadoReclamo(str, Enum):
    RECHAZADO = "RECHAZADO"


class ReclamoGarantia(BaseModel):
    """Un reclamo de garantia rechazado.

    ``vigencias``: lo que se evaluo de cada Detalle reclamado (plazo,
    vencimiento, vigente y la excepcion autorizada si la hubo).
    ``excepciones_pedidas``: los motivos de excepcion que trajo el pedido.
    ``orden_continuacion_id``: la Orden paga que lo continuo, si existe.
    """

    id: str = Field(pattern=r"^RGA-\d{6,}$")
    orden_origen_id: str
    detalles_reclamados: list[str]
    equipo: Equipo
    usuario_id: str
    fecha: datetime
    vigencias: list[VigenciaGarantiaOrigen] = Field(default_factory=list)
    excepciones_pedidas: dict[str, str] = Field(default_factory=dict)
    resultado: ResultadoReclamo = ResultadoReclamo.RECHAZADO
    motivo: str
    orden_continuacion_id: str | None = None
    continuado_por: str | None = None
    continuado_en: datetime | None = None
