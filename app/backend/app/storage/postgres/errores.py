"""Traduccion de errores de PostgreSQL a los de la capa de persistencia.

Las reglas de negocio se validan en ``app.services``; el esquema ``rma``
garantiza la integridad por debajo (stock, Orden cerrada, unicidad,
inmutabilidad). Que la base rechace una escritura significa que los
datos cambiaron entre la lectura y el guardado -o que a un service le
falta una validacion-, nunca un mensaje funcional para el usuario:

    clase 23 (restriccion violada)          -> ConflictoDeEscrituraError
    40001, 40P01, 55P03 (concurrencia)      -> ConflictoDeEscrituraError,
                                               y ademas ``es_reintentable``
    todo lo demas (conexion, timeout,       -> PersistenciaError
    permisos, P0001 de las tablas inmutables)

Los mensajes llevan el SQLSTATE y, si la hay, la restriccion; nunca el
texto del servidor, que puede citar valores de las filas.
"""

from app.repositories.exceptions import (
    ConflictoDeEscrituraError,
    PersistenciaError,
    RepositoryError,
)

CLASE_INTEGRIDAD = "23"
# Serializacion, deadlock y ``lock_timeout``: repetir la transaccion
# completa puede funcionar.
SQLSTATE_REINTENTABLES = frozenset({"40001", "40P01", "55P03"})
SQLSTATE_TIMEOUT = "57014"


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
    if codigo in SQLSTATE_REINTENTABLES or (
        codigo is not None and codigo.startswith(CLASE_INTEGRIDAD)
    ):
        traducido = ConflictoDeEscrituraError(
            "Los datos cambiaron mientras se procesaba esta operacion: no "
            "se guardo. Recarga y volve a intentarlo "
            f"({referencia})."
        )
    elif codigo == SQLSTATE_TIMEOUT:
        traducido = PersistenciaError(
            f"PostgreSQL no respondio a tiempo ({referencia})."
        )
    else:
        traducido = PersistenciaError(f"Fallo de PostgreSQL ({referencia}).")
    traducido.sqlstate = codigo
    traducido.reintentable = es_reintentable(error)
    return traducido


def _referencia(error: BaseException, codigo: str | None) -> str:
    partes = [f"SQLSTATE {codigo or 'desconocido'}"]
    restriccion = getattr(
        getattr(error, "diag", None), "constraint_name", None
    )
    if restriccion:
        partes.append(f"restriccion {restriccion}")
    return ", ".join(partes)
