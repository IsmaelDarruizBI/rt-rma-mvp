"""Fotos del equipo (UAT-010).

Opcionales, de cualquier usuario operativo, con quien y cuando; la imagen
va a un almacenamiento de objetos (en los tests, en memoria), nunca al
JSON de la Orden. Sin almacenamiento configurado, quedan deshabilitadas.
El adaptador de Google Cloud Storage se prueba contra HTTP simulado: no
hay un bucket real todavia.
"""

import io
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import FotoOrden
from app.main import create_app
from app.services import MAX_FOTOS_POR_ORDEN, tipo_de_imagen
from app.storage import (
    AlmacenFotosDirectorio,
    AlmacenFotosError,
    AlmacenFotosGcs,
    AlmacenFotosMemoria,
)
from tests.fixtures.api_salidas import (
    BATERIA,
    COORDINADOR,
    RECEPCION,
    TECNICO,
    archivo,
    conflicto,
    notificar_pagar_entregar,
    ok,
    repo_ordenes,
    sembrar,
)
from tests.fixtures.ingreso_inicial import ingresada
from tests.test_garantia_checkin import _lista

JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 100


class AlmacenQueFalla(AlmacenFotosMemoria):
    def guardar(self, clave, contenido, tipo):
        raise AlmacenFotosError("sin conexion")


@pytest.fixture
def armar(tmp_path):
    sembrar(tmp_path, "10")
    clientes = []

    def _armar(almacen=None):
        app = create_app(Settings(data_dir=tmp_path))
        app.state.contexto = replace(app.state.contexto, fotos=almacen)
        cliente = TestClient(app)
        clientes.append(cliente)
        return cliente

    yield _armar
    for cliente in clientes:
        cliente.close()


def _subir(cliente, orden_id, contenido=JPEG, usuario=RECEPCION, **extra):
    return cliente.post(
        f"/api/orders/{orden_id}/photos",
        params={"usuario_id": usuario, **extra},
        content=contenido,
        headers={"Content-Type": "application/octet-stream"},
    )


# --- Deshabilitadas sin almacenamiento ------------------------------------


def test_sin_almacenamiento_las_fotos_estan_deshabilitadas(armar, tmp_path):
    cliente = armar(almacen=None)
    orden_id = ingresada(cliente, BATERIA)
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    assert orden["fotos_habilitadas"] is False and orden["fotos"] == []
    antes = archivo(tmp_path, orden_id)

    assert "no están habilitadas" in conflicto(_subir(cliente, orden_id))
    assert archivo(tmp_path, orden_id) == antes


# --- Subir y consultar -----------------------------------------------------


def test_subir_varias_fotos_con_quien_y_cuando(armar, tmp_path):
    almacen = AlmacenFotosMemoria()
    cliente = armar(almacen)
    orden_id = ingresada(cliente, BATERIA)

    ok(_subir(cliente, orden_id, JPEG, RECEPCION, nombre="frente.jpg"))
    orden = ok(_subir(cliente, orden_id, PNG, TECNICO))

    assert orden["fotos_habilitadas"] is True
    primera, segunda = orden["fotos"]
    assert primera["usuario_id"] == RECEPCION
    assert primera["tipo_contenido"] == "image/jpeg"
    assert primera["tamano_bytes"] == len(JPEG)
    assert primera["nombre_original"] == "frente.jpg"
    assert primera["fecha"]
    assert (segunda["usuario_id"], segunda["tipo_contenido"]) == (
        TECNICO,
        "image/png",
    )
    # La clave interna del almacenamiento no se expone.
    assert "objeto" not in primera
    # La imagen esta en el almacenamiento, no en el JSON de la Orden.
    assert sorted(almacen.objetos) == sorted(
        [
            f"ordenes/{orden_id}/{primera['id']}.jpg",
            f"ordenes/{orden_id}/{segunda['id']}.png",
        ]
    )
    assert JPEG.hex() not in archivo(tmp_path, orden_id).hex()
    guardada = json.loads(archivo(tmp_path, orden_id))["fotos"][0]
    assert guardada["objeto"].startswith(f"ordenes/{orden_id}/")

    imagen = cliente.get(f"/api/orders/{orden_id}/photos/{primera['id']}")
    assert imagen.status_code == 200
    assert imagen.content == JPEG
    assert imagen.headers["content-type"] == "image/jpeg"
    assert "private" in imagen.headers["cache-control"]


def test_todos_los_roles_operativos_pueden_subir(armar):
    cliente = armar(AlmacenFotosMemoria())
    orden_id = ingresada(cliente, BATERIA)

    for usuario in (RECEPCION, TECNICO, COORDINADOR, "ADMIN-001"):
        ok(_subir(cliente, orden_id, WEBP, usuario))

    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    assert [f["usuario_id"] for f in orden["fotos"]] == [
        RECEPCION,
        TECNICO,
        COORDINADOR,
        "ADMIN-001",
    ]


@pytest.mark.parametrize(
    ("contenido", "mensaje"),
    [
        (b"", "vacia"),
        (b"no es una imagen", "no es una imagen"),
        (b"GIF89a" + b"\x00" * 20, "no es una imagen"),
    ],
)
def test_rechaza_lo_que_no_es_una_imagen(armar, tmp_path, contenido, mensaje):
    almacen = AlmacenFotosMemoria()
    cliente = armar(almacen)
    orden_id = ingresada(cliente, BATERIA)
    antes = archivo(tmp_path, orden_id)

    assert mensaje in conflicto(_subir(cliente, orden_id, contenido))
    assert almacen.objetos == {}
    assert archivo(tmp_path, orden_id) == antes


def test_rechaza_una_foto_de_mas_de_8_mb(armar):
    almacen = AlmacenFotosMemoria()
    cliente = armar(almacen)
    orden_id = ingresada(cliente, BATERIA)

    grande = JPEG + b"\x00" * (8 * 1024 * 1024)
    assert "8 MB" in conflicto(_subir(cliente, orden_id, grande))
    assert almacen.objetos == {}


def test_tope_de_fotos_por_orden(armar, tmp_path):
    almacen = AlmacenFotosMemoria()
    cliente = armar(almacen)
    orden_id = ingresada(cliente, BATERIA)
    repo = repo_ordenes(tmp_path)
    orden = repo.obtener(orden_id)
    orden.fotos = [
        FotoOrden(
            id=f"FOT-{i}",
            objeto=f"ordenes/{orden_id}/FOT-{i}.jpg",
            tipo_contenido="image/jpeg",
            tamano_bytes=10,
            usuario_id=RECEPCION,
            fecha=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        for i in range(MAX_FOTOS_POR_ORDEN)
    ]
    repo.guardar(orden)

    assert "maximo" in conflicto(_subir(cliente, orden_id))
    assert almacen.objetos == {}


def test_si_el_almacenamiento_falla_no_se_registra_nada(armar, tmp_path):
    cliente = armar(AlmacenQueFalla())
    orden_id = ingresada(cliente, BATERIA)
    antes = archivo(tmp_path, orden_id)

    respuesta = _subir(cliente, orden_id)

    assert respuesta.status_code == 503
    assert respuesta.json()["error"]["codigo"] == (
        "ALMACENAMIENTO_NO_DISPONIBLE"
    )
    assert archivo(tmp_path, orden_id) == antes


def test_orden_cerrada_no_admite_fotos_pero_se_consultan(armar):
    cliente = armar(AlmacenFotosMemoria())
    orden_id = ingresada(cliente, BATERIA)
    foto_id = ok(_subir(cliente, orden_id))["fotos"][0]["id"]
    _lista(cliente, orden_id, BATERIA)
    notificar_pagar_entregar(cliente, orden_id)

    conflicto(_subir(cliente, orden_id), "ORDEN_CERRADA")
    imagen = cliente.get(f"/api/orders/{orden_id}/photos/{foto_id}")
    assert imagen.status_code == 200 and imagen.content == JPEG
    respuesta = cliente.get(f"/api/orders/{orden_id}/photos/FOT-NO")
    assert respuesta.status_code == 404


# --- Tipos y adaptadores ---------------------------------------------------


@pytest.mark.parametrize(
    ("contenido", "tipo"),
    [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")],
)
def test_tipo_por_contenido(contenido, tipo):
    assert tipo_de_imagen(contenido) == tipo


def test_directorio_local_no_sale_de_su_raiz(tmp_path):
    almacen = AlmacenFotosDirectorio(tmp_path / "fotos")
    almacen.guardar("ordenes/OR-1/FOT-1.jpg", JPEG, "image/jpeg")

    assert almacen.obtener("ordenes/OR-1/FOT-1.jpg") == JPEG
    with pytest.raises(AlmacenFotosError):
        almacen.guardar("../fuera.jpg", JPEG, "image/jpeg")


class RespuestaHttp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class HttpSimulado:
    """Lo que el adaptador le pediria a GCS y al servidor de metadatos."""

    def __init__(self):
        self.pedidos = []

    def __call__(self, pedido, timeout):
        self.pedidos.append(pedido)
        if "metadata.google.internal" in pedido.full_url:
            cuerpo = {"access_token": "token-1", "expires_in": 3600}
            return RespuestaHttp(json.dumps(cuerpo).encode())
        if pedido.get_method() == "GET":
            return RespuestaHttp(JPEG)
        return RespuestaHttp(b"{}")


def test_gcs_sube_y_lee_con_el_token_de_la_cuenta_de_servicio():
    http = HttpSimulado()
    almacen = AlmacenFotosGcs("rt-rma-uat-fotos", abrir=http)

    almacen.guardar("ordenes/OR-1/FOT-1.jpg", JPEG, "image/jpeg")
    assert almacen.obtener("ordenes/OR-1/FOT-1.jpg") == JPEG

    token, subida = http.pedidos[0], http.pedidos[1]
    assert token.get_header("Metadata-flavor") == "Google"
    assert subida.get_method() == "POST"
    assert subida.full_url.startswith(
        "https://storage.googleapis.com/upload/storage/v1/b/"
        "rt-rma-uat-fotos/o?"
    )
    assert "uploadType=media" in subida.full_url
    assert "name=ordenes%2FOR-1%2FFOT-1.jpg" in subida.full_url
    assert "ifGenerationMatch=0" in subida.full_url
    assert subida.get_header("Authorization") == "Bearer token-1"
    assert subida.get_header("Content-type") == "image/jpeg"
    assert subida.data == JPEG
    lectura = http.pedidos[2]
    assert lectura.full_url == (
        "https://storage.googleapis.com/storage/v1/b/rt-rma-uat-fotos/o/"
        "ordenes%2FOR-1%2FFOT-1.jpg?alt=media"
    )
    # El token se reutiliza hasta que vence (un solo pedido de token).
    assert sum("metadata" in p.full_url for p in http.pedidos) == 1


def test_gcs_caido_es_un_error_de_almacenamiento():
    def caido(pedido, timeout):
        raise OSError("sin red")

    with pytest.raises(AlmacenFotosError):
        AlmacenFotosGcs("bucket", abrir=caido).obtener("ordenes/a/b.jpg")


@pytest.fixture(autouse=True)
def _sin_bucket_real(monkeypatch):
    """Ningun test sale a la red."""
    monkeypatch.delenv("RMA_FOTOS_BUCKET", raising=False)


def test_la_configuracion_elige_el_almacenamiento(tmp_path):
    from app.application import construir_contexto

    sin = construir_contexto(Settings(data_dir=tmp_path))
    gcs = construir_contexto(
        Settings(data_dir=tmp_path, fotos_bucket="rt-rma-uat-fotos")
    )
    local = construir_contexto(
        Settings(data_dir=tmp_path, fotos_dir=tmp_path / "fotos")
    )

    assert sin.fotos is None
    assert isinstance(gcs.fotos, AlmacenFotosGcs)
    assert gcs.fotos.bucket == "rt-rma-uat-fotos"
    assert isinstance(local.fotos, AlmacenFotosDirectorio)


# --- UAT-011: tope de 10, acceso por Orden y limpieza de huerfanas ----------


def test_el_tope_es_10_fotos_por_orden(armar):
    cliente = armar(AlmacenFotosMemoria())
    orden_id = ingresada(cliente, BATERIA)

    for _ in range(10):
        ok(_subir(cliente, orden_id))

    assert MAX_FOTOS_POR_ORDEN == 10
    assert "10 fotos" in conflicto(_subir(cliente, orden_id))
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    assert len(orden["fotos"]) == 10


def test_una_foto_solo_se_ve_desde_su_orden(armar):
    cliente = armar(AlmacenFotosMemoria())
    una = ingresada(cliente, BATERIA)
    otra = ingresada(cliente, BATERIA)
    foto_id = ok(_subir(cliente, una))["fotos"][0]["id"]

    respuesta = cliente.get(f"/api/orders/{otra}/photos/{foto_id}")

    assert respuesta.status_code == 404
    assert (
        cliente.get(f"/api/orders/{una}/photos/{foto_id}").status_code == 200
    )


def _limpiar(cliente, usuario="ADMIN-001", aplicar=False):
    return cliente.post(
        "/api/maintenance/photos/cleanup",
        params={"usuario_id": usuario, "aplicar": str(aplicar).lower()},
    )


def test_limpieza_de_imagenes_huerfanas(armar):
    """Solo se borran las que ninguna Orden usa y no son recientes."""
    almacen = AlmacenFotosMemoria()
    cliente = armar(almacen)
    orden_id = ingresada(cliente, BATERIA)
    usada = ok(_subir(cliente, orden_id))["fotos"][0]["id"]
    vieja = "ordenes/OR-000099/FOT-viejo.jpg"
    reciente = "ordenes/OR-000099/FOT-reciente.jpg"
    almacen.guardar(vieja, JPEG, "image/jpeg")
    almacen.guardar(reciente, JPEG, "image/jpeg")
    almacen.fechas[vieja] = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # La foto usada se conserva aunque sea vieja.
    clave_usada = next(c for c in almacen.objetos if usada in c)
    almacen.fechas[clave_usada] = datetime(2026, 1, 1, tzinfo=timezone.utc)

    informe = ok(_limpiar(cliente))
    assert informe["aplicada"] is False
    assert (informe["revisadas"], informe["referenciadas"]) == (3, 1)
    assert informe["huerfanas"] == [vieja]
    assert informe["recientes_conservadas"] == [reciente]
    assert informe["eliminadas"] == []
    assert vieja in almacen.objetos

    aplicada = ok(_limpiar(cliente, aplicar=True))

    assert aplicada["eliminadas"] == [vieja]
    assert sorted(almacen.objetos) == sorted([clave_usada, reciente])
    imagen = cliente.get(f"/api/orders/{orden_id}/photos/{usada}")
    assert imagen.status_code == 200


def test_la_limpieza_es_solo_de_administracion(armar):
    cliente = armar(AlmacenFotosMemoria())

    conflicto(_limpiar(cliente, usuario=RECEPCION))


def test_directorio_local_lista_y_elimina(tmp_path):
    almacen = AlmacenFotosDirectorio(tmp_path / "fotos")
    almacen.guardar("ordenes/OR-1/FOT-1.jpg", JPEG, "image/jpeg")
    almacen.guardar("otros/x.jpg", JPEG, "image/jpeg")

    (objeto,) = almacen.listar("ordenes/")
    assert objeto.clave == "ordenes/OR-1/FOT-1.jpg"
    almacen.eliminar(objeto.clave)
    assert almacen.listar("ordenes/") == []


class HttpListado(HttpSimulado):
    """GCS con dos paginas de objetos."""

    def __call__(self, pedido, timeout):
        self.pedidos.append(pedido)
        if "metadata.google.internal" in pedido.full_url:
            cuerpo = {"access_token": "token-1", "expires_in": 3600}
            return RespuestaHttp(json.dumps(cuerpo).encode())
        if pedido.get_method() == "DELETE":
            return RespuestaHttp(b"")
        if "pageToken=p2" in pedido.full_url:
            cuerpo = {
                "items": [
                    {
                        "name": "ordenes/b.jpg",
                        "updated": "2026-10-02T00:00:00Z",
                    }
                ]
            }
        else:
            cuerpo = {
                "items": [
                    {
                        "name": "ordenes/a.jpg",
                        "updated": "2026-10-01T10:00:00.123Z",
                    }
                ],
                "nextPageToken": "p2",
            }
        return RespuestaHttp(json.dumps(cuerpo).encode())


def test_gcs_lista_por_paginas_y_elimina():
    http = HttpListado()
    almacen = AlmacenFotosGcs("rt-rma-uat-fotos", abrir=http)

    objetos = almacen.listar("ordenes/")
    almacen.eliminar("ordenes/OR-1/FOT-1.jpg")

    assert [o.clave for o in objetos] == ["ordenes/a.jpg", "ordenes/b.jpg"]
    assert objetos[0].actualizado == datetime(
        2026, 10, 1, 10, 0, 0, 123000, tzinfo=timezone.utc
    )
    primera = http.pedidos[1]
    assert primera.full_url.startswith(
        "https://storage.googleapis.com/storage/v1/b/rt-rma-uat-fotos/o?"
    )
    assert "prefix=ordenes%2F" in primera.full_url
    borrado = http.pedidos[-1]
    assert borrado.get_method() == "DELETE"
    assert borrado.full_url == (
        "https://storage.googleapis.com/storage/v1/b/rt-rma-uat-fotos/o/"
        "ordenes%2FOR-1%2FFOT-1.jpg"
    )
    assert borrado.get_header("Authorization") == "Bearer token-1"
