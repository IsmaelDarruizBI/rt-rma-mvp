"""Equipo recibido para reparacion y su devolucion sin reparar."""

from datetime import datetime

from pydantic import BaseModel


class Equipo(BaseModel):
    """Equipo fisico asociado a una Orden de Reparacion."""

    id: str
    marca: str
    modelo: str
    falla_reportada: str
    imei: str | None = None
    numero_serie: str | None = None


class DevolucionEquipo(BaseModel):
    """Devolucion fisica del equipo de una Orden CANCELADA (PROC-REP-270).

    No es una entrega comercial: sin cobro, sin comprobante final ni
    garantia. Registra quien entrega (usuario del sistema), quien recibe
    (texto libre: el cliente o Gestion RT) y cuando.
    """

    entregado_por: str
    recibido_por: str
    fecha: datetime
    observaciones: str | None = None
