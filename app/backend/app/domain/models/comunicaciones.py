"""Comunicaciones asistidas y consentimiento (DEC-MI-08; BR-REP-043/044).

- Plantillas de WhatsApp: las administra Administracion; cinco iniciales,
  todas operativas (avisos sobre la Orden). El texto usa variables de la
  Orden entre llaves, de una lista cerrada (``VARIABLES``).
- Cada envio asistido es un intento: el mensaje preparado (revisado y quiza
  editado por el usuario), la plantilla, el destinatario, el canal, quien y
  cuando se abrio WhatsApp. Abrir WhatsApp no es enviar.
- La confirmacion manual dice si el usuario envio el mensaje o no. Nunca se
  registra «entregado» ni «leido»: no hay un proveedor que lo pruebe.
- Consentimiento: historial por cliente, finalidad y canal. Lo comercial
  (marketing) exige un consentimiento expreso vigente; lo operativo se envia
  salvo que el cliente lo haya rechazado para ese canal (su preferencia).
  Revocar es registrar un consentimiento no otorgado: nada se borra.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FinalidadComunicacion(str, Enum):
    OPERATIVA = "OPERATIVA"
    COMERCIAL = "COMERCIAL"


class CanalMensaje(str, Enum):
    WHATSAPP = "WHATSAPP"


#: Variables que una plantilla puede usar, con su descripcion.
VARIABLES = {
    "cliente": "Nombre y apellido del cliente",
    "orden": "Número de la Orden",
    "equipo": "Marca, modelo y variante del equipo",
    "total": "Total de la Orden",
    "saldo": "Saldo pendiente",
    "empresa": "Nombre de la empresa",
    "garantia_hasta": "Vencimiento de la garantía más larga",
}


class PlantillaMensaje(BaseModel):
    codigo: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]*$")
    nombre: str = Field(min_length=1)
    finalidad: FinalidadComunicacion = FinalidadComunicacion.OPERATIVA
    texto: str = Field(min_length=1)
    activa: bool = True


PLANTILLAS_INICIALES = (
    PlantillaMensaje(
        codigo="INGRESO",
        nombre="Ingreso de equipo",
        texto=(
            "Hola {cliente}! Recibimos tu {equipo} con la orden {orden}. "
            "Te avisamos por este medio cuando haya novedades. {empresa}"
        ),
    ),
    PlantillaMensaje(
        codigo="AUTORIZACION_PENDIENTE",
        nombre="Autorización pendiente",
        texto=(
            "Hola {cliente}! Para seguir con la orden {orden} ({equipo}) "
            "necesitamos tu autorización. Total: {total}. {empresa}"
        ),
    ),
    PlantillaMensaje(
        codigo="LISTO_PARA_RETIRAR",
        nombre="Equipo listo para retirar",
        texto=(
            "Hola {cliente}! Tu {equipo} (orden {orden}) está listo para "
            "retirar. Saldo pendiente: {saldo}. {empresa}"
        ),
    ),
    PlantillaMensaje(
        codigo="RECORDATORIO_RETIRO",
        nombre="Recordatorio de retiro",
        texto=(
            "Hola {cliente}! Te recordamos que tu {equipo} (orden {orden}) "
            "te espera para retirarlo. Saldo pendiente: {saldo}. {empresa}"
        ),
    ),
    PlantillaMensaje(
        codigo="GARANTIA",
        nombre="Garantía",
        texto=(
            "Hola {cliente}! La reparación de tu {equipo} (orden {orden}) "
            "tiene garantía hasta el {garantia_hasta}. {empresa}"
        ),
    ),
)


class ConfirmacionEnvio(BaseModel):
    """Lo que el usuario confirma a mano: si lo envio o no."""

    enviado: bool
    usuario_id: str
    fecha: datetime
    nota: str | None = None


class ComunicacionCliente(BaseModel):
    """Un intento de envio asistido (DEC-MI-08). Solo crece: la confirmacion
    se agrega una vez y no cambia."""

    id: str
    plantilla_codigo: str | None = None
    finalidad: FinalidadComunicacion = FinalidadComunicacion.OPERATIVA
    canal: CanalMensaje = CanalMensaje.WHATSAPP
    destinatario: str | None = None
    mensaje: str = Field(min_length=1)
    usuario_id: str
    fecha: datetime
    confirmacion: ConfirmacionEnvio | None = None


class ConsentimientoComunicacion(BaseModel):
    """Un registro del historial de consentimiento de un cliente."""

    cliente_id: str
    finalidad: FinalidadComunicacion
    canal: CanalMensaje = CanalMensaje.WHATSAPP
    otorgado: bool
    origen: str = Field(min_length=1)
    usuario_id: str
    fecha: datetime
