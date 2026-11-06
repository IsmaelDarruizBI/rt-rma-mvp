"""Traduccion de errores de PostgreSQL a los de la capa de persistencia.

Las reglas de negocio se validan en ``app.services``; el esquema ``rma``
garantiza la integridad por debajo (stock, Orden cerrada, unicidad,
inmutabilidad). Un rechazo de la base nunca es un mensaje funcional para
el usuario, y solo se presenta como conflicto si de verdad lo es (L-3):

    40001, 40P01 (concurrencia)             -> ConflictoDeEscrituraError,
                                               reintentable
    55P03 (bloqueo agotado)                 -> ConflictoDeEscrituraError,
                                               reintentable, sin decir que
                                               los datos cambiaron
    23505 de una clave unica de negocio     -> ConflictoDeEscrituraError:
                                               ya existe, no es reintentable
    el resto de la clase 23 (clave primaria,-> RestriccionDeIntegridadError
    CHECK, clave foranea, NOT NULL, triggers)
    clase 22 (valor invalido)               -> DatosInvalidosError
    todo lo demas (conexion, timeout,       -> PersistenciaError
    permisos, P0001 de las tablas inmutables)

Una clave primaria repetida no es una carrera: las claves de las filas del
agregado salen de la Orden o de un ``uuid``, asi que indica un dato que el
esquema no admite. Una clave unica de negocio (codigo, documento, clave de
idempotencia) si puede repetirse porque otra operacion la creo primero.

``RestriccionDeIntegridadError`` y ``DatosInvalidosError`` son
``PersistenciaError``: la API los responde con su 500 generico, sin
detalles del esquema.

Nunca se usa el texto del servidor, que puede citar valores de las filas.
El mensaje de un ``ConflictoDeEscrituraError`` llega al cliente (409), asi
que no lleva nada del esquema: el SQLSTATE y la restriccion quedan en sus
atributos y en el log. Los demas errores los llevan en el mensaje, que solo
va al log: al cliente le llega el 500 generico.
"""

import logging

from app.repositories.exceptions import (
    ConflictoDeEscrituraError,
    DatosInvalidosError,
    PersistenciaError,
    RepositoryError,
    RestriccionDeIntegridadError,
)

logger = logging.getLogger(__name__)

CLASE_INTEGRIDAD = "23"
CLASE_DATOS = "22"
# Serializacion, deadlock y ``lock_timeout``: repetir la transaccion
# completa puede funcionar.
SQLSTATE_REINTENTABLES = frozenset({"40001", "40P01", "55P03"})
SQLSTATE_BLOQUEO_AGOTADO = "55P03"
SQLSTATE_UNICIDAD = "23505"
SQLSTATE_TIMEOUT = "57014"
SUFIJO_CLAVE_PRIMARIA = "_pkey"


def sqlstate(error: BaseException) -> str | None:
    """El SQLSTATE de un error de psycopg (``None`` si no lo tiene)."""
    return getattr(error, "sqlstate", None)


def es_reintentable(error: BaseException) -> bool:
    """Si repetir la transaccion completa puede resolver el error."""
    return sqlstate(error) in SQLSTATE_REINTENTABLES


def traducir_error(error: BaseException) -> RepositoryError:
    """Error de la capa de persistencia equivalente a ``error``.

    Se usa como ``raise traducir_error(error) from None``: el texto de
    psycopg trae el DETAIL del servidor, con valores de la fila (un DNI,
    por ejemplo), y encadenarlo lo llevaria al traceback del log. El
    SQLSTATE y la restriccion del mensaje traducido alcanzan para
    diagnosticar.

    El traducido conserva ``sqlstate`` y ``reintentable``: como el error
    original no se encadena, es lo que queda para decidir un reintento.
    """
    codigo = sqlstate(error)
    referencia = _referencia(error, codigo)
    traducido: RepositoryError
    if codigo == SQLSTATE_BLOQUEO_AGOTADO:
        traducido = ConflictoDeEscrituraError(
            "Otra operacion esta usando estos datos: no se guardo. Volve a "
            "intentarlo en unos segundos."
        )
    elif codigo in SQLSTATE_REINTENTABLES:
        traducido = ConflictoDeEscrituraError(
            "Los datos cambiaron mientras se procesaba esta operacion: no "
            "se guardo. Recarga y volve a intentarlo."
        )
    elif _es_unicidad_de_negocio(error, codigo):
        traducido = ConflictoDeEscrituraError(
            "Ya existe un registro con esos datos: no se guardo. Recarga y "
            "verifica."
        )
    elif codigo is not None and codigo.startswith(CLASE_INTEGRIDAD):
        traducido = RestriccionDeIntegridadError(
            "La base rechazo la escritura por una restriccion de integridad: "
            f"no se guardo ({referencia})."
        )
    elif codigo is not None and codigo.startswith(CLASE_DATOS):
        traducido = DatosInvalidosError(
            f"La base rechazo un valor invalido: no se guardo ({referencia})."
        )
    elif codigo == SQLSTATE_TIMEOUT:
        traducido = PersistenciaError(
            f"PostgreSQL no respondio a tiempo ({referencia})."
        )
    else:
        traducido = PersistenciaError(f"Fallo de PostgreSQL ({referencia}).")
    traducido.sqlstate = codigo
    traducido.restriccion = _restriccion(error)
    traducido.reintentable = es_reintentable(error)
    if isinstance(traducido, ConflictoDeEscrituraError):
        logger.warning("Conflicto de escritura (%s).", referencia)
    return traducido


def _restriccion(error: BaseException) -> str | None:
    return getattr(getattr(error, "diag", None), "constraint_name", None)


def _es_unicidad_de_negocio(error: BaseException, codigo: str | None) -> bool:
    """Repetida porque otra operacion la creo primero. Sin nombre es la de
    un trigger, que tambien protege un codigo de negocio."""
    return codigo == SQLSTATE_UNICIDAD and not (
        _restriccion(error) or ""
    ).endswith(SUFIJO_CLAVE_PRIMARIA)


def _referencia(error: BaseException, codigo: str | None) -> str:
    partes = [f"SQLSTATE {codigo or 'desconocido'}"]
    restriccion = _restriccion(error)
    if restriccion:
        partes.append(f"restriccion {restriccion}")
    return ", ".join(partes)
