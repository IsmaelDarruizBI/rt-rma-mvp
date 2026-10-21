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
