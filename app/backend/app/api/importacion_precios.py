"""Importacion masiva de precios por modelo (DEC-AJ-13, BF-02).

    GET  /api/admin/model-prices/template?formato=xlsx|csv
                                     plantilla con los precios vigentes
    POST /api/admin/model-prices/import/preview?usuario_id=&nombre=
                                     vista previa, sin escribir nada
    POST /api/admin/model-prices/import?usuario_id=&nombre=
                                     aplica todo o nada (PostgreSQL)

Con el permiso «Gestionar precios» (PRECIOS_GESTIONAR). El cuerpo de los
POST es la planilla tal cual, sin multipart (como las fotos y las firmas):
un ``.xlsx``, un CSV (``text/csv``) o las celdas pegadas
(``text/tab-separated-values`` o ``text/plain``). ``nombre`` es el nombre
del archivo, solo para la auditoria. Aplicar vuelve a leer y validar la
planilla en el servidor. Acepta la clave de idempotencia (E6): un
reintento con la misma clave y el mismo contenido devuelve lo ya
confirmado.
"""

import hashlib
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.application.importacion_precios import (
    aplicar_importacion,
    plantilla_precios,
    previsualizar_importacion,
)
from app.domain.models import FormatoImportacion
from app.integraciones.planillas import MAX_BYTES
from app.services import PrecondicionInvalidaError, permisos

from .dependencias import ContextoDep
from .idempotencia import ClaveDep, con_clave
from .seguridad import exigir_rol

router = APIRouter(prefix="/api/admin/model-prices", tags=["administracion"])

_precios = [exigir_rol(permisos.PRECIOS_GESTIONAR)]


@router.get("/template", dependencies=_precios)
def get_plantilla(
    contexto: ContextoDep, formato: Literal["xlsx", "csv"] = "xlsx"
) -> Response:
    """La plantilla con los Tipos con precio por modelo en las columnas, los
    modelos Apple vigentes en las filas y los precios vigentes."""
    archivo = plantilla_precios(
        contexto,
        formato=(
            FormatoImportacion.XLSX
            if formato == "xlsx"
            else FormatoImportacion.CSV
        ),
    )
    return Response(
        archivo.contenido,
        media_type=archivo.tipo,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{archivo.nombre}"'
            ),
            "Cache-Control": "no-store",
        },
    )


async def _planilla(request: Request) -> tuple[bytes, str | None]:
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > MAX_BYTES:
        raise PrecondicionInvalidaError(
            f"El archivo supera los {MAX_BYTES // (1024 * 1024)} MB."
        )
    contenido = await request.body()
    return contenido, request.headers.get("content-type")


@router.post("/import/preview", dependencies=_precios)
async def post_vista_previa(
    usuario_id: str,
    request: Request,
    contexto: ContextoDep,
    nombre: str | None = None,
) -> dict:
    """D-13.3: cambios propuestos (nuevos y actualizaciones), errores con
    su celda y avisos. ``editable`` es falso en el modo JSON: ahi no se
    puede aplicar."""
    contenido, tipo = await _planilla(request)
    vista = await run_in_threadpool(
        previsualizar_importacion,
        contexto,
        usuario_id=usuario_id,
        contenido=contenido,
        tipo_contenido=tipo,
        nombre_archivo=nombre,
    )
    return {
        **vista.model_dump(mode="json"),
        "editable": contexto.configuracion is not None,
    }


@router.post("/import", dependencies=_precios)
async def post_importar(
    usuario_id: str,
    request: Request,
    contexto: ContextoDep,
    nombre: str | None = None,
    clave_idempotencia: ClaveDep = None,
):
    """Aplica la importacion: todo o nada, con la auditoria agrupada por
    importacion. Devuelve la importacion registrada y la vista con la que
    se aplico."""
    contenido, tipo = await _planilla(request)

    def aplicar() -> dict:
        resultado = aplicar_importacion(
            contexto,
            usuario_id=usuario_id,
            contenido=contenido,
            tipo_contenido=tipo,
            nombre_archivo=nombre,
        )
        return resultado.model_dump(mode="json")

    return await run_in_threadpool(
        con_clave,
        contexto,
        clave_idempotencia,
        operacion="IMPORTAR_PRECIOS_MODELO",
        usuario_id=usuario_id,
        parametros={
            "usuario_id": usuario_id,
            "nombre": nombre,
            "tipo": tipo,
            "contenido": hashlib.sha256(contenido).hexdigest(),
        },
        ejecutar=aplicar,
    )
