"""Fotografias del equipo: reglas (MVP v2, UAT-010).

Cualquier usuario operativo (Recepcion, Taller, Coordinacion o
Administracion) puede agregar fotos a una Orden abierta y todos pueden
verlas. Son opcionales. Se aceptan JPEG, PNG y WebP, identificados por su
contenido (no por el nombre ni por lo que declara el navegador), con un
tope por foto y por Orden. La Orden guarda los datos de cada foto; la
imagen va al almacenamiento de objetos (``app.storage.fotos``).
"""

from datetime import datetime

from app.domain.models import (
    FotoOrden,
    OrdenReparacion,
    RolUsuario,
    Usuario,
)

from .autorizacion import validar_alguno_de
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError

ROLES_FOTOS = (
    RolUsuario.RECEPCION,
    RolUsuario.TECNICO,
    RolUsuario.COORDINADOR_RMA,
    RolUsuario.ADMINISTRADOR,
)
# El navegador reduce cada foto antes de subirla (unos cientos de KB): el
# tope solo frena un archivo enorme o equivocado.
MAX_BYTES_FOTO = 8 * 1024 * 1024
MAX_FOTOS_POR_ORDEN = 10

_EXTENSION = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def tipo_de_imagen(contenido: bytes) -> str | None:
    """El tipo real de la imagen por su firma, o ``None`` si no es una."""
    if contenido.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contenido.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "image/webp"
    return None


def exigir_foto_agregable(orden: OrdenReparacion, *, usuario: Usuario) -> None:
    """Quien puede agregar fotos y si la Orden admite otra."""
    validar_alguno_de(usuario, ROLES_FOTOS)
    if len(orden.fotos) >= MAX_FOTOS_POR_ORDEN:
        raise PrecondicionInvalidaError(
            f"La Orden ya tiene {MAX_FOTOS_POR_ORDEN} fotos, el maximo."
        )


def validar_imagen(contenido: bytes) -> str:
    """Devuelve el tipo de la imagen o rechaza lo que no sirve."""
    if not contenido:
        raise PrecondicionInvalidaError("La foto esta vacia.")
    if len(contenido) > MAX_BYTES_FOTO:
        raise PrecondicionInvalidaError(
            "La foto supera los 8 MB: reducila o elegi otra."
        )
    tipo = tipo_de_imagen(contenido)
    if tipo is None:
        raise PrecondicionInvalidaError(
            "El archivo no es una imagen JPEG, PNG ni WebP."
        )
    return tipo


def clave_de_foto(orden_id: str, foto_id: str, tipo: str) -> str:
    """Donde se guarda la imagen en el almacenamiento de objetos."""
    return f"ordenes/{orden_id}/{foto_id}.{_EXTENSION[tipo]}"


def registrar_foto(
    orden: OrdenReparacion,
    *,
    foto_id: str,
    objeto: str,
    tipo: str,
    tamano: int,
    usuario: Usuario,
    fecha: datetime,
    nombre_original: str | None = None,
) -> OrdenReparacion:
    """Agrega los datos de una foto ya guardada (quien y cuando)."""
    exigir_foto_agregable(orden, usuario=usuario)
    nueva_orden = orden.model_copy(deep=True)
    nueva_orden.fotos.append(
        FotoOrden(
            id=foto_id,
            objeto=objeto,
            tipo_contenido=tipo,
            tamano_bytes=tamano,
            usuario_id=usuario.id,
            fecha=fecha,
            nombre_original=(nombre_original or "").strip()[:120] or None,
        )
    )
    nueva_orden.updated_at = fecha
    return nueva_orden


def fotos_referenciadas(ordenes) -> set[str]:
    """Las claves que alguna Orden usa: las demas son huerfanas."""
    return {foto.objeto for orden in ordenes for foto in orden.fotos}


def buscar_foto(orden: OrdenReparacion, foto_id: str) -> FotoOrden:
    for foto in orden.fotos:
        if foto.id == foto_id:
            return foto
    raise EntidadNoEncontradaError(
        f"La Orden {orden.id} no tiene la foto {foto_id}."
    )
