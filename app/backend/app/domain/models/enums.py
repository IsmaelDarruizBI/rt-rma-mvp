"""Conjuntos cerrados de valores del dominio RMA.

Alcance MVP v1: solo los valores que HP-REP-001 necesita. MVP v2
(Slice 0 - Foundation) amplia algunos de forma aditiva para representar
el dominio que HP-REP-002, HP-REP-003 y sus Variants/Exceptions van a
necesitar, sin activar todavia sus flujos: ver el docstring de cada
enum para lo que ya es operativo y lo que todavia no.
"""

from enum import Enum


class OrigenOrden(str, Enum):
    """Origen de la Orden de Reparacion.

    Los tres valores son los que ``docs/discovery/README.md`` fija como
    scope cerrado de MVP v2 (``RT_GARANTIA_VENTA`` queda deliberadamente
    afuera). Que el valor exista en el enum NO significa que la API ya
    pueda crear una Orden con ese origen: en Slice 0, ``CLIENTE_EXTERNO``
    sigue siendo el unico origen operativo -el unico que
    ``crear_orden_cliente_externo`` y ``CrearOrdenIn`` aceptan-.
    ``RT_INTERNO`` y ``RMA_GARANTIA_REPARACION`` quedan representados en
    el dominio y en ``app.domain.politicas`` para que los slices que
    implementan HP-REP-002 y HP-REP-003 no tengan que tocar el enum.
    """

    CLIENTE_EXTERNO = "CLIENTE_EXTERNO"
    RT_INTERNO = "RT_INTERNO"
    RMA_GARANTIA_REPARACION = "RMA_GARANTIA_REPARACION"


class EstadoWorkflow(str, Enum):
    """Hitos de workflow de la Orden, fijados por eventos explicitos.

    No deben confundirse con el estado tecnico agregado de BR-REP-012,
    que se deriva del conjunto de Detalles. Estos son hitos que avanzan
    por acciones concretas del flujo:

        PROC-REP-040 -> REQUERIMIENTO
        PROC-REP-055 -> EN_REVISION
        PROC-REP-140 -> HABILITADA
        PROC-REP-170 -> EN_COLA
        PROC-REP-185 -> EN_REPARACION
        PROC-REP-240 -> REPARACION_LISTA
        PROC-REP-270 -> ENTREGADA

    ``EN_REVISION`` (PROC-REP-055, VAR-REP-001/002) significa que la
    Orden espera o atraviesa una revision tecnica ANTES de poder definir
    sus Detalles (por eso admite cero Detalles). NO significa que la
    revision este embebida dentro de la Orden: ver
    ``app.services.revisiones``. ``CANCELADA`` existe en V1.3 pero el MVP
    todavia no la representa: la cancelacion esta fuera de scope de MVP v2.
    """

    REQUERIMIENTO = "REQUERIMIENTO"
    EN_REVISION = "EN_REVISION"
    HABILITADA = "HABILITADA"
    EN_COLA = "EN_COLA"
    EN_REPARACION = "EN_REPARACION"
    REPARACION_LISTA = "REPARACION_LISTA"
    ENTREGADA = "ENTREGADA"


class EstadoReparacionDetail(str, Enum):
    """Ciclo tecnico de un Detalle de Reparacion.

    Solo el avance del trabajo. La reserva de insumos vive en
    MovimientoInsumo y la aprobacion en ``ReparacionDetail.control_estado``:
    ninguna de las dos es un estado tecnico del Detalle. La condicion de
    bloqueo (``CondicionReparacionDetail``) tampoco es un estado tecnico:
    es una dimension independiente, ver esa clase.

    Los nombres no siguen literalmente al contrato funcional -que llama
    PENDIENTE / EN_PROCESO al primer y segundo valor-: se mantienen por
    compatibilidad con JSON, backend, frontend y tests ya existentes.
    Equivalencia:

        DEFINIDO      ~= PENDIENTE (contrato)
        EN_PROGRESO   ~= EN_PROCESO (contrato)
        COMPLETO      == COMPLETO
    """

    DEFINIDO = "DEFINIDO"
    EN_PROGRESO = "EN_PROGRESO"
    COMPLETO = "COMPLETO"


class CondicionReparacionDetail(str, Enum):
    """Condicion de bloqueo del Detalle: BR-REP-002/006/012.

    Dimension independiente de ``EstadoReparacionDetail``: un Detalle
    ``DEFINIDO`` puede estar disponible para trabajarse (``SIN_BLOQUEO``)
    o bloqueado por un motivo concreto. El resolver de BR-REP-012
    (``app.services.resolucion``) la consulta para derivar
    ``es_trabajable``, ``requiere_revision`` y ``bloqueado_por_recursos``.

    ``BLOQUEADO_POR_RECURSOS`` lo fija PROC-REP-080 por Detalle
    (EXC-REP-001) y se reevalua en cada revalidacion. ``REQUIERE_DEFINICION``
    (EXC-REP-004) lo asigna PROC-REP-200 "Requiere redefinicion" y lo quita
    PROC-REP-127; PROC-REP-080 no lo pisa. El resolver clasifica ambos.
    """

    SIN_BLOQUEO = "SIN_BLOQUEO"
    REQUIERE_DEFINICION = "REQUIERE_DEFINICION"
    BLOQUEADO_POR_RECURSOS = "BLOQUEADO_POR_RECURSOS"


class EstadoControl(str, Enum):
    """Resultado del control tecnico sobre un Detalle (PROC-REP-220)."""

    PENDIENTE = "PENDIENTE"
    APROBADO = "APROBADO"


class TipoMovimientoInsumo(str, Enum):
    """Tipos de movimiento de inventario trazados a un Detalle."""

    RESERVA = "RESERVA"
    CONSUMO = "CONSUMO"
    LIBERACION_RESERVA = "LIBERACION_RESERVA"
    DEVOLUCION = "DEVOLUCION"


class EstadoTomaOrden(str, Enum):
    """Estado de la participacion activa de un tecnico sobre la Orden."""

    ACTIVA = "ACTIVA"
    CERRADA = "CERRADA"


class EstadoEjecucion(str, Enum):
    """Estado de una Ejecucion concreta de un Detalle.

    ``COMPLETADO`` e ``INTERRUMPIDO`` son los dos resultados terminales de
    PROC-REP-200 (VAR-REP-003 agrega el segundo). Una Ejecucion terminal
    nunca se reabre: continuar un Detalle interrumpido es una Ejecucion
    NUEVA.
    """

    EN_PROGRESO = "EN_PROGRESO"
    COMPLETADO = "COMPLETADO"
    INTERRUMPIDO = "INTERRUMPIDO"


class RolUsuario(str, Enum):
    """Rol operativo del usuario dentro de RMA."""

    ADMINISTRADOR = "ADMINISTRADOR"
    RECEPCION = "RECEPCION"
    COORDINADOR_RMA = "COORDINADOR_RMA"
    TECNICO = "TECNICO"


class TipoReferenciaHistorial(str, Enum):
    """Que clase de referencia guarda una entrada del historial.

    PROCESS_NODE       -> paso del recorrido secuencial del Business
                          Process (``PROC-REP-*``). Avanza el flujo.
    FUNCTIONAL_ACTION  -> capacidad transversal ejecutada sobre la Orden
                          (``ACC-REP-*``). No pertenece al recorrido y
                          no mueve ``current_process``.
    """

    PROCESS_NODE = "PROCESS_NODE"
    FUNCTIONAL_ACTION = "FUNCTIONAL_ACTION"


class TipoPago(str, Enum):
    """Momento comercial en que se registra un Pago.

    Dimension distinta del medio de pago (``Pago.metodo``): un ANTICIPO
    en EFECTIVO y un PAGO en EFECTIVO son el mismo medio y distinto tipo.

    No lo elige el usuario: se deriva del estado de la Orden al
    registrarlo (ver ``app.services.pagos.registrar_pago``). BR-REP-017
    define el Pago como capacidad transversal, asi que puede registrarse
    antes de que la reparacion este lista.
    """

    ANTICIPO = "ANTICIPO"
    PAGO = "PAGO"


class EstadoPago(str, Enum):
    """Estado de cobro, siempre derivado del total y de lo pagado."""

    PENDIENTE = "PENDIENTE"
    PARCIAL = "PARCIAL"
    PAGADO = "PAGADO"
