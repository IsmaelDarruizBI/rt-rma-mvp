"""Macroiteracion V1.4 en PostgreSQL: evaluacion tecnica (BR-REP-035,
VAR-REP-019), descarte tecnico, antecedentes del Equipo y reporte
operativo.

Contra la base local descartable con la migracion
``20261112000100_evaluacion_tecnica.sql``: cada evaluacion queda en
``rma.evaluacion_tecnica``, el origen del diagnostico en
``rma.detalle.origen_diagnostico`` y los pasos 182/183/184 con su tipo de
evento. La relectura devuelve lo mismo que respondio el comando.
"""

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.sembrado import fijar_stock  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api


def _evaluar(cliente, orden_id, resultado, **extra):
    return cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/evaluation",
        json={"usuario_id": f.TECNICO, "resultado": resultado, **extra},
    )


def _evaluaciones(base, orden_id):
    return _sql(
        base,
        """
        select d.codigo, x.version_definicion, x.resultado, u.codigo,
               x.observaciones, x.posicion
        from rma.evaluacion_tecnica x
        join rma.detalle d on d.id = x.detalle_id
        join rma.orden o on o.id = d.orden_id
        join rma.usuario u on u.id = x.usuario_id
        where o.codigo = %s
        order by x.posicion
        """,
        (orden_id,),
    )


def _detalle(base, orden_id):
    return _sql(
        base,
        """
        select d.origen_diagnostico, d.cancelacion_origen
        from rma.detalle d join rma.orden o on o.id = d.orden_id
        where o.codigo = %s and d.codigo = 'DET-001'
        """,
        (orden_id,),
    )[0]


def _tipos(base, orden_id, nodo):
    return _sql(
        base,
        """
        select t.codigo from rma.evento_negocio e
        join rma.tipo_evento t on t.id = e.tipo_evento_id
        join rma.orden o on o.id = e.orden_id
        where o.codigo = %s and e.historial_referencia_id = %s
        order by e.secuencia
        """,
        (orden_id, nodo),
    )


@pytest.mark.v14_evaluacion
def test_v14_evaluacion_confirmada_se_guarda_y_se_relee(api, base):
    _, cliente = api
    with psycopg.connect(base, autocommit=True) as conexion:
        fijar_stock(conexion, f.INSUMO_BATERIA, 10)
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    assert _detalle(base, orden_id) == ("RECEPCION", None)

    evaluada = f.ok(_evaluar(cliente, orden_id, "CONFIRMADO"))

    assert _evaluaciones(base, orden_id) == [
        ("DET-001", 1, "CONFIRMADO", f.TECNICO, None, 1)
    ]
    assert f.ok(cliente.get(f"/api/orders/{orden_id}")) == evaluada
    assert _tipos(base, orden_id, "PROC-REP-183") == [("EV-REP-025",)]
    assert _tipos(base, orden_id, "PROC-REP-184") == [("EV-SIS-001",)]

    iniciada = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": f.TECNICO},
        )
    )
    assert f.ok(cliente.get(f"/api/orders/{orden_id}")) == iniciada
    # 182 dos veces: "Requiere" al evaluar y "No requiere" al iniciar.
    assert _tipos(base, orden_id, "PROC-REP-182") == [
        ("EV-SIS-001",),
        ("EV-SIS-001",),
    ]


@pytest.mark.v14_evaluacion
def test_v14_descarte_tecnico_se_guarda(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)

    descartada = f.ok(
        _evaluar(
            cliente,
            orden_id,
            "DESCARTADO",
            observaciones="Falla de software.",
        )
    )

    assert _detalle(base, orden_id) == ("RECEPCION", "DESCARTE_TECNICO")
    assert _evaluaciones(base, orden_id) == [
        ("DET-001", 1, "DESCARTADO", f.TECNICO, "Falla de software.", 1)
    ]
    assert f.ok(cliente.get(f"/api/orders/{orden_id}")) == descartada
    # La evaluacion es historia: no se modifica ni se borra.
    for sentencia in (
        "update rma.evaluacion_tecnica set observaciones = 'x'",
        "delete from rma.evaluacion_tecnica",
    ):
        with pytest.raises(psycopg.Error):
            _sql(base, sentencia)
    assert len(_evaluaciones(base, orden_id)) == 1


@pytest.mark.v14_evaluacion
def test_v14_redefinicion_en_la_evaluacion_se_guarda(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)

    redefinida = f.ok(
        _evaluar(
            cliente,
            orden_id,
            "REQUIERE_REDEFINICION",
            observaciones="Es la pantalla.",
            tipo_reparacion_id=f.PANTALLA,
        )
    )

    assert _detalle(base, orden_id) == ("REVISION_TECNICA", None)
    assert _evaluaciones(base, orden_id) == [
        (
            "DET-001",
            1,
            "REQUIERE_REDEFINICION",
            f.TECNICO,
            "Es la pantalla.",
            1,
        )
    ]
    assert f.ok(cliente.get(f"/api/orders/{orden_id}")) == redefinida


@pytest.mark.v14_evaluacion
def test_v14_reparaciones_adicionales_se_guardan(api, base):
    """184 -> 128 en la evaluacion y 128 durante la ejecucion: cada alta es
    un Detalle del tecnico (REVISION_TECNICA) con su evento de alta."""
    _, cliente = api
    with psycopg.connect(base, autocommit=True) as conexion:
        fijar_stock(conexion, f.INSUMO_BATERIA, 10)
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ok(
        _evaluar(
            cliente,
            orden_id,
            "CONFIRMADO",
            adicionales=[{"tipo_reparacion_id": f.PANTALLA}],
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": f.TECNICO},
        )
    )
    durante = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/additional",
            json={"usuario_id": f.TECNICO, "tipo_reparacion_id": f.BATERIA},
        )
    )

    filas = _sql(
        base,
        """
        select d.codigo, d.origen_diagnostico
        from rma.detalle d join rma.orden o on o.id = d.orden_id
        where o.codigo = %s order by d.codigo
        """,
        (orden_id,),
    )
    assert filas == [
        ("DET-001", "RECEPCION"),
        ("DET-002", "REVISION_TECNICA"),
        ("DET-003", "REVISION_TECNICA"),
    ]
    assert _tipos(base, orden_id, "PROC-REP-128") == [
        ("EV-REP-010",),
        ("EV-REP-010",),
    ]
    assert f.ok(cliente.get(f"/api/orders/{orden_id}")) == durante


def test_v14_un_detalle_anterior_queda_sin_origen(api, base):
    """Plan de transicion: lo anterior a la evaluacion queda en NULL."""
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    assert _detalle(base, orden_id) == (None, None)


def test_v14_antecedentes_y_reporte_en_postgres(api, base):
    _, cliente = api

    def crear(imei, serie=None):
        return f.ok(
            cliente.post(
                "/api/orders",
                json={
                    "usuario_id": f.RECEPCION,
                    "cliente": {"nombre_apellido": "Cli", "telefono": "341-9"},
                    "equipo": {
                        "marca": "Apple",
                        "modelo": "iPhone 14",
                        "falla_reportada": "No carga.",
                        "imei": imei,
                        "numero_serie": serie,
                    },
                },
            )
        )["id"]

    primera = crear("356938035643809", "F2LX1")
    segunda = crear("35 6938 0356 43809")
    crear("999999999999999")

    por_imei = f.ok(
        cliente.get(
            "/api/equipment/history",
            params={"imei": "356938035643809", "excluir_orden_id": segunda},
        )
    )
    assert [o["orden_id"] for o in por_imei["ordenes"]] == [primera]
    por_serie = f.ok(
        cliente.get("/api/equipment/history", params={"numero_serie": "f2lx1"})
    )
    assert [o["orden_id"] for o in por_serie["ordenes"]] == [primera]

    reporte = f.ok(cliente.get("/api/reports/operational"))
    assert sum(reporte["ordenes_por_origen"].values()) == 3
    assert len(reporte["pendientes"]) == 3
