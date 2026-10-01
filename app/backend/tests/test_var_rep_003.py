"""VAR-REP-003 (ejecucion interrumpida) componiendo services.

PROC-REP-190 -> 200 "Interrumpido" -> 210 -> 211: la Ejecucion queda
INTERRUMPIDO (terminal), el Detalle vuelve a DEFINIDO, lo utilizado se
consume y lo reservado que no se uso se libera, la toma sigue activa y
continuar es una Ejecucion NUEVA. La mecanica es transversal a los
Origenes (HP-REP-001/002/003).
"""

import json
from decimal import Decimal

import pytest

from app.application import acciones_disponibles
from app.domain.models import (
    CondicionReparacionDetail,
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    InsumoUtilizado,
    OrdenReparacion,
    TipoMovimientoInsumo,
    TipoReparacionInsumos,
)
from app.services import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    ResultadoEvaluacionOrden,
    ejecucion_activa,
    ejecutar_detalle,
    evaluar_situacion_orden,
    generar_movimientos_inventario,
    hay_reservas_activas,
    registrar_ejecucion_completada,
    registrar_ejecucion_interrumpida,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
)
from app.storage import JsonOrdenReparacionRepository
from tests.fixtures import flujo_mvp
from tests.fixtures import flujo_mvp_rt as flujo_rt
from tests.fixtures.catalogos_mvp import (
    INSUMO_BATERIA,
    TECNICO,
    TECNICO_DOS,
    t,
)

DETALLE = flujo_mvp.DETALLE_ID

# Reserva de 2 unidades (el fixture estandar reserva 1) y stock holgado.
PREVISTOS_DOS = [
    TipoReparacionInsumos(
        tipo_reparacion_id="TREP-001",
        insumo_id="INS-001",
        cantidad=Decimal("2"),
    )
]
INSUMOS_HOLGADOS = [
    INSUMO_BATERIA.model_copy(update={"stock_fisico": Decimal("10")})
]


def _utilizado(cantidad: str) -> list[InsumoUtilizado]:
    """Lo realmente usado; "0" es no haber usado nada (lista vacia)."""
    if Decimal(cantidad) == 0:
        return []
    return [InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal(cantidad))]


def _iniciada(tomada, previstos=None) -> OrdenReparacion:
    """Desde una Orden tomada: 185 + 190, con una Ejecucion EN_PROGRESO."""
    orden = reservar_insumos_e_iniciar_ejecucion(
        tomada,
        detalle_id=DETALLE,
        usuario=TECNICO,
        insumos=INSUMOS_HOLGADOS,
        insumos_previstos=previstos or flujo_mvp.INSUMOS_PREVISTOS,
        fecha=t(65),
    )
    return ejecutar_detalle(
        orden, detalle_id=DETALLE, usuario=TECNICO, fecha=t(70)
    )


def _interrumpida(
    tomada=None, utilizado="0", previstos=None
) -> OrdenReparacion:
    orden = _iniciada(tomada or flujo_mvp.orden_tomada(), previstos)
    return registrar_ejecucion_interrumpida(
        orden,
        ejecucion_id=orden.ejecuciones[-1].id,
        insumos_utilizados=_utilizado(utilizado),
        usuario=TECNICO,
        fecha=t(100),
        observaciones="Falta una herramienta.",
    )


def _movimientos(orden, ejecucion_id):
    return [
        (m.tipo, m.cantidad)
        for m in orden.movimientos_insumo
        if m.ejecucion_id == ejecucion_id
        and m.tipo is not TipoMovimientoInsumo.RESERVA
    ]


# --- Interrupcion basica ----


def test_interrumpir_deja_la_ejecucion_terminal_y_el_detalle_definido():
    orden = _interrumpida(utilizado="1")

    (ejecucion,) = orden.ejecuciones
    assert ejecucion.estado is EstadoEjecucion.INTERRUMPIDO
    assert ejecucion.fin == t(100)
    assert ejecucion.observaciones == "Falta una herramienta."
    assert [
        (u.insumo_id, u.cantidad) for u in ejecucion.insumos_utilizados
    ] == [("INS-001", Decimal("1"))]
    detalle = orden.reparaciones_detail[0]
    assert detalle.estado is EstadoReparacionDetail.DEFINIDO
    assert detalle.condicion is CondicionReparacionDetail.SIN_BLOQUEO
    paso = orden.historial[-1]
    assert (paso.referencia_id, paso.accion, paso.observacion) == (
        "PROC-REP-200",
        "REGISTRAR_EJECUCION_REAL",
        "Interrumpido",
    )
    assert paso.ejecucion_id == ejecucion.id


def test_interrumpir_no_cierra_la_toma():
    orden = _interrumpida()

    (toma,) = orden.tomas
    assert toma.estado is EstadoTomaOrden.ACTIVA
    assert ejecucion_activa(orden) is None


def test_completar_sigue_dando_completado_y_detalle_completo():
    orden = _iniciada(flujo_mvp.orden_tomada())
    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        insumos_utilizados=_utilizado("1"),
        usuario=TECNICO,
        fecha=t(100),
    )

    assert orden.ejecuciones[0].estado is EstadoEjecucion.COMPLETADO
    assert (
        orden.reparaciones_detail[0].estado is EstadoReparacionDetail.COMPLETO
    )
    assert orden.historial[-1].observacion == "Completado"


# --- Guards ----


def test_solo_el_tecnico_propietario_puede_interrumpir():
    orden = _iniciada(flujo_mvp.orden_tomada())

    with pytest.raises(PrecondicionInvalidaError):
        registrar_ejecucion_interrumpida(
            orden,
            ejecucion_id=orden.ejecuciones[0].id,
            insumos_utilizados=[],
            usuario=TECNICO_DOS,
            fecha=t(100),
        )
    with pytest.raises(PrecondicionInvalidaError):
        registrar_ejecucion_interrumpida(
            orden,
            ejecucion_id=orden.ejecuciones[0].id,
            insumos_utilizados=[],
            usuario=flujo_mvp.RECEPCION,
            fecha=t(100),
        )
    assert orden.ejecuciones[0].estado is EstadoEjecucion.EN_PROGRESO


@pytest.mark.parametrize("terminal", ["completar", "interrumpir"])
def test_una_ejecucion_terminal_no_puede_interrumpirse(terminal):
    orden = _iniciada(flujo_mvp.orden_tomada())
    ejecucion_id = orden.ejecuciones[0].id
    cierre = (
        registrar_ejecucion_completada
        if terminal == "completar"
        else registrar_ejecucion_interrumpida
    )
    orden = cierre(
        orden,
        ejecucion_id=ejecucion_id,
        insumos_utilizados=_utilizado("1"),
        usuario=TECNICO,
        fecha=t(100),
    )

    with pytest.raises(PrecondicionInvalidaError, match="ya esta"):
        registrar_ejecucion_interrumpida(
            orden,
            ejecucion_id=ejecucion_id,
            insumos_utilizados=[],
            usuario=TECNICO,
            fecha=t(110),
        )


def test_no_se_interrumpe_una_ejecucion_inexistente():
    with pytest.raises(EntidadNoEncontradaError):
        registrar_ejecucion_interrumpida(
            _iniciada(flujo_mvp.orden_tomada()),
            ejecucion_id="EJE-NO-EXISTE",
            insumos_utilizados=[],
            usuario=TECNICO,
            fecha=t(100),
        )


# --- Inventario (PROC-REP-210) ---


@pytest.mark.parametrize(
    ("utilizado", "esperado"),
    [
        ("0", [(TipoMovimientoInsumo.LIBERACION_RESERVA, Decimal("2"))]),
        (
            "1",
            [
                (TipoMovimientoInsumo.CONSUMO, Decimal("1")),
                (TipoMovimientoInsumo.LIBERACION_RESERVA, Decimal("1")),
            ],
        ),
        ("2", [(TipoMovimientoInsumo.CONSUMO, Decimal("2"))]),
    ],
    ids=["sin_consumo", "consumo_parcial", "consumo_total"],
)
def test_210_reconcilia_la_ejecucion_interrumpida(utilizado, esperado):
    orden = _interrumpida(utilizado=utilizado, previstos=PREVISTOS_DOS)
    ejecucion_id = orden.ejecuciones[0].id
    reserva = next(
        m
        for m in orden.movimientos_insumo
        if m.tipo is TipoMovimientoInsumo.RESERVA
    )
    assert reserva.cantidad == Decimal("2")

    orden = generar_movimientos_inventario(
        orden, ejecucion_id=ejecucion_id, fecha=t(101)
    )

    assert _movimientos(orden, ejecucion_id) == esperado
    assert not hay_reservas_activas(orden.movimientos_insumo)
    for movimiento in orden.movimientos_insumo:
        assert movimiento.reparacion_detail_id == DETALLE
        if movimiento.tipo is not TipoMovimientoInsumo.RESERVA:
            assert movimiento.ejecucion_id == ejecucion_id
    assert orden.historial[-1].referencia_id == "PROC-REP-210"


def test_210_rechaza_una_ejecucion_en_progreso():
    orden = _iniciada(flujo_mvp.orden_tomada())
    assert orden.ejecuciones[0].estado is EstadoEjecucion.EN_PROGRESO

    with pytest.raises(PrecondicionInvalidaError, match="terminada"):
        generar_movimientos_inventario(
            orden, ejecucion_id=orden.ejecuciones[0].id, fecha=t(101)
        )
    assert "PROC-REP-210" not in [p.referencia_id for p in orden.historial]


def test_210_acepta_completado_e_interrumpido():
    interrumpida = _interrumpida(utilizado="1")
    generar_movimientos_inventario(
        interrumpida, ejecucion_id=interrumpida.ejecuciones[0].id, fecha=t(101)
    )

    completada = _iniciada(flujo_mvp.orden_tomada())
    completada = registrar_ejecucion_completada(
        completada,
        ejecucion_id=completada.ejecuciones[0].id,
        insumos_utilizados=_utilizado("1"),
        usuario=TECNICO,
        fecha=t(100),
    )
    generar_movimientos_inventario(
        completada, ejecucion_id=completada.ejecuciones[0].id, fecha=t(101)
    )


# --- PROC-REP-211 y acciones -----------------------------------------------


def test_211_sale_del_resolver_con_el_detalle_trabajable():
    orden = _interrumpida(utilizado="1")
    orden = generar_movimientos_inventario(
        orden, ejecucion_id=orden.ejecuciones[0].id, fecha=t(101)
    )

    orden, resultado = evaluar_situacion_orden(orden, fecha=t(102))

    assert resultado is ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE
    assert orden.historial[-1].observacion == "ABIERTA_TRABAJABLE"
    assert orden.tomas[0].estado is EstadoTomaOrden.ACTIVA


def test_acciones_con_ejecucion_activa_y_luego_de_interrumpir():
    activa = _iniciada(flujo_mvp.orden_tomada())
    codigos = [a.codigo for a in acciones_disponibles(activa)]
    assert "COMPLETAR_EJECUCION" in codigos
    assert "INTERRUMPIR_EJECUCION" in codigos
    interrumpir = next(
        a
        for a in acciones_disponibles(activa)
        if a.codigo == "INTERRUMPIR_EJECUCION"
    )
    assert interrumpir.roles == (TECNICO.rol,)
    assert interrumpir.detalle_id == DETALLE
    assert interrumpir.ejecucion_id == activa.ejecuciones[0].id

    orden = _interrumpida(utilizado="1")
    orden = generar_movimientos_inventario(
        orden, ejecucion_id=orden.ejecuciones[0].id, fecha=t(101)
    )
    orden, _ = evaluar_situacion_orden(orden, fecha=t(102))
    assert [a.codigo for a in acciones_disponibles(orden)] == [
        "INICIAR_DETALLE",
        "LIBERAR_ORDEN",
        "REGISTRAR_PAGO",
    ]


# --- Continuar: Ejecucion nueva ----


def test_el_mismo_tecnico_continua_con_una_ejecucion_nueva():
    primera = _interrumpida(utilizado="1")
    primera = generar_movimientos_inventario(
        primera, ejecucion_id=primera.ejecuciones[0].id, fecha=t(101)
    )
    primera, _ = evaluar_situacion_orden(primera, fecha=t(102))
    foto_primera = primera.ejecuciones[0].model_dump()

    orden = seleccionar_detalle(
        primera, detalle_id=DETALLE, usuario=TECNICO, fecha=t(110)
    )
    orden = reservar_insumos_e_iniciar_ejecucion(
        orden,
        detalle_id=DETALLE,
        usuario=TECNICO,
        insumos=INSUMOS_HOLGADOS,
        insumos_previstos=flujo_mvp.INSUMOS_PREVISTOS,
        fecha=t(111),
    )

    interrumpida, nueva = orden.ejecuciones
    assert interrumpida.model_dump() == foto_primera
    assert interrumpida.estado is EstadoEjecucion.INTERRUMPIDO
    assert nueva.id != interrumpida.id
    assert nueva.estado is EstadoEjecucion.EN_PROGRESO
    assert nueva.toma_orden_id == interrumpida.toma_orden_id  # misma toma
    assert nueva.inicio == t(111)
    assert (
        orden.reparaciones_detail[0].estado
        is EstadoReparacionDetail.EN_PROGRESO
    )


# --- Transversal a los Origenes ----


@pytest.mark.parametrize(
    "tomada",
    [flujo_mvp.orden_tomada, flujo_rt.orden_rt_tomada],
    ids=["cliente_externo", "rt_interno"],
)
def test_la_interrupcion_no_depende_del_origen(tomada):
    orden = _interrumpida(tomada=tomada(), utilizado="1")
    orden = generar_movimientos_inventario(
        orden, ejecucion_id=orden.ejecuciones[0].id, fecha=t(101)
    )
    orden, resultado = evaluar_situacion_orden(orden, fecha=t(102))

    assert orden.ejecuciones[0].estado is EstadoEjecucion.INTERRUMPIDO
    assert resultado is ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE


# --- Persistencia ----


def test_una_ejecucion_interrumpida_hace_round_trip_json(tmp_path):
    repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    orden = _interrumpida(utilizado="1")
    repo.guardar(orden)

    recuperada = repo.obtener(orden.id)

    (ejecucion,) = recuperada.ejecuciones
    assert ejecucion.estado is EstadoEjecucion.INTERRUMPIDO
    assert ejecucion.fin == t(100)
    assert ejecucion.observaciones == "Falta una herramienta."
    assert ejecucion.insumos_utilizados[0].cantidad == Decimal("1")
    crudo = json.loads(
        (repo.directorio / f"{orden.id}.json").read_text("utf-8")
    )
    assert crudo["ejecuciones"][0]["estado"] == "INTERRUMPIDO"
    assert recuperada.model_dump() == orden.model_dump()


def test_json_previo_con_ejecuciones_en_progreso_y_completadas_sigue_cargando(
    tmp_path,
):
    repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    repo.guardar(flujo_mvp.orden_con_ejecucion_iniciada())
    assert repo.obtener("OR-001").ejecuciones[0].estado is (
        EstadoEjecucion.EN_PROGRESO
    )

    repo.guardar(flujo_mvp.orden_entregada())
    assert repo.obtener("OR-001").ejecuciones[0].estado is (
        EstadoEjecucion.COMPLETADO
    )
