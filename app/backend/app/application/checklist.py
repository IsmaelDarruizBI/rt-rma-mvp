"""Checklist de recepcion por tipo de equipo y advertencia por informacion
faltante (DC12). El catalogo lo administra Administracion sobre PostgreSQL
(DC23); en JSON esta vacio y no se edita."""

from collections.abc import Sequence

from app.domain.models import OrdenReparacion
from app.domain.models.checklist import PreguntaChecklist, TipoEquipo
from app.services import EntidadNoEncontradaError
from app.services.checklist import (
    cambios_de_pregunta,
    cambios_de_tipo_equipo,
    confirmar_informacion_faltante,
    registrar_checklist,
)

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar
from .operativa import _editable


def catalogo(contexto: ApplicationContext, *, solo_vigentes: bool) -> dict:
    with contexto.lectura():
        tipos = contexto.operativa.listar_tipos_equipo()
        preguntas = contexto.operativa.listar_preguntas_checklist()
    if solo_vigentes:
        tipos = [t for t in tipos if t.activo]
        vigentes = {t.id for t in tipos}
        preguntas = [
            p for p in preguntas if p.activa and p.tipo_equipo_id in vigentes
        ]
    return {
        "editable": contexto.operativa.editable,
        "tipos": tipos,
        "preguntas": preguntas,
    }


def _siguiente(existentes: Sequence[str], prefijo: str) -> str:
    numeros = [
        int(codigo.split("-")[-1])
        for codigo in existentes
        if codigo.split("-")[-1].isdigit()
    ]
    return f"{prefijo}-{max(numeros, default=0) + 1:04d}"


def guardar_tipo_equipo(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    codigo: str | None,
    nombre: str,
    activo: bool,
) -> TipoEquipo:
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    with contexto.transaccion():
        existentes = {t.id: t for t in repositorio.listar_tipos_equipo()}
        nuevo = codigo is None
        codigo = codigo or _siguiente(list(existentes), "TEQ")
        anterior = existentes.get(codigo)
        if not nuevo and anterior is None:
            raise EntidadNoEncontradaError(
                f"No existe el tipo de equipo {codigo}"
            )
        tipo = TipoEquipo(id=codigo, nombre=nombre.strip(), activo=activo)
        cambios = cambios_de_tipo_equipo(
            anterior, tipo, usuario=usuario, fecha=contexto.ahora()
        )
        repositorio.guardar_tipo_equipo(tipo, nuevo=nuevo, cambios=cambios)
    return tipo


def guardar_pregunta(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    codigo: str | None,
    tipo_equipo_id: str,
    texto: str,
    opciones: Sequence[str],
    activa: bool,
    orden: int,
) -> PreguntaChecklist:
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    with contexto.transaccion():
        tipos = {t.id for t in repositorio.listar_tipos_equipo()}
        if tipo_equipo_id not in tipos:
            raise EntidadNoEncontradaError(
                f"No existe el tipo de equipo {tipo_equipo_id}"
            )
        existentes = {
            p.id: p for p in repositorio.listar_preguntas_checklist()
        }
        nuevo = codigo is None
        codigo = codigo or _siguiente(list(existentes), "CHK")
        anterior = existentes.get(codigo)
        if not nuevo and anterior is None:
            raise EntidadNoEncontradaError(f"No existe la pregunta {codigo}")
        pregunta = PreguntaChecklist(
            id=codigo,
            tipo_equipo_id=tipo_equipo_id,
            texto=texto.strip(),
            opciones=list(opciones),
            activa=activa,
            orden=orden,
        )
        cambios = cambios_de_pregunta(
            anterior, pregunta, usuario=usuario, fecha=contexto.ahora()
        )
        repositorio.guardar_pregunta_checklist(
            pregunta, nuevo=nuevo, cambios=cambios
        )
    return pregunta


def registrar_checklist_de_orden(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    tipo_equipo_id: str,
    respuestas: Sequence[tuple[str, str | None, bool]],
    motivo: str | None,
) -> OrdenReparacion:
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with orden_para_modificar(contexto, orden_id) as orden:
        tipos = {t.id: t for t in contexto.operativa.listar_tipos_equipo()}
        if tipo_equipo_id not in tipos:
            raise EntidadNoEncontradaError(
                f"No existe el tipo de equipo {tipo_equipo_id}"
            )
        orden = registrar_checklist(
            orden,
            tipo=tipos[tipo_equipo_id],
            preguntas=contexto.operativa.listar_preguntas_checklist(),
            respuestas=respuestas,
            motivo=motivo,
            usuario=usuario,
            fecha=fecha,
        )
        contexto.ordenes.guardar(orden)
    return orden


def confirmar_faltantes(
    contexto: ApplicationContext, *, orden_id: str, usuario_id: str
) -> OrdenReparacion:
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with orden_para_modificar(contexto, orden_id) as orden:
        orden = confirmar_informacion_faltante(
            orden, usuario=usuario, fecha=fecha
        )
        contexto.ordenes.guardar(orden)
    return orden
