"""Catalogo tecnico de modelos de equipo, propio de RMA.

Identifica QUE equipo es (marca, modelo comercial y variante), no esta
unidad: la identidad fisica (IMEI, numero de serie) y lo que no cambia el
tipo de equipo (capacidad, color) son del Equipo de cada Orden.

No depende del catalogo comercial de Ventas: su contenido inicial se
genero una vez a partir de esos datos (``scripts/generar_modelos_equipo``)
y desde entonces es de RMA. ``numeros_modelo`` son los identificadores del
fabricante (por ejemplo «A2849»), no el ``tp_number`` de Ventas: lista
vacia mientras no haya informacion verificada.
"""

from pydantic import BaseModel, Field


class ModeloEquipo(BaseModel):
    """Un modelo tecnico: «Apple iPhone 15 Pro Max».

    ``id`` es propio de RMA y estable (``MOD-0001``): una Orden lo guarda
    junto con una copia de marca, modelo y variante. ``variante`` ``None``
    es la version estandar del modelo. Un modelo no se borra: deja de
    ofrecerse con ``activo`` en falso.
    """

    model_config = {"frozen": True}

    id: str = Field(pattern=r"^MOD-\d{4,}$")
    marca: str = Field(min_length=1)
    modelo: str = Field(min_length=1)
    variante: str | None = None
    numeros_modelo: tuple[str, ...] = ()
    activo: bool = True

    @property
    def nombre(self) -> str:
        """Marca, modelo y variante: «Apple iPhone 15 Pro Max»."""
        return " ".join(
            parte
            for parte in (self.marca, self.modelo, self.variante)
            if parte
        )
