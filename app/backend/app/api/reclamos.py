"""Reclamos de garantia rechazados (DEC-MI-02).

    GET  /api/warranty-claims                 los reclamos (consulta)
    GET  /api/warranty-claims/{codigo}        un reclamo
    POST /api/warranty-claims/{codigo}/continue
         continuar como reparacion paga (Recepcion, con confirmacion)

Consultan Recepcion, Coordinacion RMA y Administracion (permiso
configurable ``RECLAMOS_CONSULTAR``).
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.application.reclamos import (
    continuar_como_pago,
    listar_reclamos,
    obtener_reclamo,
)
from app.domain.models.reclamos import ReclamoGarantia
from app.services import permisos

from .dependencias import ContextoDep
from .seguridad import exigir_rol

router = APIRouter(prefix="/api/warranty-claims", tags=["reclamos"])
_consulta = [exigir_rol(permisos.RECLAMOS_CONSULTAR)]


class ContinuarReclamoIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    confirmado: bool = False
    falla_reportada: str | None = None


@router.get("", dependencies=_consulta)
def get_reclamos(contexto: ContextoDep) -> list[ReclamoGarantia]:
    return listar_reclamos(contexto)


@router.get("/{codigo}", dependencies=_consulta)
def get_reclamo(codigo: str, contexto: ContextoDep) -> ReclamoGarantia:
    return obtener_reclamo(contexto, codigo)


@router.post("/{codigo}/continue")
def post_continuar(
    codigo: str, cuerpo: ContinuarReclamoIn, contexto: ContextoDep
) -> dict:
    orden, reclamo = continuar_como_pago(
        contexto,
        reclamo_id=codigo,
        usuario_id=cuerpo.usuario_id,
        confirmado=cuerpo.confirmado,
        falla_reportada=cuerpo.falla_reportada,
    )
    return {
        "orden_id": orden.id,
        "reclamo": reclamo.model_dump(mode="json"),
    }
