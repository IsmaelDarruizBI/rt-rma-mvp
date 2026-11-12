"""Descuento comercial sobre los trabajos de una Orden (MVP v2).

Recepcion (o Administracion) aplica, cambia o quita un descuento
porcentual o de importe fijo, con su motivo (promocion, convenio, acuerdo
comercial). El precio snapshot de cada Detalle y el catalogo no cambian:
el descuento es un ajuste aparte y el total se deriva (subtotal menos
descuento). Cada cambio queda registrado en la Orden con quien, cuando y
por que.

Con pagos registrados, un DESCUENTO que dejaria el total por debajo de lo
ya cobrado se rechaza: primero se anula o se devuelve el excedente (como
tratarlo sigue pendiente en BR-REP-016).

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
    EstadoWorkflow,
    OrdenReparacion,
    RegistroDescuento,
    RolUsuario,
    TipoDescuento,
    Usuario,
    importe_de_descuento,
)

from .autorizacion import validar_alguno_de
from .exceptions import PrecondicionInvalidaError
from .pagos import es_cobrable

ROLES_DESCUENTO = (RolUsuario.RECEPCION, RolUsuario.ADMINISTRADOR)
# BR-REP-016: el permiso inicial de cada tipo de ajuste sigue pendiente de
# decision. PROVISIONAL: la cortesia autorizada por Administracion de V1.3,
# que la regla documenta. Cambiarlo es cambiar esta tupla.
ROLES_CORTESIA = (RolUsuario.ADMINISTRADOR,)


def es_cortesia_total(
    subtotal: Decimal, tipo: TipoDescuento, valor: Decimal
) -> bool:
    """La cortesia cubre todo el subtotal de los trabajos."""
    if tipo is TipoDescuento.PORCENTAJE:
        return valor == 100
    return valor == subtotal


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
) -> OrdenReparacion:
    """Aplica, cambia o quita (``tipo`` en ``None``) el Ajuste Comercial.

    Porcentaje entre 0 y 100; importe fijo hasta el subtotal de los
    trabajos. Un DESCUENTO se rechaza si el nuevo total quedaria por
    debajo de lo ya cobrado (pagos validos menos devoluciones). Una
    CORTESIA solo puede ser total y si queda por debajo de lo cobrado deja
    saldo a favor del cliente, a devolver antes de entregar (DC11). Quitar
    una cortesia exige el mismo permiso que otorgarla.
    """
    vigente = orden.descuento_vigente
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
    motivo = (motivo or "").strip()
    if not motivo:
        raise PrecondicionInvalidaError(
            "El descuento exige indicar el motivo (promocion, convenio o "
            "acuerdo comercial)."
        )
    if tipo is None:
        if orden.descuento_vigente is None:
            raise PrecondicionInvalidaError("La Orden no tiene descuento.")
        registro = RegistroDescuento(
            motivo=motivo,
            usuario_id=usuario.id,
            fecha=fecha,
            clase=vigente.clase,
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
        if tipo is TipoDescuento.IMPORTE and valor > orden.subtotal:
            raise PrecondicionInvalidaError(
                f"El descuento ({valor}) no puede superar el subtotal de los "
                f"trabajos ({orden.subtotal})."
            )
        if clase is ClaseAjuste.CORTESIA and not es_cortesia_total(
            orden.subtotal, tipo, valor
        ):
            raise PrecondicionInvalidaError(
                "La cortesia es por el total de la Orden (100 % o el "
                f"subtotal, {orden.subtotal}); una cortesia parcial sigue "
                "pendiente de definicion: para una rebaja usa un descuento."
            )
        registro = RegistroDescuento(
            tipo=tipo,
            valor=valor,
            motivo=motivo,
            usuario_id=usuario.id,
            fecha=fecha,
            clase=clase,
        )

    nuevo_total = orden.subtotal - importe_de_descuento(
        orden.subtotal, registro
    )
    cobrado = orden.resumen_pago.pagado - orden.resumen_pago.devuelto
    if registro.clase is ClaseAjuste.DESCUENTO and nuevo_total < cobrado:
        raise PrecondicionInvalidaError(
            f"Con ese descuento el total ({nuevo_total}) quedaria por debajo "
            f"de lo ya cobrado ({cobrado}). Anula o devolve el excedente "
            "antes de cambiar el descuento."
        )

    nueva_orden = orden.model_copy(deep=True)
    nueva_orden.descuentos.append(registro)
    nueva_orden.updated_at = fecha
    return nueva_orden
