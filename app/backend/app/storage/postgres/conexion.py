"""Configuracion y apertura de conexiones a PostgreSQL.

Traduce ``Settings`` a los argumentos de ``psycopg.connect`` y rechaza
cualquier configuracion insegura antes de intentar conectar:

- la cadena sale de ``RMA_DATABASE_URL`` (en Cloud Run, de Secret
  Manager) y nunca aparece en mensajes, logs ni ``repr``;
- contra un servidor remoto el TLS es siempre ``verify-full``, con la CA
  de ``RMA_DB_SSLROOTCERT``: otro ``sslmode`` es un error, no se degrada;
- solo un servidor local (``localhost``) puede ir sin TLS: es la base
  descartable de las pruebas;
- sin sentencias preparadas del lado del servidor
  (``prepare_threshold=None``): el pooler de Supabase en modo
  transaccion no las admite.

psycopg es una dependencia opcional (``pip install '.[postgres]'``): se
importa recien al conectar, asi el modo JSON no la necesita.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import SecretStr

from app.core.config import Settings
from app.repositories.exceptions import PersistenciaError

if TYPE_CHECKING:
    import psycopg

ESQUEMAS_URL = frozenset({"postgresql", "postgres"})
HOSTS_LOCALES = frozenset({"localhost", "127.0.0.1", "::1"})
SSLMODES_LIBPQ = frozenset(
    {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
)
SEGUNDOS_PARA_CONECTAR = 10
NOMBRE_APLICACION = "rt-rma-api"
# libpq tambien toma el servidor de la query (``host``, ``hostaddr``) o de
# un archivo de servicios (``service``), y esos valores reemplazan al host
# de la URL. Se rechazan: el host que se valida tiene que ser el unico al
# que se conecta.
PARAMETROS_DE_DESTINO = ("host", "hostaddr", "service")

_CABECERA_PEM = b"-----BEGIN CERTIFICATE-----"
_URL_EN_TEXTO = re.compile(r"postgres(?:ql)?://\S+")
_PASSWORD_EN_TEXTO = re.compile(r"password\s*=\s*\S+", re.IGNORECASE)


class ConfiguracionPersistenciaError(Exception):
    """La persistencia elegida no tiene una configuracion utilizable.

    Se lanza al arrancar: la aplicacion no queda levantada a medias. El
    mensaje nombra la variable a corregir y nunca incluye la cadena de
    conexion.
    """


@dataclass(frozen=True)
class ConfiguracionPostgres:
    """Conexion validada. ``conninfo`` queda oculta en ``repr``."""

    conninfo: SecretStr
    sslmode: str
    sslrootcert: Path | None

    def argumentos_conexion(self) -> dict[str, object]:
        """Argumentos para ``psycopg.connect`` (y, mas adelante, el pool)."""
        argumentos: dict[str, object] = {
            "sslmode": self.sslmode,
            "prepare_threshold": None,
            "connect_timeout": SEGUNDOS_PARA_CONECTAR,
            "application_name": NOMBRE_APLICACION,
        }
        if self.sslrootcert is not None:
            argumentos["sslrootcert"] = str(self.sslrootcert)
        return argumentos

    def sin_secretos(self, texto: str) -> str:
        """Quita de ``texto`` la cadena de conexion y la contrasena."""
        url = self.conninfo.get_secret_value()
        ocultos = [url]
        try:
            password = urlsplit(url).password
        except ValueError:
            password = None
        if password:
            ocultos += [password, unquote(password)]
        for valor in ocultos:
            texto = texto.replace(valor, "<oculto>")
        texto = _URL_EN_TEXTO.sub("<oculto>", texto)
        return _PASSWORD_EN_TEXTO.sub("password=<oculto>", texto)


def configuracion_postgres(settings: Settings) -> ConfiguracionPostgres:
    """Valida ``RMA_DATABASE_URL`` y el TLS; no abre ninguna conexion."""
    secreto = settings.database_url
    url = secreto.get_secret_value().strip() if secreto else ""
    if not url:
        raise ConfiguracionPersistenciaError(
            "RMA_PERSISTENCIA=postgres requiere RMA_DATABASE_URL."
        )
    try:
        host = servidor_unico(url)
    except ValueError as error:
        raise ConfiguracionPersistenciaError(
            f"RMA_DATABASE_URL {error}"
        ) from None
    parametros = parse_qs(urlsplit(url).query, keep_blank_values=True)
    sslmodes = parametros.get("sslmode", [])
    if len(sslmodes) > 1:
        raise ConfiguracionPersistenciaError(
            "RMA_DATABASE_URL repite el parametro sslmode."
        )
    sslmode = sslmodes[0] if sslmodes else None

    if host in HOSTS_LOCALES:
        return ConfiguracionPostgres(
            conninfo=SecretStr(url),
            sslmode=sslmode or "prefer",
            sslrootcert=None,
        )

    if sslmode not in (None, "verify-full"):
        valor = sslmode if sslmode in SSLMODES_LIBPQ else "no reconocido"
        raise ConfiguracionPersistenciaError(
            f"RMA_DATABASE_URL pide sslmode={valor}: contra un servidor "
            "remoto solo se admite verify-full."
        )
    if "sslrootcert" in parametros:
        raise ConfiguracionPersistenciaError(
            "RMA_DATABASE_URL no debe traer sslrootcert: la CA se "
            "configura con RMA_DB_SSLROOTCERT."
        )
    return ConfiguracionPostgres(
        conninfo=SecretStr(url),
        sslmode="verify-full",
        sslrootcert=_certificado_raiz(settings.db_sslrootcert),
    )


def servidor_unico(url: str) -> str:
    """El unico host al que conectaria libpq con ``url``.

    ValueError si la URL no es valida, nombra varios servidores o trae
    parametros que redefinen el destino. El mensaje nunca cita la URL.
    """
    # ``from None``: el error de urllib podria citar partes de la URL.
    try:
        partes = urlsplit(url)
        host = partes.hostname
        partes.port  # un puerto no numerico lanza ValueError
        parametros = parse_qs(partes.query, keep_blank_values=True)
    except ValueError:
        raise ValueError("no es una URL de conexion valida.") from None
    if partes.scheme not in ESQUEMAS_URL or not host:
        raise ValueError(
            "debe tener la forma "
            "postgresql://usuario:contrasena@host:puerto/base."
        )
    if "," in partes.netloc.rpartition("@")[2]:
        raise ValueError("debe nombrar un solo servidor.")
    redefinidos = [p for p in PARAMETROS_DE_DESTINO if p in parametros]
    if redefinidos:
        raise ValueError(
            f"no debe traer {', '.join(redefinidos)} como parametro: el "
            "servidor se indica solo antes de la ruta."
        )
    return host


def conectar(
    configuracion: ConfiguracionPostgres, *, autocommit: bool = False
) -> "psycopg.Connection":
    """Abre una conexion. Un fallo se informa sin datos de conexion."""
    psycopg = _importar_psycopg()
    try:
        return psycopg.connect(
            configuracion.conninfo.get_secret_value(),
            autocommit=autocommit,
            **configuracion.argumentos_conexion(),
        )
    except psycopg.Error as error:
        # ``from None``: el error original podria citar la cadena.
        raise PersistenciaError(
            "No se pudo conectar a PostgreSQL: "
            + configuracion.sin_secretos(str(error)).strip()
        ) from None


def _certificado_raiz(ruta: Path) -> Path:
    """La CA tiene que existir y ser un certificado PEM."""
    try:
        contenido = ruta.read_bytes()
    except OSError:
        raise ConfiguracionPersistenciaError(
            f"RMA_DB_SSLROOTCERT: no se puede leer {ruta}."
        ) from None
    if _CABECERA_PEM not in contenido:
        raise ConfiguracionPersistenciaError(
            f"RMA_DB_SSLROOTCERT: {ruta} no es un certificado PEM."
        )
    return ruta.resolve()


def _importar_psycopg():
    try:
        import psycopg
    except ImportError:
        raise ConfiguracionPersistenciaError(
            "Falta la dependencia opcional de PostgreSQL: instalar el "
            "backend con pip install '.[postgres]'."
        ) from None
    return psycopg
