"""Lotes, series, desperdicio y devolucion sobre PostgreSQL (DEC-MI-10).

Con ``20261113000900_lotes_inventario.sql`` y los comandos reales:

- Sin lote: el desperdicio cierra la reserva y baja el fisico; la
  devolucion vuelve al stock lo consumido, sin superarlo.
- Con lote: el stock existente queda «sin lote identificado» (no se
  inventan numeros); todo ingreso nombra su lote; las salidas salen de un
  lote con saldo o del stock sin lote identificado; la devolucion vuelve al
  mismo lote. El control no cambia mientras haya saldo en lotes.
- Serie: de a una unidad, nunca dos veces en stock.
- Concurrencia: dos salidas del mismo lote no lo dejan negativo.
- La base concilia (verificar_integridad) en cada caso.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.application import (  # noqa: E402
    completar_ejecucion,
    registrar_ajuste_stock,
    registrar_ingreso_stock,
)
from app.application.lotes import (  # noqa: E402
    registrar_devolucion_insumo,
    saldos_de_insumo,
)
from app.application.operativa import guardar_insumo  # noqa: E402
from app.domain.models import (  # noqa: E402
    InsumoUtilizado,
    TipoMovimientoInsumo,
)
from app.domain.models.lotes import ControlInsumo  # noqa: E402
from app.services import PrecondicionInvalidaError  # noqa: E402
from app.storage.postgres.lotes import PostgresLotesRepository  # noqa: E402
from app.storage.postgres.operativa import (  # noqa: E402
    PostgresConfiguracionOperativa,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_reservas_postgres as reservas  # noqa: E402
from tests.postgres.test_movimientos_postgres import _en_paralelo  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402
from tests.postgres.test_reservas_postgres import (  # noqa: E402
    INSUMO,
    _fijar,
    _iniciar,
    _integridad,
    _stock,
)

armar = reservas.armar
base = reservas.base
corpus = reservas.corpus
plantilla = reservas.plantilla
taller = reservas.taller

T = TipoMovimientoInsumo


@pytest.fixture
def lotes(taller):
    repo, unidad, contexto, tomadas = taller
    contexto = replace(
        contexto,
        lotes=PostgresLotesRepository(unidad),
        operativa=PostgresConfiguracionOperativa(unidad),
    )
    return contexto, tomadas


def _cerrar(contexto, orden, tecnico, **linea):
    resultado, _ = completar_ejecucion(
        contexto,
        orden_id=orden.id,
        ejecucion_id=orden.ejecuciones[-1].id,
        usuario_id=tecnico,
        insumos_utilizados=[InsumoUtilizado(insumo_id=INSUMO, **linea)],
    )
    return resultado


def _controlar(contexto, control):
    insumo = contexto.catalogos.obtener_insumo(INSUMO)
    return guardar_insumo(
        contexto,
        usuario_id=f.ADMINISTRADOR,
        clave=insumo.id,
        codigo=insumo.codigo,
        nombre=insumo.nombre,
        unidad=insumo.unidad,
        activo=True,
        nuevo=False,
        control=control,
    )


def _ingreso(contexto, cantidad, lote=None):
    return registrar_ingreso_stock(
        contexto,
        insumo_id=INSUMO,
        usuario_id=f.ADMINISTRADOR,
        cantidad=Decimal(cantidad),
        motivo="Compra.",
        lote=lote,
    )


def _ajuste(contexto, diferencia, lote_id=None):
    return registrar_ajuste_stock(
        contexto,
        insumo_id=INSUMO,
        usuario_id=f.ADMINISTRADOR,
        diferencia=Decimal(diferencia),
        motivo="Conteo.",
        confirmado=True,
        lote_id=lote_id,
    )


def _saldo(contexto, numero):
    estado = saldos_de_insumo(contexto, INSUMO)
    return next(s.saldo for s in estado.lotes if s.lote.numero == numero)


def _lote_id(contexto, numero):
    estado = saldos_de_insumo(contexto, INSUMO)
    return next(s.lote.id for s in estado.lotes if s.lote.numero == numero)


def test_migracion_conserva_el_stock_existente(lotes, base):
    contexto, _ = lotes
    assert _sql(
        base, "select count(*) from rma.insumo where control <> 'SIN_LOTE'"
    ) == [(0,)]
    assert _sql(base, "select count(*) from rma.lote_insumo") == [(0,)]
    estado = saldos_de_insumo(contexto, INSUMO)
    assert estado.lotes == []
    assert estado.sin_lote_identificado == estado.stock_fisico
    assert _integridad(base) == []


def test_desperdicio_y_devolucion_sin_lote(lotes, base):
    contexto, tomadas = lotes
    _fijar(base, 5)
    (orden_a, tecnico_a), (orden_b, tecnico_b) = tomadas
    a = _cerrar(
        contexto,
        _iniciar(contexto, orden_a, tecnico_a),
        tecnico_a,
        cantidad=Decimal("0"),
        desperdicio=Decimal("1"),
    )
    assert [m.tipo for m in a.movimientos_insumo] == [T.RESERVA, T.DESPERDICIO]
    assert _stock(base)[0] == Decimal("4")

    b = _cerrar(
        contexto,
        _iniciar(contexto, orden_b, tecnico_b),
        tecnico_b,
        cantidad=Decimal("1"),
    )
    consumo = next(m for m in b.movimientos_insumo if m.tipo is T.CONSUMO)
    assert _stock(base)[0] == Decimal("3")
    devuelta = registrar_devolucion_insumo(
        contexto,
        orden_id=orden_b,
        consumo_id=consumo.id,
        cantidad=Decimal("1"),
        motivo="Sobro sin usar.",
        usuario_id=f.COORDINADOR,
    )
    assert devuelta.movimientos_insumo[-1].tipo is T.DEVOLUCION
    assert _stock(base)[0] == Decimal("4")
    with pytest.raises(PrecondicionInvalidaError, match="quedan 0"):
        registrar_devolucion_insumo(
            contexto,
            orden_id=orden_b,
            consumo_id=consumo.id,
            cantidad=Decimal("1"),
            motivo="Otra vez.",
            usuario_id=f.COORDINADOR,
        )
    with pytest.raises(PrecondicionInvalidaError):
        registrar_devolucion_insumo(
            contexto,
            orden_id=orden_b,
            consumo_id=consumo.id,
            cantidad=Decimal("1"),
            motivo="Sin permiso.",
            usuario_id=f.TECNICO,
        )
    assert _integridad(base) == []


def test_lotes_ingreso_consumo_devolucion_y_transicion(lotes, base):
    contexto, tomadas = lotes
    _fijar(base, 2)
    _controlar(contexto, ControlInsumo.LOTE)
    estado = saldos_de_insumo(contexto, INSUMO)
    # El stock que habia queda sin lote identificado.
    assert (estado.lotes, estado.sin_lote_identificado) == ([], Decimal("2"))

    with pytest.raises(PrecondicionInvalidaError, match="indica el numero"):
        _ingreso(contexto, "3")
    _ingreso(contexto, "3", lote="L-1")
    _ingreso(contexto, "1", lote="L-1")
    estado = saldos_de_insumo(contexto, INSUMO)
    assert [(s.lote.numero, s.saldo) for s in estado.lotes] == [
        ("L-1", Decimal("4"))
    ]
    assert (estado.stock_fisico, estado.sin_lote_identificado) == (
        Decimal("6"),
        Decimal("2"),
    )

    (orden_a, tecnico_a), (orden_b, tecnico_b) = tomadas
    l1 = _lote_id(contexto, "L-1")
    with pytest.raises(PrecondicionInvalidaError, match="no es del insumo"):
        _cerrar(
            contexto,
            _iniciar(contexto, orden_a, tecnico_a),
            tecnico_a,
            cantidad=Decimal("1"),
            lote_id="LOT-NO",
        )
    a = contexto.ordenes.obtener(orden_a)
    a = _cerrar(contexto, a, tecnico_a, cantidad=Decimal("1"), lote_id=l1)
    consumo = next(m for m in a.movimientos_insumo if m.tipo is T.CONSUMO)
    assert consumo.lote_id == l1
    assert _saldo(contexto, "L-1") == Decimal("3")
    # Del stock sin lote identificado, explicitamente.
    _cerrar(
        contexto,
        _iniciar(contexto, orden_b, tecnico_b),
        tecnico_b,
        cantidad=Decimal("1"),
    )
    assert saldos_de_insumo(contexto, INSUMO).sin_lote_identificado == 1

    registrar_devolucion_insumo(
        contexto,
        orden_id=orden_a,
        consumo_id=consumo.id,
        cantidad=Decimal("1"),
        motivo="No hizo falta.",
        usuario_id=f.ADMINISTRADOR,
    )
    assert _saldo(contexto, "L-1") == Decimal("4")
    with pytest.raises(PrecondicionInvalidaError, match="no alcanza"):
        _ajuste(contexto, "-5", lote_id=l1)
    with pytest.raises(PrecondicionInvalidaError, match="sin lote"):
        _ajuste(contexto, "-2")
    with pytest.raises(PrecondicionInvalidaError, match="lotes identificados"):
        _controlar(contexto, ControlInsumo.SIN_LOTE)
    assert _integridad(base) == []
    # La base tambien lo impide sin pasar por el service.
    with pytest.raises(psycopg.Error, match="no alcanza"):
        _sql(
            base,
            """
            insert into rma.movimiento_inventario
                (codigo, tipo, insumo_id, cantidad, motivo_ajuste_id,
                 motivo_texto, usuario_id, accion_id, lote_id)
            select 'MOV-LOTE-X', 'AJUSTE_NEGATIVO', i.id, 99, m.id, 'x', u.id,
                   (select id from rma.accion_usuario limit 1), l.id
              from rma.insumo i, rma.motivo_ajuste m, rma.usuario u,
                   rma.lote_insumo l
             where i.clave = %s and m.aplica_a in ('AMBOS', 'NEGATIVO')
               and u.codigo = 'ADMIN-001' and l.numero = 'L-1'
             limit 1
            """,
            (INSUMO,),
        )


def test_series_de_a_una_y_nunca_dos_veces(lotes, base):
    contexto, tomadas = lotes
    _fijar(base, 0)
    _controlar(contexto, ControlInsumo.SERIE)
    with pytest.raises(PrecondicionInvalidaError, match="de a una"):
        _ingreso(contexto, "2", lote="S-1")
    _ingreso(contexto, "1", lote="S-1")
    with pytest.raises(PrecondicionInvalidaError, match="ya esta en stock"):
        _ingreso(contexto, "1", lote="S-1")
    _ingreso(contexto, "1", lote="S-2")
    orden_a, tecnico_a = tomadas[0]
    s1 = _lote_id(contexto, "S-1")
    _cerrar(
        contexto,
        _iniciar(contexto, orden_a, tecnico_a),
        tecnico_a,
        cantidad=Decimal("1"),
        lote_id=s1,
    )
    assert _saldo(contexto, "S-1") == 0
    assert _saldo(contexto, "S-2") == 1
    assert _integridad(base) == []


def test_dos_salidas_del_mismo_lote_no_lo_dejan_negativo(lotes, base):
    contexto, _ = lotes
    _fijar(base, 0)
    _controlar(contexto, ControlInsumo.LOTE)
    _ingreso(contexto, "3", lote="L-C")
    lote_id = _lote_id(contexto, "L-C")
    resultados, errores = _en_paralelo(
        lambda: _ajuste(contexto, "-2", lote_id=lote_id),
        lambda: _ajuste(contexto, "-2", lote_id=lote_id),
    )
    assert len([r for r in resultados if r is not None]) == 1
    assert len(errores) == 1
    assert _saldo(contexto, "L-C") == 1
    assert _integridad(base) == []
