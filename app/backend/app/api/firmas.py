"""Firma opcional de los documentos emitidos (DEC-MI-06).

    GET  /api/orders/{id}/signatures                  firmas de la Orden
    POST /api/orders/{id}/documents/{doc}/signatures?usuario_id=&forma=
         el cuerpo es la imagen (firma en pantalla o foto del papel)
    GET  /api/orders/{id}/signatures/{firma}          la imagen

Ningun documento exige firma. Registrarla no modifica la Orden.
"""

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.application.firmas import (
    firmas_de_la_orden,
    imagen_de_firma,
    registrar_firma,
)
from app.domain.models.firmas import FirmaDocumento, FormaFirma
from app.services import ROLES_FOTOS, PrecondicionInvalidaError
from app.services.fotos import MAX_BYTES_FOTO

from .dependencias import ContextoDep
from .seguridad import exigir_rol

router = APIRouter(prefix="/api/orders", tags=["firmas"])
# Las imagenes de las firmas las ven quienes ven las fotos del equipo.
_ver = [exigir_rol(ROLES_FOTOS)]


@router.get("/{orden_id}/signatures", dependencies=_ver)
def get_firmas(orden_id: str, contexto: ContextoDep) -> list[FirmaDocumento]:
    return firmas_de_la_orden(contexto, orden_id)


@router.post("/{orden_id}/documents/{documento_id}/signatures")
async def post_firma(
    orden_id: str,
    documento_id: str,
    usuario_id: str,
    forma: FormaFirma,
    request: Request,
    contexto: ContextoDep,
    firmante: str | None = None,
) -> list[FirmaDocumento]:
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > MAX_BYTES_FOTO:
        raise PrecondicionInvalidaError(
            "La imagen supera los 8 MB: reducila o elegi otra."
        )
    contenido = await request.body()
    return await run_in_threadpool(
        registrar_firma,
        contexto,
        orden_id=orden_id,
        documento_id=documento_id,
        usuario_id=usuario_id,
        forma=forma,
        contenido=contenido,
        firmante=firmante,
    )


@router.get("/{orden_id}/signatures/{firma_id}", dependencies=_ver)
def get_imagen_firma(
    orden_id: str, firma_id: str, contexto: ContextoDep
) -> Response:
    contenido, tipo = imagen_de_firma(
        contexto, orden_id=orden_id, firma_id=firma_id
    )
    return Response(
        content=contenido,
        media_type=tipo,
        headers={"Cache-Control": "private, max-age=3600"},
    )
