"""Errores de la capa de persistencia.

Deliberadamente separados de ``app.services.exceptions``: un fallo de
infraestructura (el archivo no existe, el JSON esta corrupto, el disco
no responde) no es una regla de negocio incumplida, y quien los atrape
va a querer tratarlos distinto.
"""


class RepositoryError(Exception):
    """Fallo al acceder a la persistencia.

    ``sqlstate``, ``restriccion`` y ``reintentable`` los completa la
    traduccion de errores de PostgreSQL
    (``app.storage.postgres.traducir_error``): informacion interna para
    diagnosticar y decidir un reintento, nunca para el usuario.
    """

    sqlstate: str | None = None
    restriccion: str | None = None
    reintentable: bool = False


class EntidadPersistidaNoEncontradaError(RepositoryError):
    """La entidad pedida no existe en el almacenamiento."""


class PersistenciaError(RepositoryError):
    """No se pudo leer o escribir: contenido invalido o error de E/S."""


class PersistenciaNoDisponibleError(PersistenciaError):
    """No hubo una conexion libre a tiempo: no se hizo nada.

    Es transitorio (el pool esta agotado): la API lo responde 503. No es
    un conflicto de datos (409) ni un fallo interno (500).
    """

    codigo = "PERSISTENCIA_NO_DISPONIBLE"


class PersistenciaSinConexionError(PersistenciaNoDisponibleError):
    """No se pudo establecer una conexion a la base a tiempo (E3, L2).

    Distinto del pool agotado: habia lugar en el pool, pero la base no
    respondio o rechazo la conexion. Tampoco se hizo nada. Hereda de
    ``PersistenciaNoDisponibleError`` (503) y se distingue por su codigo.
    """

    codigo = "PERSISTENCIA_SIN_CONEXION"


class TransaccionInvalidadaError(PersistenciaError):
    """La transaccion se revirtio porque algo fallo dentro de ella.

    Una excepcion salio de una transaccion anidada, o la base ya habia
    abortado la transaccion, y aun asi el bloque exterior termino como si
    nada: se revierte todo en vez de confirmar una parte. Es un error de
    programacion (atrapar un fallo dentro de la transaccion), no de datos.
    """


class RestriccionDeIntegridadError(PersistenciaError):
    """La base rechazo la escritura por una restriccion de integridad.

    Clave primaria, CHECK, clave foranea, NOT NULL o un trigger del esquema.
    No significa que otro comando haya modificado los datos: los services
    validan las reglas antes, asi que es un dato que el esquema no admite o
    una validacion que falta. Por eso no es un conflicto: repetir la
    operacion daria lo mismo. La API lo responde como un fallo interno.
    """


class DatosInvalidosError(PersistenciaError):
    """La base rechazo un valor: texto demasiado largo, numero fuera de
    rango, fecha invalida. Es un error de programacion, no de concurrencia.
    """


class PersistenciaResultadoInciertoError(PersistenciaError):
    """Se perdio la conexion durante el COMMIT: no se sabe si se guardo
    (E6, DE6-5, M4). La API responde 503 y no afirma ningun resultado.
    Con clave de idempotencia, reintentar es seguro."""

    codigo = "PERSISTENCIA_RESULTADO_INCIERTO"


class ClaveReutilizadaError(RepositoryError):
    """La clave de idempotencia ya se uso para otra operacion o con otros
    parametros (E6, DE6-3). La API responde 422: no es un reintento."""

    codigo = "CLAVE_REUTILIZADA"


class ConflictoDeEscrituraError(RepositoryError):
    """Se intento guardar una version obsoleta de la entidad (E4).

    La version persistida cambio despues de que la operacion la leyo, o
    ya esta cerrada. No es un fallo de infraestructura: la API lo responde
    como conflicto (409) para que el usuario recargue y reintente.
    """

    codigo = "CONFLICTO_CONCURRENTE"
