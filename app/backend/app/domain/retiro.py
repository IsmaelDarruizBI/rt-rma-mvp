"""Retiro demorado del equipo (DEC-MI-14; cierra ABI-07).

El plazo se cuenta desde el aviso de equipo listo (PROC-REP-260). Vencido,
la Orden queda en retiro demorado: se alerta y se registran seguimientos,
pero nunca se cierra, se declara abandonada ni se dispone del equipo por
el vencimiento. Es un dato derivado: no se guarda.
"""

from datetime import datetime

from app.domain.models import OrdenReparacion

PASO_AVISO_LISTO = "PROC-REP-260"


def fecha_aviso_listo(orden: OrdenReparacion) -> datetime | None:
    """Cuando se aviso por ultima vez que el equipo estaba listo."""
    return next(
        (
            paso.fecha
            for paso in reversed(orden.historial)
            if paso.referencia_id == PASO_AVISO_LISTO
        ),
        None,
    )


def dias_de_retiro_demorado(
    orden: OrdenReparacion, ahora: datetime, plazo_dias: int
) -> int | None:
    """Dias desde el aviso si el retiro esta demorado; si no, ``None``."""
    if orden.esta_cerrada or orden.entrega is not None:
        return None
    if orden.devolucion is not None:
        return None
    aviso = fecha_aviso_listo(orden)
    if aviso is None:
        return None
    dias = (ahora - aviso).days
    return dias if dias >= plazo_dias else None
