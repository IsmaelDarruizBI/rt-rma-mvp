"""Checklist de recepcion por tipo de equipo y advertencia por informacion
faltante (DC12).

Los Tipos de Equipo son una copia del catalogo de Ventas de Gestion RT:
``sincronizar_tipos_equipo`` los lee con el mismo origen de solo lectura
que la copia de productos (``contexto.proveedor_catalogo``), de la columna
que fija ``RMA_TIPO_EQUIPO_CAMPO``, y los guarda en RMA. Administracion no
los crea ni los edita; configura las preguntas de cada uno (DC23). Todo
sobre PostgreSQL; en JSON el catalogo esta vacio y no se edita."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.models import OrdenReparacion
from app.domain.models.checklist import PreguntaChecklist, TipoEquipo
from app.integraciones.catalogo import CatalogoOrigenInvalidoError
from app.services import EntidadNoEncontradaError, PrecondicionInvalidaError
from app.services.autorizacion import validar_alguno_de
from app.services.checklist import (
    cambios_de_pregunta,
    confirmar_informacion_faltante,
    fusionar_tipos_equipo,
    registrar_checklist,
    tipos_informados,
)
from app.services.permisos import CONFIGURACION_ADMINISTRAR

from .codigos import con_reintento_de_codigo
from .contexto import ApplicationContext
from .modificacion import orden_para_modificar
from .operativa import _editable

DECISION_PENDIENTE = (
    "Falta definir qué dato del catálogo de Ventas es el tipo de equipo "
    "(RMA_TIPO_EQUIPO_CAMPO): es una decisión de negocio pendiente de DC12."
)


def origen_tipos_equipo(
    contexto: ApplicationContext, tipos: Sequence[TipoEquipo]
) -> dict:
    """De donde salen los tipos y cuando se actualizaron por ultima vez."""
    fechas = [t.sincronizado_en for t in tipos if t.sincronizado_en]
    origen = contexto.proveedor_catalogo
    return {
        "campo": contexto.campo_tipo_equipo,
        "definido": contexto.campo_tipo_equipo is not None,
        "origen": origen.descripcion if origen else None,
        "sincronizable": (
            contexto.operativa.editable
            and contexto.campo_tipo_equipo is not None
            and origen is not None
        ),
        "ultima_sincronizacion": max(fechas) if fechas else None,
        "aviso": (None if contexto.campo_tipo_equipo else DECISION_PENDIENTE),
    }


def catalogo(contexto: ApplicationContext, *, solo_vigentes: bool) -> dict:
    with contexto.lectura():
        tipos = contexto.operativa.listar_tipos_equipo()
        preguntas = contexto.operativa.listar_preguntas_checklist()
    origen = origen_tipos_equipo(contexto, tipos)
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
        "origen": origen,
    }


def checklist_disponible(contexto: ApplicationContext) -> bool:
    """Hay al menos un tipo de equipo vigente: se puede completar un
    checklist. En la lectura en curso, si hay una."""
    with contexto.lectura():
        return any(t.activo for t in contexto.operativa.listar_tipos_equipo())


@dataclass(frozen=True)
class ResultadoTiposEquipo:
    campo: str
    origen: str
    fecha: datetime
    vigentes: int
    nuevos: int
    reactivados: int
    dados_de_baja: int
    sin_cambios: int


def sincronizar_tipos_equipo(
    contexto: ApplicationContext, *, usuario_id: str
) -> ResultadoTiposEquipo:
    """Actualiza la copia de los tipos de equipo desde el catalogo de
    Ventas (solo lectura). La lectura es FUERA de la transaccion; si el
    origen falla (``CatalogoOrigenNoDisponibleError``, 503) o responde
    algo no confiable (409), la copia no cambia y las Ordenes siguen
    consultandose con lo que ya tenian."""
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, CONFIGURACION_ADMINISTRAR)
    campo = contexto.campo_tipo_equipo
    if campo is None:
        raise PrecondicionInvalidaError(DECISION_PENDIENTE)
    origen = contexto.proveedor_catalogo
    if origen is None:
        raise PrecondicionInvalidaError(
            "No hay un origen del catálogo de Ventas configurado "
            "(RMA_CATALOGO_ORIGEN): no se pueden actualizar los tipos."
        )
    descripcion = origen.descripcion
    try:
        lectura = origen.leer(contexto.filtro_catalogo)
    except CatalogoOrigenInvalidoError as error:
        raise PrecondicionInvalidaError(str(error)) from error
    informados = tipos_informados(lectura.productos, campo)
    fecha = contexto.ahora()
    with contexto.transaccion():
        fusion = fusionar_tipos_equipo(
            repositorio.listar_tipos_equipo(),
            informados,
            campo=campo,
            usuario=usuario,
            fecha=fecha,
        )
        repositorio.aplicar_tipos_equipo(fusion.tipos, fusion.cambios)
    return ResultadoTiposEquipo(
        campo=campo,
        origen=descripcion,
        fecha=fecha,
        vigentes=len(informados),
        nuevos=fusion.nuevos,
        reactivados=fusion.reactivados,
        dados_de_baja=fusion.dados_de_baja,
        sin_cambios=fusion.sin_cambios,
    )


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
    # El permiso antes de reservar un codigo: un rechazo no consume numeros.
    validar_alguno_de(usuario, CONFIGURACION_ADMINISTRAR)
    codigo_informado = codigo

    def intento():
        codigo = codigo_informado
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
            # CFG-01: el codigo lo genera la base (CHK-NNNN), seguro ante
            # altas concurrentes.
            codigo = codigo or repositorio.reservar_codigo("CHK")
            anterior = existentes.get(codigo)
            if not nuevo and anterior is None:
                raise EntidadNoEncontradaError(
                    f"No existe la pregunta {codigo}"
                )
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

    return con_reintento_de_codigo(intento, generado=codigo_informado is None)


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
        disponible = any(
            t.activo for t in contexto.operativa.listar_tipos_equipo()
        )
        orden = confirmar_informacion_faltante(
            orden,
            usuario=usuario,
            fecha=fecha,
            checklist_disponible=disponible,
        )
        contexto.ordenes.guardar(orden)
    return orden
