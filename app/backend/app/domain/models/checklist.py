"""Checklist de recepcion por tipo de equipo (DC12; BR-REP-024/025/040).

- El Tipo de Equipo viene del catalogo de Ventas de Gestion RT (decision
  aprobada de DC12): RMA guarda una COPIA de solo lectura, que se actualiza
  sincronizando desde el origen ya existente (``integraciones.catalogo``).
  Administracion no crea ni edita tipos; si configura las preguntas, que se
  asocian al identificador estable del tipo en Ventas.
- Que dato de Ventas es el Tipo de Equipo lo fija ``RMA_TIPO_EQUIPO_CAMPO``.
  Mientras negocio no lo confirme queda vacio: no hay tipos y el checklist
  no se ofrece. Nada se infiere del modelo ni de la marca.
- Lo que se registra en la Orden es una copia del tipo (identificador y
  descripcion) y de las preguntas y opciones aplicadas: un cambio posterior
  del catalogo no altera un checklist ya completado. Una correccion agrega
  una version nueva con motivo; rige la ultima.
- Advertencia por informacion faltante (BR-REP-025): fotos, observaciones
  o verificaciones sin registrar. Nunca bloquea: Recepcion puede continuar
  igualmente y esa confirmacion queda registrada.
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class TipoEquipo(BaseModel):
    """Un Tipo de Equipo del catalogo de Ventas, tal como lo copio RMA.

    ``id``: el valor de Ventas tal cual (identificador estable). ``activo``:
    sigue en el catalogo en la ultima sincronizacion (los que dejan de
    estar no se borran: las preguntas y los checklists los referencian).
    """

    id: str = Field(min_length=1, max_length=200)
    nombre: str = Field(min_length=1)
    activo: bool = True
    # Columna de Ventas de la que salio (``tp_categoria``, ...).
    campo_origen: str | None = None
    # Ultima sincronizacion en la que estaba en el catalogo.
    sincronizado_en: datetime | None = None


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
