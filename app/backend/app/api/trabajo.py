"""Bandejas de trabajo por rol y cola de taller.

Consultas de solo lectura (el MVP no autentica lecturas): ``usuario_id`` es
el usuario de demostracion elegido, solo para saber que bandejas mostrarle
y que acciones le corresponden. Los comandos -por ejemplo, tomar una Orden
desde la cola- siguen siendo los endpoints de siempre. El router no decide
nada: delega en ``app.application``.
"""

from fastapi import APIRouter

from app.application import bandejas_de_inicio, bandejas_de_taller

from .dependencias import ContextoDep
from .schemas_trabajo import BandejasOut

router = APIRouter(prefix="/api/work", tags=["bandejas"])


@router.get("/inbox")
def get_bandejas(usuario_id: str, contexto: ContextoDep) -> BandejasOut:
    """Las bandejas del rol del usuario: lo que tiene que resolver y lo
    que sigue (Recepcion, Tecnico, Coordinacion RMA o Administracion)."""
    return BandejasOut.desde_aplicacion(
        bandejas_de_inicio(contexto, usuario_id=usuario_id)
    )


@router.get("/workshop")
def get_taller(usuario_id: str, contexto: ContextoDep) -> BandejasOut:
    """El taller: tomadas del tecnico, cola por prioridad y tomas activas."""
    return BandejasOut.desde_aplicacion(
        bandejas_de_taller(contexto, usuario_id=usuario_id)
    )
