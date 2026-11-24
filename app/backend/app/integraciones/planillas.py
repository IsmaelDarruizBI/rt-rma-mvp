"""Lectura y escritura de planillas: Excel ``.xlsx``, CSV y celdas pegadas.

La usa la importacion de precios por modelo (DEC-AJ-13). Convierte el
archivo en una matriz de celdas (texto, numero o vacia) y la matriz de la
plantilla en un archivo. No sabe nada de precios: eso es de
``services/importacion_precios.py``.

- **XLSX:** ``openpyxl`` en modo de solo lectura y solo los valores (de una
  formula, el ultimo calculado). Solo la primera hoja. Las celdas numericas
  llegan como numero, sin pasar por el formato de la pantalla.
- **CSV:** UTF-8, con o sin BOM; si no es UTF-8, Windows-1252 (el «CSV» de
  Excel en Windows). El separador se detecta en la primera fila con
  contenido, entre tabulacion, punto y coma y coma: gana el que la divide
  en mas columnas.
- **Texto pegado:** lo que copia Google Sheets o Excel, separado por
  tabulaciones (con la misma deteccion).

Limites: ``MAX_BYTES`` del archivo; un ``.xlsx`` no puede descomprimirse a
mas de ``MAX_BYTES_DESCOMPRIMIDOS`` (protege de un archivo comprimido
malicioso); se leen como mucho ``max_filas`` filas y ``max_columnas``
columnas, mas una para saber si las supera.
"""

import csv
import io
import zipfile
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from app.domain.models import FormatoImportacion

MAX_BYTES = 2 * 1024 * 1024
MAX_BYTES_DESCOMPRIMIDOS = 30 * 1024 * 1024

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TIPO_CSV = "text/csv"
_TIPOS_CSV = {
    "text/csv",
    "application/csv",
    "text/comma-separated-values",
    # Windows declara asi los .csv si Excel esta instalado.
    "application/vnd.ms-excel",
}
_TIPOS_TEXTO = {"text/plain", "text/tab-separated-values"}
_FIRMA_ZIP = b"PK\x03\x04"
_FIRMA_XLS = b"\xd0\xcf\x11\xe0"
_SEPARADORES = ("\t", ";", ",")

Celda = str | Decimal | None


class PlanillaIlegibleError(ValueError):
    """El archivo no se puede leer como planilla; el mensaje lo explica."""


def formato_de(
    contenido: bytes, tipo_contenido: str | None
) -> FormatoImportacion:
    """El formato por el contenido y el ``Content-Type`` declarado.

    Un ``.xlsx`` se reconoce por su contenido (es un ZIP), declare lo que
    declare. El texto es CSV o texto pegado segun el tipo declarado.
    """
    tipo = (tipo_contenido or "").split(";")[0].strip().lower()
    if contenido.startswith(_FIRMA_ZIP):
        return FormatoImportacion.XLSX
    if contenido.startswith(_FIRMA_XLS):
        raise PlanillaIlegibleError(
            "El archivo es un Excel antiguo (.xls): guardalo como .xlsx o "
            "como CSV."
        )
    if tipo == TIPO_XLSX:
        raise PlanillaIlegibleError("El archivo no es un .xlsx valido.")
    if tipo in _TIPOS_CSV or tipo in ("", "application/octet-stream"):
        return FormatoImportacion.CSV
    if tipo in _TIPOS_TEXTO:
        return FormatoImportacion.TEXTO
    raise PlanillaIlegibleError(
        "Formato no admitido: subi un .xlsx o un .csv, o pega las celdas "
        "copiadas de la planilla."
    )


def leer_planilla(
    contenido: bytes,
    formato: FormatoImportacion,
    *,
    max_filas: int,
    max_columnas: int,
) -> list[list[Celda]]:
    """La matriz de celdas de la planilla (la primera hoja de un .xlsx).

    Lee hasta ``max_filas`` + 1 filas y ``max_columnas`` + 1 columnas: con
    una de mas alcanza para saber si la planilla supera el limite.
    """
    if not contenido.strip():
        raise PlanillaIlegibleError("El archivo esta vacio.")
    if len(contenido) > MAX_BYTES:
        raise PlanillaIlegibleError(
            f"El archivo supera los {MAX_BYTES // (1024 * 1024)} MB."
        )
    if formato is FormatoImportacion.XLSX:
        return _leer_xlsx(contenido, max_filas + 1, max_columnas + 1)
    return _leer_texto(contenido, max_filas + 1, max_columnas + 1)


def _leer_xlsx(
    contenido: bytes, filas: int, columnas: int
) -> list[list[Celda]]:
    # Importacion diferida: solo la necesita quien lee o escribe un .xlsx.
    from openpyxl import load_workbook

    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as archivo:
            descomprimido = sum(i.file_size for i in archivo.infolist())
        if descomprimido > MAX_BYTES_DESCOMPRIMIDOS:
            raise PlanillaIlegibleError(
                "El .xlsx es demasiado grande: deja solo la hoja de precios."
            )
        libro = load_workbook(
            io.BytesIO(contenido), read_only=True, data_only=True
        )
    except PlanillaIlegibleError:
        raise
    except Exception as error:  # zip roto, XML invalido, no es un libro
        raise PlanillaIlegibleError(
            "No se pudo leer el .xlsx: abrilo en Excel o Google Sheets y "
            "volve a guardarlo, o subilo como CSV."
        ) from error
    try:
        if not libro.worksheets:
            raise PlanillaIlegibleError("El .xlsx no tiene hojas.")
        hoja = libro.worksheets[0]
        matriz: list[list[Celda]] = []
        for fila in hoja.iter_rows(
            min_row=1, max_row=filas, max_col=columnas, values_only=True
        ):
            matriz.append([_celda_xlsx(v) for v in fila])
        return _sin_vacias_al_final(matriz)
    except PlanillaIlegibleError:
        raise
    except Exception as error:
        raise PlanillaIlegibleError(
            "No se pudo leer la primera hoja del .xlsx."
        ) from error
    finally:
        libro.close()


def _celda_xlsx(valor: object) -> Celda:
    if valor is None:
        return None
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, float):
        try:
            numero = Decimal(repr(valor))
        except InvalidOperation:
            return str(valor)
        # Un binario como 80000.09999999999 es 80000.10: se redondea si
        # esta a menos de una millonesima de los centavos.
        centavos = numero.quantize(Decimal("0.01"))
        if abs(numero - centavos) < Decimal("0.000001"):
            return centavos
        return numero
    if isinstance(valor, Decimal):
        return valor
    return str(valor)


def _decodificar(contenido: bytes) -> str:
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("cp1252", errors="replace")


def _separador(texto: str) -> str:
    primera = next(
        (linea for linea in texto.splitlines() if linea.strip()), ""
    )
    mejor, columnas = "\t", 0
    for candidato in _SEPARADORES:
        campos = next(csv.reader([primera], delimiter=candidato), [])
        if len(campos) > columnas:
            mejor, columnas = candidato, len(campos)
    return mejor


def _leer_texto(
    contenido: bytes, filas: int, columnas: int
) -> list[list[Celda]]:
    texto = _decodificar(contenido)
    if "\x00" in texto:
        raise PlanillaIlegibleError(
            "El archivo no es texto: subi un .xlsx o un .csv."
        )
    lector = csv.reader(
        io.StringIO(texto, newline=""), delimiter=_separador(texto)
    )
    matriz: list[list[Celda]] = []
    try:
        for fila in lector:
            if len(matriz) >= filas:
                break
            matriz.append([c or None for c in fila[:columnas]])
    except csv.Error as error:
        raise PlanillaIlegibleError(
            f"No se pudo leer el texto: {error}."
        ) from error
    return _sin_vacias_al_final(matriz)


def _sin_vacias_al_final(matriz: list[list[Celda]]) -> list[list[Celda]]:
    """Sin las celdas vacias al final de cada fila ni las filas vacias del
    final (un .xlsx completa cada fila hasta la ultima columna pedida)."""

    def vacia(valor: Celda) -> bool:
        return valor is None or valor == ""

    recortada = []
    for fila in matriz:
        fin = len(fila)
        while fin and vacia(fila[fin - 1]):
            fin -= 1
        recortada.append(list(fila[:fin]))
    while recortada and not recortada[-1]:
        recortada.pop()
    return recortada


# --- Plantilla ---------------------------------------------------------------


def _texto_csv(valor: Celda) -> str:
    if valor is None:
        return ""
    if isinstance(valor, Decimal):
        # Formato argentino, sin separador de miles: 80000,00.
        return f"{valor:.2f}".replace(".", ",")
    return valor


def escribir_csv(matriz: Sequence[Sequence[Celda]]) -> bytes:
    """CSV para Excel en castellano: UTF-8 con BOM, punto y coma y coma
    decimal."""
    salida = io.StringIO(newline="")
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    for fila in matriz:
        escritor.writerow([_texto_csv(v) for v in fila])
    return salida.getvalue().encode("utf-8-sig")


INSTRUCCIONES = (
    "Importacion de precios por modelo",
    "",
    "Se importa solo la primera hoja.",
    "Cada fila es un modelo, identificado por su codigo (columna Modelo).",
    "Cada columna de precios es un Tipo de Reparacion, identificado por el "
    "codigo del principio del encabezado (TR-001).",
    "Los nombres son solo de referencia: se ignoran.",
    "Una celda vacia no cambia el precio actual. Para quitar un precio, "
    "usa la edicion individual en Configuracion.",
    "Importes: 80000, 80000,50 u 80.000,50 (hasta dos decimales).",
    "No se crean modelos ni Tipos: los que no existen son errores.",
    "Antes de aplicar se muestra la vista previa; se aplica todo o nada.",
)


def escribir_xlsx(matriz: Sequence[Sequence[Celda]]) -> bytes:
    """La plantilla en .xlsx: la hoja «Precios» con el encabezado fijo y
    los importes con formato de miles, y una hoja de instrucciones."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Precios"
    for fila in matriz:
        hoja.append(list(fila))
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for fila in hoja.iter_rows(min_row=2, min_col=3):
        for celda in fila:
            celda.number_format = "#,##0.00"
    hoja.freeze_panes = "C2"
    hoja.column_dimensions["A"].width = 12
    hoja.column_dimensions["B"].width = 32
    for indice in range(3, len(matriz[0]) + 1 if matriz else 3):
        letra = hoja.cell(row=1, column=indice).column_letter
        hoja.column_dimensions[letra].width = 24
    ayuda = libro.create_sheet("Instrucciones")
    for linea in INSTRUCCIONES:
        ayuda.append([linea])
    ayuda.column_dimensions["A"].width = 100
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
