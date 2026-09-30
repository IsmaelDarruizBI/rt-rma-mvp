"""Aggregate raiz del MVP: la Orden de Reparacion."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, computed_field

from .documentos import DocumentosOrden
from .enums import EstadoControl, EstadoPago, EstadoWorkflow, OrigenOrden
from .equipos import Equipo
from .inventario import MovimientoInsumo
from .pagos import ResumenPago
from .personas import Cliente
from .reparacion import EjecucionReparacion, ReparacionDetail, TomaOrden
from .workflow import HistorialWorkflow


class OrdenReparacion(BaseModel):
    """Unidad de gestion del proceso de reparacion.

    Contiene sus entidades transaccionales (Detalles, tomas, ejecuciones,
    movimientos, pagos, documentos e historial) y referencia los
    catalogos -TipoReparacion, Insumo, EstacionTrabajo, Usuario- solo por
    ID: nunca los copia.

    La situacion comercial (``total``, ``saldo``, ``estado_pago``) es
    siempre derivada: nada que deba sincronizarse a mano. El alcance del
    MVP cubre HP-REP-001 (CLIENTE_EXTERNO) y HP-REP-002 (RT_INTERNO), sin
    descuentos, cortesias, cancelaciones, impuestos ni ajustes.

    ``cliente`` es ``None`` para RT_INTERNO (BR-REP-016): el equipo es de
    Rosario Tecno, no hay un Cliente externo que lo deje. ``referencia_rt``
    es el contexto minimo que PROC-REP-020 recibe de Gestion RT para ese
    origen; queda ``None`` para los demas.

    Es el aggregate que mas adelante se persistira como un unico JSON.
    """

    id: str

    origen: OrigenOrden
    estado_workflow: EstadoWorkflow
    current_process: str

    cliente: Cliente | None = None
    equipo: Equipo

    referencia_rt: str | None = None

    prioridad: int = Field(default=0, ge=0)

    reparaciones_detail: list[ReparacionDetail] = Field(default_factory=list)

    tomas: list[TomaOrden] = Field(default_factory=list)

    ejecuciones: list[EjecucionReparacion] = Field(default_factory=list)

    movimientos_insumo: list[MovimientoInsumo] = Field(default_factory=list)

    resumen_pago: ResumenPago = Field(default_factory=ResumenPago)

    documentos: DocumentosOrden = Field(default_factory=DocumentosOrden)

    historial: list[HistorialWorkflow] = Field(default_factory=list)

    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def total(self) -> Decimal:
        """Total cobrable: suma de los precios snapshot de los Detalles."""
        return sum(
            (detalle.precio for detalle in self.reparaciones_detail),
            Decimal("0"),
        )

    @computed_field
    @property
    def puntaje_total(self) -> int:
        """Puntaje de la Orden: suma de sus Detalles aprobados.

        El puntaje se acredita por Detalle en el momento de su
        aprobacion (PROC-REP-245, BR-REP-009), no al cerrar la Orden.
        """
        return sum(
            detalle.puntaje
            for detalle in self.reparaciones_detail
            if detalle.control_estado is EstadoControl.APROBADO
        )

    @computed_field
    @property
    def saldo(self) -> Decimal:
        """Diferencia entre el total cobrable y lo efectivamente pagado."""
        return self.total - self.resumen_pago.pagado

    @computed_field
    @property
    def estado_pago(self) -> EstadoPago:
        """Estado de cobro derivado del saldo y de lo pagado.

        Una Orden sin Detalles todavia no tiene nada que cobrar, y no es
        lo mismo que una Orden con Detalles cuyo total da 0: la primera
        queda PENDIENTE, la segunda PAGADA.
        """
        if not self.reparaciones_detail:
            return EstadoPago.PENDIENTE
        if self.saldo <= 0:
            return EstadoPago.PAGADO
        if self.resumen_pago.pagado > 0:
            return EstadoPago.PARCIAL
        return EstadoPago.PENDIENTE
