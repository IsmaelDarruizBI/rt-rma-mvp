"""Catalogo de equipos de Gestion de Ventas, sincronizado en RMA.

RMA no administra este catalogo: lo copia, a pedido, desde el origen de
datos de Ventas (hoy una hoja de Google Sheets; manana una base de datos)
y lo usa para que Recepcion elija que equipo ingresa. El alta de una Orden
nunca consulta el origen: lee esta copia.

``tipo_producto_id`` es el ``tp_id`` de Ventas, sin transformar: es la
clave para cruzar una Orden con Ventas, sea cual sea el almacenamiento de
cada lado. Un producto nunca se borra de la copia: si Ventas deja de
informarlo (o lo marca eliminado) queda NO vigente y ya no se ofrece, pero
sigue existiendo para las Ordenes que lo referencian.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MotivoNoSeleccionable(str, Enum):
    """Por que un producto del catalogo no se ofrece para elegir."""

    # Registro tecnico de Ventas que genera variantes: no es un equipo.
    GENERADOR = "GENERADOR"
    # Le falta modelo, capacidad o color (o la variante).
    INCOMPLETO = "INCOMPLETO"


class MotivoBaja(str, Enum):
    """Por que un producto dejo de estar vigente."""

    # La ultima sincronizacion exitosa no lo trajo (Ventas lo borro, o ya
    # no entra en el filtro configurado).
    NO_INFORMADO = "NO_INFORMADO"
    # Ventas lo marco eliminado.
    ELIMINADO_EN_ORIGEN = "ELIMINADO_EN_ORIGEN"


class ProductoInformado(BaseModel):
    """Un producto tal como lo informa el origen, ya en terminos de RMA.

    Lo produce el adaptador del origen (Sheets hoy, una base de datos
    manana): las convenciones de Ventas (``Nada``, ``cualquier_color``,
    ``128gb``) ya vienen traducidas. ``faltantes`` nombra los datos que el
    origen no informo (``marca``, ``modelo``, ``variante``, ``capacidad``,
    ``color``); ``generador`` es un registro tecnico de Ventas, no un
    equipo.
    """

    model_config = {"frozen": True}

    tipo_producto_id: str = Field(min_length=1)
    descripcion: str
    categoria: str | None = None
    subcategoria: str | None = None
    grupo: str | None = None
    marca: str | None = None
    modelo: str | None = None
    variante: str | None = None
    capacidad: str | None = None
    color: str | None = None
    color_generico: bool = False
    generador: bool = False
    eliminado: bool = False
    faltantes: tuple[str, ...] = ()
    valores_origen: dict[str, str] = Field(default_factory=dict)


class ProductoCatalogo(BaseModel):
    """Un tipo de producto del catalogo de Ventas, tal como lo copio RMA.

    ``marca`` ... ``color`` son las etiquetas legibles; ``valores_origen``
    guarda los valores tal como vinieron (``tp_number``, ``tp_gb``, ...).
    ``variante`` ``None`` es la version estandar del modelo; ``color``
    ``None`` con ``color_generico`` es el producto «cualquier color».
    """

    tipo_producto_id: str = Field(min_length=1)
    descripcion: str
    categoria: str | None = None
    subcategoria: str | None = None
    grupo: str | None = None
    marca: str | None = None
    modelo: str | None = None
    variante: str | None = None
    capacidad: str | None = None
    color: str | None = None
    color_generico: bool = False
    seleccionable: bool = True
    motivo_no_seleccionable: MotivoNoSeleccionable | None = None
    vigente: bool = True
    motivo_baja: MotivoBaja | None = None
    valores_origen: dict[str, str] = Field(default_factory=dict)
    # Primera y ultima sincronizacion exitosa que lo trajo del origen.
    primera_sincronizacion: datetime
    ultima_sincronizacion: datetime

    @property
    def elegible(self) -> bool:
        """Se ofrece en el alta: vigente y representa un equipo."""
        return self.vigente and self.seleccionable


class ResultadoSincronizacion(str, Enum):
    EXITOSA = "EXITOSA"
    # El origen no respondio (red, permisos, servicio caido).
    FALLIDA = "FALLIDA"
    # El origen respondio, pero sus datos no son confiables (faltan
    # columnas, ``tp_id`` repetidos, ningun producto): no se aplica nada.
    RECHAZADA = "RECHAZADA"


class SincronizacionCatalogo(BaseModel):
    """Un intento de sincronizacion: quien, cuando, desde donde y que paso.

    Una sincronizacion FALLIDA o RECHAZADA no cambia el catalogo: queda el
    de la ultima EXITOSA. ``origen`` y ``filtro`` describen la fuente sin
    secretos (nunca tokens ni credenciales).
    """

    id: str
    usuario_id: str
    origen: str
    filtro: str
    iniciada_en: datetime
    finalizada_en: datetime
    resultado: ResultadoSincronizacion
    mensaje: str | None = None
    # Registros que leyo del origen y los que pasaron el filtro.
    leidos: int = 0
    filtrados: int = 0
    # Registros sin ``tp_id``: no se pueden referenciar, se descartan.
    descartados: int = 0
    nuevos: int = 0
    actualizados: int = 0
    sin_cambios: int = 0
    reactivados: int = 0
    dados_de_baja: int = 0
    # Despues de aplicar: vigentes y, de ellos, los que se ofrecen.
    vigentes: int = 0
    elegibles: int = 0
