"""Tramo de Recepcion: ingreso del equipo y definicion de la reparacion.

Comandos, uno por accion humana de ACT-RECEP:

    crear_orden          PROC-REP-010 -> 030 -> 040
    definir_reparacion   PROC-REP-045 -> 070 -> 050 -> 060 -> 080 ->
                         090 -> 140
    crear_garantia_rma   PROC-REP-035 -> 040 -> 045 -> 070 -> 050 ->
                         060 -> 080 -> 090 -> 140 (HP-REP-003)
    enviar_a_revision    PROC-REP-045 (No) -> 055 -> 050 -> 060 si
                         corresponde (VAR-REP-001/002)
    crear_garantia_rma_en_revision
                         PROC-REP-035 -> 040 -> 045 (No) -> 055 -> 050 ->
                         060 (VAR-REP-001)
    definir_reparacion_desde_revision
                         PROC-REP-068 (Si) -> 075 -> 080 -> 090 -> 140

El corte entre ambos es la frontera del actor: entre 040 y 045 el
proceso vuelve a pedirle algo a Recepcion (que reparacion se va a
hacer), asi que son dos intenciones distintas y dos endpoints distintos.
Dentro de cada comando, los nodos ACT-SYSTEM y las decisiones que
siguen (050/060/080/090/140) se encadenan sin volver a preguntar.
"""

from datetime import datetime

from app.domain.models import Cliente, Equipo, OrdenReparacion
from app.services import (
    RecursoNoDisponibleError,
    cargar_reservas_externas,
    crear_orden_cliente_externo,
    crear_orden_garantia_rma,
    crear_orden_rt_interno,
    definir_reparacion_detail,
    definir_reparacion_detail_luego_revision,
    generar_comprobante_recepcion,
    habilitar_orden,
    marcar_orden_en_revision,
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


def crear_orden_rt(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    equipo: Equipo,
    referencia_rt: str,
) -> OrdenReparacion:
    """Ingreso de un equipo RT_INTERNO (PROC-REP-010/020/040, HP-REP-002).

    Analoga a ``crear_orden`` pero sin Cliente: el equipo es de Rosario
    Tecno. El resto del recorrido -definir la reparacion, factibilidad,
    habilitar- es exactamente el mismo comando (``definir_reparacion``):
    la diferencia por Origen queda contenida en los services, no
    duplicada aqui.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with seccion_critica_inventario():
        orden = crear_orden_rt_interno(
            orden_id=siguiente_orden_id(contexto.ordenes),
            equipo=equipo,
            referencia_rt=referencia_rt,
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
        orden = _finalizar_definicion(contexto, orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden


def _finalizar_definicion(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-050 -> 060 -> 080 -> 090 -> 140: de Detalles a HABILITADA.

    Compartido por ``definir_reparacion`` y ``crear_garantia_rma``. El
    tramo 080 -> 140 es ``_validar_y_habilitar``.
    """
    orden = generar_comprobante_recepcion(orden, fecha=fecha)
    return _validar_y_habilitar(contexto, orden, fecha=fecha)


def _validar_y_habilitar(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-080 -> 090 -> 140: factibilidad y habilitacion.

    Tambien lo usa el camino de revision (075 -> 080), donde el
    comprobante ya se genero antes del diagnostico.
    """
    orden, factible = validar_factibilidad_detalles(
        orden,
        insumos=contexto.catalogos.listar_insumos(),
        insumos_previstos=contexto.catalogos.listar_tipo_reparacion_insumos(),
        fecha=fecha,
        reservas_externas=cargar_reservas_externas(orden.id, contexto.ordenes),
    )
    if not factible:
        raise RecursoNoDisponibleError(
            "No hay disponibilidad de insumos para la reparacion "
            "pedida (PROC-REP-090). El MVP no resuelve el camino de "
            "faltante, asi que la Orden no se modifico."
        )

    return habilitar_orden(orden, fecha=fecha)


def crear_garantia_rma(
    contexto: ApplicationContext,
    *,
    orden_origen_id: str,
    detalle_origen_id: str,
    usuario_id: str,
) -> OrdenReparacion:
    """Recepcion genera la garantia RMA de un Detalle (HP-REP-003).

    Encadena PROC-REP-035 -> 040 (Orden nueva vinculada), 045 -> 070
    (un Detalle de garantia que referencia al Detalle origen) y, desde
    ahi, 050 -> 060 -> 080 -> 090 -> 140 igual que ``definir_reparacion``.
    Es un unico comando porque Recepcion ya eligio que Detalle reprocesar.

    Devuelve la Orden NUEVA. La Orden origen solo se lee: no se vuelve a
    guardar ni se modifica (BR-REP-019). El Detalle nuevo es del mismo
    Tipo de Reparacion y toma un snapshot propio del catalogo actual.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden_origen = contexto.ordenes.obtener(orden_origen_id)

    with seccion_critica_inventario():
        orden = crear_orden_garantia_rma(
            orden_id=siguiente_orden_id(contexto.ordenes),
            orden_origen=orden_origen,
            detalle_origen_id=detalle_origen_id,
            usuario=usuario,
            fecha=fecha,
        )
        detalle_origen = next(
            detalle
            for detalle in orden_origen.reparaciones_detail
            if detalle.id == detalle_origen_id
        )
        orden = definir_reparacion_detail(
            orden,
            detalle_id=siguiente_detalle_id(orden),
            tipo_reparacion=contexto.catalogos.obtener_tipo_reparacion(
                detalle_origen.tipo_reparacion_id
            ),
            usuario=usuario,
            fecha=fecha,
            detalle_origen_id=detalle_origen_id,
        )
        orden = _finalizar_definicion(contexto, orden, fecha=fecha)
        contexto.ordenes.guardar(orden)

    return orden


def enviar_a_revision(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
) -> OrdenReparacion:
    """Recepcion envia una Orden sin diagnostico a revision (VAR-REP-001/002).

    PROC-REP-045 (No) -> 055 (EN_REVISION) -> 050 y, si la politica del
    Origen exige comprobante, 060. La Orden queda EN_REVISION y sin
    Detalles: el comprobante no los lista ("reparacion pendiente de
    diagnostico"). La diferencia entre VAR-REP-001 y VAR-REP-002 sale solo
    de ``PoliticaOrigen.requiere_comprobante_recepcion``.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    orden = marcar_orden_en_revision(orden, usuario=usuario, fecha=fecha)
    orden = generar_comprobante_recepcion(orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden


def crear_garantia_rma_en_revision(
    contexto: ApplicationContext,
    *,
    orden_origen_id: str,
    detalle_origen_id: str,
    usuario_id: str,
) -> OrdenReparacion:
    """Garantia RMA que entra directamente en revision (VAR-REP-001).

    PROC-REP-035 -> 040 -> 045 (No) -> 055 -> 050 -> 060 y se detiene:
    todavia no hay Detalles. La procedencia queda en ``orden_origen_id`` y
    ``detalles_origen_ids``. Igual que HP-REP-003, la Orden origen solo
    se lee: no se guarda ni se modifica.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden_origen = contexto.ordenes.obtener(orden_origen_id)

    with seccion_critica_inventario():
        orden = crear_orden_garantia_rma(
            orden_id=siguiente_orden_id(contexto.ordenes),
            orden_origen=orden_origen,
            detalle_origen_id=detalle_origen_id,
            usuario=usuario,
            fecha=fecha,
        )
        orden = marcar_orden_en_revision(orden, usuario=usuario, fecha=fecha)
        orden = generar_comprobante_recepcion(orden, fecha=fecha)
        contexto.ordenes.guardar(orden)

    return orden


def definir_reparacion_desde_revision(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    tipo_reparacion_id: str,
    observaciones: str | None = None,
    finalizar_definicion: bool = True,
    detalle_origen_id: str | None = None,
) -> OrdenReparacion:
    """Recepcion define un Detalle luego de la revision (VAR-REP-001/002).

    PROC-REP-068 (Si, una sola vez) -> 075 por Detalle y, con
    ``finalizar_definicion``, 080 -> 090 -> 140. NO repite 050/060: el
    comprobante se genero antes del diagnostico.

    ``detalle_origen_id`` solo hace falta en una garantia con mas de un
    Detalle origen identificado.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    tipo = contexto.catalogos.obtener_tipo_reparacion(tipo_reparacion_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)

    orden = definir_reparacion_detail_luego_revision(
        orden,
        detalle_id=siguiente_detalle_id(orden),
        tipo_reparacion=tipo,
        usuario=usuario,
        fecha=fecha,
        observaciones=observaciones,
        detalle_origen_id=detalle_origen_id,
    )

    if finalizar_definicion:
        orden = _validar_y_habilitar(contexto, orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden
