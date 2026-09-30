"""Progreso de una Orden: por que nodos del proceso ya paso.

Es un dato de VISUALIZACION, no de workflow: no autoriza nada, no
decide que accion corresponde y no gobierna ninguna transicion -eso lo
sigue haciendo el estado real de la Orden y los services cuando el
comando llega, ver ``application.acciones``-. Esto es solo lo que la
pantalla puede ofrecer para mostrarle al usuario donde esta la Orden
dentro de su recorrido de referencia.

La ruta de referencia esta declarada por Origen en ``_RUTAS_POR_ORIGEN``:
un dato explicito, no un interprete del Process Graph. En Slice 0 solo
``CLIENTE_EXTERNO`` tiene Ordenes reales -es el unico origen que la API
puede crear-, asi que es la unica ruta poblada; agregar la de
HP-REP-002 o HP-REP-003 en un slice futuro es agregar una entrada a este
dict, sin tocar ``progreso()``.
"""

from dataclasses import dataclass

from app.domain.models import OrdenReparacion, OrigenOrden

# Nodos de HP-REP-001, en el orden en que el escenario los recorre.
# ``EVT-REP-999`` no genera historial: se alcanza cuando la Orden queda
# en ese ``current_process``.
_RUTA_CLIENTE_EXTERNO: tuple[tuple[str, str], ...] = (
    ("PROC-REP-010", "Identificar origen"),
    ("PROC-REP-030", "Registrar cliente y equipo"),
    ("PROC-REP-040", "Crear Orden"),
    ("PROC-REP-045", "Detalles conocidos"),
    ("PROC-REP-070", "Definir Detalles"),
    ("PROC-REP-050", "Requiere comprobante de recepcion"),
    ("PROC-REP-060", "Generar comprobante de recepcion"),
    ("PROC-REP-080", "Validar factibilidad"),
    ("PROC-REP-090", "Existe Detalle trabajable"),
    ("PROC-REP-140", "Habilitar Orden"),
    ("PROC-REP-150", "Definir prioridad"),
    ("PROC-REP-170", "Ingresar a cola"),
    ("PROC-REP-172", "Validar estacion de trabajo"),
    ("PROC-REP-180", "Tomar Orden"),
    ("PROC-REP-181", "Seleccionar Detalle"),
    ("PROC-REP-174", "Estacion habilitada para el Detalle"),
    ("PROC-REP-185", "Reservar insumos e iniciar Ejecucion"),
    ("PROC-REP-190", "Ejecutar Detalle"),
    ("PROC-REP-200", "Registrar ejecucion real"),
    ("PROC-REP-210", "Aplicar movimientos de inventario"),
    ("PROC-REP-211", "Evaluar situacion de la Orden"),
    ("PROC-REP-220", "Realizar control tecnico"),
    ("PROC-REP-230", "Todos los Detalles aprobados"),
    ("PROC-REP-245", "Consolidar puntaje"),
    ("PROC-REP-240", "Marcar reparacion lista"),
    ("PROC-REP-250", "Requiere entrega a cliente"),
    ("PROC-REP-260", "Notificar cliente"),
    ("PROC-REP-265", "Validar condicion de entrega"),
    ("PROC-REP-266", "Saldo pendiente"),
    ("PROC-REP-280", "Generar comprobante final"),
    ("PROC-REP-270", "Entregar equipo"),
    ("EVT-REP-999", "Proceso finalizado"),
)

# Ruta de referencia por Origen. Solo CLIENTE_EXTERNO tiene Ordenes
# reales en Slice 0; RT_INTERNO y RMA_GARANTIA_REPARACION se agregan
# cuando HP-REP-002 y HP-REP-003 tengan su propio recorrido conectado.
_RUTAS_POR_ORIGEN: dict[OrigenOrden, tuple[tuple[str, str], ...]] = {
    OrigenOrden.CLIENTE_EXTERNO: _RUTA_CLIENTE_EXTERNO,
}


@dataclass(frozen=True)
class PasoProgreso:
    """Un nodo de la ruta de referencia y si la Orden ya paso por el."""

    process_id: str
    etiqueta: str
    alcanzado: bool


def _ruta_esperada(orden: OrdenReparacion) -> tuple[tuple[str, str], ...]:
    """Ruta de referencia para mostrar el progreso de esta Orden.

    Si el Origen todavia no tiene una ruta propia declarada, se usa la
    de CLIENTE_EXTERNO como mejor aproximacion disponible: es solo
    visualizacion, nunca gobierna que accion corresponde.
    """
    return _RUTAS_POR_ORIGEN.get(orden.origen, _RUTA_CLIENTE_EXTERNO)


def nodos_alcanzados(orden: OrdenReparacion) -> set[str]:
    """IDs de proceso por los que la Orden ya paso."""
    # Solo los nodos: una accion transversal (ACC-REP-*) no forma parte
    # del recorrido y no debe marcar progreso.
    alcanzados = {
        paso.referencia_id
        for paso in orden.historial
        if paso.process_id is not None
    }
    if orden.current_process == "EVT-REP-999":
        alcanzados.add("EVT-REP-999")
    return alcanzados


def progreso(orden: OrdenReparacion) -> list[PasoProgreso]:
    """Recorrido de referencia de la Orden marcando lo ya transitado."""
    alcanzados = nodos_alcanzados(orden)
    return [
        PasoProgreso(
            process_id=process_id,
            etiqueta=etiqueta,
            alcanzado=process_id in alcanzados,
        )
        for process_id, etiqueta in _ruta_esperada(orden)
    ]
