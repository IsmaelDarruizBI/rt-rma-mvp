"""Textos legales versionados de los comprobantes (DEC-AJ-09, BF-19).

Hoy hay un solo tipo: los Terminos y Condiciones que acompanan al
"Comprobante de entrega y garantia" (DEC-AJ-04). Cada version es
inmutable: corregir el texto es publicar una version nueva, que rige para
los documentos que se emitan despues. Cada comprobante guarda en su
snapshot la version que uso (y, en PostgreSQL, ``texto_legal_id``), asi
que reimprimirlo da siempre el mismo texto.

``TERMINOS_INICIALES`` es la version 2, la que carga la migracion
``20261123000300_comprobantes_empresa_terminos`` (misma copia que
``app/datos/terminos_condiciones_v2.json``): el texto del bloque 2 (P-05)
con P-04 aplicado, sin un plazo fijo de 180 dias. En el modo JSON es la
version vigente si el directorio de catalogos no trae la suya.
"""

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class TipoTextoLegal(str, Enum):
    TERMINOS_CONDICIONES_ENTREGA = "TERMINOS_CONDICIONES_ENTREGA"


class EncabezadoTextoLegal(BaseModel):
    marca: str = ""
    titulo: str = ""
    subtitulo: str = ""


class ApartadoTextoLegal(BaseModel):
    """Un apartado numerado: la primera linea lo abre y las siguientes son
    los renglones que la hoja muestra aparte. ``destacado`` se imprime
    resaltado."""

    numero: int = Field(ge=1)
    lineas: list[str] = Field(min_length=1)
    destacado: bool = False

    @field_validator("lineas")
    @classmethod
    def _sin_lineas_vacias(cls, lineas: list[str]) -> list[str]:
        limpias = [linea.strip() for linea in lineas]
        if any(not linea for linea in limpias):
            raise ValueError("un apartado no tiene lineas vacias")
        return limpias


class ContenidoTextoLegal(BaseModel):
    """El texto completo tal como se imprime: encabezado, apartados en
    orden y los espacios del pie (firma, aclaracion, fecha)."""

    encabezado: EncabezadoTextoLegal = Field(
        default_factory=EncabezadoTextoLegal
    )
    apartados: list[ApartadoTextoLegal] = Field(min_length=1)
    pie: list[str] = Field(default_factory=list)


class TextoLegal(BaseModel):
    """Una version publicada de un texto legal (``rma.texto_legal``).

    ``publicado_por`` es el usuario que la publico (``None`` en la carga
    inicial). Rige la de mayor version: se publica vigente desde ese
    momento.
    """

    tipo: TipoTextoLegal = TipoTextoLegal.TERMINOS_CONDICIONES_ENTREGA
    version: int = Field(ge=1)
    titulo: str = Field(min_length=1)
    contenido: ContenidoTextoLegal
    vigente_desde: datetime
    publicado_por: str | None = None


_ARCHIVO_INICIAL = (
    Path(__file__).resolve().parents[2]
    / "datos"
    / "terminos_condiciones_v2.json"
)


def _terminos_iniciales() -> TextoLegal:
    return TextoLegal.model_validate(
        json.loads(_ARCHIVO_INICIAL.read_text(encoding="utf-8"))
    )


TERMINOS_INICIALES = _terminos_iniciales()
