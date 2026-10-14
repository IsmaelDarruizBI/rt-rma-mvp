"""Documentos de la Orden: marcas del proceso y documentos emitidos.

Dos cosas distintas:

- ``Documento`` (``generado``/``fecha_generacion``) es la MARCA de que el
  proceso paso por el nodo que emite el documento (PROC-REP-060/280). Es
  lo unico que guardaban las Ordenes anteriores.
- ``DocumentoEmitido`` es el documento entregado al cliente: un snapshot
  de los datos con que se emitio, para poder reproducirlo tal cual aunque
  la Orden o los catalogos cambien despues. Nunca se modifica; una
  correccion es una version nueva que referencia a la anterior.

No se guarda ningun PDF ni binario: el snapshot alcanza para reproducir la
version imprimible.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .catalogos import DatosEmpresa
from .enums import (
    EstadoCustodia,
    EstadoWorkflow,
    OrigenCancelacion,
    OrigenOrden,
    TipoDocumento,
    TipoEntrega,
    TipoPago,
)
from .equipos import Equipo
from .personas import Cliente


class Documento(BaseModel):
    """Marca de emision de un documento del proceso (PROC-REP-060/280)."""

    generado: bool = False
    fecha_generacion: datetime | None = None


# --- Contenido (snapshot) ------------------------------------------------


class UsuarioEnDocumento(BaseModel):
    """Usuario tal como figuraba al emitir el documento."""

    id: str
    nombre: str


class TrabajoEnDocumento(BaseModel):
    """Un Detalle de reparacion tal como figura en el documento.

    ``precio`` es ``None`` cuando la Orden no se cobra (RT_INTERNO o
    garantia RMA): el documento no muestra cobros inexistentes.
    """

    detalle_id: str
    tipo_reparacion_id: str
    nombre: str
    precio: Decimal | None = None
    detalle_origen_id: str | None = None


class TrabajoCanceladoEnDocumento(TrabajoEnDocumento):
    """Un Detalle cancelado: figura como no realizado y no cobrado."""

    motivo: str | None = None
    origen_cancelacion: OrigenCancelacion | None = None


class PagoEnDocumento(BaseModel):
    """Un Pago vigente (los anulados no figuran)."""

    id: str
    fecha: datetime
    tipo_pago: TipoPago
    medio: str
    monto: Decimal
    referencia: str | None = None


class DevolucionDineroEnDocumento(BaseModel):
    """Dinero devuelto al cliente."""

    id: str
    pago_id: str
    fecha: datetime
    medio: str
    monto: Decimal
    motivo: str


class CoberturaGarantia(BaseModel):
    """Garantia de UN trabajo realizado, con el plazo de su Detalle.

    ``vence`` es la fecha de inicio (entrega efectiva) mas
    ``garantia_dias``; ``None`` si el Detalle no tiene plazo (0 dias) o si
    todavia no hubo entrega (vista previa).
    """

    detalle_id: str
    tipo_reparacion_id: str
    nombre: str
    garantia_dias: int = Field(ge=0)
    vence: date | None = None
    detalle_origen_id: str | None = None
    observaciones: str | None = None


class _ContenidoBase(BaseModel):
    """Datos comunes a todos los documentos."""

    empresa: DatosEmpresa
    orden_id: str
    origen: OrigenOrden
    fecha_ingreso: datetime
    cliente: Cliente | None = None
    referencia_rt: str | None = None
    equipo: Equipo
    # Garantia RMA (BR-REP-019): Orden original y Detalles reclamados.
    orden_origen_id: str | None = None
    detalles_reclamados: list[TrabajoEnDocumento] = Field(default_factory=list)


class ContenidoComprobanteRecepcion(_ContenidoBase):
    """Comprobante de recepcion (PROC-REP-060, FEAT-REP-001).

    Acredita que se recibio el equipo y en que condiciones. NO lista
    reparaciones ni precios: no implica que el cliente autorizo ningun
    trabajo. ``recepcion_fisica`` es el estado de custodia al emitirlo.
    """

    tipo: Literal[TipoDocumento.COMPROBANTE_RECEPCION] = (
        TipoDocumento.COMPROBANTE_RECEPCION
    )
    estado_fisico: str | None = None
    accesorios: list[str] = Field(default_factory=list)
    observaciones: str | None = None
    notas: list[str] = Field(default_factory=list)
    registrado_por: UsuarioEnDocumento | None = None
    registrado_en: datetime | None = None
    recepcion_fisica: EstadoCustodia
    confirmada_por: UsuarioEnDocumento | None = None
    confirmada_en: datetime | None = None
    leyenda: str


class ContenidoComprobanteEntrega(_ContenidoBase):
    """Comprobante final: entrega o devolucion del equipo.

    ``tipo_entrega`` distingue una reparacion terminada de una devolucion
    sin reparacion. Los importes solo figuran si la Orden es cobrable.
    Sin entrega registrada (vista previa) los datos de la entrega quedan
    vacios.
    """

    tipo: Literal[TipoDocumento.COMPROBANTE_ENTREGA] = (
        TipoDocumento.COMPROBANTE_ENTREGA
    )
    estado_final: EstadoWorkflow
    tipo_entrega: TipoEntrega
    resultado: str
    fecha_entrega: datetime | None = None
    entregado_por: UsuarioEnDocumento | None = None
    recibido_por: str | None = None
    identificacion_receptor: str | None = None
    observaciones_entrega: str | None = None
    trabajos_realizados: list[TrabajoEnDocumento] = Field(default_factory=list)
    trabajos_cancelados: list[TrabajoCanceladoEnDocumento] = Field(
        default_factory=list
    )
    cobrable: bool
    total: Decimal | None = None
    pagado: Decimal | None = None
    devuelto: Decimal | None = None
    saldo: Decimal | None = None
    pagos: list[PagoEnDocumento] = Field(default_factory=list)
    devoluciones_dinero: list[DevolucionDineroEnDocumento] = Field(
        default_factory=list
    )


class ContenidoGarantia(_ContenidoBase):
    """Garantia de los trabajos realizados (PROC-REP-280).

    Cada trabajo con su propio plazo: no hay una duracion general. La
    vigencia empieza con la entrega efectiva del equipo (``fecha_inicio``).
    """

    tipo: Literal[TipoDocumento.GARANTIA] = TipoDocumento.GARANTIA
    fecha_inicio: datetime | None = None
    coberturas: list[CoberturaGarantia] = Field(default_factory=list)
    condiciones: str | None = None
    observaciones_entrega: str | None = None


ContenidoDocumento = Annotated[
    ContenidoComprobanteRecepcion
    | ContenidoComprobanteEntrega
    | ContenidoGarantia,
    Field(discriminator="tipo"),
]


class DocumentoEmitido(BaseModel):
    """Documento entregado al cliente, inmutable.

    ``version`` cuenta las emisiones del mismo tipo; una version nueva
    exige ``motivo`` y apunta a la que reemplaza (``reemplaza_a``). La
    anterior se conserva. ``usuario_id`` es quien ejecuto la accion que lo
    emitio.
    """

    id: str
    tipo: TipoDocumento
    orden_id: str
    version: int = Field(ge=1)
    fecha_emision: datetime
    usuario_id: str | None = None
    motivo: str | None = None
    reemplaza_a: str | None = None
    contenido: ContenidoDocumento


class DocumentosOrden(BaseModel):
    """Marcas del proceso y documentos emitidos de la Orden.

    ``emitidos`` tiene default vacio: una Orden anterior conserva sus
    marcas pero no tiene copia de lo que se le entrego al cliente, y no se
    inventa.
    """

    comprobante_recepcion: Documento = Field(default_factory=Documento)
    comprobante_final: Documento = Field(default_factory=Documento)
    garantia_reparacion: Documento = Field(default_factory=Documento)
    emitidos: list[DocumentoEmitido] = Field(default_factory=list)
