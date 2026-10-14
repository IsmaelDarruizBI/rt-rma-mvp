"""Equipo recibido para reparacion y su salida fisica del local."""

from datetime import datetime

from pydantic import BaseModel

from .enums import TipoEntrega


class Equipo(BaseModel):
    """Equipo fisico asociado a una Orden de Reparacion.

    ``imei`` y ``numero_serie`` son opcionales: no todo equipo tiene IMEI
    (una notebook, un parlante) y el identificador se registra si existe.
    ``falla_reportada`` es la falla declarada por quien deja el equipo.
    """

    id: str
    marca: str
    modelo: str
    falla_reportada: str
    imei: str | None = None
    numero_serie: str | None = None


class EntregaEquipo(BaseModel):
    """Salida fisica del equipo: entrega o devolucion (PROC-REP-270).

    Registra quien entrega (usuario del sistema), quien retira (texto
    libre: el cliente, un tercero o Gestion RT), su identificacion si
    corresponde (DNI u otra) y cuando. No hay firma ni identificacion
    digital del receptor.

    ``tipo`` distingue la entrega de una reparacion terminada de una
    devolucion sin reparacion. Default DEVOLUCION_SIN_REPARACION: antes de
    este campo solo se registraba la devolucion de una Orden CANCELADA, asi
    que un JSON anterior sigue cargando con el valor correcto.
    """

    tipo: TipoEntrega = TipoEntrega.DEVOLUCION_SIN_REPARACION
    entregado_por: str
    recibido_por: str
    identificacion_receptor: str | None = None
    fecha: datetime
    observaciones: str | None = None


# Nombre historico: la devolucion sin reparar de una Orden CANCELADA es una
# ``EntregaEquipo`` de tipo DEVOLUCION_SIN_REPARACION.
DevolucionEquipo = EntregaEquipo
