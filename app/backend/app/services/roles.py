"""Roles de los usuarios y permisos configurables (DC27A, DC08; DEC-MI-12).

Reglas puras; la persistencia (el cambio y su auditoria en la misma
transaccion) es del repository de configuracion.

- Solo Administracion asigna roles y configura permisos
  (``permisos.ROLES_ADMINISTRAR``, no configurable).
- Un usuario tiene al menos un rol; con varios, sus permisos se suman.
- Ningun cambio deja el sistema sin un Administrador activo.
- Los permisos de administracion no se configuran (``configurable=False``):
  nadie puede quedarse sin quien administre la configuracion.
- Cada cambio deja un ``CambioConfiguracion`` con los roles anteriores y
  los nuevos.
"""

from collections.abc import Collection, Iterable
from datetime import datetime

from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    RolUsuario,
    Usuario,
)

from . import permisos
from .autorizacion import validar_alguno_de
from .exceptions import PrecondicionInvalidaError
from .permisos import Permiso

ORDEN_ROLES = (
    RolUsuario.ADMINISTRADOR,
    RolUsuario.COORDINADOR_RMA,
    RolUsuario.RECEPCION,
    RolUsuario.TECNICO,
)
CAMPO_ROLES = "roles"


def texto_roles(roles: Iterable[RolUsuario]) -> str | None:
    """Los roles como texto estable para la auditoria (``None`` si ninguno)."""
    presentes = set(roles)
    return ", ".join(r.value for r in ORDEN_ROLES if r in presentes) or None


def roles_para(
    usuario: Usuario, pedidos: Collection[RolUsuario]
) -> tuple[RolUsuario, ...]:
    """Los roles pedidos, con el principal actual primero si lo conserva."""
    nuevos = tuple(dict.fromkeys(pedidos))
    if usuario.rol in nuevos:
        nuevos = (usuario.rol, *(r for r in nuevos if r is not usuario.rol))
    return nuevos


def cambio_de_roles(
    destino: Usuario,
    pedidos: Collection[RolUsuario],
    *,
    usuarios: Iterable[Usuario],
    usuario: Usuario,
    fecha: datetime,
) -> tuple[tuple[RolUsuario, ...], CambioConfiguracion]:
    """Los roles nuevos de ``destino`` y su auditoria."""
    validar_alguno_de(usuario, permisos.ROLES_ADMINISTRAR)
    nuevos = roles_para(destino, pedidos)
    if not nuevos:
        raise PrecondicionInvalidaError(
            f"El usuario {destino.id} necesita al menos un rol."
        )
    if set(nuevos) == set(destino.roles):
        raise PrecondicionInvalidaError(
            f"El usuario {destino.id} ya tiene esos roles: no hay cambios."
        )
    administradores = [
        u
        for u in usuarios
        if u.activo
        and RolUsuario.ADMINISTRADOR
        in (nuevos if u.id == destino.id else u.roles)
    ]
    if not administradores:
        raise PrecondicionInvalidaError(
            "El cambio dejaria el sistema sin un Administrador activo."
        )
    return nuevos, CambioConfiguracion(
        entidad=EntidadConfiguracion.USUARIO,
        clave=destino.id,
        campo=CAMPO_ROLES,
        valor_anterior=texto_roles(destino.roles),
        valor_nuevo=texto_roles(nuevos),
        usuario_id=usuario.id,
        fecha=fecha,
    )


def cambio_de_permiso(
    permiso: Permiso,
    pedidos: Collection[RolUsuario],
    *,
    usuario: Usuario,
    fecha: datetime,
) -> tuple[tuple[RolUsuario, ...], CambioConfiguracion]:
    """Los roles nuevos de ``permiso`` y su auditoria."""
    validar_alguno_de(usuario, permisos.ROLES_ADMINISTRAR)
    if not permiso.configurable:
        raise PrecondicionInvalidaError(
            f"El permiso {permiso.codigo} no se configura: es de "
            "Administracion."
        )
    presentes = set(pedidos)
    nuevos = tuple(r for r in ORDEN_ROLES if r in presentes)
    if set(nuevos) == set(permiso.roles):
        raise PrecondicionInvalidaError(
            f"El permiso {permiso.codigo} ya tiene esos roles: no hay cambios."
        )
    return nuevos, CambioConfiguracion(
        entidad=EntidadConfiguracion.PERMISO,
        clave=permiso.codigo,
        campo=CAMPO_ROLES,
        valor_anterior=texto_roles(permiso.roles) or "(ninguno)",
        valor_nuevo=texto_roles(nuevos) or "(ninguno)",
        usuario_id=usuario.id,
        fecha=fecha,
    )


def permisos_de(usuario: Usuario) -> list[str]:
    """Los codigos de permiso que el usuario tiene hoy (union de roles)."""
    return [
        codigo
        for codigo, permiso in permisos.REGISTRO.items()
        if usuario.activo and usuario.tiene_alguno(permiso.roles)
    ]
