"""Configuracion operativa: motivos y parametros (DEC-MI-13, 14 y 15).

- Motivos de cancelacion y de interrupcion: catalogos separados,
  administrados por Administracion. Cada uno empieza solo con «Otro», que
  exige descripcion (DEC-MI-15); el resto lo carga Administracion. Al
  usarse, el texto del motivo se copia en el registro: una cancelacion
  antigua no cambia de significado si el catalogo cambia.
- Parametros operativos: por ahora el plazo de retiro demorado (30 dias
  desde el aviso de equipo listo, DEC-MI-14).
- Seguimiento de un retiro demorado: quien, cuando, que y por que canal.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TipoMotivo(str, Enum):
    CANCELACION = "CANCELACION"
    INTERRUPCION = "INTERRUPCION"


class MotivoOperativo(BaseModel):
    codigo: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]*$")
    tipo: TipoMotivo
    nombre: str = Field(min_length=1)
    activo: bool = True
    requiere_descripcion: bool = False


# CFG-01: prefijo de los codigos que genera la base para cada tipo.
PREFIJO_MOTIVO = {
    TipoMotivo.CANCELACION: "CANC",
    TipoMotivo.INTERRUPCION: "INT",
}

MOTIVOS_INICIALES = (
    MotivoOperativo(
        codigo="CANC-OTRO",
        tipo=TipoMotivo.CANCELACION,
        nombre="Otro",
        requiere_descripcion=True,
    ),
    MotivoOperativo(
        codigo="INT-OTRO",
        tipo=TipoMotivo.INTERRUPCION,
        nombre="Otro",
        requiere_descripcion=True,
    ),
)

PARAMETRO_PLAZO_RETIRO = "PLAZO_RETIRO_DIAS"
PARAMETROS_INICIALES = {PARAMETRO_PLAZO_RETIRO: "30"}


class SeguimientoRetiro(BaseModel):
    """Un seguimiento de un retiro demorado (DEC-MI-14)."""

    usuario_id: str
    fecha: datetime
    nota: str = Field(min_length=1)
    canal: str | None = None
