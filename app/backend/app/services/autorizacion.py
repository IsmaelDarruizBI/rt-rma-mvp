"""Autorizacion funcional de los casos de uso.

PROC-REP V1.3 asigna un actor a cada nodo. Cuando ese actor es una
persona concreta (ACT-RECEP, ACT-COORD, ACT-TECH, ACT-ADMIN), quien
ejecuta la operacion debe tener ese rol: es una regla del caso de uso,
no algo que deba quedar librado a que la UI esconda un boton.

Esto NO es autenticacion ni un sistema de permisos. No hay ACLs, scopes
ni permisos dinamicos: solo se comprueba que el usuario este activo y
que su rol sea el que el nodo requiere.

Los nodos ACT-SYSTEM no llevan actor humano. Cuando una operacion
automatica necesita saber quien es el tecnico, lo obtiene de la Toma o
de la Ejecucion existente, no de un usuario inventado.

Correspondencia con ``business/actors/actors.yaml``:

    ACT-RECEP  -> RolUsuario.RECEPCION
    ACT-COORD  -> RolUsuario.COORDINADOR_RMA
    ACT-TECH   -> RolUsuario.TECNICO
    ACT-ADMIN  -> RolUsuario.ADMINISTRADOR

Un nodo puede declarar ``actores_alternativos``: varios actores
igualmente autorizados, sin jerarquia. Para esos casos se usa
``validar_alguno_de``.
"""

from collections.abc import Iterable

from app.domain.models import RolUsuario, Usuario

from .exceptions import PrecondicionInvalidaError
from .permisos import Permiso, anotar_rol_habilitante


def _roles(
    autorizados: RolUsuario | Iterable[RolUsuario],
) -> tuple[RolUsuario, ...]:
    if isinstance(autorizados, RolUsuario):
        return (autorizados,)
    return tuple(autorizados)


def actor_valido(
    usuario: Usuario, rol_requerido: RolUsuario | Permiso
) -> bool:
    """True si el usuario esta activo y tiene un rol que lo habilita.

    Version no excepcional, para los nodos de validacion que devuelven
    un resultado en vez de interrumpir el flujo (PROC-REP-172).
    """
    return usuario.activo and usuario.tiene_alguno(_roles(rol_requerido))


def validar_actor(
    usuario: Usuario, rol_requerido: RolUsuario | Permiso
) -> None:
    """Exige que el usuario pueda actuar como el actor del nodo.

    Falla si esta inactivo o si ninguno de sus roles lo habilita.
    """
    validar_alguno_de(usuario, _roles(rol_requerido))


def validar_alguno_de(
    usuario: Usuario,
    roles_autorizados: Iterable[RolUsuario] | Permiso,
) -> RolUsuario:
    """Exige que el usuario tenga ALGUNO de los roles que habilitan la accion.

    ``roles_autorizados`` es un ``Permiso`` (configurable, DC08) o una
    tupla fija. Con varios roles (DC27A) alcanza con uno; el primero que
    habilita queda anotado como rol habilitante de la accion y se registra
    en el historial. Devuelve ese rol.
    """
    if not usuario.activo:
        raise PrecondicionInvalidaError(
            f"El usuario {usuario.id} no esta activo."
        )
    permitidos = _roles(roles_autorizados)
    rol = usuario.rol_habilitante(permitidos)
    if rol is None:
        esperados = " o ".join(r.value for r in permitidos) or "ninguno"
        propios = ", ".join(r.value for r in usuario.roles)
        raise PrecondicionInvalidaError(
            f"La operacion requiere el rol {esperados}; "
            f"el usuario {usuario.id} es {propios}."
        )
    anotar_rol_habilitante(usuario.id, rol)
    return rol


def validar_usuario_activo(usuario: Usuario) -> None:
    """Exige unicamente que el usuario este activo.

    Se usa en los nodos ACT-SYSTEM que igualmente registran quien
    disparo la operacion, y en las capacidades transversales cuyo rol
    autorizado todavia no esta definido funcionalmente (por ejemplo
    Registrar Pago, BR-REP-017).
    """
    if not usuario.activo:
        raise PrecondicionInvalidaError(
            f"El usuario {usuario.id} no esta activo."
        )
