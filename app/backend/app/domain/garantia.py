"""Plazo de garantia sugerido por Detalle (MVP v2, check-in del ingreso).

El check-in es la verificacion de funciones basicas del equipo al
recibirlo. Si se hizo, el taller puede responder por el equipo y sugiere
la garantia completa; si no, una reducida. El plazo se asigna a CADA
Detalle y un empleado autorizado puede cambiarlo; el vencimiento siempre
se cuenta desde la entrega del equipo al cliente.

Sin check-in registrado (Ordenes anteriores, RT interno o garantia RMA sin
el dato) se conserva el plazo del Tipo de Reparacion, como hasta ahora.
"""

GARANTIA_CON_CHECKIN_DIAS = 90
GARANTIA_SIN_CHECKIN_DIAS = 30
# Tope de un ajuste manual: evita un plazo cargado por error (dias de mas).
GARANTIA_MAXIMA_DIAS = 730


def garantia_sugerida(checkin: bool | None, dias_del_tipo: int) -> int:
    """Dias sugeridos para un Detalle segun el check-in del ingreso."""
    if checkin is True:
        return GARANTIA_CON_CHECKIN_DIAS
    if checkin is False:
        return GARANTIA_SIN_CHECKIN_DIAS
    return dias_del_tipo
