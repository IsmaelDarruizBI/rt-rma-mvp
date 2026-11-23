"""Bloque 3 de ajustes funcionales (ingreso) sobre PostgreSQL.

- Migracion ``20261123000200``: ``rma.recepcion`` guarda el trabajo
  solicitado (DEC-AJ-05), la verificacion del ingreso con sus
  observaciones (DEC-AJ-07) y la marca «IMEI no disponible» (DEC-AJ-06), y
  sus versiones las conservan; se releen igual.
- DEC-AJ-05: el comprobante de recepcion confirma la custodia en la misma
  operacion; la fila de la recepcion queda decidida.
- DEC-AJ-06: el IMEI real se registra con la custodia confirmada sin
  tocar ``rma.recepcion`` (el trigger la protege): actualiza el equipo y la
  copia de la Orden, y su auditoria es una fila de
  ``rma.recepcion_version``. El paso queda como «Datos del ingreso
  corregidos» (EV-REP-002), sin el IMEI en la observacion.
"""

import pytest

pytest.importorskip("psycopg_pool")

from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api

IMEI_REAL = "356789012345678"
TRABAJO = "Cambiar la bateria."


def _crear(cliente, **recepcion) -> dict:
    return f.ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": f.RECEPCION,
                "cliente": {
                    "nombre_apellido": "Ana Gomez",
                    "telefono": "341-555",
                },
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 13",
                    "falla_reportada": "No carga.",
                },
                "recepcion": {
                    "observaciones": "No carga.",
                    "observaciones_unificadas": True,
                    "trabajo_solicitado": TRABAJO,
                    "funcionalidades_verificadas": False,
                    "observaciones_verificacion": "No enciende.",
                    "imei_no_disponible": True,
                    **recepcion,
                },
            },
        )
    )


def _recepcion(url, orden_id):
    return _sql(
        url,
        "select r.trabajo_solicitado, r.funcionalidades_verificadas, "
        "r.observaciones_verificacion, r.imei_no_disponible, "
        "r.checkin_ingreso, r.confirmada_en is not null "
        "from rma.recepcion r join rma.orden o on o.id = r.orden_id "
        "where o.codigo = %s",
        (orden_id,),
    )


def test_datos_nuevos_del_ingreso_se_guardan_y_se_releen(api, base):
    _, cliente = api
    orden = _crear(cliente)
    orden_id = orden["id"]

    assert _recepcion(base, orden_id) == [
        (TRABAJO, False, "No enciende.", True, None, False)
    ]
    # Una correccion antes de recibir el equipo los conserva en la version.
    corregida = f.ok(
        cliente.put(
            f"/api/orders/{orden_id}/reception",
            json={
                "usuario_id": f.RECEPCION,
                "observaciones": "No carga.",
                "observaciones_unificadas": True,
                "funcionalidades_verificadas": True,
                "motivo": "Se verifico despues.",
            },
        )
    )
    leida = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert leida["recepcion"] == corregida["recepcion"]
    version = leida["recepcion"]["versiones_anteriores"][-1]
    assert version["datos"]["funcionalidades_verificadas"] is False
    assert version["datos"]["trabajo_solicitado"] == TRABAJO
    assert leida["recepcion"]["datos"]["trabajo_solicitado"] == TRABAJO


def test_recepcion_con_custodia_e_imei_real_despues(api, base):
    _, cliente = api
    orden = _crear(cliente)
    orden_id, equipo_id = orden["id"], orden["equipo"]["id"]

    enviada = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/send-to-review",
            json={"usuario_id": f.RECEPCION},
        )
    )
    assert enviada["custodia"]["estado"] == "EN_CUSTODIA"
    assert _recepcion(base, orden_id)[0][-1] is True

    registrada = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/real-imei",
            json={
                "usuario_id": f.RECEPCION,
                "imei": IMEI_REAL,
                "motivo": "Trajo la caja.",
            },
        )
    )

    leida = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert leida["equipo"] == registrada["equipo"]
    assert leida["equipo"]["imei"] == IMEI_REAL
    assert leida["equipo"]["id"] == equipo_id
    assert leida["recepcion"] == registrada["recepcion"]
    assert leida["historial"] == registrada["historial"]
    version = leida["recepcion"]["versiones_anteriores"][-1]
    assert version["motivo"] == "Trajo la caja."
    assert version["cambios"] == [
        {"campo": "equipo.imei", "anterior": None, "nuevo": IMEI_REAL}
    ]
    # El equipo y la copia de la Orden tienen el IMEI; la fila de la
    # recepcion, decidida, no cambio.
    assert _sql(
        base,
        "select e.imei, o.equipo_imei from rma.orden o "
        "join rma.equipo e on e.id = o.equipo_id where o.codigo = %s",
        (orden_id,),
    ) == [(IMEI_REAL, IMEI_REAL)]
    assert _recepcion(base, orden_id) == [
        (TRABAJO, False, "No enciende.", True, None, True)
    ]
    ((tipo, observacion),) = _sql(
        base,
        "select t.codigo, e.observacion from rma.evento_negocio e "
        "join rma.tipo_evento t on t.id = e.tipo_evento_id "
        "join rma.orden o on o.id = e.orden_id "
        "where o.codigo = %s and e.historial_accion = 'REGISTRAR_IMEI_REAL'",
        (orden_id,),
    )
    assert tipo == "EV-REP-002"
    assert IMEI_REAL not in observacion
