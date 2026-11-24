"""Administracion de catalogos con auditoria (DC23, DC23AUD, BR-REP-040).

    GET  /api/admin/catalog          Tipos y Mesas, con sus habilitados
    POST /api/admin/repair-types     alta de un Tipo
    PUT  /api/admin/repair-types/{codigo}            edicion o baja
    PUT  /api/admin/repair-types/{codigo}/model-prices
                                     precios por modelo de un Tipo
    GET  /api/admin/device-models    modelos de equipo, activos o no
    POST /api/admin/device-models    alta de un modelo (MOD-NNNN)
    PUT  /api/admin/device-models/{codigo}           edicion o baja
    PUT  /api/admin/stations/{codigo}/repair-types   habilitados de la Mesa
    GET  /api/admin/config-changes?entidad=&clave=   auditoria y precios
    GET  /api/admin/users                     usuarios y sus roles (DC27A)
    PUT  /api/admin/users/{codigo}/roles      roles de un usuario
    GET  /api/admin/permissions               permisos, predeterminados y hoy
    PUT  /api/admin/permissions/{codigo}      roles de un permiso (DC08)
    GET  /api/admin/payment-methods           medios de pago y su recargo
    PUT  /api/admin/payment-methods/{codigo}  recargo de un medio (UX-08)
    GET  /api/admin/company                   datos de la empresa (DEC-AJ-09)
    PUT  /api/admin/company                   edicion, con auditoria
    GET  /api/admin/terms                     versiones de los terminos
    POST /api/admin/terms                     publica una version nueva

Solo Administracion (con sesion real, 403 para los demas roles; el caso de
uso lo valida igual). Las escrituras exigen PostgreSQL (DC23).
"""

from decimal import Decimal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.application.checklist import catalogo as catalogo_checklist
from app.application.checklist import (
    guardar_pregunta,
    sincronizar_tipos_equipo,
)
from app.application.comprobantes import (
    datos_empresa,
    guardar_datos_empresa,
    publicar_terminos,
    versiones_terminos,
)
from app.application.configuracion import (
    CONSERVAR,
    guardar_modelo_equipo,
    guardar_precios_modelo,
    guardar_tipo_reparacion,
    habilitar_tipos_en_mesa,
    historial_de_cambios,
    listar_modelos_administrables,
)
from app.application.operativa import (
    MANTENER,
    guardar_insumo,
    guardar_motivo,
    guardar_parametro,
    guardar_recargo_medio_pago,
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
    ContenidoTextoLegal,
    DatosEmpresa,
    EntidadConfiguracion,
    ModeloEquipo,
    PoliticaGarantiaRma,
    PrecioTipoModelo,
    RolUsuario,
    TextoLegal,
)
from app.domain.models.lotes import ControlInsumo
from app.domain.models.operativa import MotivoOperativo, TipoMotivo
from app.services import permisos

from .dependencias import ContextoDep
from .schemas import MedioPagoOut, UsuarioOut
from .seguridad import exigir_rol, verificar_permiso

router = APIRouter(prefix="/api/admin", tags=["administracion"])

# CFG-03: cada catalogo con su permiso (configurable); lo sensible sigue
# siendo de Administracion (no configurable).
_tipos = [exigir_rol(permisos.TIPO_REPARACION_GESTIONAR)]
_catalogo = [
    exigir_rol(
        permisos.TIPO_REPARACION_GESTIONAR, permisos.MESA_TIPOS_GESTIONAR
    )
]
_mesas = [exigir_rol(permisos.MESA_TIPOS_GESTIONAR)]
# DEC-AJ-12: precios por modelo y modelos de equipo. La lista de modelos la
# necesitan los dos (la grilla de precios muestra todos los modelos).
_precios = [exigir_rol(permisos.PRECIOS_GESTIONAR)]
_modelos = [exigir_rol(permisos.MODELO_EQUIPO_GESTIONAR)]
_lista_modelos = [
    exigir_rol(permisos.MODELO_EQUIPO_GESTIONAR, permisos.PRECIOS_GESTIONAR)
]
_motivos = [exigir_rol(permisos.MOTIVO_GESTIONAR)]
_insumos = [exigir_rol(permisos.INSUMO_GESTIONAR)]
_checklist = [exigir_rol(permisos.CHECKLIST_GESTIONAR)]
_roles = [exigir_rol(permisos.ROLES_ADMINISTRAR)]
_sistema = [exigir_rol(permisos.CONFIGURACION_ADMINISTRAR)]

# La auditoria de una entidad la ve quien la administra; la completa,
# Administracion.
PERMISO_DE_ENTIDAD = {
    EntidadConfiguracion.TIPO_REPARACION: (
        permisos.TIPO_REPARACION_GESTIONAR,
    ),
    EntidadConfiguracion.MESA_TRABAJO: (permisos.MESA_TIPOS_GESTIONAR,),
    EntidadConfiguracion.MODELO_EQUIPO: (permisos.MODELO_EQUIPO_GESTIONAR,),
    EntidadConfiguracion.PRECIO_MODELO: (permisos.PRECIOS_GESTIONAR,),
    EntidadConfiguracion.MOTIVO: (permisos.MOTIVO_GESTIONAR,),
    EntidadConfiguracion.INSUMO: (permisos.INSUMO_GESTIONAR,),
    EntidadConfiguracion.PLANTILLA: (permisos.PLANTILLA_GESTIONAR,),
    EntidadConfiguracion.CHECKLIST: (permisos.CHECKLIST_GESTIONAR,),
    EntidadConfiguracion.PROVEEDOR: (permisos.PROVEEDOR_GESTIONAR,),
    EntidadConfiguracion.USUARIO: (permisos.ROLES_ADMINISTRAR,),
    EntidadConfiguracion.PERMISO: (permisos.ROLES_ADMINISTRAR,),
}


class TipoReparacionIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    precio: Decimal = Field(ge=0)
    puntaje: int = Field(ge=0)
    activo: bool = True
    # DEC-MI-01: plazos segun el check-in y politica RMA (ABI-38).
    # CFG-06 (DF-1, DF-2): todos opcionales. El que no viene se conserva en
    # la edicion; en el alta, el plazo generico toma el de con check-in.
    garantia_dias: int | None = Field(default=None, ge=0)
    garantia_con_checkin: int | None = Field(default=None, ge=0)
    garantia_sin_checkin: int | None = Field(default=None, ge=0)
    politica_garantia_rma: PoliticaGarantiaRma | None = None
    # DEC-AJ-12: si no viene se conserva (en el alta, precio unico).
    precio_por_modelo: bool | None = None


GARANTIAS = (
    "garantia_dias",
    "garantia_con_checkin",
    "garantia_sin_checkin",
    "politica_garantia_rma",
)


def _datos_de_tipo(cuerpo: TipoReparacionIn) -> dict:
    """Los campos de garantia que no vinieron se conservan (CFG-06). Un
    plazo en null tampoco cambia nada; la politica en null es «sin
    definir», como antes."""
    datos = cuerpo.model_dump()
    for campo in GARANTIAS:
        informado = campo in cuerpo.model_fields_set
        if not informado or (
            datos[campo] is None and campo != "politica_garantia_rma"
        ):
            datos[campo] = CONSERVAR
    if datos["precio_por_modelo"] is None:
        datos["precio_por_modelo"] = CONSERVAR
    return datos


class AltaTipoReparacionIn(TipoReparacionIn):
    # CFG-01: opcional. Sin codigo lo genera la base (TR-NNN); el que
    # informa un cliente anterior o un script se respeta.
    codigo: str | None = None


class TiposDeMesaIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    tipos: list[str]


class RolesIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    roles: list[RolUsuario]


@router.get("/catalog", dependencies=_catalogo)
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


@router.post("/repair-types", dependencies=_tipos)
def post_tipo(cuerpo: AltaTipoReparacionIn, contexto: ContextoDep) -> dict:
    tipo = guardar_tipo_reparacion(
        contexto, **_datos_de_tipo(cuerpo), nuevo=True
    )
    return tipo.model_dump(mode="json")


@router.put("/repair-types/{codigo}", dependencies=_tipos)
def put_tipo(
    codigo: str, cuerpo: TipoReparacionIn, contexto: ContextoDep
) -> dict:
    tipo = guardar_tipo_reparacion(
        contexto, codigo=codigo, **_datos_de_tipo(cuerpo), nuevo=False
    )
    return tipo.model_dump(mode="json")


class PrecioModeloIn(BaseModel):
    modelo_equipo_id: str = Field(min_length=1)
    # ``None``: retira el precio del modelo (queda sin precio de catalogo).
    precio: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class PreciosModeloIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    precios: list[PrecioModeloIn] = Field(min_length=1)


@router.put("/repair-types/{codigo}/model-prices", dependencies=_precios)
def put_precios_modelo(
    codigo: str, cuerpo: PreciosModeloIn, contexto: ContextoDep
) -> dict:
    """DEC-AJ-12: fija o retira precios del Tipo por modelo, con auditoria
    (entidad PRECIO_MODELO), todo o nada. Devuelve el Tipo y los cambios."""
    cambios = guardar_precios_modelo(
        contexto,
        usuario_id=cuerpo.usuario_id,
        precios=[
            PrecioTipoModelo(
                tipo_reparacion_id=codigo,
                modelo_equipo_id=precio.modelo_equipo_id,
                precio=precio.precio,
            )
            for precio in cuerpo.precios
        ],
    )
    tipo = contexto.catalogos.obtener_tipo_reparacion(codigo)
    return {
        "tipo": tipo.model_dump(mode="json"),
        "cambios": [c.model_dump(mode="json") for c in cambios],
    }


class ModeloEquipoIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    marca: str = Field(min_length=1)
    modelo: str = Field(min_length=1)
    variante: str | None = None
    numeros_modelo: list[str] = Field(default_factory=list)
    activo: bool = True


class AltaModeloEquipoIn(ModeloEquipoIn):
    # Opcional: sin codigo lo genera la base (MOD-NNNN).
    codigo: str | None = None


def _modelo_out(modelo: ModeloEquipo) -> dict:
    return {**modelo.model_dump(mode="json"), "nombre": modelo.nombre}


@router.get("/device-models", dependencies=_lista_modelos)
def get_modelos_admin(contexto: ContextoDep) -> dict:
    """DEC-AJ-12 (D-12.5): todos los modelos, activos o no."""
    return {
        "editable": contexto.configuracion is not None,
        "modelos": [
            _modelo_out(m) for m in listar_modelos_administrables(contexto)
        ],
    }


@router.post("/device-models", dependencies=_modelos)
def post_modelo(cuerpo: AltaModeloEquipoIn, contexto: ContextoDep) -> dict:
    return _modelo_out(
        guardar_modelo_equipo(contexto, **cuerpo.model_dump(), nuevo=True)
    )


@router.put("/device-models/{codigo}", dependencies=_modelos)
def put_modelo(
    codigo: str, cuerpo: ModeloEquipoIn, contexto: ContextoDep
) -> dict:
    return _modelo_out(
        guardar_modelo_equipo(
            contexto, codigo=codigo, **cuerpo.model_dump(), nuevo=False
        )
    )


@router.put("/stations/{codigo}/repair-types", dependencies=_mesas)
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
    request: Request,
    contexto: ContextoDep,
    entidad: EntidadConfiguracion | None = None,
    clave: str | None = None,
) -> list[CambioConfiguracion]:
    """La auditoria: la de una entidad, para quien la administra (CFG-03);
    la completa (o la de parametros y recargos), solo Administracion."""
    verificar_permiso(
        request,
        contexto,
        permisos.CONFIGURACION_ADMINISTRAR,
        *PERMISO_DE_ENTIDAD.get(entidad, ()),
    )
    return historial_de_cambios(contexto, entidad=entidad, clave=clave)


@router.get("/users", dependencies=_roles)
def get_usuarios_y_roles(contexto: ContextoDep) -> list[UsuarioOut]:
    return [
        UsuarioOut.desde_dominio(u)
        for u in listar_usuarios_con_roles(contexto)
    ]


@router.put("/users/{codigo}/roles", dependencies=_roles)
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


@router.get("/permissions", dependencies=_roles)
def get_permisos(contexto: ContextoDep) -> list[VistaPermiso]:
    return listar_permisos(contexto)


@router.put("/permissions/{codigo}", dependencies=_roles)
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
    # CFG-01: opcional; sin codigo lo genera la base (CANC-NNN o INT-NNN).
    codigo: str | None = None


class ParametroIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    valor: str = Field(min_length=1)


@router.get("/reasons", dependencies=_motivos)
def get_motivos_admin(contexto: ContextoDep) -> dict:
    return {
        "editable": contexto.operativa.editable,
        "motivos": listar_motivos(contexto),
    }


@router.post("/reasons", dependencies=_motivos)
def post_motivo(
    cuerpo: AltaMotivoIn, contexto: ContextoDep
) -> MotivoOperativo:
    return guardar_motivo(contexto, **cuerpo.model_dump(), nuevo=True)


@router.put("/reasons/{codigo}", dependencies=_motivos)
def put_motivo(
    codigo: str, cuerpo: MotivoIn, contexto: ContextoDep
) -> MotivoOperativo:
    return guardar_motivo(
        contexto, codigo=codigo, **cuerpo.model_dump(), nuevo=False
    )


@router.get("/parameters", dependencies=_sistema)
def get_parametros(contexto: ContextoDep) -> dict:
    return {
        "editable": contexto.operativa.editable,
        "parametros": parametros(contexto),
    }


@router.put("/parameters/{clave}", dependencies=_sistema)
def put_parametro(
    clave: str, cuerpo: ParametroIn, contexto: ContextoDep
) -> dict[str, str]:
    return guardar_parametro(
        contexto, usuario_id=cuerpo.usuario_id, clave=clave, valor=cuerpo.valor
    )


class RecargoMedioPagoIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    recargo_porcentaje: Decimal = Field(ge=0, le=100)


@router.get("/payment-methods", dependencies=_sistema)
def get_medios_pago_admin(contexto: ContextoDep) -> dict:
    """UX-08: los medios de pago con su recargo, para Administracion."""
    return {
        "editable": contexto.operativa.editable,
        "medios": [
            MedioPagoOut.desde_dominio(m).model_dump(mode="json")
            for m in contexto.catalogos.listar_medios_pago()
        ],
    }


@router.put("/payment-methods/{codigo}", dependencies=_sistema)
def put_recargo_medio_pago(
    codigo: str, cuerpo: RecargoMedioPagoIn, contexto: ContextoDep
) -> MedioPagoOut:
    return MedioPagoOut.desde_dominio(
        guardar_recargo_medio_pago(
            contexto,
            usuario_id=cuerpo.usuario_id,
            medio_id=codigo,
            porcentaje=cuerpo.recargo_porcentaje,
        )
    )


class DatosEmpresaIn(BaseModel):
    """DEC-AJ-09: lo que edita «Datos de la empresa». Un campo vacio queda
    sin informar; el nombre comercial es obligatorio."""

    usuario_id: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    razon_social: str | None = None
    cuit: str | None = None
    direccion: str | None = None
    telefono: str | None = None
    email: str | None = None
    horario: str | None = None
    pie_comprobante: str | None = None


@router.get("/company", dependencies=_sistema)
def get_datos_empresa(contexto: ContextoDep) -> dict:
    return {
        "editable": contexto.operativa.editable,
        "empresa": datos_empresa(contexto).model_dump(mode="json"),
    }


@router.put("/company", dependencies=_sistema)
def put_datos_empresa(
    cuerpo: DatosEmpresaIn, contexto: ContextoDep
) -> DatosEmpresa:
    datos = cuerpo.model_dump(exclude={"usuario_id"})
    return guardar_datos_empresa(
        contexto, usuario_id=cuerpo.usuario_id, datos=datos
    )


class TerminosIn(BaseModel):
    """DEC-AJ-09: una version nueva y completa de los terminos y
    condiciones. Los apartados se numeran en el orden recibido."""

    usuario_id: str = Field(min_length=1)
    titulo: str = Field(min_length=1)
    contenido: ContenidoTextoLegal


@router.get("/terms", dependencies=_sistema)
def get_terminos(contexto: ContextoDep) -> dict:
    """Las versiones publicadas (de la primera a la ultima) y la vigente."""
    vista = versiones_terminos(contexto)
    return {
        "editable": contexto.operativa.editable,
        "tipo": vista.tipo.value,
        "vigente": (
            vista.vigente.model_dump(mode="json") if vista.vigente else None
        ),
        "versiones": [v.model_dump(mode="json") for v in vista.versiones],
    }


@router.post("/terms", dependencies=_sistema)
def post_terminos(cuerpo: TerminosIn, contexto: ContextoDep) -> TextoLegal:
    return publicar_terminos(
        contexto,
        usuario_id=cuerpo.usuario_id,
        titulo=cuerpo.titulo,
        contenido=cuerpo.contenido,
    )


class InsumoIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    # CFG-01 (D4): opcional. En el alta, sin codigo se usa el identificador;
    # en la edicion no cambia (si se informa, debe ser el mismo).
    codigo: str | None = None
    nombre: str = Field(min_length=1)
    unidad: str | None = None
    activo: bool = True
    # DEC-MI-10 y DEC-MI-09: control por lote o serie y precio.
    control: ControlInsumo | None = None
    precio: Decimal | None = Field(default=None, ge=0)
    # DEC-AJ-11: opcional; null lo quita. En la edicion, si no se informa,
    # se conserva el actual.
    stock_minimo: Decimal | None = Field(default=None, ge=0)

    def stock_minimo_pedido(self):
        if "stock_minimo" in self.model_fields_set:
            return self.stock_minimo
        return MANTENER


class AltaInsumoIn(InsumoIn):
    # CFG-01 (D4): opcional; sin identificador lo genera la base (INS-NNN).
    clave: str | None = None


@router.get("/supplies", dependencies=_insumos)
def get_insumos_admin(contexto: ContextoDep) -> dict:
    return {
        "editable": contexto.operativa.editable,
        "insumos": [
            i.model_dump(mode="json")
            for i in contexto.catalogos.listar_insumos()
        ],
    }


@router.post("/supplies", dependencies=_insumos)
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
        stock_minimo=cuerpo.stock_minimo,
    ).model_dump(mode="json")


@router.put("/supplies/{clave}", dependencies=_insumos)
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
        stock_minimo=cuerpo.stock_minimo_pedido(),
    ).model_dump(mode="json")


class SincronizarTiposIn(BaseModel):
    usuario_id: str = Field(min_length=1)


class PreguntaChecklistIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    tipo_equipo_id: str = Field(min_length=1)
    texto: str = Field(min_length=1)
    opciones: list[str] = Field(min_length=2)
    activa: bool = True
    orden: int = 0


@router.get("/checklist", dependencies=_checklist)
def get_checklist_admin(contexto: ContextoDep) -> dict:
    return catalogo_checklist(contexto, solo_vigentes=False)


@router.post("/equipment-types/sync", dependencies=_checklist)
def post_sincronizar_tipos(
    cuerpo: SincronizarTiposIn, contexto: ContextoDep
) -> dict:
    """DC12: actualiza la copia de los Tipos de Equipo desde el catalogo
    de Ventas (solo lectura). RMA no crea ni edita tipos: no hay alta ni
    edicion. 409 si la columna de origen no esta definida; 503 si el
    origen no responde (la copia no cambia)."""
    resultado = sincronizar_tipos_equipo(
        contexto, usuario_id=cuerpo.usuario_id
    )
    return {
        "campo": resultado.campo,
        "origen": resultado.origen,
        "fecha": resultado.fecha.isoformat(),
        "vigentes": resultado.vigentes,
        "nuevos": resultado.nuevos,
        "reactivados": resultado.reactivados,
        "dados_de_baja": resultado.dados_de_baja,
        "sin_cambios": resultado.sin_cambios,
    }


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


@router.post("/checklist-questions", dependencies=_checklist)
def post_pregunta(cuerpo: PreguntaChecklistIn, contexto: ContextoDep) -> dict:
    return _pregunta(contexto, None, cuerpo)


@router.put("/checklist-questions/{codigo}", dependencies=_checklist)
def put_pregunta(
    codigo: str, cuerpo: PreguntaChecklistIn, contexto: ContextoDep
) -> dict:
    return _pregunta(contexto, codigo, cuerpo)
