"""Invariantes de la capa de services.

Comprueban que los services no mutan lo que reciben y que las reglas de
V1.3 que el MVP si modela se sostienen. Los caminos alternativos del
proceso no se implementan: aqui solo se verifica que el flujo falla de
forma explicita en vez de continuar en un estado invalido.
"""

from decimal import Decimal

import pytest

from app.domain.models import (
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    InsumoUtilizado,
    TipoMovimientoInsumo,
)
from app.services import (
    PrecondicionInvalidaError,
    RecursoNoDisponibleError,
    aprobar_control_tecnico,
    cantidad_pendiente,
    definir_prioridad,
    definir_reparacion_detail,
    ejecucion_activa,
    entregar_equipo,
    evaluar_situacion_orden,
    generar_movimientos_inventario,
    habilitar_orden,
    hay_reservas_activas,
    ingresar_a_cola,
    marcar_reparacion_lista,
    registrar_ejecucion_completada,
    registrar_pago,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
    toma_activa,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_estacion_trabajo,
    validar_factibilidad_detalles,
)
from tests.fixtures import flujo_mvp
from tests.fixtures.catalogos_mvp import (
    ADMINISTRADOR,
    COMPATIBILIDADES,
    COORDINADOR,
    ESTACION,
    ESTACION_OTRA,
    ESTACIONES,
    INSUMO_BATERIA,
    INSUMOS,
    INSUMOS_PREVISTOS,
    RECEPCION,
    TECNICO,
    TECNICO_DOS,
    TIPO_BATERIA,
    t,
)

DETALLE_ID = flujo_mvp.DETALLE_ID


# 1) Los services no mutan la Orden recibida.


def test_habilitar_orden_no_muta_la_orden_recibida():
    original = flujo_mvp.orden_con_factibilidad()
    copia_previa = original.model_dump(mode="json")

    nueva = habilitar_orden(original, fecha=t(20))

    assert nueva is not original
    assert nueva.estado_workflow is EstadoWorkflow.HABILITADA
    assert original.estado_workflow is EstadoWorkflow.REQUERIMIENTO
    assert original.model_dump(mode="json") == copia_previa


def test_definir_detalle_no_muta_la_orden_recibida():
    original = flujo_mvp.orden_creada()

    nueva = definir_reparacion_detail(
        original,
        detalle_id="DET-001",
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(5),
    )

    assert original.reparaciones_detail == []
    assert len(nueva.reparaciones_detail) == 1
    assert original.historial is not nueva.historial


def test_tomar_orden_no_muta_la_orden_recibida():
    original = flujo_mvp.orden_en_cola()

    nueva = tomar_orden(
        original, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )

    assert original.tomas == []
    assert len(nueva.tomas) == 1


def test_registrar_pago_no_muta_la_orden_recibida():
    original = flujo_mvp.orden_reparacion_lista()

    nueva = registrar_pago(
        original,
        monto=Decimal("80000"),
        metodo="EFECTIVO",
        usuario=ADMINISTRADOR,
        fecha=t(185),
    )

    assert original.resumen_pago.pagos == []
    assert original.saldo == Decimal("80000")
    assert nueva.saldo == Decimal("0")


def test_reservar_no_muta_la_orden_recibida():
    original = flujo_mvp.orden_tomada()

    nueva = reservar_insumos_e_iniciar_ejecucion(
        original,
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )

    assert original.movimientos_insumo == []
    assert original.ejecuciones == []
    assert original.reparaciones_detail[0].estado is (
        EstadoReparacionDetail.DEFINIDO
    )
    assert len(nueva.movimientos_insumo) == 1
    assert len(nueva.ejecuciones) == 1


def test_una_cadena_de_services_deja_intactos_los_estados_previos():
    en_cola = flujo_mvp.orden_en_cola()
    tomada = tomar_orden(
        en_cola, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )
    seleccionada = seleccionar_detalle(
        tomada, detalle_id=DETALLE_ID, usuario=TECNICO, fecha=t(62)
    )

    assert en_cola.tomas == []
    assert len(tomada.tomas) == 1
    assert len(tomada.historial) < len(seleccionada.historial)


# 2) No puede haber dos Tomas activas (BR-REP-018).


def test_no_puede_haber_dos_tomas_activas():
    tomada = flujo_mvp.orden_tomada()

    with pytest.raises(PrecondicionInvalidaError):
        tomar_orden(
            tomada,
            usuario=TECNICO_DOS,
            estacion_id=ESTACION.id,
            fecha=t(64),
        )


def test_la_validacion_de_estacion_rechaza_una_orden_ya_tomada():
    tomada = flujo_mvp.orden_tomada()

    _, valida = validar_estacion_trabajo(
        tomada,
        usuario=TECNICO_DOS,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(64),
    )

    assert valida is False


# 3) No puede haber dos Ejecuciones activas (BR-REP-007).


def test_no_puede_haber_dos_ejecuciones_activas():
    orden = flujo_mvp.orden_con_ejecucion_iniciada()

    with pytest.raises(PrecondicionInvalidaError):
        reservar_insumos_e_iniciar_ejecucion(
            orden,
            detalle_id=DETALLE_ID,
            usuario=TECNICO,
            insumos=INSUMOS,
            insumos_previstos=INSUMOS_PREVISTOS,
            fecha=t(80),
        )


# 4) Una estacion incompatible no supera la validacion (BR-REP-011).


def test_estacion_incompatible_no_supera_la_validacion_agregada():
    en_cola = flujo_mvp.orden_en_cola()

    _, valida = validar_estacion_trabajo(
        en_cola,
        usuario=TECNICO,
        estacion_id=ESTACION_OTRA.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )

    assert valida is False


def test_estacion_incompatible_con_el_detalle_seleccionado():
    en_cola = flujo_mvp.orden_en_cola()
    tomada = tomar_orden(
        en_cola,
        usuario=TECNICO,
        estacion_id=ESTACION_OTRA.id,
        fecha=t(60),
    )

    _, compatible = validar_compatibilidad_detalle(
        tomada,
        detalle_id=DETALLE_ID,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(63),
    )

    assert compatible is False


def test_usuario_sin_rol_tecnico_no_supera_la_validacion():
    en_cola = flujo_mvp.orden_en_cola()

    _, valida = validar_estacion_trabajo(
        en_cola,
        usuario=RECEPCION,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )

    assert valida is False


# 5) Reserva insuficiente: falla sin movimientos parciales.


def test_reserva_insuficiente_no_deja_movimientos_parciales():
    tomada = flujo_mvp.orden_tomada()
    sin_stock = INSUMO_BATERIA.model_copy(
        update={"stock_fisico": Decimal("0")}
    )

    with pytest.raises(RecursoNoDisponibleError):
        reservar_insumos_e_iniciar_ejecucion(
            tomada,
            detalle_id=DETALLE_ID,
            usuario=TECNICO,
            insumos=[sin_stock],
            insumos_previstos=INSUMOS_PREVISTOS,
            fecha=t(65),
        )

    assert tomada.movimientos_insumo == []
    assert tomada.ejecuciones == []
    assert tomada.estado_workflow is EstadoWorkflow.EN_COLA


# 6) PROC-REP-185 crea reserva + ejecucion.


def test_reservar_crea_reserva_y_ejecucion():
    orden = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )

    assert len(orden.movimientos_insumo) == 1
    reserva = orden.movimientos_insumo[0]
    assert reserva.tipo is TipoMovimientoInsumo.RESERVA
    assert reserva.cantidad == Decimal("1")
    assert reserva.usuario_id is None
    assert reserva.reparacion_detail_id == DETALLE_ID

    assert len(orden.ejecuciones) == 1
    ejecucion = orden.ejecuciones[0]
    assert ejecucion.estado is EstadoEjecucion.EN_PROGRESO
    assert ejecucion.toma_orden_id == orden.tomas[0].id
    assert ejecucion.usuario_id == TECNICO.id

    assert orden.reparaciones_detail[0].estado is (
        EstadoReparacionDetail.EN_PROGRESO
    )
    assert orden.estado_workflow is EstadoWorkflow.EN_REPARACION


# 7) PROC-REP-200 registra los insumos reales.


def test_registrar_ejecucion_guarda_los_insumos_reales():
    orden = flujo_mvp.orden_con_ejecucion_completada()
    ejecucion = orden.ejecuciones[0]

    assert ejecucion.estado is EstadoEjecucion.COMPLETADO
    assert ejecucion.fin == t(145)
    assert [
        (u.insumo_id, u.cantidad) for u in ejecucion.insumos_utilizados
    ] == [("INS-001", Decimal("1"))]
    assert orden.reparaciones_detail[0].estado is (
        EstadoReparacionDetail.COMPLETO
    )


# 8) PROC-REP-210 consume la reserva.


def test_generar_movimientos_consume_la_reserva():
    orden = flujo_mvp.orden_con_inventario_conciliado()

    reserva, consumo = orden.movimientos_insumo

    assert reserva.tipo is TipoMovimientoInsumo.RESERVA
    assert consumo.tipo is TipoMovimientoInsumo.CONSUMO
    assert consumo.cantidad == Decimal("1")
    assert consumo.movimiento_origen_id == reserva.id
    assert consumo.ejecucion_id == orden.ejecuciones[0].id
    assert consumo.usuario_id is None
    # La reserva original no se modifica.
    assert reserva.cantidad == Decimal("1")
    pendiente = cantidad_pendiente(reserva, orden.movimientos_insumo)
    assert pendiente == Decimal("0")
    assert hay_reservas_activas(orden.movimientos_insumo) is False


# 9) Consumo menor a la reserva: liberacion por la diferencia.


def test_consumo_parcial_genera_liberacion_por_la_diferencia():
    orden = flujo_mvp.orden_con_ejecucion_iniciada()
    # La reserva es de 1; el tecnico declara haber usado 0.4.
    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("0.4"))
        ],
        usuario=TECNICO,
        fecha=t(145),
    )
    orden = generar_movimientos_inventario(
        orden, ejecucion_id=orden.ejecuciones[0].id, fecha=t(146)
    )

    tipos = [movimiento.tipo for movimiento in orden.movimientos_insumo]
    assert tipos == [
        TipoMovimientoInsumo.RESERVA,
        TipoMovimientoInsumo.CONSUMO,
        TipoMovimientoInsumo.LIBERACION_RESERVA,
    ]

    reserva, consumo, liberacion = orden.movimientos_insumo
    assert consumo.cantidad == Decimal("0.4")
    assert liberacion.cantidad == Decimal("0.6")
    assert consumo.movimiento_origen_id == reserva.id
    assert liberacion.movimiento_origen_id == reserva.id
    assert hay_reservas_activas(orden.movimientos_insumo) is False


# 10) Consumo mayor a la reserva: falla.


def test_consumo_mayor_a_la_reserva_falla():
    orden = flujo_mvp.orden_con_ejecucion_completada(cantidad_utilizada="2")

    with pytest.raises(PrecondicionInvalidaError):
        generar_movimientos_inventario(
            orden, ejecucion_id=orden.ejecuciones[0].id, fecha=t(146)
        )


# 11) PROC-REP-211 cierra la toma si la Orden quedo completa (BR-REP-018).


def test_evaluar_orden_cierra_la_toma_activa():
    previa = flujo_mvp.orden_con_inventario_conciliado()
    assert toma_activa(previa) is not None

    orden, _ = evaluar_situacion_orden(previa, fecha=t(150))

    assert toma_activa(orden) is None
    assert orden.tomas[0].estado is EstadoTomaOrden.CERRADA
    assert orden.tomas[0].fin == t(150)
    # El historial de la participacion se conserva.
    assert len(orden.tomas) == 1
    assert orden.tomas[0].usuario_id == TECNICO.id
    # La Orden todavia no es REPARACION_LISTA: eso ocurre en 240.
    assert orden.estado_workflow is EstadoWorkflow.EN_REPARACION


# 12) Control tecnico con Ejecucion activa: falla.


def test_control_tecnico_falla_con_ejecucion_activa():
    orden = flujo_mvp.orden_con_ejecucion_iniciada()
    assert ejecucion_activa(orden) is not None

    with pytest.raises(PrecondicionInvalidaError):
        aprobar_control_tecnico(orden, usuario=RECEPCION, fecha=t(160))


# 13) REPARACION_LISTA sin control aprobado: falla.


def test_no_se_marca_reparacion_lista_sin_control_aprobado():
    orden = flujo_mvp.orden_evaluada()
    assert orden.reparaciones_detail[0].control_estado.value == "PENDIENTE"

    with pytest.raises(PrecondicionInvalidaError):
        marcar_reparacion_lista(orden, fecha=t(170))


# 14) Registrar Pago no toca current_process.


def test_registrar_pago_no_cambia_el_nodo_actual():
    previa = flujo_mvp.orden_reparacion_lista()

    orden = registrar_pago(
        previa,
        monto=Decimal("30000"),
        metodo="TRANSFERENCIA",
        usuario=ADMINISTRADOR,
        fecha=t(185),
    )

    assert orden.current_process == previa.current_process
    assert orden.resumen_pago.pagado == Decimal("30000")
    assert orden.updated_at == t(185)

    # Deja traza transversal, sin avanzar el recorrido.
    assert len(orden.historial) == len(previa.historial) + 1
    ultima = orden.historial[-1]
    assert ultima.es_accion_funcional is True
    assert ultima.referencia_id == "ACC-REP-020"
    assert ultima.process_id is None


# 15) Entrega con saldo pendiente: falla.


def test_entrega_con_saldo_pendiente_falla():
    orden = flujo_mvp.orden_reparacion_lista()
    assert orden.saldo == Decimal("80000")

    with pytest.raises(PrecondicionInvalidaError):
        entregar_equipo(orden, usuario=ADMINISTRADOR, fecha=t(195))


# 16) Entrega con reservas activas: falla.


def test_entrega_con_reserva_activa_falla():
    orden = flujo_mvp.orden_documentada()

    # Se reinyecta la reserva original sin su consumo: queda pendiente.
    reserva = next(
        movimiento
        for movimiento in orden.movimientos_insumo
        if movimiento.tipo is TipoMovimientoInsumo.RESERVA
    )
    orden = orden.model_copy(deep=True)
    orden.movimientos_insumo = [reserva]
    assert hay_reservas_activas(orden.movimientos_insumo) is True

    with pytest.raises(PrecondicionInvalidaError):
        entregar_equipo(orden, usuario=ADMINISTRADOR, fecha=t(195))


# Precondiciones adicionales del recorrido.


def test_no_se_habilita_una_orden_sin_detalles():
    with pytest.raises(PrecondicionInvalidaError):
        habilitar_orden(flujo_mvp.orden_creada(), fecha=t(20))


def test_la_prioridad_no_puede_ser_negativa():
    orden = flujo_mvp.orden_habilitada()

    with pytest.raises(PrecondicionInvalidaError):
        definir_prioridad(
            orden, prioridad=-1, usuario=COORDINADOR, fecha=t(25)
        )


def test_no_se_toma_una_orden_que_no_esta_en_cola():
    with pytest.raises(PrecondicionInvalidaError):
        tomar_orden(
            flujo_mvp.orden_con_detalle(),
            usuario=TECNICO,
            estacion_id=ESTACION.id,
            fecha=t(60),
        )


def test_no_se_ingresa_dos_veces_a_la_cola():
    orden = flujo_mvp.orden_en_cola()

    with pytest.raises(PrecondicionInvalidaError):
        ingresar_a_cola(orden, fecha=t(31))


def test_no_se_selecciona_un_detalle_ya_en_progreso():
    orden = flujo_mvp.orden_con_ejecucion_iniciada()

    with pytest.raises(PrecondicionInvalidaError):
        seleccionar_detalle(
            orden, detalle_id=DETALLE_ID, usuario=TECNICO, fecha=t(80)
        )


# Gate de PROC-REP-140: solo se habilita tras 080 -> 090 "Si".


def test_habilitar_no_permite_saltear_la_factibilidad_desde_070():
    orden = flujo_mvp.orden_con_detalle()
    assert orden.current_process == "PROC-REP-060"
    sin_comprobante = flujo_mvp.orden_creada()
    directo = definir_reparacion_detail(
        sin_comprobante,
        detalle_id="DET-001",
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(5),
    )
    assert directo.current_process == "PROC-REP-070"

    for candidata in (directo, orden):
        with pytest.raises(PrecondicionInvalidaError, match="factibilidad"):
            habilitar_orden(candidata, fecha=t(20))
        assert "PROC-REP-140" not in [
            p.referencia_id for p in candidata.historial
        ]


def test_habilitar_funciona_tras_090_si():
    orden = flujo_mvp.orden_con_factibilidad()
    assert orden.current_process == "PROC-REP-090"
    assert orden.historial[-1].observacion == "Si"

    habilitada = habilitar_orden(orden, fecha=t(20))

    assert habilitada.estado_workflow is EstadoWorkflow.HABILITADA
    assert habilitada.historial[-1].referencia_id == "PROC-REP-140"


def test_habilitar_rechaza_090_con_faltantes():
    sin_stock = [
        INSUMO_BATERIA.model_copy(update={"stock_fisico": Decimal("0")})
    ]
    orden, factible = validar_factibilidad_detalles(
        flujo_mvp.orden_con_detalle(),
        insumos=sin_stock,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(15),
    )
    assert factible is False
    assert orden.current_process == "PROC-REP-090"
    assert orden.historial[-1].observacion.startswith("Faltantes")

    with pytest.raises(PrecondicionInvalidaError, match="no fue aprobada"):
        habilitar_orden(orden, fecha=t(20))
    assert "PROC-REP-140" not in [p.referencia_id for p in orden.historial]
