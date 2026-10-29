"""Generacion del catalogo tecnico desde una exportacion de Ventas.

Con el catalogo de Ventas FICTICIO de ``fixtures.catalogo_ventas``: un
modelo por marca, modelo y variante (sin capacidad ni color), «16E» como
«iPhone 16e», la linea iPhone 18 excluida, filas sin modelo informadas y
nunca agregadas, e IDs estables al regenerar.
"""

import json

from app.domain.models import ModeloEquipo
from app.integraciones.catalogo.archivo import ProveedorCatalogoArchivo
from scripts.generar_modelos_equipo import (
    FILTRO,
    a_json,
    generar,
    main,
)
from tests.fixtures.catalogo_ventas import GENERADOR, escribir_csv, fila

INDICE_TP_MODELO = 5


def _sin_modelo(descripcion: str, tp_id: str) -> list:
    """Una fila real sin ``tp_number`` ni variante."""
    registro = fila("", "", "128gb", "", subcat="IPHONE NUEVOS")
    registro[0] = tp_id
    registro[INDICE_TP_MODELO] = descripcion
    return registro


def _filas() -> list[list]:
    return [
        GENERADOR,
        fila("15", "Nada", "128gb", "black"),
        fila("15", "Nada", "256gb", "cualquier_color"),
        fila("15", "Pro Max", "256gb", "black", subcat="IPHONE NUEVOS"),
        fila("15", "Pro Max", "512gb", "blue", eliminado=True),
        fila("16", "E", "128gb", "cualquier_color"),
        fila("16", "Nada", "128gb", "cualquier_color"),
        fila("Xs", "Max", "64gb", "space"),
        fila("SE 2020", "Nada", "128gb", "red"),
        fila("18", "Nada", "128gb", "black"),
        fila("18", "Duo", "128gb", "black"),
        fila("18", "E", "128gb", "black"),
        _sin_modelo("iPhone 16 128gb", "sin_numero_1"),
        _sin_modelo("iPhone 99 128gb", "sin_numero_2"),
        _sin_modelo("iPhone 18 Pro 256GB", "sin_numero_3"),
        # Otra categoria: queda para la carga manual.
        ["moto", "SMARTPHONE", "Motorola", "x", False, "Moto G13 4/128GB"],
    ]


def _productos(tmp_path, filas=None):
    ruta = escribir_csv(
        tmp_path / "ventas.csv", _filas() if filas is None else filas
    )
    proveedor = ProveedorCatalogoArchivo(ruta, marcas={"IPHONE": "Apple"})
    return proveedor.leer(FILTRO).productos


def _nombres(modelos) -> list[tuple]:
    return [(m.id, m.modelo, m.variante) for m in modelos]


def test_un_modelo_por_marca_modelo_y_variante(tmp_path):
    informe = generar(_productos(tmp_path))

    assert _nombres(informe.incluidos) == [
        ("MOD-0001", "iPhone 15", None),
        ("MOD-0002", "iPhone 15", "Pro Max"),
        ("MOD-0003", "iPhone 16", None),
        ("MOD-0004", "iPhone 16e", None),
        ("MOD-0005", "iPhone SE 2020", None),
        ("MOD-0006", "iPhone Xs", "Max"),
    ]
    assert {m.marca for m in informe.incluidos} == {"Apple"}
    # Sin numeros de fabricante: el tp_number no lo es.
    assert all(m.numeros_modelo == () for m in informe.incluidos)
    assert all(m.activo for m in informe.incluidos)


def test_la_linea_iphone_18_queda_excluida(tmp_path):
    informe = generar(_productos(tmp_path))
    assert not any("18" in m.modelo for m in informe.incluidos)
    motivo, filas = informe.excluidos["iPhone 18"]
    assert filas == 3
    assert "verificar" in motivo


def test_las_filas_sin_modelo_se_informan_y_no_se_agregan(tmp_path):
    informe = generar(_productos(tmp_path))
    descartados = {d.tipo_producto_id: d.motivo for d in informe.descartados}
    assert set(descartados) == {"sin_numero_1", "sin_numero_2", "sin_numero_3"}
    assert "representado por «apple iphone 16»" in descartados["sin_numero_1"]
    assert "NO representado" in descartados["sin_numero_2"]
    assert "linea excluida iPhone 18" in descartados["sin_numero_3"]
    assert not any("99" in m.modelo for m in informe.incluidos)


def test_regenerar_con_los_mismos_datos_no_cambia_nada(tmp_path):
    productos = _productos(tmp_path)
    primero = generar(productos)
    segundo = generar(productos, primero.incluidos)

    assert a_json(segundo.incluidos) == a_json(primero.incluidos)
    assert segundo.nuevos == []
    ids = [m.id for m in segundo.incluidos]
    assert len(ids) == len(set(ids))


def test_los_ids_existentes_se_conservan_y_los_nuevos_siguen(tmp_path):
    anterior = [
        # Con datos cargados a mano: se conservan.
        ModeloEquipo(
            id="MOD-0007",
            marca="Apple",
            modelo="iPhone 15",
            variante="Pro Max",
            numeros_modelo=("A2849",),
        ),
        # Ventas ya no lo informa: se conserva, no se borra.
        ModeloEquipo(
            id="MOD-0003", marca="Apple", modelo="iPhone 11", activo=False
        ),
    ]
    informe = generar(_productos(tmp_path), anterior)
    por_clave = {(m.modelo, m.variante): m for m in informe.incluidos}

    assert por_clave[("iPhone 15", "Pro Max")] == anterior[0]
    assert por_clave[("iPhone 11", None)] == anterior[1]
    assert informe.conservados_sin_origen == ["MOD-0003"]
    # Los nuevos, desde el mayor existente.
    assert sorted(informe.nuevos) == [
        "MOD-0008",
        "MOD-0009",
        "MOD-0010",
        "MOD-0011",
        "MOD-0012",
    ]


def test_el_script_escribe_el_archivo_y_es_idempotente(tmp_path, capsys):
    csv = escribir_csv(tmp_path / "ventas.csv", _filas())
    salida = tmp_path / "modelos.json"

    assert main([str(csv), "--salida", str(salida)]) == 0
    primera = salida.read_bytes()
    assert main([str(csv), "--salida", str(salida)]) == 0

    assert salida.read_bytes() == primera
    registros = json.loads(primera)
    assert registros[0] == {
        "id": "MOD-0001",
        "marca": "Apple",
        "modelo": "iPhone 15",
        "variante": None,
        "numeros_modelo": [],
        "activo": True,
    }
    salida_consola = capsys.readouterr().out
    assert "Excluido: iPhone 18 (3 filas)" in salida_consola
    assert "Descartada: sin_numero_1" in salida_consola
