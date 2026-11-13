"""Personas del dominio: cliente externo y usuario operativo."""

from typing import Any

from pydantic import BaseModel, model_serializer, model_validator

from .enums import RolUsuario


class Cliente(BaseModel):
    """Cliente externo que deja un equipo para reparar.

    ``id`` es el identificador interno (nunca el DNI): se conserva entre
    las Ordenes del mismo cliente. ``dni`` (solo digitos, 7 u 8; opcional)
    permite reconocer a un cliente que ya vino. ``nombre_apellido`` es el
    nombre completo exactamente como lo cargo Recepcion o lo devolvio una
    fuente autorizada: no se separa en nombre y apellido.

    Compatibilidad de lectura: las Ordenes y los documentos anteriores
    guardaron el nombre completo en ``nombre`` y se leen tal cual en
    ``nombre_apellido``, sin migrar los archivos (al volver a guardar una
    Orden se escribe con la clave nueva; el texto no cambia).
    """

    id: str
    dni: str | None = None
    nombre_apellido: str
    telefono: str
    email: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _desde_estructura_anterior(cls, datos: Any) -> Any:
        """``nombre`` (estructura anterior) -> ``nombre_apellido``."""
        if (
            isinstance(datos, dict)
            and "nombre_apellido" not in datos
            and "nombre" in datos
        ):
            datos = dict(datos)
            datos["nombre_apellido"] = datos.pop("nombre")
        return datos


class Usuario(BaseModel):
    """Usuario operativo de RMA.

    Varios roles por usuario (DC27A, DEC-MI-12): ``roles`` son todos los
    roles asignados y sus permisos se suman (siempre sujetos a las
    restricciones de contexto de cada regla). ``rol`` es el rol principal,
    el primero de ``roles``: lo usan las pantallas que muestran un solo rol
    y los datos anteriores, que solo traen ``rol`` (se leen como un usuario
    con ese unico rol, sin migrar nada).
    """

    id: str
    nombre: str
    rol: RolUsuario
    roles: tuple[RolUsuario, ...] = ()
    activo: bool = True

    @model_validator(mode="before")
    @classmethod
    def _rol_y_roles(cls, datos: Any) -> Any:
        if not isinstance(datos, dict):
            return datos
        datos = dict(datos)
        roles = list(datos.get("roles") or ())
        rol = datos.get("rol")
        if rol is None and roles:
            datos["rol"] = roles[0]
        elif rol is not None and not roles:
            datos["roles"] = [rol]
        return datos

    @model_validator(mode="after")
    def _principal_entre_los_roles(self) -> "Usuario":
        roles = tuple(dict.fromkeys(self.roles))
        if self.rol not in roles:
            roles = (self.rol, *roles)
        if roles != self.roles:
            object.__setattr__(self, "roles", roles)
        return self

    @model_serializer(mode="wrap")
    def _sin_roles_si_es_uno(self, handler):
        """Un usuario de un solo rol se guarda como siempre (solo ``rol``):
        los catalogos JSON existentes no cambian de forma."""
        datos = handler(self)
        if isinstance(datos, dict) and len(self.roles) <= 1:
            datos.pop("roles", None)
        return datos

    def tiene_rol(self, rol: RolUsuario) -> bool:
        return rol in self.roles

    def tiene_alguno(self, roles) -> bool:
        return any(rol in self.roles for rol in roles)

    def rol_habilitante(self, roles) -> RolUsuario | None:
        """El primero de sus roles que habilita la accion (o ``None``)."""
        permitidos = tuple(roles)
        return next((r for r in self.roles if r in permitidos), None)
