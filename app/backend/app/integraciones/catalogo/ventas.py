"""Formato de la tabla TipoProducto de Gestion de Ventas.

Lo comparten todos los adaptadores que leen esa tabla, sea cual sea su
almacenamiento: hoy la hoja ``raw_TipoProducto`` de Google Sheets; manana
una tabla de Cloud SQL o BigQuery con las mismas columnas. Este modulo es
el unico que conoce los nombres de columna y las convenciones de Ventas:

    tp_id          identificador del tipo de producto: se copia TAL CUAL
    tp_categoria   IPHONE, SMARTPHONE, ACCESORIOS, ...
    tp_subcat_1    IPHONE USADOS, IPHONE NUEVOS, ... (el filtro)
    tp_gp          grupo de productos
    tp_generator   TRUE: registro que genera variantes, no es un equipo
    tp_modelo      descripcion completa («iPhone 12 Pro Max 128gb black»)
    tp_number      modelo («12», «SE 2020», «Xr»)
    tp_promaxness  variante; «Nada» es la version estandar
    tp_gb          capacidad («128gb», «1tb»)
    tp_color       color; «cualquier_color» es un producto sin color
                   especifico
    tp_eliminado   «yes»: eliminado en Ventas

Las demas columnas (precios, descuentos, ``tp_eliminado_por`` -un email-,
fechas) no se copian: RMA no las usa.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.domain.models import ProductoInformado

from .puerto import (
    CatalogoOrigenInvalidoError,
    FiltroCatalogo,
    LecturaCatalogo,
)

COLUMNA_ID = "tp_id"
COLUMNA_SUBCATEGORIA = "tp_subcat_1"
COLUMNAS = (
    COLUMNA_ID,
    "tp_categoria",
    COLUMNA_SUBCATEGORIA,
    "tp_gp",
    "tp_generator",
    "tp_modelo",
    "tp_number",
    "tp_promaxness",
    "tp_gb",
    "tp_color",
    "tp_eliminado",
)
# Se guardan en el producto, tal como vienen, para auditoria.
COLUMNAS_ATRIBUTOS = ("tp_number", "tp_promaxness", "tp_gb", "tp_color")

VARIANTE_ESTANDAR = "nada"
COLOR_GENERICO = "cualquier_color"
_VERDADEROS = frozenset({"true", "yes", "si", "sí", "1", "x"})
_CAPACIDAD = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(gb|tb)$", re.IGNORECASE)


def _texto(valor: Any) -> str:
    """Una celda como texto, sin espacios al borde (vacia: "")."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "TRUE" if valor else "FALSE"
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def _verdadero(valor: str) -> bool:
    return valor.casefold() in _VERDADEROS


def etiqueta_capacidad(valor: str) -> str | None:
    """«128gb» -> «128 GB», «1tb» -> «1 TB»; otro formato, tal cual."""
    if not valor:
        return None
    coincide = _CAPACIDAD.match(valor.replace(" ", ""))
    if not coincide:
        return valor
    return f"{coincide.group(1)} {coincide.group(2).upper()}"


def etiqueta_color(valor: str) -> str | None:
    """«deep_purple» -> «Deep Purple»; «black titanium» -> «Black
    Titanium». El generico («cualquier_color») no es un color."""
    if not valor or valor.casefold() == COLOR_GENERICO:
        return None
    palabras = valor.replace("_", " ").split()
    return " ".join(palabra[:1].upper() + palabra[1:] for palabra in palabras)


def _modelo(descripcion: str, numero: str) -> str | None:
    """El modelo sin variante, capacidad ni color: «iPhone 12».

    Es el comienzo de ``tp_modelo`` hasta ``tp_number`` inclusive. Si el
    numero no aparece en la descripcion, el numero solo.
    """
    if not numero:
        return None
    coincide = re.search(
        rf"(?<!\w){re.escape(numero)}(?!\w)", descripcion, re.IGNORECASE
    )
    if not coincide:
        return numero
    return descripcion[: coincide.end()].strip()


def producto_desde_valores(
    valores: Mapping[str, str],
    *,
    marcas: Mapping[str, str],
) -> ProductoInformado:
    """Un registro de TipoProducto (ya como texto) en terminos de RMA.

    ``marcas``: marca por ``tp_categoria`` (``RMA_CATALOGO_MARCAS``); el
    catalogo de Ventas no tiene una columna de marca.
    """
    categoria = valores.get("tp_categoria", "")
    numero = valores.get("tp_number", "")
    variante = valores.get("tp_promaxness", "")
    capacidad = valores.get("tp_gb", "")
    color = valores.get("tp_color", "")
    descripcion = " ".join(valores.get("tp_modelo", "").split())
    marca = {
        clave.strip().casefold(): nombre for clave, nombre in marcas.items()
    }.get(categoria.casefold())
    faltantes = tuple(
        campo
        for campo, valor in (
            ("marca", marca),
            ("modelo", numero),
            ("variante", variante),
            ("capacidad", capacidad),
            ("color", color),
        )
        if not valor
    )
    return ProductoInformado(
        tipo_producto_id=valores[COLUMNA_ID],
        descripcion=descripcion or valores[COLUMNA_ID],
        categoria=categoria or None,
        subcategoria=valores.get(COLUMNA_SUBCATEGORIA) or None,
        grupo=valores.get("tp_gp") or None,
        marca=marca,
        modelo=_modelo(descripcion, numero),
        variante=(
            None
            if not variante or variante.casefold() == VARIANTE_ESTANDAR
            else variante
        ),
        capacidad=etiqueta_capacidad(capacidad),
        color=etiqueta_color(color),
        color_generico=color.casefold() == COLOR_GENERICO,
        generador=_verdadero(valores.get("tp_generator", "")),
        eliminado=_verdadero(valores.get("tp_eliminado", "")),
        faltantes=faltantes,
        valores_origen={
            columna: valores.get(columna, "") for columna in COLUMNAS_ATRIBUTOS
        },
    )


def lectura_desde_tabla(
    encabezados: Sequence[Any],
    filas: Iterable[Sequence[Any]],
    filtro: FiltroCatalogo,
    *,
    marcas: Mapping[str, str],
) -> LecturaCatalogo:
    """La tabla (encabezados y filas, como las da el origen) filtrada.

    Las columnas se ubican por NOMBRE, no por posicion: Ventas puede
    agregar o reordenar columnas sin romper la sincronizacion. Si falta
    una de las que RMA usa, se rechaza todo (``CatalogoOrigenInvalidoError``).
    Las filas vacias se ignoran; las que pasan el filtro sin ``tp_id``, se
    descartan y se cuentan.
    """
    nombres = [_texto(encabezado) for encabezado in encabezados]
    faltan = [columna for columna in COLUMNAS if columna not in nombres]
    if faltan:
        raise CatalogoOrigenInvalidoError(
            "Al catálogo de Ventas le faltan columnas: "
            + ", ".join(faltan)
            + "."
        )
    repetidas = sorted(
        {columna for columna in COLUMNAS if nombres.count(columna) > 1}
    )
    if repetidas:
        raise CatalogoOrigenInvalidoError(
            "El catálogo de Ventas repite columnas: "
            + ", ".join(repetidas)
            + "."
        )
    indices = {columna: nombres.index(columna) for columna in COLUMNAS}

    productos: list[ProductoInformado] = []
    leidos = filtrados = descartados = 0
    for fila in filas:
        valores = {
            columna: _texto(fila[indice]) if indice < len(fila) else ""
            for columna, indice in indices.items()
        }
        if not any(valores.values()):
            continue
        leidos += 1
        if not filtro.admite(valores[COLUMNA_SUBCATEGORIA]):
            continue
        filtrados += 1
        if not valores[COLUMNA_ID]:
            descartados += 1
            continue
        productos.append(producto_desde_valores(valores, marcas=marcas))
    return LecturaCatalogo(
        productos=tuple(productos),
        leidos=leidos,
        filtrados=filtrados,
        descartados=descartados,
    )
