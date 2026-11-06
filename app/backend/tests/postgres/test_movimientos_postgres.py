"""Consumos, liberaciones, ingresos y ajustes en PostgreSQL (E5, slice A7).

Contra la base local descartable, con los comandos reales sobre
PostgreSQL (Ordenes, catalogos y stock en la base; el taller es el de
``test_reservas_postgres.py``). Semantica que se verifica:

- 210: completar consume la reserva; interrumpir sin usar la libera; un uso
  parcial consume y libera el resto. El libro mueve el stock y el saldo
  esperado por el service se verifica (DI-1).
- Sin doble consumo ni doble liberacion; un movimiento repetido o una
  operacion repetida no se aplican dos veces.
- Ingresos y ajustes: el motivo es el texto libre (DI-8); el ajuste
  negativo pide confirmacion; H-1: nunca queda el disponible negativo.
- Concurrencia: consumo contra reserva, consumo contra ingreso, reserva
  contra ajuste negativo y dos envios de la misma operacion.
- Todo o nada.

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (seccion 18).
"""

import threading
from datetime import datetime, timezone
from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

from app.application import (  # noqa: E402
    completar_ejecucion,
    interrumpir_ejecucion,
    movimientos_de_inventario,
    registrar_ajuste_stock,
    registrar_ingreso_stock,
)
from app.domain.models import (  # noqa: E402
    InsumoUtilizado,
    MovimientoInsumo,
    MovimientoStock,
    TipoMovimientoInsumo,
)
from app.repositories.exceptions import (  # noqa: E402
    PersistenciaError,
    RestriccionDeIntegridadError,
)
from app.services import (  # noqa: E402
    ConfirmacionRequeridaError,
    PrecondicionInvalidaError,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_reservas_postgres as reservas  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql, _version  # noqa: E402
from tests.postgres.test_reservas_postgres import (  # noqa: E402
    INSUMO,
    _fijar,
    _iniciar,
    _integridad,
    _reservo,
    _stock,
)

armar = reservas.armar
base = reservas.base
corpus = reservas.corpus
plantilla = reservas.plantilla
taller = reservas.taller

CONSUMO = TipoMovimientoInsumo.CONSUMO
LIBERACION = TipoMovimientoInsumo.LIBERACION_RESERVA


def _tipos(orden):
    return [m.tipo for m in orden.movimientos_insumo]


def _usado(cantidad="1"):
    return [InsumoUtilizado(insumo_id=INSUMO, cantidad=Decimal(cantidad))]


def _ejecucion(orden):
    return orden.ejecuciones[-1].id


def _completar(contexto, orden, tecnico, cantidad="1"):
    resultado, _ = completar_ejecucion(
        contexto,
        orden_id=orden.id,
        ejecucion_id=_ejecucion(orden),
        usuario_id=tecnico,
        insumos_utilizados=_usado(cantidad),
    )
    return resultado


def _reservada(contexto, tomadas, indice=0):
    orden_id, tecnico = tomadas[indice]
    return _iniciar(contexto, orden_id, tecnico), tecnico


def _ingreso(contexto, cantidad="3", **extra):
    return registrar_ingreso_stock(
        contexto,
        insumo_id=INSUMO,
        usuario_id=f.ADMINISTRADOR,
        cantidad=Decimal(cantidad),
        motivo=extra.pop("motivo", "Compra al proveedor."),
        **extra,
    )


def _ajuste(contexto, diferencia, confirmado=True, motivo="Conteo."):
    return registrar_ajuste_stock(
        contexto,
        insumo_id=INSUMO,
        usuario_id=f.ADMINISTRADOR,
        diferencia=Decimal(diferencia),
        motivo=motivo,
        confirmado=confirmado,
    )


def _libro(base):
    return _sql(
        base,
        "select tipo, cantidad from rma.movimiento_inventario "
        "where usuario_id is not null or orden_id is not null "
        "order by secuencia",
    )


def _en_paralelo(*funciones):
    barrera = threading.Barrier(len(funciones))
    resultados, errores = [None] * len(funciones), []

    def correr(indice, funcion):
        barrera.wait(10)
        try:
            resultados[indice] = funcion()
        except Exception as error:  # noqa: BLE001
            errores.append(error)

    hilos = [
        threading.Thread(target=correr, args=(i, fn))
        for i, fn in enumerate(funciones)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    return resultados, errores


# --- 210: consumo y liberacion ----------------------------------------------


def test_a7_completar_consume_la_reserva(taller, base):
    repo, _, contexto, tomadas = taller
    orden, tecnico = _reservada(contexto, tomadas)
    completada = _completar(contexto, orden, tecnico)
    assert _tipos(completada) == [TipoMovimientoInsumo.RESERVA, CONSUMO]
    consumo = completada.movimientos_insumo[-1]
    assert consumo.movimiento_origen_id == orden.movimientos_insumo[0].id
    assert repo.obtener(orden.id) == completada
    assert _stock(base) == (Decimal("4"), Decimal("0"))
    assert _integridad(base) == []


def test_a7_interrumpir_sin_usar_libera_la_reserva(taller, base):
    repo, _, contexto, tomadas = taller
    orden, tecnico = _reservada(contexto, tomadas)
    interrumpida, _ = interrumpir_ejecucion(
        contexto,
        orden_id=orden.id,
        ejecucion_id=_ejecucion(orden),
        usuario_id=tecnico,
        insumos_utilizados=[],
        motivo="Falta una pieza.",
    )
    assert _tipos(interrumpida)[-1] is LIBERACION
    assert repo.obtener(orden.id) == interrumpida
    assert _stock(base) == (Decimal("5"), Decimal("0"))
    assert _integridad(base) == []


def test_a7_un_uso_parcial_consume_y_libera_el_resto(taller, base):
    repo, _, contexto, tomadas = taller
    orden, tecnico = _reservada(contexto, tomadas)
    completada = _completar(contexto, orden, tecnico, "0.5")
    assert sorted(t.value for t in _tipos(completada)[1:]) == [
        "CONSUMO",
        "LIBERACION_RESERVA",
    ]
    assert repo.obtener(orden.id) == completada
    assert _stock(base) == (Decimal("4.5"), Decimal("0"))
    assert _integridad(base) == []


def test_a7_una_diferencia_con_el_libro_revierte_el_comando(taller, base):
    """DI-1: el service espera un stock que el libro no deja."""
    repo, unidad, contexto, tomadas = taller
    orden_id = tomadas[0][0]
    antes, version = _stock(base), _version(base, orden_id)
    with pytest.raises(PersistenciaError, match="DI-1"):
        with unidad.transaccion():
            orden = repo.obtener_para_modificar(orden_id)
            contexto.catalogos.actualizar_stock_insumo(INSUMO, Decimal("99"))
            orden.prioridad = 1
            repo.guardar(orden)
    assert _stock(base) == antes
    assert _version(base, orden_id) == version


# --- Doble consumo, doble liberacion y duplicados ---------------------------


@pytest.mark.parametrize("tipo", [CONSUMO, LIBERACION])
def test_a7_no_se_cierra_dos_veces_una_reserva(taller, base, tipo):
    repo, unidad, contexto, tomadas = taller
    orden, tecnico = _reservada(contexto, tomadas)
    completada = _completar(contexto, orden, tecnico)
    reserva, consumo = completada.movimientos_insumo
    antes, version = _stock(base), _version(base, orden.id)
    with pytest.raises(RestriccionDeIntegridadError):
        with unidad.transaccion():
            cargada = repo.obtener_para_modificar(orden.id)
            cargada.movimientos_insumo.append(
                MovimientoInsumo(
                    id="MOV-OTRA-VEZ",
                    tipo=tipo,
                    insumo_id=INSUMO,
                    reparacion_detail_id=reserva.reparacion_detail_id,
                    ejecucion_id=consumo.ejecucion_id,
                    cantidad=Decimal("1"),
                    movimiento_origen_id=reserva.id,
                    fecha=consumo.fecha,
                )
            )
            repo.guardar(cargada)
    assert _stock(base) == antes
    assert _version(base, orden.id) == version


def test_a7_completar_otra_vez_no_vuelve_a_consumir(taller, base):
    _, _, contexto, tomadas = taller
    orden, tecnico = _reservada(contexto, tomadas)
    _completar(contexto, orden, tecnico)
    antes = _stock(base)
    with pytest.raises(PrecondicionInvalidaError):
        _completar(contexto, orden, tecnico)
    assert _stock(base) == antes


# --- Ingresos y ajustes -----------------------------------------------------


def test_a7_un_ingreso_real_entra_al_libro(taller, base):
    _, _, contexto, _ = taller
    resultado = _ingreso(contexto, referencia="FC-1", operacion_id="op-1")
    assert _stock(base) == (Decimal("8"), Decimal("0"))
    assert contexto.catalogos.listar_movimientos_stock() == [
        resultado.movimiento
    ]
    assert resultado.situacion.insumo.stock_fisico == Decimal("8")


@pytest.mark.parametrize(
    "repetido", [{"operacion_id": "op-1"}, {"referencia": "fc-1"}]
)
def test_a7_un_ingreso_repetido_no_se_aplica(taller, base, repetido):
    _, _, contexto, _ = taller
    _ingreso(contexto, referencia="FC-1", operacion_id="op-1")
    antes = _libro(base)
    with pytest.raises(PrecondicionInvalidaError):
        _ingreso(contexto, **repetido)
    assert _libro(base) == antes


def test_a7_dos_envios_simultaneos_de_la_misma_operacion(taller, base):
    _, _, contexto, _ = taller
    resultados, errores = _en_paralelo(
        lambda: _ingreso(contexto, operacion_id="doble"),
        lambda: _ingreso(contexto, operacion_id="doble"),
    )
    assert [type(e) for e in errores] == [PrecondicionInvalidaError]
    assert _stock(base) == (Decimal("8"), Decimal("0"))
    assert _integridad(base) == []


def test_a7_el_ajuste_guarda_el_motivo_libre(taller, base):
    """DI-8: el texto tal cual, sin codigo de catalogo."""
    _, _, contexto, _ = taller
    motivo = "Rotura en el deposito: 2 unidades (ñandú, «caja 3»)."
    with pytest.raises(ConfirmacionRequeridaError):
        _ajuste(contexto, "-2", confirmado=False, motivo=motivo)
    assert _stock(base) == (Decimal("5"), Decimal("0"))
    negativo = _ajuste(contexto, "-2", motivo=motivo)
    positivo = _ajuste(contexto, "1", motivo="Aparecio una.")
    assert _stock(base) == (Decimal("4"), Decimal("0"))
    assert _sql(
        base,
        "select motivo_texto, motivo_ajuste_id from rma.movimiento_inventario "
        "where codigo = %s",
        (negativo.movimiento.id,),
    ) == [(motivo, None)]
    assert contexto.catalogos.listar_movimientos_stock() == [
        negativo.movimiento,
        positivo.movimiento,
    ]


def test_a7_h1_un_ajuste_no_deja_el_disponible_negativo(taller, base):
    """H-1 (DI-3): con una unidad reservada, el ajuste confirmado que la
    quitaria se rechaza con el error funcional, como en JSON, y no escribe
    nada."""
    _, _, contexto, tomadas = taller
    _fijar(base, 1)
    orden, _ = _reservada(contexto, tomadas)
    antes = _libro(base)
    with pytest.raises(PrecondicionInvalidaError, match=orden.id):
        _ajuste(contexto, "-1")
    assert _libro(base) == antes
    assert _stock(base) == (Decimal("1"), Decimal("1"))


def test_a7_h1_el_trigger_protege_aunque_se_saltee_el_service(taller, base):
    """La red por debajo de DI-3: un ajuste que llega al repository sin
    pasar por el service igual se rechaza, sin escribir."""
    _, unidad, contexto, tomadas = taller
    _fijar(base, 1)
    _reservada(contexto, tomadas)
    antes = _libro(base)
    movimiento = MovimientoStock(
        id="MST-SIN-SERVICE",
        tipo=TipoMovimientoInsumo.AJUSTE_NEGATIVO,
        insumo_id=INSUMO,
        cantidad=Decimal("1"),
        stock_anterior=Decimal("1"),
        stock_resultante=Decimal("0"),
        reservado=Decimal("1"),
        disponible_resultante=Decimal("-1"),
        usuario_id=f.ADMINISTRADOR,
        fecha=datetime.now(timezone.utc),
        motivo="Sin pasar por el service.",
    )
    with pytest.raises(RestriccionDeIntegridadError):
        with unidad.transaccion():
            contexto.catalogos.registrar_movimiento_stock(movimiento)
    assert _libro(base) == antes


def test_a7_historial_de_movimientos(taller):
    _, _, contexto, tomadas = taller
    orden, tecnico = _reservada(contexto, tomadas)
    _completar(contexto, orden, tecnico)
    _ingreso(contexto)
    tipos = [
        m.tipo for m in movimientos_de_inventario(contexto, insumo_id=INSUMO)
    ]
    assert sorted(t.value for t in tipos) == [
        "CONSUMO",
        "INGRESO",
        "RESERVA",
    ]


# --- Concurrencia -----------------------------------------------------------


def test_a7_consumo_y_reserva_del_mismo_insumo_a_la_vez(taller, base):
    _, _, contexto, tomadas = taller
    _fijar(base, 2)
    orden, tecnico = _reservada(contexto, tomadas, 0)
    segunda, segundo_tecnico = tomadas[1]
    resultados, errores = _en_paralelo(
        lambda: _completar(contexto, orden, tecnico),
        lambda: _iniciar(contexto, segunda, segundo_tecnico),
    )
    assert errores == []
    assert _reservo(resultados[1])
    assert _stock(base) == (Decimal("1"), Decimal("1"))
    assert _integridad(base) == []


def test_a7_consumo_e_ingreso_a_la_vez(taller, base):
    """Escenario 3 de §5.2: los saldos son la suma exacta."""
    _, _, contexto, tomadas = taller
    orden, tecnico = _reservada(contexto, tomadas)
    _, errores = _en_paralelo(
        lambda: _completar(contexto, orden, tecnico),
        lambda: _ingreso(contexto, "3"),
    )
    assert errores == []
    assert _stock(base) == (Decimal("7"), Decimal("0"))
    assert _integridad(base) == []


def test_a7_reserva_y_ajuste_negativo_a_la_vez(taller, base):
    """Escenario 2 de §5.2: ningun resultado deja el fisico por debajo de
    lo reservado. Gane quien gane, el otro no se aplica."""
    _, _, contexto, tomadas = taller
    _fijar(base, 1)
    orden_id, tecnico = tomadas[0]
    resultados, errores = _en_paralelo(
        lambda: _iniciar(contexto, orden_id, tecnico),
        lambda: _ajuste(contexto, "-1"),
    )
    fisico, reservado = _stock(base)
    assert fisico >= reservado
    reservada = resultados[0] is not None and _reservo(resultados[0])
    ajustado = resultados[1] is not None
    assert reservada != ajustado
    assert _integridad(base) == []
    # Bajo el bloqueo del insumo, el segundo ve al primero: un rechazo
    # funcional (186 o H-1), nunca el del trigger.
    assert all(isinstance(e, PrecondicionInvalidaError) for e in errores)
