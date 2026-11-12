"""Plazo de garantia sugerido por Detalle segun el check-in (MVP v2).

El check-in es la verificacion de funciones basicas del equipo. Se
registra antes de entregarlo, con la reparacion terminada y aprobada
(UAT-009; antes se registraba al recibirlo). Si se pudieron verificar, el
taller sugiere la garantia completa; si no, una reducida. El plazo se
asigna a CADA Detalle y un empleado autorizado puede cambiarlo (un ajuste
manual nunca se pisa); el vencimiento siempre se cuenta desde la entrega
del equipo al cliente.

Sin check-in registrado (todavia no se hizo, RT interno o garantia RMA)
rige el plazo del Tipo de Reparacion, como hasta ahora.
"""

from datetime import date, datetime, timedelta, tzinfo

GARANTIA_CON_CHECKIN_DIAS = 90
GARANTIA_SIN_CHECKIN_DIAS = 30
# Tope de un ajuste manual: evita un plazo cargado por error (dias de mas).
GARANTIA_MAXIMA_DIAS = 730


def garantia_sugerida(checkin: bool | None, dias_del_tipo: int) -> int:
    """Dias sugeridos para un Detalle segun el check-in."""
    if checkin is True:
        return GARANTIA_CON_CHECKIN_DIAS
    if checkin is False:
        return GARANTIA_SIN_CHECKIN_DIAS
    return dias_del_tipo


def vencimiento_garantia(
    fecha_inicio: datetime | None,
    garantia_dias: int,
    zona_horaria: tzinfo,
) -> date | None:
    """Ultimo dia de garantia: el dia (local) de la entrega + el plazo.

    ``None`` sin entrega todavia o con un plazo de 0 dias (sin garantia).
    Es el mismo calculo del comprobante de garantia y de la validacion de
    vigencia de una garantia RMA (PROC-REP-036, BR-REP-041).
    """
    if fecha_inicio is None or garantia_dias <= 0:
        return None
    dia_entrega = fecha_inicio.astimezone(zona_horaria).date()
    return dia_entrega + timedelta(days=garantia_dias)
