"""Equipo recibido para reparacion y su salida fisica del local."""

from datetime import datetime

from pydantic import BaseModel

from .enums import TipoEntrega


class Equipo(BaseModel):
    """Equipo fisico asociado a una Orden de Reparacion.

    Identidad FISICA de esta unidad: ``id`` (interno de RMA), ``imei`` y
    ``numero_serie``. Son opcionales: no todo equipo tiene IMEI (una
    notebook, un parlante) y el identificador se registra si existe.

    Que equipo es: ``marca``, ``modelo`` y ``variante``. Si se eligio del
    catalogo tecnico de RMA, ``modelo_tecnico_id`` es el ID del modelo y
    marca, modelo y variante son una copia de como estaba al elegirlo (un
    cambio posterior del catalogo no reescribe la Orden). Sin ID, se
    cargaron a mano (equipos fuera del catalogo). ``capacidad`` y
    ``color`` no identifican el tipo de equipo: el color es opcional y se
    carga aparte.

    Ordenes anteriores: ``tipo_producto_id`` es el ``tp_id`` del producto
    del catalogo de Ventas que se eligio (con su capacidad y color). Se
    conserva tal cual; las Ordenes nuevas ya no lo usan.

    ``tipo_producto_id`` identifica un TIPO de producto, no esta unidad: dos
    equipos del mismo modelo, capacidad y color comparten ``tp_id`` y se
    distinguen por su ``id`` y su IMEI.

    ``falla_reportada`` es la falla declarada por quien deja el equipo.
    """

    id: str
    marca: str
    modelo: str
    falla_reportada: str
    imei: str | None = None
    numero_serie: str | None = None
    tipo_producto_id: str | None = None
    # Modelo del catalogo tecnico de RMA (``MOD-0001``).
    modelo_tecnico_id: str | None = None
    # ``None``: la version estandar del modelo (o no informada).
    variante: str | None = None
    capacidad: str | None = None
    # ``None``: no especificado (por ejemplo, el producto «cualquier color»
    # del catalogo) o carga manual.
    color: str | None = None

    @property
    def nombre(self) -> str:
        """Marca, modelo y variante: «Apple iPhone 12 Pro Max»."""
        return " ".join(
            parte
            for parte in (self.marca, self.modelo, self.variante)
            if parte
        )

    @property
    def descripcion(self) -> str:
        """El nombre con capacidad y color, si se conocen."""
        return " ".join(
            parte
            for parte in (self.nombre, self.capacidad, self.color)
            if parte
        )


class EntregaEquipo(BaseModel):
    """Salida fisica del equipo: entrega o devolucion (PROC-REP-270).

    Registra quien entrega (usuario del sistema), quien retira (texto
    libre: el cliente, un tercero o Gestion RT), su identificacion si
    corresponde (DNI u otra) y cuando. No hay firma ni identificacion
    digital del receptor.

    ``tipo`` distingue la entrega de una reparacion terminada de una
    devolucion sin reparacion. Default DEVOLUCION_SIN_REPARACION: antes de
    este campo solo se registraba la devolucion de una Orden CANCELADA, asi
    que un JSON anterior sigue cargando con el valor correcto.
    """

    tipo: TipoEntrega = TipoEntrega.DEVOLUCION_SIN_REPARACION
    entregado_por: str
    recibido_por: str
    identificacion_receptor: str | None = None
    fecha: datetime
    observaciones: str | None = None


# Nombre historico: la devolucion sin reparar de una Orden CANCELADA es una
# ``EntregaEquipo`` de tipo DEVOLUCION_SIN_REPARACION.
DevolucionEquipo = EntregaEquipo
