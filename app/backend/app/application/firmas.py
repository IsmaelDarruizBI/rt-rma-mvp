"""Firma opcional de los documentos emitidos (DEC-MI-06).

Registrar: la imagen (firma en pantalla o foto del papel firmado) va al
almacenamiento privado de las fotos, bajo ``firmas/``, y sus datos al
repositorio de firmas. No modifica la Orden: vale tambien con la Orden
cerrada (el comprobante de entrega se firma al entregar). Ningun documento
la exige.
"""

from app.domain.models.firmas import FirmaDocumento, FormaFirma
from app.services import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    nuevo_id,
    permisos,
    validar_alguno_de,
    validar_imagen,
)

from .contexto import ApplicationContext
from .fotos import _almacen

_EXTENSION = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _repositorio(contexto: ApplicationContext):
    if contexto.firmas is None:
        raise PrecondicionInvalidaError(
            "Esta persistencia no registra firmas."
        )
    return contexto.firmas


def firmas_de_la_orden(
    contexto: ApplicationContext, orden_id: str
) -> list[FirmaDocumento]:
    if contexto.firmas is None:
        return []
    with contexto.lectura():
        return contexto.firmas.de_la_orden(orden_id)


def registrar_firma(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    documento_id: str,
    usuario_id: str,
    forma: FormaFirma,
    contenido: bytes,
    firmante: str | None = None,
) -> list[FirmaDocumento]:
    repositorio = _repositorio(contexto)
    almacen = _almacen(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, permisos.FIRMA_REGISTRAR)
    tipo = validar_imagen(contenido)
    orden = contexto.ordenes.obtener(orden_id)
    if not any(d.id == documento_id for d in orden.documentos.emitidos):
        raise EntidadNoEncontradaError(
            f"La Orden {orden_id} no tiene el documento {documento_id}"
        )
    firma_id = nuevo_id("FIR")
    objeto = f"firmas/{orden_id}/{firma_id}.{_EXTENSION[tipo]}"
    almacen.guardar(objeto, contenido, tipo)
    firma = FirmaDocumento(
        id=firma_id,
        orden_id=orden_id,
        documento_id=documento_id,
        forma=forma,
        objeto=objeto,
        tipo_contenido=tipo,
        tamano_bytes=len(contenido),
        usuario_id=usuario.id,
        fecha=contexto.ahora(),
        firmante=(firmante or "").strip()[:120] or None,
    )
    with contexto.transaccion():
        repositorio.agregar(firma)
    return firmas_de_la_orden(contexto, orden_id)


def imagen_de_firma(
    contexto: ApplicationContext, *, orden_id: str, firma_id: str
) -> tuple[bytes, str]:
    almacen = _almacen(contexto)
    for firma in firmas_de_la_orden(contexto, orden_id):
        if firma.id == firma_id:
            return almacen.obtener(firma.objeto), firma.tipo_contenido
    raise EntidadNoEncontradaError(f"No existe la firma {firma_id}")
