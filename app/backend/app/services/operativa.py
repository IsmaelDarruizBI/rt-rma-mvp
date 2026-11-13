"""Reglas de la configuracion operativa (DEC-MI-13, 14 y 15).

- Un motivo de catalogo se valida por tipo y vigencia; «Otro» (o cualquier
  motivo que lo exija) pide descripcion. El texto que se registra copia el
  nombre del motivo: lo historico conserva su significado.
- Sin motivo de catalogo se admite el texto libre de siempre.
- Administracion da de alta, edita o desactiva motivos y cambia parametros,
  con auditoria.
- Seguimiento de un retiro demorado: lo registra quien tiene el permiso, con
  una nota; la Orden no cambia de estado.
"""

from collections.abc import Iterable
from datetime import datetime

from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    OrdenReparacion,
    Usuario,
)
from app.domain.models.operativa import (
    PARAMETRO_PLAZO_RETIRO,
    MotivoOperativo,
    SeguimientoRetiro,
    TipoMotivo,
)
from app.domain.retiro import fecha_aviso_listo

from . import permisos
from .autorizacion import validar_alguno_de
from .configuracion import texto
from .exceptions import PrecondicionInvalidaError

CAMPOS_MOTIVO = ("nombre", "activo", "requiere_descripcion")


def texto_de_motivo(
    motivos: Iterable[MotivoOperativo],
    tipo: TipoMotivo,
    codigo: str | None,
    descripcion: str | None,
) -> str:
    """El texto que se registra para un motivo elegido (o el texto libre)."""
    if codigo is None:
        # Texto libre: lo valida la regla de cada caso, como siempre.
        return descripcion or ""
    descripcion = (descripcion or "").strip()
    motivo = next(
        (m for m in motivos if m.codigo == codigo and m.tipo is tipo), None
    )
    if motivo is None:
        raise PrecondicionInvalidaError(
            f"No existe el motivo {codigo} para {tipo.value.lower()}."
        )
    if not motivo.activo:
        raise PrecondicionInvalidaError(f"El motivo {codigo} no esta vigente.")
    if motivo.requiere_descripcion and not descripcion:
        raise PrecondicionInvalidaError(
            f"El motivo «{motivo.nombre}» exige una descripcion."
        )
    return f"{motivo.nombre}: {descripcion}" if descripcion else motivo.nombre


def cambios_de_motivo(
    anterior: MotivoOperativo | None,
    nuevo: MotivoOperativo,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> list[CambioConfiguracion]:
    validar_alguno_de(usuario, permisos.CONFIGURACION_ADMINISTRAR)
    if anterior is not None and anterior.tipo is not nuevo.tipo:
        raise PrecondicionInvalidaError("El tipo de un motivo no cambia.")
    cambios = [
        CambioConfiguracion(
            entidad=EntidadConfiguracion.MOTIVO,
            clave=nuevo.codigo,
            campo=campo,
            valor_anterior=texto(getattr(anterior, campo))
            if anterior
            else None,
            valor_nuevo=texto(getattr(nuevo, campo)),
            usuario_id=usuario.id,
            fecha=fecha,
        )
        for campo in CAMPOS_MOTIVO
        if anterior is None
        or texto(getattr(anterior, campo)) != texto(getattr(nuevo, campo))
    ]
    if not cambios:
        raise PrecondicionInvalidaError(
            f"El motivo {nuevo.codigo} ya tiene esos valores: no hay cambios."
        )
    return cambios


def cambio_de_parametro(
    clave: str,
    anterior: str | None,
    nuevo: str,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> CambioConfiguracion:
    validar_alguno_de(usuario, permisos.CONFIGURACION_ADMINISTRAR)
    nuevo = (nuevo or "").strip()
    if clave == PARAMETRO_PLAZO_RETIRO:
        if not nuevo.isdigit() or int(nuevo) < 1:
            raise PrecondicionInvalidaError(
                "El plazo de retiro es una cantidad entera de dias, mayor "
                "que cero."
            )
        nuevo = str(int(nuevo))
    if anterior == nuevo:
        raise PrecondicionInvalidaError(
            f"El parametro {clave} ya tiene ese valor: no hay cambios."
        )
    return CambioConfiguracion(
        entidad=EntidadConfiguracion.PARAMETRO,
        clave=clave,
        campo="valor",
        valor_anterior=anterior,
        valor_nuevo=nuevo,
        usuario_id=usuario.id,
        fecha=fecha,
    )


def registrar_seguimiento_retiro(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
    nota: str,
    canal: str | None = None,
) -> OrdenReparacion:
    """Un seguimiento del retiro (DEC-MI-14): con el aviso de equipo listo
    hecho y el equipo todavia en el local. No cambia el estado."""
    validar_alguno_de(usuario, permisos.RETIRO_SEGUIMIENTO)
    nota = (nota or "").strip()
    if not nota:
        raise PrecondicionInvalidaError("El seguimiento exige una nota.")
    if orden.esta_cerrada or orden.entrega is not None:
        raise PrecondicionInvalidaError(
            "El equipo ya se entrego: no hay retiro que seguir."
        )
    if fecha_aviso_listo(orden) is None:
        raise PrecondicionInvalidaError(
            "Todavia no se aviso al cliente que el equipo esta listo."
        )
    nueva = orden.model_copy(deep=True)
    nueva.seguimientos_retiro.append(
        SeguimientoRetiro(
            usuario_id=usuario.id,
            fecha=fecha,
            nota=nota,
            canal=(canal or "").strip() or None,
        )
    )
    nueva.updated_at = fecha
    return nueva
