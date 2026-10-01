"""Catalogos y configuracion referenciados por ID desde la Orden.

Ninguna de estas entidades se embebe en OrdenReparacion: las entidades
transaccionales las referencian por ID para que un cambio de catalogo no
reescriba historia ya registrada.
"""

from decimal import Decimal

from pydantic import BaseModel, Field


class TipoReparacion(BaseModel):
    """Tipo de reparacion ofrecido, con sus valores vigentes de catalogo.

    ``precio``, ``puntaje`` y ``garantia_dias`` son los valores ACTUALES.
    Al asignarse a un ReparacionDetail se copian alli como snapshot.
    """

    id: str
    nombre: str
    precio: Decimal = Field(ge=0)
    puntaje: int = Field(ge=0)
    garantia_dias: int = Field(ge=0)
    activo: bool = True


class Insumo(BaseModel):
    """Insumo de inventario.

    Solo se persiste el stock fisico. El stock disponible
    (``stock_fisico - reservas_activas``) es un calculo posterior sobre
    los MovimientoInsumo, no un campo de esta entidad.
    """

    id: str
    codigo: str
    nombre: str
    # Puede ser negativo: un override de factibilidad autorizado (BR-REP-003,
    # PROC-REP-130) permite consumir sin stock suficiente. La proteccion
    # vive en los services (solo un Detalle con override puede llevarlo a
    # negativo), no en el tipo.
    stock_fisico: Decimal
    activo: bool = True


class TipoReparacionInsumos(BaseModel):
    """Insumo previsto que consume un Tipo de Reparacion, y su cantidad."""

    tipo_reparacion_id: str
    insumo_id: str
    cantidad: Decimal = Field(gt=0)


class EstacionTrabajo(BaseModel):
    """Estacion de trabajo fisica desde la que opera un tecnico."""

    id: str
    nombre: str
    activa: bool = True


class TipoReparacionEstacion(BaseModel):
    """Compatibilidad entre un Tipo de Reparacion y una Estacion."""

    tipo_reparacion_id: str
    estacion_id: str
