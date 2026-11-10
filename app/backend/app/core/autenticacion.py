"""Verificacion local de los tokens de Supabase Auth.

Supabase Auth autentica (email y contrasena); FastAPI autoriza con los
roles de PostgreSQL (decision G-5). Este modulo solo responde "quien es":
verifica el JWT con las claves PUBLICAS del proyecto (JWKS), sin llamar a
Supabase en cada pedido, y devuelve su ``sub``, que es el
``rma.usuario.auth_user_id`` de la persona.

Se exige:

- firma con un algoritmo asimetrico permitido (por defecto ``ES256``, el
  del proyecto). ``HS*`` y ``none`` se rechazan siempre: el backend no
  tiene ningun secreto compartido;
- ``iss`` = ``<proyecto>/auth/v1``, ``aud`` = ``authenticated``;
- ``exp``, ``iat`` y ``sub`` presentes, y ``role`` = ``authenticated``
  (la clave publica ``anon`` tambien es un JWT valido del proyecto, pero
  no identifica a nadie).

Las claves se descargan una vez y se guardan en memoria; una clave nueva
(rotacion) se busca de nuevo por su ``kid``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt

from app.core.config import Settings

ALGORITMOS_ASIMETRICOS = frozenset(
    {"ES256", "ES384", "ES512", "RS256", "RS384", "RS512", "EdDSA"}
)


class ConfiguracionAutenticacionError(RuntimeError):
    """La configuracion de autenticacion no permite arrancar con seguridad."""


class TokenInvalidoError(Exception):
    """El token falta, no es valido o vencio (401)."""


class AutenticacionNoDisponibleError(Exception):
    """No se pudieron obtener las claves publicas para verificar (503)."""


@dataclass(frozen=True)
class ParametrosToken:
    emisor: str
    audiencia: str
    algoritmos: tuple[str, ...]
    margen_reloj_s: int
    url_claves: str


def parametros_de(settings: Settings) -> ParametrosToken:
    """Traduce la configuracion y la valida (sin conectarse a nada)."""
    url = (settings.auth_supabase_url or "").rstrip("/")
    if not url:
        raise ConfiguracionAutenticacionError(
            "RMA_AUTH_MODO=supabase exige RMA_AUTH_SUPABASE_URL "
            "(https://<proyecto>.supabase.co)."
        )
    if not url.startswith("https://"):
        raise ConfiguracionAutenticacionError(
            "RMA_AUTH_SUPABASE_URL debe usar https."
        )
    algoritmos = tuple(settings.auth_algoritmos)
    if not algoritmos or not set(algoritmos) <= ALGORITMOS_ASIMETRICOS:
        raise ConfiguracionAutenticacionError(
            "RMA_AUTH_ALGORITMOS solo admite algoritmos asimetricos "
            f"({', '.join(sorted(ALGORITMOS_ASIMETRICOS))})."
        )
    return ParametrosToken(
        emisor=f"{url}/auth/v1",
        audiencia=settings.auth_audiencia,
        algoritmos=algoritmos,
        margen_reloj_s=settings.auth_margen_reloj_s,
        url_claves=f"{url}/auth/v1/.well-known/jwks.json",
    )


def exigir_modo_seguro(settings: Settings, entorno: dict[str, str]) -> None:
    """UAT y produccion nunca corren en modo ``demo``.

    Se reconocen por correr en Cloud Run (``K_SERVICE``) o por usar una
    base remota (``RMA_DB_REMOTO_HABILITADO``).
    """
    if settings.auth_modo == "supabase":
        parametros_de(settings)
        return
    if "K_SERVICE" in entorno or settings.db_remoto_habilitado:
        raise ConfiguracionAutenticacionError(
            "RMA_AUTH_MODO=demo es solo para desarrollo local y tests: en "
            "Cloud Run o con una base remota se exige RMA_AUTH_MODO=supabase."
        )


ObtenerClave = Callable[[str], Any]
"""Dado el token, devuelve la clave publica con que se firmo."""


def obtener_clave_jwks(url_claves: str) -> ObtenerClave:
    """Claves del JWKS, en memoria (con un ``kid`` nuevo se recargan)."""
    cliente = jwt.PyJWKClient(
        url_claves, cache_keys=True, lifespan=3600, timeout=10
    )

    def obtener(token: str) -> Any:
        try:
            return cliente.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientConnectionError as error:
            raise AutenticacionNoDisponibleError(
                "No se pudieron obtener las claves de Supabase Auth."
            ) from error
        except (jwt.PyJWKClientError, jwt.DecodeError) as error:
            raise TokenInvalidoError("El token no es valido.") from error

    return obtener


class VerificadorDeTokens:
    """Verifica un token y devuelve la identidad (``sub``)."""

    def __init__(
        self, parametros: ParametrosToken, obtener_clave: ObtenerClave
    ) -> None:
        self._parametros = parametros
        self._obtener_clave = obtener_clave

    def identidad(self, token: str) -> str:
        try:
            encabezado = jwt.get_unverified_header(token)
        except jwt.DecodeError as error:
            raise TokenInvalidoError("El token no es valido.") from error
        # El algoritmo se decide aca, nunca por lo que diga el token.
        if encabezado.get("alg") not in self._parametros.algoritmos:
            raise TokenInvalidoError("El token usa un algoritmo no admitido.")
        clave = self._obtener_clave(token)
        try:
            datos = jwt.decode(
                token,
                clave,
                algorithms=list(self._parametros.algoritmos),
                audience=self._parametros.audiencia,
                issuer=self._parametros.emisor,
                leeway=self._parametros.margen_reloj_s,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as error:
            raise TokenInvalidoError("La sesion vencio.") from error
        except jwt.InvalidTokenError as error:
            raise TokenInvalidoError("El token no es valido.") from error
        if datos.get("role") != "authenticated":
            raise TokenInvalidoError("El token no identifica a una persona.")
        sub = datos.get("sub")
        if not isinstance(sub, str) or not sub:
            raise TokenInvalidoError("El token no identifica a una persona.")
        return sub
