"""Catalogo de Ventas ficticio con la estructura real de raw_TipoProducto.

Mismos 33 encabezados y los mismos tipos que devuelve la API de Sheets con
``UNFORMATTED_VALUE`` (``tp_generator`` booleano, precios numericos, celdas
vacias como ""). Los valores son de prueba: ningun dato personal (el email
de ``tp_eliminado_por`` es de un dominio reservado, ``.invalid``).
"""

import csv
import io
import json
from pathlib import Path

ENCABEZADOS = [
    "tp_id", "tp_categoria", "tp_subcat_1", "tp_gp", "tp_generator",
    "tp_modelo", "tp_number", "tp_promaxness", "tp_gb", "tp_color",
    "tp_precio_venta", "tp_precio_moneda", "tp_precio_categoria_1",
    "tp_precio_categoria_2", "tp_precio_categoria_3",
    "tp_precio_categoria_4", "tp_precio_toma_rt_c1", "tp_precio_toma_rt_c2",
    "tp_precio_toma_no_c1", "tp_precio_toma_no_c2",
    "tp_descuento_estetico_1", "tp_descuento_estetico_2",
    "tp_reparacion_pantalla", "tp_descuento_camara",
    "tp_reparacion_bateria", "tp_reparacion_pin", "tp_moneda_compra",
    "tp_descuento_faceid", "tp_descuento_modulo", "tp_eliminado",
    "tp_eliminado_por", "tp_eliminado_at", "tp_prod_devol",
]  # fmt: skip

EMAIL_FICTICIO = "vendedor@example.invalid"


def fila(
    numero: str,
    variante: str,
    gb: str,
    color: str,
    *,
    subcat: str = "IPHONE USADOS",
    grupo: str = "apple_usados",
    eliminado: bool = False,
    precio: int | str = 410,
) -> list:
    """Una variante como las de Ventas: ``tp_id`` y ``tp_modelo``
    compuestos igual que en la planilla real."""
    estado = subcat.split()[-1].lower()
    tp_id = f"apple_{estado}_iPhone_{numero}_{variante}_{gb}_{color}"
    nombre_variante = "" if variante == "Nada" else variante
    modelo = f"iPhone {numero} {nombre_variante} {gb} {color}"
    valores = {
        "tp_id": tp_id,
        "tp_categoria": "IPHONE",
        "tp_subcat_1": subcat,
        "tp_gp": grupo,
        "tp_generator": False,
        "tp_modelo": modelo,
        "tp_number": numero,
        "tp_promaxness": variante,
        "tp_gb": gb,
        "tp_color": color,
        "tp_precio_moneda": "USD",
        "tp_precio_categoria_2": precio,
    }
    if eliminado:
        valores |= {
            "tp_eliminado": "yes",
            "tp_eliminado_por": EMAIL_FICTICIO,
            "tp_eliminado_at": 45898,
        }
    # La API omite las celdas vacias del final de cada fila.
    completa = [valores.get(columna, "") for columna in ENCABEZADOS]
    while completa and completa[-1] == "":
        completa.pop()
    return completa


GENERADOR = [
    "iphone_usados", "IPHONE", "IPHONE USADOS", "apple_usados", True,
    "iPhone",
]  # fmt: skip
GENERADOR_CON_ID_CORTO = [
    "c05e814d", "IPHONE", "IPHONE USADOS", "smartphone_usados_", True,
    "iPhone 17 E 256GB", "", "", "", "", "", "", "", "", "", "", "", "",
    "", "", "", "", "", "", "", "", "", "", "", "", "", "", "c05e814d",
]  # fmt: skip


def filas_base() -> list[list]:
    """Usados de varias generaciones, con los casos especiales reales."""
    return [
        GENERADOR,
        fila("12", "Mini", "128gb", "black"),
        fila("12", "Mini", "128gb", "cualquier_color"),
        fila("12", "Nada", "128gb", "black"),
        fila("12", "Nada", "64gb", "blue"),
        fila("12", "Pro Max", "256gb", "deep_purple"),
        fila("12", "Pro Max", "256gb", "cualquier_color"),
        fila("16", "Pro Max", "1tb", "black titanium"),
        fila("8", "Plus", "64gb", "gold"),
        fila("SE 2020", "Nada", "128gb", "red"),
        fila("Xs", "Max", "512gb", "space"),
        GENERADOR_CON_ID_CORTO,
        # Otra subcategoria: no entra en el filtro.
        fila("12", "Nada", "128gb", "black", subcat="IPHONE NUEVOS",
             grupo="apple_nuevos"),
        [],  # fila vacia en el medio
        ["", "ACCESORIOS", "Fundas", "accesorios_fundas", False, "Funda"],
    ]  # fmt: skip


def tabla(filas: list[list] | None = None) -> list[list]:
    return [ENCABEZADOS, *(filas_base() if filas is None else filas)]


def respuesta_sheets(filas: list[list] | None = None) -> bytes:
    """El cuerpo de ``values.get`` con ``majorDimension=ROWS``."""
    return json.dumps(
        {
            "range": "raw_TipoProducto!A1:AG4081",
            "majorDimension": "ROWS",
            "values": tabla(filas),
        }
    ).encode("utf-8")


def escribir_csv(ruta: Path, filas: list[list] | None = None) -> Path:
    """La misma tabla como CSV (adaptador de archivo)."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    for registro in tabla(filas):
        escritor.writerow(
            [
                ("TRUE" if valor else "FALSE")
                if isinstance(valor, bool)
                else valor
                for valor in registro
            ]
        )
    ruta.write_text(buffer.getvalue(), encoding="utf-8")
    return ruta


ID_12_MINI_NEGRO = "apple_usados_iPhone_12_Mini_128gb_black"
ID_12_MINI_GENERICO = "apple_usados_iPhone_12_Mini_128gb_cualquier_color"
ID_12_NEGRO = "apple_usados_iPhone_12_Nada_128gb_black"
ID_12_PRO_MAX_VIOLETA = "apple_usados_iPhone_12_Pro Max_256gb_deep_purple"
ID_SE_ROJO = "apple_usados_iPhone_SE 2020_Nada_128gb_red"
ID_16_PRO_MAX = "apple_usados_iPhone_16_Pro Max_1tb_black titanium"
