"""Importacion masiva de precios por modelo (DEC-AJ-13, BF-02). Logica pura.

Recibe la matriz de celdas de la planilla (la primera hoja del ``.xlsx``,
el CSV o las celdas pegadas de Google Sheets o Excel, ya leidas por
``integraciones/planillas.py``) y el catalogo vigente, y arma la vista
previa: los precios nuevos y los que cambian, los errores con la celda en
notacion de planilla («C5») y los avisos. No lee archivos ni la base.

Forma de la planilla (D-13.1): una matriz con los modelos en las filas y
los Tipos de Reparacion en las columnas, identificados por sus codigos
estables, no por los nombres:

- **Encabezado:** la primera fila con contenido.
- **Columna clave:** la primera cuyo encabezado es «Modelo» (sin
  distinguir mayusculas ni acentos; tambien «Codigo del modelo»); si
  ninguna se llama asi, la primera columna. Cada fila lleva el codigo del
  modelo (``MOD-0012``); se toma el codigo del principio de la celda, asi
  que «MOD-0012 · Apple iPhone 15» tambien vale.
- **Columnas de precios:** las que empiezan con un codigo de Tipo
  (``TR-001`` o «TR-001 · Cambio de bateria»).
- **Columnas ignoradas:** cualquier otra (por ejemplo «Nombre del
  modelo»). La vista previa las informa, para que un encabezado mal escrito
  no pase inadvertido.

Reglas (D-13.2, D-13.3 y sus precisiones):

- Solo modelos existentes de marca Apple y vigentes, y Tipos existentes,
  vigentes y con precio por modelo. Otra marca, un codigo desconocido, un
  modelo dado de baja, un Tipo de precio unico, «Otros» o un Tipo dado de
  baja son errores de la fila o de la columna, aunque sus celdas esten
  vacias. Nada se crea.
- Una celda vacia no cambia nada. Quitar un precio se hace en la edicion
  individual.
- Importes: ``80000``, ``80000.50``, ``80000,50``, ``80.000``,
  ``80.000,50`` o ``$ 80.000``. La coma separa decimales y el punto los
  miles; un solo punto seguido de uno o dos digitos es el separador
  decimal. «80,000» es ambiguo y se rechaza. Hasta dos decimales y nunca
  negativos.
- Modelos o Tipos repetidos son errores.
- Cada celda valida queda NUEVO (sin precio vigente), CAMBIA o SIN_CAMBIO.
- Avisos que no bloquean: una variacion de mas del 50 % y un precio 0.
- Se aplica solo sin errores y con algun cambio, todo o nada.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel

from app.domain.models import (
    FormatoImportacion,
    ModeloEquipo,
    PrecioTipoModelo,
    TipoReparacion,
)
from app.domain.models.catalogos import TIPO_REPARACION_OTROS

# Una celda leida: texto, un numero (de una celda numerica del .xlsx) o
# nada.
Valor = str | Decimal | None

# Limites de una importacion (las filas de modelos debajo del encabezado,
# las columnas y las celdas con contenido).
MAX_FILAS = 500
MAX_COLUMNAS = 100
MAX_CELDAS = 20_000

MARCA_IMPORTABLE = "apple"
VARIACION_AVISO = Decimal("0.5")
CENTAVO = Decimal("0.01")

_CODIGO_TIPO = re.compile(r"^(TR-[0-9A-Z]+)(?![0-9A-Z])")
_CODIGO_MODELO = re.compile(r"^(MOD-[0-9A-Z]+)(?![0-9A-Z])")
_ENCABEZADOS_CLAVE = {"modelo", "codigo modelo", "codigo del modelo"}
_MILES = re.compile(r"^[1-9]\d{0,2}(\.\d{3})+$")
_ESPACIOS = re.compile(r"[\s  ]+")


class EstadoPrecio(str, Enum):
    NUEVO = "NUEVO"
    CAMBIA = "CAMBIA"
    SIN_CAMBIO = "SIN_CAMBIO"


class Observacion(BaseModel):
    """Un error o un aviso; ``celda`` en notacion de planilla («C5»)."""

    celda: str | None = None
    mensaje: str


class PrecioImportado(BaseModel):
    """Un precio nuevo o que cambia, con la celda de donde salio."""

    celda: str
    modelo_equipo_id: str
    modelo: str
    tipo_reparacion_id: str
    tipo: str
    anterior: Decimal | None = None
    nuevo: Decimal
    estado: EstadoPrecio


class ColumnaIgnorada(BaseModel):
    columna: str
    encabezado: str


class ResumenImportacion(BaseModel):
    modelos: int = 0
    tipos: int = 0
    nuevos: int = 0
    actualizados: int = 0
    sin_cambio: int = 0
    vacias: int = 0
    errores: int = 0
    avisos: int = 0


class VistaPreviaImportacion(BaseModel):
    """Lo que aplicaria la importacion, sin escribir nada.

    ``cambios`` trae solo los precios NUEVO y CAMBIA; los que no cambian se
    cuentan en el resumen. ``aplicable``: sin errores y con algun cambio.
    """

    formato: FormatoImportacion
    nombre_archivo: str | None = None
    resumen: ResumenImportacion
    cambios: list[PrecioImportado]
    errores: list[Observacion]
    avisos: list[Observacion]
    columnas_ignoradas: list[ColumnaIgnorada]
    aplicable: bool


# --- Celdas e importes -------------------------------------------------------


def letra_de_columna(columna: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    letras = ""
    while columna:
        columna, resto = divmod(columna - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return letras


def celda(fila: int, columna: int) -> str:
    """La coordenada de planilla de la fila y la columna (desde 1): «C5»."""
    return f"{letra_de_columna(columna)}{fila}"


def texto_de_celda(valor: Valor) -> str:
    """El contenido de la celda como texto, sin espacios al borde."""
    if valor is None:
        return ""
    if isinstance(valor, Decimal):
        return format(valor, "f")
    return valor.replace("﻿", "").strip()


class ImporteInvalidoError(ValueError):
    """El texto no es un importe valido; el mensaje explica por que."""


def parsear_importe(valor: Valor) -> Decimal:
    """El importe de una celda con contenido, con dos decimales.

    Acepta el numero de una celda numerica y los textos ``80000``,
    ``80000.50``, ``80000,50``, ``80.000``, ``80.000,50`` y ``$ 80.000``.
    ``ImporteInvalidoError`` si es negativo, ambiguo («80,000»), con mas de
    dos decimales o no es un importe.
    """
    if isinstance(valor, Decimal):
        numero = valor
    else:
        numero = _importe_de_texto(texto_de_celda(valor))
    if not numero.is_finite():
        raise ImporteInvalidoError("no es un importe")
    if numero < 0:
        raise ImporteInvalidoError("el precio no puede ser negativo")
    if numero != numero.quantize(CENTAVO):
        raise ImporteInvalidoError("admite hasta dos decimales")
    return numero.quantize(CENTAVO)


def _importe_de_texto(original: str) -> Decimal:
    texto = _ESPACIOS.sub("", original)
    if texto.startswith(("-", "−")) or texto.endswith("-"):
        raise ImporteInvalidoError("el precio no puede ser negativo")
    if texto.startswith("$"):
        texto = texto[1:]
    if texto.startswith(("-", "−")):
        raise ImporteInvalidoError("el precio no puede ser negativo")
    if not texto or not re.fullmatch(r"[\d.,]+", texto):
        raise ImporteInvalidoError(f"«{original}» no es un importe")
    if "," in texto:
        if texto.count(",") > 1:
            raise ImporteInvalidoError(
                f"«{original}» no es un importe: la coma separa los "
                "decimales y el punto los miles (80.000,50)"
            )
        entero, decimales = texto.split(",")
        if "." in decimales:
            raise ImporteInvalidoError(
                f"«{original}» no es un importe: usa 80.000,50 o 80000.50"
            )
        if len(decimales) == 3 and "." not in entero:
            raise ImporteInvalidoError(
                f"«{original}» es ambiguo: escribi 80000 o 80.000 para los "
                "miles y la coma solo para los decimales"
            )
        if not decimales or not entero:
            raise ImporteInvalidoError(f"«{original}» no es un importe")
        if len(decimales) > 2:
            raise ImporteInvalidoError("admite hasta dos decimales")
        return Decimal(f"{_entero(entero, original)}.{decimales}")
    if texto.count(".") == 1:
        entero, decimales = texto.split(".")
        if not entero or not decimales:
            raise ImporteInvalidoError(f"«{original}» no es un importe")
        if len(decimales) == 3 and _MILES.fullmatch(texto):
            # «80.000»: el punto de los miles (formato argentino).
            return Decimal(entero + decimales)
        if len(decimales) > 2:
            raise ImporteInvalidoError("admite hasta dos decimales")
        return Decimal(f"{entero}.{decimales}")
    return Decimal(_entero(texto, original))


def _entero(texto: str, original: str) -> str:
    """La parte entera, sin los puntos de los miles (bien agrupados)."""
    if "." not in texto:
        return texto
    if not _MILES.fullmatch(texto):
        raise ImporteInvalidoError(
            f"«{original}» no es un importe: los miles van de a tres "
            "digitos (1.234.567)"
        )
    return texto.replace(".", "")


def _normalizado(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(
        c for c in sin_acentos if not unicodedata.combining(c)
    )
    return " ".join(sin_acentos.casefold().split())


def _pesos(valor: Decimal) -> str:
    return (
        f"$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )


# --- Que se importa ----------------------------------------------------------


def es_modelo_importable(modelo: ModeloEquipo) -> bool:
    """Solo iPhone por ahora (D-13.2): marca Apple."""
    return _normalizado(modelo.marca) == MARCA_IMPORTABLE


def es_tipo_importable(tipo: TipoReparacion) -> bool:
    """Tipos vigentes con precio por modelo («Otros» nunca)."""
    return (
        tipo.precio_por_modelo
        and tipo.activo
        and tipo.id.upper() != TIPO_REPARACION_OTROS
    )


def matriz_plantilla(
    tipos: Sequence[TipoReparacion], modelos: Sequence[ModeloEquipo]
) -> list[list[Valor]]:
    """La plantilla con los precios vigentes (D-13.1): los modelos Apple
    vigentes en las filas (codigo y nombre), los Tipos vigentes con precio
    por modelo en las columnas («TR-001 · Cambio de bateria») y el precio
    vigente de cada combinacion, o vacia si no tiene."""
    columnas = sorted(
        (t for t in tipos if es_tipo_importable(t)), key=lambda t: t.id
    )
    filas = [m for m in modelos if m.activo and es_modelo_importable(m)]
    matriz: list[list[Valor]] = [
        ["Modelo", "Nombre del modelo"]
        + [f"{t.id} · {t.nombre}" for t in columnas]
    ]
    for modelo in filas:
        matriz.append(
            [modelo.id, modelo.nombre]
            + [
                _con_centavos(t.precios_modelo.get(modelo.id))
                for t in columnas
            ]
        )
    return matriz


def _con_centavos(valor: Decimal | None) -> Decimal | None:
    return None if valor is None else valor.quantize(CENTAVO)


# --- Vista previa ------------------------------------------------------------


class _Analisis:
    def __init__(self) -> None:
        self.errores: list[Observacion] = []
        self.avisos: list[Observacion] = []

    def error(self, coordenada: str | None, mensaje: str) -> None:
        self.errores.append(Observacion(celda=coordenada, mensaje=mensaje))

    def aviso(self, coordenada: str | None, mensaje: str) -> None:
        self.avisos.append(Observacion(celda=coordenada, mensaje=mensaje))


def previsualizar(
    matriz: Sequence[Sequence[Valor]],
    *,
    tipos: Mapping[str, TipoReparacion],
    modelos: Mapping[str, ModeloEquipo],
    formato: FormatoImportacion,
    nombre_archivo: str | None = None,
) -> VistaPreviaImportacion:
    """Valida la matriz contra el catalogo vigente y clasifica cada precio.

    ``tipos``: los Tipos por codigo, con sus precios por modelo vigentes;
    ``modelos``: los modelos por codigo, vigentes o no. Junta todos los
    errores (no se detiene en el primero).
    """
    analisis = _Analisis()
    resumen = ResumenImportacion()
    cambios: list[PrecioImportado] = []
    ignoradas: list[ColumnaIgnorada] = []

    def vista() -> VistaPreviaImportacion:
        resumen.errores = len(analisis.errores)
        resumen.avisos = len(analisis.avisos)
        return VistaPreviaImportacion(
            formato=formato,
            nombre_archivo=nombre_archivo,
            resumen=resumen,
            cambios=cambios,
            errores=analisis.errores,
            avisos=analisis.avisos,
            columnas_ignoradas=ignoradas,
            aplicable=not analisis.errores and bool(cambios),
        )

    filas = [[texto_de_celda(v) for v in fila] for fila in matriz]
    inicio = next((i for i, fila in enumerate(filas) if any(fila)), None)
    if inicio is None:
        analisis.error(None, "La planilla esta vacia.")
        return vista()
    if len(filas) - inicio - 1 > MAX_FILAS:
        analisis.error(
            None,
            f"La planilla tiene mas de {MAX_FILAS} filas de modelos: "
            "dividila en varias importaciones.",
        )
        return vista()
    ancho = max(
        (max((i + 1 for i, v in enumerate(fila) if v), default=0))
        for fila in filas
    )
    if ancho > MAX_COLUMNAS:
        analisis.error(
            None, f"La planilla tiene mas de {MAX_COLUMNAS} columnas."
        )
        return vista()
    if sum(1 for fila in filas for v in fila if v) > MAX_CELDAS:
        analisis.error(
            None, f"La planilla tiene mas de {MAX_CELDAS} celdas con datos."
        )
        return vista()

    numero_encabezado = inicio + 1
    encabezado = filas[inicio] + [""] * (ancho - len(filas[inicio]))
    cuerpo = filas[inicio + 1 :]

    def valor(fila: list[str], indice: int) -> str:
        return fila[indice] if indice < len(fila) else ""

    clave = next(
        (
            i
            for i, titulo in enumerate(encabezado)
            if _normalizado(titulo) in _ENCABEZADOS_CLAVE
        ),
        0,
    )

    # Columnas: los Tipos (validos o no) y las ignoradas.
    columnas_tipo: dict[int, str] = {}
    validas: dict[int, TipoReparacion] = {}
    vistos_tipos: dict[str, str] = {}
    for indice, titulo in enumerate(encabezado):
        if indice == clave:
            continue
        coordenada = celda(numero_encabezado, indice + 1)
        encontrado = _CODIGO_TIPO.match(titulo.upper())
        if encontrado is None:
            con_datos = any(valor(fila, indice) for fila in cuerpo)
            if titulo or con_datos:
                ignoradas.append(
                    ColumnaIgnorada(
                        columna=letra_de_columna(indice + 1),
                        encabezado=titulo,
                    )
                )
            continue
        codigo = encontrado.group(1)
        columnas_tipo[indice] = codigo
        if codigo in vistos_tipos:
            analisis.error(
                coordenada,
                f"El Tipo {codigo} esta repetido (tambien en "
                f"{vistos_tipos[codigo]}).",
            )
            continue
        vistos_tipos[codigo] = coordenada
        tipo = tipos.get(codigo)
        if codigo == TIPO_REPARACION_OTROS:
            analisis.error(
                coordenada,
                "«Otros» lleva un precio manual por trabajo: no tiene "
                "precios por modelo.",
            )
        elif tipo is None:
            analisis.error(
                coordenada, f"No existe el Tipo de Reparacion {codigo}."
            )
        elif not tipo.activo:
            analisis.error(
                coordenada, f"El Tipo {codigo} ({tipo.nombre}) esta de baja."
            )
        elif not tipo.precio_por_modelo:
            analisis.error(
                coordenada,
                f"El Tipo {codigo} ({tipo.nombre}) tiene precio unico: "
                "marcalo con precio por modelo en Tipos de reparacion.",
            )
        else:
            validas[indice] = tipo
    if not columnas_tipo:
        analisis.error(
            None,
            "El encabezado no tiene columnas de Tipos de Reparacion: cada "
            "una tiene que empezar con su codigo (por ejemplo TR-001). "
            "Descarga la plantilla para ver la forma.",
        )
    resumen.tipos = len(validas)

    # Filas: los modelos.
    vistos_modelos: dict[str, str] = {}
    for desplazamiento, fila in enumerate(cuerpo):
        numero = numero_encabezado + 1 + desplazamiento
        coordenada = celda(numero, clave + 1)
        texto_clave = valor(fila, clave)
        con_precios = any(valor(fila, i) for i in columnas_tipo)
        if not texto_clave:
            if con_precios:
                analisis.error(
                    coordenada, "Falta el codigo del modelo (MOD-0001)."
                )
            continue
        encontrado = _CODIGO_MODELO.match(texto_clave.upper())
        if encontrado is None:
            analisis.error(
                coordenada,
                f"«{texto_clave}» no es un codigo de modelo (MOD-0001).",
            )
            continue
        codigo = encontrado.group(1)
        if codigo in vistos_modelos:
            analisis.error(
                coordenada,
                f"El modelo {codigo} esta repetido (tambien en "
                f"{vistos_modelos[codigo]}).",
            )
            continue
        vistos_modelos[codigo] = coordenada
        modelo = modelos.get(codigo)
        if modelo is None:
            analisis.error(coordenada, f"No existe el modelo {codigo}.")
            continue
        if not es_modelo_importable(modelo):
            analisis.error(
                coordenada,
                f"{codigo} ({modelo.nombre}) no es de marca Apple: la "
                "importacion es solo para iPhone; sus precios se cargan "
                "en la edicion individual.",
            )
            continue
        if not modelo.activo:
            analisis.error(
                coordenada,
                f"El modelo {codigo} ({modelo.nombre}) esta de baja: quita "
                "la fila o reactivalo en Modelos de equipo.",
            )
            continue
        resumen.modelos += 1
        for indice, tipo in validas.items():
            contenido = valor(fila, indice)
            lugar = celda(numero, indice + 1)
            if not contenido:
                resumen.vacias += 1
                continue
            try:
                nuevo = parsear_importe(
                    matriz_valor(matriz, inicio + 1 + desplazamiento, indice)
                )
            except ImporteInvalidoError as error:
                analisis.error(lugar, f"Importe invalido: {error}.")
                continue
            anterior = tipo.precios_modelo.get(codigo)
            if anterior is not None and anterior == nuevo:
                resumen.sin_cambio += 1
                continue
            estado = (
                EstadoPrecio.NUEVO if anterior is None else EstadoPrecio.CAMBIA
            )
            if estado is EstadoPrecio.NUEVO:
                resumen.nuevos += 1
            else:
                resumen.actualizados += 1
            cambios.append(
                PrecioImportado(
                    celda=lugar,
                    modelo_equipo_id=codigo,
                    modelo=modelo.nombre,
                    tipo_reparacion_id=tipo.id,
                    tipo=tipo.nombre,
                    anterior=_con_centavos(anterior),
                    nuevo=nuevo,
                    estado=estado,
                )
            )
            if anterior and abs(nuevo - anterior) / anterior > VARIACION_AVISO:
                analisis.aviso(
                    lugar,
                    f"{tipo.id} para {codigo} cambia mas del 50 %: de "
                    f"{_pesos(anterior)} a {_pesos(nuevo)}.",
                )
            if nuevo == 0:
                analisis.aviso(
                    lugar, f"{tipo.id} para {codigo} queda con precio 0."
                )
    return vista()


def matriz_valor(
    matriz: Sequence[Sequence[Valor]], fila: int, columna: int
) -> Valor:
    """El valor original de la celda (un numero del .xlsx no pasa por el
    texto)."""
    original = matriz[fila]
    return original[columna] if columna < len(original) else None


def precios_a_aplicar(
    vista: VistaPreviaImportacion,
) -> list[PrecioTipoModelo]:
    """Los precios NUEVO y CAMBIA para ``guardar_precios_modelo``. Nunca
    lleva un precio vacio: una celda vacia no retira nada."""
    return [
        PrecioTipoModelo(
            tipo_reparacion_id=cambio.tipo_reparacion_id,
            modelo_equipo_id=cambio.modelo_equipo_id,
            precio=cambio.nuevo,
        )
        for cambio in vista.cambios
    ]
