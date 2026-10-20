"""Descuento comercial sobre los trabajos de una Orden (MVP v2).

Recepcion (o Administracion) aplica, cambia o quita un descuento
porcentual o de importe fijo, con su motivo (promocion, convenio, acuerdo
comercial). El precio snapshot de cada Detalle y el catalogo no cambian:
el descuento es un ajuste aparte y el total se deriva (subtotal menos
descuento). Cada cambio queda registrado en la Orden con quien, cuando y
por que.

Con pagos registrados, un descuento que dejaria el total por debajo de lo
ya cobrado se rechaza: primero se anula o se devuelve el excedente. Asi
nunca aparece un saldo a favor por un cambio de descuento.
"""

from datetime import datetime
from decimal import Decimal

from app.domain.models import (
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
) -> OrdenReparacion:
    """Aplica, cambia o quita (``tipo`` en ``None``) el descuento.

    Porcentaje entre 0 y 100; importe fijo hasta el subtotal de los
    trabajos. Rechaza el cambio si el nuevo total quedaria por debajo de
    lo ya cobrado (pagos validos menos devoluciones).
    """
    validar_alguno_de(usuario, ROLES_DESCUENTO)
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
            motivo=motivo, usuario_id=usuario.id, fecha=fecha
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
        registro = RegistroDescuento(
            tipo=tipo,
            valor=valor,
            motivo=motivo,
            usuario_id=usuario.id,
            fecha=fecha,
        )

    nuevo_total = orden.subtotal - importe_de_descuento(
        orden.subtotal, registro
    )
    cobrado = orden.resumen_pago.pagado - orden.resumen_pago.devuelto
    if nuevo_total < cobrado:
        raise PrecondicionInvalidaError(
            f"Con ese descuento el total ({nuevo_total}) quedaria por debajo "
            f"de lo ya cobrado ({cobrado}). Anula o devolve el excedente "
            "antes de cambiar el descuento."
        )

    nueva_orden = orden.model_copy(deep=True)
    nueva_orden.descuentos.append(registro)
    nueva_orden.updated_at = fecha
    return nueva_orden
