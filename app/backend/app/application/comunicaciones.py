"""Comunicaciones asistidas por WhatsApp y consentimiento (DEC-MI-08).

Preparar un mensaje solo lee. Registrar el intento (al abrir WhatsApp) y
confirmar el envio a mano modifican la Orden. El consentimiento es un
historial por cliente. Las plantillas las administra Administracion sobre
PostgreSQL, con auditoria; en JSON rigen las cinco iniciales.
"""

from dataclasses import dataclass

from app.domain.models import OrdenReparacion
from app.domain.models.comunicaciones import (
    VARIABLES,
    CanalMensaje,
    ConsentimientoComunicacion,
    FinalidadComunicacion,
    PlantillaMensaje,
)
from app.services.comunicaciones import (
    cambios_de_plantilla,
    confirmar_envio,
    consentimiento_vigente,
    impedimento_de_consentimiento,
    nuevo_consentimiento,
    preparar_mensaje,
    registrar_intento,
    variables_de_la_orden,
)
from app.services.exceptions import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
)

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar
from .operativa import _editable


@dataclass(frozen=True)
class MensajePreparado:
    plantilla: PlantillaMensaje
    mensaje: str
    faltantes: list[str]
    destinatario: str | None
    impedimento: str | None


def listar_plantillas(contexto: ApplicationContext) -> list[PlantillaMensaje]:
    with contexto.lectura():
        return contexto.operativa.listar_plantillas()


def variables_disponibles() -> dict[str, str]:
    return dict(VARIABLES)


def _plantilla(contexto: ApplicationContext, codigo: str) -> PlantillaMensaje:
    for plantilla in listar_plantillas(contexto):
        if plantilla.codigo == codigo:
            return plantilla
    raise EntidadNoEncontradaError(f"No existe la plantilla {codigo}")


def _historial(
    contexto: ApplicationContext, cliente_id: str
) -> list[ConsentimientoComunicacion]:
    if contexto.consentimientos is None:
        return []
    return contexto.consentimientos.listar(cliente_id)


def preparar(
    contexto: ApplicationContext, *, orden_id: str, plantilla_codigo: str
) -> MensajePreparado:
    plantilla = _plantilla(contexto, plantilla_codigo)
    with contexto.lectura():
        orden = contexto.ordenes.obtener(orden_id)
        empresa = contexto.catalogos.obtener_datos_empresa().nombre
        historial = (
            _historial(contexto, orden.cliente.id) if orden.cliente else []
        )
    mensaje, faltantes = preparar_mensaje(
        plantilla,
        variables_de_la_orden(
            orden, empresa=empresa, zona_horaria=contexto.zona_horaria
        ),
    )
    impedimento = (
        "La Orden no tiene un cliente externo a quien escribir."
        if orden.cliente is None
        else impedimento_de_consentimiento(
            historial, plantilla.finalidad, CanalMensaje.WHATSAPP
        )
    )
    if not plantilla.activa:
        impedimento = f"La plantilla «{plantilla.nombre}» no esta vigente."
    return MensajePreparado(
        plantilla=plantilla,
        mensaje=mensaje,
        faltantes=faltantes,
        destinatario=orden.cliente.telefono if orden.cliente else None,
        impedimento=impedimento,
    )


def registrar_comunicacion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    plantilla_codigo: str | None,
    mensaje: str,
    destinatario: str | None,
) -> OrdenReparacion:
    plantilla = (
        _plantilla(contexto, plantilla_codigo) if plantilla_codigo else None
    )
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with orden_para_modificar(contexto, orden_id) as orden:
        historial = (
            _historial(contexto, orden.cliente.id) if orden.cliente else []
        )
        orden = registrar_intento(
            orden,
            plantilla=plantilla,
            mensaje=mensaje,
            destinatario=destinatario,
            historial=historial,
            usuario=usuario,
            fecha=fecha,
        )
        contexto.ordenes.guardar(orden)
    return orden


def confirmar_comunicacion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    comunicacion_id: str,
    usuario_id: str,
    enviado: bool,
    nota: str | None,
) -> OrdenReparacion:
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with orden_para_modificar(contexto, orden_id) as orden:
        orden = confirmar_envio(
            orden,
            comunicacion_id,
            enviado=enviado,
            nota=nota,
            usuario=usuario,
            fecha=fecha,
        )
        contexto.ordenes.guardar(orden)
    return orden


@dataclass(frozen=True)
class EstadoConsentimiento:
    historial: list[ConsentimientoComunicacion]
    vigentes: dict[str, bool | None]


def consentimientos(
    contexto: ApplicationContext, cliente_id: str
) -> EstadoConsentimiento:
    with contexto.lectura():
        historial = _historial(contexto, cliente_id)
    vigentes = {}
    for finalidad in FinalidadComunicacion:
        vigente = consentimiento_vigente(
            historial, finalidad, CanalMensaje.WHATSAPP
        )
        vigentes[finalidad.value] = vigente.otorgado if vigente else None
    return EstadoConsentimiento(
        historial=sorted(historial, key=lambda r: r.fecha, reverse=True),
        vigentes=vigentes,
    )


def registrar_consentimiento(
    contexto: ApplicationContext,
    *,
    cliente_id: str,
    usuario_id: str,
    finalidad: FinalidadComunicacion,
    otorgado: bool,
    origen: str,
    canal: CanalMensaje = CanalMensaje.WHATSAPP,
) -> EstadoConsentimiento:
    if contexto.consentimientos is None:
        raise PrecondicionInvalidaError(
            "Esta persistencia no registra consentimientos."
        )
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    registro = nuevo_consentimiento(
        cliente_id=cliente_id,
        finalidad=finalidad,
        canal=canal,
        otorgado=otorgado,
        origen=origen,
        usuario=usuario,
        fecha=contexto.ahora(),
    )
    with contexto.transaccion():
        contexto.consentimientos.agregar(registro)
    return consentimientos(contexto, cliente_id)


def guardar_plantilla(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    plantilla: PlantillaMensaje,
    nuevo: bool,
) -> PlantillaMensaje:
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with contexto.transaccion():
        existentes = {p.codigo: p for p in repositorio.listar_plantillas()}
        anterior = existentes.get(plantilla.codigo)
        if nuevo and anterior is not None:
            raise PrecondicionInvalidaError(
                f"Ya existe la plantilla {plantilla.codigo}."
            )
        if not nuevo and anterior is None:
            raise EntidadNoEncontradaError(
                f"No existe la plantilla {plantilla.codigo}"
            )
        cambios = cambios_de_plantilla(
            anterior, plantilla, usuario=usuario, fecha=fecha
        )
        repositorio.guardar_plantilla(plantilla, nuevo=nuevo, cambios=cambios)
    return plantilla
