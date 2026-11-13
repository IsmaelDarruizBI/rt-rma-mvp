"""Reglas de la identidad del Equipo (DEC-MI-11).

- Vincular un ingreso a un Equipo existente exige compartir su IMEI o su
  numero de serie (``comparte_identidad``): nunca por similitud.
- Corregir una vinculacion erronea: Recepcion, Coordinacion RMA o
  Administracion, con motivo; queda auditada en la Orden (de que identidad
  a cual). El destino es otro Equipo con la misma identificacion o una
  identidad nueva («Ninguno»).
"""

from datetime import datetime

from app.domain.identidad import comparte_identidad
from app.domain.models import Equipo, OrdenReparacion, Usuario
from app.domain.models.equipos import CorreccionVinculoEquipo

from . import permisos
from .autorizacion import validar_alguno_de
from .exceptions import PrecondicionInvalidaError


def exigir_vinculo_por_identidad(
    equipo: Equipo, existente: Equipo | None
) -> None:
    """``existente``: el Equipo ya registrado con ese ID (o ninguno)."""
    if existente is not None and not comparte_identidad(equipo, existente):
        raise PrecondicionInvalidaError(
            f"El Equipo {existente.id} no tiene el mismo IMEI ni el mismo "
            "numero de serie: no se vincula por similitud. Elegi otro o "
            "indica «Ninguno»."
        )


def corregir_vinculo(
    orden: OrdenReparacion,
    *,
    nuevo_equipo_id: str,
    existente: Equipo | None,
    motivo: str,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """La Orden pasa a la identidad ``nuevo_equipo_id`` (existente o
    nueva). Los datos del equipo de la Orden no cambian."""
    validar_alguno_de(usuario, permisos.EQUIPO_VINCULO_CORREGIR)
    motivo = (motivo or "").strip()
    if not motivo:
        raise PrecondicionInvalidaError(
            "Corregir la vinculacion del Equipo exige un motivo."
        )
    if nuevo_equipo_id == orden.equipo.id:
        raise PrecondicionInvalidaError(
            "La Orden ya esta vinculada a ese Equipo."
        )
    exigir_vinculo_por_identidad(orden.equipo, existente)
    nueva = orden.model_copy(deep=True)
    nueva.correcciones_equipo.append(
        CorreccionVinculoEquipo(
            equipo_anterior_id=orden.equipo.id,
            equipo_nuevo_id=nuevo_equipo_id,
            motivo=motivo,
            usuario_id=usuario.id,
            fecha=fecha,
        )
    )
    nueva.equipo = nueva.equipo.model_copy(update={"id": nuevo_equipo_id})
    nueva.updated_at = fecha
    return nueva
