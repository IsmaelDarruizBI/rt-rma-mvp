"""Descuento comercial sobre los trabajos de una Orden (MVP v2).

Recepcion (o Administracion) aplica, cambia o quita un descuento
porcentual o de importe fijo, con su motivo (promocion, convenio, acuerdo
comercial). El precio snapshot de cada Detalle y el catalogo no cambian:
el descuento es un ajuste aparte y el total se deriva (subtotal menos
descuento). Cada cambio queda registrado en la Orden con quien, cuando y
por que.

Ajustes por Orden o por Detalle (DC09, DEC-MI-03). Con pagos registrados,
un ajuste que deja el total por debajo de lo ya cobrado deja saldo a favor
del cliente, a devolver antes de entregar (DEC-MI-03 cierra ABI-10).

CORTESIA (V1.4, DC11, VAR-REP-041): la Orden no se cobra. Por ahora solo
la cortesia TOTAL (si puede ser parcial sigue pendiente). Con Pagos previos
deja saldo a favor del cliente: los Pagos y la cortesia se conservan y la
devolucion de dinero (PROC-REP-267) es obligatoria antes de entregar
(BR-REP-038); la condicion de entrega ya lo exige (``saldo == 0``).
"""

from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    ClaseAjuste,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    RegistroDescuento,
    TipoDescuento,
    Usuario,
)

from . import permisos
from .autorizacion import validar_alguno_de
from .exceptions import PrecondicionInvalidaError
from .pagos import es_cobrable

ROLES_DESCUENTO = permisos.DESCUENTO
# DEC-IT1-02 (11/11/2026, BR-REP-016/039): otorgan, modifican y quitan la
# CORTESIA Recepcion, Coordinacion RMA y Administracion. El permiso del
# DESCUENTO no cambia (sigue la implementacion del UAT).
ROLES_CORTESIA = permisos.CORTESIA


def descripcion_de_descuento(registro: RegistroDescuento) -> str:
    """Como se expresa: "10 %" o "$ 5000"."""
    if registro.tipo is TipoDescuento.PORCENTAJE:
        return f"{registro.valor.normalize():f} %"
    return f"$ {registro.valor:.2f}"


def descuento_editable(orden: OrdenReparacion) -> bool:
    """La Orden admite descuento: cobrable, abierta, no cancelada, con
    trabajos y todavia sin entregar."""
    return (
        es_cobrable(orden)
        and not orden.esta_cerrada
        and orden.estado_workflow is not EstadoWorkflow.CANCELADA
        and orden.entrega is None
        and orden.subtotal > 0
    )


def aplicar_descuento(
    orden: OrdenReparacion,
    *,
    tipo: TipoDescuento | None,
    valor: Decimal | None,
    motivo: str,
    usuario: Usuario,
    fecha: datetime,
    clase: ClaseAjuste = ClaseAjuste.DESCUENTO,
    detalle_id: str | None = None,
) -> OrdenReparacion:
    """Aplica, cambia o quita (``tipo`` en ``None``) un Ajuste Comercial.

    DC09 y DEC-MI-03: el ajuste es de la Orden (``detalle_id`` en ``None``)
    o de un Detalle no cancelado. Un solo ajuste vigente por destino (el
    ultimo registro), sin acumular. El de un Detalle descuenta sobre su
    precio; el de la Orden, sobre lo que queda despues de los ajustes de
    los Detalles, y no se prorratea entre ellos. Porcentaje entre 0 y 100;
    importe fijo hasta lo que queda del destino.

    Si un DESCUENTO o una CORTESIA deja el total por debajo de lo ya
    cobrado, queda saldo a favor del cliente: los Pagos y los ajustes se
    conservan y la devolucion de dinero (PROC-REP-267) es obligatoria antes
    de entregar (DC11, BR-REP-038, DEC-MI-03); la condicion de entrega ya lo
    exige (``saldo == 0``). Cada clase tiene su permiso (``ROLES_DESCUENTO``
    y ``ROLES_CORTESIA``).
    """
    detalle = None
    if detalle_id is not None:
        detalle = next(
            (d for d in orden.reparaciones_detail if d.id == detalle_id), None
        )
        if detalle is None:
            raise PrecondicionInvalidaError(
                f"La Orden no tiene el trabajo {detalle_id}."
            )
    vigente = (
        orden.ajuste_de_detalle(detalle_id)
        if detalle_id is not None
        else orden.descuento_vigente
    )
    otorga_o_quita_cortesia = clase is ClaseAjuste.CORTESIA or (
        tipo is None
        and vigente is not None
        and vigente.clase is ClaseAjuste.CORTESIA
    )
    validar_alguno_de(
        usuario,
        ROLES_CORTESIA if otorga_o_quita_cortesia else ROLES_DESCUENTO,
    )
    if not descuento_editable(orden):
        raise PrecondicionInvalidaError(
            "El descuento solo se aplica en una Orden cobrable, abierta, no "
            "cancelada, con trabajos y antes de entregar el equipo."
        )
    if (
        detalle is not None
        and detalle.estado is EstadoReparacionDetail.CANCELADO
    ):
        raise PrecondicionInvalidaError(
            f"El trabajo {detalle_id} esta cancelado: no se cobra."
        )
    motivo = (motivo or "").strip()
    if not motivo:
        raise PrecondicionInvalidaError(
            "El descuento exige indicar el motivo (promocion, convenio o "
            "acuerdo comercial)."
        )
    base = (
        detalle.precio
        if detalle is not None
        else orden.subtotal - orden.descuento_detalles
    )
    if tipo is None:
        if vigente is None:
            raise PrecondicionInvalidaError(
                "El trabajo no tiene descuento."
                if detalle_id
                else "La Orden no tiene descuento."
            )
        registro = RegistroDescuento(
            motivo=motivo,
            usuario_id=usuario.id,
            fecha=fecha,
            clase=vigente.clase,
            detalle_id=detalle_id,
        )
    else:
        if valor is None or valor <= 0:
            raise PrecondicionInvalidaError(
                "El descuento debe ser mayor que cero."
            )
        if tipo is TipoDescuento.PORCENTAJE and valor > 100:
            raise PrecondicionInvalidaError(
                "Un descuento porcentual no puede superar el 100 %."
            )
        if tipo is TipoDescuento.IMPORTE and valor > base:
            destino = (
                f"el precio del trabajo ({base})"
                if detalle_id
                else f"el subtotal de los trabajos ({base})"
            )
            raise PrecondicionInvalidaError(
                f"El descuento ({valor}) no puede superar {destino}."
            )
        registro = RegistroDescuento(
            tipo=tipo,
            valor=valor,
            motivo=motivo,
            usuario_id=usuario.id,
            fecha=fecha,
            clase=clase,
            detalle_id=detalle_id,
        )

    nueva_orden = orden.model_copy(deep=True)
    nueva_orden.descuentos.append(registro)
    nueva_orden.updated_at = fecha
    return nueva_orden
