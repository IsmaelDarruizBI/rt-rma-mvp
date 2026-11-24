"""Clasificacion de insumos y compatibilidad con modelos (DEC-AJ-14).

Cada insumo es un repuesto real (SKU) con su stock: la clasificacion no lo
cambia (D-14.1). Se agrega, de forma opcional y gradual (D-14.2, D-14.5):

- **Categoria → Subcategoria:** dos niveles fijos. El insumo guarda el nivel
  mas especifico (``Insumo.categoria_id``); la categoria padre se deriva.
- **Fabricante** (catalogo), **variante** y **codigo del fabricante**.
- **Modelos compatibles** (``Insumo.modelos_compatibles``, codigos MOD del
  mismo catalogo de los precios). Vacio: **universal**, compatible con
  todos los modelos.

Funciones puras para la eleccion de piezas (parte B del bloque 8):

- ``compatible(insumo, modelo_equipo_id)``;
- ``insumos_compatibles(insumos, modelo_equipo_id, categoria_id, ...)``.

Y la validacion y la auditoria de la administracion (``INSUMO_GESTIONAR``,
punto 10 de la resolucion de 11.1).
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from app.domain.models import (
    CambioConfiguracion,
    CategoriaInsumo,
    EntidadConfiguracion,
    FabricanteRepuesto,
    Insumo,
    ModeloEquipo,
    Usuario,
)

from . import permisos
from .autorizacion import validar_alguno_de
from .configuracion import texto
from .exceptions import PrecondicionInvalidaError

# --- Compatibilidad (pura) ---------------------------------------------------


def es_universal(insumo: Insumo) -> bool:
    """Sin modelos compatibles cargados: sirve para todos los modelos."""
    return not insumo.modelos_compatibles


def compatible(insumo: Insumo, modelo_equipo_id: str | None) -> bool:
    """¿El insumo sirve para un equipo de ese modelo?

    - Universal: siempre.
    - Con modelos: solo esos.
    - Equipo sin modelo tecnico (``None``): solo los universales. Elegir
      otra pieza de la categoria con «compatibilidad no verificada» (punto
      2 de la resolucion de 11.1) es una excepcion explicita de la parte B,
      no de esta regla.
    """
    if es_universal(insumo):
        return True
    if modelo_equipo_id is None:
        return False
    return modelo_equipo_id in insumo.modelos_compatibles


def categorias_por_id(
    categorias: Iterable[CategoriaInsumo],
) -> dict[str, CategoriaInsumo]:
    return {c.id: c for c in categorias}


def categoria_padre(
    categoria_id: str | None, categorias: Mapping[str, CategoriaInsumo]
) -> str | None:
    """La categoria de primer nivel de ``categoria_id`` (ella misma si no
    tiene padre). ``None`` si no hay o no existe."""
    if categoria_id is None:
        return None
    categoria = categorias.get(categoria_id)
    if categoria is None:
        return None
    return categoria.padre_id or categoria.id


def en_categoria(
    insumo: Insumo,
    categoria_id: str,
    categorias: Mapping[str, CategoriaInsumo],
) -> bool:
    """¿El insumo pertenece a ``categoria_id``?

    Una categoria incluye a sus subcategorias: un insumo de «Modulos ›
    OLED» esta en «Modulos» y en «OLED». Una subcategoria incluye solo lo
    suyo."""
    if insumo.categoria_id is None:
        return False
    if insumo.categoria_id == categoria_id:
        return True
    return categoria_padre(insumo.categoria_id, categorias) == categoria_id


def insumos_compatibles(
    insumos: Iterable[Insumo],
    modelo_equipo_id: str | None,
    categoria_id: str | None = None,
    *,
    categorias: Iterable[CategoriaInsumo] = (),
    solo_activos: bool = True,
) -> list[Insumo]:
    """Los insumos que sirven para ese modelo y, si se indica, de esa
    categoria o subcategoria, en el orden recibido.

    ``categorias`` hace falta solo para filtrar por una categoria de primer
    nivel (incluye sus subcategorias). ``solo_activos``: los insumos dados
    de baja no se ofrecen para elegir."""
    por_id = categorias_por_id(categorias)
    return [
        insumo
        for insumo in insumos
        if (insumo.activo or not solo_activos)
        and compatible(insumo, modelo_equipo_id)
        and (
            categoria_id is None or en_categoria(insumo, categoria_id, por_id)
        )
    ]


# --- Administracion de los catalogos -----------------------------------------


def nombre_limpio(valor: str | None) -> str | None:
    """Sin espacios de mas; vacio es ``None``."""
    return " ".join((valor or "").split()) or None


def _clave_nombre(nombre: str) -> str:
    return " ".join(nombre.split()).casefold()


def _cambios(
    entidad: EntidadConfiguracion,
    anterior: object | None,
    nuevo,
    campos: Sequence[str],
    *,
    usuario: Usuario,
    fecha: datetime,
) -> list[CambioConfiguracion]:
    return [
        CambioConfiguracion(
            entidad=entidad,
            clave=nuevo.id,
            campo=campo,
            valor_anterior=(
                texto(getattr(anterior, campo)) if anterior else None
            ),
            valor_nuevo=texto(getattr(nuevo, campo)),
            usuario_id=usuario.id,
            fecha=fecha,
        )
        for campo in campos
        if (anterior is None and texto(getattr(nuevo, campo)) is not None)
        or (
            anterior is not None
            and texto(getattr(anterior, campo)) != texto(getattr(nuevo, campo))
        )
    ]


CAMPOS_CATEGORIA = ("nombre", "padre_id", "activo")
CAMPOS_FABRICANTE = ("nombre", "activo")


def cambios_de_categoria(
    anterior: CategoriaInsumo | None,
    nueva: CategoriaInsumo,
    *,
    existentes: Iterable[CategoriaInsumo],
    usuario: Usuario,
    fecha: datetime,
) -> list[CambioConfiguracion]:
    """Alta o edicion de una categoria o subcategoria, con su auditoria.

    - Dos niveles: el padre de una subcategoria es una categoria vigente sin
      padre. El nivel y el padre no cambian despues del alta (la base lo
      exige tambien): mover una subcategoria reclasificaria en silencio los
      insumos que la tienen.
    - El nombre no se repite entre las categorias, ni entre las
      subcategorias de una misma categoria (sin distinguir mayusculas).
    - Dar de baja una categoria no toca los insumos que la tienen: la
      conservan, pero no se asigna a otros (tampoco sus subcategorias).
    """
    validar_alguno_de(usuario, permisos.INSUMO_GESTIONAR)
    por_id = categorias_por_id(existentes)
    if anterior is not None and anterior.padre_id != nueva.padre_id:
        raise PrecondicionInvalidaError(
            "Una categoria no cambia de nivel ni de categoria: da de alta "
            "otra y reclasifica los insumos."
        )
    if anterior is None and nueva.padre_id is not None:
        padre = por_id.get(nueva.padre_id)
        if padre is None:
            raise PrecondicionInvalidaError(
                f"No existe la categoria {nueva.padre_id}."
            )
        if padre.padre_id is not None:
            raise PrecondicionInvalidaError(
                "Solo hay dos niveles: una subcategoria no puede tener "
                "subcategorias."
            )
        if not padre.activo:
            raise PrecondicionInvalidaError(
                f"La categoria {padre.id} ({padre.nombre}) esta dada de "
                "baja: no admite subcategorias nuevas."
            )
    repetida = next(
        (
            c
            for c in por_id.values()
            if c.id != nueva.id
            and c.padre_id == nueva.padre_id
            and _clave_nombre(c.nombre) == _clave_nombre(nueva.nombre)
        ),
        None,
    )
    if repetida is not None:
        donde = (
            f"en {por_id[nueva.padre_id].nombre}"
            if nueva.padre_id in por_id
            else "entre las categorias"
        )
        raise PrecondicionInvalidaError(
            f"Ya existe {repetida.id} «{repetida.nombre}» {donde}."
        )
    cambios = _cambios(
        EntidadConfiguracion.CATEGORIA_INSUMO,
        anterior,
        nueva,
        CAMPOS_CATEGORIA,
        usuario=usuario,
        fecha=fecha,
    )
    if not cambios:
        raise PrecondicionInvalidaError(
            f"La categoria {nueva.id} ya tiene esos valores: no hay cambios."
        )
    return cambios


def cambios_de_fabricante(
    anterior: FabricanteRepuesto | None,
    nuevo: FabricanteRepuesto,
    *,
    existentes: Iterable[FabricanteRepuesto],
    usuario: Usuario,
    fecha: datetime,
) -> list[CambioConfiguracion]:
    """Alta o edicion de un fabricante, con su auditoria. El nombre es
    unico sin distinguir mayusculas. Darlo de baja no toca los insumos."""
    validar_alguno_de(usuario, permisos.INSUMO_GESTIONAR)
    repetido = next(
        (
            f
            for f in existentes
            if f.id != nuevo.id
            and _clave_nombre(f.nombre) == _clave_nombre(nuevo.nombre)
        ),
        None,
    )
    if repetido is not None:
        raise PrecondicionInvalidaError(
            f"Ya existe el fabricante {repetido.id} «{repetido.nombre}»."
        )
    cambios = _cambios(
        EntidadConfiguracion.FABRICANTE_REPUESTO,
        anterior,
        nuevo,
        CAMPOS_FABRICANTE,
        usuario=usuario,
        fecha=fecha,
    )
    if not cambios:
        raise PrecondicionInvalidaError(
            f"El fabricante {nuevo.id} ya tiene esos valores: no hay cambios."
        )
    return cambios


# --- Clasificacion de un insumo ----------------------------------------------


def categoria_vigente(
    categoria: CategoriaInsumo, categorias: Mapping[str, CategoriaInsumo]
) -> bool:
    """Vigente ella y, si es subcategoria, su categoria."""
    if not categoria.activo:
        return False
    padre = categorias.get(categoria.padre_id) if categoria.padre_id else None
    return padre is None or padre.activo


def normalizar_modelos(modelos: Iterable[str]) -> tuple[str, ...]:
    """Codigos MOD sin repetir, en mayusculas y ordenados."""
    return tuple(
        sorted({m.strip().upper() for m in modelos if m and m.strip()})
    )


def validar_clasificacion(
    anterior: Insumo | None,
    nuevo: Insumo,
    *,
    categorias: Iterable[CategoriaInsumo],
    fabricantes: Iterable[FabricanteRepuesto],
    modelos: Iterable[ModeloEquipo],
) -> None:
    """La clasificacion y la compatibilidad de un alta o edicion.

    - La categoria, el fabricante y los modelos tienen que existir.
    - Lo que se asigna o se agrega tiene que estar vigente. Lo que el
      insumo ya tenia se conserva aunque se haya dado de baja: la
      clasificacion es gradual y no obliga a corregir todo de una vez.
    """
    por_categoria = categorias_por_id(categorias)
    if nuevo.categoria_id is not None:
        categoria = por_categoria.get(nuevo.categoria_id)
        if categoria is None:
            raise PrecondicionInvalidaError(
                f"No existe la categoria {nuevo.categoria_id}."
            )
        sin_cambio = (
            anterior is not None and anterior.categoria_id == categoria.id
        )
        if not sin_cambio and not categoria_vigente(categoria, por_categoria):
            raise PrecondicionInvalidaError(
                f"La categoria {categoria.id} ({categoria.nombre}) esta dada "
                "de baja: no se asigna a un insumo."
            )
    if nuevo.fabricante_id is not None:
        fabricante = next(
            (f for f in fabricantes if f.id == nuevo.fabricante_id), None
        )
        if fabricante is None:
            raise PrecondicionInvalidaError(
                f"No existe el fabricante {nuevo.fabricante_id}."
            )
        sin_cambio = (
            anterior is not None and anterior.fabricante_id == fabricante.id
        )
        if not sin_cambio and not fabricante.activo:
            raise PrecondicionInvalidaError(
                f"El fabricante {fabricante.id} ({fabricante.nombre}) esta "
                "dado de baja: no se asigna a un insumo."
            )
    por_modelo = {m.id: m for m in modelos}
    previos = set(anterior.modelos_compatibles) if anterior else set()
    desconocidos = [
        m for m in nuevo.modelos_compatibles if m not in por_modelo
    ]
    if desconocidos:
        raise PrecondicionInvalidaError(
            "No existen los modelos " + ", ".join(desconocidos) + "."
        )
    de_baja = [
        m
        for m in nuevo.modelos_compatibles
        if m not in previos and not por_modelo[m].activo
    ]
    if de_baja:
        raise PrecondicionInvalidaError(
            "Los modelos "
            + ", ".join(de_baja)
            + " estan dados de baja: no se agregan a la compatibilidad."
        )
