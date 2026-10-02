"""Tramo de recursos (EXC-REP-001): esperar y revalidar.

    esperar_recursos     PROC-REP-110 (No) -> 120
    revalidar_recursos   PROC-REP-120 -> 080 -> 090 [-> 140 | -> 100]
    forzar_detalle_por_recursos
                         autorizacion transversal del Detalle (EXC-REP-002)
                         [en PROC-REP-100: 110 (Si) -> 130 -> 140]

Esperar y revalidar son eventos de sistema, sin actor humano: PROC-REP-120
es ACT-SYSTEM y la rama No de PROC-REP-110 no declara actor. El override es
de ACT-COORD. En el MVP un boton dispara
manualmente el evento de revalidacion ("cambio de disponibilidad de
insumos") que V1.3 describe.

El circuito no pertenece solo al ingreso: PROC-REP-120 tambien se alcanza
desde PROC-REP-211 en otros slices.
"""

from app.domain.models import OrdenReparacion
from app.services import (
    autorizar_override_recursos,
    continuar_por_override,
    exigir_espera_por_recursos,
    habilitar_orden,
    registrar_espera_recursos,
)

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


def forzar_detalle_por_recursos(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
    usuario_id: str,
    motivo: str,
) -> OrdenReparacion:
    """Un Coordinador autoriza el override de UN Detalle bloqueado.

    BR-REP-003 / EXC-REP-002: capacidad transversal por Detalle. Siempre
    registra la misma autorizacion (``autorizar_override_recursos``) y deja
    ese Detalle SIN_BLOQUEO; no reserva ni descuenta stock (la reserva es
    PROC-REP-185 y el consumo PROC-REP-210, donde el override habilita un
    disponible / stock negativo).

    Solo si la Orden esta detenida en PROC-REP-100 ("ningun Detalle
    trabajable") el proceso continua 110 "Si" -> 130 -> 140, sin fabricar
    un 090 "Si". Con factibilidad parcial (Orden habilitada, en cola,
    tomada o en reparacion) no se recorre ningun nodo: no vuelve a 140, no
    cierra la toma ni toca la Ejecucion en curso. Persiste una sola vez.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    orden = autorizar_override_recursos(
        orden,
        detalle_id=detalle_id,
        usuario=usuario,
        motivo=motivo,
        fecha=fecha,
    )
    if orden.current_process == "PROC-REP-100":
        orden = continuar_por_override(
            orden, detalle_id=detalle_id, usuario=usuario, fecha=fecha
        )
        orden = habilitar_orden(orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden
