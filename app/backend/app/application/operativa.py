"""Motivos, parametros y retiro demorado (DEC-MI-13, 14 y 15).

La administracion (alta y edicion de motivos, cambio de parametros) es de
Administracion y sobre PostgreSQL, con auditoria. La consulta de motivos y
el plazo vigente valen en los dos modos (en JSON, los valores iniciales).
"""

from app.domain.models import OrdenReparacion
from app.domain.models.operativa import (
    PARAMETRO_PLAZO_RETIRO,
    PARAMETROS_INICIALES,
    MotivoOperativo,
    TipoMotivo,
)
from app.services.exceptions import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
)
from app.services.operativa import (
    cambio_de_parametro,
    cambios_de_motivo,
    registrar_seguimiento_retiro,
    texto_de_motivo,
)

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar


def _editable(contexto: ApplicationContext):
    if not contexto.operativa.editable:
        raise PrecondicionInvalidaError(
            "La configuracion se administra sobre la base PostgreSQL (DC23); "
            "en el modo JSON es de solo lectura."
        )
    return contexto.operativa


def listar_motivos(
    contexto: ApplicationContext, tipo: TipoMotivo | None = None
) -> list[MotivoOperativo]:
    with contexto.lectura():
        return contexto.operativa.listar_motivos(tipo)


def resolver_motivo(
    contexto: ApplicationContext,
    tipo: TipoMotivo,
    codigo: str | None,
    descripcion: str | None,
) -> str:
    motivos = listar_motivos(contexto, tipo) if codigo else []
    return texto_de_motivo(motivos, tipo, codigo, descripcion)


def guardar_motivo(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    motivo: MotivoOperativo,
    nuevo: bool,
) -> MotivoOperativo:
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with contexto.transaccion():
        existentes = {m.codigo: m for m in repositorio.listar_motivos()}
        anterior = existentes.get(motivo.codigo)
        if nuevo and anterior is not None:
            raise PrecondicionInvalidaError(
                f"Ya existe el motivo {motivo.codigo}."
            )
        if not nuevo and anterior is None:
            raise EntidadNoEncontradaError(
                f"No existe el motivo {motivo.codigo}"
            )
        cambios = cambios_de_motivo(
            anterior, motivo, usuario=usuario, fecha=fecha
        )
        repositorio.guardar_motivo(motivo, nuevo=nuevo, cambios=cambios)
    return motivo


def parametros(contexto: ApplicationContext) -> dict[str, str]:
    with contexto.lectura():
        return {**PARAMETROS_INICIALES, **contexto.operativa.parametros()}


def plazo_retiro_dias(contexto: ApplicationContext) -> int:
    valor = parametros(contexto).get(PARAMETRO_PLAZO_RETIRO, "30")
    return int(valor) if valor.isdigit() else 30


def guardar_parametro(
    contexto: ApplicationContext, *, usuario_id: str, clave: str, valor: str
) -> dict[str, str]:
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with contexto.transaccion():
        actuales = repositorio.parametros()
        if clave not in actuales:
            raise EntidadNoEncontradaError(f"No existe el parametro {clave}")
        cambio = cambio_de_parametro(
            clave, actuales[clave], valor, usuario=usuario, fecha=fecha
        )
        repositorio.guardar_parametro(clave, cambio.valor_nuevo, cambio)
    return parametros(contexto)


def registrar_seguimiento(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    nota: str,
    canal: str | None = None,
) -> OrdenReparacion:
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_seguimiento_retiro(
            orden, usuario=usuario, fecha=fecha, nota=nota, canal=canal
        )
        contexto.ordenes.guardar(orden)
    return orden
