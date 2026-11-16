"""UX-02 sobre PostgreSQL: identificador interno del Equipo sin IMEI.

- Altas simultaneas sin IMEI ni serie crean identidades distintas, cada
  una con su codigo ``EQP-…`` unico; ninguna recibe un IMEI.
- La base rechaza un codigo de Equipo repetido (``equipo.codigo`` unico).
- Asociar despues el IMEI real conserva el identificador.
"""

import threading

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402
from tests.test_identidad_equipo import _ingresar  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api

SIMULTANEAS = 5


def test_altas_simultaneas_sin_imei_tienen_identificadores_unicos(api, base):
    _, cliente = api
    barrera = threading.Barrier(SIMULTANEAS)
    respuestas: list = [None] * SIMULTANEAS

    def alta(indice: int) -> None:
        barrera.wait()
        respuestas[indice] = _ingresar(cliente)

    hilos = [
        threading.Thread(target=alta, args=(i,)) for i in range(SIMULTANEAS)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    ordenes_creadas = [f.ok(r) for r in respuestas]
    equipos = {o["equipo"]["id"] for o in ordenes_creadas}
    assert len(equipos) == SIMULTANEAS
    assert all(e.startswith("EQP-") for e in equipos)
    assert _sql(
        base,
        "select count(*), count(distinct codigo), count(imei) "
        "from rma.equipo where codigo = any(%s)",
        (list(equipos),),
    ) == [(SIMULTANEAS, SIMULTANEAS, 0)]


def test_la_base_no_admite_un_identificador_repetido(api, base):
    _, cliente = api
    equipo_id = f.ok(_ingresar(cliente))["equipo"]["id"]
    with (
        pytest.raises(psycopg.errors.UniqueViolation),
        psycopg.connect(base) as conexion,
    ):
        conexion.execute(
            "insert into rma.equipo (codigo) "
            "select codigo from rma.equipo where codigo = %s",
            (equipo_id,),
        )


def test_el_imei_real_se_asocia_despues(api, base):
    _, cliente = api
    orden = f.ok(_ingresar(cliente))
    equipo_id = orden["equipo"]["id"]
    corregida = f.ok(
        cliente.put(
            f"/api/orders/{orden['id']}/reception",
            json={
                "usuario_id": f.RECEPCION,
                "estado_fisico": "Rayon en la tapa.",
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 14",
                    "falla_reportada": "No carga.",
                    "imei": "356789012345678",
                },
            },
        )
    )
    assert corregida["equipo"]["id"] == equipo_id
    assert _sql(
        base,
        "select imei from rma.equipo where codigo = %s",
        (equipo_id,),
    ) == [("356789012345678",)]
