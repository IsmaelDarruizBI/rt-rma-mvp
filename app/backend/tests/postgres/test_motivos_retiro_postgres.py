"""Motivos, parametros y retiro demorado sobre PostgreSQL (DEC-MI-14 y 15).

Con ``20261113000500_motivos_parametros_retiro.sql``: Administracion edita
motivos y el plazo de retiro con auditoria; la cancelacion registra el texto
del motivo; los seguimientos del retiro solo crecen.
"""

from dataclasses import replace
from datetime import timedelta

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.storage.postgres.operativa import (  # noqa: E402
    PostgresConfiguracionOperativa,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.fixtures import iteracion1 as it  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api


@pytest.fixture
def cliente(api):
    app, cliente = api
    contexto = app.state.contexto
    app.state.contexto = replace(
        contexto,
        operativa=PostgresConfiguracionOperativa(contexto.unidad_de_trabajo),
    )
    return cliente


def test_motivos_y_parametros_administrados_con_auditoria(cliente, base):
    admin = f.ADMINISTRADOR
    assert f.ok(cliente.get("/api/admin/reasons"))["editable"] is True
    f.ok(
        cliente.post(
            "/api/admin/reasons",
            json={
                "usuario_id": admin,
                "codigo": "canc-precio",
                "tipo": "CANCELACION",
                "nombre": "El cliente no acepta el precio",
            },
        )
    )
    assert "Ya existe" in f.conflicto(
        cliente.post(
            "/api/admin/reasons",
            json={
                "usuario_id": admin,
                "codigo": "CANC-PRECIO",
                "tipo": "CANCELACION",
                "nombre": "Repetido",
            },
        )
    )
    f.conflicto(
        cliente.post(
            "/api/admin/reasons",
            json={
                "usuario_id": f.RECEPCION,
                "codigo": "CANC-X",
                "tipo": "CANCELACION",
                "nombre": "Sin permiso",
            },
        )
    )
    motivos = f.ok(cliente.get("/api/catalogs/reasons?tipo=CANCELACION"))
    assert [m["codigo"] for m in motivos] == ["CANC-OTRO", "CANC-PRECIO"]

    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/cancel",
            json={"usuario_id": f.RECEPCION, "motivo_codigo": "CANC-PRECIO"},
        )
    )
    # Desactivar el motivo no cambia lo historico.
    f.ok(
        cliente.put(
            "/api/admin/reasons/CANC-PRECIO",
            json={
                "usuario_id": admin,
                "tipo": "CANCELACION",
                "nombre": "Precio no aceptado",
                "activo": False,
            },
        )
    )
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert (
        f.detalle(orden, "DET-001")["cancelacion"]["motivo"]
        == "El cliente no acepta el precio"
    )
    assert "no esta vigente" in f.conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-002/cancel",
            json={"usuario_id": f.RECEPCION, "motivo_codigo": "CANC-PRECIO"},
        )
    )

    assert "entera" in f.conflicto(
        cliente.put(
            "/api/admin/parameters/PLAZO_RETIRO_DIAS",
            json={"usuario_id": admin, "valor": "0"},
        )
    )
    f.ok(
        cliente.put(
            "/api/admin/parameters/PLAZO_RETIRO_DIAS",
            json={"usuario_id": admin, "valor": "10"},
        )
    )
    assert f.ok(cliente.get("/api/admin/parameters"))["parametros"] == {
        "PLAZO_RETIRO_DIAS": "10"
    }
    auditoria = _sql(
        base,
        """
        select entidad, clave, campo, valor_anterior, valor_nuevo
          from rma.cambio_configuracion
         where entidad in ('MOTIVO', 'PARAMETRO')
         order by id
        """,
    )
    assert ("PARAMETRO", "PLAZO_RETIRO_DIAS", "valor", "30", "10") in auditoria
    assert (
        "MOTIVO",
        "CANC-PRECIO",
        "activo",
        "true",
        "false",
    ) in auditoria


def test_retiro_demorado_y_seguimientos_en_postgres(cliente, base):
    reloj = it.instalar_reloj(cliente)
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id, "DET-001", f.BATERIA)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": f.RECEPCION}
        )
    )
    reloj.desplazamiento = timedelta(days=30, hours=1)
    assert (
        f.ok(cliente.get(f"/api/orders/{orden_id}"))["retiro_demorado_dias"]
        == 30
    )
    for nota in ("Primer llamado.", "Segundo llamado."):
        orden = f.ok(
            cliente.post(
                f"/api/orders/{orden_id}/pickup-followups",
                json={"usuario_id": f.RECEPCION, "nota": nota},
            )
        )
    assert [s["nota"] for s in orden["seguimientos_retiro"]] == [
        "Primer llamado.",
        "Segundo llamado.",
    ]
    assert _sql(
        base, "select nota from rma.seguimiento_retiro order by posicion"
    ) == [("Primer llamado.",), ("Segundo llamado.",)]
    for sentencia in (
        "update rma.seguimiento_retiro set nota = 'x'",
        "delete from rma.seguimiento_retiro",
    ):
        with pytest.raises(psycopg.Error):
            _sql(base, sentencia)
    assert _sql(base, "select count(*) from rma.verificar_integridad()") == [
        (0,)
    ]
