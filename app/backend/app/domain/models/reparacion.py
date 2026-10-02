"""Trabajo tecnico de la Orden: Detalle, toma de Orden y Ejecucion.

Relacion conceptual:

    OrdenReparacion -> TomaOrden -> EjecucionReparacion -> ReparacionDetail
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from .enums import (
    CondicionReparacionDetail,
    EstadoControl,
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoTomaOrden,
)
from .inventario import InsumoUtilizado


class DefinicionAnteriorDetalle(BaseModel):
    """Definicion de un Detalle reemplazada por PROC-REP-127 (BR-REP-015).

    Append-only: cada redefinicion agrega la definicion que deja de estar
    vigente (Tipo y snapshots), cuando y quien la reemplazo. La primera
    definicion (PROC-REP-070/075) no genera entrada: solo existe historia
    cuando algo se reemplaza.
    """

    tipo_reparacion_id: str
    precio: Decimal = Field(ge=0)
    puntaje: int = Field(ge=0)
    garantia_dias: int = Field(ge=0)
    reemplazada_en: datetime
    usuario_id: str


class ReparacionDetail(BaseModel):
    """Trabajo tecnico requerido dentro de una Orden.

    ``precio``, ``puntaje`` y ``garantia_dias`` son snapshots tomados del
    TipoReparacion al crear el Detalle: no se releen del catalogo, para
    que un cambio de precio futuro no altere ordenes ya registradas. Por
    eso solo se guarda ``tipo_reparacion_id``, nunca el objeto.

    ``estado`` y ``condicion`` son dos dimensiones independientes: el
    avance tecnico del trabajo y si algo lo bloquea. ``condicion`` tiene
    default ``SIN_BLOQUEO`` para que un JSON persistido antes de Slice 0
    -que no conoce el campo- siga cargando sin tocarse.
    """

    id: str
    tipo_reparacion_id: str

    precio: Decimal = Field(ge=0)
    puntaje: int = Field(ge=0)
    garantia_dias: int = Field(ge=0)

    estado: EstadoReparacionDetail = EstadoReparacionDetail.DEFINIDO
    condicion: CondicionReparacionDetail = (
        CondicionReparacionDetail.SIN_BLOQUEO
    )

    control_estado: EstadoControl = EstadoControl.PENDIENTE
    control_usuario_id: str | None = None
    control_fecha: datetime | None = None
    control_observaciones: str | None = None

    observaciones: str | None = None

    # BR-REP-019: en un Detalle de garantia RMA, el Detalle de la Orden
    # origen que motiva el reproceso (solo el ID, no el objeto).
    detalle_origen_id: str | None = None

    # BR-REP-015 / PROC-REP-127: definiciones reemplazadas, de la mas
    # antigua a la mas reciente. Default vacio: un JSON anterior al
    # Slice 9 sigue cargando sin migracion.
    definiciones_anteriores: list[DefinicionAnteriorDetalle] = Field(
        default_factory=list
    )


class TomaOrden(BaseModel):
    """Participacion activa de un tecnico sobre la Orden completa.

    Distinta de la Ejecucion de un Detalle: una toma puede abarcar varias
    Ejecuciones. Al cerrarse se registra ``fin`` y el estado pasa a
    CERRADA, de modo que una Orden entregada no conserva tomas activas.
    """

    id: str
    usuario_id: str
    estacion_id: str
    estado: EstadoTomaOrden = EstadoTomaOrden.ACTIVA
    inicio: datetime
    fin: datetime | None = None


class EjecucionReparacion(BaseModel):
    """Ejecucion concreta de un Detalle dentro de una toma de Orden.

    ``insumos_utilizados`` es lo efectivamente consumido, confirmado por
    el tecnico en PROC-REP-200. Es la fuente de verdad que PROC-REP-210
    compara contra las reservas para generar consumos y liberaciones.
    """

    id: str
    reparacion_detail_id: str
    toma_orden_id: str
    usuario_id: str
    estado: EstadoEjecucion = EstadoEjecucion.EN_PROGRESO
    inicio: datetime
    fin: datetime | None = None
    insumos_utilizados: list[InsumoUtilizado] = Field(default_factory=list)
    observaciones: str | None = None
    # PROC-REP-200 "Requiere redefinicion" (EXC-REP-004): motivo
    # obligatorio por el que la definicion del Detalle dejo de servir.
    motivo_redefinicion: str | None = None
