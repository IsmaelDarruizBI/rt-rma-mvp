"""Reglas del catalogo tecnico de modelos de equipo (sin E/S).

    modelo_elegible    el modelo que eligio Recepcion, si se puede
    equipo_con_modelo  copia marca, modelo y variante del modelo al Equipo

El Equipo guarda el ID del modelo y una COPIA de marca, modelo y variante
(un cambio posterior del catalogo no reescribe la Orden). La identidad
fisica (IMEI, numero de serie) y el color son del equipo fisico: no
salen del modelo.
"""

from app.domain.models import Equipo, ModeloEquipo

from .exceptions import PrecondicionInvalidaError


class ModeloNoDisponibleError(PrecondicionInvalidaError):
    """El modelo elegido no esta (o ya no esta activo) en el catalogo."""

    codigo = "MODELO_EQUIPO_NO_DISPONIBLE"


def modelo_elegible(
    modelo: ModeloEquipo | None, modelo_id: str
) -> ModeloEquipo:
    """El modelo elegido, si todavia se puede elegir."""
    if modelo is None:
        raise ModeloNoDisponibleError(
            f"El modelo elegido ({modelo_id}) no está en el catálogo de "
            "modelos. Elegilo de nuevo o cargá el equipo a mano."
        )
    if not modelo.activo:
        raise ModeloNoDisponibleError(
            f"El modelo elegido ({modelo.nombre}) ya no se ofrece. Elegí "
            "otro o cargá el equipo a mano."
        )
    return modelo


def equipo_con_modelo(equipo: Equipo, modelo: ModeloEquipo) -> Equipo:
    """El Equipo con marca, modelo y variante del modelo tecnico.

    Copia (no referencia). Ya no es un producto del catalogo de Ventas, ni
    tiene una capacidad que lo identifique; el color es el que se cargo.
    """
    return equipo.model_copy(
        update={
            "modelo_tecnico_id": modelo.id,
            "marca": modelo.marca,
            "modelo": modelo.modelo,
            "variante": modelo.variante,
            "tipo_producto_id": None,
            "capacidad": None,
        }
    )
