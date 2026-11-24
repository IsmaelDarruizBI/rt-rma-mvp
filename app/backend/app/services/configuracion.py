"""Administracion de catalogos con auditoria (DC23, DC23AUD, BR-REP-040).

Reglas puras: quien administra, que se valida y que cambios se auditan. La
persistencia (el catalogo y su auditoria en la misma transaccion) es del
repository.

- Permisos configurables (CFG-03): ``TIPO_REPARACION_GESTIONAR`` para el
  Tipo y ``PRECIOS_GESTIONAR`` para su precio (D3: un alta fija el precio,
  asi que exige los dos); ``MESA_TIPOS_GESTIONAR`` para las Mesas.
- Un Tipo de Reparacion no se borra: se desactiva. Su codigo no cambia y
  ``TR-OTROS`` esta reservado.
- Cada campo que cambia deja un ``CambioConfiguracion`` con el valor
  anterior y el nuevo; un pedido sin cambios se rechaza.
- Lo ya registrado no cambia: los Detalles guardan su copia (BR-REP-015).
- DEC-AJ-12: ``precio_por_modelo`` de un Tipo y sus precios por modelo
  (entidad ``PRECIO_MODELO``, clave «TR-001/MOD-0012», campo «precio») son
  precios: ``PRECIOS_GESTIONAR``. Los modelos de equipo (entidad
  ``MODELO_EQUIPO``): ``MODELO_EQUIPO_GESTIONAR``.
"""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.domain.models import (
    TIPO_REPARACION_OTROS,
    CambioConfiguracion,
    CategoriaInsumo,
    EntidadConfiguracion,
    Insumo,
    ModeloEquipo,
    PrecioTipoModelo,
    TipoReparacion,
    TipoReparacionInsumos,
    TipoReparacionRequisito,
    Usuario,
)

from . import permisos
from .autorizacion import validar_alguno_de
from .exceptions import PrecondicionInvalidaError

ROLES_ADMINISTRACION_CONFIGURACION = permisos.CONFIGURACION_ADMINISTRAR
ROLES_TIPO_REPARACION = permisos.TIPO_REPARACION_GESTIONAR
ROLES_PRECIOS = permisos.PRECIOS_GESTIONAR
ROLES_MESA_TIPOS = permisos.MESA_TIPOS_GESTIONAR
ROLES_MODELOS = permisos.MODELO_EQUIPO_GESTIONAR
CAMPOS_TIPO = (
    "nombre",
    "precio",
    "puntaje",
    "garantia_dias",
    "garantia_con_checkin",
    "garantia_sin_checkin",
    "politica_garantia_rma",
    "activo",
    "precio_por_modelo",
)
# Los campos de un Tipo que son su precio (D3 y DEC-AJ-12).
CAMPOS_DE_PRECIO = ("precio", "precio_por_modelo")
CAMPOS_MODELO = ("marca", "modelo", "variante", "numeros_modelo", "activo")
CAMPO_PRECIO = "precio"
CAMPO_TIPOS_HABILITADOS = "tipos_habilitados"


def texto(valor: object) -> str | None:
    """El valor como lo guarda la auditoria."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, Decimal):
        return f"{valor:.2f}"
    if isinstance(valor, Enum):
        return valor.value
    if isinstance(valor, tuple | list):
        return ", ".join(str(v) for v in valor) or None
    return str(valor)


def _validar_tipo(tipo: TipoReparacion) -> None:
    if tipo.id.upper() == TIPO_REPARACION_OTROS:
        raise PrecondicionInvalidaError(
            f"{TIPO_REPARACION_OTROS} esta reservado para la reparacion no "
            "tipificada: no se administra como un Tipo del catalogo."
        )
    if not tipo.nombre.strip():
        raise PrecondicionInvalidaError(
            "El Tipo de Reparacion necesita nombre."
        )
    if (
        tipo.precio < 0
        or tipo.puntaje < 0
        or tipo.garantia_dias < 0
        or tipo.garantia_con_checkin < 0
        or tipo.garantia_sin_checkin < 0
    ):
        raise PrecondicionInvalidaError(
            "Precio, puntaje y garantia no pueden ser negativos."
        )


def cambios_de_tipo(
    anterior: TipoReparacion | None,
    nuevo: TipoReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> list[CambioConfiguracion]:
    """Los cambios auditables de un alta (``anterior`` None) o una edicion."""
    validar_alguno_de(usuario, ROLES_TIPO_REPARACION)
    if nuevo.precio != nuevo.precio.quantize(Decimal("0.01")):
        # QA B, M1: la base guarda dos decimales; uno mas cambiaria el
        # precio por redondeo sin pasar por PRECIOS_GESTIONAR.
        raise PrecondicionInvalidaError(
            "El precio admite hasta dos decimales."
        )
    if any(
        (anterior is None and campo == "precio")
        or (
            anterior is not None
            and texto(getattr(anterior, campo)) != texto(getattr(nuevo, campo))
        )
        for campo in CAMPOS_DE_PRECIO
    ) or (anterior is None and nuevo.precio_por_modelo):
        # D3: fijar o cambiar el precio es aparte. DEC-AJ-12: pasar a
        # precio por modelo (o volver al unico) tambien es un precio.
        validar_alguno_de(usuario, ROLES_PRECIOS)
    _validar_tipo(nuevo)
    if anterior is not None and anterior.id != nuevo.id:
        raise PrecondicionInvalidaError("El codigo de un Tipo no cambia.")
    cambios = [
        CambioConfiguracion(
            entidad=EntidadConfiguracion.TIPO_REPARACION,
            clave=nuevo.id,
            campo=campo,
            valor_anterior=(
                texto(getattr(anterior, campo)) if anterior else None
            ),
            valor_nuevo=texto(getattr(nuevo, campo)),
            usuario_id=usuario.id,
            fecha=fecha,
        )
        for campo in CAMPOS_TIPO
        if (
            anterior is None
            and texto(getattr(nuevo, campo)) is not None
            # Un alta de precio unico no anota «precio_por_modelo: false».
            and (campo != "precio_por_modelo" or nuevo.precio_por_modelo)
        )
        or (
            anterior is not None
            and texto(getattr(anterior, campo)) != texto(getattr(nuevo, campo))
        )
    ]
    if not cambios:
        raise PrecondicionInvalidaError(
            f"El Tipo {nuevo.id} ya tiene esos valores: no hay cambios."
        )
    return cambios


def cambio_de_tipos_habilitados(
    estacion_id: str,
    anteriores: Collection[str],
    nuevos: Collection[str],
    *,
    tipos_existentes: Iterable[TipoReparacion],
    usuario: Usuario,
    fecha: datetime,
) -> CambioConfiguracion:
    """Los Tipos que una Mesa de trabajo puede trabajar (BR-REP-011)."""
    validar_alguno_de(usuario, ROLES_MESA_TIPOS)
    conocidos = {tipo.id for tipo in tipos_existentes}
    desconocidos = sorted(set(nuevos) - conocidos)
    if desconocidos:
        raise PrecondicionInvalidaError(
            f"No existen los Tipos de Reparacion {', '.join(desconocidos)}."
        )
    antes = ", ".join(sorted(set(anteriores))) or None
    despues = ", ".join(sorted(set(nuevos))) or None
    if antes == despues:
        raise PrecondicionInvalidaError(
            f"La Mesa {estacion_id} ya tiene esos Tipos: no hay cambios."
        )
    return CambioConfiguracion(
        entidad=EntidadConfiguracion.MESA_TRABAJO,
        clave=estacion_id,
        campo=CAMPO_TIPOS_HABILITADOS,
        valor_anterior=antes,
        valor_nuevo=despues,
        usuario_id=usuario.id,
        fecha=fecha,
    )


# --- Modelos de equipo (DEC-AJ-12, D-12.5) ----------------------------------


def _clave_modelo(modelo: ModeloEquipo) -> tuple[str, str, str]:
    """(marca, modelo, variante) sin distinguir mayusculas ni espacios."""
    return tuple(
        " ".join((parte or "").split()).casefold()
        for parte in (modelo.marca, modelo.modelo, modelo.variante)
    )


def cambios_de_modelo(
    anterior: ModeloEquipo | None,
    nuevo: ModeloEquipo,
    *,
    existentes: Iterable[ModeloEquipo],
    usuario: Usuario,
    fecha: datetime,
) -> list[CambioConfiguracion]:
    """Los cambios auditables del alta o la edicion de un modelo.

    La marca y el modelo son obligatorios; la variante vacia es la version
    estandar. No se admite otro modelo con la misma marca, modelo y
    variante (sin distinguir mayusculas): evita duplicados, tambien con una
    futura regeneracion desde Ventas, que empareja por esa clave.
    """
    validar_alguno_de(usuario, ROLES_MODELOS)
    if anterior is not None and anterior.id != nuevo.id:
        raise PrecondicionInvalidaError("El codigo de un modelo no cambia.")
    clave = _clave_modelo(nuevo)
    repetido = next(
        (
            modelo
            for modelo in existentes
            if modelo.id != nuevo.id and _clave_modelo(modelo) == clave
        ),
        None,
    )
    if repetido is not None:
        raise PrecondicionInvalidaError(
            f"Ya existe el modelo {repetido.id} ({repetido.nombre}) con esa "
            "marca, modelo y variante."
        )
    cambios = [
        CambioConfiguracion(
            entidad=EntidadConfiguracion.MODELO_EQUIPO,
            clave=nuevo.id,
            campo=campo,
            valor_anterior=(
                texto(getattr(anterior, campo)) if anterior else None
            ),
            valor_nuevo=texto(getattr(nuevo, campo)),
            usuario_id=usuario.id,
            fecha=fecha,
        )
        for campo in CAMPOS_MODELO
        if (anterior is None and texto(getattr(nuevo, campo)) is not None)
        or (
            anterior is not None
            and texto(getattr(anterior, campo)) != texto(getattr(nuevo, campo))
        )
    ]
    if not cambios:
        raise PrecondicionInvalidaError(
            f"El modelo {nuevo.id} ya tiene esos valores: no hay cambios."
        )
    return cambios


# --- Precios por modelo (DEC-AJ-12, D-12.1) ---------------------------------


def clave_precio_modelo(tipo_id: str, modelo_id: str) -> str:
    """La clave de auditoria de un precio por modelo: «TR-001/MOD-0012»."""
    return f"{tipo_id}/{modelo_id}"


def cambios_de_precios_modelo(
    precios: Sequence[PrecioTipoModelo],
    *,
    tipos: Mapping[str, TipoReparacion],
    modelos: Mapping[str, ModeloEquipo],
    usuario: Usuario,
    fecha: datetime,
) -> tuple[list[PrecioTipoModelo], list[CambioConfiguracion]]:
    """Valida un lote de precios por modelo y devuelve los que cambian y su
    auditoria (un registro por combinacion, campo «precio»).

    ``tipos`` son los Tipos del catalogo con sus precios por modelo
    vigentes; ``modelos``, los modelos existentes (activos o no). Un precio
    ``None`` retira el de la combinacion. Las combinaciones que ya tienen
    ese valor no se escriben ni se auditan; si ninguna cambia, se rechaza.
    Exige ``PRECIOS_GESTIONAR``. Nunca toca los Detalles: guardan su copia.
    """
    validar_alguno_de(usuario, ROLES_PRECIOS)
    vistos: set[tuple[str, str]] = set()
    efectivos: list[PrecioTipoModelo] = []
    cambios: list[CambioConfiguracion] = []
    for pedido in precios:
        par = (pedido.tipo_reparacion_id, pedido.modelo_equipo_id)
        if par in vistos:
            raise PrecondicionInvalidaError(
                f"La combinacion {clave_precio_modelo(*par)} esta repetida."
            )
        vistos.add(par)
        if pedido.tipo_reparacion_id.upper() == TIPO_REPARACION_OTROS:
            raise PrecondicionInvalidaError(
                "«Otros» lleva un precio manual por trabajo: no tiene "
                "precios por modelo."
            )
        tipo = tipos.get(pedido.tipo_reparacion_id)
        if tipo is None:
            raise PrecondicionInvalidaError(
                f"No existe el Tipo de Reparacion {pedido.tipo_reparacion_id}."
            )
        if pedido.modelo_equipo_id not in modelos:
            raise PrecondicionInvalidaError(
                f"No existe el modelo de equipo {pedido.modelo_equipo_id}."
            )
        if pedido.precio is not None and (
            pedido.precio < 0
            or pedido.precio != pedido.precio.quantize(Decimal("0.01"))
        ):
            raise PrecondicionInvalidaError(
                "El precio no puede ser negativo y admite hasta dos decimales."
            )
        anterior = tipo.precios_modelo.get(pedido.modelo_equipo_id)
        if texto(anterior) == texto(pedido.precio):
            continue
        efectivos.append(pedido)
        cambios.append(
            CambioConfiguracion(
                entidad=EntidadConfiguracion.PRECIO_MODELO,
                clave=clave_precio_modelo(*par),
                campo=CAMPO_PRECIO,
                valor_anterior=texto(anterior),
                valor_nuevo=texto(pedido.precio),
                usuario_id=usuario.id,
                fecha=fecha,
            )
        )
    if not cambios:
        raise PrecondicionInvalidaError(
            "Los precios ya tienen esos valores: no hay cambios."
        )
    return efectivos, cambios


# --- Insumos necesarios de un Tipo (DEC-AJ-14, D-14.4) ----------------------

CAMPO_INSUMOS_PREVISTOS = "insumos_previstos"
CAMPO_REQUISITOS = "requisitos"
_MILESIMA = Decimal("0.001")
_TOPE_CANTIDAD = Decimal("1000000000")


def _cantidad_valida(cantidad: Decimal, que: str) -> Decimal:
    """Mayor que cero y con hasta tres decimales (numeric(12, 3))."""
    if cantidad <= 0:
        raise PrecondicionInvalidaError(
            f"La cantidad de {que} tiene que ser mayor que cero."
        )
    if cantidad != cantidad.quantize(_MILESIMA) or cantidad >= _TOPE_CANTIDAD:
        raise PrecondicionInvalidaError(
            f"La cantidad de {que} admite hasta tres decimales."
        )
    return cantidad


def _cantidad_texto(cantidad: Decimal) -> str:
    return format(cantidad.normalize(), "f")


def _texto_lineas(lineas: Iterable[tuple[str, Decimal]]) -> str | None:
    """«INS-001 x 1; INS-004 x 2» (o los CAT-…), en orden; vacio: None."""
    return (
        "; ".join(
            f"{codigo} x {_cantidad_texto(cantidad)}"
            for codigo, cantidad in lineas
        )
        or None
    )


def insumos_necesarios(
    tipo: TipoReparacion,
    *,
    previstos_actuales: Sequence[TipoReparacionInsumos],
    requisitos_actuales: Sequence[TipoReparacionRequisito],
    previstos: Sequence[tuple[str, Decimal]],
    requisitos: Sequence[tuple[str, Decimal]],
    insumos: Mapping[str, Insumo],
    categorias: Mapping[str, CategoriaInsumo],
    usuario: Usuario,
    fecha: datetime,
    nuevo_id: Callable[[], str],
) -> tuple[
    list[TipoReparacionInsumos],
    list[TipoReparacionRequisito],
    list[CambioConfiguracion],
]:
    """«Insumos necesarios» de un Tipo: los previstos concretos y los
    requisitos por categoria, en bloque (reemplazan el conjunto).

    - **Previstos concretos** (insumo y cantidad, uno por insumo): lo que se
      agrega tiene que existir, estar vigente y ser **universal** (sin
      modelos compatibles cargados): una pieza que depende del modelo va
      como requisito por categoria (precision 6). Lo que ya estaba se
      conserva aunque no lo sea.
    - **Requisitos** (categoria o subcategoria y cantidad, una por
      categoria): lo que se agrega tiene que existir y estar vigente (una
      subcategoria de una categoria dada de baja cuenta como de baja). Un
      requisito que sigue conserva su identificador (las piezas elegidas lo
      referencian); el que se quita queda inactivo, nunca se borra, y el
      que vuelve se reactiva.
    - Auditoria: entidad TIPO_REPARACION, campos ``insumos_previstos`` y
      ``requisitos`` («INS-001 x 1; …»), uno por campo que cambia. Sin
      cambios se rechaza.

    Devuelve los previstos efectivos, todos los requisitos del Tipo
    (activos o no, con su estado nuevo) y los cambios.
    """
    validar_alguno_de(usuario, ROLES_TIPO_REPARACION)
    if tipo.id == TIPO_REPARACION_OTROS:
        raise PrecondicionInvalidaError(
            "«Otros» no tiene insumos previstos ni requisitos."
        )

    anteriores = {p.insumo_id: p.cantidad for p in previstos_actuales}
    efectivos: list[TipoReparacionInsumos] = []
    vistos: set[str] = set()
    for insumo_id, cantidad in previstos:
        insumo_id = (insumo_id or "").strip()
        if insumo_id in vistos:
            raise PrecondicionInvalidaError(
                f"El insumo {insumo_id} esta repetido: va una sola linea con "
                "la cantidad total."
            )
        vistos.add(insumo_id)
        insumo = insumos.get(insumo_id)
        if insumo is None:
            raise PrecondicionInvalidaError(
                f"No existe el insumo {insumo_id}."
            )
        cantidad = _cantidad_valida(cantidad, insumo.codigo)
        if insumo_id not in anteriores:
            if not insumo.activo:
                raise PrecondicionInvalidaError(
                    f"El insumo {insumo.codigo} esta dado de baja: no se "
                    "agrega."
                )
            if insumo.modelos_compatibles:
                raise PrecondicionInvalidaError(
                    f"El insumo {insumo.codigo} solo sirve para algunos "
                    "modelos: agregalo como requisito por categoria (la "
                    "pieza se elige segun el modelo del equipo)."
                )
        efectivos.append(
            TipoReparacionInsumos(
                tipo_reparacion_id=tipo.id,
                insumo_id=insumo_id,
                cantidad=cantidad,
            )
        )

    del_tipo = [
        r for r in requisitos_actuales if r.tipo_reparacion_id == tipo.id
    ]
    por_categoria: dict[str, TipoReparacionRequisito] = {}
    for requisito in del_tipo:
        # Uno por categoria; si hubiera dos, manda el activo.
        actual = por_categoria.get(requisito.categoria_id)
        if actual is None or (requisito.activo and not actual.activo):
            por_categoria[requisito.categoria_id] = requisito
    pedidas: set[str] = set()
    resultado: dict[str, TipoReparacionRequisito] = {r.id: r for r in del_tipo}
    for posicion, (categoria_id, cantidad) in enumerate(requisitos, 1):
        categoria_id = (categoria_id or "").strip().upper()
        if categoria_id in pedidas:
            raise PrecondicionInvalidaError(
                f"La categoria {categoria_id} esta repetida: va un solo "
                "requisito con la cantidad total."
            )
        pedidas.add(categoria_id)
        categoria = categorias.get(categoria_id)
        if categoria is None:
            raise PrecondicionInvalidaError(
                f"No existe la categoria {categoria_id}."
            )
        cantidad = _cantidad_valida(cantidad, categoria.nombre)
        existente = por_categoria.get(categoria_id)
        if existente is None or not existente.activo:
            padre = categorias.get(categoria.padre_id or "")
            if not categoria.activo or (
                padre is not None and not padre.activo
            ):
                raise PrecondicionInvalidaError(
                    f"La categoria {categoria.nombre} esta dada de baja: no "
                    "se agrega como requisito."
                )
        if existente is None:
            requisito = TipoReparacionRequisito(
                id=nuevo_id(),
                tipo_reparacion_id=tipo.id,
                categoria_id=categoria_id,
                cantidad=cantidad,
                posicion=posicion,
            )
        else:
            requisito = existente.model_copy(
                update={
                    "cantidad": cantidad,
                    "posicion": posicion,
                    "activo": True,
                }
            )
        resultado[requisito.id] = requisito
    for requisito in del_tipo:
        if requisito.activo and requisito.categoria_id not in pedidas:
            resultado[requisito.id] = requisito.model_copy(
                update={"activo": False}
            )

    def activos(lista: Iterable[TipoReparacionRequisito]):
        return [
            (r.categoria_id, r.cantidad)
            for r in sorted(
                (r for r in lista if r.activo),
                key=lambda r: (r.posicion, r.categoria_id),
            )
        ]

    cambios: list[CambioConfiguracion] = []
    antes = _texto_lineas(
        (p.insumo_id, p.cantidad)
        for p in sorted(previstos_actuales, key=lambda p: p.insumo_id)
    )
    despues = _texto_lineas(
        (p.insumo_id, p.cantidad)
        for p in sorted(efectivos, key=lambda p: p.insumo_id)
    )
    if antes != despues:
        cambios.append(
            CambioConfiguracion(
                entidad=EntidadConfiguracion.TIPO_REPARACION,
                clave=tipo.id,
                campo=CAMPO_INSUMOS_PREVISTOS,
                valor_anterior=antes,
                valor_nuevo=despues,
                usuario_id=usuario.id,
                fecha=fecha,
            )
        )
    antes = _texto_lineas(activos(del_tipo))
    despues = _texto_lineas(activos(resultado.values()))
    if antes != despues:
        cambios.append(
            CambioConfiguracion(
                entidad=EntidadConfiguracion.TIPO_REPARACION,
                clave=tipo.id,
                campo=CAMPO_REQUISITOS,
                valor_anterior=antes,
                valor_nuevo=despues,
                usuario_id=usuario.id,
                fecha=fecha,
            )
        )
    if not cambios:
        raise PrecondicionInvalidaError(
            f"El Tipo {tipo.id} ya tiene esos insumos necesarios: no hay "
            "cambios."
        )
    return efectivos, list(resultado.values()), cambios
