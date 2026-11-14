"""Reglas de Compras sin base (DEC-MI-09): sugerencias, en camino,
recepciones parciales y series. El circuito completo, con stock y lotes,
se prueba sobre PostgreSQL (tests/postgres/test_compras_postgres.py)."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.models import Insumo, RolUsuario, Usuario
from app.domain.models.compras import (
    EstadoOrdenCompra,
    EstadoSolicitud,
    ItemOrdenCompra,
    LineaRecepcion,
    OrigenSolicitud,
    Proveedor,
)
from app.domain.models.lotes import ControlInsumo
from app.services import PrecondicionInvalidaError
from app.services.compras import (
    confirmar_orden_compra,
    en_camino,
    nueva_orden_compra,
    nueva_recepcion,
    nueva_solicitud,
    sugerencias,
)

FECHA = datetime(2026, 11, 14, tzinfo=timezone.utc)
RECEP = Usuario(id="RECEP-001", nombre="R", rol=RolUsuario.RECEPCION)
TECH = Usuario(id="TECH-001", nombre="T", rol=RolUsuario.TECNICO)
PROV = Proveedor(id="PRV-0001", nombre="Repuestos SA")
D = Decimal


def _insumo(control=ControlInsumo.SIN_LOTE, id="INS-001"):
    return Insumo(
        id=id, codigo=id, nombre=id, stock_fisico=D("0"), control=control
    )


def _orden(insumos, cantidad="5"):
    orden = nueva_orden_compra(
        orden_compra_id="OC-000001",
        proveedor=PROV,
        items=[
            ItemOrdenCompra(
                insumo_id=i.id, cantidad=D(cantidad), costo_unitario=D("100")
            )
            for i in insumos
        ],
        solicitudes=[],
        insumos={i.id: i for i in insumos},
        observaciones=None,
        usuario=RECEP,
        fecha=FECHA,
    )
    return confirmar_orden_compra(orden, usuario=RECEP, fecha=FECHA)


def _recibir(orden, insumos, **linea):
    return nueva_recepcion(
        orden,
        recepcion_id=f"REC-{len(orden.recepciones) + 1:02d}",
        lineas=[LineaRecepcion(**linea)],
        insumos={i.id: i for i in insumos},
        remito=linea.pop("remito", None) if "remito" in linea else None,
        observaciones=None,
        usuario=RECEP,
        fecha=FECHA,
    )


def test_sugerencias_restan_disponible_y_en_camino():
    resultado = sugerencias(
        disponibles={"A": D("1"), "B": D("-2"), "C": D("10")},
        demanda={"A": (D("4"), ["OR-1", "OR-2"]), "C": (D("3"), ["OR-3"])},
        en_camino={"A": D("1")},
    )
    assert [(s.insumo_id, s.sugerido) for s in resultado] == [
        ("A", D("2")),
        ("B", D("2")),
    ]
    assert resultado[0].ordenes == ["OR-1", "OR-2"]


def test_solicitud_solo_de_quien_puede_y_con_motivo():
    with pytest.raises(PrecondicionInvalidaError):
        nueva_solicitud(
            solicitud_id="SC-000001",
            insumo=_insumo(),
            cantidad=D("1"),
            motivo="x",
            origen=OrigenSolicitud.MANUAL,
            ordenes=[],
            usuario=TECH,
            fecha=FECHA,
        )
    with pytest.raises(PrecondicionInvalidaError, match="motivo"):
        nueva_solicitud(
            solicitud_id="SC-000001",
            insumo=_insumo(),
            cantidad=D("1"),
            motivo="  ",
            origen=OrigenSolicitud.MANUAL,
            ordenes=[],
            usuario=RECEP,
            fecha=FECHA,
        )
    solicitud = nueva_solicitud(
        solicitud_id="SC-000001",
        insumo=_insumo(),
        cantidad=D("2"),
        motivo="Reponer.",
        origen=OrigenSolicitud.FALTANTE,
        ordenes=["OR-2", "OR-1", "OR-2"],
        usuario=RECEP,
        fecha=FECHA,
    )
    assert (solicitud.estado, solicitud.ordenes) == (
        EstadoSolicitud.PENDIENTE,
        ["OR-1", "OR-2"],
    )
    assert en_camino([], [solicitud]) == {"INS-001": D("2")}


def test_recepciones_parciales_nunca_superan_lo_pendiente():
    insumos = [_insumo()]
    orden = _orden(insumos)
    assert orden.estado is EstadoOrdenCompra.CONFIRMADA
    recepcion = _recibir(
        orden,
        insumos,
        insumo_id="INS-001",
        cantidad=D("2"),
        costo_unitario=D("120"),
    )
    assert "acordado 100" in recepcion.lineas[0].diferencia
    orden = orden.model_copy(update={"recepciones": [recepcion]})
    assert (orden.estado, orden.pendiente("INS-001")) == (
        EstadoOrdenCompra.PARCIAL,
        D("3"),
    )
    with pytest.raises(PrecondicionInvalidaError, match="quedan 3"):
        _recibir(
            orden,
            insumos,
            insumo_id="INS-001",
            cantidad=D("4"),
            costo_unitario=D("100"),
        )
    resto = _recibir(
        orden,
        insumos,
        insumo_id="INS-001",
        cantidad=D("3"),
        costo_unitario=D("100"),
    )
    assert resto.lineas[0].diferencia is None
    orden = orden.model_copy(update={"recepciones": [recepcion, resto]})
    assert orden.estado is EstadoOrdenCompra.RECIBIDA
    with pytest.raises(PrecondicionInvalidaError, match="no espera"):
        _recibir(
            orden,
            insumos,
            insumo_id="INS-001",
            cantidad=D("1"),
            costo_unitario=D("100"),
        )


def test_lote_y_series_segun_el_control_del_insumo():
    con_lote = _insumo(ControlInsumo.LOTE, "INS-L")
    serie = _insumo(ControlInsumo.SERIE, "INS-S")
    orden = _orden([con_lote, serie], cantidad="2")
    with pytest.raises(PrecondicionInvalidaError, match="indica el lote"):
        _recibir(
            orden,
            [con_lote, serie],
            insumo_id="INS-L",
            cantidad=D("1"),
            costo_unitario=D("100"),
        )
    with pytest.raises(PrecondicionInvalidaError, match="serie distinto"):
        _recibir(
            orden,
            [con_lote, serie],
            insumo_id="INS-S",
            cantidad=D("2"),
            costo_unitario=D("100"),
            series=["S-1", "S-1"],
        )
    recepcion = _recibir(
        orden,
        [con_lote, serie],
        insumo_id="INS-S",
        cantidad=D("2"),
        costo_unitario=D("100"),
        series=["S-1", "S-2"],
    )
    assert recepcion.lineas[0].series == ["S-1", "S-2"]


def test_no_se_compra_dos_veces_el_mismo_insumo_en_una_orden():
    insumo = _insumo()
    with pytest.raises(PrecondicionInvalidaError, match="dos veces"):
        nueva_orden_compra(
            orden_compra_id="OC-000001",
            proveedor=PROV,
            items=[
                ItemOrdenCompra(
                    insumo_id="INS-001", cantidad=D("1"), costo_unitario=D("1")
                ),
                ItemOrdenCompra(
                    insumo_id="INS-001", cantidad=D("1"), costo_unitario=D("1")
                ),
            ],
            solicitudes=[],
            insumos={"INS-001": insumo},
            observaciones=None,
            usuario=RECEP,
            fecha=FECHA,
        )


def test_en_la_demo_json_compras_no_esta_disponible(tmp_path):
    from tests.fixtures import api_salidas as f

    with f.cliente_http(tmp_path, "10") as cliente:
        assert f.ok(cliente.get("/api/purchases/status")) == {
            "disponible": False
        }
        assert "PostgreSQL" in f.conflicto(
            cliente.post(
                "/api/purchases/requests",
                json={
                    "usuario_id": f.RECEPCION,
                    "insumo_id": f.INSUMO_BATERIA,
                    "cantidad": "1",
                    "motivo": "x",
                },
            )
        )
