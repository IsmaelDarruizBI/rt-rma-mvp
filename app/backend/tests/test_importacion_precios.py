"""DEC-AJ-13 (BF-02): importacion masiva de precios por modelo.

- Logica pura (``services/importacion_precios.py``): importes con formato
  argentino, forma de la matriz, errores con su celda, clasificacion
  NUEVO / CAMBIA / SIN_CAMBIO, avisos y plantilla.
- Lectura de planillas (``integraciones/planillas.py``): .xlsx, CSV con o
  sin BOM y con cualquiera de los separadores, celdas pegadas, limites y
  la plantilla de ida y vuelta sin cambios.
- API en el modo JSON: plantilla y vista previa (solo lectura); aplicar es
  de PostgreSQL (``tests/postgres/test_importacion_precios_postgres.py``).
"""

import io
import json
from decimal import Decimal

import pytest

from app.domain.models import (
    FormatoImportacion,
    ModeloEquipo,
    TipoReparacion,
)
from app.integraciones.planillas import (
    MAX_BYTES,
    PlanillaIlegibleError,
    escribir_csv,
    escribir_xlsx,
    formato_de,
    leer_planilla,
)
from app.services.importacion_precios import (
    MAX_COLUMNAS,
    MAX_FILAS,
    EstadoPrecio,
    ImporteInvalidoError,
    celda,
    matriz_plantilla,
    parsear_importe,
    precios_a_aplicar,
    previsualizar,
)
from tests.fixtures import api_salidas as f

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _tipo(codigo, nombre="Cambio", *, por_modelo=True, activo=True, **p):
    return TipoReparacion(
        id=codigo,
        nombre=nombre,
        precio=Decimal("1"),
        puntaje=1,
        garantia_dias=90,
        activo=activo,
        precio_por_modelo=por_modelo,
        precios_modelo={k: Decimal(v) for k, v in p.items()},
    )


def _modelo(codigo, modelo, *, marca="Apple", activo=True):
    return ModeloEquipo(id=codigo, marca=marca, modelo=modelo, activo=activo)


TIPOS = {
    t.id: t
    for t in (
        _tipo(
            "TR-010",
            "Cambio de modulo",
            **{"MOD-0001": "60000", "MOD-0002": "100"},
        ),
        _tipo("TR-011", "Cambio de bateria"),
        _tipo("TR-001", "Precio unico", por_modelo=False),
        _tipo("TR-020", "De baja", activo=False),
    )
}
MODELOS = {
    m.id: m
    for m in (
        _modelo("MOD-0001", "iPhone 8"),
        _modelo("MOD-0002", "iPhone 8 Plus"),
        _modelo("MOD-0003", "iPhone 11", activo=False),
        _modelo("MOD-0050", "Galaxy S24", marca="Samsung"),
    )
}


def _vista(matriz, formato=FormatoImportacion.CSV):
    return previsualizar(matriz, tipos=TIPOS, modelos=MODELOS, formato=formato)


# --- Importes ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("80000", "80000.00"),
        ("80.000", "80000.00"),
        ("80.000,50", "80000.50"),
        ("80000,50", "80000.50"),
        ("80000,5", "80000.50"),
        ("80000.50", "80000.50"),
        ("$ 80.000", "80000.00"),
        ("$80.000,5", "80000.50"),
        ("1.234.567", "1234567.00"),
        (" 80 000 ", "80000.00"),
        ("0", "0.00"),
        (Decimal("80000"), "80000.00"),
        (Decimal("80000.5"), "80000.50"),
    ],
)
def test_importes_validos(texto, esperado):
    assert parsear_importe(texto) == Decimal(esperado)
    assert str(parsear_importe(texto)) == esperado


@pytest.mark.parametrize(
    ("texto", "motivo"),
    [
        ("80,000", "ambiguo"),
        ("-100", "negativo"),
        ("$ -5", "negativo"),
        ("80.000,505", "dos decimales"),
        ("80000.505", "dos decimales"),
        ("0.500", "dos decimales"),
        ("abc", "no es un importe"),
        ("1,234,567", "no es un importe"),
        ("80,000.50", "no es un importe"),
        ("12.34.5", "miles"),
        ("$", "no es un importe"),
        (Decimal("1.234"), "dos decimales"),
        (Decimal("-1"), "negativo"),
    ],
)
def test_importes_invalidos_con_su_motivo(texto, motivo):
    with pytest.raises(ImporteInvalidoError) as error:
        parsear_importe(texto)
    assert motivo in str(error.value)


def test_coordenadas_de_planilla():
    assert celda(5, 3) == "C5"
    assert celda(1, 27) == "AA1"


# --- Vista previa ------------------------------------------------------------


def test_clasifica_nuevos_cambios_y_sin_cambio_e_ignora_nombres():
    vista = _vista(
        [
            [
                "Modelo",
                "Nombre del modelo",
                "TR-010 · Cambio de modulo",
                "TR-011",
            ],
            ["MOD-0001", "iPhone 8", "60.000", "70000"],
            ["MOD-0002 · iPhone 8 Plus", "x", "200", ""],
            ["", "", "", ""],
        ]
    )
    assert vista.errores == []
    assert vista.aplicable is True
    assert [
        (c.celda, c.modelo_equipo_id, c.tipo_reparacion_id, c.estado)
        for c in vista.cambios
    ] == [
        ("D2", "MOD-0001", "TR-011", EstadoPrecio.NUEVO),
        ("C3", "MOD-0002", "TR-010", EstadoPrecio.CAMBIA),
    ]
    cambia = vista.cambios[1]
    assert (cambia.anterior, cambia.nuevo) == (Decimal("100"), Decimal("200"))
    resumen = vista.resumen
    assert (resumen.modelos, resumen.tipos) == (2, 2)
    assert (resumen.nuevos, resumen.actualizados, resumen.sin_cambio) == (
        1,
        1,
        1,
    )
    assert resumen.vacias == 1
    # Una variacion de mas del 50 % avisa, sin bloquear.
    assert [(a.celda, "50 %" in a.mensaje) for a in vista.avisos] == [
        ("C3", True)
    ]
    assert [(c.columna, c.encabezado) for c in vista.columnas_ignoradas] == [
        ("B", "Nombre del modelo")
    ]
    # Solo los nuevos y los que cambian, nunca un precio vacio.
    precios = precios_a_aplicar(vista)
    assert [
        (p.tipo_reparacion_id, p.modelo_equipo_id, p.precio) for p in precios
    ] == [
        ("TR-011", "MOD-0001", Decimal("70000.00")),
        ("TR-010", "MOD-0002", Decimal("200.00")),
    ]


def test_sin_cambios_no_es_aplicable():
    vista = _vista([["Modelo", "TR-010"], ["MOD-0001", "60000,00"]])
    assert vista.errores == []
    assert vista.resumen.sin_cambio == 1
    assert vista.cambios == []
    assert vista.aplicable is False


def test_errores_de_columnas_con_su_celda():
    vista = _vista(
        [
            [
                "Modelo",
                "TR-999",
                "TR-001 · Precio unico",
                "TR-OTROS",
                "TR-020",
                "TR-010",
                "TR-010 otra vez",
            ],
            ["MOD-0001", "1", "2", "3", "4", "5", "6"],
        ]
    )
    errores = {e.celda: e.mensaje for e in vista.errores}
    assert "No existe el Tipo de Reparacion TR-999" in errores["B1"]
    assert "precio unico" in errores["C1"]
    assert "Otros" in errores["D1"]
    assert "de baja" in errores["E1"]
    assert "repetido" in errores["G1"]
    assert vista.aplicable is False
    # Las columnas con error no se evaluan; la valida si.
    assert [c.celda for c in vista.cambios] == ["F2"]


def test_errores_de_filas_con_su_celda():
    vista = _vista(
        [
            ["Modelo", "TR-010", "TR-011"],
            ["MOD-0001", "", "1"],
            ["MOD-9999", "", ""],
            ["MOD-0050", "", ""],
            ["MOD-0003", "", ""],
            ["mod-0001", "", ""],
            ["iPhone 8", "1", ""],
            ["", "5", ""],
            ["MOD-0002", "80,000", "-3"],
        ]
    )
    errores = [(e.celda, e.mensaje) for e in vista.errores]
    assert errores[0] == ("A3", "No existe el modelo MOD-9999.")
    assert errores[1][0] == "A4" and "no es de marca Apple" in errores[1][1]
    assert errores[2][0] == "A5" and "de baja" in errores[2][1]
    assert errores[3][0] == "A6" and "repetido" in errores[3][1]
    assert "A2" in errores[3][1]
    assert (
        errores[4][0] == "A7" and "no es un codigo de modelo" in errores[4][1]
    )
    assert errores[5] == ("A8", "Falta el codigo del modelo (MOD-0001).")
    assert errores[6][0] == "B9" and "ambiguo" in errores[6][1]
    assert errores[7][0] == "C9" and "negativo" in errores[7][1]
    assert len(errores) == 8
    assert vista.resumen.errores == 8
    assert vista.aplicable is False


def test_estructura_invalida():
    assert "vacia" in _vista([["", ""], []]).errores[0].mensaje
    vista = _vista([["Modelo", "Nombre"], ["MOD-0001", "x"]])
    assert "TR-001" in vista.errores[0].mensaje
    filas = [["Modelo", "TR-010"]] + [
        ["MOD-0001", "1"] for _ in range(MAX_FILAS + 1)
    ]
    assert "filas" in _vista(filas).errores[0].mensaje
    ancho = [["Modelo"] + ["x"] * MAX_COLUMNAS]
    assert "columnas" in _vista(ancho).errores[0].mensaje


def test_columna_clave_por_nombre_y_encabezado_despues_de_filas_vacias():
    vista = _vista(
        [
            [],
            ["Nombre", "Código del modelo", "TR-011"],
            ["iPhone 8", "MOD-0001", "$ 1.500"],
        ]
    )
    assert vista.errores == []
    assert [(c.celda, c.nuevo) for c in vista.cambios] == [
        ("C3", Decimal("1500.00"))
    ]


def test_aviso_de_precio_cero():
    vista = _vista([["Modelo", "TR-011"], ["MOD-0001", "0"]])
    assert vista.aplicable is True
    assert "precio 0" in vista.avisos[0].mensaje


def test_plantilla_solo_apple_vigentes_y_tipos_por_modelo():
    matriz = matriz_plantilla(list(TIPOS.values()), list(MODELOS.values()))
    assert matriz[0] == [
        "Modelo",
        "Nombre del modelo",
        "TR-010 · Cambio de modulo",
        "TR-011 · Cambio de bateria",
    ]
    assert matriz[1:] == [
        ["MOD-0001", "Apple iPhone 8", Decimal("60000.00"), None],
        ["MOD-0002", "Apple iPhone 8 Plus", Decimal("100.00"), None],
    ]


# --- Lectura de planillas ----------------------------------------------------


def _leer(contenido, tipo):
    formato = formato_de(contenido, tipo)
    return formato, leer_planilla(
        contenido, formato, max_filas=MAX_FILAS + 1, max_columnas=MAX_COLUMNAS
    )


def test_csv_con_bom_y_punto_y_coma():
    contenido = "﻿Modelo;TR-010\r\nMOD-0001;80.000,50\r\n".encode()
    formato, matriz = _leer(contenido, "text/csv")
    assert formato is FormatoImportacion.CSV
    assert matriz == [["Modelo", "TR-010"], ["MOD-0001", "80.000,50"]]


def test_csv_con_coma_e_importes_entre_comillas_sin_bom():
    contenido = (
        b'Modelo,Nombre,TR-010\nMOD-0001,"iPhone 8, usado","80.000,50"\n'
    )
    _, matriz = _leer(contenido, "application/vnd.ms-excel")
    assert matriz[1] == ["MOD-0001", "iPhone 8, usado", "80.000,50"]


def test_csv_de_excel_en_windows_1252():
    contenido = "Modelo;TR-010 · Batería\nMOD-0001;1\n".encode("cp1252")
    _, matriz = _leer(contenido, "text/csv")
    assert matriz[0][1] == "TR-010 · Batería"


def test_celdas_pegadas_con_tabulaciones():
    contenido = "Modelo\tTR-010\nMOD-0001\t80.000,50\nMOD-0002\t\n".encode()
    formato, matriz = _leer(contenido, "text/tab-separated-values")
    assert formato is FormatoImportacion.TEXTO
    assert matriz == [
        ["Modelo", "TR-010"],
        ["MOD-0001", "80.000,50"],
        ["MOD-0002"],
    ]
    assert _leer(contenido, "text/plain")[0] is FormatoImportacion.TEXTO


def test_formatos_no_admitidos():
    with pytest.raises(PlanillaIlegibleError, match="xls"):
        formato_de(b"\xd0\xcf\x11\xe0resto", "application/vnd.ms-excel")
    with pytest.raises(PlanillaIlegibleError, match="no admitido"):
        formato_de(b"{}", "application/json")
    with pytest.raises(PlanillaIlegibleError, match="no es un .xlsx"):
        formato_de(b"Modelo", XLSX)
    with pytest.raises(PlanillaIlegibleError, match="No se pudo leer"):
        _leer(b"PK\x03\x04roto", XLSX)
    with pytest.raises(PlanillaIlegibleError, match="vacio"):
        _leer(b"  ", "text/csv")
    with pytest.raises(PlanillaIlegibleError, match="MB"):
        _leer(b"x" * (MAX_BYTES + 1), "text/csv")


def _xlsx(filas) -> bytes:
    from openpyxl import Workbook

    libro = Workbook()
    hoja = libro.active
    for fila in filas:
        hoja.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def test_xlsx_numeros_textos_y_filas_vacias_al_principio():
    contenido = _xlsx(
        [
            [],
            ["Modelo", "TR-010", "TR-011"],
            ["MOD-0001", 80000.1, "80.000,50"],
            ["MOD-0002", 150, None],
        ]
    )
    formato, matriz = _leer(contenido, "application/octet-stream")
    assert formato is FormatoImportacion.XLSX
    vista = _vista(matriz, FormatoImportacion.XLSX)
    assert vista.errores == []
    assert [(c.celda, c.nuevo) for c in vista.cambios] == [
        ("B3", Decimal("80000.10")),
        ("C3", Decimal("80000.50")),
        ("B4", Decimal("150.00")),
    ]


def test_xlsx_mas_filas_que_el_limite():
    filas = [["Modelo", "TR-010"]] + [
        [f"MOD-{i:04d}", 1] for i in range(1, MAX_FILAS + 3)
    ]
    _, matriz = _leer(_xlsx(filas), XLSX)
    # Se lee una fila de mas, suficiente para rechazarla.
    assert len(matriz) == MAX_FILAS + 2
    assert "filas" in _vista(matriz).errores[0].mensaje


def test_plantilla_de_ida_y_vuelta_sin_cambios():
    matriz = matriz_plantilla(list(TIPOS.values()), list(MODELOS.values()))
    for contenido, tipo in (
        (escribir_xlsx(matriz), XLSX),
        (escribir_csv(matriz), "text/csv"),
    ):
        formato, leida = _leer(contenido, tipo)
        vista = _vista(leida, formato)
        assert vista.errores == [], (formato, vista.errores)
        assert vista.cambios == []
        assert vista.resumen.sin_cambio == 2
        assert vista.resumen.vacias == 2
    assert escribir_csv(matriz).startswith("﻿Modelo;".encode())
    assert b"MOD-0001;Apple iPhone 8;60000,00;" in escribir_csv(matriz)


# --- API (modo JSON) ---------------------------------------------------------

POR_MODELO = "TR-010"


@pytest.fixture
def cliente(tmp_path):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    f.sembrar(tmp_path)
    ruta = tmp_path / "catalogs" / "tipos_reparacion.json"
    tipos = json.loads(ruta.read_text("utf-8"))
    tipos.append(
        _tipo(
            POR_MODELO, "Cambio de modulo", **{"MOD-0001": "60000"}
        ).model_dump(mode="json")
    )
    ruta.write_text(json.dumps(tipos), encoding="utf-8")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as http:
        yield http


def _previa(cliente, texto, usuario=f.ADMINISTRADOR, tipo="text/csv"):
    return cliente.post(
        "/api/admin/model-prices/import/preview",
        params={"usuario_id": usuario, "nombre": "precios.csv"},
        content=texto.encode(),
        headers={"Content-Type": tipo},
    )


def test_api_plantilla_en_xlsx_y_csv(cliente):
    respuesta = cliente.get("/api/admin/model-prices/template")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == XLSX
    assert "precios-por-modelo-" in respuesta.headers["content-disposition"]
    _, matriz = _leer(respuesta.content, XLSX)
    assert matriz[0] == [
        "Modelo",
        "Nombre del modelo",
        "TR-010 · Cambio de modulo",
    ]
    assert matriz[1] == ["MOD-0001", "Apple iPhone 8", Decimal("60000.00")]
    # Los 36 modelos Apple de la carga inicial.
    assert len(matriz) == 37

    csv = cliente.get(
        "/api/admin/model-prices/template", params={"formato": "csv"}
    )
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    assert ".csv" in csv.headers["content-disposition"]
    vista = f.ok(
        cliente.post(
            "/api/admin/model-prices/import/preview",
            params={"usuario_id": f.ADMINISTRADOR},
            content=csv.content,
            headers={"Content-Type": "text/csv"},
        )
    )
    assert vista["errores"] == []
    assert vista["resumen"]["sin_cambio"] == 1
    assert vista["aplicable"] is False


def test_api_vista_previa_en_json_sin_aplicar(cliente):
    vista = f.ok(
        _previa(
            cliente,
            "Modelo\tTR-010\nMOD-0001\t90.000\nMOD-0003\t50.000\n",
            tipo="text/tab-separated-values",
        )
    )
    assert vista["formato"] == "TEXTO"
    assert vista["nombre_archivo"] == "precios.csv"
    assert vista["editable"] is False
    assert vista["aplicable"] is True
    assert [
        (c["celda"], c["estado"], c["anterior"], c["nuevo"])
        for c in vista["cambios"]
    ] == [
        ("B2", "CAMBIA", "60000.00", "90000.00"),
        ("B3", "NUEVO", None, "50000.00"),
    ]
    # Aplicar es de PostgreSQL: en JSON los catalogos son de solo lectura.
    respuesta = cliente.post(
        "/api/admin/model-prices/import",
        params={"usuario_id": f.ADMINISTRADOR},
        content=b"Modelo;TR-010\nMOD-0001;90000\n",
        headers={"Content-Type": "text/csv"},
    )
    assert "PostgreSQL" in f.conflicto(respuesta)


def test_api_exige_gestionar_precios_y_un_formato_admitido(cliente):
    for usuario in (f.RECEPCION, f.TECNICO, f.COORDINADOR):
        respuesta = _previa(cliente, "Modelo;TR-010\n", usuario=usuario)
        assert "requiere" in f.conflicto(respuesta), usuario
    respuesta = _previa(cliente, "{}", tipo="application/json")
    assert "no admitido" in f.conflicto(respuesta)
