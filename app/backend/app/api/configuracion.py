"""Administracion de catalogos con auditoria (DC23, DC23AUD, BR-REP-040).

    GET  /api/admin/catalog          Tipos y Mesas, con sus habilitados
    POST /api/admin/repair-types     alta de un Tipo
    PUT  /api/admin/repair-types/{codigo}            edicion o baja
    PUT  /api/admin/stations/{codigo}/repair-types   habilitados de la Mesa
    GET  /api/admin/config-changes?entidad=&clave=   auditoria y precios
    GET  /api/admin/users                     usuarios y sus roles (DC27A)
    PUT  /api/admin/users/{codigo}/roles      roles de un usuario
    GET  /api/admin/permissions               permisos, predeterminados y hoy
    PUT  /api/admin/permissions/{codigo}      roles de un permiso (DC08)

Solo Administracion (con sesion real, 403 para los demas roles; el caso de
uso lo valida igual). Las escrituras exigen PostgreSQL (DC23).
"""

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.application.checklist import catalogo as catalogo_checklist
from app.application.checklist import (
    guardar_pregunta,
    guardar_tipo_equipo,
)
from app.application.configuracion import (
    guardar_tipo_reparacion,
    habilitar_tipos_en_mesa,
    historial_de_cambios,
)
from app.application.operativa import (
    guardar_insumo,
    guardar_motivo,
    guardar_parametro,
    listar_motivos,
    parametros,
)
from app.application.roles import (
    VistaPermiso,
    asignar_roles,
    configurar_permiso,
    listar_permisos,
    listar_usuarios_con_roles,
)
from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    PoliticaGarantiaRma,
    RolUsuario,
)
from app.domain.models.lotes import ControlInsumo
from app.domain.models.operativa import MotivoOperativo, TipoMotivo
from app.services.configuracion import ROLES_ADMINISTRACION_CONFIGURACION

from .dependencias import ContextoDep
from .schemas import UsuarioOut
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
    # DEC-MI-01: plazos segun el check-in y politica RMA (ABI-38).
    garantia_con_checkin: int = Field(default=90, ge=0)
    garantia_sin_checkin: int = Field(default=30, ge=0)
    politica_garantia_rma: PoliticaGarantiaRma | None = None


class AltaTipoReparacionIn(TipoReparacionIn):
    codigo: str = Field(min_length=1)


class TiposDeMesaIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    tipos: list[str]


class RolesIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    roles: list[RolUsuario]


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


@router.get("/users")
def get_usuarios_y_roles(contexto: ContextoDep) -> list[UsuarioOut]:
    return [
        UsuarioOut.desde_dominio(u)
        for u in listar_usuarios_con_roles(contexto)
    ]


@router.put("/users/{codigo}/roles")
def put_roles_de_usuario(
    codigo: str, cuerpo: RolesIn, contexto: ContextoDep
) -> UsuarioOut:
    return UsuarioOut.desde_dominio(
        asignar_roles(
            contexto,
            usuario_id=cuerpo.usuario_id,
            destino_id=codigo,
            roles=cuerpo.roles,
        )
    )


@router.get("/permissions")
def get_permisos(contexto: ContextoDep) -> list[VistaPermiso]:
    return listar_permisos(contexto)


@router.put("/permissions/{codigo}")
def put_permiso(
    codigo: str, cuerpo: RolesIn, contexto: ContextoDep
) -> VistaPermiso:
    return configurar_permiso(
        contexto,
        usuario_id=cuerpo.usuario_id,
        codigo=codigo,
        roles=cuerpo.roles,
    )


class MotivoIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    tipo: TipoMotivo
    nombre: str = Field(min_length=1)
    activo: bool = True
    requiere_descripcion: bool = False


class AltaMotivoIn(MotivoIn):
    codigo: str = Field(min_length=1)


class ParametroIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    valor: str = Field(min_length=1)


def _motivo(codigo: str, cuerpo: MotivoIn) -> MotivoOperativo:
    return MotivoOperativo(
        codigo=codigo.strip().upper(),
        tipo=cuerpo.tipo,
        nombre=cuerpo.nombre.strip(),
        activo=cuerpo.activo,
        requiere_descripcion=cuerpo.requiere_descripcion,
    )


@router.get("/reasons")
def get_motivos_admin(contexto: ContextoDep) -> dict:
    return {
        "editable": contexto.operativa.editable,
        "motivos": listar_motivos(contexto),
    }


@router.post("/reasons")
def post_motivo(
    cuerpo: AltaMotivoIn, contexto: ContextoDep
) -> MotivoOperativo:
    return guardar_motivo(
        contexto,
        usuario_id=cuerpo.usuario_id,
        motivo=_motivo(cuerpo.codigo, cuerpo),
        nuevo=True,
    )


@router.put("/reasons/{codigo}")
def put_motivo(
    codigo: str, cuerpo: MotivoIn, contexto: ContextoDep
) -> MotivoOperativo:
    return guardar_motivo(
        contexto,
        usuario_id=cuerpo.usuario_id,
        motivo=_motivo(codigo, cuerpo),
        nuevo=False,
    )


@router.get("/parameters")
def get_parametros(contexto: ContextoDep) -> dict:
    return {
        "editable": contexto.operativa.editable,
        "parametros": parametros(contexto),
    }


@router.put("/parameters/{clave}")
def put_parametro(
    clave: str, cuerpo: ParametroIn, contexto: ContextoDep
) -> dict[str, str]:
    return guardar_parametro(
        contexto, usuario_id=cuerpo.usuario_id, clave=clave, valor=cuerpo.valor
    )


class InsumoIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    codigo: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    unidad: str | None = None
    activo: bool = True
    # DEC-MI-10 y DEC-MI-09: control por lote o serie y precio.
    control: ControlInsumo | None = None
    precio: Decimal | None = Field(default=None, ge=0)


class AltaInsumoIn(InsumoIn):
    clave: str = Field(min_length=1)


@router.get("/supplies")
def get_insumos_admin(contexto: ContextoDep) -> dict:
    return {
        "editable": contexto.operativa.editable,
        "insumos": [
            i.model_dump(mode="json")
            for i in contexto.catalogos.listar_insumos()
        ],
    }


@router.post("/supplies")
def post_insumo(cuerpo: AltaInsumoIn, contexto: ContextoDep) -> dict:
    return guardar_insumo(
        contexto,
        usuario_id=cuerpo.usuario_id,
        clave=cuerpo.clave,
        codigo=cuerpo.codigo,
        nombre=cuerpo.nombre,
        unidad=cuerpo.unidad,
        activo=cuerpo.activo,
        nuevo=True,
        control=cuerpo.control,
        precio=cuerpo.precio,
    ).model_dump(mode="json")


@router.put("/supplies/{clave}")
def put_insumo(clave: str, cuerpo: InsumoIn, contexto: ContextoDep) -> dict:
    return guardar_insumo(
        contexto,
        usuario_id=cuerpo.usuario_id,
        clave=clave,
        codigo=cuerpo.codigo,
        nombre=cuerpo.nombre,
        unidad=cuerpo.unidad,
        activo=cuerpo.activo,
        nuevo=False,
        control=cuerpo.control,
        precio=cuerpo.precio,
    ).model_dump(mode="json")


class TipoEquipoIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    activo: bool = True


class PreguntaChecklistIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    tipo_equipo_id: str = Field(min_length=1)
    texto: str = Field(min_length=1)
    opciones: list[str] = Field(min_length=2)
    activa: bool = True
    orden: int = 0


@router.get("/checklist")
def get_checklist_admin(contexto: ContextoDep) -> dict:
    return catalogo_checklist(contexto, solo_vigentes=False)


@router.post("/equipment-types")
def post_tipo_equipo(cuerpo: TipoEquipoIn, contexto: ContextoDep) -> dict:
    return guardar_tipo_equipo(
        contexto,
        usuario_id=cuerpo.usuario_id,
        codigo=None,
        nombre=cuerpo.nombre,
        activo=cuerpo.activo,
    ).model_dump()


@router.put("/equipment-types/{codigo}")
def put_tipo_equipo(
    codigo: str, cuerpo: TipoEquipoIn, contexto: ContextoDep
) -> dict:
    return guardar_tipo_equipo(
        contexto,
        usuario_id=cuerpo.usuario_id,
        codigo=codigo,
        nombre=cuerpo.nombre,
        activo=cuerpo.activo,
    ).model_dump()


def _pregunta(contexto, codigo, cuerpo: PreguntaChecklistIn) -> dict:
    return guardar_pregunta(
        contexto,
        usuario_id=cuerpo.usuario_id,
        codigo=codigo,
        tipo_equipo_id=cuerpo.tipo_equipo_id,
        texto=cuerpo.texto,
        opciones=cuerpo.opciones,
        activa=cuerpo.activa,
        orden=cuerpo.orden,
    ).model_dump()


@router.post("/checklist-questions")
def post_pregunta(cuerpo: PreguntaChecklistIn, contexto: ContextoDep) -> dict:
    return _pregunta(contexto, None, cuerpo)


@router.put("/checklist-questions/{codigo}")
def put_pregunta(
    codigo: str, cuerpo: PreguntaChecklistIn, contexto: ContextoDep
) -> dict:
    return _pregunta(contexto, codigo, cuerpo)
