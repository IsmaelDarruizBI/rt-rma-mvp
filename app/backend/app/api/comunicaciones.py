"""Comunicaciones asistidas por WhatsApp y consentimiento (DEC-MI-08).

    GET  /api/communications/templates          plantillas (y variables)
    GET  /api/orders/{id}/messages/prepare?plantilla=X
         mensaje preparado con los datos de la Orden (solo lee)
    POST /api/orders/{id}/messages               intento: se abrio WhatsApp
    POST /api/orders/{id}/messages/{com}/confirm confirmacion manual
    GET  /api/clients/{id}/consents              historial y vigentes
    POST /api/clients/{id}/consents              otorgar o revocar
    GET/POST/PUT /api/admin/message-templates    administracion (PostgreSQL)

Ningun registro dice «entregado» ni «leido»: no hay proveedor que lo pruebe.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.application.comunicaciones import (
    EstadoConsentimiento,
    confirmar_comunicacion,
    consentimientos,
    guardar_plantilla,
    listar_plantillas,
    preparar,
    registrar_comunicacion,
    registrar_consentimiento,
    variables_disponibles,
)
from app.domain.models.comunicaciones import (
    ConsentimientoComunicacion,
    FinalidadComunicacion,
    PlantillaMensaje,
)

from .dependencias import ContextoDep
from .ordenes import _salida
from .schemas import OrdenOut

router = APIRouter(prefix="/api", tags=["comunicaciones"])


class PlantillasOut(BaseModel):
    editable: bool
    plantillas: list[PlantillaMensaje]
    variables: dict[str, str]


class MensajePreparadoOut(BaseModel):
    plantilla: PlantillaMensaje
    mensaje: str
    faltantes: list[str]
    destinatario: str | None
    impedimento: str | None


class ComunicacionIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    plantilla_codigo: str | None = None
    mensaje: str = Field(min_length=1)
    destinatario: str | None = None


class ConfirmacionIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    enviado: bool
    nota: str | None = None


class ConsentimientoIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    finalidad: FinalidadComunicacion
    otorgado: bool
    origen: str = Field(min_length=1)


class ConsentimientosOut(BaseModel):
    historial: list[ConsentimientoComunicacion]
    vigentes: dict[str, bool | None]


class PlantillaIn(BaseModel):
    usuario_id: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    finalidad: FinalidadComunicacion = FinalidadComunicacion.OPERATIVA
    texto: str = Field(min_length=1)
    activa: bool = True


class AltaPlantillaIn(PlantillaIn):
    codigo: str = Field(min_length=1)


def _plantillas(contexto) -> PlantillasOut:
    return PlantillasOut(
        editable=contexto.operativa.editable,
        plantillas=listar_plantillas(contexto),
        variables=variables_disponibles(),
    )


def _consentimientos(estado: EstadoConsentimiento) -> ConsentimientosOut:
    return ConsentimientosOut(
        historial=estado.historial, vigentes=estado.vigentes
    )


@router.get("/communications/templates")
def get_plantillas(contexto: ContextoDep) -> PlantillasOut:
    return _plantillas(contexto)


@router.get("/orders/{orden_id}/messages/prepare")
def get_mensaje_preparado(
    orden_id: str, plantilla: str, contexto: ContextoDep
) -> MensajePreparadoOut:
    preparado = preparar(
        contexto, orden_id=orden_id, plantilla_codigo=plantilla
    )
    return MensajePreparadoOut(
        plantilla=preparado.plantilla,
        mensaje=preparado.mensaje,
        faltantes=preparado.faltantes,
        destinatario=preparado.destinatario,
        impedimento=preparado.impedimento,
    )


@router.post("/orders/{orden_id}/messages")
def post_comunicacion(
    orden_id: str, cuerpo: ComunicacionIn, contexto: ContextoDep
) -> OrdenOut:
    orden = registrar_comunicacion(
        contexto,
        orden_id=orden_id,
        usuario_id=cuerpo.usuario_id,
        plantilla_codigo=cuerpo.plantilla_codigo,
        mensaje=cuerpo.mensaje,
        destinatario=cuerpo.destinatario,
    )
    return _salida(orden, contexto)


@router.post("/orders/{orden_id}/messages/{comunicacion_id}/confirm")
def post_confirmacion(
    orden_id: str,
    comunicacion_id: str,
    cuerpo: ConfirmacionIn,
    contexto: ContextoDep,
) -> OrdenOut:
    orden = confirmar_comunicacion(
        contexto,
        orden_id=orden_id,
        comunicacion_id=comunicacion_id,
        usuario_id=cuerpo.usuario_id,
        enviado=cuerpo.enviado,
        nota=cuerpo.nota,
    )
    return _salida(orden, contexto)


@router.get("/clients/{cliente_id}/consents")
def get_consentimientos(
    cliente_id: str, contexto: ContextoDep
) -> ConsentimientosOut:
    return _consentimientos(consentimientos(contexto, cliente_id))


@router.post("/clients/{cliente_id}/consents")
def post_consentimiento(
    cliente_id: str, cuerpo: ConsentimientoIn, contexto: ContextoDep
) -> ConsentimientosOut:
    return _consentimientos(
        registrar_consentimiento(
            contexto,
            cliente_id=cliente_id,
            usuario_id=cuerpo.usuario_id,
            finalidad=cuerpo.finalidad,
            otorgado=cuerpo.otorgado,
            origen=cuerpo.origen,
        )
    )


def _plantilla(codigo: str, cuerpo: PlantillaIn) -> PlantillaMensaje:
    return PlantillaMensaje(
        codigo=codigo.strip().upper(),
        nombre=cuerpo.nombre.strip(),
        finalidad=cuerpo.finalidad,
        texto=cuerpo.texto.strip(),
        activa=cuerpo.activa,
    )


@router.get("/admin/message-templates")
def get_plantillas_admin(contexto: ContextoDep) -> PlantillasOut:
    return _plantillas(contexto)


@router.post("/admin/message-templates")
def post_plantilla(
    cuerpo: AltaPlantillaIn, contexto: ContextoDep
) -> PlantillaMensaje:
    return guardar_plantilla(
        contexto,
        usuario_id=cuerpo.usuario_id,
        plantilla=_plantilla(cuerpo.codigo, cuerpo),
        nuevo=True,
    )


@router.put("/admin/message-templates/{codigo}")
def put_plantilla(
    codigo: str, cuerpo: PlantillaIn, contexto: ContextoDep
) -> PlantillaMensaje:
    return guardar_plantilla(
        contexto,
        usuario_id=cuerpo.usuario_id,
        plantilla=_plantilla(codigo, cuerpo),
        nuevo=False,
    )
