"""Roles de los usuarios y permisos configurables (DC27A, DC08; DEC-MI-12).

Solo Administracion, desde Configuracion, y sobre PostgreSQL (DC23: la
administracion vive en la persistencia definitiva). Cada comando guarda el
cambio y su auditoria en la misma transaccion. En el modo JSON se consulta
(los roles del catalogo y los permisos predeterminados) pero no se cambia.
"""

from collections.abc import Collection
from dataclasses import dataclass

from app.domain.models import RolUsuario, Usuario
from app.services import permisos
from app.services.exceptions import EntidadNoEncontradaError
from app.services.roles import cambio_de_permiso, cambio_de_roles

from .configuracion import _repositorio
from .contexto import ApplicationContext


@dataclass(frozen=True)
class VistaPermiso:
    codigo: str
    descripcion: str
    grupo: str
    consulta: bool
    configurable: bool
    predeterminados: tuple[RolUsuario, ...]
    vigentes: tuple[RolUsuario, ...]
    # CFG-03: los permisos de consulta que la accion necesita.
    requiere: tuple[str, ...] = ()


def _vista(permiso: permisos.Permiso) -> VistaPermiso:
    return VistaPermiso(
        codigo=permiso.codigo,
        descripcion=permiso.descripcion,
        grupo=permiso.grupo,
        consulta=permiso.consulta,
        configurable=permiso.configurable,
        predeterminados=permiso.predeterminados,
        vigentes=permiso.roles,
        requiere=permiso.requiere,
    )


def listar_usuarios_con_roles(contexto: ApplicationContext) -> list[Usuario]:
    with contexto.lectura():
        return list(contexto.catalogos.listar_usuarios())


def listar_permisos(contexto: ApplicationContext) -> list[VistaPermiso]:
    """Todos los permisos, con sus predeterminados y los roles de hoy."""
    return [_vista(p) for p in permisos.REGISTRO.values()]


def asignar_roles(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    destino_id: str,
    roles: Collection[RolUsuario],
) -> Usuario:
    repositorio = _repositorio(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with contexto.transaccion():
        usuarios = contexto.catalogos.listar_usuarios()
        destino = next((u for u in usuarios if u.id == destino_id), None)
        if destino is None:
            raise EntidadNoEncontradaError(
                f"No existe el usuario {destino_id}"
            )
        nuevos, cambio = cambio_de_roles(
            destino, roles, usuarios=usuarios, usuario=usuario, fecha=fecha
        )
        repositorio.guardar_roles_de_usuario(destino.id, nuevos, cambio)
    return destino.model_copy(update={"rol": nuevos[0], "roles": nuevos})


def configurar_permiso(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    codigo: str,
    roles: Collection[RolUsuario],
) -> VistaPermiso:
    repositorio = _repositorio(contexto)
    permiso = permisos.REGISTRO.get(codigo)
    if permiso is None:
        raise EntidadNoEncontradaError(f"No existe el permiso {codigo}")
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with contexto.transaccion():
        nuevos, cambio = cambio_de_permiso(
            permiso, roles, usuario=usuario, fecha=fecha
        )
        repositorio.guardar_permiso(permiso.codigo, nuevos, cambio)
    vista = _vista(permiso)
    return VistaPermiso(**{**vista.__dict__, "vigentes": nuevos})
