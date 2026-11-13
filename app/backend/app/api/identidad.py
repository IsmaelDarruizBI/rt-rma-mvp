"""Identidad del Equipo (DEC-MI-11).

    GET  /api/equipment/identify?imei=&numero_serie=
         candidatos por IMEI y, si no hay, por numero de serie
    GET  /api/equipment/{equipo_id}/orders   historial de esa identidad
    POST /api/orders/{id}/equipment-link     corregir la vinculacion

Nunca se vincula por similitud de nombre, modelo o cliente.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.application.identidad import (
    corregir_vinculo_equipo,
    identificar,
    ordenes_del_equipo,
)
from app.domain.identidad import CandidatoEquipo
from app.services import permisos

from .dependencias import ContextoDep
from .ordenes import _salida
from .schemas import OrdenOut
from .seguridad import exigir_rol

router = APIRouter(prefix="/api", tags=["identidad"])
_consulta = [exigir_rol(permisos.ANTECEDENTES_CONSULTAR)]


class IdentificacionOut(BaseModel):
    criterio: str | None
    candidatos: list[CandidatoEquipo]


class HistorialEquipoOut(BaseModel):
    equipo_id: str
    ordenes: list[dict]


class VinculoEquipoIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    # ``None``: «Ninguno», una identidad nueva.
    equipo_id: str | None = None
    motivo: str = Field(min_length=1)


@router.get("/equipment/identify", dependencies=_consulta)
def get_identificar(
    contexto: ContextoDep,
    imei: str | None = None,
    numero_serie: str | None = None,
) -> IdentificacionOut:
    criterio, encontrados = identificar(
        contexto, imei=imei, numero_serie=numero_serie
    )
    return IdentificacionOut(criterio=criterio, candidatos=encontrados)


@router.get("/equipment/{equipo_id}/orders", dependencies=_consulta)
def get_historial_equipo(
    equipo_id: str, contexto: ContextoDep
) -> HistorialEquipoOut:
    return HistorialEquipoOut(
        equipo_id=equipo_id,
        ordenes=[
            {
                "orden_id": o.id,
                "origen": o.origen.value,
                "estado_workflow": o.estado_workflow.value,
                "creada_en": o.created_at,
                "entregada_en": o.entrega.fecha if o.entrega else None,
                "falla_reportada": o.equipo.falla_reportada,
                "orden_origen_id": o.orden_origen_id,
                "trabajos": [
                    {
                        "detalle_id": d.id,
                        "tipo_reparacion_id": d.tipo_reparacion_id,
                        "estado": d.estado.value,
                        "garantia_dias": d.garantia_dias,
                    }
                    for d in o.reparaciones_detail
                ],
                "custodia": (
                    "ENTREGADO"
                    if o.entrega
                    else "EN_LOCAL"
                    if o.recepcion and o.recepcion.confirmacion
                    else "SIN_CONFIRMAR"
                ),
            }
            for o in ordenes_del_equipo(contexto, equipo_id)
        ],
    )


@router.post("/orders/{orden_id}/equipment-link")
def post_vinculo_equipo(
    orden_id: str, cuerpo: VinculoEquipoIn, contexto: ContextoDep
) -> OrdenOut:
    orden = corregir_vinculo_equipo(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        equipo_id=cuerpo.equipo_id,
        motivo=cuerpo.motivo,
    )
    return _salida(orden, contexto)
