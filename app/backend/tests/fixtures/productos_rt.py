# ruff: noqa: E501  (tabla de casos, una fila por linea)
"""Productos de Gestion RT ficticios con la estructura real de Producto.

Las 31 columnas de Producto, en su orden (``contrato.COLUMNAS``), y los
mismos tipos que devuelve Sheets con ``UNFORMATTED_VALUE`` y
``SERIAL_NUMBER``. Ningun dato real: IMEI de 15 digitos con digito
verificador valido y prefijo de prueba (``35999 9``), ``producto_tp`` del
catalogo ficticio de Ventas (``catalogo_ventas``), y todas las columnas
que RMA nunca lee -``producto_passcode``, documento, precios, comentario,
personas- con el valor fijo ``NO-LEER-FICTICIO``, para comprobar que
nunca aparecen en pedidos, tablas, respuestas ni registros.

``productos_base()`` cubre los casos de la seccion 8 del diseño
(docs/reparacion-rt-discovery.md). Lo usan las pruebas, el ensayo local y
el generador del CSV (``generar_productos_rt_ficticios.py``).
"""

import csv
import io
import json
from pathlib import Path

from app.integraciones.gestion_rt.contrato import COLUMNAS
from tests.fixtures import catalogo_ventas

VALOR_SENSIBLE = "NO-LEER-FICTICIO"
NO_LEER = (
    "producto_oc", "producto_movimiento", "producto_precio_compra",
    "producto_cantidad", "producto_venta_reparacion", "producto_comentario",
    "producto_creado_por", "producto_eliminado_por",
    "producto_eliminado_at", "producto_ov", "producto_precio_vendido",
    "producto_fecha_venta", "producto_enviar_precio", "producto_stock",
    "producto_passcode", "app_id", "producto_documento",
    "producto_check_movimiento",
)  # fmt: skip
# Alta: 10/11/2026 12:00 hora de Gestion RT, como numero de serie de Sheets.
CREADO_EN_SERIAL = 46336.5

TP_12_NEGRO = "apple_usados_iPhone_12_Nada_128gb_black"
TP_12_PRO_MAX = "apple_usados_iPhone_12_Pro Max_256gb_deep_purple"
TP_16 = "apple_usados_iPhone_16_Pro Max_1tb_black titanium"
TP_SE = "apple_usados_iPhone_SE 2020_Nada_128gb_red"
TP_8 = "apple_usados_iPhone_8_Plus_64gb_gold"
TP_NUEVO = "apple_nuevos_iPhone_12_Nada_128gb_black"
TP_ELIMINADO = "apple_usados_iPhone_11_Nada_64gb_white"
TP_INEXISTENTE = "apple_usados_iPhone_99_Nada_1gb_none"


def imei_ficticio(numero: int) -> str:
    """15 digitos: prefijo de prueba, 8 digitos y el verificador (Luhn)."""
    cuerpo = f"359999{numero:08d}"
    total = 0
    for posicion, caracter in enumerate(reversed(cuerpo)):
        digito = int(caracter)
        if posicion % 2 == 0:
            digito *= 2
            if digito > 9:
                digito -= 9
        total += digito
    return cuerpo + str((10 - total % 10) % 10)


def producto(
    producto_id: str,
    *,
    tp: str = TP_12_NEGRO,
    imei: str | int | None = None,
    sede: str = "Centro",
    status: str = "Reparacion",
    eliminado: str = "",
    creado_en: float | str = CREADO_EN_SERIAL,
    bateria: str | int = 87,
    defecto: str = "Pantalla con líneas (ficticio)",
    detalle_estetico: str = "Marcas leves en el marco",
    toma_rt: str = "TOMA",
    tipo_reparacion: str = "Pantalla",
    repuesto: str = "Pantalla OLED genérica",
) -> list:
    """Una fila completa de Producto, con las 31 columnas en su orden."""
    valores = {columna: VALOR_SENSIBLE for columna in NO_LEER}
    valores |= {
        "producto_id": producto_id,
        "producto_tp": tp,
        "producto_imei": "" if imei is None else imei,
        "producto_bateria": bateria,
        "producto_detalle_estetico": detalle_estetico,
        "producto_sede": sede,
        "producto_creado_en": creado_en,
        "producto_eliminado": eliminado,
        "producto_status": status,
        "producto_defecto": defecto,
        "producto_toma_rt": toma_rt,
        "producto_tipo_reparacion": tipo_reparacion,
        "producto_repuesto": repuesto,
    }
    return [valores[columna] for columna in COLUMNAS]


IMEI_REPETIDO = imei_ficticio(9)

# Lo que deja la primera sincronizacion de ``productos_base()``.
EN_REPARACION_POR_SEDE = {
    "Alippi": 2,
    "Centro": 3,
    "eCommerce": 2,
    "Fisherton": 3,
    "RMA": 3,
    "Rosario Norte": 1,
}
EN_REPARACION = sum(EN_REPARACION_POR_SEDE.values())  # 14
LEIDOS = 22
DESCARTADOS = 1
DUPLICADOS = ("900018",)
# Para las coincidencias sugeridas (pruebas con Ordenes ficticias).
ID_CON_REFERENCIA = "900022"
IMEI_CON_ORDEN = imei_ficticio(22)


def productos_base() -> list[list]:
    """Los casos de la seccion 8 (comentario por fila)."""
    return [
        # Reparacion en las 5 sedes confirmadas.
        producto("900001", tp=TP_12_NEGRO, imei=imei_ficticio(1), sede="Alippi"),
        producto("900002", tp=TP_12_PRO_MAX, imei=imei_ficticio(2), sede="Alippi"),
        producto("900003", tp=TP_16, imei=imei_ficticio(3), sede="Centro"),
        # Sin IMEI.
        producto("900004", tp=TP_SE, imei=None, sede="Centro"),
        # IMEI invalido.
        producto("900005", tp=TP_8, imei="12345", sede="Centro"),
        # IMEI guardado como numero y mostrado en notacion cientifica.
        producto("900006", tp=TP_12_NEGRO, imei="3.59999E+14", sede="eCommerce"),
        # TipoProducto inexistente.
        producto("900007", tp=TP_INEXISTENTE, imei=imei_ficticio(7), sede="Fisherton"),
        # TipoProducto eliminado en Ventas.
        producto("900008", tp=TP_ELIMINADO, imei=imei_ficticio(8), sede="Fisherton"),
        # El mismo IMEI en dos productos (y de otra subcategoria).
        producto("900009", tp=TP_NUEVO, imei=IMEI_REPETIDO, sede="RMA"),
        producto("900010", tp=TP_12_NEGRO, imei=IMEI_REPETIDO, sede="RMA"),
        # Estado con espacios al borde: cuenta (se recortan).
        producto("900011", tp=TP_SE, imei=imei_ficticio(11), sede="RMA",
                 status=" Reparacion "),
        # Sede no confirmada.
        producto("900012", tp=TP_12_NEGRO, imei=imei_ficticio(12),
                 sede="Rosario Norte"),
        # Variantes del estado: aviso, no cuentan.
        producto("900013", imei=imei_ficticio(13), status="reparacion"),
        producto("900014", imei=imei_ficticio(14), sede="Alippi",
                 status="Reparación"),
        # Otros estados: no se copian (no es una copia del inventario).
        producto("900015", imei=imei_ficticio(15), status="Stock"),
        producto("900016", imei=imei_ficticio(16), sede="RMA", status="Vendido"),
        # Sin producto_id: se descarta y se cuenta.
        producto("", imei=imei_ficticio(17), sede="Alippi"),
        # producto_id repetido: no se aplica.
        producto("900018", imei=imei_ficticio(18)),
        producto("900018", imei=imei_ficticio(19)),
        # Eliminado en Gestion RT: no se agrega.
        producto("900020", imei=imei_ficticio(20), sede="Alippi", eliminado="yes"),
        # Fecha de alta que no se puede interpretar.
        producto("900021", tp=TP_16, imei=imei_ficticio(21), sede="Fisherton",
                 creado_en="ayer"),
        # Coincide con una Orden RT manual (referencia) y otra por IMEI.
        producto(ID_CON_REFERENCIA, tp=TP_12_PRO_MAX, imei=IMEI_CON_ORDEN,
                 sede="eCommerce"),
    ]  # fmt: skip


def tipos_base() -> list[list]:
    """TipoProducto ficticio: el de ``catalogo_ventas`` mas un eliminado."""
    return [
        *catalogo_ventas.filas_base(),
        catalogo_ventas.fila("11", "Nada", "64gb", "white", eliminado=True),
    ]


def tabla(filas: list[list] | None = None) -> list[list]:
    return [list(COLUMNAS), *(productos_base() if filas is None else filas)]


def _csv(filas: list[list]) -> str:
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    for registro in filas:
        escritor.writerow(
            [
                ("TRUE" if valor else "FALSE")
                if isinstance(valor, bool)
                else valor
                for valor in registro
            ]
        )
    return buffer.getvalue()


def escribir_csv(ruta: Path, filas: list[list] | None = None) -> Path:
    """Producto como CSV (adaptador de archivo)."""
    ruta.write_text(_csv(tabla(filas)), encoding="utf-8")
    return ruta


def escribir_tipos(ruta: Path, filas: list[list] | None = None) -> Path:
    """TipoProducto como CSV."""
    return catalogo_ventas.escribir_csv(
        ruta, tipos_base() if filas is None else filas
    )


def columnas(filas: list[list] | None = None) -> list[list]:
    """La tabla por columnas (``majorDimension=COLUMNS``), encabezado
    incluido, sin las celdas vacias del final de cada columna."""
    completa = tabla(filas)
    resultado = []
    for indice in range(len(COLUMNAS)):
        columna = [
            fila[indice] if indice < len(fila) else "" for fila in completa
        ]
        while columna and columna[-1] == "":
            columna.pop()
        resultado.append(columna)
    return resultado


def respuesta_tipos() -> bytes:
    """``values.get`` de raw_TipoProducto (filas)."""
    return catalogo_ventas.respuesta_sheets(tipos_base())


def respuesta_json(cuerpo: dict) -> bytes:
    return json.dumps(cuerpo).encode("utf-8")
