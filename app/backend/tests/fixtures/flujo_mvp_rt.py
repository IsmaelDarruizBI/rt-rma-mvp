"""Atajos para llevar una Orden RT_INTERNO hasta un punto de HP-REP-002.

Analogo a ``flujo_mvp.py`` (HP-REP-001), pero para el origen RT_INTERNO:
sin Cliente, sin comprobante de recepcion, y con el cierre propio de
Gestion RT (informar resultado + devolucion del equipo) en vez de
notificar/cobrar/entregar a un cliente.

Todo se construye componiendo los mismos services que usara la API: no
hay ningun atajo que fabrique estado a mano.
"""

from decimal import Decimal

from app.domain.models import InsumoUtilizado, OrdenReparacion
from app.services import (
    aprobar_control_tecnico,
    calcular_puntaje,
    crear_orden_rt_interno,
    definir_prioridad,
    definir_reparacion_detail,
    devolver_equipo_rt,
    ejecutar_detalle,
    evaluar_situacion_orden,
    generar_comprobante_recepcion,
    generar_movimientos_inventario,
    habilitar_orden,
    informar_resultado_rt,
    ingresar_a_cola,
    marcar_reparacion_lista,
    registrar_ejecucion_completada,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_estacion_trabajo,
    validar_factibilidad_detalles,
)

from .catalogos_mvp import (
    ADMINISTRADOR,
    COMPATIBILIDADES,
    COORDINADOR,
    EQUIPO,
    ESTACION,
    ESTACIONES,
    INSUMOS,
    INSUMOS_PREVISTOS,
    RECEPCION,
    TECNICO,
    TIPO_BATERIA,
    t,
)

DETALLE_ID = "DET-001"
REFERENCIA_RT = "RT-INGRESO-0001"


def orden_rt_creada() -> OrdenReparacion:
    """Hasta PROC-REP-040: Orden RT_INTERNO en REQUERIMIENTO, sin Cliente."""
    return crear_orden_rt_interno(
        orden_id="OR-001",
        equipo=EQUIPO,
        referencia_rt=REFERENCIA_RT,
        usuario=RECEPCION,
        fecha=t(0),
    )


def orden_rt_con_detalle() -> OrdenReparacion:
    """Hasta PROC-REP-050 ('No'): un Detalle DEFINIDO, sin comprobante."""
    orden = definir_reparacion_detail(
        orden_rt_creada(),
        detalle_id=DETALLE_ID,
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(5),
    )
    return generar_comprobante_recepcion(orden, fecha=t(10))


def orden_rt_en_cola() -> OrdenReparacion:
    """Hasta PROC-REP-170: Orden EN_COLA, lista para tomarse."""
    orden, _ = validar_factibilidad_detalles(
        orden_rt_con_detalle(),
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(15),
    )
    orden = habilitar_orden(orden, fecha=t(20))
    orden = definir_prioridad(
        orden, prioridad=1, usuario=COORDINADOR, fecha=t(25)
    )
    return ingresar_a_cola(orden, fecha=t(30))


def orden_rt_tomada() -> OrdenReparacion:
    """Hasta PROC-REP-174: Orden tomada y Detalle seleccionado."""
    orden, _ = validar_estacion_trabajo(
        orden_rt_en_cola(),
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )
    orden = tomar_orden(
        orden, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )
    orden = seleccionar_detalle(
        orden, detalle_id=DETALLE_ID, usuario=TECNICO, fecha=t(62)
    )
    orden, _ = validar_compatibilidad_detalle(
        orden,
        detalle_id=DETALLE_ID,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(63),
    )
    return orden


def orden_rt_con_ejecucion_completada(
    cantidad_utilizada: str = "1",
) -> OrdenReparacion:
    """Hasta PROC-REP-200: Ejecucion COMPLETADO y Detalle COMPLETO."""
    orden = reservar_insumos_e_iniciar_ejecucion(
        orden_rt_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )
    orden = ejecutar_detalle(
        orden, detalle_id=DETALLE_ID, usuario=TECNICO, fecha=t(70)
    )
    return registrar_ejecucion_completada(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        insumos_utilizados=[
            InsumoUtilizado(
                insumo_id="INS-001",
                cantidad=Decimal(cantidad_utilizada),
            )
        ],
        usuario=TECNICO,
        fecha=t(145),
        observaciones="Bateria reemplazada sin novedades.",
    )


def orden_rt_con_inventario_conciliado(
    cantidad_utilizada: str = "1",
) -> OrdenReparacion:
    """Hasta PROC-REP-210: reservas consumidas o liberadas."""
    orden = orden_rt_con_ejecucion_completada(cantidad_utilizada)
    return generar_movimientos_inventario(
        orden, ejecucion_id=orden.ejecuciones[0].id, fecha=t(146)
    )


def orden_rt_evaluada() -> OrdenReparacion:
    """Hasta PROC-REP-211: Orden COMPLETA y toma cerrada."""
    orden, _ = evaluar_situacion_orden(
        orden_rt_con_inventario_conciliado(), fecha=t(150)
    )
    return orden


def orden_rt_controlada() -> OrdenReparacion:
    """Hasta PROC-REP-245: control aprobado y puntaje acreditado."""
    orden = aprobar_control_tecnico(
        orden_rt_evaluada(),
        usuario=RECEPCION,
        fecha=t(160),
        observaciones="Equipo enciende y carga correctamente.",
    )
    return calcular_puntaje(orden, fecha=t(165))


def orden_rt_reparacion_lista() -> OrdenReparacion:
    """Hasta PROC-REP-240: REPARACION_LISTA."""
    return marcar_reparacion_lista(orden_rt_controlada(), fecha=t(170))


def orden_rt_informada() -> OrdenReparacion:
    """Hasta PROC-REP-290: el resultado ya se informo a Gestion RT.

    PROC-REP-290 es ACT-SYSTEM: no recibe Usuario.
    """
    return informar_resultado_rt(orden_rt_reparacion_lista(), fecha=t(175))


def orden_rt_devuelta() -> OrdenReparacion:
    """HP-REP-002 completo: hasta PROC-REP-270 -> EVT-REP-999."""
    return devolver_equipo_rt(
        orden_rt_informada(), usuario=ADMINISTRADOR, fecha=t(180)
    )
