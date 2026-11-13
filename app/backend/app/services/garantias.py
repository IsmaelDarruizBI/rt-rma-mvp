"""Plazo de garantia por Detalle: check-in y ajuste manual (MVP v2).

El plazo SUGERIDO lo fija el check-in (``app.domain.garantia``): la
verificacion de funciones basicas que Recepcion registra antes de
entregar el equipo, con la reparacion terminada y aprobada (UAT-009).
Hasta entonces rige el plazo del Tipo. Un empleado autorizado puede
cambiar el plazo DEFINITIVO de un Detalle con su motivo: se conservan el
sugerido, el definitivo y cada ajuste (quien, cuando, de cuanto a cuanto y
por que), y el check-in nunca pisa un ajuste. El vencimiento se sigue
calculando desde la entrega del equipo.
"""

from datetime import datetime

from app.domain.garantia import GARANTIA_MAXIMA_DIAS
from app.domain.models import (
    AjusteGarantia,
    EstadoControl,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    RegistroCheckin,
    Usuario,
)
from app.domain.politicas import politica_de

from . import permisos
from .autorizacion import validar_alguno_de
from .custodia import checkin_de
from .exceptions import PrecondicionInvalidaError
from .reparaciones import reaplicar_garantia_sugerida
from .tomas import buscar_detalle

ROLES_AJUSTE_GARANTIA = permisos.GARANTIA_AJUSTAR
# Los mismos que entregan el equipo: el check-in es el paso previo.
ROLES_CHECKIN = permisos.CHECKIN


def _con_trabajos_realizados(orden: OrdenReparacion) -> bool:
    """Algun Detalle terminado y aprobado en control: tiene garantia."""
    return any(
        detalle.estado is EstadoReparacionDetail.COMPLETO
        and detalle.control_estado is EstadoControl.APROBADO
        for detalle in orden.reparaciones_detail
    )


def tiene_garantia(detalle) -> bool:
    """Un trabajo con garantia mayor a cero (DEC-MI-01): el plazo ajustado
    a mano si lo hay, o alguno de los plazos de su politica."""
    if detalle.ajustes_garantia:
        return detalle.garantia_dias > 0
    con = (
        90
        if detalle.garantia_con_checkin is None
        else detalle.garantia_con_checkin
    )
    sin = (
        30
        if detalle.garantia_sin_checkin is None
        else detalle.garantia_sin_checkin
    )
    return max(con, sin) > 0


def _con_trabajos_con_garantia(orden: OrdenReparacion) -> bool:
    """DEC-MI-01 (cierra ABI-37): algun trabajo realizado con garantia
    mayor a cero. Solo entonces el check-in se exige para entregar."""
    return any(
        tiene_garantia(d)
        for d in orden.reparaciones_detail
        if d.estado is EstadoReparacionDetail.COMPLETO
        and d.control_estado is EstadoControl.APROBADO
    )


def checkin_registrable(orden: OrdenReparacion) -> bool:
    """Se puede registrar (o volver a registrar) el check-in ahora.

    En el Origen que lo exige (``requiere_checkin_en_entrega``), con la
    reparacion lista -los trabajos terminados y aprobados en control- y
    antes de la entrega. Notificar y cobrar no lo condicionan.
    """
    return (
        politica_de(orden.origen).requiere_checkin_en_entrega
        and orden.estado_workflow is EstadoWorkflow.REPARACION_LISTA
        and orden.entrega is None
        and orden.recepcion is not None
        and _con_trabajos_realizados(orden)
        and _con_trabajos_con_garantia(orden)
    )


def checkin_pendiente_para_entrega(orden: OrdenReparacion) -> bool:
    """Hay trabajos con garantia y todavia no hay check-in: no se entrega.

    Una Orden anterior que ya tiene el check-in del ingreso cumple (se
    puede volver a registrar antes de entregar). Sin trabajos realizados
    (sin reparacion) no hay garantia que definir.
    """
    return checkin_registrable(orden) and checkin_de(orden) is None


def exigir_checkin_para_entrega(orden: OrdenReparacion) -> None:
    if checkin_pendiente_para_entrega(orden):
        raise PrecondicionInvalidaError(
            "Falta registrar el check-in antes de entregar: indica si se "
            "pudieron verificar las funciones basicas del equipo (define la "
            "garantia de cada trabajo)."
        )


def registrar_checkin_de_entrega(
    orden: OrdenReparacion,
    *,
    realizado: bool,
    usuario: Usuario,
    fecha: datetime,
    motivo: str | None = None,
) -> OrdenReparacion:
    """Registra el check-in antes de la entrega y reasigna la garantia.

    DEC-MI-05 (cierra ABI-32): cambiar un resultado ya registrado es una
    correccion y exige motivo; todos los registros se conservan y rige el
    ultimo. El comprobante final se genera al entregar, con el vigente.

    ``realizado``: si se pudieron verificar las funciones basicas. Queda
    en ``DatosRecepcion.checkin`` (el mismo dato de siempre) con quien y
    cuando en ``registros_checkin``. Cada Detalle no cancelado recibe la
    garantia sugerida (90 o 30 dias); el definitivo la sigue salvo que
    tenga un ajuste manual. Se puede volver a registrar antes de entregar;
    repetir el mismo resultado no agrega nada (reintento).
    """
    validar_alguno_de(usuario, ROLES_CHECKIN)
    if not checkin_registrable(orden):
        raise PrecondicionInvalidaError(
            "El check-in se registra en una Orden de Cliente Externo con la "
            "reparacion lista (trabajos terminados y aprobados en control) y "
            "antes de entregar el equipo."
        )
    registros = orden.recepcion.registros_checkin
    if (
        registros
        and registros[-1].realizado is realizado
        and checkin_de(orden) is realizado
    ):
        return orden

    motivo = (motivo or "").strip() or None
    anterior = checkin_de(orden)
    if anterior is not None and anterior is not realizado and motivo is None:
        raise PrecondicionInvalidaError(
            "Corregir el check-in ya registrado exige un motivo."
        )
    nueva_orden = orden.model_copy(deep=True)
    nueva_orden.recepcion.datos.checkin = realizado
    nueva_orden.recepcion.registros_checkin.append(
        RegistroCheckin(
            realizado=realizado,
            usuario_id=usuario.id,
            fecha=fecha,
            motivo=motivo if anterior is not None else None,
        )
    )
    nueva_orden.updated_at = fecha
    return reaplicar_garantia_sugerida(nueva_orden)


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
