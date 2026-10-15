"""Endpoints de consulta de catalogos.

Solo lectura. El frontend los usa para poblar selectores: tipos de
reparacion al definir un Detalle, estaciones al tomar una Orden,
usuarios para el selector de actor DEMO, medios de pago para cobrar o
devolver dinero y prioridades al ingresar una Orden a la cola.
"""

from fastapi import APIRouter

from app.application import (
    listar_estaciones,
    listar_medios_pago,
    listar_tipos_reparacion,
    listar_usuarios,
)

from .dependencias import ContextoDep
from .schemas import (
    EstacionOut,
    MedioPagoOut,
    PrioridadOut,
    TipoReparacionOut,
    UsuarioOut,
)

router = APIRouter(prefix="/api/catalogs", tags=["catalogos"])


@router.get("/repair-types")
def get_tipos_reparacion(contexto: ContextoDep) -> list[TipoReparacionOut]:
    """Tipos de Reparacion del catalogo."""
    return [
        TipoReparacionOut.desde_dominio(tipo)
        for tipo in listar_tipos_reparacion(contexto)
    ]


@router.get("/stations")
def get_estaciones(contexto: ContextoDep) -> list[EstacionOut]:
    """Estaciones de trabajo configuradas."""
    return [
        EstacionOut.desde_dominio(estacion)
        for estacion in listar_estaciones(contexto)
    ]


@router.get("/users")
def get_usuarios(contexto: ContextoDep) -> list[UsuarioOut]:
    """Usuarios operativos. Alimenta el selector de actor DEMO."""
    return [
        UsuarioOut.desde_dominio(usuario)
        for usuario in listar_usuarios(contexto)
    ]


@router.get("/priorities")
def get_prioridades() -> list[PrioridadOut]:
    """Prioridades de la Orden: 1 Urgente ... 4 Normal (predeterminada)."""
    return PrioridadOut.catalogo()


@router.get("/payment-methods")
def get_medios_pago(contexto: ContextoDep) -> list[MedioPagoOut]:
    """Medios de pago y de devolucion de dinero (catalogo configurable).

    Los de ``medios_pago.json`` del directorio de catalogos o, si no
    existe, los predeterminados.
    """
    return [
        MedioPagoOut.desde_dominio(medio)
        for medio in listar_medios_pago(contexto)
    ]
