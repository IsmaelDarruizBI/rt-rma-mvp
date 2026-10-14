"""Catalogos y configuracion referenciados por ID desde la Orden.

Ninguna de estas entidades se embebe en OrdenReparacion: las entidades
transaccionales las referencian por ID para que un cambio de catalogo no
reescriba historia ya registrada.
"""

from decimal import Decimal

from pydantic import BaseModel, Field


class TipoReparacion(BaseModel):
    """Tipo de reparacion ofrecido, con sus valores vigentes de catalogo.

    ``precio``, ``puntaje`` y ``garantia_dias`` son los valores ACTUALES.
    Al asignarse a un ReparacionDetail se copian alli como snapshot.
    """

    id: str
    nombre: str
    precio: Decimal = Field(ge=0)
    puntaje: int = Field(ge=0)
    garantia_dias: int = Field(ge=0)
    activo: bool = True


class Insumo(BaseModel):
    """Insumo de inventario.

    Solo se persiste el stock fisico. El stock disponible
    (``stock_fisico - reservas_activas``) es un calculo posterior sobre
    los MovimientoInsumo, no un campo de esta entidad.
    """

    id: str
    codigo: str
    nombre: str
    # Puede ser negativo: un override de factibilidad autorizado (BR-REP-003,
    # ACC-REP-049) permite consumir sin stock suficiente. La proteccion
    # vive en los services (solo un Detalle con override vigente puede
    # llevarlo a negativo), no en el tipo.
    stock_fisico: Decimal
    activo: bool = True


class TipoReparacionInsumos(BaseModel):
    """Insumo previsto que consume un Tipo de Reparacion, y su cantidad."""

    tipo_reparacion_id: str
    insumo_id: str
    cantidad: Decimal = Field(gt=0)


class EstacionTrabajo(BaseModel):
    """Estacion de trabajo fisica desde la que opera un tecnico."""

    id: str
    nombre: str
    activa: bool = True


class MedioPago(BaseModel):
    """Medio por el que se cobra o se devuelve dinero (catalogo).

    Los Pagos y las devoluciones guardan solo el ``id``. Un medio inactivo
    ya no se ofrece ni se acepta para movimientos nuevos, pero sigue
    nombrando a los registrados. ``admite_devolucion`` permite excluir un
    medio de las devoluciones sin tocar la logica financiera.
    """

    id: str
    nombre: str
    activo: bool = True
    admite_devolucion: bool = True


class TipoReparacionEstacion(BaseModel):
    """Compatibilidad entre un Tipo de Reparacion y una Estacion."""

    tipo_reparacion_id: str
    estacion_id: str


class DatosEmpresa(BaseModel):
    """Identificacion de Rosario Tecno en los documentos (configuracion).

    ``condiciones_garantia`` es el texto comercial de la garantia, si el
    negocio lo define: el sistema no inventa condiciones. Cada documento
    emitido guarda una copia, asi que cambiar estos datos no altera lo ya
    entregado al cliente.
    """

    nombre: str
    razon_social: str | None = None
    cuit: str | None = None
    direccion: str | None = None
    telefono: str | None = None
    email: str | None = None
    condiciones_garantia: str | None = None


# Unica definicion de los medios iniciales. Se usan mientras el directorio
# de catalogos no traiga su propio ``medios_pago.json``: para ampliar o
# cambiar los medios alcanza con crear ese archivo, la logica financiera
# solo conoce IDs.
MEDIOS_PAGO_PREDETERMINADOS = (
    MedioPago(id="EFECTIVO", nombre="Efectivo"),
    MedioPago(id="TRANSFERENCIA", nombre="Transferencia"),
    MedioPago(id="TARJETA_DEBITO", nombre="Tarjeta de debito"),
    MedioPago(id="TARJETA_CREDITO", nombre="Tarjeta de credito"),
    MedioPago(id="OTRO", nombre="Otro"),
)

# Se usa mientras el directorio de catalogos no traiga ``empresa.json``.
DATOS_EMPRESA_PREDETERMINADOS = DatosEmpresa(nombre="Rosario Tecno")
