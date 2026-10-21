"""Aggregate raiz del MVP: la Orden de Reparacion."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, computed_field

from .descuentos import RegistroDescuento, importe_de_descuento
from .documentos import DocumentosOrden
from .enums import (
    EstadoControl,
    EstadoPago,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrigenOrden,
)
from .equipos import EntregaEquipo, Equipo
from .fotos import FotoOrden
from .inventario import MovimientoInsumo
from .pagos import ResumenPago
from .personas import Cliente
from .recepcion import RecepcionEquipo
from .reparacion import EjecucionReparacion, ReparacionDetail, TomaOrden
from .workflow import HistorialWorkflow


class OrdenReparacion(BaseModel):
    """Unidad de gestion del proceso de reparacion.

    Contiene sus entidades transaccionales (Detalles, tomas, ejecuciones,
    movimientos, pagos, documentos e historial) y referencia los
    catalogos -TipoReparacion, Insumo, EstacionTrabajo, Usuario- solo por
    ID: nunca los copia.

    La situacion comercial (``subtotal``, ``descuento_aplicado``,
    ``total``, ``saldo``, ``estado_pago``) es siempre derivada: nada que
    deba sincronizarse a mano. Lo unico persistido es el precio snapshot
    de cada Detalle, los pagos y los registros de descuento. Sin impuestos
    ni cortesias por Detalle.

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

    # HP-REP-003 / BR-REP-019: solo RMA_GARANTIA_REPARACION la completa
    # (ID de la Orden ENTREGADA de la que nace la garantia; nunca el
    # objeto). Default None: un JSON anterior a Slice 3 sigue cargando.
    orden_origen_id: str | None = None

    # BR-REP-019: Detalles de la Orden origen identificados en
    # PROC-REP-035 como procedencia de esta garantia. Existe aparte de
    # ``ReparacionDetail.detalle_origen_id`` (Detalle NUEVO -> Detalle
    # origen) porque una garantia que entra en revision todavia no tiene
    # Detalles propios. Vacio en los demas Origenes (y en JSON previo).
    detalles_origen_ids: list[str] = Field(default_factory=list)

    prioridad: int = Field(default=0, ge=0)

    reparaciones_detail: list[ReparacionDetail] = Field(default_factory=list)

    tomas: list[TomaOrden] = Field(default_factory=list)

    ejecuciones: list[EjecucionReparacion] = Field(default_factory=list)

    movimientos_insumo: list[MovimientoInsumo] = Field(default_factory=list)

    resumen_pago: ResumenPago = Field(default_factory=ResumenPago)

    documentos: DocumentosOrden = Field(default_factory=DocumentosOrden)

    historial: list[HistorialWorkflow] = Field(default_factory=list)

    # Datos del ingreso fisico y confirmacion de custodia. ``None`` solo en
    # una Orden anterior a este registro: no se presume su custodia.
    recepcion: RecepcionEquipo | None = None
    # Descuento comercial sobre los trabajos (MVP v2): todos los cambios,
    # del mas antiguo al mas reciente; el vigente es el ultimo (si no lo
    # quito). Default vacio: un JSON anterior sigue cargando sin descuento.
    descuentos: list[RegistroDescuento] = Field(default_factory=list)
    # Fotos del equipo (UAT-010): solo sus datos; la imagen esta en el
    # almacenamiento de objetos. Default vacio: un JSON anterior carga.
    fotos: list[FotoOrden] = Field(default_factory=list)

    # PROC-REP-270 tras una cancelacion: devolucion fisica del equipo sin
    # reparar. Default None: un JSON anterior sigue cargando.
    devolucion: EntregaEquipo | None = None

    # PROC-REP-270 de la entrega (Orden ENTREGADA): quien retiro el equipo.
    # ``None`` en una Orden entregada antes de este registro.
    entrega: EntregaEquipo | None = None

    created_at: datetime
    updated_at: datetime

    @property
    def esta_cerrada(self) -> bool:
        """True si la Orden ya termino su proceso y solo puede consultarse.

        Decision de negocio E1 (MVP v2): una Orden ENTREGADA queda cerrada
        para cualquier modificacion operativa. RT_INTERNO no pasa por
        ENTREGADA -su estado terminal sigue pendiente de definicion-: al
        devolverse a Gestion RT su proceso termina en EVT-REP-999, y
        recibe el mismo trato. Una garantia RMA nace de una Orden cerrada
        sin modificarla: es otra Orden.

        No es un campo: se deriva del estado, asi que no cambia el JSON
        persistido.
        """
        return (
            self.estado_workflow is EstadoWorkflow.ENTREGADA
            or self.current_process == "EVT-REP-999"
        )

    @property
    def descuento_vigente(self) -> RegistroDescuento | None:
        """El descuento en vigor: el ultimo registro, si no lo quita."""
        ultimo = self.descuentos[-1] if self.descuentos else None
        return ultimo if ultimo is not None and ultimo.tipo else None

    @computed_field
    @property
    def subtotal(self) -> Decimal:
        """Suma de los precios snapshot de los Detalles no cancelados.

        Un Detalle CANCELADO conserva su precio snapshot (historia), pero
        no se cobra (BR-REP-014).
        """
        return sum(
            (
                detalle.precio
                for detalle in self.reparaciones_detail
                if detalle.estado is not EstadoReparacionDetail.CANCELADO
            ),
            Decimal("0"),
        )

    @computed_field
    @property
    def descuento_aplicado(self) -> Decimal:
        """Lo que descuenta el descuento vigente sobre el subtotal."""
        return importe_de_descuento(self.subtotal, self.descuento_vigente)

    @computed_field
    @property
    def total(self) -> Decimal:
        """Total cobrable: subtotal de los trabajos menos el descuento."""
        return self.subtotal - self.descuento_aplicado

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
        """Saldo = Total - Pagado valido + Devuelto (BR-REP-038).

        Positivo: el cliente debe. Cero: no hay diferencias. Negativo:
        credito a favor del cliente, pendiente de devolver. Los Pagos
        anulados no cuentan como pagados.
        """
        return (
            self.total - self.resumen_pago.pagado + self.resumen_pago.devuelto
        )

    @property
    def credito_a_favor(self) -> Decimal:
        """Dinero a devolver al cliente: el saldo negativo, o 0."""
        return max(-self.saldo, Decimal("0"))

    @computed_field
    @property
    def estado_pago(self) -> EstadoPago:
        """Estado de cobro derivado del saldo y de lo pagado.

        Una Orden sin Detalles todavia no tiene nada que cobrar, y no es
        lo mismo que una Orden con Detalles cuyo total da 0: la primera
        queda PENDIENTE, la segunda PAGADA. Los Detalles CANCELADO no
        cuentan: una Orden con todos cancelados no figura PAGADA. Con
        credito a favor del cliente es SALDO_A_FAVOR, haya Detalles o no.
        """
        if self.saldo < 0:
            return EstadoPago.SALDO_A_FAVOR
        if all(
            detalle.estado is EstadoReparacionDetail.CANCELADO
            for detalle in self.reparaciones_detail
        ):
            return EstadoPago.PENDIENTE
        if self.saldo == 0:
            return EstadoPago.PAGADO
        if self.resumen_pago.pagado > 0:
            return EstadoPago.PARCIAL
        return EstadoPago.PENDIENTE
