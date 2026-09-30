"""HP-REP-002 ejecutado de punta a punta componiendo services.

Origen RT_INTERNO: sin Cliente, sin comprobante de recepcion, y un
cierre propio -informar a Gestion RT y devolver el equipo- en vez de
notificar/cobrar/entregar a un cliente
(``business/scenarios/repair-management-scenarios-v1.3.yaml``, HP-REP-002).

Arranca desde cero: no usa ningun atajo que fabrique estado a mano, solo
compone los mismos services que despues usa la API.
"""

from decimal import Decimal

import pytest

from app.application import acciones_disponibles
from app.domain.models import (
    EstadoControl,
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    OrigenOrden,
    TipoMovimientoInsumo,
)
from app.domain.politicas import CondicionComercial, politica_de
from app.services import (
    PrecondicionInvalidaError,
    ResultadoEvaluacionOrden,
    devolver_equipo_rt,
    registrar_pago,
    resolver_situacion_orden,
)
from tests.fixtures.catalogos_mvp import (
    ADMINISTRADOR,
    RECEPCION,
    TECNICO,
    t,
)
from tests.fixtures.flujo_mvp import orden_reparacion_lista as orden_hp1_lista
from tests.fixtures.flujo_mvp_rt import (
    DETALLE_ID,
    REFERENCIA_RT,
    orden_rt_controlada,
    orden_rt_creada,
    orden_rt_devuelta,
    orden_rt_en_cola,
    orden_rt_evaluada,
    orden_rt_informada,
    orden_rt_reparacion_lista,
)


def test_orden_rt_nace_sin_cliente_con_referencia_de_contexto():
    orden = orden_rt_creada()

    assert orden.origen is OrigenOrden.RT_INTERNO
    assert orden.cliente is None
    assert orden.referencia_rt == REFERENCIA_RT
    assert orden.estado_workflow is EstadoWorkflow.REQUERIMIENTO
    assert orden.current_process == "PROC-REP-040"


def test_ingreso_rt_no_pasa_por_registro_de_cliente_ni_comprobante():
    """Diverge de CLIENTE_EXTERNO desde el ingreso (skipped_nodes)."""
    orden = orden_rt_en_cola()

    referencias = [paso.referencia_id for paso in orden.historial]

    assert "PROC-REP-020" in referencias
    assert "PROC-REP-030" not in referencias
    assert "PROC-REP-060" not in referencias
    assert orden.documentos.comprobante_recepcion.generado is False

    # PROC-REP-050 SI se registra, pero resuelve "No" (BR-REP-016).
    paso_050 = next(
        p for p in orden.historial if p.referencia_id == "PROC-REP-050"
    )
    assert paso_050.observacion == "No"


def test_evaluar_situacion_llega_a_completa_igual_que_hp1():
    orden = orden_rt_evaluada()

    resultado = resolver_situacion_orden(orden.reparaciones_detail)
    assert resultado is ResultadoEvaluacionOrden.COMPLETA

    detalle = orden.reparaciones_detail[0]
    assert detalle.estado is EstadoReparacionDetail.COMPLETO

    toma = orden.tomas[0]
    assert toma.estado is EstadoTomaOrden.CERRADA


def test_control_tecnico_y_puntaje_son_los_mismos_mecanismos_que_hp1():
    orden = orden_rt_controlada()

    detalle = orden.reparaciones_detail[0]
    assert detalle.control_estado is EstadoControl.APROBADO
    assert orden.puntaje_total == detalle.puntaje


def test_reparacion_lista_no_notifica_ni_pasa_por_260():
    orden = orden_rt_reparacion_lista()

    assert orden.estado_workflow is EstadoWorkflow.REPARACION_LISTA
    referencias = [paso.referencia_id for paso in orden.historial]
    assert "PROC-REP-260" not in referencias


def test_informar_rt_registra_250_no_y_290():
    orden = orden_rt_informada()

    referencias = [paso.referencia_id for paso in orden.historial]
    assert "PROC-REP-290" in referencias
    assert orden.current_process == "PROC-REP-290"

    paso_250 = next(
        p for p in orden.historial if p.referencia_id == "PROC-REP-250"
    )
    assert paso_250.observacion == "No"

    # No se recorrio el cierre comercial de cliente.
    assert "PROC-REP-265" not in referencias
    assert "PROC-REP-266" not in referencias
    assert "PROC-REP-280" not in referencias


def test_devolucion_rt_llega_a_evt_999_sin_marcar_entregada():
    """HP-REP-002: el estado terminal sigue pendiente de definicion (V1.3).

    ``current_process`` evidencia el fin del proceso; ``estado_workflow``
    NO pasa a ENTREGADA porque el negocio no lo definio (ver
    ``services.ordenes.devolver_equipo_rt``).
    """
    orden = orden_rt_devuelta()

    assert orden.current_process == "EVT-REP-999"
    assert orden.estado_workflow is EstadoWorkflow.REPARACION_LISTA

    referencias = [paso.referencia_id for paso in orden.historial]
    assert referencias.count("PROC-REP-270") == 1

    assert not any(
        toma.estado is EstadoTomaOrden.ACTIVA for toma in orden.tomas
    )
    assert not any(
        ejecucion.estado is EstadoEjecucion.EN_PROGRESO
        for ejecucion in orden.ejecuciones
    )


def test_detalle_conserva_snapshots_independientes_de_hp1():
    orden = orden_rt_devuelta()
    detalle = orden.reparaciones_detail[0]

    assert detalle.id == DETALLE_ID
    assert detalle.precio == Decimal("80000")
    assert detalle.puntaje == 10
    assert detalle.garantia_dias == 90


def test_movimientos_de_inventario_quedan_vinculados_al_detalle():
    orden = orden_rt_devuelta()

    assert orden.movimientos_insumo, "esperaba reserva y consumo"
    for movimiento in orden.movimientos_insumo:
        assert movimiento.reparacion_detail_id == DETALLE_ID
    tipos = {m.tipo for m in orden.movimientos_insumo}
    assert TipoMovimientoInsumo.CONSUMO in tipos


def test_no_se_genera_ningun_comprobante_para_rt_interno():
    orden = orden_rt_devuelta()

    assert orden.documentos.comprobante_recepcion.generado is False
    assert orden.documentos.comprobante_final.generado is False
    assert orden.documentos.garantia_reparacion.generado is False


# --- Negativos: lo que RT_INTERNO NO debe ofrecer -----------------------


def test_rt_interno_no_ofrece_registrar_pago_ni_notificar_ni_entregar():
    orden = orden_rt_reparacion_lista()

    codigos = {accion.codigo for accion in acciones_disponibles(orden)}

    assert "REGISTRAR_PAGO" not in codigos
    assert "NOTIFICAR" not in codigos
    assert "ENTREGAR" not in codigos
    assert "INFORMAR_RT" in codigos


def test_rt_interno_no_exige_saldo_cero_para_devolver():
    """El saldo nominal (precio snapshot) puede ser > 0: no bloquea nada."""
    orden = orden_rt_informada()

    assert orden.saldo > 0
    devuelta = orden_rt_devuelta()
    assert devuelta.current_process == "EVT-REP-999"


def test_devolver_rt_esta_disponible_recien_despues_de_informar():
    lista = orden_rt_reparacion_lista()
    codigos_antes = {a.codigo for a in acciones_disponibles(lista)}
    assert "DEVOLVER_RT" not in codigos_antes
    assert "INFORMAR_RT" in codigos_antes

    informada = orden_rt_informada()
    codigos_despues = {a.codigo for a in acciones_disponibles(informada)}
    assert "DEVOLVER_RT" in codigos_despues
    assert "INFORMAR_RT" not in codigos_despues


def test_orden_terminada_no_ofrece_ninguna_accion():
    orden = orden_rt_devuelta()
    assert acciones_disponibles(orden) == []


# --- Pago: BR-REP-016/017, no solo en la UI ------------------------------


def test_registrar_pago_rechaza_una_orden_rt_interno():
    """El backend lo rechaza aunque se invoque directo, no solo la UI."""
    orden = orden_rt_reparacion_lista()

    with pytest.raises(PrecondicionInvalidaError):
        registrar_pago(
            orden,
            monto=Decimal("1"),
            metodo="EFECTIVO",
            usuario=ADMINISTRADOR,
            fecha=t(999),
        )


def test_registrar_pago_sigue_funcionando_en_cliente_externo():
    """CLIENTE_EXTERNO (COBRABLE) no se ve afectado por el rechazo de RT."""
    orden = orden_hp1_lista()

    pagada = registrar_pago(
        orden,
        monto=Decimal("80000"),
        metodo="EFECTIVO",
        usuario=ADMINISTRADOR,
        fecha=t(999),
    )
    assert pagada.saldo == Decimal("0")


# --- PROC-REP-290: ACT-SYSTEM, no una accion humana ----------------------


def test_informar_rt_no_registra_ningun_actor_humano():
    orden = orden_rt_informada()

    paso_290 = next(
        p for p in orden.historial if p.referencia_id == "PROC-REP-290"
    )
    assert paso_290.usuario_id is None


def test_informar_rt_se_publica_como_accion_de_sistema_sin_actor():
    lista = orden_rt_reparacion_lista()
    accion = next(
        a for a in acciones_disponibles(lista) if a.codigo == "INFORMAR_RT"
    )
    assert accion.requiere_actor is False
    assert accion.roles == ()


def test_devolver_rt_no_puede_ejecutarse_antes_de_informar():
    """PROC-REP-270 (RT) exige haber pasado por PROC-REP-290 antes."""
    lista = orden_rt_reparacion_lista()

    with pytest.raises(PrecondicionInvalidaError):
        devolver_equipo_rt(lista, usuario=ADMINISTRADOR, fecha=t(999))


# --- PROC-REP-270: NO es ACT-SYSTEM, exige un actor humano real ----------


def test_devolver_rt_con_administrador_registra_su_usuario_id():
    orden = devolver_equipo_rt(
        orden_rt_informada(), usuario=ADMINISTRADOR, fecha=t(999)
    )

    paso_270 = next(
        p for p in orden.historial if p.referencia_id == "PROC-REP-270"
    )
    assert paso_270.usuario_id == ADMINISTRADOR.id


def test_devolver_rt_con_recepcion_registra_su_usuario_id():
    orden = devolver_equipo_rt(
        orden_rt_informada(), usuario=RECEPCION, fecha=t(999)
    )

    paso_270 = next(
        p for p in orden.historial if p.referencia_id == "PROC-REP-270"
    )
    assert paso_270.usuario_id == RECEPCION.id


def test_devolver_rt_rechaza_tecnico():
    with pytest.raises(PrecondicionInvalidaError):
        devolver_equipo_rt(
            orden_rt_informada(), usuario=TECNICO, fecha=t(999)
        )


# --- Representacion comercial: snapshot != deuda pendiente ---------------


def test_representacion_comercial_rt_no_es_deuda_pendiente():
    """El snapshot nominal no implica que se le cobre a nadie."""
    orden = orden_rt_reparacion_lista()
    detalle = orden.reparaciones_detail[0]

    politica = politica_de(orden.origen)
    assert politica.condicion_comercial == (
        CondicionComercial.NO_COBRABLE_AL_CLIENTE
    )

    # El precio snapshot se conserva -no se puso en 0- y el total/saldo
    # nominal lo reflejan; lo que cambia es la condicion comercial, que
    # es lo que la API/UI deben leer para no presentarlo como deuda.
    assert detalle.precio == Decimal("80000")
    assert orden.total == Decimal("80000")
    assert orden.saldo == Decimal("80000")

    # Y en la practica: no hay forma de cobrarlo (ver tests de arriba) ni
    # de que bloquee la devolucion (ver
    # test_rt_interno_no_exige_saldo_cero_para_devolver).
    codigos = {a.codigo for a in acciones_disponibles(orden)}
    assert "REGISTRAR_PAGO" not in codigos
