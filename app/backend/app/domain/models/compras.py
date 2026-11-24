"""Compras (DEC-MI-09; BR-REP-049): Solicitud -> Orden de compra ->
Recepciones -> Ingreso de stock. Proceso propio, fuera de PROC-REP (DC24).

- Solicitud de compra: manual o sugerida por un faltante; nunca se crea
  sola: la sugerencia se confirma.
- Orden de compra: la crean Recepcion, Coordinacion RMA o Administracion,
  sin aprobacion; registra quien la crea y quien la confirma, el proveedor,
  los insumos, las cantidades y los costos acordados.
- Recepcion: varias parciales por Orden de compra; nunca mas de lo
  pendiente; el costo real lo registra quien recibe; cada linea genera su
  ingreso de stock (con lote o serie si el insumo lo exige). Las
  diferencias (costo distinto del acordado) quedan registradas.
- Costos: el ultimo costo de compra de un insumo es la referencia
  operativa; cada recepcion conserva su costo historico. Los precios los
  configura Administracion (en el insumo), no las compras.
- Sin pagos a proveedores ni integracion contable.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class Proveedor(BaseModel):
    id: str = Field(pattern=r"^PRV-[0-9A-Z-]+$")
    nombre: str = Field(min_length=1)
    cuit: str | None = None
    telefono: str | None = None
    email: str | None = None
    contacto: str | None = None
    activo: bool = True


class OrigenSolicitud(str, Enum):
    MANUAL = "MANUAL"
    FALTANTE = "FALTANTE"
    # DEC-AJ-11: confirmada desde una sugerencia que repone hasta el stock
    # minimo (sola o junto con un faltante).
    STOCK_MINIMO = "STOCK_MINIMO"


class EstadoSolicitud(str, Enum):
    PENDIENTE = "PENDIENTE"
    EN_ORDEN = "EN_ORDEN"
    DESCARTADA = "DESCARTADA"


class SolicitudCompra(BaseModel):
    id: str
    insumo_id: str
    cantidad: Decimal = Field(gt=0)
    origen: OrigenSolicitud
    motivo: str = Field(min_length=1)
    # Ordenes con el faltante que la origino (FALTANTE, o STOCK_MINIMO
    # cuando la sugerencia tambien cubria un faltante).
    ordenes: list[str] = Field(default_factory=list)
    usuario_id: str
    fecha: datetime
    estado: EstadoSolicitud = EstadoSolicitud.PENDIENTE
    orden_compra_id: str | None = None
    descartada_por: str | None = None
    descartada_en: datetime | None = None
    motivo_descarte: str | None = None


class ItemOrdenCompra(BaseModel):
    insumo_id: str
    cantidad: Decimal = Field(gt=0)
    costo_unitario: Decimal = Field(ge=0)


class LineaRecepcion(BaseModel):
    insumo_id: str
    cantidad: Decimal = Field(gt=0)
    # Costo real que registra quien recibe (historico de esta recepcion).
    costo_unitario: Decimal = Field(ge=0)
    lote: str | None = None
    series: list[str] = Field(default_factory=list)
    # Ingresos de stock que genero la linea.
    movimientos: list[str] = Field(default_factory=list)
    diferencia: str | None = None


class RecepcionCompra(BaseModel):
    id: str
    usuario_id: str
    fecha: datetime
    remito: str | None = None
    lineas: list[LineaRecepcion]
    observaciones: str | None = None


class EstadoOrdenCompra(str, Enum):
    BORRADOR = "BORRADOR"
    CONFIRMADA = "CONFIRMADA"
    PARCIAL = "PARCIAL"
    RECIBIDA = "RECIBIDA"
    CANCELADA = "CANCELADA"


class OrdenCompra(BaseModel):
    id: str
    proveedor_id: str
    items: list[ItemOrdenCompra]
    solicitudes: list[str] = Field(default_factory=list)
    creada_por: str
    creada_en: datetime
    confirmada_por: str | None = None
    confirmada_en: datetime | None = None
    cancelada_por: str | None = None
    cancelada_en: datetime | None = None
    motivo_cancelacion: str | None = None
    recepciones: list[RecepcionCompra] = Field(default_factory=list)
    observaciones: str | None = None

    def pedido(self, insumo_id: str) -> Decimal:
        return sum(
            (i.cantidad for i in self.items if i.insumo_id == insumo_id),
            Decimal("0"),
        )

    def recibido(self, insumo_id: str) -> Decimal:
        return sum(
            (
                linea.cantidad
                for recepcion in self.recepciones
                for linea in recepcion.lineas
                if linea.insumo_id == insumo_id
            ),
            Decimal("0"),
        )

    def pendiente(self, insumo_id: str) -> Decimal:
        return self.pedido(insumo_id) - self.recibido(insumo_id)

    @computed_field
    @property
    def estado(self) -> EstadoOrdenCompra:
        if self.cancelada_en is not None:
            return EstadoOrdenCompra.CANCELADA
        if self.confirmada_en is None:
            return EstadoOrdenCompra.BORRADOR
        insumos = {i.insumo_id for i in self.items}
        if all(self.pendiente(i) <= 0 for i in insumos):
            return EstadoOrdenCompra.RECIBIDA
        if self.recepciones:
            return EstadoOrdenCompra.PARCIAL
        return EstadoOrdenCompra.CONFIRMADA

    @computed_field
    @property
    def renglones(self) -> list[dict]:
        """Pedido, recibido y pendiente por insumo (para la pantalla)."""
        vistos: list[str] = []
        for item in self.items:
            if item.insumo_id not in vistos:
                vistos.append(item.insumo_id)
        return [
            {
                "insumo_id": insumo_id,
                "pedido": str(self.pedido(insumo_id)),
                "recibido": str(self.recibido(insumo_id)),
                "pendiente": str(self.pendiente(insumo_id)),
            }
            for insumo_id in vistos
        ]


class CostoCompra(BaseModel):
    """Un costo historico: el de una linea de recepcion."""

    insumo_id: str
    orden_compra_id: str
    recepcion_id: str
    proveedor_id: str
    cantidad: Decimal
    costo_unitario: Decimal
    fecha: datetime


class SugerenciaCompra(BaseModel):
    """Reposicion que conviene pedir: nunca se compra sola.

    ``sugerido = por_faltante + por_minimo`` (DEC-AJ-11). ``motivo`` es el
    origen con que se confirma la solicitud: ``STOCK_MINIMO`` si el minimo
    aporta algo a la cantidad (sola o junto con un faltante); si no,
    ``FALTANTE``."""

    insumo_id: str
    disponible: Decimal
    demanda_bloqueada: Decimal
    en_camino: Decimal
    sugerido: Decimal
    ordenes: list[str]
    stock_minimo: Decimal | None = None
    por_faltante: Decimal = Decimal("0")
    por_minimo: Decimal = Decimal("0")
    motivo: OrigenSolicitud = OrigenSolicitud.FALTANTE
