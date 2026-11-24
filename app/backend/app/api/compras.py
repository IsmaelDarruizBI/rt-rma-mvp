"""Compras (DEC-MI-09). Solo sobre PostgreSQL: en la demo JSON responde que
no esta disponible.

    GET  /api/purchases/status                     si Compras esta disponible
    GET  /api/purchases/suppliers                  proveedores
    GET  /api/purchases/requests                   solicitudes
    POST /api/purchases/requests                   solicitud manual o desde
                                                   una sugerencia (FALTANTE
                                                   o STOCK_MINIMO)
    POST /api/purchases/requests/{id}/discard      descartar con motivo
    GET  /api/purchases/suggestions                reposicion sugerida
                                                   (faltantes y minimo)
    GET  /api/purchases/orders[/{id}]              ordenes de compra
    POST /api/purchases/orders                     crear (borrador)
    POST /api/purchases/orders/{id}/confirm        confirmar (sin aprobacion)
    POST /api/purchases/orders/{id}/cancel         cancelar sin recepciones
    POST /api/purchases/orders/{id}/receipts       recibir (parcial o total)
    GET  /api/purchases/costs?insumo_id=           costos historicos
    GET/POST/PUT /api/admin/suppliers              proveedores (Administracion)
"""

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.application.compras import (
    cancelar,
    confirmar,
    costos_de_compra,
    crear_orden_compra,
    crear_solicitud,
    descartar,
    disponible,
    guardar_proveedor,
    listar_ordenes_compra,
    listar_proveedores,
    listar_solicitudes,
    obtener_orden_compra,
    recibir,
    sugerencias_de_compra,
)
from app.domain.models.compras import (
    CostoCompra,
    ItemOrdenCompra,
    LineaRecepcion,
    OrdenCompra,
    OrigenSolicitud,
    Proveedor,
    SolicitudCompra,
    SugerenciaCompra,
)
from app.services import permisos

from .dependencias import ContextoDep
from .idempotencia import idempotente
from .seguridad import exigir_rol

router = APIRouter(tags=["compras"])
_consulta = [exigir_rol(permisos.COMPRAS_CONSULTAR)]
# CFG-03 (D5, DF-5): cada accion de Compras con su permiso, tambien en la
# API (antes solo el servicio controlaba los comandos).
_solicitar = [exigir_rol(permisos.COMPRA_SOLICITAR)]
_crear_oc = [exigir_rol(permisos.OC_CREAR)]
_confirmar_oc = [exigir_rol(permisos.OC_CONFIRMAR)]
# Cancelar: OC_CANCELAR, o OC_CREAR para el borrador propio (el servicio
# decide segun el estado y quien la creo).
_cancelar_oc = [exigir_rol(permisos.OC_CANCELAR, permisos.OC_CREAR)]
_recibir = [exigir_rol(permisos.COMPRA_RECIBIR)]
_admin = [exigir_rol(permisos.PROVEEDOR_GESTIONAR)]


class ProveedorIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    cuit: str | None = None
    telefono: str | None = None
    email: str | None = None
    contacto: str | None = None
    activo: bool = True

    def datos(self) -> dict:
        datos = self.model_dump(exclude={"usuario_id"})
        return {
            k: (v.strip() or None)
            if isinstance(v, str) and k != "nombre"
            else v
            for k, v in datos.items()
        } | {"nombre": self.nombre.strip()}


class SolicitudIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    insumo_id: str = Field(min_length=1)
    cantidad: Decimal = Field(gt=0)
    motivo: str = Field(min_length=1)
    origen: OrigenSolicitud = OrigenSolicitud.MANUAL
    ordenes: list[str] = Field(default_factory=list)


class MotivoIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    motivo: str = Field(min_length=1)


class UsuarioIn(BaseModel):
    usuario_id: str = Field(min_length=1)


class OrdenCompraIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    proveedor_id: str = Field(min_length=1)
    items: list[ItemOrdenCompra] = Field(min_length=1)
    solicitudes: list[str] = Field(default_factory=list)
    observaciones: str | None = None


class LineaRecepcionIn(BaseModel):
    insumo_id: str = Field(min_length=1)
    cantidad: Decimal = Field(gt=0)
    costo_unitario: Decimal = Field(ge=0)
    lote: str | None = None
    series: list[str] = Field(default_factory=list)
    diferencia: str | None = None


class RecepcionIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    lineas: list[LineaRecepcionIn] = Field(min_length=1)
    remito: str | None = None
    observaciones: str | None = None


@router.get("/api/purchases/status")
def get_estado(contexto: ContextoDep) -> dict:
    return {"disponible": disponible(contexto)}


@router.get("/api/purchases/suppliers", dependencies=_consulta)
def get_proveedores(contexto: ContextoDep) -> list[Proveedor]:
    return listar_proveedores(contexto)


@router.get("/api/purchases/requests", dependencies=_consulta)
def get_solicitudes(contexto: ContextoDep) -> list[SolicitudCompra]:
    return listar_solicitudes(contexto)


@router.post("/api/purchases/requests", dependencies=_solicitar)
def post_solicitud(
    cuerpo: SolicitudIn, contexto: ContextoDep
) -> SolicitudCompra:
    return crear_solicitud(
        contexto,
        usuario_id=cuerpo.usuario_id,
        insumo_id=cuerpo.insumo_id,
        cantidad=cuerpo.cantidad,
        motivo=cuerpo.motivo,
        origen=cuerpo.origen,
        ordenes=cuerpo.ordenes,
    )


@router.post(
    "/api/purchases/requests/{solicitud_id}/discard", dependencies=_solicitar
)
def post_descartar(
    solicitud_id: str, cuerpo: MotivoIn, contexto: ContextoDep
) -> SolicitudCompra:
    return descartar(
        contexto,
        usuario_id=cuerpo.usuario_id,
        solicitud_id=solicitud_id,
        motivo=cuerpo.motivo,
    )


@router.get("/api/purchases/suggestions", dependencies=_consulta)
def get_sugerencias(contexto: ContextoDep) -> list[SugerenciaCompra]:
    return sugerencias_de_compra(contexto)


@router.get("/api/purchases/orders", dependencies=_consulta)
def get_ordenes(contexto: ContextoDep) -> list[OrdenCompra]:
    return listar_ordenes_compra(contexto)


@router.get("/api/purchases/orders/{orden_id}", dependencies=_consulta)
def get_orden(orden_id: str, contexto: ContextoDep) -> OrdenCompra:
    return obtener_orden_compra(contexto, orden_id)


@router.post("/api/purchases/orders", dependencies=_crear_oc)
def post_orden(cuerpo: OrdenCompraIn, contexto: ContextoDep) -> OrdenCompra:
    return crear_orden_compra(
        contexto,
        usuario_id=cuerpo.usuario_id,
        proveedor_id=cuerpo.proveedor_id,
        items=cuerpo.items,
        solicitudes=cuerpo.solicitudes,
        observaciones=cuerpo.observaciones,
    )


@router.post(
    "/api/purchases/orders/{orden_id}/confirm", dependencies=_confirmar_oc
)
def post_confirmar(
    orden_id: str, cuerpo: UsuarioIn, contexto: ContextoDep
) -> OrdenCompra:
    return confirmar(contexto, usuario_id=cuerpo.usuario_id, orden_id=orden_id)


@router.post(
    "/api/purchases/orders/{orden_id}/cancel", dependencies=_cancelar_oc
)
def post_cancelar(
    orden_id: str, cuerpo: MotivoIn, contexto: ContextoDep
) -> OrdenCompra:
    return cancelar(
        contexto,
        usuario_id=cuerpo.usuario_id,
        orden_id=orden_id,
        motivo=cuerpo.motivo,
    )


@router.post(
    "/api/purchases/orders/{compra_id}/receipts", dependencies=_recibir
)
@idempotente("RECIBIR_COMPRA")
def post_recepcion(
    compra_id: str, cuerpo: RecepcionIn, contexto: ContextoDep
) -> OrdenCompra:
    # ``compra_id``: la idempotencia reserva ``orden_id`` para las Ordenes
    # de Reparacion.
    return recibir(
        contexto,
        usuario_id=cuerpo.usuario_id,
        orden_id=compra_id,
        lineas=[
            LineaRecepcion(**linea.model_dump()) for linea in cuerpo.lineas
        ],
        remito=cuerpo.remito,
        observaciones=cuerpo.observaciones,
    )


@router.get("/api/purchases/costs", dependencies=_consulta)
def get_costos(
    contexto: ContextoDep, insumo_id: str | None = None
) -> list[CostoCompra]:
    return costos_de_compra(contexto, insumo_id)


@router.get("/api/admin/suppliers", dependencies=_admin)
def get_proveedores_admin(contexto: ContextoDep) -> dict:
    return {
        "editable": disponible(contexto),
        "proveedores": listar_proveedores(contexto),
    }


@router.post("/api/admin/suppliers", dependencies=_admin)
def post_proveedor(cuerpo: ProveedorIn, contexto: ContextoDep) -> Proveedor:
    return guardar_proveedor(
        contexto,
        usuario_id=cuerpo.usuario_id,
        datos=cuerpo.datos(),
        codigo=None,
    )


@router.put("/api/admin/suppliers/{codigo}", dependencies=_admin)
def put_proveedor(
    codigo: str, cuerpo: ProveedorIn, contexto: ContextoDep
) -> Proveedor:
    return guardar_proveedor(
        contexto,
        usuario_id=cuerpo.usuario_id,
        datos=cuerpo.datos(),
        codigo=codigo,
    )
