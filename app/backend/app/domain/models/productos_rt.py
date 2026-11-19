"""Productos de Gestion RT en reparacion (DEC-RT-01 a 07; BR-REP-050).

``ProductoRt`` es la copia de CONSULTA de un producto de Gestion RT: no es
un Equipo de RMA ni una sincronizacion de inventario. Producto RT y Equipo
RMA son entidades distintas y nunca se fusionan; en la etapa 1 no hay
vinculos: una Orden que coincide por referencia RT o por IMEI es solo una
``CoincidenciaSugerida`` (DEC-RT-03), nunca un vinculo, una Orden activa ni
historial del producto.

Nunca se borra: un producto que sale de Reparacion, se elimina en Gestion
RT o deja de aparecer en el origen queda marcado. Ningun dato comercial ni
personal: solo las columnas de la lista permitida
(``integraciones.gestion_rt.contrato.COPIAR``).
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from .catalogo_equipos import ResultadoSincronizacion


class ProductoRt(BaseModel):
    """Un producto de la copia ``PRODUCTOS_RT``."""

    producto_id: str
    # ``producto_status`` tal como vino (sin espacios al borde).
    estado_gestion_rt: str
    en_reparacion: bool
    # Inicio del periodo de reparacion vigente (o del ultimo): la primera
    # sincronizacion que lo vio en Reparacion. Volver a Reparacion abre un
    # periodo nuevo.
    en_reparacion_desde: datetime | None = None
    salio_de_reparacion_en: datetime | None = None
    eliminado_en_origen: bool = False
    # Falso si la ultima lectura exitosa no lo trajo (nunca se borra).
    presente_en_origen: bool = True
    sede: str | None = None
    # IMEI tal como vino, normalizado (sin espacios, en mayusculas) y si es
    # valido (15 digitos). El digito verificador se informa, no invalida.
    imei: str | None = None
    imei_normalizado: str | None = None
    imei_valido: bool = False
    imei_luhn_valido: bool | None = None
    # Mismo IMEI valido en otro producto presente: nunca sugiere ni vincula.
    imei_repetido: bool = False
    tipo_producto_id: str | None = None
    tipo_producto_encontrado: bool = False
    tipo_producto_eliminado: bool = False
    # Del TipoProducto (Producto no tiene color ni capacidad propios).
    descripcion_tipo: str | None = None
    modelo: str | None = None
    categoria: str | None = None
    subcategoria: str | None = None
    capacidad: str | None = None
    color: str | None = None
    # Datos tecnicos de Gestion RT, para la ficha (tal cual).
    bateria: str | None = None
    detalle_estetico: str | None = None
    defecto: str | None = None
    toma_rt: str | None = None
    tipo_reparacion_origen: str | None = None
    repuesto: str | None = None
    creado_en_origen: datetime | None = None
    # El ``producto_id`` vino repetido en la ultima lectura: se conservan los
    # datos anteriores hasta que el origen lo resuelva.
    conflicto_origen: bool = False
    # Cambio el IMEI o el TipoProducto del mismo ``producto_id``: se avisa.
    cambio_identidad: bool = False
    identidad_anterior: dict[str, str | None] | None = None
    # Para la busqueda: ID, IMEI y equipo, sin mayusculas ni tildes.
    texto_busqueda: str = ""
    # Huella de los datos del origen: detecta los cambios.
    huella: str = ""
    primera_vez_visto_en: datetime
    sincronizado_en: datetime

    @property
    def listable(self) -> bool:
        """Se lista por defecto: en Reparacion, presente y no eliminado."""
        return (
            self.en_reparacion
            and self.presente_en_origen
            and not self.eliminado_en_origen
        )


class SincronizacionProductosRt(BaseModel):
    """Un intento de sincronizar la copia de Productos RT.

    FALLIDA, RECHAZADA o INTERRUMPIDA no cambian la copia: queda la de la
    ultima EXITOSA. ``avisos`` nunca incluye IMEI ni valores del origen:
    solo contadores, columnas y ``producto_id``."""

    id: str
    usuario_id: str
    origen: str
    filtro: str
    iniciada_en: datetime
    finalizada_en: datetime
    resultado: ResultadoSincronizacion
    mensaje: str | None = None
    contadores: dict[str, int] = Field(default_factory=dict)
    avisos: list[str] = Field(default_factory=list)


class CriterioCoincidencia(str, Enum):
    REFERENCIA_RT = "REFERENCIA_RT"
    IMEI = "IMEI"


class CoincidenciaSugerida(BaseModel):
    """Una Orden de RMA que COINCIDE con el producto (DEC-RT-03).

    Es solo una sugerencia: no vincula, no es la Orden activa del producto
    ni su historial. Una Orden que coincide por los dos criterios aparece
    una vez, con ambos."""

    orden_id: str
    criterios: list[CriterioCoincidencia]
    origen: str
    estado_workflow: str
    cerrada: bool
    creada_en: datetime
