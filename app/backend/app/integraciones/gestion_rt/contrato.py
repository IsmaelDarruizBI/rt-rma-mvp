"""Contrato de la tabla Producto de Gestion RT (Reparacion RT, etapa 1).

Unico modulo que conoce los nombres de columna de Producto y como se
interpretan sus celdas (docs/reparacion-rt-discovery.md, seccion 2.2). Lo
comparten todos los adaptadores, sea cual sea el almacenamiento.

Regla de lectura (seccion 2.2 y 2.8):

- Producto tiene 31 columnas (``COLUMNAS``). RMA copia SOLO las 13 de
  ``COPIAR``: 6 obligatorias y 7 opcionales. Las demas no se piden al
  origen (en Sheets, cada columna viaja por separado) o, si el origen
  entrega la fila completa (un CSV), se descartan aca, antes de salir de
  esta funcion.
- ``producto_passcode`` NUNCA se lee (``NUNCA``): una prueba falla si
  entrara en ``COPIAR``.
- Las columnas se ubican por NOMBRE (Gestion RT puede reordenarlas). Una
  obligatoria que falta o una columna copiada repetida rechaza la lectura;
  una opcional que falta deja su campo vacio y genera un aviso.

Las celdas siguen las convenciones de la tabla TipoProducto
(``catalogo.ventas``): texto sin espacios al borde, un numero ``n.0`` como
entero (un IMEI guardado como numero vuelve a sus 15 digitos), y los
verdaderos de ``tp_eliminado``.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

from app.integraciones.catalogo.ventas import es_verdadero, texto_de_celda

# Las 31 columnas de Producto, en el orden de Gestion RT [U].
COLUMNAS = (
    "producto_id", "producto_oc", "producto_tp", "producto_movimiento",
    "producto_imei", "producto_bateria", "producto_precio_compra",
    "producto_cantidad", "producto_venta_reparacion",
    "producto_detalle_estetico", "producto_sede", "producto_comentario",
    "producto_creado_en", "producto_creado_por", "producto_eliminado",
    "producto_eliminado_por", "producto_eliminado_at", "producto_status",
    "producto_ov", "producto_precio_vendido", "producto_fecha_venta",
    "producto_enviar_precio", "producto_defecto", "producto_toma_rt",
    "producto_stock", "producto_passcode", "app_id", "producto_documento",
    "producto_check_movimiento", "producto_tipo_reparacion",
    "producto_repuesto",
)  # fmt: skip

OBLIGATORIAS = (
    "producto_id",
    "producto_tp",
    "producto_imei",
    "producto_sede",
    "producto_status",
    "producto_eliminado",
)
OPCIONALES = (
    "producto_bateria",
    "producto_detalle_estetico",
    "producto_creado_en",
    "producto_defecto",
    "producto_toma_rt",
    "producto_tipo_reparacion",
    "producto_repuesto",
)
# La lista permitida: lo unico que RMA pide al origen.
COPIAR = OBLIGATORIAS + OPCIONALES
# Sensible [U]: nunca se pide, nunca se guarda.
NUNCA = frozenset({"producto_passcode"})

# El epoch de los numeros de serie de fecha de Sheets (y de Excel).
_EPOCH_SERIAL = datetime(1899, 12, 30)
# Un numero de serie fuera de este rango (1954 a 2119) no es una fecha de
# alta plausible: se informa como invalido en lugar de adivinar.
_SERIAL_MINIMO, _SERIAL_MAXIMO = 20_000.0, 80_000.0
_FORMATOS_FECHA = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
)


@dataclass(frozen=True)
class FilaProducto:
    """Una fila de Producto, solo con las columnas copiadas y ya como texto.

    Ningun campo es el IMEI interpretado: la validez y la normalizacion son
    reglas de RMA (``services.productos_rt``)."""

    producto_id: str
    tipo_producto_id: str | None
    imei: str | None
    sede: str | None
    estado: str
    eliminado: bool
    bateria: str | None = None
    detalle_estetico: str | None = None
    defecto: str | None = None
    toma_rt: str | None = None
    tipo_reparacion: str | None = None
    repuesto: str | None = None
    creado_en: datetime | None = None
    # La celda de alta tenia un valor que no es una fecha reconocible.
    creado_en_invalido: bool = False


@dataclass(frozen=True)
class TablaProductos:
    """Lo que se leyo de Producto.

    ``leidos``: filas con datos; ``descartados``: de esas, las que no tienen
    ``producto_id`` (no se pueden referenciar). ``faltantes``: columnas
    opcionales ausentes en el origen."""

    filas: tuple[FilaProducto, ...]
    leidos: int
    descartados: int
    faltantes: tuple[str, ...] = ()


def columnas_a_leer(
    encabezados: Sequence[Any], *, error: type[Exception]
) -> tuple[dict[str, int], tuple[str, ...]]:
    """La posicion de cada columna de ``COPIAR`` presente, por nombre, y las
    opcionales que faltan.

    Rechaza (``error``) si falta una obligatoria o si una columna copiada
    aparece mas de una vez: no hay como saber cual es la buena."""
    nombres = [texto_de_celda(encabezado) for encabezado in encabezados]
    faltan = [c for c in OBLIGATORIAS if c not in nombres]
    if faltan:
        raise error(
            "A la tabla Producto le faltan columnas obligatorias: "
            + ", ".join(faltan)
            + "."
        )
    repetidas = sorted({c for c in COPIAR if nombres.count(c) > 1})
    if repetidas:
        raise error(
            "La tabla Producto repite columnas: " + ", ".join(repetidas) + "."
        )
    indices = {c: nombres.index(c) for c in COPIAR if c in nombres}
    faltantes = tuple(c for c in OPCIONALES if c not in indices)
    return indices, faltantes


def tabla_desde_columnas(
    columnas: Mapping[str, Sequence[Any]],
    *,
    faltantes: Sequence[str] = (),
    zona: tzinfo,
) -> TablaProductos:
    """Las filas a partir de los valores de cada columna copiada (sin el
    encabezado), como los devuelve Sheets por columnas: las celdas vacias
    del final de una columna no vienen, asi que las columnas pueden tener
    largos distintos.

    Una columna fuera de ``COPIAR`` es un error de programacion: nunca se
    acepta, aunque llegue."""
    ajenas = sorted(set(columnas) - set(COPIAR))
    if ajenas:
        raise ValueError(
            "Solo se interpretan las columnas copiadas; llegaron: "
            + ", ".join(ajenas)
        )
    largo = max((len(valores) for valores in columnas.values()), default=0)
    filas: list[FilaProducto] = []
    leidos = descartados = 0
    for indice in range(largo):
        valores = {
            nombre: (celdas[indice] if indice < len(celdas) else None)
            for nombre, celdas in columnas.items()
        }
        textos = {
            nombre: texto_de_celda(valor) for nombre, valor in valores.items()
        }
        if not any(textos.values()):
            continue
        leidos += 1
        if not textos.get("producto_id"):
            descartados += 1
            continue
        filas.append(_fila(valores, textos, zona))
    return TablaProductos(
        filas=tuple(filas),
        leidos=leidos,
        descartados=descartados,
        faltantes=tuple(faltantes),
    )


def tabla_desde_filas(
    encabezados: Sequence[Any],
    filas: Iterable[Sequence[Any]],
    *,
    zona: tzinfo,
    error: type[Exception],
) -> TablaProductos:
    """La tabla a partir de filas completas (un CSV con las 31 columnas):
    se toman solo las columnas copiadas; el resto se descarta aca."""
    indices, faltantes = columnas_a_leer(encabezados, error=error)
    columnas: dict[str, list[Any]] = {nombre: [] for nombre in indices}
    for fila in filas:
        for nombre, posicion in indices.items():
            columnas[nombre].append(
                fila[posicion] if posicion < len(fila) else None
            )
    return tabla_desde_columnas(columnas, faltantes=faltantes, zona=zona)


def fecha_de_celda(valor: Any, zona: tzinfo) -> tuple[datetime | None, bool]:
    """(fecha en UTC, invalida) de una celda de fecha.

    - Numero (``dateTimeRenderOption=SERIAL_NUMBER``) o texto numerico: dias
      desde el 30/12/1899, en la hora local de Gestion RT (``zona``).
    - Texto ISO 8601 o dd/mm/aaaa [hh:mm[:ss]]: sin zona, la de ``zona``.
    - Vacia: (None, False). Otra cosa: (None, True); nunca se adivina."""
    if valor is None or isinstance(valor, bool):
        return None, False
    if isinstance(valor, int | float):
        return _desde_serial(float(valor), zona)
    if isinstance(valor, datetime):
        return _a_utc(valor, zona), False
    if isinstance(valor, date):
        return _a_utc(
            datetime(valor.year, valor.month, valor.day), zona
        ), False
    texto = str(valor).strip()
    if not texto:
        return None, False
    try:
        return _desde_serial(float(texto.replace(",", ".")), zona)
    except ValueError:
        pass
    try:
        return _a_utc(datetime.fromisoformat(texto), zona), False
    except ValueError:
        pass
    for formato in _FORMATOS_FECHA:
        try:
            return _a_utc(datetime.strptime(texto, formato), zona), False
        except ValueError:
            continue
    return None, True


def _desde_serial(numero: float, zona: tzinfo) -> tuple[datetime | None, bool]:
    if not (_SERIAL_MINIMO <= numero <= _SERIAL_MAXIMO):
        return None, True
    local = _EPOCH_SERIAL + timedelta(days=numero)
    # Al segundo: un serial trae fracciones de dia que no son exactas.
    local = local.replace(microsecond=0) + timedelta(
        seconds=round(local.microsecond / 1_000_000)
    )
    return _a_utc(local, zona), False


def _a_utc(momento: datetime, zona: tzinfo) -> datetime:
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=zona)
    return momento.astimezone(timezone.utc)


def _opcional(textos: Mapping[str, str], nombre: str) -> str | None:
    return textos.get(nombre) or None


def _fila(
    valores: Mapping[str, Any], textos: Mapping[str, str], zona: tzinfo
) -> FilaProducto:
    creado_en, invalida = fecha_de_celda(
        valores.get("producto_creado_en"), zona
    )
    return FilaProducto(
        producto_id=textos["producto_id"],
        tipo_producto_id=_opcional(textos, "producto_tp"),
        imei=_opcional(textos, "producto_imei"),
        sede=_opcional(textos, "producto_sede"),
        estado=textos.get("producto_status", ""),
        eliminado=es_verdadero(textos.get("producto_eliminado", "")),
        bateria=_opcional(textos, "producto_bateria"),
        detalle_estetico=_opcional(textos, "producto_detalle_estetico"),
        defecto=_opcional(textos, "producto_defecto"),
        toma_rt=_opcional(textos, "producto_toma_rt"),
        tipo_reparacion=_opcional(textos, "producto_tipo_reparacion"),
        repuesto=_opcional(textos, "producto_repuesto"),
        creado_en=creado_en,
        creado_en_invalido=invalida,
    )
