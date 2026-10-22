"""Credenciales de Google para leer el catalogo, sin claves JSON.

Cada credencial es un callable que devuelve un token de acceso de corta
vida, siempre con alcance de SOLO LECTURA de Sheets:

    CredencialCloudRun    la cuenta de servicio con la que corre el
                          servicio (servidor de metadatos). Requiere la
                          planilla compartida, como Lector, con esa cuenta.
    CredencialImpersonada OTRA cuenta de servicio (la que tiene la planilla
                          compartida): IAM Credentials emite su token con
                          la identidad base. Requiere
                          roles/iam.serviceAccountTokenCreator de la base
                          sobre esa cuenta.
    CredencialGcloud      solo desarrollo local: gcloud CLI con las
                          credenciales del desarrollador, impersonando la
                          cuenta de servicio.

Los tokens nunca se registran ni se incluyen en un mensaje de error.
"""

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from .puerto import CatalogoOrigenNoDisponibleError

ALCANCE_SHEETS_LECTURA = (
    "https://www.googleapis.com/auth/spreadsheets.readonly"
)
ALCANCE_CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"
URL_TOKEN_METADATA = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)
URL_GENERAR_TOKEN = (
    "https://iamcredentials.googleapis.com/v1/projects/-/"
    "serviceAccounts/{cuenta}:generateAccessToken"
)
# Se renueva un minuto antes de vencer.
_MARGEN_S = 60

Credencial = Callable[[], str]
Abrir = Callable[..., Any]


class _Cache:
    def __init__(self, reloj: Callable[[], float]) -> None:
        self._reloj = reloj
        self._token: str | None = None
        self._vence = 0.0

    def vigente(self) -> str | None:
        if self._token and self._reloj() < self._vence - _MARGEN_S:
            return self._token
        return None

    def guardar(self, token: str, segundos: float) -> str:
        self._token = token
        self._vence = self._reloj() + segundos
        return token


class CredencialCloudRun:
    """Token de la cuenta de servicio del servicio de Cloud Run."""

    def __init__(
        self,
        alcances: Sequence[str] = (ALCANCE_SHEETS_LECTURA,),
        *,
        abrir: Abrir = urllib.request.urlopen,
        reloj: Callable[[], float] = time.monotonic,
        timeout: float = 10.0,
    ) -> None:
        self._alcances = tuple(alcances)
        self._abrir = abrir
        self._timeout = timeout
        self._cache = _Cache(reloj)

    def __call__(self) -> str:
        vigente = self._cache.vigente()
        if vigente:
            return vigente
        pedido = urllib.request.Request(
            f"{URL_TOKEN_METADATA}?scopes={quote(','.join(self._alcances))}",
            headers={"Metadata-Flavor": "Google"},
        )
        try:
            with self._abrir(pedido, timeout=self._timeout) as respuesta:
                datos = json.load(respuesta)
            token = datos["access_token"]
            segundos = float(datos.get("expires_in", 300))
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CatalogoOrigenNoDisponibleError(
                "No se pudo obtener la credencial de la cuenta de servicio "
                "(servidor de metadatos de Cloud Run)."
            ) from error
        return self._cache.guardar(token, segundos)


class CredencialImpersonada:
    """Token de ``cuenta`` emitido por IAM Credentials."""

    def __init__(
        self,
        cuenta: str,
        base: Credencial,
        alcances: Sequence[str] = (ALCANCE_SHEETS_LECTURA,),
        *,
        abrir: Abrir = urllib.request.urlopen,
        reloj: Callable[[], float] = time.monotonic,
        duracion_s: int = 600,
        timeout: float = 15.0,
    ) -> None:
        self._cuenta = cuenta
        self._base = base
        self._alcances = list(alcances)
        self._abrir = abrir
        self._duracion = duracion_s
        self._timeout = timeout
        self._cache = _Cache(reloj)

    def __call__(self) -> str:
        vigente = self._cache.vigente()
        if vigente:
            return vigente
        pedido = urllib.request.Request(
            URL_GENERAR_TOKEN.format(cuenta=quote(self._cuenta, safe="@.")),
            data=json.dumps(
                {"scope": self._alcances, "lifetime": f"{self._duracion}s"}
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._base()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._abrir(pedido, timeout=self._timeout) as respuesta:
                datos = json.load(respuesta)
            token = datos["accessToken"]
        except urllib.error.HTTPError as error:
            raise CatalogoOrigenNoDisponibleError(
                "La identidad del servicio no puede emitir credenciales de "
                f"la cuenta de lectura del catálogo (HTTP {error.code})."
            ) from error
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CatalogoOrigenNoDisponibleError(
                "No se pudo obtener la credencial de la cuenta de lectura "
                "del catálogo."
            ) from error
        return self._cache.guardar(token, _segundos_hasta(datos))


def _segundos_hasta(datos: dict[str, Any]) -> float:
    try:
        vence = datetime.fromisoformat(
            str(datos["expireTime"]).replace("Z", "+00:00")
        )
        return max(0.0, (vence - datetime.now(timezone.utc)).total_seconds())
    except (KeyError, ValueError):
        return 300.0


class CredencialGcloud:
    """Solo desarrollo local: ``gcloud auth print-access-token``."""

    def __init__(
        self,
        cuenta: str,
        alcances: Sequence[str] = (ALCANCE_SHEETS_LECTURA,),
        *,
        ejecutar: Callable[..., Any] = subprocess.run,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cuenta = cuenta
        self._alcances = tuple(alcances)
        self._ejecutar = ejecutar
        self._cache = _Cache(reloj)

    def __call__(self) -> str:
        vigente = self._cache.vigente()
        if vigente:
            return vigente
        gcloud = shutil.which("gcloud") or "gcloud"
        try:
            resultado = self._ejecutar(
                [
                    gcloud,
                    "auth",
                    "print-access-token",
                    f"--impersonate-service-account={self._cuenta}",
                    f"--scopes={','.join(self._alcances)}",
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise CatalogoOrigenNoDisponibleError(
                "No se pudo ejecutar gcloud para obtener la credencial."
            ) from error
        token = (resultado.stdout or "").strip()
        if resultado.returncode != 0 or not token:
            raise CatalogoOrigenNoDisponibleError(
                "gcloud no pudo emitir la credencial de la cuenta de "
                "lectura del catálogo (¿falta iniciar sesión o el permiso "
                "para impersonarla?)."
            )
        # gcloud no informa el vencimiento: los tokens duran una hora.
        return self._cache.guardar(token, 3000)
