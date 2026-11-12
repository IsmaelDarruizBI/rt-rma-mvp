"""Administracion de catalogos en PostgreSQL (DC23, DC23AUD, BR-REP-040).

Alta y edicion de Tipos de Reparacion, Tipos habilitados por Mesa, la
auditoria de cada cambio en ``rma.cambio_configuracion`` (inmutable) y el
historial de precios. Un cambio de precio no altera lo ya registrado.
"""

from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.storage.postgres.configuracion import (  # noqa: E402
    PostgresConfiguracionRepository,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api


@pytest.fixture
def admin(api):
    app, cliente = api
    contexto = app.state.contexto
    app.state.contexto = replace(
        contexto,
        configuracion=PostgresConfiguracionRepository(
            contexto.unidad_de_trabajo
        ),
    )
    return cliente


def _tipo(**cambios):
    return {
        "usuario_id": f.ADMINISTRADOR,
        "nombre": "Cambio de bateria",
        "precio": "80000",
        "puntaje": 10,
        "garantia_dias": 90,
        **cambios,
    }


def test_alta_y_edicion_de_un_tipo_con_su_auditoria(admin, base):
    catalogo = f.ok(admin.get("/api/admin/catalog"))
    assert catalogo["editable"] is True

    f.ok(
        admin.post(
            "/api/admin/repair-types",
            json=_tipo(codigo="TR-900", nombre="Cambio de pin de carga"),
        )
    )
    f.conflicto(
        admin.post(
            "/api/admin/repair-types",
            json=_tipo(codigo="TR-900", nombre="Duplicado"),
        )
    )
    f.ok(
        admin.put(
            "/api/admin/repair-types/TR-900",
            json=_tipo(nombre="Cambio de pin de carga", precio="45000"),
        )
    )
    # Se desactiva, no se borra.
    f.ok(
        admin.put(
            "/api/admin/repair-types/TR-900",
            json=_tipo(
                nombre="Cambio de pin de carga", precio="45000", activo=False
            ),
        )
    )

    cambios = f.ok(
        admin.get(
            "/api/admin/config-changes",
            params={"entidad": "TIPO_REPARACION", "clave": "TR-900"},
        )
    )
    assert [
        (c["campo"], c["valor_anterior"], c["valor_nuevo"]) for c in cambios
    ] == [
        ("nombre", None, "Cambio de pin de carga"),
        ("precio", None, "80000.00"),
        ("puntaje", None, "10"),
        ("garantia_dias", None, "90"),
        ("activo", None, "true"),
        ("precio", "80000.00", "45000.00"),
        ("activo", "true", "false"),
    ]
    assert {c["usuario_id"] for c in cambios} == {f.ADMINISTRADOR}
    assert _sql(
        base,
        "select precio_anterior, precio_nuevo from rma.historial_precio "
        "where tipo_reparacion = 'TR-900' order by secuencia",
    ) == [(None, "80000.00"), ("80000.00", "45000.00")]
    assert _sql(
        base,
        "select precio, activo from rma.tipo_reparacion "
        "where codigo = 'TR-900'",
    ) == [(45000, False)]

    # La auditoria no se modifica ni se borra.
    for sentencia in (
        "update rma.cambio_configuracion set valor_nuevo = 'x'",
        "delete from rma.cambio_configuracion",
    ):
        with pytest.raises(psycopg.Error):
            _sql(base, sentencia)


def test_un_cambio_de_precio_no_altera_lo_registrado(admin, base):
    anterior = f.definida(admin, f.BATERIA)
    f.ok(
        admin.put(
            f"/api/admin/repair-types/{f.BATERIA}",
            json=_tipo(precio="95000"),
        )
    )

    vieja = f.ok(admin.get(f"/api/orders/{anterior}"))
    assert f.detalle(vieja, "DET-001")["precio"] == "80000"
    nueva = f.ok(admin.get(f"/api/orders/{f.definida(admin, f.BATERIA)}"))
    assert f.detalle(nueva, "DET-001")["precio"] == "95000"


def test_tipos_habilitados_de_una_mesa(admin, base):
    f.ok(
        admin.put(
            f"/api/admin/stations/{f.ESTACION}/repair-types",
            json={"usuario_id": f.ADMINISTRADOR, "tipos": [f.BATERIA]},
        )
    )
    mesa = next(
        m
        for m in f.ok(admin.get("/api/admin/catalog"))["mesas"]
        if m["id"] == f.ESTACION
    )
    assert mesa["tipos"] == [f.BATERIA]
    (cambio,) = f.ok(
        admin.get(
            "/api/admin/config-changes",
            params={"entidad": "MESA_TRABAJO", "clave": f.ESTACION},
        )
    )
    assert cambio["campo"] == "tipos_habilitados"
    assert cambio["valor_nuevo"] == f.BATERIA


@pytest.mark.parametrize("usuario", [f.RECEPCION, f.TECNICO, f.COORDINADOR])
def test_solo_administracion_cambia_la_configuracion(admin, base, usuario):
    respuesta = admin.put(
        f"/api/admin/repair-types/{f.BATERIA}",
        json=_tipo(usuario_id=usuario, precio="1"),
    )
    assert respuesta.status_code in (403, 409), respuesta.text
    assert _sql(base, "select count(*) from rma.cambio_configuracion") == [
        (0,)
    ]
