"""Reparacion RT (etapa 1, tareas 1.1 y 1.2): contrato de Producto y
adaptadores de origen. Sin base ni red: Sheets con respuestas simuladas.

Diseño: docs/reparacion-rt-discovery.md, secciones 2.2 a 2.9.
"""

import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from app.core.config import Settings
from app.integraciones.gestion_rt import (
    COLUMNAS,
    COPIAR,
    NUNCA,
    ConfiguracionProductosRtError,
    ProductosRtOrigenInvalidoError,
    ProductosRtOrigenNoDisponibleError,
    ProveedorProductosRtArchivo,
    ProveedorProductosRtSheets,
    construir_proveedor_productos_rt,
)
from app.integraciones.gestion_rt.contrato import (
    OBLIGATORIAS,
    OPCIONALES,
    columnas_a_leer,
    fecha_de_celda,
    tabla_desde_columnas,
    tabla_desde_filas,
)
from app.integraciones.sheets import letra_de_columna
from tests.fixtures import productos_rt as ficticios

ZONA = timezone(timedelta(hours=-3))
TOKEN = "token-de-prueba-no-real"
GID = 1030788425


# --- Lista permitida (seccion 2.2 y 2.8) ------------------------------------


def test_la_lista_permitida_son_13_columnas_de_producto_sin_passcode():
    assert len(COLUMNAS) == 31 and len(set(COLUMNAS)) == 31
    assert len(OBLIGATORIAS) == 6 and len(OPCIONALES) == 7
    assert set(COPIAR) <= set(COLUMNAS)
    assert "producto_passcode" in COLUMNAS
    assert NUNCA == {"producto_passcode"}
    assert not set(COPIAR) & NUNCA
    # Ninguna columna comercial ni de personas.
    assert not set(COPIAR) & set(ficticios.NO_LEER)
    assert set(COPIAR) | set(ficticios.NO_LEER) == set(COLUMNAS)


def test_columnas_por_nombre_y_opcionales_faltantes():
    encabezado = ["otra", *reversed(OBLIGATORIAS), "producto_bateria"]
    indices, faltantes = columnas_a_leer(
        encabezado, error=ProductosRtOrigenInvalidoError
    )
    assert indices["producto_id"] == encabezado.index("producto_id")
    assert set(indices) == {*OBLIGATORIAS, "producto_bateria"}
    assert faltantes == tuple(c for c in OPCIONALES if c != "producto_bateria")


@pytest.mark.parametrize("columna", OBLIGATORIAS)
def test_falta_una_obligatoria_rechaza(columna):
    encabezado = [c for c in COLUMNAS if c != columna]
    with pytest.raises(ProductosRtOrigenInvalidoError, match=columna):
        columnas_a_leer(encabezado, error=ProductosRtOrigenInvalidoError)


@pytest.mark.parametrize("columna", ["producto_id", "producto_defecto"])
def test_una_columna_copiada_repetida_rechaza(columna):
    with pytest.raises(ProductosRtOrigenInvalidoError, match="repite"):
        columnas_a_leer(
            [*COLUMNAS, columna], error=ProductosRtOrigenInvalidoError
        )


def test_repetir_una_columna_no_copiada_no_importa():
    indices, _ = columnas_a_leer(
        [*COLUMNAS, "producto_passcode", "producto_oc"],
        error=ProductosRtOrigenInvalidoError,
    )
    assert set(indices) == set(COPIAR)


def test_una_columna_fuera_de_la_lista_nunca_se_interpreta():
    with pytest.raises(ValueError, match="producto_passcode"):
        tabla_desde_columnas(
            {"producto_id": ["1"], "producto_passcode": ["x"]}, zona=ZONA
        )


# --- Celdas ------------------------------------------------------------------


def test_filas_completas_descartan_lo_que_no_se_copia():
    tabla = tabla_desde_filas(
        COLUMNAS,
        ficticios.productos_base(),
        zona=ZONA,
        error=ProductosRtOrigenInvalidoError,
    )
    assert tabla.leidos == ficticios.LEIDOS
    assert tabla.descartados == ficticios.DESCARTADOS
    assert ficticios.VALOR_SENSIBLE not in repr(tabla)
    primera = tabla.filas[0]
    assert primera.producto_id == "900001"
    assert primera.imei == ficticios.imei_ficticio(1)
    assert primera.bateria == "87"
    assert primera.creado_en == datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
    estados = {f.producto_id: f.estado for f in tabla.filas}
    assert estados["900011"] == "Reparacion"  # sin espacios al borde
    assert estados["900014"] == "Reparación"
    eliminado = next(f for f in tabla.filas if f.producto_id == "900020")
    assert eliminado.eliminado is True
    invalida = next(f for f in tabla.filas if f.producto_id == "900021")
    assert invalida.creado_en is None and invalida.creado_en_invalido


def test_imei_y_id_guardados_como_numero_vuelven_a_sus_digitos():
    imei = ficticios.imei_ficticio(5)
    tabla = tabla_desde_columnas(
        {
            "producto_id": [900099.0],
            "producto_imei": [float(imei)],
            "producto_status": ["Reparacion"],
        },
        zona=ZONA,
    )
    assert tabla.filas[0].producto_id == "900099"
    assert tabla.filas[0].imei == imei


def test_columnas_de_largo_distinto_y_filas_vacias():
    tabla = tabla_desde_columnas(
        {
            "producto_id": ["1", "", "3"],
            "producto_status": ["Reparacion"],
            "producto_sede": ["", "", "", ""],
        },
        zona=ZONA,
    )
    assert [f.producto_id for f in tabla.filas] == ["1", "3"]
    assert tabla.leidos == 2 and tabla.descartados == 0
    assert tabla.filas[1].estado == ""


@pytest.mark.parametrize(
    ("valor", "esperada"),
    [
        (46336.5, datetime(2026, 11, 10, 15, 0, tzinfo=UTC)),
        ("46336.5", datetime(2026, 11, 10, 15, 0, tzinfo=UTC)),
        ("2026-11-10T12:00:00", datetime(2026, 11, 10, 15, 0, tzinfo=UTC)),
        ("2026-11-10T12:00:00+00:00", datetime(2026, 11, 10, 12, tzinfo=UTC)),
        ("10/11/2026 12:00", datetime(2026, 11, 10, 15, 0, tzinfo=UTC)),
        ("10/11/2026", datetime(2026, 11, 10, 3, 0, tzinfo=UTC)),
    ],
)
def test_fechas_de_alta(valor, esperada):
    assert fecha_de_celda(valor, ZONA) == (esperada, False)


@pytest.mark.parametrize("valor", [None, "", "  "])
def test_fecha_vacia(valor):
    assert fecha_de_celda(valor, ZONA) == (None, False)


@pytest.mark.parametrize("valor", ["ayer", 12, "999999", "31/02/2026"])
def test_fecha_no_reconocible_no_se_adivina(valor):
    assert fecha_de_celda(valor, ZONA) == (None, True)


# --- Adaptador de archivo ----------------------------------------------------


def _archivo(tmp_path: Path, filas=None, tipos=None):
    return ProveedorProductosRtArchivo(
        ficticios.escribir_csv(tmp_path / "producto.csv", filas),
        ficticios.escribir_tipos(tmp_path / "tipos.csv", tipos),
        marcas={"IPHONE": "Apple"},
        zona=ZONA,
    )


def test_archivo_lee_productos_y_tipos(tmp_path):
    proveedor = _archivo(tmp_path)
    lectura = proveedor.leer()
    assert proveedor.descripcion == "Archivo CSV (producto.csv)"
    assert lectura.leidos == ficticios.LEIDOS
    assert lectura.descartados == ficticios.DESCARTADOS
    assert lectura.faltantes == ()
    assert ficticios.TP_12_NEGRO in lectura.tipos
    assert ficticios.TP_NUEVO in lectura.tipos  # sin filtro de subcategoria
    assert lectura.tipos[ficticios.TP_ELIMINADO].eliminado
    assert ficticios.VALOR_SENSIBLE not in repr(lectura)


def test_archivo_sin_columna_opcional_avisa(tmp_path):
    columnas = [c for c in COLUMNAS if c != "producto_repuesto"]
    ruta = tmp_path / "producto.csv"
    ruta.write_text(",".join(columnas) + "\n1,,,,,,,,,,,", encoding="utf-8")
    proveedor = ProveedorProductosRtArchivo(
        ruta,
        ficticios.escribir_tipos(tmp_path / "tipos.csv"),
        marcas={},
        zona=ZONA,
    )
    assert proveedor.leer().faltantes == ("producto_repuesto",)


def test_archivo_inexistente_es_no_disponible(tmp_path):
    proveedor = ProveedorProductosRtArchivo(
        tmp_path / "no-existe.csv",
        tmp_path / "tampoco.csv",
        marcas={},
        zona=ZONA,
    )
    with pytest.raises(ProductosRtOrigenNoDisponibleError, match="no-existe"):
        proveedor.leer()


def test_archivo_vacio_o_no_utf8_es_invalido(tmp_path):
    vacio = tmp_path / "vacio.csv"
    vacio.write_text("", encoding="utf-8")
    binario = tmp_path / "binario.csv"
    binario.write_bytes(b"\xff\xfe\x00\x81")
    tipos = ficticios.escribir_tipos(tmp_path / "tipos.csv")
    for ruta in (vacio, binario):
        proveedor = ProveedorProductosRtArchivo(
            ruta, tipos, marcas={}, zona=ZONA
        )
        with pytest.raises(ProductosRtOrigenInvalidoError):
            proveedor.leer()


def test_tipos_sin_columnas_de_ventas_es_invalido(tmp_path):
    proveedor = _archivo(tmp_path, tipos=[])
    (tmp_path / "tipos.csv").write_text("tp_id,otra\nx,y\n", encoding="utf-8")
    with pytest.raises(ProductosRtOrigenInvalidoError, match="faltan"):
        proveedor.leer()


# --- Adaptador de Google Sheets ---------------------------------------------


class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Sheets:
    """Simula la API de Sheets v4 sobre las tablas ficticias y guarda cada
    pedido (URL completa) para revisar que se pidio."""

    def __init__(self, filas=None, *, nombre="Producto", errores=None):
        self.columnas = ficticios.columnas(filas)
        self.nombre = nombre
        self.errores = dict(errores or {})
        self.pedidos: list[str] = []

    def __call__(self, pedido, timeout=None):
        assert pedido.headers["Authorization"] == f"Bearer {TOKEN}"
        url = unquote(pedido.full_url)
        self.pedidos.append(url)
        ruta = urlparse(pedido.full_url).path
        consulta = parse_qs(urlparse(pedido.full_url).query)
        if ruta.endswith(":batchGet"):
            tipo = "lote"
        elif "/values/" in ruta:
            tipo = "tipos" if "raw_TipoProducto" in url else "encabezado"
        else:
            tipo = "planilla"
        if tipo in self.errores:
            error = self.errores[tipo]
            if isinstance(error, int):
                raise urllib.error.HTTPError(
                    pedido.full_url, error, "x", {}, io.BytesIO(b"{}")
                )
            raise error
        if tipo == "planilla":
            cuerpo = {
                "sheets": [
                    {"properties": {"sheetId": 0, "title": "Otra"}},
                    {"properties": {"sheetId": GID, "title": self.nombre}},
                ]
            }
        elif tipo == "encabezado":
            assert unquote(ruta).endswith(f"'{self.nombre}'!1:1")
            encabezado = [c[0] for c in self.columnas if c]
            cuerpo = {"values": [encabezado]} if encabezado else {}
        elif tipo == "lote":
            assert consulta["majorDimension"] == ["COLUMNS"]
            assert consulta["dateTimeRenderOption"] == ["SERIAL_NUMBER"]
            rangos = consulta["ranges"]
            cuerpo = {
                "valueRanges": [
                    {"values": [self._columna(rango)]} for rango in rangos
                ]
            }
        else:
            return _Respuesta(ficticios.respuesta_tipos())
        return _Respuesta(json.dumps(cuerpo).encode("utf-8"))

    def _columna(self, rango: str) -> list:
        hoja, columnas = rango.rsplit("!", 1)
        assert hoja == f"'{self.nombre}'"
        letra = columnas.split(":")[0]
        indice = [letra_de_columna(i) for i in range(len(COLUMNAS))].index(
            letra
        )
        return self.columnas[indice]

    def rangos_pedidos(self) -> list[str]:
        return [
            rango
            for url in self.pedidos
            if ":batchGet" in url
            for rango in parse_qs(urlparse(url).query)["ranges"]
        ]


def _sheets(http: Sheets) -> ProveedorProductosRtSheets:
    return ProveedorProductosRtSheets(
        planilla_id="PLANILLA-PRUEBA",
        gid=GID,
        planilla_tipos_id="PLANILLA-VENTAS",
        hoja_tipos="raw_TipoProducto",
        credencial=lambda: TOKEN,
        marcas={"IPHONE": "Apple"},
        zona=ZONA,
        abrir=http,
    )


def test_sheets_pide_solo_las_columnas_copiadas(tmp_path):
    http = Sheets()
    lectura = _sheets(http).leer()
    assert lectura.leidos == ficticios.LEIDOS
    assert len(lectura.filas) == ficticios.LEIDOS - ficticios.DESCARTADOS
    # Un rango por columna copiada, y ninguno de otra columna.
    letras = {
        rango.rsplit("!", 1)[1].split(":")[0]
        for rango in http.rangos_pedidos()
    }
    permitidas = {letra_de_columna(COLUMNAS.index(c)) for c in COPIAR}
    assert letras == permitidas
    passcode = letra_de_columna(COLUMNAS.index("producto_passcode"))
    assert passcode not in letras
    # La fila 1 es el unico rango completo de Producto que se pide.
    producto = [u for u in http.pedidos if "/values/'Producto'" in u]
    assert producto and all("!1:1" in u for u in producto)
    assert ficticios.VALOR_SENSIBLE not in repr(lectura)
    # Productos de la planilla de prueba; tipos de la de Ventas.
    assert all(
        "PLANILLA-PRUEBA" in u
        for u in http.pedidos
        if "raw_TipoProducto" not in u or "fields=" in u
    )
    assert any("PLANILLA-VENTAS" in u for u in http.pedidos)


def test_sheets_encuentra_la_hoja_por_gid_aunque_cambie_de_nombre():
    http = Sheets(nombre="Producto (renombrada)")
    lectura = _sheets(http).leer()
    assert lectura.leidos == ficticios.LEIDOS
    assert _sheets(http).descripcion == f"Google Sheets (hoja con GID {GID})"


def test_sheets_gid_inexistente_es_invalido():
    http = Sheets()
    proveedor = ProveedorProductosRtSheets(
        planilla_id="PLANILLA-PRUEBA",
        gid=999,
        planilla_tipos_id="PLANILLA-VENTAS",
        hoja_tipos="raw_TipoProducto",
        credencial=lambda: TOKEN,
        marcas={},
        zona=ZONA,
        abrir=http,
    )
    with pytest.raises(ProductosRtOrigenInvalidoError, match="GID 999"):
        proveedor.leer()


def test_sheets_hoja_sin_encabezado_es_invalida():
    http = Sheets(filas=[])
    http.columnas = [[] for _ in COLUMNAS]
    with pytest.raises(ProductosRtOrigenInvalidoError, match="vacía"):
        _sheets(http).leer()


def test_sheets_columna_movida_entre_pedidos_rechaza():
    http = Sheets()
    original = http._columna

    def movida(rango):
        columna = original(rango)
        if columna[:1] == ["producto_tp"]:
            return ["otra_cosa", *columna[1:]]
        return columna

    http._columna = movida
    with pytest.raises(ProductosRtOrigenInvalidoError, match="cambió"):
        _sheets(http).leer()


@pytest.mark.parametrize(
    ("codigo", "texto"),
    [
        (401, "permiso"),
        (403, "permiso"),
        (404, "No se encontró"),
        (429, "limitó"),
        (500, "HTTP 500"),
    ],
)
@pytest.mark.parametrize("tipo", ["planilla", "lote", "tipos"])
def test_sheets_errores_http_son_no_disponible(tipo, codigo, texto):
    http = Sheets(errores={tipo: codigo})
    with pytest.raises(ProductosRtOrigenNoDisponibleError, match=texto) as e:
        _sheets(http).leer()
    assert TOKEN not in str(e.value)


def test_sheets_sin_conexion_es_no_disponible():
    http = Sheets(errores={"encabezado": TimeoutError("lento")})
    with pytest.raises(ProductosRtOrigenNoDisponibleError, match="conectar"):
        _sheets(http).leer()


# --- Configuracion -----------------------------------------------------------


def _settings(**valores) -> Settings:
    return Settings(_env_file=None, **valores)


def test_sin_origen_no_hay_proveedor():
    assert construir_proveedor_productos_rt(_settings()) is None


def test_archivo_usa_tipos_del_catalogo_si_no_se_indican(tmp_path):
    proveedor = construir_proveedor_productos_rt(
        _settings(
            productos_rt_origen="archivo",
            productos_rt_archivo=tmp_path / "p.csv",
            catalogo_archivo=tmp_path / "t.csv",
        )
    )
    assert isinstance(proveedor, ProveedorProductosRtArchivo)
    assert proveedor._tipos == tmp_path / "t.csv"


def test_archivo_sin_rutas_no_arranca():
    with pytest.raises(ConfiguracionProductosRtError, match="archivos"):
        construir_proveedor_productos_rt(
            _settings(productos_rt_origen="archivo")
        )


def test_sheets_sin_planilla_o_gid_no_arranca():
    with pytest.raises(ConfiguracionProductosRtError) as error:
        construir_proveedor_productos_rt(
            _settings(productos_rt_origen="google_sheets")
        )
    for variable in (
        "RMA_PRODUCTOS_RT_PLANILLA",
        "RMA_PRODUCTOS_RT_GID",
        "RMA_CATALOGO_SHEETS_PLANILLA",
    ):
        assert variable in str(error.value)


def test_sheets_configurado_con_gid_cero():
    proveedor = construir_proveedor_productos_rt(
        _settings(
            productos_rt_origen="google_sheets",
            productos_rt_planilla="PLANILLA-PRUEBA",
            productos_rt_gid=0,
            catalogo_sheets_planilla="PLANILLA-VENTAS",
        )
    )
    assert isinstance(proveedor, ProveedorProductosRtSheets)
    assert proveedor.descripcion == "Google Sheets (hoja con GID 0)"
