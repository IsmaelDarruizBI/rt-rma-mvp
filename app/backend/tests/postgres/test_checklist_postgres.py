"""Checklist de recepcion por tipo de equipo sobre PostgreSQL (DC12), con
``20261113001100_checklist_recepcion.sql``.

Administracion configura tipos y preguntas (auditado); Recepcion elige el
tipo y responde lo que quiera (todo opcional, «no realizada» incluida); lo
registrado guarda la copia de las preguntas; corregir agrega una version
con motivo y un cambio del catalogo no altera lo ya registrado.
"""

from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.storage.postgres.operativa import (  # noqa: E402
    PostgresConfiguracionOperativa,
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
def cliente_checklist(api):
    app, cliente = api
    contexto = app.state.contexto
    app.state.contexto = replace(
        contexto,
        operativa=PostgresConfiguracionOperativa(contexto.unidad_de_trabajo),
    )
    return cliente


def _admin(cliente, metodo, ruta, **cuerpo):
    return f.ok(
        getattr(cliente, metodo)(
            ruta, json={"usuario_id": f.ADMINISTRADOR, **cuerpo}
        )
    )


def test_checklist_configurable_con_copia_y_versiones(cliente_checklist, base):
    cliente = cliente_checklist
    f.conflicto(
        cliente.post(
            "/api/admin/equipment-types",
            json={"usuario_id": f.RECEPCION, "nombre": "Celular"},
        )
    )
    tipo = _admin(
        cliente, "post", "/api/admin/equipment-types", nombre="Celular"
    )
    assert tipo["id"] == "TEQ-0001"
    carga = _admin(
        cliente,
        "post",
        "/api/admin/checklist-questions",
        tipo_equipo_id="TEQ-0001",
        texto="Carga",
        opciones=["Carga", "No carga"],
        orden=1,
    )
    _admin(
        cliente,
        "post",
        "/api/admin/checklist-questions",
        tipo_equipo_id="TEQ-0001",
        texto="Camara",
        opciones=["Funciona", "Falla"],
        orden=2,
    )
    catalogo = f.ok(cliente.get("/api/catalogs/checklist"))
    assert [p["texto"] for p in catalogo["preguntas"]] == ["Carga", "Camara"]

    orden_id = f.crear(cliente)
    ruta = f"/api/orders/{orden_id}/checklist"
    assert "no es una opcion" in f.conflicto(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.RECEPCION,
                "tipo_equipo_id": "TEQ-0001",
                "respuestas": [
                    {"pregunta_id": carga["id"], "respuesta": "Tal vez"}
                ],
            },
        )
    )
    orden = f.ok(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.RECEPCION,
                "tipo_equipo_id": "TEQ-0001",
                "respuestas": [
                    {"pregunta_id": carga["id"], "no_realizada": True}
                ],
            },
        )
    )
    (registro,) = orden["checklists_recepcion"]
    assert registro["sin_registrar"] == ["Camara"]
    assert registro["respuestas"][0]["no_realizada"] is True
    assert (
        "Verificaciones del checklist sin registrar (1)"
        in orden["informacion_faltante"]
    )

    # Corregir exige motivo y agrega una version.
    assert "motivo" in f.conflicto(
        cliente.post(
            ruta,
            json={"usuario_id": f.RECEPCION, "tipo_equipo_id": "TEQ-0001"},
        )
    )
    orden = f.ok(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.RECEPCION,
                "tipo_equipo_id": "TEQ-0001",
                "respuestas": [
                    {"pregunta_id": carga["id"], "respuesta": "No carga"}
                ],
                "motivo": "Se pudo probar el cargador.",
            },
        )
    )
    assert len(orden["checklists_recepcion"]) == 2

    # Cambiar el catalogo no altera lo registrado.
    _admin(
        cliente,
        "put",
        f"/api/admin/checklist-questions/{carga['id']}",
        tipo_equipo_id="TEQ-0001",
        texto="Carga por USB",
        opciones=["Si", "No"],
        orden=1,
    )
    releida = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert releida["checklists_recepcion"] == orden["checklists_recepcion"]
    assert releida["checklists_recepcion"][1]["respuestas"][0]["texto"] == (
        "Carga"
    )
    assert ("TEQ-0001/CHK-0001", "texto", "Carga", "Carga por USB") in _sql(
        base,
        """
        select clave, campo, valor_anterior, valor_nuevo
          from rma.cambio_configuracion where entidad = 'CHECKLIST'
        """,
    )
    with pytest.raises(psycopg.Error):
        _sql(base, "update rma.checklist_registro set motivo = 'x'")
    assert _sql(base, "select count(*) from rma.verificar_integridad()") == [
        (0,)
    ]
