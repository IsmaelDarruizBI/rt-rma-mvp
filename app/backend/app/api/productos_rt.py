"""Reparacion RT, etapa 1: Productos de Gestion RT en reparacion.

    GET  /api/rt-products              listado con busqueda, filtros y
                                       pagina (PRODUCTOS_RT_CONSULTAR)
    GET  /api/rt-products/{id}         ficha (PRODUCTOS_RT_CONSULTAR)
    POST /api/rt-products/sync?usuario_id=
                                       sincroniza a pedido
                                       (PRODUCTOS_RT_SINCRONIZAR)
    GET  /api/rt-products/syncs        ultimos intentos
                                       (PRODUCTOS_RT_SINCRONIZAR)

Los GET leen la copia: nunca consultan el origen. El POST es el unico que
lo lee. Nada escribe en Gestion RT (DEC-RT-01). El POST no usa la clave de
idempotencia, igual que el del catalogo (bloque C): la sincronizacion lee
el origen fuera de toda transaccion y registra los intentos fallidos;
repetirla es inocuo y la reserva impide dos a la vez.

Toda relacion con una Orden se informa en ``coincidencias_sugeridas``, con
su criterio: es una sugerencia, nunca un vinculo, una Orden activa ni
historial del producto (DEC-RT-03). Los vinculos llegan en la etapa 2.

Solo sobre PostgreSQL: en el modo JSON el listado responde con la copia no
habilitada (la pantalla lo informa) y la ficha y la sincronizacion, 409.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.application.productos_rt import (
    EstadoProductosRt,
    ficha_producto_rt,
    listar_productos_rt,
    sincronizaciones_productos_rt,
    sincronizar_productos_rt,
)
from app.domain.models import (
    CoincidenciaSugerida,
    CriterioCoincidencia,
    ProductoRt,
    ResultadoSincronizacion,
    SincronizacionProductosRt,
)
from app.repositories.productos_rt import FiltroOrdenRma, FiltroProductosRt
from app.services import permisos
from app.services.productos_rt import terminos_de_busqueda

from .dependencias import ContextoDep
from .seguridad import exigir_rol

router = APIRouter(prefix="/api/rt-products", tags=["reparacion-rt"])

_consulta = [exigir_rol(permisos.PRODUCTOS_RT_CONSULTAR)]
_sincronizacion = [exigir_rol(permisos.PRODUCTOS_RT_SINCRONIZAR)]

TAMANO_MAXIMO = 100
# ``sede=`` (vacia) filtra los productos sin sede.
SIN_SEDE = ""


class AvisoProducto(str, Enum):
    """Advertencias de un producto (la pantalla las explica)."""

    SIN_IMEI = "SIN_IMEI"
    IMEI_INVALIDO = "IMEI_INVALIDO"
    IMEI_VERIFICADOR_INCORRECTO = "IMEI_VERIFICADOR_INCORRECTO"
    IMEI_REPETIDO = "IMEI_REPETIDO"
    TIPO_NO_ENCONTRADO = "TIPO_NO_ENCONTRADO"
    TIPO_ELIMINADO = "TIPO_ELIMINADO"
    SIN_SEDE = "SIN_SEDE"
    SEDE_NO_CONFIRMADA = "SEDE_NO_CONFIRMADA"
    CONFLICTO_ORIGEN = "CONFLICTO_ORIGEN"
    CAMBIO_IDENTIDAD = "CAMBIO_IDENTIDAD"
    FUERA_DE_REPARACION = "FUERA_DE_REPARACION"
    ELIMINADO_EN_ORIGEN = "ELIMINADO_EN_ORIGEN"
    AUSENTE_DEL_ORIGEN = "AUSENTE_DEL_ORIGEN"


def _avisos(
    producto: ProductoRt, sedes: tuple[str, ...]
) -> list[AvisoProducto]:
    avisos = []
    if producto.imei_normalizado is None:
        avisos.append(AvisoProducto.SIN_IMEI)
    elif not producto.imei_valido:
        avisos.append(AvisoProducto.IMEI_INVALIDO)
    elif producto.imei_luhn_valido is False:
        avisos.append(AvisoProducto.IMEI_VERIFICADOR_INCORRECTO)
    if producto.imei_repetido:
        avisos.append(AvisoProducto.IMEI_REPETIDO)
    if not producto.tipo_producto_encontrado:
        avisos.append(AvisoProducto.TIPO_NO_ENCONTRADO)
    elif producto.tipo_producto_eliminado:
        avisos.append(AvisoProducto.TIPO_ELIMINADO)
    if producto.sede is None:
        avisos.append(AvisoProducto.SIN_SEDE)
    elif producto.sede not in sedes:
        avisos.append(AvisoProducto.SEDE_NO_CONFIRMADA)
    if producto.conflicto_origen:
        avisos.append(AvisoProducto.CONFLICTO_ORIGEN)
    if producto.cambio_identidad:
        avisos.append(AvisoProducto.CAMBIO_IDENTIDAD)
    if not producto.en_reparacion:
        avisos.append(AvisoProducto.FUERA_DE_REPARACION)
    if producto.eliminado_en_origen:
        avisos.append(AvisoProducto.ELIMINADO_EN_ORIGEN)
    if not producto.presente_en_origen:
        avisos.append(AvisoProducto.AUSENTE_DEL_ORIGEN)
    return avisos


class SincronizacionOut(BaseModel):
    id: str
    usuario_id: str
    origen: str
    filtro: str
    iniciada_en: datetime
    finalizada_en: datetime
    resultado: ResultadoSincronizacion
    mensaje: str | None = None
    contadores: dict[str, int]
    avisos: list[str]

    @classmethod
    def desde_dominio(
        cls, sincronizacion: SincronizacionProductosRt
    ) -> "SincronizacionOut":
        return cls(**sincronizacion.model_dump())


class EstadoCopiaOut(BaseModel):
    """De cuando son los datos (la pantalla siempre lo muestra)."""

    habilitado: bool
    sincronizable: bool
    origen: str | None
    filtro: str
    # Fecha de los datos: la ultima sincronizacion exitosa.
    datos_del: datetime | None
    ultima: SincronizacionOut | None
    ultima_exitosa: SincronizacionOut | None
    desactualizada: bool
    antiguedad_aviso_horas: int

    @classmethod
    def desde_dominio(cls, estado: EstadoProductosRt) -> "EstadoCopiaOut":
        return cls(
            habilitado=estado.habilitado,
            sincronizable=estado.sincronizable,
            origen=estado.origen,
            filtro=estado.filtro,
            datos_del=(
                estado.ultima_exitosa.finalizada_en
                if estado.ultima_exitosa
                else None
            ),
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
            desactualizada=estado.desactualizada,
            antiguedad_aviso_horas=int(
                estado.antiguedad_aviso.total_seconds() // 3600
            ),
        )


class CoincidenciaOut(BaseModel):
    """Una Orden que COINCIDE: solo una sugerencia (DEC-RT-03)."""

    orden_id: str
    criterios: list[CriterioCoincidencia]
    origen: str
    estado_workflow: str
    cerrada: bool
    creada_en: datetime

    @classmethod
    def desde_dominio(cls, c: CoincidenciaSugerida) -> "CoincidenciaOut":
        return cls(**c.model_dump())


class ProductoRtResumenOut(BaseModel):
    producto_id: str
    imei: str | None
    imei_valido: bool
    imei_repetido: bool
    modelo: str | None
    capacidad: str | None
    color: str | None
    descripcion_tipo: str | None
    sede: str | None
    estado_gestion_rt: str
    en_reparacion: bool
    en_reparacion_desde: datetime | None
    salio_de_reparacion_en: datetime | None
    eliminado_en_origen: bool
    presente_en_origen: bool
    avisos: list[AvisoProducto]
    coincidencias_sugeridas: list[CoincidenciaOut]


class ProductoRtOut(ProductoRtResumenOut):
    """La ficha: datos tecnicos, avisos y coincidencias sugeridas."""

    imei_normalizado: str | None
    imei_luhn_valido: bool | None
    tipo_producto_id: str | None
    tipo_producto_encontrado: bool
    tipo_producto_eliminado: bool
    categoria: str | None
    subcategoria: str | None
    bateria: str | None
    detalle_estetico: str | None
    defecto: str | None
    toma_rt: str | None
    tipo_reparacion_origen: str | None
    repuesto: str | None
    creado_en_origen: datetime | None
    conflicto_origen: bool
    cambio_identidad: bool
    identidad_anterior: dict[str, str | None] | None
    primera_vez_visto_en: datetime
    sincronizado_en: datetime


def _resumen_datos(
    producto: ProductoRt,
    coincidencias: tuple[CoincidenciaSugerida, ...],
    sedes: tuple[str, ...],
) -> dict:
    return {
        **producto.model_dump(
            exclude={"texto_busqueda", "huella"},
        ),
        "avisos": _avisos(producto, sedes),
        "coincidencias_sugeridas": [
            CoincidenciaOut.desde_dominio(c) for c in coincidencias
        ],
    }


class SedeOut(BaseModel):
    sede: str | None
    cantidad: int
    confirmada: bool


class ListadoProductosRtOut(BaseModel):
    copia: EstadoCopiaOut
    sedes: list[SedeOut]
    total: int
    pagina: int
    tamano: int
    productos: list[ProductoRtResumenOut]


class FichaProductoRtOut(BaseModel):
    copia: EstadoCopiaOut
    producto: ProductoRtOut


@router.get("", dependencies=_consulta)
def get_productos_rt(
    contexto: ContextoDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sede: Annotated[list[str] | None, Query()] = None,
    orden_rma: FiltroOrdenRma | None = None,
    incluir_fuera: bool = False,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamano: Annotated[int, Query(ge=1, le=TAMANO_MAXIMO)] = 50,
) -> ListadoProductosRtOut:
    """Los productos en reparacion (o todos, con ``incluir_fuera``)."""
    filtro = FiltroProductosRt(
        terminos=tuple(terminos_de_busqueda(q)),
        sedes=tuple(
            None if s.strip() == SIN_SEDE else s.strip() for s in sede or ()
        ),
        orden_rma=orden_rma,
        incluir_fuera=incluir_fuera,
        pagina=pagina,
        tamano=tamano,
    )
    estado, resultado = listar_productos_rt(contexto, filtro)
    confirmadas = contexto.reglas_productos_rt.sedes
    sedes = {s: 0 for s in confirmadas}
    for nombre, cantidad in resultado.sedes:
        sedes[nombre] = cantidad
    return ListadoProductosRtOut(
        copia=EstadoCopiaOut.desde_dominio(estado),
        sedes=[
            SedeOut(sede=s, cantidad=n, confirmada=s in confirmadas)
            for s, n in sedes.items()
        ],
        total=resultado.total,
        pagina=pagina,
        tamano=tamano,
        productos=[
            ProductoRtResumenOut(
                **_resumen_datos(
                    listado.producto, listado.coincidencias, confirmadas
                )
            )
            for listado in resultado.productos
        ],
    )


@router.get("/syncs", dependencies=_sincronizacion)
def get_sincronizaciones(
    contexto: ContextoDep,
    limite: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[SincronizacionOut]:
    """Los ultimos intentos, del mas reciente al mas viejo."""
    return [
        SincronizacionOut.desde_dominio(s)
        for s in sincronizaciones_productos_rt(contexto, limite=limite)
    ]


@router.post("/sync", dependencies=_sincronizacion)
def post_sincronizar(
    usuario_id: str, contexto: ContextoDep
) -> SincronizacionOut:
    """Sincroniza la copia con el origen configurado."""
    return SincronizacionOut.desde_dominio(
        sincronizar_productos_rt(contexto, usuario_id=usuario_id)
    )


@router.get("/{producto_id}", dependencies=_consulta)
def get_producto_rt(
    producto_id: str, contexto: ContextoDep
) -> FichaProductoRtOut:
    """Ficha: datos tecnicos, avisos y coincidencias sugeridas."""
    ficha = ficha_producto_rt(contexto, producto_id)
    return FichaProductoRtOut(
        copia=EstadoCopiaOut.desde_dominio(ficha.estado),
        producto=ProductoRtOut(
            **_resumen_datos(
                ficha.producto,
                ficha.coincidencias,
                contexto.reglas_productos_rt.sedes,
            )
        ),
    )
