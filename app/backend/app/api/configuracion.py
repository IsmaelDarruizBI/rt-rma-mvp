"""Administracion de catalogos con auditoria (DC23, DC23AUD, BR-REP-040).

    GET  /api/admin/catalog          Tipos y Mesas, con sus habilitados
    POST /api/admin/repair-types     alta de un Tipo
    PUT  /api/admin/repair-types/{codigo}            edicion o baja
    PUT  /api/admin/stations/{codigo}/repair-types   habilitados de la Mesa
    GET  /api/admin/config-changes?entidad=&clave=   auditoria y precios

Solo Administracion (con sesion real, 403 para los demas roles; el caso de
uso lo valida igual). Las escrituras exigen PostgreSQL (DC23).
"""

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.application.configuracion import (
    guardar_tipo_reparacion,
    habilitar_tipos_en_mesa,
    historial_de_cambios,
)
from app.domain.models import CambioConfiguracion, EntidadConfiguracion
from app.services.configuracion import ROLES_ADMINISTRACION_CONFIGURACION

from .dependencias import ContextoDep
from .seguridad import exigir_rol

router = APIRouter(
    prefix="/api/admin",
    tags=["administracion"],
    dependencies=[exigir_rol(ROLES_ADMINISTRACION_CONFIGURACION)],
)


class TipoReparacionIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    precio: Decimal = Field(ge=0)
    puntaje: int = Field(ge=0)
    garantia_dias: int = Field(ge=0)
    activo: bool = True


class AltaTipoReparacionIn(TipoReparacionIn):
    codigo: str = Field(min_length=1)


class TiposDeMesaIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    tipos: list[str]


@router.get("/catalog")
def get_catalogo(contexto: ContextoDep) -> dict:
    catalogos = contexto.catalogos
    habilitados: dict[str, list[str]] = {}
    for compatible in catalogos.listar_tipo_reparacion_estaciones():
        habilitados.setdefault(compatible.estacion_id, []).append(
            compatible.tipo_reparacion_id
        )
    return {
        "editable": contexto.configuracion is not None,
        "tipos": [
            t.model_dump(mode="json")
            for t in catalogos.listar_tipos_reparacion()
        ],
        "mesas": [
            {
                **m.model_dump(mode="json"),
                "tipos": sorted(habilitados.get(m.id, [])),
            }
            for m in catalogos.listar_estaciones()
        ],
    }


@router.post("/repair-types")
def post_tipo(cuerpo: AltaTipoReparacionIn, contexto: ContextoDep) -> dict:
    tipo = guardar_tipo_reparacion(contexto, **cuerpo.model_dump(), nuevo=True)
    return tipo.model_dump(mode="json")


@router.put("/repair-types/{codigo}")
def put_tipo(
    codigo: str, cuerpo: TipoReparacionIn, contexto: ContextoDep
) -> dict:
    tipo = guardar_tipo_reparacion(
        contexto, codigo=codigo, **cuerpo.model_dump(), nuevo=False
    )
    return tipo.model_dump(mode="json")


@router.put("/stations/{codigo}/repair-types")
def put_tipos_de_mesa(
    codigo: str, cuerpo: TiposDeMesaIn, contexto: ContextoDep
) -> CambioConfiguracion:
    return habilitar_tipos_en_mesa(
        contexto,
        usuario_id=cuerpo.usuario_id,
        estacion_id=codigo,
        tipo_ids=cuerpo.tipos,
    )


@router.get("/config-changes")
def get_cambios(
    contexto: ContextoDep,
    entidad: EntidadConfiguracion | None = None,
    clave: str | None = None,
) -> list[CambioConfiguracion]:
    return historial_de_cambios(contexto, entidad=entidad, clave=clave)
