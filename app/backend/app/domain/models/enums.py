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
    ``app.services.revisiones``.

    ``CANCELADA`` (BR-REP-014) la fija PROC-REP-211 cuando todos los
    Detalles quedan CANCELADO, o PROC-REP-306 al cancelar una Orden sin
    Detalles. NO equivale a ENTREGADA: si el equipo esta en custodia, su
    devolucion fisica (PROC-REP-270) se registra despues, y recien ahi el
    proceso termina (EVT-REP-999); la Orden sigue CANCELADA.
    """

    REQUERIMIENTO = "REQUERIMIENTO"
    EN_REVISION = "EN_REVISION"
    HABILITADA = "HABILITADA"
    EN_COLA = "EN_COLA"
    EN_REPARACION = "EN_REPARACION"
    REPARACION_LISTA = "REPARACION_LISTA"
    ENTREGADA = "ENTREGADA"
    CANCELADA = "CANCELADA"


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
        CANCELADO     == CANCELADO (PROC-REP-300/305, BR-REP-014)

    COMPLETO y CANCELADO son terminales. Un Detalle CANCELADO no se borra:
    conserva Tipo, precio snapshot e historial, y deja de cobrarse.
    """

    DEFINIDO = "DEFINIDO"
    EN_PROGRESO = "EN_PROGRESO"
    COMPLETO = "COMPLETO"
    CANCELADO = "CANCELADO"


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
    """Control tecnico VIGENTE de un Detalle (PROC-REP-220).

    Describe el ciclo de control actual: un rechazo (PROC-REP-235) reabre
    el Detalle y su control vuelve a PENDIENTE hasta el retrabajo. Lo que
    paso en cada control queda en ``ReparacionDetail.controles``.
    """

    PENDIENTE = "PENDIENTE"
    APROBADO = "APROBADO"


class ResultadoControl(str, Enum):
    """Resultado de UN control tecnico registrado (PROC-REP-220/235)."""

    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"


class ResultadoAutorizacion(str, Enum):
    """Decision del cliente sobre UN Detalle (PROC-REP-046, BR-REP-028).

    Solo los dos resultados que se REGISTRAN. "Sin respuesta" no es una
    decision: no se persiste nada y el Detalle sigue pendiente (estado
    derivado, ver ``app.services.autorizacion_cliente``).
    """

    AUTORIZADO = "AUTORIZADO"
    RECHAZADO = "RECHAZADO"


class CanalComunicacion(str, Enum):
    """Por donde respondio el cliente (evidencia de consentimiento).

    BR-REP-028 deja el canal pendiente de decision de negocio: estos
    valores son la lista provisoria del MVP, con ``OTRO`` como salida.
    """

    PRESENCIAL = "PRESENCIAL"
    TELEFONO = "TELEFONO"
    WHATSAPP = "WHATSAPP"
    EMAIL = "EMAIL"
    OTRO = "OTRO"


class OrigenCancelacion(str, Enum):
    """Por que se cancelo un Detalle (PROC-REP-300/305).

    ``INTERNA``: lo decidio Recepcion o Coordinacion. ``RECHAZO_CLIENTE``:
    el cliente rechazo la propuesta pendiente (PROC-REP-047).
    ``DESISTIMIENTO_CLIENTE``: el cliente la habia autorizado y desistio
    despues, antes de que se realizara; su autorizacion queda en la
    historia, sin reemplazarse.
    """

    INTERNA = "INTERNA"
    RECHAZO_CLIENTE = "RECHAZO_CLIENTE"
    DESISTIMIENTO_CLIENTE = "DESISTIMIENTO_CLIENTE"


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
    registrarlo (ver ``app.services.pagos.tipo_de_pago_para``). BR-REP-017
    define el Pago como capacidad transversal, asi que puede registrarse
    antes de que la reparacion este lista:

        ANTICIPO  antes de que la Orden tenga resultado (seña, adelanto)
        PARCIAL   en el cierre, sin saldar la cuenta
        FINAL     en el cierre, salda la cuenta

    ``PAGO`` es el valor anterior a esta distincion (cobro del cierre sin
    distinguir parcial o final): se conserva para leer JSON anteriores y
    ya no se genera.
    """

    ANTICIPO = "ANTICIPO"
    PARCIAL = "PARCIAL"
    FINAL = "FINAL"
    PAGO = "PAGO"


class EstadoPago(str, Enum):
    """Estado de cobro, siempre derivado del total, lo pagado y lo devuelto.

    ``SALDO_A_FAVOR``: el cliente pago mas que el total final (por ejemplo,
    se cancelaron trabajos despues de un anticipo) y queda dinero por
    devolverle (BR-REP-038).
    """

    PENDIENTE = "PENDIENTE"
    PARCIAL = "PARCIAL"
    PAGADO = "PAGADO"
    SALDO_A_FAVOR = "SALDO_A_FAVOR"


class RegistroRecepcion(str, Enum):
    """Como nacio el registro de recepcion fisica del equipo.

    INGRESO         se registro al crear la Orden (PROC-REP-030/020/035)
    REGULARIZACION  se registro despues, sobre una Orden anterior a
                    este registro: nadie documento el ingreso en su
                    momento y no se presume que haya ocurrido
    """

    INGRESO = "INGRESO"
    REGULARIZACION = "REGULARIZACION"


class EstadoCustodia(str, Enum):
    """Donde esta el equipo fisicamente. Siempre derivado, nunca persistido.

    Es independiente del comprobante de recepcion: emitir un documento no
    prueba que el equipo este en el local.

        PENDIENTE_CONFIRMACION  hay datos de ingreso, falta confirmar que el
                                equipo se recibio
        SIN_REGISTRO            Orden anterior al registro de recepcion:
                                requiere regularizacion
        EN_CUSTODIA             recepcion confirmada (o equipo RT_INTERNO
                                recibido por el circuito de Gestion RT)
        ENTREGADO               salio por la entrega de la Orden
        DEVUELTO                salio sin reparar (cancelacion) o volvio a
                                Gestion RT
        NO_RECIBIDO             se registro explicitamente que el equipo
                                nunca ingreso (nunca se deduce)
    """

    PENDIENTE_CONFIRMACION = "PENDIENTE_CONFIRMACION"
    SIN_REGISTRO = "SIN_REGISTRO"
    EN_CUSTODIA = "EN_CUSTODIA"
    ENTREGADO = "ENTREGADO"
    DEVUELTO = "DEVUELTO"
    NO_RECIBIDO = "NO_RECIBIDO"


class TipoEntrega(str, Enum):
    """Que se le entrega a quien retira el equipo (PROC-REP-270).

    No lo elige el usuario: sale del resultado de la Orden. Una devolucion
    sin reparacion (Orden SIN_REPARACION o CANCELADA) nunca es una entrega
    de reparacion terminada.
    """

    REPARACION_TERMINADA = "REPARACION_TERMINADA"
    DEVOLUCION_SIN_REPARACION = "DEVOLUCION_SIN_REPARACION"


class TipoDocumento(str, Enum):
    """Documentos que la Orden emite al cliente.

    COMPROBANTE_RECEPCION  PROC-REP-060 (FEAT-REP-001)
    COMPROBANTE_ENTREGA    PROC-REP-280, o la devolucion sin reparar
                           de una Orden CANCELADA (PROC-REP-270)
    GARANTIA               PROC-REP-280, solo con trabajos realizados
    """

    COMPROBANTE_RECEPCION = "COMPROBANTE_RECEPCION"
    COMPROBANTE_ENTREGA = "COMPROBANTE_ENTREGA"
    GARANTIA = "GARANTIA"
