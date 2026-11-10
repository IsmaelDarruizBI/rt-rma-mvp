"""Autenticacion y autorizacion de la API.

Con ``RMA_AUTH_MODO=supabase`` todo endpoint, salvo ``/health``, exige
``Authorization: Bearer <token de Supabase Auth>``:

- **401** sin token, con un token invalido o vencido;
- **403** si la identidad no esta vinculada a un usuario de RMA
  (``rma.usuario.auth_user_id``), si el usuario esta inactivo, si el
  ``usuario_id`` que llega en la consulta o en el cuerpo no es el del
  token (no se acepta actuar en nombre de otro), o si su rol no puede usar
  una ruta administrativa (``exigir_rol``).

Las reglas de negocio no cambian: los casos de uso siguen recibiendo el
``usuario_id`` y validando rol, titular y estado como siempre. Lo nuevo
es que ese ``usuario_id`` ahora esta probado. Como el alcance de las
claves de idempotencia es ``(usuario_id, clave)``, cada identidad tiene
sus propias claves.

Con ``RMA_AUTH_MODO=demo`` (desarrollo local y tests) nada de esto se
aplica: la API se comporta como antes.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.core.autenticacion import (
    AutenticacionNoDisponibleError,
    TokenInvalidoError,
    VerificadorDeTokens,
)
from app.domain.models import RolUsuario, Usuario

from .dependencias import ContextoDep
from .schemas import UsuarioOut


class AccesoDenegadoError(Exception):
    """Autenticado, pero sin permiso para este pedido (403)."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


class Autenticacion:
    """Lo que la app necesita para identificar a quien llama."""

    def __init__(self, verificador: VerificadorDeTokens | None) -> None:
        self.verificador = verificador

    @property
    def activa(self) -> bool:
        return self.verificador is not None


def _usuario_del_token(request: Request, contexto) -> Usuario | None:
    autenticacion: Autenticacion = request.app.state.autenticacion
    if not autenticacion.activa:
        return None
    if hasattr(request.state, "usuario"):
        return request.state.usuario
    encabezado = request.headers.get("authorization", "")
    esquema, _, token = encabezado.partition(" ")
    if esquema.lower() != "bearer" or not token.strip():
        raise TokenInvalidoError("Falta iniciar sesion.")
    identidad = autenticacion.verificador.identidad(token.strip())
    # Sin memoria entre pedidos: desactivar a alguien o cambiarle el rol en
    # la base vale desde el pedido siguiente (el token se verifica local).
    usuario = contexto.catalogos.obtener_usuario_por_identidad(identidad)
    if usuario is None:
        raise AccesoDenegadoError(
            "USUARIO_NO_HABILITADO",
            "La cuenta no esta habilitada en RMA. Pedile acceso a "
            "Administracion.",
        )
    if not usuario.activo:
        raise AccesoDenegadoError(
            "USUARIO_INACTIVO", "La cuenta esta inactiva en RMA."
        )
    request.state.usuario = usuario
    return usuario


async def _usuarios_declarados(request: Request) -> list[str]:
    """Los ``usuario_id`` que el pedido dice traer (consulta y cuerpo)."""
    declarados = request.query_params.getlist("usuario_id")
    tipo = request.headers.get("content-type", "")
    if request.method in ("POST", "PUT", "PATCH") and tipo.startswith(
        "application/json"
    ):
        try:
            cuerpo: Any = json.loads(await request.body() or b"null")
        except ValueError:
            cuerpo = None  # FastAPI responde 422 al validar el cuerpo.
        if isinstance(cuerpo, dict) and "usuario_id" in cuerpo:
            declarados.append(cuerpo["usuario_id"])
    return declarados


async def exigir_identidad(request: Request, contexto: ContextoDep) -> None:
    """Dependencia de todos los routers (salvo ``/health``).

    La busqueda del usuario puede ir a la base: corre en el pool de hilos
    para no bloquear el bucle de eventos."""
    usuario = await run_in_threadpool(_usuario_del_token, request, contexto)
    if usuario is None:
        return
    for declarado in await _usuarios_declarados(request):
        if declarado != usuario.id:
            raise AccesoDenegadoError(
                "IDENTIDAD_NO_COINCIDE",
                "El pedido indica otro usuario que el de la sesion.",
            )


def exigir_rol(roles: Sequence[RolUsuario]):
    """Ruta administrativa: con sesion real, solo esos roles (403).

    Son los mismos roles que ya valida el caso de uso; aca se corta antes,
    sin ejecutar nada. En modo ``demo`` no hace nada.
    """
    permitidos = tuple(roles)

    def dependencia(request: Request, contexto: ContextoDep) -> None:
        usuario = _usuario_del_token(request, contexto)
        if usuario is not None and usuario.rol not in permitidos:
            raise AccesoDenegadoError(
                "ROL_NO_AUTORIZADO",
                "Tu rol no puede usar esta funcion.",
            )

    return Depends(dependencia)


router = APIRouter(prefix="/api", tags=["sesion"])


@router.get("/me")
def get_me(request: Request, contexto: ContextoDep) -> UsuarioOut:
    """El usuario de RMA de la sesion actual."""
    usuario = _usuario_del_token(request, contexto)
    if usuario is None:
        raise AccesoDenegadoError(
            "AUTENTICACION_DEMO",
            "La API corre sin autenticacion (modo demo): no hay sesion.",
        )
    return UsuarioOut.model_validate(usuario.model_dump())


def registrar_manejadores_de_seguridad(application: FastAPI) -> None:
    def _respuesta(codigo: str, mensaje: str, estado: int, **extra):
        return JSONResponse(
            {"error": {"codigo": codigo, "mensaje": mensaje}},
            status_code=estado,
            **extra,
        )

    @application.exception_handler(TokenInvalidoError)
    async def _sin_sesion(_: Request, error: TokenInvalidoError):
        return _respuesta(
            "NO_AUTENTICADO",
            str(error),
            status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    @application.exception_handler(AccesoDenegadoError)
    async def _denegado(_: Request, error: AccesoDenegadoError):
        return _respuesta(error.codigo, str(error), status.HTTP_403_FORBIDDEN)

    @application.exception_handler(AutenticacionNoDisponibleError)
    async def _sin_claves(_: Request, error: AutenticacionNoDisponibleError):
        return _respuesta(
            "AUTENTICACION_NO_DISPONIBLE",
            str(error),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
