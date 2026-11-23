"""Retiro demorado del equipo (DEC-MI-14; cierra ABI-07).

DEC-AJ-03 (23/11/2026): el plazo se cuenta desde que la Orden esta lista
para retirar (reparacion lista, PROC-REP-240, o finalizada sin reparacion,
PROC-REP-069), no desde el aviso al cliente (PROC-REP-260), que dejo de
ser obligatorio. La fecha del aviso se conserva aparte, como un dato
independiente (``fecha_aviso_listo``).

Vencido el plazo, la Orden queda en retiro demorado: se alerta y se
registran seguimientos, pero nunca se cierra, se declara abandonada ni se
dispone del equipo por el vencimiento. Es un dato derivado: no se guarda.
"""

from datetime import datetime

from app.domain.models import EstadoWorkflow, OrdenReparacion
from app.domain.politicas import politica_de

PASO_AVISO_LISTO = "PROC-REP-260"
# La Orden queda lista para retirar: reparacion lista (240) o finalizada sin
# reparacion (069). Los dos llevan al cierre por Origen (PROC-REP-250).
PASOS_LISTA_PARA_RETIRAR = ("PROC-REP-240", "PROC-REP-069")


def _ultima_fecha(orden: OrdenReparacion, *nodos: str) -> datetime | None:
    return next(
        (
            paso.fecha
            for paso in reversed(orden.historial)
            if paso.referencia_id in nodos
        ),
        None,
    )


def fecha_aviso_listo(orden: OrdenReparacion) -> datetime | None:
    """Cuando se aviso por ultima vez que el equipo estaba listo (260).

    Dato independiente desde DEC-AJ-03: ya no define el retiro demorado.
    """
    return _ultima_fecha(orden, PASO_AVISO_LISTO)


def fecha_lista_para_retirar(orden: OrdenReparacion) -> datetime | None:
    """Desde cuando el equipo espera que el cliente lo retire.

    Solo para un Origen con entrega al cliente (RT_INTERNO vuelve a
    Gestion RT y no tiene retiro) y mientras el equipo siga en el local:
    la Orden con resultado (REPARACION_LISTA o SIN_REPARACION) y sin
    entrega. La fecha es la del ultimo paso que la dejo lista; una Orden
    anterior sin ese paso usa el aviso, como antes de DEC-AJ-03.
    """
    if not politica_de(orden.origen).requiere_entrega_cliente:
        return None
    if orden.esta_cerrada or orden.entrega is not None:
        return None
    if orden.devolucion is not None:
        return None
    lista = _ultima_fecha(orden, *PASOS_LISTA_PARA_RETIRAR)
    sin_reparacion = any(
        paso.referencia_id == "PROC-REP-069" for paso in orden.historial
    )
    if (
        orden.estado_workflow is not EstadoWorkflow.REPARACION_LISTA
        and not sin_reparacion
    ):
        return None
    return lista or fecha_aviso_listo(orden)


def dias_de_retiro_demorado(
    orden: OrdenReparacion, ahora: datetime, plazo_dias: int
) -> int | None:
    """Dias desde que esta lista para retirar si el retiro esta demorado;
    si no, ``None``."""
    lista = fecha_lista_para_retirar(orden)
    if lista is None:
        return None
    dias = (ahora - lista).days
    return dias if dias >= plazo_dias else None
