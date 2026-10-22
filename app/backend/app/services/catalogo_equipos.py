"""Reglas de la copia del catalogo de equipos de Ventas (sin E/S).

    validar_informados    lo que trajo el origen es confiable (o se
                          rechaza todo y queda el catalogo anterior)
    fusionar_catalogo     aplica lo informado sobre la copia: altas,
                          cambios, bajas y reactivaciones; nunca borra
    opciones_de_seleccion el arbol Modelo -> Variante -> Capacidad ->
                          Color con las combinaciones que existen
    producto_elegible     el producto que eligio Recepcion, si se puede
    equipo_con_producto   copia las caracteristicas comerciales al Equipo

Que se ofrece para elegir: un producto vigente que no es un generador y
tiene marca, modelo, variante, capacidad y color (el color puede ser el
generico «cualquier color», que se ofrece como «Otro / sin especificar»).
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.models import (
    Equipo,
    MotivoBaja,
    MotivoNoSeleccionable,
    ProductoCatalogo,
    ProductoInformado,
    RolUsuario,
)

from .exceptions import PrecondicionInvalidaError

# Quienes pueden pedir una sincronizacion.
ROLES_SINCRONIZACION_CATALOGO = (
    RolUsuario.ADMINISTRADOR,
    RolUsuario.COORDINADOR_RMA,
)


class CatalogoRechazadoError(PrecondicionInvalidaError):
    """Lo que informo el origen no es confiable: no se aplica nada."""

    codigo = "CATALOGO_ORIGEN_INVALIDO"


class SincronizacionEnCursoError(PrecondicionInvalidaError):
    codigo = "SINCRONIZACION_EN_CURSO"


class ProductoNoDisponibleError(PrecondicionInvalidaError):
    """El ``tp_id`` elegido no esta (o ya no esta vigente) en la copia."""

    codigo = "PRODUCTO_CATALOGO_NO_DISPONIBLE"


# --- Validacion y fusion -----------------------------------------------------


def validar_informados(informados: Sequence[ProductoInformado]) -> None:
    """Rechaza una lectura vacia o con ``tp_id`` repetidos.

    Un ``tp_id`` repetido es ambiguo (no se sabe cual de los dos es el
    producto): antes que adivinar, se conserva el catalogo anterior.
    """
    if not informados:
        raise CatalogoRechazadoError(
            "El origen no informó ningún producto para el filtro "
            "configurado. Se conserva el catálogo anterior."
        )
    repetidos = sorted(
        tipo_id
        for tipo_id, veces in Counter(
            producto.tipo_producto_id for producto in informados
        ).items()
        if veces > 1
    )
    if repetidos:
        muestra = ", ".join(repetidos[:5])
        resto = f" y {len(repetidos) - 5} más" if len(repetidos) > 5 else ""
        raise CatalogoRechazadoError(
            f"El origen repite tp_id ({muestra}{resto}). Se conserva el "
            "catálogo anterior."
        )


def _clasificar(
    informado: ProductoInformado,
) -> MotivoNoSeleccionable | None:
    if informado.generador:
        return MotivoNoSeleccionable.GENERADOR
    if informado.faltantes:
        return MotivoNoSeleccionable.INCOMPLETO
    return None


def _datos_de(informado: ProductoInformado) -> dict:
    """Los campos del producto que vienen del origen (sin fechas)."""
    motivo = _clasificar(informado)
    return {
        "descripcion": informado.descripcion,
        "categoria": informado.categoria,
        "subcategoria": informado.subcategoria,
        "grupo": informado.grupo,
        "marca": informado.marca,
        "modelo": informado.modelo,
        "variante": informado.variante,
        "capacidad": informado.capacidad,
        "color": informado.color,
        "color_generico": informado.color_generico,
        "seleccionable": motivo is None,
        "motivo_no_seleccionable": motivo,
        "vigente": not informado.eliminado,
        "motivo_baja": (
            MotivoBaja.ELIMINADO_EN_ORIGEN if informado.eliminado else None
        ),
        "valores_origen": dict(informado.valores_origen),
    }


_FECHAS = {"primera_sincronizacion", "ultima_sincronizacion"}


@dataclass(frozen=True)
class FusionCatalogo:
    productos: tuple[ProductoCatalogo, ...]
    nuevos: int
    actualizados: int
    sin_cambios: int
    reactivados: int
    dados_de_baja: int

    @property
    def vigentes(self) -> int:
        return sum(1 for producto in self.productos if producto.vigente)

    @property
    def elegibles(self) -> int:
        return sum(1 for producto in self.productos if producto.elegible)


def fusionar_catalogo(
    actuales: Sequence[ProductoCatalogo],
    informados: Sequence[ProductoInformado],
    *,
    fecha: datetime,
) -> FusionCatalogo:
    """La copia despues de aplicar lo que informo el origen.

    Por ``tp_id`` (el de Ventas, sin transformar): repetir la misma
    sincronizacion no duplica nada. Lo que el origen ya no informa queda
    NO vigente (``NO_INFORMADO``) y lo que marca eliminado, tambien
    (``ELIMINADO_EN_ORIGEN``): nunca se borra, porque una Orden puede
    referenciarlo. Un eliminado que la copia nunca tuvo no se agrega.
    """
    por_id = {producto.tipo_producto_id: producto for producto in actuales}
    informados_ids = {producto.tipo_producto_id for producto in informados}
    productos: list[ProductoCatalogo] = []
    nuevos = actualizados = sin_cambios = reactivados = dados_de_baja = 0

    for informado in informados:
        datos = _datos_de(informado)
        anterior = por_id.get(informado.tipo_producto_id)
        if anterior is None:
            if informado.eliminado:
                continue
            productos.append(
                ProductoCatalogo(
                    tipo_producto_id=informado.tipo_producto_id,
                    primera_sincronizacion=fecha,
                    ultima_sincronizacion=fecha,
                    **datos,
                )
            )
            nuevos += 1
            continue
        actualizado = anterior.model_copy(
            update={**datos, "ultima_sincronizacion": fecha}
        )
        if not anterior.vigente and actualizado.vigente:
            reactivados += 1
        elif anterior.vigente and not actualizado.vigente:
            dados_de_baja += 1
        elif anterior.model_dump(exclude=_FECHAS) != actualizado.model_dump(
            exclude=_FECHAS
        ):
            actualizados += 1
        else:
            sin_cambios += 1
        productos.append(actualizado)

    for anterior in actuales:
        if anterior.tipo_producto_id in informados_ids:
            continue
        if anterior.vigente:
            dados_de_baja += 1
            anterior = anterior.model_copy(
                update={
                    "vigente": False,
                    "motivo_baja": MotivoBaja.NO_INFORMADO,
                }
            )
        productos.append(anterior)

    return FusionCatalogo(
        productos=tuple(productos),
        nuevos=nuevos,
        actualizados=actualizados,
        sin_cambios=sin_cambios,
        reactivados=reactivados,
        dados_de_baja=dados_de_baja,
    )


# --- Seleccion en el alta ----------------------------------------------------


@dataclass(frozen=True)
class OpcionColor:
    # ``None`` con ``generico``: «Otro / sin especificar».
    color: str | None
    generico: bool
    tipo_producto_id: str


@dataclass(frozen=True)
class OpcionCapacidad:
    capacidad: str
    colores: tuple[OpcionColor, ...]


@dataclass(frozen=True)
class OpcionVariante:
    # ``None``: la version estandar del modelo.
    variante: str | None
    capacidades: tuple[OpcionCapacidad, ...]


@dataclass(frozen=True)
class OpcionModelo:
    marca: str
    modelo: str
    variantes: tuple[OpcionVariante, ...]


def _orden_natural(texto: str) -> tuple:
    """«iPhone 8» antes que «iPhone 11»: los numeros como numeros."""
    return tuple(
        (0, int(parte)) if parte.isdigit() else (1, parte.casefold())
        for parte in re.split(r"(\d+)", texto)
        if parte
    )


_UNIDADES = {"MB": 1 / 1024, "GB": 1, "TB": 1024}


def _orden_capacidad(capacidad: str) -> tuple:
    """128 GB < 512 GB < 1 TB; lo que no se entiende, al final."""
    coincide = re.match(r"^(\d+(?:[.,]\d+)?)\s*(MB|GB|TB)$", capacidad)
    if not coincide:
        return (1, _orden_natural(capacidad))
    numero = float(coincide.group(1).replace(",", "."))
    return (0, numero * _UNIDADES[coincide.group(2)])


def opciones_de_seleccion(
    productos: Sequence[ProductoCatalogo],
) -> tuple[OpcionModelo, ...]:
    """El arbol del selector, solo con combinaciones que existen.

    Solo productos elegibles. Modelos y variantes en orden natural (la
    version estandar primero), capacidades de menor a mayor y colores
    alfabeticos, con «Otro / sin especificar» al final.
    """
    arbol: dict[tuple[str, str], dict[str | None, dict[str, list]]] = {}
    for producto in productos:
        if not producto.elegible:
            continue
        if not (producto.marca and producto.modelo and producto.capacidad):
            continue
        variantes = arbol.setdefault((producto.marca, producto.modelo), {})
        capacidades = variantes.setdefault(producto.variante, {})
        capacidades.setdefault(producto.capacidad, []).append(
            OpcionColor(
                color=producto.color,
                generico=producto.color_generico,
                tipo_producto_id=producto.tipo_producto_id,
            )
        )

    def orden_color(opcion: OpcionColor) -> tuple:
        return (opcion.generico, _orden_natural(opcion.color or ""))

    return tuple(
        OpcionModelo(
            marca=marca,
            modelo=modelo,
            variantes=tuple(
                OpcionVariante(
                    variante=variante,
                    capacidades=tuple(
                        OpcionCapacidad(
                            capacidad=capacidad,
                            colores=tuple(sorted(colores, key=orden_color)),
                        )
                        for capacidad, colores in sorted(
                            capacidades.items(),
                            key=lambda par: _orden_capacidad(par[0]),
                        )
                    ),
                )
                for variante, capacidades in sorted(
                    variantes.items(),
                    key=lambda par: (
                        par[0] is not None,
                        _orden_natural(par[0] or ""),
                    ),
                )
            ),
        )
        for (marca, modelo), variantes in sorted(
            arbol.items(),
            key=lambda par: (
                _orden_natural(par[0][0]),
                _orden_natural(par[0][1]),
            ),
        )
    )


def producto_elegible(
    producto: ProductoCatalogo | None, tipo_producto_id: str
) -> ProductoCatalogo:
    """El producto elegido, si todavia se puede elegir."""
    if producto is None:
        raise ProductoNoDisponibleError(
            f"El equipo elegido ({tipo_producto_id}) no está en el catálogo "
            "sincronizado. Elegilo de nuevo o cargá marca y modelo a mano."
        )
    if not producto.elegible:
        raise ProductoNoDisponibleError(
            f"El equipo elegido ({producto.descripcion}) ya no se ofrece en "
            "el catálogo de Ventas. Elegí otro o cargá marca y modelo a "
            "mano."
        )
    return producto


CAMPOS_COMERCIALES = (
    "tipo_producto_id",
    "marca",
    "modelo",
    "variante",
    "capacidad",
    "color",
)


def equipo_con_producto(equipo: Equipo, producto: ProductoCatalogo) -> Equipo:
    """El Equipo con las caracteristicas comerciales del producto.

    Copia (no referencia): un cambio posterior del catalogo no reescribe
    la Orden. La identidad fisica (``id``, IMEI, serie) no cambia.
    """
    return equipo.model_copy(
        update={
            "tipo_producto_id": producto.tipo_producto_id,
            "marca": producto.marca or "",
            "modelo": producto.modelo or producto.descripcion,
            "variante": producto.variante,
            "capacidad": producto.capacidad,
            "color": producto.color,
        }
    )


def equipo_carga_manual(equipo: Equipo) -> Equipo:
    """Sin producto del catalogo: marca y modelo a mano, sin los datos que
    solo vienen del catalogo."""
    return equipo.model_copy(
        update={
            "tipo_producto_id": None,
            "variante": None,
            "capacidad": None,
            "color": None,
        }
    )
