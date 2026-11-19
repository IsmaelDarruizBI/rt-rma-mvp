# ruff: noqa: E501  (SQL)
"""Configuracion v2, CFG-06 (DF-1 y DF-2): la pantalla de Tipos muestra solo
los plazos con y sin check-in.

- Alta sin el plazo generico (el que rige sin check-in registrado: RT
  interno, garantia RMA y el provisorio): toma el plazo con check-in. Sin
  plazos: 90 y 30 dias, como antes. La politica RMA queda sin definir.
- Edicion sin esos campos: se conservan los valores del Tipo (DF-1: no se
  pisan los existentes; DF-2: la politica RMA se conserva).
- Un cliente anterior que manda todo se respeta.
- Lo historico no cambia: las versiones de definicion guardan su copia.
"""

from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

from app.storage.postgres.catalogos import (  # noqa: E402
    PostgresCatalogosRepository,
)
from app.storage.postgres.configuracion import (  # noqa: E402
    PostgresConfiguracionRepository,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

pytestmark = pytest.mark.postgres

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api


@pytest.fixture
def cliente(api):
    app, cliente = api
    contexto = app.state.contexto
    unidad = contexto.unidad_de_trabajo
    app.state.contexto = replace(
        contexto,
        configuracion=PostgresConfiguracionRepository(unidad),
        catalogos=PostgresCatalogosRepository(unidad),
    )
    return cliente


def _alta(cliente, **campos):
    return f.ok(
        cliente.post(
            "/api/admin/repair-types",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Cambio de pin de carga",
                "precio": "30000",
                "puntaje": 3,
                **campos,
            },
        )
    )


def _plazos(base, codigo):
    return _sql(
        base,
        "select garantia_dias, garantia_con_checkin, garantia_sin_checkin, politica_garantia_rma"
        " from rma.tipo_reparacion where codigo = %s",
        (codigo,),
    )[0]


def test_alta_sin_el_plazo_generico_toma_el_de_con_checkin(cliente, base):
    solo_check_in = _alta(
        cliente, garantia_con_checkin=120, garantia_sin_checkin=45
    )
    assert _plazos(base, solo_check_in["id"]) == (120, 120, 45, None)
    sin_plazos = _alta(cliente)
    assert _plazos(base, sin_plazos["id"]) == (90, 90, 30, None)
    # Cliente anterior: manda el plazo generico y la politica.
    anterior = _alta(
        cliente,
        garantia_dias=60,
        garantia_con_checkin=90,
        garantia_sin_checkin=30,
        politica_garantia_rma="PLAZO_RESTANTE",
    )
    assert _plazos(base, anterior["id"]) == (60, 90, 30, "PLAZO_RESTANTE")


def test_la_edicion_conserva_lo_que_la_pantalla_no_muestra(cliente, base):
    tipo = _alta(
        cliente,
        garantia_dias=60,
        garantia_con_checkin=90,
        garantia_sin_checkin=30,
        politica_garantia_rma="SIN_GARANTIA",
    )["id"]
    # La pantalla nueva manda solo los plazos con y sin check-in.
    f.ok(
        cliente.put(
            f"/api/admin/repair-types/{tipo}",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Cambio de pin de carga USB-C",
                "precio": "30000",
                "puntaje": 3,
                "garantia_con_checkin": 180,
                "garantia_sin_checkin": 60,
            },
        )
    )
    assert _plazos(base, tipo) == (60, 180, 60, "SIN_GARANTIA")
    # La auditoria registra solo lo que cambio.
    campos = {
        r[0]
        for r in _sql(
            base,
            "select campo from rma.cambio_configuracion where entidad = 'TIPO_REPARACION'"
            " and clave = %s and valor_anterior is not null",
            (tipo,),
        )
    }
    assert campos == {"nombre", "garantia_con_checkin", "garantia_sin_checkin"}
    # Un cliente anterior puede seguir cambiando la politica, y null es
    # «sin definir», como antes.
    f.ok(
        cliente.put(
            f"/api/admin/repair-types/{tipo}",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Cambio de pin de carga USB-C",
                "precio": "30000",
                "puntaje": 3,
                "politica_garantia_rma": None,
            },
        )
    )
    assert _plazos(base, tipo) == (60, 180, 60, None)


def test_los_tipos_existentes_no_cambian(cliente, base):
    antes = _sql(
        base,
        "select codigo, garantia_dias, garantia_con_checkin, garantia_sin_checkin,"
        " politica_garantia_rma from rma.tipo_reparacion order by codigo",
    )
    _alta(cliente)
    despues = {
        fila[0]: fila
        for fila in _sql(
            base,
            "select codigo, garantia_dias, garantia_con_checkin, garantia_sin_checkin,"
            " politica_garantia_rma from rma.tipo_reparacion order by codigo",
        )
    }
    for fila in antes:
        assert despues[fila[0]] == fila


def test_editar_un_tipo_no_cambia_los_detalles_ya_definidos(cliente, base):
    # QA C, menor 3: el Detalle guardo su copia de los plazos al definirse.
    orden_id = f.definida(cliente)
    copia = """
        select dv.garantia_dias, d.garantia_con_checkin, d.garantia_sin_checkin
          from rma.detalle d
          join rma.orden o on o.id = d.orden_id
          join rma.detalle_version dv on dv.detalle_id = d.id
         where o.codigo = %s
    """
    antes = _sql(base, copia, (orden_id,))
    assert antes
    f.ok(
        cliente.put(
            f"/api/admin/repair-types/{f.BATERIA}",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Cambio de bateria",
                "precio": "80000",
                "puntaje": 10,
                "garantia_con_checkin": 200,
                "garantia_sin_checkin": 77,
            },
        )
    )
    assert _sql(base, copia, (orden_id,)) == antes
    # El Tipo cambio; su plazo generico se conservo (DF-1).
    assert _plazos(base, f.BATERIA)[1:3] == (200, 77)
