"""Tramo de Recepcion: ingreso del equipo y definicion de la reparacion.

Dos comandos, uno por accion humana de ACT-RECEP:

    crear_orden          PROC-REP-010 -> 030 -> 040
    definir_reparacion   PROC-REP-045 -> 070 -> 050 -> 060 -> 080 ->
                         090 -> 140

El corte entre ambos es la frontera del actor: entre 040 y 045 el
proceso vuelve a pedirle algo a Recepcion (que reparacion se va a
hacer), asi que son dos intenciones distintas y dos endpoints distintos.
Dentro de cada comando, los nodos ACT-SYSTEM y las decisiones que
siguen (050/060/080/090/140) se encadenan sin volver a preguntar.
"""

from app.domain.models import Cliente, Equipo, OrdenReparacion
from app.services import (
    RecursoNoDisponibleError,
    cargar_reservas_externas,
    crear_orden_cliente_externo,
    definir_reparacion_detail,
    generar_comprobante_recepcion,
    habilitar_orden,
    validar_factibilidad_detalles,
)

from .concurrencia import seccion_critica_inventario
from .contexto import ApplicationContext
from .identificadores import siguiente_detalle_id, siguiente_orden_id


def crear_orden(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    cliente: Cliente,
    equipo: Equipo,
) -> OrdenReparacion:
    """Ingreso de un equipo de CLIENTE_EXTERNO (PROC-REP-010/030/040).

    La Orden nace en REQUERIMIENTO y sin Detalles: el proceso continua
    cuando Recepcion define la reparacion.

    La numeracion se calcula sobre lo persistido, asi que se asigna
    dentro de la seccion critica: dos altas simultaneas no pueden
    quedarse con el mismo ``OR-XXXXXX``.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with seccion_critica_inventario():
        orden = crear_orden_cliente_externo(
            orden_id=siguiente_orden_id(contexto.ordenes),
            cliente=cliente,
            equipo=equipo,
            usuario=usuario,
            fecha=fecha,
        )
        contexto.ordenes.guardar(orden)

    return orden


def definir_reparacion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    tipo_reparacion_id: str,
    observaciones: str | None = None,
    finalizar_definicion: bool = True,
) -> OrdenReparacion:
    """Recepcion define un Detalle de la reparacion (Multi-Detalle).

    Encadena PROC-REP-045 -> 070 (Detalle con precio snapshot) y, solo
    cuando ``finalizar_definicion`` es verdadero, PROC-REP-050 -> 060
    (comprobante de recepcion), PROC-REP-080 -> 090 (factibilidad) y
    PROC-REP-140 (habilitar).

    Una Orden puede recibir N Detalles: cada llamada agrega uno nuevo
    mientras la Orden siga en REQUERIMIENTO. ``finalizar_definicion``
    (default ``True``, aditivo) es la extension minima que permite
    seguir agregando Detalles sin habilitar la Orden todavia -Recepcion
    llama de nuevo con ``finalizar_definicion=False`` por cada Detalle
    que todavia no es el ultimo, y con ``True`` (o el default) en el
    ultimo-. Con un unico Detalle el comportamiento es identico al de
    antes: HP-REP-001 no necesita ningun paso nuevo.

    La factibilidad CONSULTA el stock global -lo que las demas Ordenes
    tienen reservado- pero NO reserva nada (BR-REP-006): la reserva real
    ocurre recien cuando un tecnico inicia el Detalle. Por eso este
    comando no entra en la seccion critica de inventario: no escribe
    stock ni compite por el.

    Si no hay disponibilidad, PROC-REP-090 da "No" y el MVP corta: los
    caminos de faltante (PROC-REP-100/110/120/130) no estan
    implementados.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    tipo = contexto.catalogos.obtener_tipo_reparacion(tipo_reparacion_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)

    orden = definir_reparacion_detail(
        orden,
        detalle_id=siguiente_detalle_id(orden),
        tipo_reparacion=tipo,
        usuario=usuario,
        fecha=fecha,
        observaciones=observaciones,
    )

    if finalizar_definicion:
        orden = generar_comprobante_recepcion(orden, fecha=fecha)

        orden, factible = validar_factibilidad_detalles(
            orden,
            insumos=contexto.catalogos.listar_insumos(),
            insumos_previstos=(
                contexto.catalogos.listar_tipo_reparacion_insumos()
            ),
            fecha=fecha,
            reservas_externas=cargar_reservas_externas(
                orden.id, contexto.ordenes
            ),
        )
        if not factible:
            raise RecursoNoDisponibleError(
                "No hay disponibilidad de insumos para la reparacion "
                "pedida (PROC-REP-090). El MVP no resuelve el camino de "
                "faltante, asi que la Orden no se modifico."
            )

        orden = habilitar_orden(orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden
