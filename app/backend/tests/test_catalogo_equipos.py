"""Catalogo de equipos de Ventas: formato, adaptadores y reglas.

La lectura de Google Sheets se prueba contra HTTP simulado con la
estructura real de ``raw_TipoProducto`` (``tests.fixtures.catalogo_ventas``);
ningun test consulta la planilla real ni usa datos personales.
"""

import io
import json
import subprocess
import urllib.error
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from app.core.config import Settings
from app.domain.models import (
    MotivoBaja,
    MotivoNoSeleccionable,
    ProductoInformado,
)
from app.integraciones.catalogo import (
    CatalogoOrigenInvalidoError,
    CatalogoOrigenNoDisponibleError,
    ConfiguracionCatalogoError,
    FiltroCatalogo,
    ProveedorCatalogoArchivo,
    ProveedorCatalogoSheets,
    construir_proveedor_catalogo,
    filtro_catalogo,
)
from app.integraciones.catalogo.credenciales import (
    ALCANCE_SHEETS_LECTURA,
    CredencialCloudRun,
    CredencialGcloud,
    CredencialImpersonada,
)
from app.integraciones.catalogo.ventas import lectura_desde_tabla
from app.services import (
    CatalogoRechazadoError,
    fusionar_catalogo,
    opciones_de_seleccion,
    validar_informados,
)
from tests.fixtures.catalogo_ventas import (
    EMAIL_FICTICIO,
    ENCABEZADOS,
    ID_12_MINI_GENERICO,
    ID_12_MINI_NEGRO,
    ID_12_NEGRO,
    ID_12_PRO_MAX_VIOLETA,
    ID_16_PRO_MAX,
    ID_SE_ROJO,
    escribir_csv,
    fila,
    respuesta_sheets,
    tabla,
)

USADOS = FiltroCatalogo(("IPHONE USADOS",))
MARCAS = {"IPHONE": "Apple"}
T0 = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
TOKEN = "token-de-prueba-no-real"


def _leer(filas=None, filtro=USADOS, marcas=MARCAS):
    encabezados, *resto = tabla(filas)
    return lectura_desde_tabla(encabezados, resto, filtro, marcas=marcas)


def _por_id(lectura):
    return {p.tipo_producto_id: p for p in lectura.productos}


# --- Formato de Ventas -------------------------------------------------------


def test_filtra_por_subcategoria_y_cuenta_lo_leido():
    lectura = _leer()
    # 14 filas con datos (la vacia no cuenta); 12 de IPHONE USADOS.
    assert (lectura.leidos, lectura.filtrados, lectura.descartados) == (
        14,
        12,
        0,
    )
    assert all(p.subcategoria == "IPHONE USADOS" for p in lectura.productos)
    assert "apple_nuevos_iPhone_12_Nada_128gb_black" not in _por_id(lectura)


def test_el_filtro_no_distingue_mayusculas_ni_espacios():
    assert FiltroCatalogo(("iphone usados",)).admite("  IPHONE USADOS ")
    assert not FiltroCatalogo(("IPHONE USADOS",)).admite("IPHONE NUEVOS")
    varias = _leer(filtro=FiltroCatalogo(("IPHONE USADOS", "IPHONE NUEVOS")))
    assert varias.filtrados == 13


def test_conserva_el_tp_id_original_sin_transformarlo():
    productos = _por_id(_leer())
    # Con espacios y mayusculas, tal como lo genera Ventas.
    assert ID_12_PRO_MAX_VIOLETA in productos
    assert ID_16_PRO_MAX in productos
    assert "c05e814d" in productos


def test_traduce_las_convenciones_de_ventas():
    productos = _por_id(_leer())
    estandar = productos[ID_12_NEGRO]
    assert (estandar.marca, estandar.modelo, estandar.variante) == (
        "Apple",
        "iPhone 12",
        None,
    )
    assert (estandar.capacidad, estandar.color) == ("128 GB", "Black")
    assert estandar.descripcion == "iPhone 12 128gb black"
    assert estandar.valores_origen == {
        "tp_number": "12",
        "tp_promaxness": "Nada",
        "tp_gb": "128gb",
        "tp_color": "black",
    }
    violeta = productos[ID_12_PRO_MAX_VIOLETA]
    assert (violeta.variante, violeta.capacidad, violeta.color) == (
        "Pro Max",
        "256 GB",
        "Deep Purple",
    )
    titanio = productos[ID_16_PRO_MAX]
    assert (titanio.capacidad, titanio.color) == ("1 TB", "Black Titanium")
    assert productos[ID_SE_ROJO].modelo == "iPhone SE 2020"
    generico = productos[ID_12_MINI_GENERICO]
    assert generico.color is None and generico.color_generico
    assert not generico.faltantes


def test_los_generadores_no_son_equipos():
    productos = _por_id(_leer())
    for tipo_id in ("iphone_usados", "c05e814d"):
        assert productos[tipo_id].generador
        assert set(productos[tipo_id].faltantes) >= {
            "modelo",
            "variante",
            "capacidad",
            "color",
        }
    assert not productos[ID_12_NEGRO].generador


def test_ubica_las_columnas_por_nombre_y_no_copia_las_demas():
    orden = list(reversed(ENCABEZADOS))
    filas = [
        [dict(zip(ENCABEZADOS, f + [""] * 40))[c] for c in orden]
        for f in [fila("12", "Nada", "128gb", "black", eliminado=True)]
    ]
    lectura = lectura_desde_tabla(orden, filas, USADOS, marcas=MARCAS)
    (producto,) = lectura.productos
    assert producto.tipo_producto_id == ID_12_NEGRO and producto.eliminado
    # Ni precios ni quien lo elimino (un email) llegan al producto.
    assert EMAIL_FICTICIO not in producto.model_dump_json()
    assert "410" not in json.dumps(producto.valores_origen)


def test_rechaza_si_faltan_o_se_repiten_columnas():
    sin_color = [c for c in ENCABEZADOS if c != "tp_color"]
    with pytest.raises(CatalogoOrigenInvalidoError, match="tp_color"):
        lectura_desde_tabla(sin_color, [], USADOS, marcas=MARCAS)
    with pytest.raises(CatalogoOrigenInvalidoError, match="repite"):
        lectura_desde_tabla([*ENCABEZADOS, "tp_id"], [], USADOS, marcas=MARCAS)


def test_descarta_las_filas_del_filtro_sin_tp_id():
    sin_id = fila("13", "Pro", "128gb", "gold")
    sin_id[0] = "  "
    lectura = _leer([sin_id, fila("13", "Pro", "256gb", "gold")])
    assert (lectura.filtrados, lectura.descartados) == (2, 1)
    assert len(lectura.productos) == 1


def test_una_categoria_sin_marca_configurada_queda_incompleta():
    lectura = _leer([fila("12", "Nada", "128gb", "black")], marcas={})
    (producto,) = lectura.productos
    assert producto.marca is None and "marca" in producto.faltantes


# --- Adaptador Google Sheets (HTTP simulado) ---------------------------------


class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class HttpSimulado:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.pedidos = []

    def __call__(self, pedido, timeout=None):
        self.pedidos.append(pedido)
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return _Respuesta(respuesta)


def _error_http(codigo):
    return urllib.error.HTTPError(
        "https://sheets.googleapis.com", codigo, "x", {}, io.BytesIO(b"{}")
    )


def _sheets(http, credencial=lambda: TOKEN):
    return ProveedorCatalogoSheets(
        planilla_id="PLANILLA-DE-PRUEBA",
        hoja="raw_TipoProducto",
        credencial=credencial,
        marcas=MARCAS,
        abrir=http,
    )


def test_sheets_lee_la_hoja_en_solo_lectura_y_filtra():
    http = HttpSimulado(respuesta_sheets())
    lectura = _sheets(http).leer(USADOS)
    assert lectura.filtrados == 12 and ID_12_NEGRO in _por_id(lectura)
    (pedido,) = http.pedidos
    url = urlparse(pedido.full_url)
    assert url.netloc == "sheets.googleapis.com"
    assert unquote(url.path) == (
        "/v4/spreadsheets/PLANILLA-DE-PRUEBA/values/'raw_TipoProducto'"
    )
    assert parse_qs(url.query)["valueRenderOption"] == ["UNFORMATTED_VALUE"]
    assert pedido.get_method() == "GET"
    assert pedido.get_header("Authorization") == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    ("codigo", "texto"),
    [
        (403, "permiso de lectura"),
        (404, "No se encontró la planilla"),
        (400, "no tiene la hoja"),
        (429, "limitó"),
        (500, "HTTP 500"),
    ],
)
def test_sheets_traduce_los_errores_http_sin_secretos(codigo, texto):
    with pytest.raises(CatalogoOrigenNoDisponibleError, match=texto) as e:
        _sheets(HttpSimulado(_error_http(codigo))).leer(USADOS)
    assert TOKEN not in str(e.value)


def test_sheets_sin_conexion_o_con_respuesta_invalida():
    with pytest.raises(CatalogoOrigenNoDisponibleError, match="conectar"):
        _sheets(HttpSimulado(urllib.error.URLError("dns"))).leer(USADOS)
    with pytest.raises(CatalogoOrigenNoDisponibleError):
        _sheets(HttpSimulado(TimeoutError())).leer(USADOS)
    with pytest.raises(CatalogoOrigenInvalidoError, match="JSON"):
        _sheets(HttpSimulado(b"<html>")).leer(USADOS)
    with pytest.raises(CatalogoOrigenInvalidoError, match="vacía"):
        _sheets(HttpSimulado(b'{"range": "x"}')).leer(USADOS)


def test_sheets_sin_credencial_no_consulta():
    def sin_credencial():
        raise CatalogoOrigenNoDisponibleError("sin credencial")

    http = HttpSimulado()
    with pytest.raises(CatalogoOrigenNoDisponibleError, match="credencial"):
        _sheets(http, sin_credencial).leer(USADOS)
    assert http.pedidos == []


def test_el_adaptador_de_archivo_cumple_el_mismo_puerto(tmp_path):
    ruta = escribir_csv(tmp_path / "tipo_producto.csv")
    desde_csv = ProveedorCatalogoArchivo(ruta, marcas=MARCAS).leer(USADOS)
    desde_sheets = _sheets(HttpSimulado(respuesta_sheets())).leer(USADOS)
    assert desde_csv == desde_sheets
    with pytest.raises(CatalogoOrigenNoDisponibleError):
        ProveedorCatalogoArchivo(tmp_path / "no.csv", marcas=MARCAS).leer(
            USADOS
        )


# --- Credenciales ------------------------------------------------------------


class Reloj:
    def __init__(self):
        self.ahora = 1000.0

    def __call__(self):
        return self.ahora


def test_credencial_cloud_run_pide_alcance_de_solo_lectura_y_cachea():
    http = HttpSimulado(
        json.dumps({"access_token": "a1", "expires_in": 3599}).encode(),
        json.dumps({"access_token": "a2", "expires_in": 3599}).encode(),
    )
    reloj = Reloj()
    credencial = CredencialCloudRun(abrir=http, reloj=reloj)
    assert credencial() == "a1" and credencial() == "a1"
    (pedido,) = http.pedidos
    assert pedido.get_header("Metadata-flavor") == "Google"
    assert unquote(pedido.full_url).endswith(
        f"?scopes={ALCANCE_SHEETS_LECTURA}"
    )
    reloj.ahora += 3600
    assert credencial() == "a2"


def test_credencial_cloud_run_fuera_de_google_no_esta_disponible():
    credencial = CredencialCloudRun(
        abrir=HttpSimulado(urllib.error.URLError("sin metadatos"))
    )
    with pytest.raises(CatalogoOrigenNoDisponibleError, match="metadatos"):
        credencial()


def test_credencial_impersonada_usa_iam_credentials():
    vence = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    http = HttpSimulado(
        json.dumps({"accessToken": "imp", "expireTime": vence}).encode()
    )
    credencial = CredencialImpersonada(
        "lector@proyecto.iam.gserviceaccount.com",
        base=lambda: "base",
        abrir=http,
    )
    assert credencial() == "imp"
    (pedido,) = http.pedidos
    assert pedido.full_url == (
        "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
        "lector@proyecto.iam.gserviceaccount.com:generateAccessToken"
    )
    assert pedido.get_header("Authorization") == "Bearer base"
    assert json.loads(pedido.data)["scope"] == [ALCANCE_SHEETS_LECTURA]
    sin_permiso = CredencialImpersonada(
        "lector@x", base=lambda: "base", abrir=HttpSimulado(_error_http(403))
    )
    with pytest.raises(CatalogoOrigenNoDisponibleError, match="HTTP 403"):
        sin_permiso()


def test_credencial_gcloud_impersona_con_alcance_de_lectura():
    llamadas = []

    def ejecutar(comando, **_):
        llamadas.append(comando)
        return subprocess.CompletedProcess(comando, 0, "tok\n", "")

    assert CredencialGcloud("lector@x", ejecutar=ejecutar)() == "tok"
    (comando,) = llamadas
    assert "--impersonate-service-account=lector@x" in comando
    assert f"--scopes={ALCANCE_SHEETS_LECTURA}" in comando

    def falla(comando, **_):
        return subprocess.CompletedProcess(comando, 1, "", "PERMISSION")

    with pytest.raises(CatalogoOrigenNoDisponibleError, match="gcloud"):
        CredencialGcloud("lector@x", ejecutar=falla)()


# --- Configuracion centralizada ----------------------------------------------


def test_la_configuracion_elige_el_adaptador(tmp_path):
    assert construir_proveedor_catalogo(Settings(data_dir=tmp_path)) is None
    sheets = construir_proveedor_catalogo(
        Settings(
            data_dir=tmp_path,
            catalogo_origen="google_sheets",
            catalogo_sheets_planilla="PLANILLA",
        )
    )
    assert isinstance(sheets, ProveedorCatalogoSheets)
    assert isinstance(sheets._credencial, CredencialCloudRun)
    impersonada = construir_proveedor_catalogo(
        Settings(
            data_dir=tmp_path,
            catalogo_origen="google_sheets",
            catalogo_sheets_planilla="PLANILLA",
            catalogo_sheets_cuenta="lector@x",
        )
    )
    assert isinstance(impersonada._credencial, CredencialImpersonada)
    archivo = construir_proveedor_catalogo(
        Settings(
            data_dir=tmp_path,
            catalogo_origen="archivo",
            catalogo_archivo=tmp_path / "c.csv",
        )
    )
    assert isinstance(archivo, ProveedorCatalogoArchivo)
    assert filtro_catalogo(Settings(data_dir=tmp_path)) == USADOS


@pytest.mark.parametrize(
    "ajustes",
    [
        {"catalogo_origen": "google_sheets"},
        {
            "catalogo_origen": "google_sheets",
            "catalogo_sheets_planilla": "P",
            "catalogo_sheets_credencial": "gcloud",
        },
        {"catalogo_origen": "archivo"},
        {"catalogo_subcategorias": [" "]},
    ],
)
def test_una_configuracion_incompleta_no_arranca(tmp_path, ajustes):
    settings = Settings(data_dir=tmp_path, **ajustes)
    with pytest.raises(ConfiguracionCatalogoError):
        construir_proveedor_catalogo(settings)
        filtro_catalogo(settings)


# --- Reglas: validacion, fusion y seleccion ----------------------------------


def _informado(tipo_id, **cambios):
    datos = {
        "tipo_producto_id": tipo_id,
        "descripcion": tipo_id,
        "marca": "Apple",
        "modelo": "iPhone 12",
        "capacidad": "128 GB",
        "color": "Black",
    }
    return ProductoInformado(**(datos | cambios))


def test_rechaza_una_lectura_vacia_o_con_tp_id_repetidos():
    with pytest.raises(CatalogoRechazadoError, match="ningún producto"):
        validar_informados([])
    with pytest.raises(CatalogoRechazadoError, match="repite tp_id \\(A\\)"):
        validar_informados([_informado("A"), _informado("A"), _informado("B")])


def test_primera_sincronizacion_y_repeticion_sin_duplicados():
    informados = _leer().productos
    primera = fusionar_catalogo([], informados, fecha=T0)
    assert primera.nuevos == 12 and len(primera.productos) == 12
    assert primera.elegibles == 10  # sin los dos generadores
    generador = {p.tipo_producto_id: p for p in primera.productos}[
        "iphone_usados"
    ]
    assert not generador.seleccionable
    assert generador.motivo_no_seleccionable == MotivoNoSeleccionable.GENERADOR

    otra_vez = fusionar_catalogo(
        primera.productos, informados, fecha=T0 + timedelta(hours=1)
    )
    assert (otra_vez.nuevos, otra_vez.actualizados, otra_vez.sin_cambios) == (
        0,
        0,
        12,
    )
    ids = [p.tipo_producto_id for p in otra_vez.productos]
    assert len(ids) == len(set(ids)) == 12
    producto = otra_vez.productos[1]
    assert producto.primera_sincronizacion == T0
    assert producto.ultima_sincronizacion == T0 + timedelta(hours=1)


def test_nunca_borra_marca_baja_y_reactiva():
    a, b, c = _informado("A"), _informado("B"), _informado("C")
    inicial = fusionar_catalogo([], [a, b, c], fecha=T0)
    cambio = fusionar_catalogo(
        inicial.productos,
        [_informado("A", color="Red"), _informado("B", eliminado=True)],
        fecha=T0,
    )
    por_id = {p.tipo_producto_id: p for p in cambio.productos}
    assert set(por_id) == {"A", "B", "C"}  # nada se borra
    assert (cambio.actualizados, cambio.dados_de_baja) == (1, 2)
    assert por_id["A"].color == "Red" and por_id["A"].vigente
    assert por_id["B"].motivo_baja == MotivoBaja.ELIMINADO_EN_ORIGEN
    assert por_id["C"].motivo_baja == MotivoBaja.NO_INFORMADO
    assert not por_id["C"].elegible

    vuelve = fusionar_catalogo(cambio.productos, [a, b, c], fecha=T0)
    assert vuelve.reactivados == 2 and vuelve.elegibles == 3


def test_un_eliminado_que_nunca_tuvimos_no_se_agrega():
    fusion = fusionar_catalogo([], [_informado("A", eliminado=True)], fecha=T0)
    assert fusion.productos == () and fusion.nuevos == 0


def test_un_producto_incompleto_no_se_ofrece():
    fusion = fusionar_catalogo(
        [], [_informado("A", faltantes=("color",), color=None)], fecha=T0
    )
    (producto,) = fusion.productos
    assert producto.motivo_no_seleccionable == MotivoNoSeleccionable.INCOMPLETO
    assert opciones_de_seleccion(fusion.productos) == ()


def test_el_arbol_solo_tiene_combinaciones_existentes_y_ordenadas():
    productos = fusionar_catalogo([], _leer().productos, fecha=T0).productos
    arbol = opciones_de_seleccion(productos)
    assert [m.modelo for m in arbol] == [
        "iPhone 8",
        "iPhone 12",
        "iPhone 16",
        "iPhone SE 2020",
        "iPhone Xs",
    ]
    doce = arbol[1]
    assert [v.variante for v in doce.variantes] == [None, "Mini", "Pro Max"]
    estandar = doce.variantes[0]
    assert [c.capacidad for c in estandar.capacidades] == ["64 GB", "128 GB"]
    mini = doce.variantes[1].capacidades[0]
    assert [
        (c.color, c.generico, c.tipo_producto_id) for c in mini.colores
    ] == [
        ("Black", False, ID_12_MINI_NEGRO),
        (None, True, ID_12_MINI_GENERICO),
    ]
    # El 16 Pro Max solo existe en 1 TB: no se ofrecen otras capacidades.
    (dieciseis,) = arbol[2].variantes
    assert [c.capacidad for c in dieciseis.capacidades] == ["1 TB"]
    todos = [
        color.tipo_producto_id
        for modelo in arbol
        for variante in modelo.variantes
        for capacidad in variante.capacidades
        for color in capacidad.colores
    ]
    assert len(todos) == 10 and "iphone_usados" not in todos


# --- Copia en JSON -----------------------------------------------------------


def _sincronizacion(numero, resultado="EXITOSA"):
    from app.domain.models import SincronizacionCatalogo

    return SincronizacionCatalogo(
        id=f"SINC-{numero}",
        usuario_id="ADMIN-001",
        origen="prueba",
        filtro="subcategoría: IPHONE USADOS",
        iniciada_en=T0,
        finalizada_en=T0,
        resultado=resultado,
    )


def test_la_copia_json_guarda_productos_y_registro_juntos(tmp_path):
    from app.storage import JsonCatalogoEquiposRepository

    copia = JsonCatalogoEquiposRepository(tmp_path)
    assert (
        copia.listar_productos() == [] and copia.obtener_producto("A") is None
    )
    productos = fusionar_catalogo([], _leer().productos, fecha=T0).productos
    copia.aplicar_sincronizacion(_sincronizacion(1), productos)
    copia.registrar_sincronizacion(_sincronizacion(2, "FALLIDA"))

    # Otro proceso (u otra instancia) lee lo mismo.
    otra = JsonCatalogoEquiposRepository(tmp_path)
    assert otra.listar_productos() == list(productos)
    assert otra.obtener_producto(ID_12_NEGRO).capacidad == "128 GB"
    assert [s.id for s in otra.listar_sincronizaciones()] == [
        "SINC-1",
        "SINC-2",
    ]
    # Si el archivo cambia por fuera, se relee.
    otra.aplicar_sincronizacion(_sincronizacion(3), productos[:1])
    assert len(copia.listar_productos()) == 1


def test_la_copia_json_conserva_los_ultimos_intentos(tmp_path):
    from app.storage import JsonCatalogoEquiposRepository
    from app.storage.json.catalogo_equipos import MAX_SINCRONIZACIONES

    copia = JsonCatalogoEquiposRepository(tmp_path)
    for numero in range(MAX_SINCRONIZACIONES + 5):
        copia.registrar_sincronizacion(_sincronizacion(numero, "FALLIDA"))
    registros = copia.listar_sincronizaciones()
    assert len(registros) == MAX_SINCRONIZACIONES
    assert registros[-1].id == f"SINC-{MAX_SINCRONIZACIONES + 4}"
