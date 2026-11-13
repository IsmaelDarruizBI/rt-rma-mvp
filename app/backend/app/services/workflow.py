"""Escritura consistente de la traza de la Orden.

Esto NO es un workflow engine: no decide cual es el proximo nodo, no
interpreta los YAML de ``business/`` y no conoce los edges del proceso.
La secuencia la compone el caller invocando services en orden; este
modulo solo centraliza como queda registrado cada evento.

Dos funciones, deliberadamente separadas:

- ``registrar_paso`` para los nodos del proceso (``PROC-REP-*``):
  agrega historial Y avanza ``current_process``.
- ``registrar_accion_funcional`` para las capacidades transversales
  (``ACC-REP-*``): agrega historial y NADA MAS. Registrar Pago no es un
  paso del flujo, asi que no puede mover el nodo actual.
"""

from datetime import datetime

from app.domain.models import (
    HistorialWorkflow,
    OrdenReparacion,
    TipoReferenciaHistorial,
)
from app.services.permisos import rol_habilitante


def registrar_paso(
    orden: OrdenReparacion,
    *,
    process_id: str,
    accion: str,
    fecha: datetime,
    usuario_id: str | None = None,
    reparacion_detail_id: str | None = None,
    ejecucion_id: str | None = None,
    observacion: str | None = None,
) -> OrdenReparacion:
    """Devuelve una copia de la Orden con el paso registrado.

    Actualiza ``current_process`` y ``updated_at``, y agrega la entrada
    al historial. La Orden recibida nunca se modifica: los services la
    usan como primer paso y siguen trabajando sobre la copia devuelta.

    ``process_id`` debe ser un ID real de ``business/`` (por ejemplo
    ``PROC-REP-185``); este modulo no los valida ni los inventa.

    Solo para nodos del proceso. Una capacidad transversal va por
    ``registrar_accion_funcional``: pasarla por aqui dejaria
    ``current_process = ACC-REP-020``, que es sencillamente falso.
    """
    nueva_orden = orden.model_copy(deep=True)

    nueva_orden.current_process = process_id
    nueva_orden.updated_at = fecha
    nueva_orden.historial.append(
        HistorialWorkflow(
            tipo_referencia=TipoReferenciaHistorial.PROCESS_NODE,
            referencia_id=process_id,
            accion=accion,
            fecha=fecha,
            usuario_id=usuario_id,
            rol=rol_habilitante(usuario_id),
            reparacion_detail_id=reparacion_detail_id,
            ejecucion_id=ejecucion_id,
            observacion=observacion,
        )
    )

    return nueva_orden


def registrar_accion_funcional(
    orden: OrdenReparacion,
    *,
    accion_id: str,
    accion: str,
    fecha: datetime,
    usuario_id: str | None = None,
    reparacion_detail_id: str | None = None,
    ejecucion_id: str | None = None,
    pago_id: str | None = None,
    observacion: str | None = None,
) -> OrdenReparacion:
    """Devuelve una copia de la Orden con la accion transversal anotada.

    Para las capacidades que FEAT/BR definen sin nodo propio en el
    Business Process (hoy: Registrar Pago, ``ACC-REP-020``,
    BR-REP-017-A). Deja traza en la Orden -que hasta ahora no quedaba en
    ningun lado- sin tocar ``current_process``: la Orden sigue parada
    donde estaba.

    ``accion_id`` es un ID real de la trazabilidad (``ACC-REP-*``); este
    modulo no los valida ni los inventa, igual que con los nodos.

    No es un event bus: registra lo que el service le pide y nada mas.
    """
    nueva_orden = orden.model_copy(deep=True)

    nueva_orden.updated_at = fecha
    nueva_orden.historial.append(
        HistorialWorkflow(
            tipo_referencia=TipoReferenciaHistorial.FUNCTIONAL_ACTION,
            referencia_id=accion_id,
            accion=accion,
            fecha=fecha,
            usuario_id=usuario_id,
            rol=rol_habilitante(usuario_id),
            reparacion_detail_id=reparacion_detail_id,
            ejecucion_id=ejecucion_id,
            pago_id=pago_id,
            observacion=observacion,
        )
    )

    return nueva_orden
