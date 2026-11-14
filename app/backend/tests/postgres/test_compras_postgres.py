"""Compras sobre PostgreSQL (DEC-MI-09), con ``20261113001000_compras.sql``.

Circuito completo con los comandos reales: proveedor (Administracion, con
auditoria) -> solicitud -> orden de compra (crea y confirma quien puede, sin
aprobacion) -> recepciones parciales que generan ingresos del libro, con
lote o serie si el insumo lo exige -> ultimo costo e historico. Tambien:
cancelacion, remito repetido, mas de lo pendiente, concurrencia y lo que la
base impide sin pasar por los services.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.application import compras  # noqa: E402
from app.application.lotes import saldos_de_insumo  # noqa: E402
from app.domain.models.compras import (  # noqa: E402
    EstadoOrdenCompra,
    EstadoSolicitud,
    ItemOrdenCompra,
    LineaRecepcion,
)
from app.domain.models.lotes import ControlInsumo  # noqa: E402
from app.services import PrecondicionInvalidaError  # noqa: E402
from app.storage.postgres.compras import (  # noqa: E402
    PostgresComprasRepository,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_reservas_postgres as reservas  # noqa: E402
from tests.postgres.test_lotes_postgres import _controlar  # noqa: E402
from tests.postgres.test_lotes_postgres import lotes as _lotes  # noqa: E402
from tests.postgres.test_movimientos_postgres import _en_paralelo  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402
from tests.postgres.test_reservas_postgres import (  # noqa: E402
    INSUMO,
    _fijar,
    _integridad,
    _stock,
)

armar = reservas.armar
base = reservas.base
corpus = reservas.corpus
plantilla = reservas.plantilla
taller = reservas.taller
lotes = _lotes
D = Decimal


@pytest.fixture
def contexto_compras(lotes):
    contexto, _ = lotes
    return replace(
        contexto,
        compras=PostgresComprasRepository(contexto.unidad_de_trabajo),
    )


def _proveedor(contexto):
    return compras.guardar_proveedor(
        contexto,
        usuario_id=f.ADMINISTRADOR,
        datos={"nombre": "Repuestos SA", "telefono": "341-555"},
        codigo=None,
    )


def _orden(contexto, cantidad="5", costo="100", solicitudes=()):
    orden = compras.crear_orden_compra(
        contexto,
        usuario_id=f.RECEPCION,
        proveedor_id=_proveedor(contexto).id,
        items=[
            ItemOrdenCompra(
                insumo_id=INSUMO, cantidad=D(cantidad), costo_unitario=D(costo)
            )
        ],
        solicitudes=list(solicitudes),
    )
    return compras.confirmar(
        contexto, usuario_id=f.COORDINADOR, orden_id=orden.id
    )


def _recibir(contexto, orden, cantidad, costo="100", **extra):
    return compras.recibir(
        contexto,
        usuario_id=f.RECEPCION,
        orden_id=orden.id,
        lineas=[
            LineaRecepcion(
                insumo_id=INSUMO,
                cantidad=D(cantidad),
                costo_unitario=D(costo),
                **{k: v for k, v in extra.items() if k != "remito"},
            )
        ],
        remito=extra.get("remito"),
    )


def test_circuito_completo_con_recepciones_parciales(contexto_compras, base):
    contexto = contexto_compras
    _fijar(base, 1)
    with pytest.raises(PrecondicionInvalidaError):
        compras.guardar_proveedor(
            contexto,
            usuario_id=f.RECEPCION,
            datos={"nombre": "Otro"},
            codigo=None,
        )
    solicitud = compras.crear_solicitud(
        contexto,
        usuario_id=f.RECEPCION,
        insumo_id=INSUMO,
        cantidad=D("5"),
        motivo="Reponer baterias.",
    )
    orden = _orden(contexto, solicitudes=[solicitud.id])
    assert (orden.creada_por, orden.confirmada_por) == (
        f.RECEPCION,
        f.COORDINADOR,
    )
    assert (
        compras.listar_solicitudes(contexto)[0].estado
        is EstadoSolicitud.EN_ORDEN
    )

    orden = _recibir(contexto, orden, "2", costo="120", remito="R-1")
    assert orden.estado is EstadoOrdenCompra.PARCIAL
    linea = orden.recepciones[0].lineas[0]
    assert "acordado 100" in linea.diferencia
    assert len(linea.movimientos) == 1
    assert _stock(base)[0] == D("3")
    with pytest.raises(PrecondicionInvalidaError, match="ya se recibio"):
        _recibir(contexto, orden, "1", remito="r-1")
    with pytest.raises(PrecondicionInvalidaError, match="quedan 3"):
        _recibir(contexto, orden, "4")
    orden = _recibir(contexto, orden, "3", costo="110", remito="R-2")
    assert orden.estado is EstadoOrdenCompra.RECIBIDA
    assert _stock(base)[0] == D("6")

    historico = compras.costos_de_compra(contexto, INSUMO)
    assert [c.costo_unitario for c in historico] == [D("110"), D("120")]
    assert compras.ultimos_costos(contexto)[INSUMO].costo_unitario == D("110")
    releida = compras.obtener_orden_compra(contexto, orden.id)
    assert releida.estado is EstadoOrdenCompra.RECIBIDA
    assert [r.id for r in releida.recepciones] == ["REC-01", "REC-02"]
    assert _sql(
        base,
        """
        select referencia, motivo_texto from rma.movimiento_inventario
         where tipo = 'INGRESO' and left(referencia, 3) = 'OC-'
         order by secuencia
        """,
    ) == [
        (f"{orden.id}/REC-01/1", f"Compra {orden.id} (REC-01)."),
        (f"{orden.id}/REC-02/1", f"Compra {orden.id} (REC-02)."),
    ]
    assert ("PRV-0001", "nombre", None, "Repuestos SA") in _sql(
        base,
        """
        select clave, campo, valor_anterior, valor_nuevo
          from rma.cambio_configuracion where entidad = 'PROVEEDOR'
        """,
    )
    assert _integridad(base) == []


def test_recepcion_con_lote_y_con_series(contexto_compras, base):
    contexto = contexto_compras
    _fijar(base, 0)
    _controlar(contexto, ControlInsumo.LOTE)
    orden = _orden(contexto, cantidad="3")
    with pytest.raises(PrecondicionInvalidaError, match="indica el lote"):
        _recibir(contexto, orden, "2")
    orden = _recibir(contexto, orden, "2", lote="L-OC")
    estado = saldos_de_insumo(contexto, INSUMO)
    (saldo,) = estado.lotes
    assert (saldo.lote.numero, saldo.lote.origen.value, saldo.saldo) == (
        "L-OC",
        "COMPRA",
        D("2"),
    )

    serie = _orden(contexto, cantidad="2")
    with pytest.raises(PrecondicionInvalidaError):
        _controlar(contexto, ControlInsumo.SERIE)  # el lote tiene saldo
    assert _integridad(base) == []
    del serie


def test_series_un_ingreso_por_unidad(contexto_compras, base):
    contexto = contexto_compras
    _fijar(base, 0)
    _controlar(contexto, ControlInsumo.SERIE)
    orden = _orden(contexto, cantidad="2")
    orden = _recibir(contexto, orden, "2", series=["S-10", "S-11"])
    (linea,) = orden.recepciones[0].lineas
    assert len(linea.movimientos) == 2
    estado = saldos_de_insumo(contexto, INSUMO)
    assert sorted((s.lote.numero, s.saldo) for s in estado.lotes) == [
        ("S-10", D("1")),
        ("S-11", D("1")),
    ]
    assert _integridad(base) == []


def test_cancelar_sin_recepciones_devuelve_las_solicitudes(
    contexto_compras, base
):
    contexto = contexto_compras
    solicitud = compras.crear_solicitud(
        contexto,
        usuario_id=f.ADMINISTRADOR,
        insumo_id=INSUMO,
        cantidad=D("2"),
        motivo="Prueba.",
    )
    orden = _orden(contexto, cantidad="2", solicitudes=[solicitud.id])
    cancelada = compras.cancelar(
        contexto,
        usuario_id=f.ADMINISTRADOR,
        orden_id=orden.id,
        motivo="Se compro por otro lado.",
    )
    assert cancelada.estado is EstadoOrdenCompra.CANCELADA
    assert (
        compras.listar_solicitudes(contexto)[0].estado
        is EstadoSolicitud.PENDIENTE
    )
    otra = _orden(contexto, cantidad="2")
    _recibir(contexto, otra, "1")
    with pytest.raises(PrecondicionInvalidaError, match="sin recepciones"):
        compras.cancelar(
            contexto,
            usuario_id=f.ADMINISTRADOR,
            orden_id=otra.id,
            motivo="Tarde.",
        )
    # La base tampoco lo deja, ni cambiar lo registrado.
    for sentencia in (
        f"update rma.orden_compra set cancelada_en = now(), "
        f"cancelada_por = creada_por, motivo_cancelacion = 'x' "
        f"where codigo = '{otra.id}'",
        "update rma.orden_compra_item set cantidad = 9",
        "delete from rma.recepcion_compra_linea",
    ):
        with pytest.raises(psycopg.Error):
            _sql(base, sentencia)


def test_dos_recepciones_a_la_vez_no_superan_lo_pedido(contexto_compras, base):
    contexto = contexto_compras
    _fijar(base, 0)
    orden = _orden(contexto, cantidad="5")
    resultados, errores = _en_paralelo(
        lambda: _recibir(contexto, orden, "3"),
        lambda: _recibir(contexto, orden, "3"),
    )
    assert len([r for r in resultados if r is not None]) == 1
    assert len(errores) == 1
    assert _stock(base)[0] == D("3")
    assert compras.obtener_orden_compra(contexto, orden.id).pendiente(
        INSUMO
    ) == D("2")
    assert _integridad(base) == []
