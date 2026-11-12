"""Administracion de catalogos con auditoria (DC23, DC23AUD, BR-REP-040).

Reglas puras: quien administra, que se valida y que cambios se auditan. La
persistencia (el catalogo y su auditoria en la misma transaccion) es del
repository.

- Administra Administracion (ACT-ADMIN). La delegacion por permisos
  configurables (BR-REP-039, DC08) sigue pendiente.
- Un Tipo de Reparacion no se borra: se desactiva. Su codigo no cambia y
  ``TR-OTROS`` esta reservado.
- Cada campo que cambia deja un ``CambioConfiguracion`` con el valor
  anterior y el nuevo; un pedido sin cambios se rechaza.
- Lo ya registrado no cambia: los Detalles guardan su copia (BR-REP-015).
"""

from collections.abc import Collection, Iterable
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    TIPO_REPARACION_OTROS,
    CambioConfiguracion,
    EntidadConfiguracion,
    RolUsuario,
    TipoReparacion,
    Usuario,
)

from .autorizacion import validar_alguno_de
from .exceptions import PrecondicionInvalidaError

ROLES_ADMINISTRACION_CONFIGURACION = (RolUsuario.ADMINISTRADOR,)
CAMPOS_TIPO = ("nombre", "precio", "puntaje", "garantia_dias", "activo")
CAMPO_TIPOS_HABILITADOS = "tipos_habilitados"


def texto(valor: object) -> str | None:
    """El valor como lo guarda la auditoria."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, Decimal):
        return f"{valor:.2f}"
    return str(valor)


def _validar_tipo(tipo: TipoReparacion) -> None:
    if tipo.id == TIPO_REPARACION_OTROS:
        raise PrecondicionInvalidaError(
            f"{TIPO_REPARACION_OTROS} esta reservado para la reparacion no "
            "tipificada: no se administra como un Tipo del catalogo."
        )
    if not tipo.nombre.strip():
        raise PrecondicionInvalidaError(
            "El Tipo de Reparacion necesita nombre."
        )
    if tipo.precio < 0 or tipo.puntaje < 0 or tipo.garantia_dias < 0:
        raise PrecondicionInvalidaError(
            "Precio, puntaje y garantia no pueden ser negativos."
        )


def cambios_de_tipo(
    anterior: TipoReparacion | None,
    nuevo: TipoReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> list[CambioConfiguracion]:
    """Los cambios auditables de un alta (``anterior`` None) o una edicion."""
    validar_alguno_de(usuario, ROLES_ADMINISTRACION_CONFIGURACION)
    _validar_tipo(nuevo)
    if anterior is not None and anterior.id != nuevo.id:
        raise PrecondicionInvalidaError("El codigo de un Tipo no cambia.")
    cambios = [
        CambioConfiguracion(
            entidad=EntidadConfiguracion.TIPO_REPARACION,
            clave=nuevo.id,
            campo=campo,
            valor_anterior=(
                texto(getattr(anterior, campo)) if anterior else None
            ),
            valor_nuevo=texto(getattr(nuevo, campo)),
            usuario_id=usuario.id,
            fecha=fecha,
        )
        for campo in CAMPOS_TIPO
        if anterior is None
        or texto(getattr(anterior, campo)) != texto(getattr(nuevo, campo))
    ]
    if not cambios:
        raise PrecondicionInvalidaError(
            f"El Tipo {nuevo.id} ya tiene esos valores: no hay cambios."
        )
    return cambios


def cambio_de_tipos_habilitados(
    estacion_id: str,
    anteriores: Collection[str],
    nuevos: Collection[str],
    *,
    tipos_existentes: Iterable[TipoReparacion],
    usuario: Usuario,
    fecha: datetime,
) -> CambioConfiguracion:
    """Los Tipos que una Mesa de trabajo puede trabajar (BR-REP-011)."""
    validar_alguno_de(usuario, ROLES_ADMINISTRACION_CONFIGURACION)
    conocidos = {tipo.id for tipo in tipos_existentes}
    desconocidos = sorted(set(nuevos) - conocidos)
    if desconocidos:
        raise PrecondicionInvalidaError(
            f"No existen los Tipos de Reparacion {', '.join(desconocidos)}."
        )
    antes = ", ".join(sorted(set(anteriores))) or None
    despues = ", ".join(sorted(set(nuevos))) or None
    if antes == despues:
        raise PrecondicionInvalidaError(
            f"La Mesa {estacion_id} ya tiene esos Tipos: no hay cambios."
        )
    return CambioConfiguracion(
        entidad=EntidadConfiguracion.MESA_TRABAJO,
        clave=estacion_id,
        campo=CAMPO_TIPOS_HABILITADOS,
        valor_anterior=antes,
        valor_nuevo=despues,
        usuario_id=usuario.id,
        fecha=fecha,
    )
