"""Atajos para llevar una Orden hasta un punto concreto de HP-REP-001.

Sirven a los tests de invariantes, que necesitan partir de un estado
intermedio sin repetir el recorrido completo. El recorrido explicito,
paso a paso, vive en ``tests/test_hp_rep_001_services.py``.

Todo se construye componiendo los mismos services que usara la API: no
hay ningun atajo que fabrique estado a mano.
"""

from decimal import Decimal

from app.domain.models import InsumoUtilizado, OrdenReparacion
from app.services import (
    aprobar_control_tecnico,
    calcular_puntaje,
    crear_orden_cliente_externo,
    definir_prioridad,
    definir_reparacion_detail,
    ejecutar_detalle,
    entregar_equipo,
    evaluar_situacion_orden,
    generar_comprobante_final,
    generar_comprobante_recepcion,
    generar_movimientos_inventario,
    habilitar_orden,
    ingresar_a_cola,
    marcar_reparacion_lista,
    notificar_cliente,
    registrar_ejecucion_completada,
    registrar_pago,
    registrar_saldo_pendiente,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_condicion_entrega,
    validar_estacion_trabajo,
    validar_factibilidad_detalles,
)

from .catalogos_mvp import (
    ADMINISTRADOR,
    CLIENTE,
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


def orden_creada() -> OrdenReparacion:
    """Hasta PROC-REP-040: Orden en REQUERIMIENTO, sin Detalles."""
    return crear_orden_cliente_externo(
        orden_id="OR-001",
        cliente=CLIENTE,
        equipo=EQUIPO,
        usuario=RECEPCION,
        fecha=t(0),
    )


def orden_con_detalle() -> OrdenReparacion:
    """Hasta PROC-REP-060: un Detalle DEFINIDO y comprobante emitido."""
    orden = definir_reparacion_detail(
        orden_creada(),
        detalle_id=DETALLE_ID,
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(5),
    )
    return generar_comprobante_recepcion(orden, fecha=t(10))


def orden_con_factibilidad() -> OrdenReparacion:
    """Hasta PROC-REP-090 "Si": factible, todavia sin habilitar."""
    orden, factible = validar_factibilidad_detalles(
        orden_con_detalle(),
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(15),
    )
    assert factible
    return orden


def orden_habilitada() -> OrdenReparacion:
    """Hasta PROC-REP-140: HABILITADA, todavia sin cola."""
    return habilitar_orden(orden_con_factibilidad(), fecha=t(20))


def orden_en_cola() -> OrdenReparacion:
    """Hasta PROC-REP-170: Orden EN_COLA, lista para tomarse."""
    orden = orden_habilitada()
    orden = definir_prioridad(
        orden, prioridad=1, usuario=COORDINADOR, fecha=t(25)
    )
    return ingresar_a_cola(orden, fecha=t(30))


def orden_tomada() -> OrdenReparacion:
    """Hasta PROC-REP-174: Orden tomada y Detalle seleccionado."""
    orden, _ = validar_estacion_trabajo(
        orden_en_cola(),
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


def orden_con_ejecucion_iniciada() -> OrdenReparacion:
    """Hasta PROC-REP-190: reserva hecha y Ejecucion en curso."""
    orden = reservar_insumos_e_iniciar_ejecucion(
        orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )
    return ejecutar_detalle(
        orden, detalle_id=DETALLE_ID, usuario=TECNICO, fecha=t(70)
    )


def orden_con_ejecucion_completada(
    cantidad_utilizada: str = "1",
) -> OrdenReparacion:
    """Hasta PROC-REP-200: Ejecucion COMPLETADO y Detalle COMPLETO."""
    orden = orden_con_ejecucion_iniciada()
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


def orden_con_inventario_conciliado(
    cantidad_utilizada: str = "1",
) -> OrdenReparacion:
    """Hasta PROC-REP-210: reservas consumidas o liberadas."""
    orden = orden_con_ejecucion_completada(cantidad_utilizada)
    return generar_movimientos_inventario(
        orden, ejecucion_id=orden.ejecuciones[0].id, fecha=t(146)
    )


def orden_evaluada() -> OrdenReparacion:
    """Hasta PROC-REP-211: Orden COMPLETA y toma cerrada."""
    orden, _ = evaluar_situacion_orden(
        orden_con_inventario_conciliado(), fecha=t(150)
    )
    return orden


def orden_controlada() -> OrdenReparacion:
    """Hasta PROC-REP-245: control aprobado y puntaje acreditado."""
    orden = aprobar_control_tecnico(
        orden_evaluada(),
        usuario=RECEPCION,
        fecha=t(160),
        observaciones="Equipo enciende y carga correctamente.",
    )
    return calcular_puntaje(orden, fecha=t(165))


def orden_reparacion_lista() -> OrdenReparacion:
    """Hasta PROC-REP-260: REPARACION_LISTA y cliente notificado."""
    orden = marcar_reparacion_lista(orden_controlada(), fecha=t(170))
    return notificar_cliente(orden, usuario=RECEPCION, fecha=t(175))


def orden_pagada() -> OrdenReparacion:
    """Hasta PROC-REP-265 aprobado: saldo 0, entrega habilitada."""
    orden, _ = validar_condicion_entrega(
        orden_reparacion_lista(), fecha=t(180)
    )
    orden = registrar_saldo_pendiente(orden, fecha=t(181))
    orden = registrar_pago(
        orden,
        monto=Decimal("80000"),
        metodo="EFECTIVO",
        usuario=ADMINISTRADOR,
        fecha=t(185),
    )
    orden, _ = validar_condicion_entrega(orden, fecha=t(186))
    return orden


def orden_documentada() -> OrdenReparacion:
    """Hasta PROC-REP-280: comprobante final y garantia emitidos."""
    return generar_comprobante_final(orden_pagada(), fecha=t(190))


def orden_entregada() -> OrdenReparacion:
    """HP-REP-001 completo: hasta PROC-REP-270 -> EVT-REP-999."""
    return entregar_equipo(
        orden_documentada(), usuario=ADMINISTRADOR, fecha=t(195)
    )
