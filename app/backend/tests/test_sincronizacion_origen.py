# ruff: noqa: E501
"""Bloque C (C3, C5, C2): motor comun de sincronizacion, lector de Google
Sheets y reserva de la copia JSON. Sin base: dobles y HTTP simulado."""

import io
import json
import logging
import re
import threading
import urllib.error
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from app.application.sincronizacion_origen import (
    MENSAJE_APLICACION,
    MENSAJE_LECTURA,
    ejecutar_sincronizacion,
)
from app.domain.models import (
    ReservaSincronizacion,
    ResultadoSincronizacion,
    SincronizacionCatalogo,
)
from app.integraciones.catalogo import (
    CatalogoOrigenInvalidoError,
    CatalogoOrigenNoDisponibleError,
)
from app.integraciones.origen import (
    OrigenInvalidoError,
    OrigenNoDisponibleError,
)
from app.integraciones.sheets import LectorSheets, letra_de_columna
from app.repositories import ReservaOcupadaError
from app.services import SincronizacionEnCursoError
from app.storage.json.catalogo_equipos import JsonCatalogoEquiposRepository

AHORA = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
TOKEN = "token-secreto-de-prueba"


# --- Motor -------------------------------------------------------------------


class RechazoPropio(Exception):
    pass


class RechazoDeLaCopia(Exception):
    pass


class CopiaDoble:
    """Una copia que registra lo que el motor le pide."""

    mensaje_en_curso = "en curso"
    rechazos = (RechazoPropio,)

    def __init__(
        self,
        *,
        leer=None,
        validar=None,
        aplicar=None,
        finalizar=None,
        ocupada=False,
    ):
        self._leer = leer or (lambda: "lectura")
        self._validar = validar or (lambda lectura: None)
        self._aplicar = aplicar or (
            lambda reserva, lectura: ("EXITOSA", reserva.id)
        )
        self._finalizar = finalizar
        self.ocupada = ocupada
        self.llamadas: list[tuple] = []
        self.reservas: list[ReservaSincronizacion] = []

    def rechazo(self, mensaje):
        return RechazoDeLaCopia(mensaje)

    def reservar(self, *, id, propietario, duracion):
        self.llamadas.append(("reservar", id, duracion))
        if self.ocupada:
            raise ReservaOcupadaError("ocupada")
        reserva = ReservaSincronizacion(
            id=id,
            copia="DOBLE",
            usuario_id="ADMIN-001",
            origen="doble",
            filtro="",
            iniciada_en=AHORA,
            vence_en=AHORA + duracion,
            propietario=propietario,
        )
        self.reservas.append(reserva)
        return reserva

    def leer(self):
        self.llamadas.append(("leer",))
        return self._leer()

    def validar(self, lectura):
        self.llamadas.append(("validar", lectura))
        self._validar(lectura)

    def aplicar(self, reserva, lectura):
        self.llamadas.append(("aplicar", reserva.id, lectura))
        return self._aplicar(reserva, lectura)

    def finalizar(self, reserva, resultado, mensaje, lectura):
        self.llamadas.append(
            ("finalizar", reserva.id, resultado, mensaje, lectura)
        )
        if self._finalizar:
            self._finalizar()


def _falla(error):
    def lanzar(*_):
        raise error

    return lanzar


def _sincronizar(copia):
    return ejecutar_sincronizacion(copia, duracion=timedelta(minutes=10))


def test_exitosa_reserva_lee_valida_y_aplica():
    copia = CopiaDoble()
    assert _sincronizar(copia)[0] == "EXITOSA"
    (reserva,) = copia.reservas
    assert re.fullmatch(r"SINC-[0-9a-f]{12}", reserva.id)
    assert re.fullmatch(r"[0-9a-f]{64}", reserva.propietario)
    assert [c[0] for c in copia.llamadas] == [
        "reservar",
        "leer",
        "validar",
        "aplicar",
    ]
    assert copia.llamadas[0][2] == timedelta(minutes=10)


def test_el_propietario_es_secreto_y_distinto_cada_vez():
    copia = CopiaDoble()
    _sincronizar(copia)
    _sincronizar(copia)
    primera, segunda = copia.reservas
    assert primera.propietario != segunda.propietario
    assert primera.propietario not in repr(primera)


def test_otra_en_curso_responde_409_sin_leer():
    copia = CopiaDoble(ocupada=True)
    with pytest.raises(SincronizacionEnCursoError, match="en curso"):
        _sincronizar(copia)
    assert [c[0] for c in copia.llamadas] == ["reservar"]


def test_origen_no_disponible_finaliza_fallida_y_sigue_el_error():
    copia = CopiaDoble(leer=_falla(CatalogoOrigenNoDisponibleError("sin red")))
    with pytest.raises(CatalogoOrigenNoDisponibleError, match="sin red"):
        _sincronizar(copia)
    final = copia.llamadas[-1]
    assert final[0] == "finalizar"
    assert final[2:] == (ResultadoSincronizacion.FALLIDA, "sin red", None)
    assert not any(c[0] == "aplicar" for c in copia.llamadas)


@pytest.mark.parametrize(
    "error",
    [OrigenInvalidoError("faltan columnas"), RechazoPropio("repetidos")],
)
def test_datos_no_confiables_finalizan_rechazada(error):
    copia = CopiaDoble(validar=_falla(error))
    with pytest.raises(RechazoDeLaCopia, match=str(error)):
        _sincronizar(copia)
    final = copia.llamadas[-1]
    assert final[2:] == (
        ResultadoSincronizacion.RECHAZADA,
        str(error),
        "lectura",
    )
    assert not any(c[0] == "aplicar" for c in copia.llamadas)


def test_un_error_inesperado_al_leer_finaliza_fallida():
    copia = CopiaDoble(leer=_falla(KeyError("x")))
    with pytest.raises(KeyError):
        _sincronizar(copia)
    assert copia.llamadas[-1][2:4] == (
        ResultadoSincronizacion.FALLIDA,
        MENSAJE_LECTURA,
    )


def test_si_aplicar_falla_se_finaliza_fallida_y_sigue_el_error():
    copia = CopiaDoble(aplicar=_falla(RuntimeError("se cayo la base")))
    with pytest.raises(RuntimeError, match="se cayo la base"):
        _sincronizar(copia)
    assert copia.llamadas[-1][2:4] == (
        ResultadoSincronizacion.FALLIDA,
        MENSAJE_APLICACION,
    )


def test_si_finalizar_tambien_falla_sigue_el_error_original(caplog):
    copia = CopiaDoble(
        leer=_falla(OrigenNoDisponibleError("sin red")),
        finalizar=_falla(RuntimeError("base caida")),
    )
    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(OrigenNoDisponibleError, match="sin red"),
    ):
        _sincronizar(copia)
    assert "INTERRUMPIDA" in caplog.text
    assert copia.reservas[0].propietario not in caplog.text


# --- Lector de Google Sheets (C5) --------------------------------------------


class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Http:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.pedidos = []

    def __call__(self, pedido, timeout=None):
        self.pedidos.append(pedido)
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        if isinstance(respuesta, (dict, list)):
            respuesta = json.dumps(respuesta).encode()
        return _Respuesta(respuesta)


def _lector(http, **ajustes):
    return LectorSheets(
        planilla_id="PLANILLA",
        credencial=lambda: TOKEN,
        abrir=http,
        **ajustes,
    )


def _http_error(codigo):
    return urllib.error.HTTPError(
        "https://sheets.googleapis.com", codigo, "x", {}, io.BytesIO(b"{}")
    )


def test_letras_de_columna():
    assert [letra_de_columna(i) for i in (0, 5, 25, 26, 27, 51, 52, 701, 702)] == [
        "A", "F", "Z", "AA", "AB", "AZ", "BA", "ZZ", "AAA",
    ]  # fmt: skip
    with pytest.raises(ValueError):
        letra_de_columna(-1)


def test_valores_de_una_hoja():
    http = Http({"values": [["a", "b"], [1, 2]]})
    assert _lector(http).valores("Hoja 1") == [["a", "b"], [1, 2]]
    url = urlparse(http.pedidos[0].full_url)
    assert unquote(url.path) == "/v4/spreadsheets/PLANILLA/values/'Hoja 1'"
    assert parse_qs(url.query)["valueRenderOption"] == ["UNFORMATTED_VALUE"]
    assert http.pedidos[0].get_header("Authorization") == f"Bearer {TOKEN}"


def test_por_columnas_solo_pide_las_columnas_indicadas():
    http = Http(
        {
            "valueRanges": [
                {"range": "'P'!A1:A3", "values": [["producto_id", "1", "2"]]},
                {
                    "range": "'P'!F1:F3",
                    "values": [["producto_status", "Reparacion"]],
                },
                {"range": "'P'!Z1:Z1"},
            ]
        }
    )
    columnas = _lector(http).valores_por_columnas("P", ["A", "F", "Z"])
    assert columnas == [
        ["producto_id", "1", "2"],
        ["producto_status", "Reparacion"],
        [],
    ]
    (pedido,) = http.pedidos
    url = urlparse(pedido.full_url)
    assert url.path == "/v4/spreadsheets/PLANILLA/values:batchGet"
    consulta = parse_qs(url.query)
    assert consulta["ranges"] == ["'P'!A:A", "'P'!F:F", "'P'!Z:Z"]
    assert consulta["majorDimension"] == ["COLUMNS"]
    assert consulta["dateTimeRenderOption"] == ["SERIAL_NUMBER"]


@pytest.mark.parametrize("columnas", [[], ["a"], ["A1"], ["A:A"], ["AAAA"]])
def test_por_columnas_rechaza_pedidos_que_no_son_letras(columnas):
    http = Http()
    with pytest.raises(ValueError):
        _lector(http).valores_por_columnas("P", columnas)
    assert http.pedidos == []


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"valueRanges": [{"values": [["a"]]}]},  # falta un rango
        {"valueRanges": [{"values": "x"}, {}]},
        {
            "valueRanges": [{"values": [["a"], ["b"]]}, {}]
        },  # dos columnas en un rango
        {"otra": 1},
    ],
)
def test_por_columnas_rechaza_respuestas_inesperadas(cuerpo):
    with pytest.raises(OrigenInvalidoError):
        _lector(Http(cuerpo)).valores_por_columnas("P", ["A", "B"])


def test_nombre_de_hoja_por_gid():
    http = Http(
        {
            "sheets": [
                {"properties": {"sheetId": 1, "title": "Otra"}},
                {"properties": {"sheetId": 1030788425, "title": "Producto"}},
            ]
        }
    )
    assert _lector(http).nombre_de_hoja(1030788425) == "Producto"
    consulta = parse_qs(urlparse(http.pedidos[0].full_url).query)
    assert consulta["fields"] == ["sheets.properties(sheetId,title)"]
    with pytest.raises(OrigenInvalidoError, match="GID 7"):
        _lector(Http({"sheets": []})).nombre_de_hoja(7)


@pytest.mark.parametrize(
    ("codigo", "texto"),
    [
        (403, "permiso de lectura sobre la planilla de prueba"),
        (404, "No se encontró la planilla de prueba"),
        (429, "limitó"),
        (500, "HTTP 500"),
    ],
)
def test_errores_http_con_el_nombre_de_la_planilla_y_sin_token(codigo, texto):
    with pytest.raises(OrigenNoDisponibleError, match=texto) as error:
        _lector(
            Http(_http_error(codigo)), nombre="la planilla de prueba"
        ).valores("H")
    assert TOKEN not in str(error.value)


def test_los_errores_son_los_del_origen_que_lo_usa():
    errores = (CatalogoOrigenNoDisponibleError, CatalogoOrigenInvalidoError)
    with pytest.raises(CatalogoOrigenNoDisponibleError):
        _lector(Http(urllib.error.URLError("dns")), errores=errores).valores(
            "H"
        )
    with pytest.raises(CatalogoOrigenInvalidoError):
        _lector(Http(b"<html>"), errores=errores).valores("H")
    # Y siguen siendo errores de origen para el motor.
    assert issubclass(CatalogoOrigenNoDisponibleError, OrigenNoDisponibleError)
    assert issubclass(CatalogoOrigenInvalidoError, OrigenInvalidoError)


# --- Reserva de la copia JSON (C2) -------------------------------------------


def _intento(id_, resultado="FALLIDA"):
    return SincronizacionCatalogo(
        id=id_,
        usuario_id="ADMIN-001",
        origen="o",
        filtro="f",
        iniciada_en=AHORA,
        finalizada_en=AHORA,
        resultado=resultado,
    )


def _reservar(repo, id_="SINC-000000000001"):
    return repo.reservar_sincronizacion(
        id=id_,
        usuario_id="ADMIN-001",
        origen="o",
        filtro="f",
        duracion=timedelta(minutes=10),
        propietario="secreto",
    )


def test_json_una_reserva_por_archivo_y_se_libera_al_finalizar(tmp_path):
    repo = JsonCatalogoEquiposRepository(tmp_path)
    otro = JsonCatalogoEquiposRepository(tmp_path)  # mismo archivo
    reserva = _reservar(repo)
    assert reserva.vence_en - reserva.iniciada_en == timedelta(minutes=10)
    with pytest.raises(ReservaOcupadaError):
        _reservar(otro, "SINC-000000000002")
    repo.registrar_sincronizacion(_intento(reserva.id), reserva)
    segunda = _reservar(otro, "SINC-000000000002")
    otro.aplicar_sincronizacion(_intento(segunda.id, "EXITOSA"), [], segunda)
    assert [s.id for s in repo.listar_sincronizaciones()] == [
        reserva.id,
        segunda.id,
    ]
    # Liberar dos veces no libera la reserva de otro.
    tercera = _reservar(repo, "SINC-000000000003")
    repo.registrar_sincronizacion(_intento("SINC-000000000004"), reserva)
    with pytest.raises(ReservaOcupadaError):
        _reservar(otro, "SINC-000000000005")
    repo.registrar_sincronizacion(_intento(tercera.id), tercera)


def test_json_otra_carpeta_es_otra_copia(tmp_path):
    a = _reservar(JsonCatalogoEquiposRepository(tmp_path / "a"))
    b = _reservar(JsonCatalogoEquiposRepository(tmp_path / "b"))
    assert a.id == b.id  # no se bloquean entre si


def test_json_sin_reserva_sigue_funcionando_como_antes(tmp_path):
    repo = JsonCatalogoEquiposRepository(tmp_path)
    repo.registrar_sincronizacion(_intento("SINC-000000000009"))
    assert len(repo.listar_sincronizaciones()) == 1


def test_json_la_reserva_se_libera_aunque_falle_la_escritura(
    tmp_path, monkeypatch
):
    repo = JsonCatalogoEquiposRepository(tmp_path)
    reserva = _reservar(repo)

    def falla(*_):
        raise OSError("disco lleno")

    monkeypatch.setattr(repo, "_escribir", falla)
    with pytest.raises(OSError):
        repo.aplicar_sincronizacion(
            _intento(reserva.id, "EXITOSA"), [], reserva
        )
    monkeypatch.undo()
    _reservar(repo, "SINC-000000000002")  # quedo libre


def test_json_dos_hilos_no_reservan_a_la_vez(tmp_path):
    repo = JsonCatalogoEquiposRepository(tmp_path)
    resultados = []
    barrera = threading.Barrier(2)

    def intentar(numero):
        barrera.wait()
        try:
            _reservar(repo, f"SINC-00000000000{numero}")
            resultados.append("reservo")
        except ReservaOcupadaError:
            resultados.append("ocupada")

    hilos = [threading.Thread(target=intentar, args=(n,)) for n in (1, 2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(5)
    assert sorted(resultados) == ["ocupada", "reservo"]
