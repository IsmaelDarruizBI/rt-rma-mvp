"""Catalogo tecnico de modelos de equipo (propio de RMA).

    GET /api/catalogs/device-models   los modelos que se ofrecen en el
                                      alta y la correccion del equipo

Solo lectura: la busqueda la hace la pantalla (el catalogo es chico).
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.application import modelos_para_seleccion
from app.domain.models import ModeloEquipo

from .dependencias import ContextoDep

router = APIRouter(prefix="/api/catalogs/device-models", tags=["catalogos"])


class ModeloEquipoOut(BaseModel):
    id: str
    marca: str
    modelo: str
    # ``None``: la version estandar del modelo.
    variante: str | None = None
    # Identificadores del fabricante (``A2849``); vacio si no se conocen.
    numeros_modelo: list[str]
    nombre: str

    @classmethod
    def desde_dominio(cls, modelo: ModeloEquipo) -> "ModeloEquipoOut":
        return cls(
            id=modelo.id,
            marca=modelo.marca,
            modelo=modelo.modelo,
            variante=modelo.variante,
            numeros_modelo=list(modelo.numeros_modelo),
            nombre=modelo.nombre,
        )


@router.get("")
def get_modelos_equipo(contexto: ContextoDep) -> list[ModeloEquipoOut]:
    """Los modelos activos, en el orden del catalogo."""
    return [
        ModeloEquipoOut.desde_dominio(modelo)
        for modelo in modelos_para_seleccion(contexto)
    ]
