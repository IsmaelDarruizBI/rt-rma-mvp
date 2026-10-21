"""Almacenamiento de las fotos del equipo (MVP v2, UAT-010).

Las imagenes no van al JSON de la Orden ni al disco efimero de Cloud Run.
Hay tres implementaciones del mismo contrato (``AlmacenFotos``):

- ``AlmacenFotosGcs``: un bucket PRIVADO de Google Cloud Storage. Usa la
  API JSON de Cloud Storage con el token de la cuenta de servicio que da
  el servidor de metadatos de Cloud Run (sin dependencias extra). El
  backend sube y sirve cada imagen: el bucket nunca se expone.
- ``AlmacenFotosDirectorio``: un directorio local, SOLO para desarrollo.
- ``AlmacenFotosMemoria``: para los tests.

Sin almacenamiento configurado, las fotos quedan deshabilitadas.

``listar`` y ``eliminar`` sirven solo a la limpieza de imagenes huerfanas
(``application.fotos.limpiar_fotos_huerfanas``): en el UAT las Ordenes
viven en JSON efimero y un redespliegue las borra, pero el bucket no.
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


class AlmacenFotosError(Exception):
    """El almacenamiento no respondio o rechazo la operacion."""


@dataclass(frozen=True)
class ObjetoFoto:
    """Una imagen guardada: su clave y cuando se escribio (UTC)."""

    clave: str
    actualizado: datetime


class AlmacenFotos(Protocol):
    """Guarda y devuelve imagenes por clave (``ordenes/<orden>/<foto>``)."""

    def guardar(self, clave: str, contenido: bytes, tipo: str) -> None: ...

    def obtener(self, clave: str) -> bytes: ...

    def listar(self, prefijo: str) -> list[ObjetoFoto]: ...

    def eliminar(self, clave: str) -> None: ...


def _exigir_clave_valida(clave: str) -> None:
    partes = clave.split("/")
    if not clave or any(parte in ("", ".", "..") for parte in partes):
        raise AlmacenFotosError(f"Clave de foto invalida: {clave!r}")


class AlmacenFotosMemoria:
    """En memoria del proceso: solo para tests."""

    def __init__(self) -> None:
        self.objetos: dict[str, tuple[bytes, str]] = {}
        self.fechas: dict[str, datetime] = {}

    def guardar(self, clave: str, contenido: bytes, tipo: str) -> None:
        _exigir_clave_valida(clave)
        self.objetos[clave] = (contenido, tipo)
        self.fechas[clave] = datetime.now(timezone.utc)

    def obtener(self, clave: str) -> bytes:
        try:
            return self.objetos[clave][0]
        except KeyError as error:
            raise AlmacenFotosError(f"No existe la foto {clave}") from error

    def listar(self, prefijo: str) -> list[ObjetoFoto]:
        return [
            ObjetoFoto(clave, self.fechas[clave])
            for clave in sorted(self.objetos)
            if clave.startswith(prefijo)
        ]

    def eliminar(self, clave: str) -> None:
        self.objetos.pop(clave, None)
        self.fechas.pop(clave, None)


class AlmacenFotosDirectorio:
    """Un directorio local. SOLO desarrollo: en Cloud Run el disco es
    efimero y se pierde con cada revision."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = Path(raiz)

    def _ruta(self, clave: str) -> Path:
        _exigir_clave_valida(clave)
        return self.raiz.joinpath(*clave.split("/"))

    def guardar(self, clave: str, contenido: bytes, tipo: str) -> None:
        ruta = self._ruta(clave)
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(contenido)
        except OSError as error:
            raise AlmacenFotosError(f"No se pudo guardar {clave}") from error

    def obtener(self, clave: str) -> bytes:
        try:
            return self._ruta(clave).read_bytes()
        except OSError as error:
            raise AlmacenFotosError(f"No existe la foto {clave}") from error

    def listar(self, prefijo: str) -> list[ObjetoFoto]:
        if not self.raiz.exists():
            return []
        objetos = []
        for ruta in sorted(self.raiz.rglob("*")):
            if not ruta.is_file():
                continue
            clave = ruta.relative_to(self.raiz).as_posix()
            if clave.startswith(prefijo):
                fecha = datetime.fromtimestamp(
                    ruta.stat().st_mtime, timezone.utc
                )
                objetos.append(ObjetoFoto(clave, fecha))
        return objetos

    def eliminar(self, clave: str) -> None:
        try:
            self._ruta(clave).unlink(missing_ok=True)
        except OSError as error:
            raise AlmacenFotosError(f"No se pudo eliminar {clave}") from error


_METADATA_TOKEN = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)
_SUBIDA = "https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
_OBJETO = "https://storage.googleapis.com/storage/v1/b/{bucket}/o/{nombre}"
_LISTA = "https://storage.googleapis.com/storage/v1/b/{bucket}/o"

Abrir = Callable[..., object]


class AlmacenFotosGcs:
    """Bucket privado de Google Cloud Storage (API JSON).

    El token lo da el servidor de metadatos de Cloud Run para la cuenta de
    servicio del servicio; se reutiliza hasta un minuto antes de vencer.
    Subir usa ``ifGenerationMatch=0``: una foto nunca pisa a otra.
    ``abrir`` permite reemplazar ``urlopen`` en los tests.
    """

    def __init__(
        self,
        bucket: str,
        *,
        abrir: Abrir = urllib.request.urlopen,
        timeout: float = 20.0,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        if not bucket:
            raise ValueError("Falta el nombre del bucket de fotos.")
        self.bucket = bucket
        self._abrir = abrir
        self._timeout = timeout
        self._reloj = reloj
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    def _access_token(self) -> str:
        with self._lock:
            ahora = self._reloj()
            if self._token and self._token[1] > ahora:
                return self._token[0]
            pedido = urllib.request.Request(
                _METADATA_TOKEN, headers={"Metadata-Flavor": "Google"}
            )
            datos = self._leer_json(pedido)
            token = datos["access_token"]
            vence = ahora + max(int(datos.get("expires_in", 0)) - 60, 0)
            self._token = (token, vence)
            return token

    def _leer(self, pedido: urllib.request.Request) -> bytes:
        try:
            with self._abrir(pedido, timeout=self._timeout) as respuesta:
                return respuesta.read()
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise AlmacenFotosError(
                f"Cloud Storage no respondio ({type(error).__name__})."
            ) from error

    def _leer_json(self, pedido: urllib.request.Request) -> dict:
        try:
            return json.loads(self._leer(pedido))
        except (json.JSONDecodeError, KeyError) as error:
            raise AlmacenFotosError("Respuesta inesperada.") from error

    def guardar(self, clave: str, contenido: bytes, tipo: str) -> None:
        _exigir_clave_valida(clave)
        consulta = urllib.parse.urlencode(
            {"uploadType": "media", "name": clave, "ifGenerationMatch": "0"}
        )
        pedido = urllib.request.Request(
            f"{_SUBIDA.format(bucket=self.bucket)}?{consulta}",
            data=contenido,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": tipo,
            },
        )
        self._leer(pedido)

    def obtener(self, clave: str) -> bytes:
        _exigir_clave_valida(clave)
        nombre = urllib.parse.quote(clave, safe="")
        pedido = urllib.request.Request(
            f"{_OBJETO.format(bucket=self.bucket, nombre=nombre)}?alt=media",
            headers={"Authorization": f"Bearer {self._access_token()}"},
        )
        return self._leer(pedido)

    def listar(self, prefijo: str) -> list[ObjetoFoto]:
        """Las imagenes bajo ``prefijo``, pagina por pagina."""
        objetos: list[ObjetoFoto] = []
        pagina: str | None = None
        while True:
            parametros = {
                "prefix": prefijo,
                "fields": "items(name,updated),nextPageToken",
            }
            if pagina:
                parametros["pageToken"] = pagina
            consulta = urllib.parse.urlencode(parametros)
            pedido = urllib.request.Request(
                f"{_LISTA.format(bucket=self.bucket)}?{consulta}",
                headers={"Authorization": f"Bearer {self._access_token()}"},
            )
            datos = self._leer_json(pedido)
            for item in datos.get("items", []):
                actualizado = datetime.fromisoformat(
                    item["updated"].replace("Z", "+00:00")
                )
                objetos.append(ObjetoFoto(item["name"], actualizado))
            pagina = datos.get("nextPageToken")
            if not pagina:
                return objetos

    def eliminar(self, clave: str) -> None:
        _exigir_clave_valida(clave)
        nombre = urllib.parse.quote(clave, safe="")
        pedido = urllib.request.Request(
            _OBJETO.format(bucket=self.bucket, nombre=nombre),
            method="DELETE",
            headers={"Authorization": f"Bearer {self._access_token()}"},
        )
        self._leer(pedido)
