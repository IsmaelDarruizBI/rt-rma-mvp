"""Tramo de Recepcion: ingreso del equipo y definicion de la reparacion.

Comandos, uno por intencion humana de ACT-RECEP:

    crear_orden          PROC-REP-010 -> 030 -> 040
    definir_reparacion   agrega UN Detalle: PROC-REP-045 (Si, una vez)
                         -> 070
    enviar_a_revision    PROC-REP-045 (No) -> 055 -> 050 -> 060 si
                         corresponde (VAR-REP-001/002)
    definir_reparacion_desde_revision
                         agrega UN Detalle: PROC-REP-068 (Si, una vez)
                         -> 075
    finalizar_definicion cierra la carga de Detalles: [050 -> 060 si
                         todavia no se evaluo el comprobante] -> 080 ->
                         090 -> 140 | 100
    finalizar_sin_reparacion
                         PROC-REP-068 (No) -> 069 (SIN_REPARACION)
    iniciar_garantia_rma PROC-REP-035 (1..N Detalles origen) -> 040 ->
                         045 (No) -> 055 -> 050 -> 060 (HP-REP-003)

Agregar un Detalle y finalizar la definicion son intenciones distintas:
agregar nunca genera comprobante, valida factibilidad ni habilita. Dentro
de cada comando, los nodos ACT-SYSTEM y las decisiones que siguen se
encadenan sin volver a preguntar.
"""

from collections.abc import Sequence
from datetime import datetime

from app.domain.models import Cliente, Equipo, OrdenReparacion
from app.services import (
    cargar_reservas_externas,
    crear_orden_cliente_externo,
    crear_orden_garantia_rma,
    crear_orden_rt_interno,
    definir_reparacion_detail,
    definir_reparacion_detail_luego_revision,
    exigir_definicion_finalizable,
    generar_comprobante_recepcion,
    habilitar_orden,
    marcar_orden_en_revision,
    registrar_finalizacion_sin_reparacion,
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
) -> OrdenReparacion:
    """Recepcion AGREGA un Detalle de la reparacion (Multi-Detalle).

    Registra PROC-REP-045 ("Si", solo con el primer Detalle) -> 070, con
    el precio snapshot del Tipo. Una sola intencion: no genera el
    comprobante, no valida factibilidad ni habilita la Orden. La Orden
    sigue en REQUERIMIENTO, lista para recibir otro Detalle o para que
    Recepcion finalice la definicion (``finalizar_definicion``).
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

    contexto.ordenes.guardar(orden)
    return orden


def finalizar_definicion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
) -> OrdenReparacion:
    """Recepcion cierra la carga de Detalles (FINALIZAR_DEFINICION).

    Exige ACT-RECEP, al menos un Detalle y la definicion todavia abierta.
    Reutiliza los services existentes, sin duplicarlos:

    - camino normal (REQUERIMIENTO): PROC-REP-050 -> 060 si corresponde y
      despues 080 -> 090 -> 140 | 100;
    - camino de revision (EN_REVISION, Detalles definidos por 075): el
      comprobante ya se evaluo antes del diagnostico, asi que va directo a
      080 -> 090 -> 140 | 100, sin regenerarlo.

    La distincion sale del historial (PROC-REP-050 ya evaluado), no de un
    flag. Si ningun Detalle es trabajable, la Orden queda en PROC-REP-100
    (EXC-REP-001/002), sin error. Persiste una sola vez.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    exigir_definicion_finalizable(orden, usuario=usuario)

    if not any(paso.process_id == "PROC-REP-050" for paso in orden.historial):
        orden = generar_comprobante_recepcion(orden, fecha=fecha)
    orden = _validar_y_habilitar(contexto, orden, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden


def _validar_y_habilitar(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-080 -> 090 -> 140: factibilidad y habilitacion.

    Tambien lo usa el camino de revision (075 -> 080) y la revalidacion de
    recursos (120 -> 080); el comprobante ya se genero antes.

    La factibilidad es por Detalle: basta uno trabajable para habilitar.
    Si ninguno lo es (EXC-REP-001) NO es un error: la Orden queda detenida
    en PROC-REP-100 -con los Detalles BLOQUEADO_POR_RECURSOS- y el caller
    la persiste; despues se espera (110 No -> 120) y se revalida.
    """
    orden, factible = validar_factibilidad_detalles(
        orden,
        insumos=contexto.catalogos.listar_insumos(),
        insumos_previstos=contexto.catalogos.listar_tipo_reparacion_insumos(),
        fecha=fecha,
        reservas_externas=cargar_reservas_externas(orden.id, contexto.ordenes),
    )
    if not factible:
        return orden

    return habilitar_orden(orden, fecha=fecha)


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


def iniciar_garantia_rma(
    contexto: ApplicationContext,
    *,
    orden_origen_id: str,
    detalle_origen_ids: Sequence[str],
    usuario_id: str,
) -> OrdenReparacion:
    """Recepcion inicia la garantia RMA de una Orden ENTREGADA (HP-REP-003).

    Una unica entrada canonica: PROC-REP-035 (1..N Detalles origen) ->
    040 -> 045 (No) -> 055 (EN_REVISION) -> 050 -> 060, y se detiene a
    esperar la revision tecnica (PROC-REP-065). La revision es obligatoria
    (BR-REP-019): no existe ningun camino que copie el Tipo del Detalle
    origen y deje la garantia habilitada.

    Devuelve la UNICA Orden NUEVA, sin Detalles propios todavia. La Orden
    origen solo se lee: no se guarda ni se modifica.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden_origen = contexto.ordenes.obtener(orden_origen_id)

    with seccion_critica_inventario():
        orden = crear_orden_garantia_rma(
            orden_id=siguiente_orden_id(contexto.ordenes),
            orden_origen=orden_origen,
            detalle_origen_ids=list(detalle_origen_ids),
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
    detalle_origen_id: str | None = None,
) -> OrdenReparacion:
    """Recepcion AGREGA un Detalle luego de la revision (075).

    PROC-REP-068 ("Si", solo con el primer Detalle) -> 075. Una sola
    intencion: no valida factibilidad ni habilita; la carga se cierra con
    ``finalizar_definicion``. NO repite 050/060: el comprobante se genero
    antes del diagnostico.

    En una garantia RMA, ``detalle_origen_id`` elige a cual de los
    Detalles origen de la Orden corresponde el Detalle nuevo (obligatorio
    si hay mas de uno).
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

    contexto.ordenes.guardar(orden)
    return orden


def finalizar_sin_reparacion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    motivo: str,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """Recepcion finaliza la Orden SIN_REPARACION (068 No -> 069).

    BR-REP-010: tras la revision tecnica, sin Detalles y con motivo
    obligatorio. No crea Detalles ni precio (Subtotal 0) y no cambia el
    estado de workflow. Despues sigue el cierre segun el Origen
    (``application.cierre``: notificar o informar a Gestion RT).
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    orden = registrar_finalizacion_sin_reparacion(
        orden,
        usuario=usuario,
        motivo=motivo,
        observaciones=observaciones,
        fecha=fecha,
    )

    contexto.ordenes.guardar(orden)
    return orden
