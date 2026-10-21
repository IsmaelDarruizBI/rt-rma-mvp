"""Fotografias del equipo vinculadas a una Orden (MVP v2, UAT-010).

La Orden guarda solo los datos de cada foto: donde esta (``objeto``, la
clave en el almacenamiento privado), de que tipo es, cuanto pesa, quien la
subio y cuando. La imagen nunca se guarda en el JSON de la Orden ni en el
disco efimero del servidor: vive en un almacenamiento de objetos privado
(``app.storage.fotos``). Las fotos son opcionales.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class FotoOrden(BaseModel):
    """Una foto del equipo: sus datos, nunca la imagen."""

    id: str
    objeto: str
    tipo_contenido: str
    tamano_bytes: int = Field(ge=1)
    usuario_id: str
    fecha: datetime
    nombre_original: str | None = None
