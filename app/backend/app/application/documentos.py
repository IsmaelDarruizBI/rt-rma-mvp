"""Documentos de la Orden: emision, consulta y vista previa.

    emitir_comprobante_recepcion      nueva version a pedido (Recepcion)
    emitir_comprobante_autorizacion   los trabajos autorizados, a pedido
                                      (Recepcion); version nueva solo si
                                      cambio lo autorizado
    documentos_de_orden               emitidos y que se puede previsualizar
    documento_de_orden                un documento emitido, tal cual se
                                      entrego
    pdf_documento_de_orden            el PDF de un documento emitido
    vista_previa_documento            contenido con datos vigentes, sin
                                      emitir

Los documentos que emite el proceso se agregan dentro de los comandos que
los disparan, en la misma operacion: el comprobante de recepcion tras
PROC-REP-060 (``emitir_comprobante_recepcion_inicial``) y el comprobante
final y la garantia en la entrega o la devolucion del equipo
(``emitir_documentos_de_salida``).

Las consultas leen tambien una Orden cerrada: un documento emitido se
puede volver a ver e imprimir siempre, sin modificar la Orden.
"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.models import (
    DocumentoEmitido,
    OrdenReparacion,
    TipoDocumento,
    TrabajoEnDocumento,
)
from app.repositories import EntidadPersistidaNoEncontradaError
from app.services import (
    ContextoDocumentos,
    PrecondicionInvalidaError,
    contenido_comprobante_autorizacion,
    contenido_comprobante_entrega,
    contenido_comprobante_recepcion,
    contenido_de,
    contenido_garantia,
    documento_emitido,
    documentos_previsualizables,
    registrar_documento,
    ultimo_documento,
)
from app.services import (
    emitir_comprobante_autorizacion as emitir_comprobante_autorizacion_srv,
)
from app.services import (
    emitir_comprobante_recepcion as emitir_comprobante_recepcion_servicio,
)

from .consultas import nombres_de_tipo_por_detalle
from .contexto import ApplicationContext
from .documentos_pdf import pdf_de_documento
from .modificacion import orden_para_modificar


@dataclass(frozen=True)
class DocumentosDeOrden:
    """Documentos de una Orden para consulta."""

    orden: OrdenReparacion
    emitidos: list[DocumentoEmitido]
    previsualizables: list[TipoDocumento]


def _detalles_reclamados(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
) -> list[TrabajoEnDocumento]:
    """Detalles de la Orden original que reclama una garantia RMA.

    Se leen de la Orden origen (que nunca se modifica), con el nombre de
    su Tipo. Si ya no se encuentran, figura el ID.
    """
    if orden.orden_origen_id is None or not orden.detalles_origen_ids:
        return []
    try:
        origen = contexto.ordenes.obtener(orden.orden_origen_id)
    except EntidadPersistidaNoEncontradaError:
        origen = None
    detalles = {
        detalle.id: detalle
        for detalle in (origen.reparaciones_detail if origen else [])
    }
    nombres = nombres_de_tipo_por_detalle(contexto, origen) if origen else {}
    reclamados = []
    for detalle_id in orden.detalles_origen_ids:
        detalle = detalles.get(detalle_id)
        reclamados.append(
            TrabajoEnDocumento(
                detalle_id=detalle_id,
                tipo_reparacion_id=(
                    detalle.tipo_reparacion_id if detalle else detalle_id
                ),
                nombre=nombres.get(detalle_id, detalle_id),
            )
        )
    return reclamados


def contexto_documentos(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
) -> ContextoDocumentos:
    """Datos de catalogo que se copian al documento al emitirlo."""
    catalogos = contexto.catalogos
    return ContextoDocumentos(
        empresa=catalogos.obtener_datos_empresa(),
        usuarios={
            usuario.id: usuario.nombre
            for usuario in catalogos.listar_usuarios()
        },
        tipos={
            tipo.id: tipo.nombre
            for tipo in catalogos.listar_tipos_reparacion()
        },
        medios={
            medio.id: medio.nombre for medio in catalogos.listar_medios_pago()
        },
        detalles_reclamados=_detalles_reclamados(contexto, orden),
        zona_horaria=contexto.zona_horaria,
    )


# --- Emision dentro de los comandos del proceso ------------------------------


def emitir_comprobante_recepcion_inicial(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
    *,
    usuario_id: str,
    fecha: datetime,
) -> OrdenReparacion:
    """Tras PROC-REP-060: emite la version 1 si todavia no hay ninguna.

    Sin la marca del nodo (el Origen no lo exige) no emite nada.
    """
    if not orden.documentos.comprobante_recepcion.generado:
        return orden
    if ultimo_documento(orden, TipoDocumento.COMPROBANTE_RECEPCION):
        return orden
    orden, _, _ = registrar_documento(
        orden,
        contenido=contenido_comprobante_recepcion(
            orden, contexto_documentos(contexto, orden)
        ),
        fecha=fecha,
        usuario_id=usuario_id,
    )
    return orden


def emitir_documentos_de_salida(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
    *,
    usuario_id: str,
    fecha: datetime,
) -> OrdenReparacion:
    """Comprobante final y, si hubo trabajos realizados, la garantia.

    Se emiten con la salida del equipo ya registrada (entrega o devolucion
    sin reparar), en la misma operacion: la garantia empieza con esa
    entrega. La garantia se emite solo si PROC-REP-280 la genero.
    """
    datos = contexto_documentos(contexto, orden)
    orden, _, _ = registrar_documento(
        orden,
        contenido=contenido_comprobante_entrega(orden, datos),
        fecha=fecha,
        usuario_id=usuario_id,
    )
    if orden.documentos.garantia_reparacion.generado and orden.entrega:
        orden, _, _ = registrar_documento(
            orden,
            contenido=contenido_garantia(orden, datos),
            fecha=fecha,
            usuario_id=usuario_id,
        )
    return orden


# --- Comando -----------------------------------------------------------------


def emitir_comprobante_recepcion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    motivo: str | None = None,
) -> OrdenReparacion:
    """Recepcion emite una version nueva del comprobante de recepcion.

    Exige motivo si ya habia una version; un reintento con el mismo
    contenido devuelve la vigente sin duplicarla.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden, _ = emitir_comprobante_recepcion_servicio(
            orden,
            usuario=usuario,
            contenido=contenido_comprobante_recepcion(
                orden, contexto_documentos(contexto, orden)
            ),
            fecha=fecha,
            motivo=motivo,
        )
        contexto.ordenes.guardar(orden)
    return orden


def emitir_comprobante_autorizacion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
) -> OrdenReparacion:
    """Recepcion emite el comprobante de los trabajos autorizados.

    Solo cuando lo pide (el boton): el proceso nunca lo emite. Si lo
    autorizado no cambio desde la ultima version, no se crea otra; si
    cambio, la version nueva lleva el motivo calculado y la anterior se
    conserva.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden, _, creado = emitir_comprobante_autorizacion_srv(
            orden,
            usuario=usuario,
            contenido=contenido_comprobante_autorizacion(
                orden, contexto_documentos(contexto, orden)
            ),
            fecha=fecha,
        )
        if creado:
            contexto.ordenes.guardar(orden)
    return orden


# --- Consultas ---------------------------------------------------------------


def documentos_de_orden(
    contexto: ApplicationContext,
    orden_id: str,
) -> DocumentosDeOrden:
    """Documentos emitidos de la Orden (abierta o cerrada)."""
    orden = contexto.ordenes.obtener(orden_id)
    return DocumentosDeOrden(
        orden=orden,
        emitidos=list(orden.documentos.emitidos),
        previsualizables=documentos_previsualizables(orden),
    )


def documento_de_orden(
    contexto: ApplicationContext,
    orden_id: str,
    documento_id: str,
) -> DocumentoEmitido:
    """Un documento emitido, tal como se entrego."""
    return documento_emitido(contexto.ordenes.obtener(orden_id), documento_id)


def pdf_documento_de_orden(
    contexto: ApplicationContext,
    orden_id: str,
    documento_id: str,
) -> tuple[str, bytes]:
    """Nombre de archivo y PDF de un documento emitido (solo lectura).

    Se arma desde el snapshot: no modifica la Orden ni deja nada en su
    historial (descargar o compartir no prueba que el cliente lo recibio).
    """
    documento = documento_emitido(
        contexto.ordenes.obtener(orden_id), documento_id
    )
    return pdf_de_documento(documento, zona_horaria=contexto.zona_horaria)


def vista_previa_documento(
    contexto: ApplicationContext,
    orden_id: str,
    tipo: TipoDocumento,
):
    """Contenido de un documento con los datos vigentes, sin emitirlo."""
    orden = contexto.ordenes.obtener(orden_id)
    if tipo not in documentos_previsualizables(orden):
        raise PrecondicionInvalidaError(
            f"La Orden {orden.id} no tiene vista previa de {tipo.value} en "
            "su estado actual."
        )
    return contenido_de(orden, tipo, contexto_documentos(contexto, orden))
