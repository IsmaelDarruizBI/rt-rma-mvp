"""Plazo de garantia por Detalle: ajuste manual (MVP v2).

El plazo SUGERIDO lo fija el check-in del ingreso al definir el Detalle
(``app.domain.garantia``). Un empleado autorizado puede cambiar el plazo
DEFINITIVO de un Detalle con su motivo: se conservan el sugerido, el
definitivo y cada ajuste (quien, cuando, de cuanto a cuanto y por que).
El vencimiento se sigue calculando desde la entrega del equipo.
"""

from datetime import datetime

from app.domain.garantia import GARANTIA_MAXIMA_DIAS
from app.domain.models import (
    AjusteGarantia,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    RolUsuario,
    Usuario,
)

from .autorizacion import validar_alguno_de
from .exceptions import PrecondicionInvalidaError
from .tomas import buscar_detalle

ROLES_AJUSTE_GARANTIA = (RolUsuario.RECEPCION, RolUsuario.COORDINADOR_RMA)


def garantia_ajustable(orden: OrdenReparacion) -> bool:
    """La Orden admite ajustar plazos: abierta, sin cancelar ni entregar."""
    return (
        not orden.esta_cerrada
        and orden.estado_workflow is not EstadoWorkflow.CANCELADA
        and orden.entrega is None
    )


def ajustar_garantia_detalle(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    dias: int,
    motivo: str,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """Cambia el plazo definitivo de garantia de UN Detalle.

    Antes de la entrega (despues, la garantia ya se emitio con su plazo).
    El sugerido no se toca; en un Detalle anterior a esta regla se
    conserva como sugerido el plazo que tenia.
    """
    validar_alguno_de(usuario, ROLES_AJUSTE_GARANTIA)
    if not garantia_ajustable(orden):
        raise PrecondicionInvalidaError(
            "La garantia solo se ajusta antes de entregar el equipo, en una "
            "Orden abierta y no cancelada."
        )
    detalle = buscar_detalle(orden, detalle_id)
    if detalle.estado is EstadoReparacionDetail.CANCELADO:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} esta cancelado: no tiene garantia."
        )
    if dias < 0 or dias > GARANTIA_MAXIMA_DIAS:
        raise PrecondicionInvalidaError(
            f"El plazo de garantia debe estar entre 0 y "
            f"{GARANTIA_MAXIMA_DIAS} dias."
        )
    motivo = (motivo or "").strip()
    if not motivo:
        raise PrecondicionInvalidaError(
            "Ajustar la garantia exige indicar el motivo."
        )
    if dias == detalle.garantia_dias:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} ya tiene {dias} dias de garantia."
        )

    nueva_orden = orden.model_copy(deep=True)
    ajustado = buscar_detalle(nueva_orden, detalle_id)
    if ajustado.garantia_dias_sugerida is None:
        ajustado.garantia_dias_sugerida = ajustado.garantia_dias
    ajustado.ajustes_garantia.append(
        AjusteGarantia(
            dias_anteriores=ajustado.garantia_dias,
            dias_nuevos=dias,
            motivo=motivo,
            usuario_id=usuario.id,
            fecha=fecha,
        )
    )
    ajustado.garantia_dias = dias
    nueva_orden.updated_at = fecha
    return nueva_orden
