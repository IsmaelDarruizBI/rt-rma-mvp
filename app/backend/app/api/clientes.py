"""Endpoints de clientes (MVP v2, UAT-010).

    GET /api/clients/lookup?dni=...&usuario_id=...

Busca los datos de un cliente por DNI para completar el formulario: primero
en nuestras Ordenes y, solo si hay una fuente externa autorizada
configurada, en esa fuente. No guarda nada.
"""

from fastapi import APIRouter

from app.application import buscar_cliente_por_dni

from .dependencias import ContextoDep
from .schemas import BusquedaClienteOut

router = APIRouter(prefix="/api/clients", tags=["clientes"])


@router.get("/lookup")
def get_buscar_cliente(
    dni: str,
    usuario_id: str,
    contexto: ContextoDep,
    externa: bool = True,
) -> BusquedaClienteOut:
    """Datos de un cliente por DNI, para revisar antes de usarlos.

    ``externa=false``: solo nuestra base (la comprobacion previa al alta).
    """
    busqueda = buscar_cliente_por_dni(
        contexto, dni=dni, usuario_id=usuario_id, incluir_externa=externa
    )
    return BusquedaClienteOut.desde_aplicacion(busqueda)
