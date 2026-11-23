"""Bloque 4 de ajustes funcionales (comprobantes, DEC-AJ-09) sobre
PostgreSQL.

- Migracion ``20261123000300``: ``rma.empresa`` tiene el horario y el pie;
  ``rma.texto_legal`` tiene la version 1 (carga inicial, sin cambios) y la
  2 (P-04), que es la vigente.
- Administracion edita los datos de la empresa con auditoria (``EMPRESA``);
  otro rol no puede. Los comprobantes nuevos copian los datos nuevos; los
  emitidos antes conservan los suyos.
- Administracion publica una version nueva de los terminos con auditoria
  (``TEXTO_LEGAL``). Cada Comprobante de entrega y garantia guarda
  ``texto_legal_id`` de la version que uso y su copia; una version
  publicada no se modifica ni se borra.
"""

from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.storage.postgres.catalogos import (  # noqa: E402
    PostgresCatalogosRepository,
)
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

EMPRESA = {
    "nombre": "Rosario Tecno",
    "direccion": "Cordoba 1234, Rosario",
    "telefono": "341-555-0100",
    "horario": "Lunes a viernes de 9 a 18",
    "pie_comprobante": "Gracias por elegirnos.",
}


@pytest.fixture
def cliente_pg(api):
    app, cliente = api
    contexto = app.state.contexto
    unidad = contexto.unidad_de_trabajo
    app.state.contexto = replace(
        contexto,
        catalogos=PostgresCatalogosRepository(unidad),
        operativa=PostgresConfiguracionOperativa(unidad),
    )
    return cliente


def _lista_y_pagada(cliente) -> str:
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    it.pagar(cliente, orden_id, "80000")
    return orden_id


def _entregar(cliente, orden_id) -> dict:
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": f.RECEPCION, "checkin": True},
        )
    )


def _comprobante(cliente, orden_id) -> dict:
    (documento,) = [
        d
        for d in f.ok(cliente.get(f"/api/orders/{orden_id}/documents"))[
            "emitidos"
        ]
        if d["tipo"] == "COMPROBANTE_ENTREGA"
    ]
    return documento["contenido"]


def _version_del_documento(url, orden_id):
    return _sql(
        url,
        "select t.version from rma.documento_emitido d "
        "join rma.orden o on o.id = d.orden_id "
        "left join rma.texto_legal t on t.id = d.texto_legal_id "
        "where o.codigo = %s and d.tipo = 'COMPROBANTE_ENTREGA'",
        (orden_id,),
    )


def _empresa(cliente, usuario=f.ADMINISTRADOR, **datos):
    return cliente.put(
        "/api/admin/company", json={"usuario_id": usuario, **datos}
    )


def _publicar(cliente, contenido, usuario=f.ADMINISTRADOR, titulo="T Y C"):
    return cliente.post(
        "/api/admin/terms",
        json={"usuario_id": usuario, "titulo": titulo, "contenido": contenido},
    )


def test_la_migracion_agrega_el_horario_el_pie_y_la_version_2(base):
    assert _sql(
        base,
        "select column_name from information_schema.columns "
        "where table_schema = 'rma' and table_name = 'empresa' "
        "and column_name in ('horario', 'pie_comprobante') "
        "order by column_name",
    ) == [("horario",), ("pie_comprobante",)]
    versiones = _sql(
        base,
        "select version, contenido -> 'apartados' -> 0 -> 'lineas' ->> 0 "
        "from rma.texto_legal order by version",
    )
    assert [v for v, _ in versiones] == [1, 2]
    assert "180 días" in versiones[0][1]
    assert "180" not in versiones[1][1]


def test_administracion_edita_la_empresa_con_auditoria(cliente_pg, base):
    antes = _lista_y_pagada(cliente_pg)
    _entregar(cliente_pg, antes)
    assert _comprobante(cliente_pg, antes)["empresa"]["horario"] is None

    f.conflicto(_empresa(cliente_pg, f.RECEPCION, **EMPRESA))
    empresa = f.ok(_empresa(cliente_pg, **EMPRESA))
    assert empresa["horario"] == "Lunes a viernes de 9 a 18"
    assert "no hay cambios" in f.conflicto(_empresa(cliente_pg, **EMPRESA))
    assert "nombre comercial" in f.conflicto(
        _empresa(cliente_pg, **{**EMPRESA, "nombre": " "})
    )
    leida = f.ok(cliente_pg.get("/api/admin/company"))
    assert leida["editable"] is True
    assert leida["empresa"] == empresa
    assert _sql(
        base,
        "select clave, campo, valor_anterior, valor_nuevo "
        "from rma.cambio_configuracion where entidad = 'EMPRESA' "
        "order by secuencia",
    ) == [
        ("EMPRESA", "direccion", None, "Cordoba 1234, Rosario"),
        ("EMPRESA", "telefono", None, "341-555-0100"),
        ("EMPRESA", "horario", None, "Lunes a viernes de 9 a 18"),
        ("EMPRESA", "pie_comprobante", None, "Gracias por elegirnos."),
    ]

    # Los comprobantes nuevos copian los datos; el emitido antes, no.
    despues = _lista_y_pagada(cliente_pg)
    _entregar(cliente_pg, despues)
    nuevo = _comprobante(cliente_pg, despues)["empresa"]
    assert (nuevo["horario"], nuevo["pie_comprobante"]) == (
        "Lunes a viernes de 9 a 18",
        "Gracias por elegirnos.",
    )
    assert _comprobante(cliente_pg, antes)["empresa"]["horario"] is None


def test_cada_comprobante_guarda_la_version_de_los_terminos(cliente_pg, base):
    vigentes = f.ok(cliente_pg.get("/api/admin/terms"))
    assert vigentes["editable"] is True
    assert vigentes["vigente"]["version"] == 2
    assert [v["version"] for v in vigentes["versiones"]] == [1, 2]

    primera = _lista_y_pagada(cliente_pg)
    _entregar(cliente_pg, primera)
    assert _version_del_documento(base, primera) == [(2,)]
    assert _comprobante(cliente_pg, primera)["terminos"]["version"] == 2

    contenido = vigentes["vigente"]["contenido"]
    contenido["apartados"][0]["lineas"] = ["Texto de la version 3."]
    f.conflicto(_publicar(cliente_pg, contenido, usuario=f.RECEPCION))
    publicada = f.ok(_publicar(cliente_pg, contenido))
    assert (publicada["version"], publicada["publicado_por"]) == (
        3,
        f.ADMINISTRADOR,
    )
    assert "no hay cambios" in f.conflicto(_publicar(cliente_pg, contenido))
    assert f.ok(cliente_pg.get("/api/admin/terms"))["vigente"]["version"] == 3
    assert _sql(
        base,
        "select clave, campo, valor_anterior, valor_nuevo "
        "from rma.cambio_configuracion where entidad = 'TEXTO_LEGAL'",
    ) == [("TERMINOS_CONDICIONES_ENTREGA", "version", "2", "3")]

    segunda = _lista_y_pagada(cliente_pg)
    _entregar(cliente_pg, segunda)
    assert _version_del_documento(base, segunda) == [(3,)]
    terminos = _comprobante(cliente_pg, segunda)["terminos"]
    assert terminos["contenido"]["apartados"][0]["lineas"] == [
        "Texto de la version 3."
    ]
    # El comprobante anterior sigue con su version.
    assert _version_del_documento(base, primera) == [(2,)]
    assert _comprobante(cliente_pg, primera)["terminos"]["version"] == 2

    # Una version usada no se modifica ni se borra.
    for sentencia in (
        "update rma.texto_legal set titulo = 'x' where version = 2",
        "delete from rma.texto_legal where version = 2",
    ):
        with pytest.raises(psycopg.Error):
            _sql(base, sentencia)
