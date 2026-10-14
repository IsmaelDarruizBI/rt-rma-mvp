"""Movimientos financieros de la Orden: pagos, anulaciones y devoluciones.

Tres movimientos distintos, todos append-only (nada se borra ni se
reescribe):

- ``Pago``: dinero recibido del cliente (anticipo, parcial o final).
- ``AnulacionPago``: correccion ADMINISTRATIVA de un Pago mal registrado.
  Queda dentro del Pago anulado, que conserva su importe original; el
  importe deja de contar como pagado.
- ``DevolucionDinero``: salida EFECTIVA de dinero hacia el cliente,
  vinculada al Pago del que se devuelve (V1.4 PROC-REP-267, BR-REP-038).
  No es un Pago de importe negativo.

Los importes son ``Decimal`` (nunca ``float``). El total cobrable, el saldo
y el estado de cobro se derivan en ``OrdenReparacion``.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, computed_field

from .enums import TipoPago


class AnulacionPago(BaseModel):
    """Quien anulo un Pago, cuando y por que. Una sola por Pago."""

    usuario_id: str
    fecha: datetime
    motivo: str


class Pago(BaseModel):
    """Pago registrado sobre la Orden.

    Puede registrarse en cualquier momento de la vida de la Orden (seña,
    anticipo, pago parcial o pago final), no unicamente al cierre.

    ``tipo_pago`` y ``metodo`` son dos dimensiones distintas: el primero
    dice CUANDO se cobro respecto del cierre (ANTICIPO / PARCIAL / FINAL),
    el segundo COMO (el ID de un medio del catalogo: EFECTIVO,
    TRANSFERENCIA, ...).

    ``referencia``: dato opcional de la operacion (numero de transferencia,
    cupon, observacion). ``operacion_id``: clave que envia quien registra
    para que un reintento no duplique el Pago. ``anulacion`` solo existe
    si el Pago se anulo. Todos con default: un JSON anterior sigue
    cargando.
    """

    id: str
    monto: Decimal = Field(gt=0)
    tipo_pago: TipoPago
    metodo: str
    usuario_id: str
    fecha: datetime
    referencia: str | None = None
    operacion_id: str | None = None
    anulacion: AnulacionPago | None = None

    @property
    def vigente(self) -> bool:
        """El Pago cuenta como cobrado: no fue anulado."""
        return self.anulacion is None


class DevolucionDinero(BaseModel):
    """Dinero devuelto al cliente desde un Pago (PROC-REP-267, BR-REP-038).

    Siempre importe positivo y vinculado al Pago de origen
    (``pago_id``). ``medio`` es un ID del catalogo de medios de pago.
    """

    id: str
    pago_id: str
    monto: Decimal = Field(gt=0)
    medio: str
    usuario_id: str
    fecha: datetime
    motivo: str
    referencia: str | None = None
    operacion_id: str | None = None


class ResumenPago(BaseModel):
    """Movimientos financieros de la Orden y sus sumas.

    No almacena el total cobrable: ese valor deriva de los Detalles de la
    Orden, que este modelo no conoce. El total, el saldo y el estado de
    cobro se calculan en OrdenReparacion.
    """

    pagos: list[Pago] = Field(default_factory=list)
    # BR-REP-038. Default vacio: un JSON anterior sigue cargando.
    devoluciones: list[DevolucionDinero] = Field(default_factory=list)

    @computed_field
    @property
    def pagado(self) -> Decimal:
        """Pagado valido: suma de los Pagos no anulados."""
        return sum(
            (pago.monto for pago in self.pagos if pago.vigente),
            Decimal("0"),
        )

    @computed_field
    @property
    def devuelto(self) -> Decimal:
        """Suma de las devoluciones de dinero registradas."""
        return sum(
            (devolucion.monto for devolucion in self.devoluciones),
            Decimal("0"),
        )

    def devuelto_de(self, pago_id: str) -> Decimal:
        """Lo ya devuelto desde ESE Pago."""
        return sum(
            (
                devolucion.monto
                for devolucion in self.devoluciones
                if devolucion.pago_id == pago_id
            ),
            Decimal("0"),
        )
