"""Idempotencia de los comandos que crean registros (E6, slice B1).

Por HTTP, con la API apuntando a PostgreSQL solo en la prueba (el contexto
de la app se reemplaza; la aplicacion no se activa). Semantica:

- Sin clave, nada cambia.
- Un reintento con la misma clave y los mismos datos devuelve exactamente
  la misma respuesta (codigo y cuerpo) sin ejecutar nada: un solo pago, un
  solo movimiento.
- La misma clave con otros datos: 422 ``CLAVE_REUTILIZADA``, sin escribir.
- Dos solicitudes simultaneas con la misma clave: una ejecuta y la otra
  recibe la respuesta de la primera.
- Un fallo antes del COMMIT no deja nada, tampoco la accion: el reintento
  con la misma clave ejecuta.
- Un rechazo funcional queda RECHAZADO para auditoria y no bloquea.
- La accion con clave es la del comando: sus eventos la referencian.
- Reservas y consumos (transiciones de estado) no se duplican.

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (secciones 6 y 20).
"""

import threading
import time
from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

from fastapi.testclient import TestClient  # noqa: E402

from app.api import ordenes as api_ordenes  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.storage.postgres.acciones import (  # noqa: E402
    PostgresRegistroDeAcciones,
)
from app.storage.postgres.catalogos import (  # noqa: E402
    PostgresCatalogosRepository,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla

CLAVE = "Idempotency-Key"


@pytest.fixture
def api(armar, tmp_path):
    f.sembrar(tmp_path)
    app = create_app(Settings(data_dir=tmp_path, fotos_dir=tmp_path / "fotos"))
    repo, unidad = armar(pool_max=6)
    app.state.contexto = replace(
        app.state.contexto,
        ordenes=repo,
        catalogos=PostgresCatalogosRepository(unidad),
        unidad_de_trabajo=unidad,
        acciones=PostgresRegistroDeAcciones(unidad),
    )
    with TestClient(app) as cliente:
        yield app, cliente


def _pago(monto="1000", usuario=f.RECEPCION):
    return {"usuario_id": usuario, "monto": monto, "metodo": "EFECTIVO"}


def _pagar(cliente, orden_id, clave=None, **datos):
    encabezados = {CLAVE: clave} if clave else {}
    return cliente.post(
        f"/api/orders/{orden_id}/payments",
        json=_pago(**datos),
        headers=encabezados,
    )


def _pagos(base):
    return _sql(base, "select count(*) from rma.pago")[0][0]


def _acciones(base, clave):
    return _sql(
        base,
        "select resultado, operacion from rma.accion_usuario "
        "where clave_idempotencia = %s order by registrada_en",
        (clave,),
    )


def _version(base, orden_id):
    return _sql(
        base, "select version from rma.orden where codigo = %s", (orden_id,)
    )[0][0]


# --- Reintentos -----


def test_b1_sin_clave_nada_cambia(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    for _ in range(2):
        f.ok(_pagar(cliente, orden_id))
    assert _pagos(base) == 2
    assert _sql(
        base,
        "select count(*) from rma.accion_usuario "
        "where clave_idempotencia is not null",
    ) == [(0,)]


def test_b1_un_reintento_devuelve_lo_mismo_sin_repetir(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    primera = _pagar(cliente, orden_id, "pago-1")
    version = _version(base, orden_id)
    segunda = _pagar(cliente, orden_id, "pago-1")
    assert primera.status_code == segunda.status_code == 200
    assert segunda.json() == primera.json()
    assert _pagos(base) == 1
    assert _version(base, orden_id) == version
    assert _acciones(base, "pago-1") == [("CONFIRMADA", "REGISTRAR_PAGO")]


def test_b1_la_respuesta_es_la_misma_que_sin_clave(api, base):
    """Con clave, el cuerpo es el que la API devuelve sin ella."""
    _, cliente = api
    con = cliente.post(
        "/api/orders",
        json={
            "usuario_id": f.RECEPCION,
            "cliente": {"nombre_apellido": "Ana", "telefono": "341"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "No carga.",
            },
        },
        headers={CLAVE: "alta-1"},
    )
    assert con.status_code == 201
    sin = cliente.get(f"/api/orders/{con.json()['id']}")
    assert con.json() == sin.json()
    repetida = cliente.post(
        "/api/orders",
        json={
            "usuario_id": f.RECEPCION,
            "cliente": {"nombre_apellido": "Ana", "telefono": "341"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "No carga.",
            },
        },
        headers={CLAVE: "alta-1"},
    )
    assert repetida.status_code == 201 and repetida.json() == con.json()
    assert _sql(base, "select count(*) from rma.orden") == [(1,)]


def test_b1_otra_operacion_con_la_misma_clave_es_un_422(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    f.ok(_pagar(cliente, orden_id, "pago-2"))
    version = _version(base, orden_id)
    otra = _pagar(cliente, orden_id, "pago-2", monto="2000")
    assert otra.status_code == 422
    assert otra.json()["error"]["codigo"] == "CLAVE_REUTILIZADA"
    nota = cliente.post(
        f"/api/orders/{orden_id}/reception/notes",
        json={"usuario_id": f.RECEPCION, "texto": "Hola."},
        headers={CLAVE: "pago-2"},
    )
    assert nota.status_code == 422
    assert _pagos(base) == 1
    assert _version(base, orden_id) == version


def test_b1_la_clave_es_de_cada_usuario(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    f.ok(_pagar(cliente, orden_id, "misma"))
    f.ok(_pagar(cliente, orden_id, "misma", usuario=f.ADMINISTRADOR))
    assert _pagos(base) == 2


# --- Concurrencia -----


def test_b1_dos_solicitudes_simultaneas_ejecutan_una_vez(
    api, base, monkeypatch
):
    """La primera queda en curso un momento; la segunda espera en el
    indice unico y recibe la respuesta de la primera."""
    app, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    original = api_ordenes.registrar_pago_de_orden

    def lento(*argumentos, **nombrados):
        resultado = original(*argumentos, **nombrados)
        time.sleep(0.5)
        return resultado

    monkeypatch.setattr(api_ordenes, "registrar_pago_de_orden", lento)
    barrera = threading.Barrier(2)
    respuestas = []

    def enviar():
        otro = TestClient(app)
        barrera.wait(10)
        respuestas.append(_pagar(otro, orden_id, "simultanea"))

    hilos = [threading.Thread(target=enviar) for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert [r.status_code for r in respuestas] == [200, 200]
    assert respuestas[0].json() == respuestas[1].json()
    assert _pagos(base) == 1
    assert _acciones(base, "simultanea") == [("CONFIRMADA", "REGISTRAR_PAGO")]


# --- Fallos y rechazos -----


def test_b1_un_fallo_antes_del_commit_no_deja_nada(api, base, monkeypatch):
    """El pago se guardo y falla armar la respuesta: se revierte todo,
    tambien la accion con la clave. El reintento ejecuta."""
    app, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    version = _version(base, orden_id)

    def falla(*argumentos, **nombrados):
        raise RuntimeError("fallo despues de guardar")

    with monkeypatch.context() as parche:
        parche.setattr(api_ordenes, "_salida_con_entrega", falla)
        with pytest.raises(RuntimeError):
            _pagar(cliente, orden_id, "falla-1")
    assert _pagos(base) == 0
    assert _version(base, orden_id) == version
    assert _acciones(base, "falla-1") == []
    f.ok(_pagar(cliente, orden_id, "falla-1"))
    assert _pagos(base) == 1


def test_b1_un_rechazo_queda_registrado_y_no_bloquea(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    rechazo = _pagar(cliente, orden_id, "excede", monto="999999")
    assert rechazo.status_code == 409
    assert _pagos(base) == 0
    assert [r for r, _ in _acciones(base, "excede")] == ["RECHAZADA"]
    # Nada se confirmo con esa clave: otro intento con ella ejecuta.
    f.ok(_pagar(cliente, orden_id, "excede"))
    assert _pagos(base) == 1
    assert [r for r, _ in _acciones(base, "excede")] == [
        "RECHAZADA",
        "CONFIRMADA",
    ]


def test_b1_la_accion_con_clave_es_la_del_comando(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    f.ok(_pagar(cliente, orden_id, "trazada"))
    assert _sql(
        base,
        "select count(distinct e.accion_id), min(a.clave_idempotencia), "
        "min(o.codigo) from rma.evento_negocio e "
        "join rma.accion_usuario a on a.id = e.accion_id "
        "left join rma.orden o on o.id = a.orden_id "
        "where a.clave_idempotencia = 'trazada'",
    ) == [(1, "trazada", orden_id)]


# --- Inventario -----


def test_b1_un_ingreso_reintentado_entra_una_vez(api, base):
    _, cliente = api
    cuerpo = {
        "usuario_id": f.COORDINADOR,
        "cantidad": "3",
        "motivo": "Compra",
    }
    ruta = f"/api/inventory/{f.INSUMO_BATERIA}/receipts"
    primera = cliente.post(ruta, json=cuerpo, headers={CLAVE: "ing-1"})
    fisico = _sql(
        base,
        "select stock_fisico from rma.insumo where clave = %s",
        (f.INSUMO_BATERIA,),
    )
    segunda = cliente.post(ruta, json=cuerpo, headers={CLAVE: "ing-1"})
    assert segunda.json() == primera.json()
    assert (
        _sql(
            base,
            "select stock_fisico from rma.insumo where clave = %s",
            (f.INSUMO_BATERIA,),
        )
        == fisico
    )
    assert _sql(
        base,
        "select count(*) from rma.movimiento_inventario "
        "where tipo = 'INGRESO' and usuario_id is not null",
    ) == [(1,)]


def test_b1_reservas_y_consumos_no_se_duplican(api, base):
    """Transiciones de estado: el reintento recibe 409 y no escribe."""
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    ejecucion = f.iniciar(cliente, orden_id)
    repetida = cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/start",
        json={"usuario_id": f.TECNICO},
    )
    assert repetida.status_code == 409
    f.ok(f.cerrar_ejecucion(cliente, orden_id, ejecucion))
    otra_vez = f.cerrar_ejecucion(cliente, orden_id, ejecucion)
    assert otra_vez.status_code == 409
    assert _sql(
        base,
        "select tipo, count(*) from rma.movimiento_inventario "
        "where orden_id is not null group by tipo order by tipo",
    ) == [("CONSUMO", 1), ("RESERVA", 1)]
    assert _sql(base, "select * from rma.verificar_integridad()") == []


def test_b1_json_ignora_la_clave(tmp_path):
    """JSON no registra acciones: el encabezado se acepta y no cambia
    nada (B1-2)."""
    f.sembrar(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as cliente:
        orden_id = f.definida(cliente, f.BATERIA)
        f.ok(_pagar(cliente, orden_id, "json"))
        assert f.ok(cliente.get(f"/api/orders/{orden_id}"))


# --- B2: COMMIT incierto -----


def _commit_perdido(monkeypatch, confirmar):
    """El proximo COMMIT de un comando: se confirma (o no) y la conexion
    se pierde antes de la respuesta."""
    import psycopg

    from app.storage.postgres import transaccion

    original = transaccion._enviar_commit
    usado = []

    def perdido(conexion):
        if usado:
            return original(conexion)
        usado.append(1)
        if confirmar:
            original(conexion)
        else:
            conexion.rollback()
        raise psycopg.errors.ConnectionFailure("se perdio la conexion")

    monkeypatch.setattr(transaccion, "_enviar_commit", perdido)


def test_b2_confirmado_con_clave_devuelve_la_respuesta(api, base, monkeypatch):
    """El COMMIT llego: con otra conexion se encuentra la accion y se
    devuelve su respuesta. El reintento devuelve lo mismo."""
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    _commit_perdido(monkeypatch, confirmar=True)
    respuesta = _pagar(cliente, orden_id, "incierto-1")
    assert respuesta.status_code == 200
    assert _pagos(base) == 1
    assert _pagar(cliente, orden_id, "incierto-1").json() == respuesta.json()
    assert _pagos(base) == 1


def test_b2_sin_confirmar_no_se_afirma_nada(api, base, monkeypatch):
    """El COMMIT no llego: no aparece la accion y la respuesta es 503
    incierto. El reintento con la misma clave ejecuta una vez."""
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    _commit_perdido(monkeypatch, confirmar=False)
    respuesta = _pagar(cliente, orden_id, "incierto-2")
    assert respuesta.status_code == 503
    assert respuesta.json()["error"]["codigo"] == (
        "PERSISTENCIA_RESULTADO_INCIERTO"
    )
    assert _pagos(base) == 0
    f.ok(_pagar(cliente, orden_id, "incierto-2"))
    f.ok(_pagar(cliente, orden_id, "incierto-2"))
    assert _pagos(base) == 1


def test_b2_sin_clave_el_incierto_no_dice_que_fallo(api, base, monkeypatch):
    """Sin clave no hay como saberlo: 503, aunque se haya guardado. Nunca
    un 500 ni un exito afirmado."""
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    _commit_perdido(monkeypatch, confirmar=True)
    respuesta = _pagar(cliente, orden_id)
    assert respuesta.status_code == 503
    assert respuesta.json()["error"]["codigo"] == (
        "PERSISTENCIA_RESULTADO_INCIERTO"
    )
    assert _pagos(base) == 1


# --- Fotos (B1-1) -----

JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\x00" * 200


def _foto(cliente, orden_id, clave, contenido=JPEG):
    return cliente.post(
        f"/api/orders/{orden_id}/photos",
        params={"usuario_id": f.RECEPCION},
        content=contenido,
        headers={CLAVE: clave},
    )


def test_b1_una_foto_reintentada_se_sube_una_vez(api, base, tmp_path):
    _, cliente = api
    orden_id = f.crear(cliente)
    primera = _foto(cliente, orden_id, "foto-1")
    segunda = _foto(cliente, orden_id, "foto-1")
    assert primera.status_code == segunda.status_code == 200
    assert segunda.json() == primera.json()
    assert _sql(base, "select count(*) from rma.foto") == [(1,)]
    objetos = [p for p in (tmp_path / "fotos").rglob("*") if p.is_file()]
    assert len(objetos) == 1
    otra = _foto(cliente, orden_id, "foto-1", JPEG + b"\x01")
    assert otra.status_code == 422
    assert _sql(base, "select count(*) from rma.foto") == [(1,)]


def test_b1_una_nota_reintentada_se_agrega_una_vez(api, base):
    _, cliente = api
    orden_id = f.crear(cliente)
    ruta = f"/api/orders/{orden_id}/reception/notes"
    cuerpo = {"usuario_id": f.RECEPCION, "texto": "Llamar al cliente."}
    primera = cliente.post(ruta, json=cuerpo, headers={CLAVE: "nota-1"})
    segunda = cliente.post(ruta, json=cuerpo, headers={CLAVE: "nota-1"})
    assert primera.status_code == segunda.status_code == 200
    assert segunda.json() == primera.json()
    assert _sql(base, "select count(*) from rma.recepcion_nota") == [(1,)]
