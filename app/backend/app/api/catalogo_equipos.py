"""Catalogo de equipos de Gestion de Ventas.

    GET  /api/catalogs/equipment                el arbol del selector del
                                                alta y el estado de la copia
    POST /api/catalogs/equipment/sync?usuario_id=
                                                sincroniza a pedido
                                                (Administracion o
                                                Coordinacion RMA)

El GET lee la copia local: nunca consulta el origen. El POST es el unico
que lo lee, a traves del adaptador configurado.
"""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.application import (
    EstadoCatalogoEquipos,
    catalogo_para_seleccion,
    estado_catalogo_equipos,
    sincronizar_catalogo_equipos,
)
from app.domain.models import ResultadoSincronizacion, SincronizacionCatalogo
from app.services import OpcionModelo

from .dependencias import ContextoDep

router = APIRouter(prefix="/api/catalogs/equipment", tags=["catalogos"])


class SincronizacionOut(BaseModel):
    id: str
    usuario_id: str
    origen: str
    filtro: str
    iniciada_en: datetime
    finalizada_en: datetime
    resultado: ResultadoSincronizacion
    mensaje: str | None = None
    leidos: int
    filtrados: int
    descartados: int
    nuevos: int
    actualizados: int
    sin_cambios: int
    reactivados: int
    dados_de_baja: int
    vigentes: int
    elegibles: int

    @classmethod
    def desde_dominio(
        cls, sincronizacion: SincronizacionCatalogo
    ) -> "SincronizacionOut":
        return cls(**sincronizacion.model_dump())


class EstadoCatalogoOut(BaseModel):
    habilitado: bool
    sincronizable: bool
    origen: str | None
    filtro: str
    ultima: SincronizacionOut | None
    ultima_exitosa: SincronizacionOut | None
    vigentes: int
    elegibles: int

    @classmethod
    def desde_dominio(
        cls, estado: EstadoCatalogoEquipos
    ) -> "EstadoCatalogoOut":
        return cls(
            habilitado=estado.habilitado,
            sincronizable=estado.sincronizable,
            origen=estado.origen,
            filtro=estado.filtro,
            ultima=(
                SincronizacionOut.desde_dominio(estado.ultima)
                if estado.ultima
                else None
            ),
            ultima_exitosa=(
                SincronizacionOut.desde_dominio(estado.ultima_exitosa)
                if estado.ultima_exitosa
                else None
            ),
            vigentes=estado.vigentes,
            elegibles=estado.elegibles,
        )


class ColorOut(BaseModel):
    color: str | None
    generico: bool
    tipo_producto_id: str


class CapacidadOut(BaseModel):
    capacidad: str
    colores: list[ColorOut]


class VarianteOut(BaseModel):
    variante: str | None
    capacidades: list[CapacidadOut]


class ModeloOut(BaseModel):
    marca: str
    modelo: str
    variantes: list[VarianteOut]

    @classmethod
    def desde_opcion(cls, opcion: OpcionModelo) -> "ModeloOut":
        return cls(
            marca=opcion.marca,
            modelo=opcion.modelo,
            variantes=[
                VarianteOut(
                    variante=variante.variante,
                    capacidades=[
                        CapacidadOut(
                            capacidad=capacidad.capacidad,
                            colores=[
                                ColorOut(
                                    color=color.color,
                                    generico=color.generico,
                                    tipo_producto_id=color.tipo_producto_id,
                                )
                                for color in capacidad.colores
                            ],
                        )
                        for capacidad in variante.capacidades
                    ],
                )
                for variante in opcion.variantes
            ],
        )


class CatalogoEquiposOut(BaseModel):
    estado: EstadoCatalogoOut
    modelos: list[ModeloOut]


@router.get("")
def get_catalogo_equipos(contexto: ContextoDep) -> CatalogoEquiposOut:
    """Selector del alta: Modelo -> Variante -> Capacidad -> Color."""
    return CatalogoEquiposOut(
        estado=EstadoCatalogoOut.desde_dominio(
            estado_catalogo_equipos(contexto)
        ),
        modelos=[
            ModeloOut.desde_opcion(opcion)
            for opcion in catalogo_para_seleccion(contexto)
        ],
    )


@router.post("/sync")
def post_sincronizar(
    usuario_id: str, contexto: ContextoDep
) -> SincronizacionOut:
    """Sincroniza la copia con el origen configurado."""
    return SincronizacionOut.desde_dominio(
        sincronizar_catalogo_equipos(contexto, usuario_id=usuario_id)
    )
