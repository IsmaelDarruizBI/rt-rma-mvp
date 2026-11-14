"""Checklist de recepcion por tipo de equipo (DC12; BR-REP-024/025/040).

- Tipos de equipo y preguntas los configura Administracion (con
  auditoria). El catalogo empieza vacio: el sistema no inventa una
  clasificacion. Cada pregunta tiene sus opciones; ninguna verificacion es
  obligatoria y cualquiera puede registrarse como no realizada.
- De donde toma la Orden su tipo de equipo no esta definido en la baseline
  (ver la discrepancia de DC12): hoy lo elige Recepcion al completar el
  checklist. Nada se infiere del modelo ni de la marca.
- Lo que se registra en la Orden es una copia de las preguntas y opciones
  aplicadas: cambiar el catalogo no altera un checklist ya completado. Una
  correccion agrega una version nueva con motivo; rige la ultima.
- Advertencia por informacion faltante (BR-REP-025): fotos, observaciones
  o verificaciones sin registrar. Nunca bloquea: Recepcion puede continuar
  igualmente y esa confirmacion queda registrada.
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class TipoEquipo(BaseModel):
    id: str = Field(pattern=r"^TEQ-[0-9A-Z-]+$")
    nombre: str = Field(min_length=1)
    activo: bool = True


class PreguntaChecklist(BaseModel):
    id: str = Field(pattern=r"^CHK-[0-9A-Z-]+$")
    tipo_equipo_id: str
    texto: str = Field(min_length=1)
    opciones: list[str] = Field(min_length=2)
    activa: bool = True
    orden: int = 0

    @model_validator(mode="after")
    def _opciones_distintas(self) -> "PreguntaChecklist":
        limpias = [o.strip() for o in self.opciones]
        if any(not o for o in limpias) or len(set(limpias)) != len(limpias):
            raise ValueError(
                "Las opciones no pueden estar vacias ni repetirse."
            )
        self.opciones = limpias
        return self


class RespuestaChecklist(BaseModel):
    """Copia de la pregunta aplicada y su respuesta (o no realizada)."""

    pregunta_id: str
    texto: str
    opciones: list[str]
    respuesta: str | None = None
    no_realizada: bool = False

    @model_validator(mode="after")
    def _respuesta_valida(self) -> "RespuestaChecklist":
        if self.no_realizada and self.respuesta is not None:
            raise ValueError(
                "Una verificacion no realizada no tiene respuesta."
            )
        if not self.no_realizada and self.respuesta not in self.opciones:
            raise ValueError(
                f"«{self.respuesta}» no es una opcion de «{self.texto}»."
            )
        return self


class RegistroChecklist(BaseModel):
    """Un checklist completado (o su correccion). Inmutable."""

    tipo_equipo_id: str
    tipo_equipo_nombre: str
    respuestas: list[RespuestaChecklist]
    # Preguntas vigentes del tipo que quedaron sin registrar.
    sin_registrar: list[str] = Field(default_factory=list)
    usuario_id: str
    fecha: datetime
    motivo: str | None = None


class ConfirmacionInformacionFaltante(BaseModel):
    """Recepcion continuo igualmente con informacion faltante (BR-REP-025)."""

    faltantes: list[str] = Field(min_length=1)
    usuario_id: str
    fecha: datetime
