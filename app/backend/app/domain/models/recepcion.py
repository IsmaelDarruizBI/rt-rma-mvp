"""Recepcion fisica del equipo: condiciones de ingreso y custodia.

Dos hechos distintos que no se infieren uno del otro:

- los DATOS del ingreso (estado fisico, accesorios, observaciones), que
  Recepcion registra y puede corregir mientras no confirme la recepcion;
- la CONFIRMACION de que el equipo quedo fisicamente en el local
  (custodia), con quien la confirmo y cuando.

El comprobante de recepcion es un tercer hecho (``documentos``): emitirlo
no prueba que el equipo este en el local.

Todo es append-only: una correccion guarda la version anterior y una
observacion posterior a la confirmacion se agrega, nunca reemplaza lo
confirmado.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import RegistroRecepcion
from .equipos import Equipo


class DatosRecepcion(BaseModel):
    """Condiciones en que se recibe el equipo.

    ``accesorios`` es la lista de lo que se recibe junto con el equipo
    (vacia: ninguno). ``observaciones`` son las observaciones iniciales
    del ingreso.
    """

    estado_fisico: str | None = None
    accesorios: list[str] = Field(default_factory=list)
    observaciones: str | None = None


class VersionRecepcion(BaseModel):
    """Datos de ingreso reemplazados por una correccion.

    Conserva el equipo y las condiciones tal como estaban, quien los
    habia registrado y quien los reemplazo.
    """

    equipo: Equipo
    datos: DatosRecepcion
    registrado_por: str
    registrado_en: datetime
    reemplazado_por: str
    reemplazado_en: datetime


class ConfirmacionRecepcion(BaseModel):
    """El equipo quedo fisicamente en el local: quien lo confirmo y cuando."""

    usuario_id: str
    fecha: datetime
    observaciones: str | None = None


class NoRecepcion(BaseModel):
    """El equipo nunca ingreso fisicamente: quien lo registro, cuando y por
    que. Es una decision explicita: nunca se deduce de la falta de
    confirmacion ni del comprobante."""

    usuario_id: str
    fecha: datetime
    motivo: str


class NotaRecepcion(BaseModel):
    """Observacion complementaria, posterior al registro del ingreso."""

    usuario_id: str
    fecha: datetime
    texto: str


class RecepcionEquipo(BaseModel):
    """Registro de la recepcion fisica del equipo de una Orden.

    ``datos`` es la version vigente; las anteriores quedan en
    ``versiones_anteriores``. ``registro`` dice si nacio con el ingreso o
    como regularizacion de una Orden anterior.

    La custodia se decide una sola vez y de forma explicita: o se confirma
    la recepcion (``confirmacion``) o se registra que el equipo nunca
    ingreso (``no_recibido``). Sin ninguna de las dos queda pendiente.
    Decidida, los datos ya no se corrigen: se agregan ``notas``.
    """

    registro: RegistroRecepcion = RegistroRecepcion.INGRESO
    datos: DatosRecepcion = Field(default_factory=DatosRecepcion)
    registrado_por: str
    registrado_en: datetime
    versiones_anteriores: list[VersionRecepcion] = Field(default_factory=list)
    confirmacion: ConfirmacionRecepcion | None = None
    # Default None: un JSON anterior queda pendiente, nunca "no recibido".
    no_recibido: NoRecepcion | None = None
    notas: list[NotaRecepcion] = Field(default_factory=list)

    @property
    def confirmada(self) -> bool:
        """La recepcion fisica del equipo fue confirmada."""
        return self.confirmacion is not None

    @property
    def decidida(self) -> bool:
        """Ya se decidio si el equipo se recibio o no."""
        return self.confirmacion is not None or self.no_recibido is not None
