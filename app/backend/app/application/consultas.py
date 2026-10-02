"""Casos de uso de lectura.

Son finos a proposito: cargan de los repositories y devuelven modelos de
dominio. La forma HTTP la decide ``app.api.schemas``; aqui no hay DTOs.

La excepcion es ``InsumoPrevisto``: no es un modelo de dominio sino el
resultado de resolver una relacion de catalogos que el aggregate no
guarda. Un ReparacionDetail solo conoce su ``tipo_reparacion_id``; que
insumos preve ese Tipo vive en ``TipoReparacionInsumos``, y los datos de
cada insumo en ``Insumo``. Esa resolucion es responsabilidad de esta
capa, no del dominio.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.domain.models import (
    EstacionTrabajo,
    OrdenReparacion,
    TipoReparacion,
    Usuario,
)
from app.repositories import (
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .contexto import ApplicationContext


@dataclass(frozen=True)
class InsumoPrevisto:
    """Insumo que un Detalle preve consumir, con su dato de catalogo.

    Es informacion de presentacion: NO se persiste en la Orden ni se
    agrega a ``ReparacionDetail``. Se resuelve al leer, porque depende
    del catalogo vigente.
    """

    insumo_id: str
    codigo: str
    nombre: str
    cantidad_prevista: Decimal


@dataclass(frozen=True)
class DetalleOrigen:
    """Detalle de la Orden origen de una garantia RMA, para presentacion.

    No se persiste en la Orden de garantia: esta solo guarda
    ``detalles_origen_ids``. El Tipo se resuelve al leer, desde la Orden
    origen (BR-REP-019), para que la UI pueda mostrar "DET-001 · Cambio de
    bateria" sin duplicar el snapshot del Detalle original.
    """

    id: str
    tipo_reparacion_nombre: str


def listar_ordenes(contexto: ApplicationContext) -> list[OrdenReparacion]:
    """Todas las Ordenes, de la mas reciente a la mas antigua."""
    return sorted(
        contexto.ordenes.listar(),
        key=lambda orden: (orden.created_at, orden.id),
        reverse=True,
    )


def obtener_orden(
    contexto: ApplicationContext,
    orden_id: str,
) -> OrdenReparacion:
    """La Orden pedida, o ``EntidadPersistidaNoEncontradaError``."""
    return contexto.ordenes.obtener(orden_id)


def listar_tipos_reparacion(
    contexto: ApplicationContext,
) -> list[TipoReparacion]:
    """Catalogo de Tipos de Reparacion."""
    return contexto.catalogos.listar_tipos_reparacion()


def listar_estaciones(contexto: ApplicationContext) -> list[EstacionTrabajo]:
    """Catalogo de Estaciones de Trabajo."""
    return contexto.catalogos.listar_estaciones()


def listar_usuarios(contexto: ApplicationContext) -> list[Usuario]:
    """Catalogo de usuarios operativos.

    Alimenta el selector de actor DEMO del frontend. No es
    autenticacion: el backend sigue validando el rol en cada comando.
    """
    return contexto.catalogos.listar_usuarios()


def insumos_previstos_por_detalle(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
) -> dict[str, list[InsumoPrevisto]]:
    """Insumos previstos de cada Detalle de la Orden.

    Recorre ``detalle.tipo_reparacion_id -> TipoReparacionInsumos ->
    Insumo`` usando el ``CatalogosRepository``. Los catalogos se leen una
    sola vez para toda la Orden.

    Un Tipo de Reparacion sin relaciones da una lista vacia: eso es
    valido y significa que la Ejecucion no consume repuestos.

    Distinto es que una relacion EXISTA y apunte a un insumo que el
    catalogo no tiene: eso es un catalogo roto, y se levanta
    ``PersistenciaError``. Las dos situaciones se veian igual desde la UI
    -``insumos_previstos: []``- y no lo son.
    """
    if not orden.reparaciones_detail:
        return {}

    relaciones = contexto.catalogos.listar_tipo_reparacion_insumos()
    insumos = {
        insumo.id: insumo for insumo in contexto.catalogos.listar_insumos()
    }

    por_tipo: dict[str, list[InsumoPrevisto]] = {}
    for relacion in relaciones:
        insumo = insumos.get(relacion.insumo_id)
        if insumo is None:
            # Inconsistencia de datos, no una condicion de negocio.
            # Omitirla devolveria una lista parcial y la UI dejaria
            # completar la Ejecucion sin un insumo que si estaba
            # previsto: callarlo es peor que fallar.
            raise PersistenciaError(
                f"El catalogo TipoReparacionInsumos referencia el insumo "
                f"{relacion.insumo_id}, pero ese insumo no existe."
            )
        por_tipo.setdefault(relacion.tipo_reparacion_id, []).append(
            InsumoPrevisto(
                insumo_id=insumo.id,
                codigo=insumo.codigo,
                nombre=insumo.nombre,
                cantidad_prevista=relacion.cantidad,
            )
        )

    return {
        detalle.id: por_tipo.get(detalle.tipo_reparacion_id, [])
        for detalle in orden.reparaciones_detail
    }


def nombres_de_tipo_por_detalle(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
) -> dict[str, str]:
    """Nombre del Tipo de Reparacion de cada Detalle.

    Se resuelve al leer, igual que ``insumos_previstos_por_detalle``: el
    Detalle guarda el ``tipo_reparacion_id`` y el precio snapshot, no el
    nombre. El nombre es dato de catalogo vigente y NO se persiste en el
    aggregate.

    Un Detalle cuyo Tipo ya no existe en el catalogo devuelve el ID como
    nombre, en vez de romper la lectura: a diferencia de un insumo
    previsto, aqui no se pierde informacion operativa -el precio, el
    puntaje y la garantia son snapshot del Detalle-, solo la etiqueta.
    """
    if not orden.reparaciones_detail:
        return {}

    tipos = {
        tipo.id: tipo.nombre
        for tipo in contexto.catalogos.listar_tipos_reparacion()
    }
    return {
        detalle.id: tipos.get(
            detalle.tipo_reparacion_id, detalle.tipo_reparacion_id
        )
        for detalle in orden.reparaciones_detail
    }


def detalles_origen_de(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
) -> list[DetalleOrigen]:
    """Detalles origen de una garantia RMA, con el nombre de su Tipo.

    Se leen de la Orden origen (que nunca se modifica). Si esa Orden o un
    Detalle ya no se encuentra, se devuelve el ID como nombre en vez de
    romper la lectura.
    """
    if orden.orden_origen_id is None or not orden.detalles_origen_ids:
        return []
    try:
        origen = contexto.ordenes.obtener(orden.orden_origen_id)
    except EntidadPersistidaNoEncontradaError:
        nombres: dict[str, str] = {}
    else:
        nombres = nombres_de_tipo_por_detalle(contexto, origen)
    return [
        DetalleOrigen(
            id=detalle_id,
            tipo_reparacion_nombre=nombres.get(detalle_id, detalle_id),
        )
        for detalle_id in orden.detalles_origen_ids
    ]
