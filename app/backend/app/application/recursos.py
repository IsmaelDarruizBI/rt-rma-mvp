"""Tramo de recursos (EXC-REP-001): esperar y revalidar.

    esperar_recursos     PROC-REP-110 (No) -> 120
    revalidar_recursos   PROC-REP-120 -> 080 -> 090 [-> 140 | -> 100]

Son eventos de sistema, sin actor humano: PROC-REP-120 es ACT-SYSTEM y la
rama No de PROC-REP-110 no declara actor. En el MVP un boton dispara
manualmente el evento de revalidacion ("cambio de disponibilidad de
insumos") que V1.3 describe.

El circuito no pertenece solo al ingreso: PROC-REP-120 tambien se alcanza
desde PROC-REP-211 en otros slices.
"""

from app.domain.models import OrdenReparacion
from app.services import exigir_espera_por_recursos, registrar_espera_recursos

from .contexto import ApplicationContext
from .ingreso import _validar_y_habilitar


def esperar_recursos(
    contexto: ApplicationContext,
    *,
    orden_id: str,
) -> OrdenReparacion:
    """La Orden no fuerza el Detalle bloqueado y espera (110 No -> 120)."""
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    orden = registrar_espera_recursos(orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden


def revalidar_recursos(
    contexto: ApplicationContext,
    *,
    orden_id: str,
) -> OrdenReparacion:
    """Revalida la factibilidad contra el stock global actual (120 -> 080).

    Con al menos un Detalle trabajable: 090 Si -> 140 (HABILITADA), y los
    Detalles que ahora tienen recursos vuelven a SIN_BLOQUEO. Si todavia
    no hay ninguno: 090 Ninguno trabajable -> 100, y la Orden queda de
    nuevo lista para esperar (cada ciclo conserva su historial). No crea
    Detalles ni repite 045/050/060/065/068/070/075; no reserva ni modifica
    el stock.
    """
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    exigir_espera_por_recursos(orden)
    orden = _validar_y_habilitar(contexto, orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden
