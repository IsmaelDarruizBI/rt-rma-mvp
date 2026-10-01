"""Progreso de una Orden: por que nodos del proceso ya paso.

Es un dato de VISUALIZACION, no de workflow: no autoriza nada, no
decide que accion corresponde y no gobierna ninguna transicion -eso lo
sigue haciendo el estado real de la Orden y los services cuando el
comando llega, ver ``application.acciones``-. Esto es solo lo que la
pantalla puede ofrecer para mostrarle al usuario donde esta la Orden
dentro de su recorrido de referencia.

La ruta de referencia esta declarada por Origen en ``_RUTAS_POR_ORIGEN``:
un dato explicito, no un interprete del Process Graph. CLIENTE_EXTERNO
(HP-REP-001) y RT_INTERNO (HP-REP-002) tienen su propia ruta poblada;
agregar la de HP-REP-003 en un slice futuro es agregar una entrada a
este dict, sin tocar ``progreso()``.
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
    ("PROC-REP-212", "Iniciar un Detalle de reparacion"),
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

# Nodos de HP-REP-003 (RMA_GARANTIA_REPARACION), en el orden en que el
# escenario los recorre. Parte de PROC-REP-035 (la Orden nace de una
# Orden origen ENTREGADA: no hay 010 ni 030) y, como todo Origen con
# entrega a cliente, recorre PROC-REP-265 pero nunca 266 (NO_COBRABLE).
_RUTA_RMA_GARANTIA_REPARACION: tuple[tuple[str, str], ...] = (
    ("PROC-REP-035", "Identificar reparacion original en garantia"),
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
    ("PROC-REP-212", "Iniciar un Detalle de reparacion"),
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
    ("PROC-REP-280", "Generar comprobante final"),
    ("PROC-REP-270", "Entregar equipo"),
    ("EVT-REP-999", "Proceso finalizado"),
)

# Nodos de HP-REP-002 (RT_INTERNO), en el orden en que el escenario los
# recorre. Diverge de CLIENTE_EXTERNO desde el ingreso (020 en vez de
# 030, sin comprobante de recepcion) y en el cierre (informar a Gestion
# RT en vez de notificar/cobrar/entregar a un cliente).
_RUTA_RT_INTERNO: tuple[tuple[str, str], ...] = (
    ("PROC-REP-010", "Identificar origen"),
    ("PROC-REP-020", "Recibir referencia y contexto del equipo RT"),
    ("PROC-REP-040", "Crear Orden"),
    ("PROC-REP-045", "Detalles conocidos"),
    ("PROC-REP-070", "Definir Detalles"),
    ("PROC-REP-050", "Requiere comprobante de recepcion"),
    ("PROC-REP-080", "Validar factibilidad"),
    ("PROC-REP-090", "Existe Detalle trabajable"),
    ("PROC-REP-140", "Habilitar Orden"),
    ("PROC-REP-150", "Definir prioridad"),
    ("PROC-REP-170", "Ingresar a cola"),
    ("PROC-REP-172", "Validar estacion de trabajo"),
    ("PROC-REP-180", "Tomar Orden"),
    ("PROC-REP-212", "Iniciar un Detalle de reparacion"),
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
    ("PROC-REP-290", "Informar resultado a Gestion RT"),
    ("PROC-REP-270", "Devolver equipo a Gestion RT"),
    ("EVT-REP-999", "Proceso finalizado"),
)

# Ruta de referencia por Origen. RMA_GARANTIA_REPARACION se agrega
# cuando HP-REP-003 tenga su propio recorrido conectado.
_RUTAS_POR_ORIGEN: dict[OrigenOrden, tuple[tuple[str, str], ...]] = {
    OrigenOrden.CLIENTE_EXTERNO: _RUTA_CLIENTE_EXTERNO,
    OrigenOrden.RT_INTERNO: _RUTA_RT_INTERNO,
    OrigenOrden.RMA_GARANTIA_REPARACION: _RUTA_RMA_GARANTIA_REPARACION,
}


@dataclass(frozen=True)
class PasoProgreso:
    """Un nodo de la ruta de referencia y si la Orden ya paso por el."""

    process_id: str
    etiqueta: str
    alcanzado: bool


_TRAMO_RECURSOS: tuple[tuple[str, str], ...] = (
    ("PROC-REP-100", "Registrar advertencia de faltante"),
    ("PROC-REP-110", "Usuario autorizado fuerza el Detalle bloqueado"),
    ("PROC-REP-120", "Detalle(s) pendientes por recursos"),
)


_NODO_OVERRIDE = ("PROC-REP-130", "Registrar override")


def _con_espera_de_recursos(
    ruta: tuple[tuple[str, str], ...],
    *,
    con_override: bool = False,
) -> tuple[tuple[str, str], ...]:
    """Intercala 100 -> 110 -> 120 despues de 090 (EXC-REP-001).

    Se muestra UNA vez aunque el historial tenga varios ciclos
    (120 -> 080 -> 090 -> 100 ...): el historial conserva cada intento.
    Con evidencia de PROC-REP-130 (override, EXC-REP-002) se agrega ese
    nodo tras 120.
    """
    resultado: list[tuple[str, str]] = []
    for nodo in ruta:
        resultado.append(nodo)
        if nodo[0] == "PROC-REP-090":
            resultado.extend(_TRAMO_RECURSOS)
            if con_override:
                resultado.append(_NODO_OVERRIDE)
    return tuple(resultado)


def _con_revision(
    ruta: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """La ruta de un Origen, pero pasando por revision (VAR-REP-001/002).

    PROC-REP-045 "No" reemplaza PROC-REP-070 por 055, y entre el
    comprobante (050 [-> 060]) y 080 se intercala 065 -> 068 -> 075. De
    080 en adelante converge con la ruta original.
    """
    resultado: list[tuple[str, str]] = []
    for nodo in ruta:
        process_id = nodo[0]
        if process_id == "PROC-REP-070":
            continue
        if process_id == "PROC-REP-080":
            resultado.extend(_TRAMO_REVISION)
        resultado.append(nodo)
        if process_id == "PROC-REP-045":
            resultado.append(("PROC-REP-055", "Marcar Orden en revision"))
    return tuple(resultado)


_TRAMO_REVISION: tuple[tuple[str, str], ...] = (
    ("PROC-REP-065", "Realizar revision tecnica"),
    ("PROC-REP-068", "Se pudo definir la reparacion requerida"),
    ("PROC-REP-075", "Definir Detalles luego de revision"),
)


def _ruta_esperada(orden: OrdenReparacion) -> tuple[tuple[str, str], ...]:
    """Ruta de referencia para mostrar el progreso de esta Orden.

    Si el Origen todavia no tiene una ruta propia declarada, se usa la
    de CLIENTE_EXTERNO como mejor aproximacion disponible: es solo
    visualizacion, nunca gobierna que accion corresponde.
    """
    ruta = _RUTAS_POR_ORIGEN.get(orden.origen, _RUTA_CLIENTE_EXTERNO)
    # La variante se reconoce por evidencia real (PROC-REP-055 en el
    # historial), no por un id de Scenario guardado en la Orden.
    alcanzados = nodos_alcanzados(orden)
    if "PROC-REP-055" in alcanzados:
        ruta = _con_revision(ruta)
    if "PROC-REP-100" in alcanzados:
        ruta = _con_espera_de_recursos(
            ruta, con_override="PROC-REP-130" in alcanzados
        )
    return ruta


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
