"""Personas del dominio: cliente externo y usuario operativo."""

from typing import Any

from pydantic import BaseModel, model_validator

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
    """Usuario operativo de RMA. Sin autenticacion en el MVP."""

    id: str
    nombre: str
    rol: RolUsuario
    activo: bool = True
