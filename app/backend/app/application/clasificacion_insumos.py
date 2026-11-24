"""Categorias de insumos y fabricantes de repuestos (DEC-AJ-14).

La lectura vale en los dos modos (en JSON, catalogos vacios: los insumos
quedan sin clasificar y universales). El alta y la edicion son con
``INSUMO_GESTIONAR`` (punto 10 de la resolucion de 11.1), sobre
PostgreSQL y con auditoria, como el resto de la configuracion. Ninguno se
borra: se desactiva.
"""

from dataclasses import dataclass

from pydantic import ValidationError

from app.domain.models import (
    CategoriaInsumo,
    FabricanteRepuesto,
    Insumo,
    ModeloEquipo,
)
from app.services import permisos
from app.services.autorizacion import validar_alguno_de
from app.services.clasificacion_insumos import (
    cambios_de_categoria,
    cambios_de_fabricante,
    insumos_compatibles,
    nombre_limpio,
)
from app.services.exceptions import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
)

from .codigos import con_reintento_de_codigo
from .configuracion import listar_modelos_administrables
from .contexto import ApplicationContext
from .operativa import _editable


@dataclass(frozen=True)
class ClasificacionInsumos:
    """Los catalogos para nombrar y filtrar insumos: categorias (con sus
    subcategorias), fabricantes y modelos de equipo, activos o no (un
    insumo puede conservar uno dado de baja)."""

    categorias: list[CategoriaInsumo]
    fabricantes: list[FabricanteRepuesto]
    modelos: list[ModeloEquipo]


def clasificacion_insumos(
    contexto: ApplicationContext,
) -> ClasificacionInsumos:
    with contexto.lectura():
        return ClasificacionInsumos(
            categorias=contexto.operativa.listar_categorias_insumo(),
            fabricantes=contexto.operativa.listar_fabricantes_repuesto(),
            modelos=listar_modelos_administrables(contexto),
        )


def listar_insumos_compatibles(
    contexto: ApplicationContext,
    *,
    modelo_equipo_id: str | None,
    categoria_id: str | None = None,
    solo_activos: bool = True,
) -> list[Insumo]:
    """Los insumos que sirven para un modelo (y una categoria o
    subcategoria, si se indica): la base para elegir la pieza concreta
    (parte B del bloque 8). Sin modelo tecnico, solo los universales."""
    with contexto.lectura():
        insumos = contexto.catalogos.listar_insumos()
        categorias = (
            contexto.operativa.listar_categorias_insumo()
            if categoria_id
            else []
        )
    return insumos_compatibles(
        insumos,
        modelo_equipo_id,
        categoria_id,
        categorias=categorias,
        solo_activos=solo_activos,
    )


def guardar_categoria_insumo(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    codigo: str | None = None,
    nombre: str,
    padre_id: str | None = None,
    activo: bool = True,
    nuevo: bool,
) -> CategoriaInsumo:
    """Alta (codigo ``CAT-NNN`` generado por la base) o edicion (nombre y
    vigencia) de una categoria o subcategoria, con auditoria. El nivel y la
    categoria padre se fijan en el alta y no cambian."""
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    validar_alguno_de(usuario, permisos.INSUMO_GESTIONAR)
    codigo = (codigo or "").strip().upper() or None
    padre_id = (padre_id or "").strip().upper() or None
    if not nuevo and codigo is None:
        raise PrecondicionInvalidaError("Falta el codigo de la categoria.")
    nombre_pedido = nombre_limpio(nombre)
    if nombre_pedido is None:
        raise PrecondicionInvalidaError("La categoria necesita un nombre.")

    def intento():
        with contexto.transaccion():
            existentes = repositorio.listar_categorias_insumo()
            anterior = None
            codigo_final = codigo
            if not nuevo:
                anterior = next(
                    (c for c in existentes if c.id == codigo), None
                )
                if anterior is None:
                    raise EntidadNoEncontradaError(
                        f"No existe la categoria {codigo}"
                    )
            else:
                codigo_final = repositorio.reservar_codigo("CAT")
            try:
                categoria = CategoriaInsumo(
                    id=codigo_final,
                    nombre=nombre_pedido,
                    padre_id=(
                        anterior.padre_id
                        if anterior is not None and padre_id is None
                        else padre_id
                    ),
                    activo=activo,
                )
            except ValidationError as error:
                raise PrecondicionInvalidaError(
                    "La categoria necesita un nombre."
                ) from error
            cambios = cambios_de_categoria(
                anterior,
                categoria,
                existentes=existentes,
                usuario=usuario,
                fecha=fecha,
            )
            repositorio.guardar_categoria_insumo(
                categoria, nuevo=nuevo, cambios=cambios
            )
        return categoria

    return con_reintento_de_codigo(intento, generado=nuevo)


def guardar_fabricante_repuesto(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    codigo: str | None = None,
    nombre: str,
    activo: bool = True,
    nuevo: bool,
) -> FabricanteRepuesto:
    """Alta (codigo ``FAB-NNN`` generado por la base) o edicion de un
    fabricante de repuestos, con auditoria."""
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    validar_alguno_de(usuario, permisos.INSUMO_GESTIONAR)
    codigo = (codigo or "").strip().upper() or None
    if not nuevo and codigo is None:
        raise PrecondicionInvalidaError("Falta el codigo del fabricante.")
    nombre_pedido = nombre_limpio(nombre)
    if nombre_pedido is None:
        raise PrecondicionInvalidaError("El fabricante necesita un nombre.")

    def intento():
        with contexto.transaccion():
            existentes = repositorio.listar_fabricantes_repuesto()
            anterior = None
            codigo_final = codigo
            if not nuevo:
                anterior = next(
                    (f for f in existentes if f.id == codigo), None
                )
                if anterior is None:
                    raise EntidadNoEncontradaError(
                        f"No existe el fabricante {codigo}"
                    )
            else:
                codigo_final = repositorio.reservar_codigo("FAB")
            fabricante = FabricanteRepuesto(
                id=codigo_final, nombre=nombre_pedido, activo=activo
            )
            cambios = cambios_de_fabricante(
                anterior,
                fabricante,
                existentes=existentes,
                usuario=usuario,
                fecha=fecha,
            )
            repositorio.guardar_fabricante_repuesto(
                fabricante, nuevo=nuevo, cambios=cambios
            )
        return fabricante

    return con_reintento_de_codigo(intento, generado=nuevo)
