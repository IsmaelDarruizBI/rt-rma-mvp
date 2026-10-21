"""Mantenimiento (UAT-011).

    POST /api/maintenance/photos/cleanup?usuario_id=...&aplicar=false

Revisa el almacenamiento de fotos contra las Ordenes y, con
``aplicar=true``, borra las imagenes que ninguna Orden usa (por ejemplo,
las de un despliegue anterior del UAT, cuyas Ordenes en JSON se borraron).
Solo Administracion. Nunca toca una foto usada ni una recien subida.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.application import limpiar_fotos_huerfanas

from .dependencias import ContextoDep

router = APIRouter(prefix="/api/maintenance", tags=["mantenimiento"])


class LimpiezaFotosOut(BaseModel):
    aplicada: bool
    revisadas: int
    referenciadas: int
    huerfanas: list[str]
    eliminadas: list[str]
    recientes_conservadas: list[str]


@router.post("/photos/cleanup")
def post_limpiar_fotos(
    usuario_id: str,
    contexto: ContextoDep,
    aplicar: bool = False,
) -> LimpiezaFotosOut:
    """Imagenes huerfanas (sin aplicar, solo informa)."""
    resultado = limpiar_fotos_huerfanas(
        contexto, usuario_id=usuario_id, aplicar=aplicar
    )
    return LimpiezaFotosOut(
        aplicada=resultado.aplicada,
        revisadas=resultado.revisadas,
        referenciadas=resultado.referenciadas,
        huerfanas=list(resultado.huerfanas),
        eliminadas=list(resultado.eliminadas),
        recientes_conservadas=list(resultado.recientes_conservadas),
    )
