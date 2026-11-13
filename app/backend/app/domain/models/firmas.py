"""Firma de un documento emitido (DEC-MI-06; BR-REP-042; cierra ABI-08).

Ningun documento exige firma. Si el cliente firma, la evidencia queda
ligada al documento: una firma en pantalla (imagen del trazo) o una foto
del documento firmado en papel. La imagen vive en el almacenamiento
privado de las fotos; aca solo sus datos. Las firmas no se modifican ni se
borran, y no forman parte de la Orden: se pueden registrar tambien despues
de la entrega (la Orden ya cerrada no cambia).
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FormaFirma(str, Enum):
    PANTALLA = "PANTALLA"
    FOTO_DOCUMENTO = "FOTO_DOCUMENTO"


class FirmaDocumento(BaseModel):
    id: str
    orden_id: str
    documento_id: str
    forma: FormaFirma
    objeto: str
    tipo_contenido: str
    tamano_bytes: int = Field(ge=1)
    usuario_id: str
    fecha: datetime
    firmante: str | None = None
