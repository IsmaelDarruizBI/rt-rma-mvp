"""Registro de las consultas SQL de los repositories PostgreSQL (E3).

El ejecutor (``EjecutorSql``) solo ejecuta consultas registradas con
``consulta(nombre, sql, modo=...)``. Se registran al importar el modulo
que las usa, con texto estatico; el registro valida cada una y, si no
cumple, el modulo no carga. Asi todo el SQL es enumerable y una prueba
estatica lo revisa completo.

Cada consulta se clasifica al registrarla (QA-E3-3):

- ``LECTURA``: empieza con SELECT o WITH y no escribe: sin INSERT,
  UPDATE, DELETE, MERGE ni RETURNING (tampoco dentro de un WITH), sin
  bloqueos de filas (``FOR UPDATE``/``FOR SHARE``) y sin ``nextval``. Es
  lo unico que acepta el lector de ``lectura()``.
- ``ESCRITURA``: cualquier DML permitido (y las lecturas que bloquean
  filas). Solo la ejecuta el ejecutor de un comando.

Reglas del texto registrado, para los dos modos:

- Una sola sentencia, que empieza con SELECT, WITH, INSERT, UPDATE o
  DELETE. Nada de control transaccional (BEGIN, COMMIT, ROLLBACK,
  SAVEPOINT...) ni de sesion (SET, RESET, DISCARD...).
- Sin ``;``, sin comentarios, sin ``$`` (cadenas con dolar) y sin
  escapes Unicode (``U&``): no hay como esconder otra sentencia.
- ``INTO`` solo en ``INSERT INTO``, con el INSERT en posicion de
  sentencia (no como alias): ``SELECT ... INTO`` crea una tabla
  (temporal o no) que sobrevive a la transaccion. Tampoco ``pg_temp``.
- Las comillas dobles de un identificador cuentan como separacion: no
  esconden un nombre ni pegan dos palabras.
- Sin ``pg_settings``: su ``UPDATE`` equivale a ``set_config(..., false)``
  y el cambio queda en la sesion (QA-E3-1).
- Sin las funciones con efectos de sesion o de servidor conocidas, ni las
  que ejecutan SQL recibido como texto (``query_to_xml`` y similares,
  ``ts_stat``, ``ts_rewrite``), que esquivarian cualquier lista de
  nombres (QA-E3-1). Ni los esquemas de extensiones con efectos fuera de
  la base (``net``, ``cron``, ``vault``, ``pgsodium``).
- Los valores siempre como parametros (``%s`` o ``%(nombre)s``).

Limite: es una red para errores de programacion, no una barrera contra
codigo malicioso ni un analizador de SQL general, y no sirve para aceptar
SQL de fuentes no confiables: solo valida texto estatico escrito y
revisado en el repositorio. Ninguna lista es completa: una
funcion definida por el usuario puede escribir o cambiar la sesion sin
que el texto lo muestre. Las barreras reales son que el texto sea
estatico y revisado, los privilegios minimos del rol de la base y, en
``lectura()`` fuera de un comando, la transaccion ``READ ONLY``. El
ejecutor ademas fuerza el protocolo extendido: el servidor rechaza mas de
una sentencia por envio.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import LiteralString


class Modo(StrEnum):
    """Clasificacion de una consulta registrada."""

    LECTURA = "lectura"
    ESCRITURA = "escritura"


LECTURA = Modo.LECTURA
ESCRITURA = Modo.ESCRITURA

PRIMERAS_PALABRAS = frozenset({"SELECT", "WITH", "INSERT", "UPDATE", "DELETE"})
PRIMERAS_DE_LECTURA = frozenset({"SELECT", "WITH"})

# Familias de funciones, por prefijo: ``pg_advisory`` y ``pg_try_advisory``
# cubren todas las variantes de bloqueos advisory; ``lo_``, los objetos
# grandes; ``*_to_xml``, las que ejecutan una consulta o leen tablas
# enteras.
PREFIJOS_PROHIBIDOS = (
    "pg_advisory",
    "pg_try_advisory",
    "lo_",
    "dblink",
    "query_to_xml",
    "cursor_to_xml",
    "table_to_xml",
    "schema_to_xml",
    "database_to_xml",
    "http_",
    # pg_sleep, pg_sleep_for y pg_sleep_until (QAF-4).
    "pg_sleep",
)
# Nombres exactos.
FUNCIONES_PROHIBIDAS = (
    "set_config",
    "setval",
    # Leen el ultimo valor de una secuencia en la sesion, que en el pool
    # puede ser de un comando anterior (QAF-14): se usa el valor devuelto
    # por la misma sentencia.
    "currval",
    "lastval",
    "loread",
    "lowrite",
    "ts_stat",
    "ts_rewrite",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "pg_notify",
    "pg_export_snapshot",
    "pg_settings",
    # El esquema temporal de la sesion: crear o escribir ahi deja estado.
    "pg_temp",
)
ESQUEMAS_PROHIBIDOS = ("net", "cron", "vault", "pgsodium")

_PRIMERA = re.compile(r"\s*\(*\s*([A-Za-z_]+)")
_PROHIBIDAS = re.compile(
    r"\b(?:"
    + "|".join(
        [re.escape(p) + r"\w*" for p in PREFIJOS_PROHIBIDOS]
        + [re.escape(f) + r"\b" for f in FUNCIONES_PROHIBIDAS]
        + [re.escape(e) + r"\s*\." for e in ESQUEMAS_PROHIBIDOS]
    )
    + r")",
    re.IGNORECASE,
)
_INTO = re.compile(r"\bINTO\b", re.IGNORECASE)
# INSERT en posicion de sentencia, no como alias o identificador
# (``SELECT 1 AS insert INTO t`` no es un INSERT, QAF-2): al principio, tras
# ``(`` (el cuerpo de un WITH) o tras ``)``. Esto ultimo solo vale en una
# consulta que empieza con WITH (la sentencia que sigue a la lista de
# WITH); en otra, ``SELECT (1) insert INTO`` es un alias.
_INSERT_ANTES = re.compile(r"(?:^|([()]))\s*INSERT\s*$", re.IGNORECASE)
# Las formas que solo existen en SELECT INTO, sea cual sea lo anterior,
# tambien con LOCAL o GLOBAL (``INTO LOCAL TEMP``).
_INTO_TABLA = re.compile(
    r"\bINTO\s+(?:(?:LOCAL|GLOBAL)\s+)?(?:TEMP|TEMPORARY|UNLOGGED|TABLE)\b",
    re.IGNORECASE,
)
_ESCRIBE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|RETURNING|NEXTVAL)\b"
    r"|\bFOR\s+(NO\s+KEY\s+UPDATE|UPDATE|KEY\s+SHARE|SHARE)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, eq=False)
class Consulta:
    """Una consulta registrada. Solo se crean con ``consulta(...)``."""

    nombre: str
    sql: str
    modo: Modo


_REGISTRO: dict[str, Consulta] = {}


def consulta(nombre: str, sql: LiteralString, *, modo: Modo) -> Consulta:
    """Registra una consulta estatica de ``modo`` (``LECTURA`` o
    ``ESCRITURA``); ``ValueError`` si no es valida."""
    if not isinstance(modo, Modo):
        raise ValueError(
            f"La consulta {nombre} no se registra: el modo tiene que ser "
            "LECTURA o ESCRITURA."
        )
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError(f"La consulta {nombre} no tiene texto.")
    problema = problema_de(sql, modo)
    if problema:
        raise ValueError(f"La consulta {nombre} no se registra: {problema}.")
    if nombre in _REGISTRO:
        raise ValueError(f"Ya hay una consulta registrada como {nombre}.")
    registrada = Consulta(nombre=nombre, sql=sql, modo=modo)
    _REGISTRO[nombre] = registrada
    return registrada


def problema_de(sql: str, modo: Modo = ESCRITURA) -> str | None:
    """Por que el texto no se puede registrar en ``modo`` (``None`` si se
    puede). Sin modo, solo las reglas comunes."""
    if "--" in sql or "/*" in sql:
        return "no admite comentarios"
    if ";" in sql:
        return "una sola sentencia, sin ';'"
    if "$" in sql:
        return "no admite '$' (cadenas con dolar)"
    if re.search(r"u&", sql, re.IGNORECASE):
        return "no admite escapes Unicode (U&)"
    # Las comillas dobles pasan a ser un espacio, no se borran: "set_config"
    # o "SELECT" no esquivan las reglas, y ALL"set_config" no se pega en
    # una sola palabra (ALLset_config) que ninguna regla reconoce (QAF-1).
    texto = sql.replace('"', " ")
    primera = _PRIMERA.match(texto)
    palabra = primera.group(1).upper() if primera else ""
    if palabra not in PRIMERAS_PALABRAS:
        return (
            f"empieza con {palabra or 'nada'}: solo SELECT, WITH, INSERT, "
            "UPDATE o DELETE"
        )
    prohibida = _PROHIBIDAS.search(texto)
    if prohibida:
        return (
            f"usa {prohibida.group(0).strip()}, que tiene efectos de sesion "
            "o fuera de la transaccion"
        )
    if _INTO_TABLA.search(texto):
        return "INTO solo en INSERT INTO (SELECT INTO crea tablas)"
    for into in _INTO.finditer(texto):
        insert = _INSERT_ANTES.search(texto[: into.start()])
        if not insert or (insert.group(1) == ")" and palabra != "WITH"):
            return "INTO solo en INSERT INTO (SELECT INTO crea tablas)"
    if modo is LECTURA:
        if palabra not in PRIMERAS_DE_LECTURA:
            return f"una consulta de lectura no empieza con {palabra}"
        escribe = _ESCRIBE.search(texto)
        if escribe:
            return (
                f"una consulta de lectura no usa {escribe.group(0).upper()}: "
                "se registra como ESCRITURA"
            )
    return None


def exigir_registrada(consulta_: object) -> Consulta:
    """La consulta, si es una registrada; si no, ``TypeError``."""
    if (
        not isinstance(consulta_, Consulta)
        or _REGISTRO.get(consulta_.nombre) is not consulta_
    ):
        raise TypeError(
            "Solo se ejecutan consultas registradas con consulta(...)."
        )
    return consulta_


def registradas() -> Mapping[str, Consulta]:
    """Todas las consultas registradas hasta ahora (solo lectura)."""
    return MappingProxyType(_REGISTRO)
