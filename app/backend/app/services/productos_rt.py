"""Reglas de la copia de Productos de Gestion RT (DEC-RT-01 a 07).

Sin base ni origen: funciones puras sobre la copia vigente y lo que leyo
el origen (docs/reparacion-rt-discovery.md, secciones 2.4 a 2.7).

``fusionar_productos_rt`` arma la copia COMPLETA despues de una lectura:

- Se aplican las filas en ``Reparacion`` (comparacion exacta, sin espacios
  al borde) y las de cualquier estado cuyo ``producto_id`` ya esta en la
  copia: asi se sabe que salieron, sin copiar el inventario.
- Un ``producto_id`` repetido en la lectura no se aplica: si ya estaba, se
  conservan sus datos y se marca ``conflicto_origen``.
- Salir de Reparacion marca ``salio_de_reparacion_en``; volver abre un
  periodo nuevo (``en_reparacion_desde``).
- Un producto que el origen ya no trae queda ``presente_en_origen = False``
  y uno eliminado en Gestion RT, ``eliminado_en_origen``: nunca se borra.
- Si desaparece mas del umbral de los presentes, la lectura no es
  confiable (truncada): ``ProductosRtRechazadoError`` y la copia no cambia.
- Un cambio de IMEI o de TipoProducto del mismo ``producto_id`` se marca
  (``cambio_identidad``) y se guarda la identidad anterior.
- Un IMEI valido repetido entre productos presentes marca a todos: no
  sugiere coincidencias (DEC-RT-03).

Los avisos nunca incluyen IMEI ni valores del origen.
"""

import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.identidad import normalizar
from app.domain.models import ProductoInformado, ProductoRt

from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError

_DIGITOS_ASCII = re.compile(r"[0-9]+")
# Cuantos ``producto_id`` se nombran en un aviso (el resto se cuenta).
MAX_IDS_EN_AVISO = 20
# Los contadores de un intento EXITOSA (siempre todos, aunque sean cero).
CONTADORES = (
    "leidos",
    "descartados",
    "duplicados",
    "nuevos",
    "actualizados",
    "sin_cambios",
    "salieron",
    "volvieron",
    "eliminados",
    "ausentes",
    "en_reparacion",
    "imei_repetidos",
)


class ProductosRtRechazadoError(PrecondicionInvalidaError):
    """Lo que informo el origen no es confiable: no se aplica nada."""

    codigo = "PRODUCTOS_RT_ORIGEN_INVALIDO"


class ProductosRtNoHabilitadoError(PrecondicionInvalidaError):
    """La copia no existe en este entorno (modo JSON) o no tiene origen."""

    codigo = "PRODUCTOS_RT_NO_HABILITADO"


class ProductoRtNoEncontradoError(EntidadNoEncontradaError):
    """No hay un producto con ese ``producto_id`` en la copia (404)."""

    codigo = "PRODUCTO_RT_NO_ENCONTRADO"


class FilaInformada(Protocol):
    """Una fila de Producto ya interpretada (``FilaProducto`` del
    contrato), sin depender del adaptador."""

    producto_id: str
    tipo_producto_id: str | None
    imei: str | None
    sede: str | None
    estado: str
    eliminado: bool
    bateria: str | None
    detalle_estetico: str | None
    defecto: str | None
    toma_rt: str | None
    tipo_reparacion: str | None
    repuesto: str | None
    creado_en: datetime | None
    creado_en_invalido: bool


@dataclass(frozen=True)
class ReglasProductosRt:
    """La configuracion de la copia (``RMA_PRODUCTOS_RT_*``)."""

    estado: str = "Reparacion"
    sedes: tuple[str, ...] = (
        "Alippi",
        "Centro",
        "eCommerce",
        "Fisherton",
        "RMA",
    )
    umbral_desaparicion: float = 0.5
    minimo_proteccion: int = 10

    @property
    def descripcion(self) -> str:
        return f"producto_status = {self.estado}"


@dataclass(frozen=True)
class FusionProductosRt:
    productos: tuple[ProductoRt, ...]
    contadores: dict[str, int]
    avisos: tuple[str, ...]


# --- IMEI y busqueda ----------------------------------------------------


def analizar_imei(valor: str | None) -> tuple[str | None, bool, bool | None]:
    """(normalizado, valido, digito verificador correcto) de un IMEI.

    Normalizado como el del Equipo (``domain.identidad.normalizar``: sin
    espacios, en mayusculas), para que la coincidencia sea la misma. Valido:
    15 digitos. El verificador (Luhn) solo se informa: ``None`` si no es
    valido."""
    normalizado = normalizar(valor)
    if normalizado is None:
        return None, False, None
    # Solo digitos ASCII: ``isdigit`` acepta tambien los de ancho completo o
    # los superindices, que la base (``^[0-9]{15}$``) rechazaria (QA, menor 1).
    if len(normalizado) != 15 or not _DIGITOS_ASCII.fullmatch(normalizado):
        return normalizado, False, None
    return normalizado, True, _luhn(normalizado)


def _luhn(digitos: str) -> bool:
    total = 0
    for posicion, caracter in enumerate(reversed(digitos)):
        numero = int(caracter)
        if posicion % 2 == 1:
            numero *= 2
            if numero > 9:
                numero -= 9
        total += numero
    return total % 10 == 0


def normalizar_busqueda(texto: str | None) -> str:
    """Sin mayusculas, tildes ni espacios repetidos (la busqueda y lo que se
    busca se normalizan igual)."""
    sin_tildes = "".join(
        caracter
        for caracter in unicodedata.normalize("NFKD", texto or "")
        if not unicodedata.combining(caracter)
    )
    return " ".join(sin_tildes.casefold().split())


def terminos_de_busqueda(q: str | None) -> list[str]:
    """Cada palabra de la busqueda: un producto coincide si las contiene
    TODAS (ID, IMEI o sus ultimos digitos, partes del modelo)."""
    return normalizar_busqueda(q).split()


def es_variante_del_estado(estado: str, objetivo: str) -> bool:
    """«reparacion», «Reparación» o « Reparacion »: parecido al objetivo
    pero no exacto (se informa como aviso, no cuenta como en Reparacion)."""
    return estado != objetivo and normalizar_busqueda(
        estado
    ) == normalizar_busqueda(objetivo)


# --- Fusion -------------------------------------------------------------


def fusionar_productos_rt(
    actuales: Sequence[ProductoRt],
    filas: Sequence[FilaInformada],
    tipos: Mapping[str, ProductoInformado],
    *,
    fecha: datetime,
    reglas: ReglasProductosRt,
    leidos: int,
    descartados: int = 0,
    faltantes: Sequence[str] = (),
) -> FusionProductosRt:
    """La copia completa despues de aplicar la lectura (modulo)."""
    por_id = {producto.producto_id: producto for producto in actuales}
    repeticiones = Counter(fila.producto_id for fila in filas)
    vistos = set(repeticiones)
    # Un ID repetido solo importa si alguna de sus filas se aplicaria (en
    # Reparacion, o ya en la copia): repetido solo en el inventario no se
    # copia ni se informa (QA, observacion 3).
    aplicables = {
        fila.producto_id
        for fila in filas
        if fila.estado == reglas.estado or fila.producto_id in por_id
    }
    en_conflicto = {
        pid
        for pid, veces in repeticiones.items()
        if veces > 1 and pid in aplicables
    }

    presentes = [p for p in actuales if p.presente_en_origen]
    if presentes and not vistos:
        # Una hoja con encabezado y sin filas no es confiable, aunque la
        # copia sea chica (QA, menor 3; seccion 2.4).
        raise ProductosRtRechazadoError(
            "La lectura no trae ningún producto y la copia tiene "
            f"{len(presentes)}: parece vacía o incompleta y no se aplica. Se "
            "conserva la copia anterior."
        )
    desaparecidos = [p for p in presentes if p.producto_id not in vistos]
    if len(presentes) >= reglas.minimo_proteccion and len(
        desaparecidos
    ) > reglas.umbral_desaparicion * len(presentes):
        raise ProductosRtRechazadoError(
            f"La lectura no trae {len(desaparecidos)} de los "
            f"{len(presentes)} productos de la copia (más del "
            f"{reglas.umbral_desaparicion:.0%}): parece incompleta y no se "
            "aplica. Se conserva la copia anterior."
        )

    contadores = Counter(
        leidos=leidos,
        descartados=descartados,
        duplicados=len(en_conflicto),
    )
    variantes: list[str] = []
    sedes_desconocidas: set[str] = set()
    sin_tipo: list[str] = []
    sin_sede: list[str] = []
    fechas_invalidas: list[str] = []
    cambios_identidad: list[str] = []
    resultado: dict[str, ProductoRt] = {}

    for fila in filas:
        pid = fila.producto_id
        if pid in en_conflicto:
            continue
        anterior = por_id.get(pid)
        en_reparacion = fila.estado == reglas.estado
        if not en_reparacion and es_variante_del_estado(
            fila.estado, reglas.estado
        ):
            variantes.append(pid)
        if anterior is None and (not en_reparacion or fila.eliminado):
            # Ni estaba ni entra: el inventario no se copia, y un eliminado
            # nuevo no se agrega.
            continue
        datos = _datos(fila, tipos)
        if not datos["sede"]:
            sin_sede.append(pid)
        elif datos["sede"] not in reglas.sedes:
            sedes_desconocidas.add(datos["sede"])
        if fila.tipo_producto_id and not datos["tipo_producto_encontrado"]:
            sin_tipo.append(pid)
        if fila.creado_en_invalido:
            fechas_invalidas.append(pid)
        if anterior is not None and _cambio_identidad(anterior, datos):
            # Cada cambio se avisa, tambien el segundo (QA, observacion 1).
            cambios_identidad.append(pid)
        producto = _aplicar(
            pid, anterior, datos, en_reparacion, fecha, contadores
        )
        resultado[pid] = producto

    conflictos_nuevos: list[str] = []
    for pid in sorted(en_conflicto):
        anterior = por_id.get(pid)
        if anterior is None:
            conflictos_nuevos.append(pid)
            continue
        actualizado = anterior.model_copy(
            update={
                "conflicto_origen": True,
                "presente_en_origen": True,
                "sincronizado_en": fecha,
            }
        )
        _contar_cambio(anterior, actualizado, contadores)
        resultado[pid] = actualizado

    for producto in actuales:
        if producto.producto_id in resultado:
            continue
        # No vino en la lectura (o vino en un estado que no se copia y no
        # estaba, que no aplica aca): ausente del origen.
        actualizado = producto.model_copy(
            update={"presente_en_origen": False, "sincronizado_en": fecha}
        )
        if producto.presente_en_origen:
            contadores["ausentes"] += 1
        _contar_cambio(producto, actualizado, contadores)
        resultado[producto.producto_id] = actualizado

    productos = _marcar_imei_repetidos(list(resultado.values()))
    contadores["en_reparacion"] = sum(1 for p in productos if p.listable)
    contadores["imei_repetidos"] = sum(1 for p in productos if p.imei_repetido)

    avisos = _avisos(
        faltantes=faltantes,
        conflictos=sorted(en_conflicto),
        conflictos_nuevos=conflictos_nuevos,
        variantes=variantes,
        sedes=sorted(sedes_desconocidas),
        sin_sede=sin_sede,
        sin_tipo=sin_tipo,
        fechas_invalidas=fechas_invalidas,
        cambios_identidad=cambios_identidad,
        imei_repetidos=contadores["imei_repetidos"],
        estado=reglas.estado,
    )
    return FusionProductosRt(
        productos=tuple(sorted(productos, key=lambda p: p.producto_id)),
        contadores={nombre: contadores[nombre] for nombre in CONTADORES},
        avisos=tuple(avisos),
    )


def _datos(
    fila: FilaInformada, tipos: Mapping[str, ProductoInformado]
) -> dict:
    """Lo que el origen dice hoy del producto, en terminos de RMA."""
    tipo = tipos.get(fila.tipo_producto_id) if fila.tipo_producto_id else None
    imei_normalizado, imei_valido, luhn = analizar_imei(fila.imei)
    modelo = None
    if tipo is not None:
        modelo = (
            " ".join(parte for parte in (tipo.modelo, tipo.variante) if parte)
            or None
        )
    datos = {
        "estado_gestion_rt": fila.estado,
        "eliminado_en_origen": fila.eliminado,
        "sede": fila.sede,
        "imei": fila.imei,
        "imei_normalizado": imei_normalizado,
        "imei_valido": imei_valido,
        "imei_luhn_valido": luhn,
        "tipo_producto_id": fila.tipo_producto_id,
        "tipo_producto_encontrado": tipo is not None,
        "tipo_producto_eliminado": bool(tipo and tipo.eliminado),
        "descripcion_tipo": tipo.descripcion if tipo else None,
        "modelo": modelo,
        "categoria": tipo.categoria if tipo else None,
        "subcategoria": tipo.subcategoria if tipo else None,
        "capacidad": tipo.capacidad if tipo else None,
        "color": tipo.color if tipo else None,
        "bateria": fila.bateria,
        "detalle_estetico": fila.detalle_estetico,
        "defecto": fila.defecto,
        "toma_rt": fila.toma_rt,
        "tipo_reparacion_origen": fila.tipo_reparacion,
        "repuesto": fila.repuesto,
        "creado_en_origen": fila.creado_en,
    }
    datos["texto_busqueda"] = normalizar_busqueda(
        " ".join(
            parte
            for parte in (
                fila.producto_id,
                imei_normalizado,
                datos["descripcion_tipo"],
                modelo,
                datos["capacidad"],
                datos["color"],
            )
            if parte
        )
    )
    datos["huella"] = _huella(datos)
    return datos


def _huella(datos: Mapping) -> str:
    """SHA-256 de lo que vino del origen (y de lo que se resolvio de su
    TipoProducto): dos lecturas iguales dan la misma huella."""
    serializable = {
        clave: (valor.isoformat() if isinstance(valor, datetime) else valor)
        for clave, valor in sorted(datos.items())
        if clave not in ("texto_busqueda", "huella")
    }
    contenido = json.dumps(serializable, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()


def _aplicar(
    producto_id: str,
    anterior: ProductoRt | None,
    datos: dict,
    en_reparacion: bool,
    fecha: datetime,
    contadores: Counter,
) -> ProductoRt:
    if anterior is None:
        contadores["nuevos"] += 1
        return ProductoRt(
            producto_id=producto_id,
            en_reparacion=en_reparacion,
            en_reparacion_desde=fecha if en_reparacion else None,
            primera_vez_visto_en=fecha,
            sincronizado_en=fecha,
            **datos,
        )
    cambios: dict = {
        **datos,
        "en_reparacion": en_reparacion,
        "presente_en_origen": True,
        "conflicto_origen": False,
        "sincronizado_en": fecha,
    }
    if en_reparacion and not anterior.en_reparacion:
        # Vuelve a Reparacion (o entra por primera vez): periodo nuevo.
        cambios["en_reparacion_desde"] = fecha
        cambios["salio_de_reparacion_en"] = None
        if anterior.en_reparacion_desde is not None:
            contadores["volvieron"] += 1
    elif not en_reparacion and anterior.en_reparacion:
        cambios["salio_de_reparacion_en"] = fecha
        contadores["salieron"] += 1
    if datos["eliminado_en_origen"] and not anterior.eliminado_en_origen:
        contadores["eliminados"] += 1
    if _cambio_identidad(anterior, datos):
        cambios["cambio_identidad"] = True
        cambios["identidad_anterior"] = _identidad(anterior)
    actualizado = anterior.model_copy(update=cambios)
    _contar_cambio(anterior, actualizado, contadores)
    return actualizado


def _cambio_identidad(anterior: ProductoRt, datos: Mapping) -> bool:
    """Cambio el IMEI o el TipoProducto que YA tenia (completar uno que
    faltaba no es un cambio de identidad)."""
    return any(
        previo is not None and previo != datos[campo]
        for campo, previo in (
            ("imei_normalizado", anterior.imei_normalizado),
            ("tipo_producto_id", anterior.tipo_producto_id),
        )
    )


def _identidad(producto: ProductoRt) -> dict[str, str | None]:
    return {
        "imei": producto.imei,
        "tipo_producto_id": producto.tipo_producto_id,
        "hasta": producto.sincronizado_en.isoformat(),
    }


def _contar_cambio(
    anterior: ProductoRt, actualizado: ProductoRt, contadores: Counter
) -> None:
    ignorar = {"sincronizado_en"}
    antes = anterior.model_dump(exclude=ignorar)
    despues = actualizado.model_dump(exclude=ignorar)
    contadores["actualizados" if antes != despues else "sin_cambios"] += 1


def _marcar_imei_repetidos(productos: list[ProductoRt]) -> list[ProductoRt]:
    """``imei_repetido`` en los productos EN REPARACION (presentes y no
    eliminados) que comparten un IMEI valido, y en ninguno mas.

    Solo entre los que estan en Reparacion: el mismo equipo que vuelve con
    un ID nuevo despues de salir con el anterior no es un repetido, y asi el
    resultado depende de lo que informa el origen hoy, no de la historia de
    la copia (QA, menor 4)."""

    def cuenta(p: ProductoRt) -> bool:
        return p.imei_valido and p.listable

    veces = Counter(p.imei_normalizado for p in productos if cuenta(p))
    marcados = []
    for producto in productos:
        repetido = cuenta(producto) and veces[producto.imei_normalizado] > 1
        if repetido != producto.imei_repetido:
            producto = producto.model_copy(update={"imei_repetido": repetido})
        marcados.append(producto)
    return marcados


def _lista(ids: Sequence[str]) -> str:
    nombrados = ", ".join(ids[:MAX_IDS_EN_AVISO])
    resto = len(ids) - MAX_IDS_EN_AVISO
    return nombrados + (f" y {resto} más" if resto > 0 else "")


def _avisos(
    *,
    faltantes: Sequence[str],
    conflictos: Sequence[str],
    conflictos_nuevos: Sequence[str],
    variantes: Sequence[str],
    sedes: Sequence[str],
    sin_sede: Sequence[str],
    sin_tipo: Sequence[str],
    fechas_invalidas: Sequence[str],
    cambios_identidad: Sequence[str],
    imei_repetidos: int,
    estado: str,
) -> list[str]:
    avisos = []
    for columna in faltantes:
        avisos.append(
            f"La tabla Producto no tiene la columna {columna}: ese dato "
            "queda vacío."
        )
    if conflictos:
        avisos.append(
            f"{len(conflictos)} producto_id repetidos en el origen no se "
            f"aplicaron: {_lista(conflictos)}."
            + (
                f" De ellos, {len(conflictos_nuevos)} no estaban en la copia."
                if conflictos_nuevos
                else ""
            )
        )
    if variantes:
        avisos.append(
            f"{len(variantes)} productos tienen un estado parecido a "
            f"«{estado}» pero no igual (no se cuentan en reparación): "
            f"{_lista(variantes)}."
        )
    if sedes:
        avisos.append("Sedes no confirmadas: " + ", ".join(sedes) + ".")
    if sin_sede:
        avisos.append(
            f"{len(sin_sede)} productos no tienen sede: {_lista(sin_sede)}."
        )
    if sin_tipo:
        avisos.append(
            f"{len(sin_tipo)} productos tienen un TipoProducto que no está "
            f"en el catálogo: {_lista(sin_tipo)}."
        )
    if fechas_invalidas:
        avisos.append(
            f"{len(fechas_invalidas)} productos tienen una fecha de alta "
            f"que no se pudo interpretar: {_lista(fechas_invalidas)}."
        )
    if cambios_identidad:
        avisos.append(
            f"{len(cambios_identidad)} productos cambiaron de IMEI o de "
            f"TipoProducto: {_lista(cambios_identidad)}."
        )
    if imei_repetidos:
        avisos.append(
            f"{imei_repetidos} productos comparten su IMEI con otro: no se "
            "usan para sugerir Órdenes."
        )
    return avisos
