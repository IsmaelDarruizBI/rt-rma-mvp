"""Unidad de trabajo PostgreSQL: una transaccion de la base por comando.

Implementa ``app.repositories.UnidadDeTrabajo`` con psycopg 3 y
psycopg-pool (dependencia opcional: este modulo los importa, por eso
``app.storage.postgres`` no lo importa). Todavia no la usa la
aplicacion: ``RMA_PERSISTENCIA=postgres`` sigue deteniendo el arranque
hasta que existan los repositories.

Ciclo de ``transaccion()``:

1. Si ya hay una transaccion vigente en este contexto, se une a ella.
2. Si no (o la del contexto ya termino), toma una conexion del pool. Si
   no hay una libre dentro de ``RMA_DB_POOL_ESPERA_S``:
   ``PersistenciaNoDisponibleError`` (503).
3. ``BEGIN`` y los ``SET LOCAL`` de ``lock_timeout`` y
   ``statement_timeout``, en un solo envio. Terminan con la transaccion:
   nunca pasan al proximo uso de la conexion.
4. Fija la transaccion en una ``ContextVar``: los repositories toman la
   conexion con ``conexion_actual()``.
5. Bloque sin errores: ``COMMIT``. Con una excepcion: ``ROLLBACK`` y la
   excepcion sigue; las de psycopg, traducidas y sin encadenar (su texto
   puede citar valores de las filas).
6. Siempre: la transaccion deja de estar vigente, la ``ContextVar``
   vuelve a su valor anterior y la conexion vuelve al pool.

Anidadas: se unen a la exterior, sin savepoints, y solo la exterior
termina la transaccion. Si una excepcion sale de una anidada, la
transaccion queda invalidada: aunque el bloque exterior la atrape y
termine bien, se revierte todo y se lanza ``TransaccionInvalidadaError``.
Lo mismo si la base ya la habia abortado (un error SQL atrapado): un
``COMMIT`` sobre una transaccion abortada es un ``ROLLBACK`` silencioso.

Por que una ``ContextVar`` y no ``threading.local``: FastAPI corre cada
endpoint sincronico en un hilo del threadpool con una copia del contexto,
asi que cada pedido ve solo su transaccion aunque los hilos se reusen. Se
abre en la capa de aplicacion: en una dependencia ``yield`` de FastAPI la
variable se fija en otro contexto y el endpoint no la ve.

Contextos copiados: ``asyncio.create_task``, ``asyncio.to_thread``,
``run_in_threadpool`` y ``contextvars.copy_context()`` copian la
variable. La transaccion pertenece al hilo y a la tarea asyncio que la
abrieron, y deja de estar vigente al terminar: una copia nunca la usa, ni
mientras sigue abierta (compartiria la conexion con otro flujo) ni
despues (la conexion ya volvio al pool y puede ser de otro pedido).
``en_curso()`` devuelve ``False`` en esa copia y ``conexion_actual()``
lanza ``PersistenciaError``. Mientras la del padre sigue abierta, la
copia tampoco puede abrir otra (``PersistenciaError``). Cuando termino,
si: ``transaccion()`` abre una propia, con su conexion, y al salir la
``ContextVar`` vuelve a la heredada.

Control transaccional: solo esta unidad envia ``BEGIN``, ``COMMIT`` y
``ROLLBACK``. Los repositories nunca llaman ``commit()`` ni ``rollback()``
ni ejecutan SQL de control de transacciones. Si igual ocurre, al terminar
el bloque la conexion ya no esta en la transaccion:
``TransaccionInvalidadaError`` avisa que lo ejecutado pudo quedar
confirmado (las conexiones son ``autocommit``: lo posterior tambien),
porque eso ya no se puede revertir. Un ``COMMIT`` seguido de un nuevo
``BEGIN`` no se detecta; lo impedira una interfaz de ejecucion restringida
para los repositories (E3).

Sin reintentos automaticos: un conflicto llega como
``ConflictoDeEscrituraError`` (409) con ``reintentable`` informado.
"""

import asyncio
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import psycopg
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout

from app.repositories.exceptions import (
    PersistenciaError,
    PersistenciaNoDisponibleError,
    TransaccionInvalidadaError,
)

from .ajustes import AjustesPostgres, validar_ajustes
from .conexion import NOMBRE_APLICACION, ConfiguracionPostgres
from .errores import sqlstate, traducir_error

logger = logging.getLogger(__name__)

# Clase 08: la conexion se perdio. Si pasa en el COMMIT, no se sabe si la
# base llego a confirmar.
CLASE_CONEXION = "08"


def _flujo_actual() -> tuple[int, object | None]:
    """El hilo y, si corre en un event loop, la tarea asyncio actuales."""
    try:
        tarea = asyncio.current_task()
    except RuntimeError:  # hilo sin event loop, como un caso de uso
        tarea = None
    return threading.get_ident(), tarea


@dataclass
class _EnCurso:
    """La transaccion abierta en el contexto actual.

    ``dueno`` es el flujo (hilo y tarea) que la abrio; ``activa`` pasa a
    ``False`` al terminar, antes de devolver la conexion al pool. Una copia
    del contexto conserva este objeto, pero ya no puede usarlo: abre otra.
    """

    unidad: "UnidadDeTrabajoPostgres"
    conexion: psycopg.Connection
    dueno: tuple[int, object | None]
    invalidada: bool = False
    activa: bool = True

    def problema(self) -> str | None:
        """Por que el flujo actual no puede usarla (``None`` si puede)."""
        if not self.activa:
            return (
                "La transaccion ya termino: un contexto copiado (una tarea "
                "o un hilo creados dentro de ella) no puede usarla."
            )
        if self.dueno != _flujo_actual():
            return (
                "La transaccion pertenece a otro hilo o tarea: su conexion "
                "no se comparte."
            )
        return None


_EN_CURSO: ContextVar[_EnCurso | None] = ContextVar(
    "rma_transaccion_postgres", default=None
)


def abrir_pool(
    configuracion: ConfiguracionPostgres, ajustes: AjustesPostgres
) -> ConnectionPool:
    """Pool con las conexiones de ``configuracion`` (TLS ya validado).

    Las conexiones son ``autocommit``: la unidad de trabajo envia el
    ``BEGIN``, el ``COMMIT`` y el ``ROLLBACK`` explicitamente, y fuera de
    ella no queda ninguna transaccion implicita abierta. Se abre sin
    esperar: si la base no responde, lo informa el primer comando (503).
    """
    validar_ajustes(ajustes)
    pool = ConnectionPool(
        configuracion.conninfo.get_secret_value(),
        kwargs={**configuracion.argumentos_conexion(), "autocommit": True},
        min_size=ajustes.pool_min,
        max_size=ajustes.pool_max,
        timeout=ajustes.pool_espera_s,
        name=NOMBRE_APLICACION,
        open=False,
    )
    pool.open(wait=False)
    return pool


class UnidadDeTrabajoPostgres:
    """Transacciones sobre las conexiones de un pool."""

    def __init__(self, pool: ConnectionPool, ajustes: AjustesPostgres):
        validar_ajustes(ajustes)
        self._pool = pool
        # Enteros validados: no hay nada que escapar.
        self._inicio = (
            "BEGIN; "
            f"SET LOCAL lock_timeout = {int(ajustes.lock_timeout_ms)}; "
            "SET LOCAL statement_timeout = "
            f"{int(ajustes.statement_timeout_ms)}"
        )

    def en_curso(self) -> bool:
        """Si este flujo esta dentro de una transaccion vigente de esta
        unidad (una copia del contexto nunca lo esta)."""
        actual = _EN_CURSO.get()
        return (
            actual is not None
            and actual.unidad is self
            and actual.problema() is None
        )

    def conexion_actual(self) -> psycopg.Connection:
        """La conexion de la transaccion en curso.

        Fuera de una transaccion es un error: ningun repository lee ni
        escribe por su cuenta.
        """
        actual = _EN_CURSO.get()
        if actual is None or actual.unidad is not self:
            raise PersistenciaError(
                "Acceso a PostgreSQL fuera de una transaccion: el caso de "
                "uso debe abrirla con contexto.transaccion()."
            )
        problema = actual.problema()
        if problema:
            raise PersistenciaError(problema)
        return actual.conexion

    @contextmanager
    def transaccion(self) -> Iterator[None]:
        """Transaccion nueva, o la que ya esta en curso."""
        actual = _EN_CURSO.get()
        if actual is not None and actual.activa:
            with self._unirse(actual):
                yield
            return

        # Sin transaccion, o con la heredada de un contexto copiado que ya
        # termino: se abre una propia, con otra conexion del pool.
        conexion = self._tomar_conexion()
        estado = _EnCurso(
            unidad=self, conexion=conexion, dueno=_flujo_actual()
        )
        token = _EN_CURSO.set(estado)
        iniciada = False
        try:
            try:
                conexion.execute(self._inicio)
                iniciada = True
                yield
                self._exigir_confirmable(estado)
            except psycopg.Error as error:
                externo = iniciada and _terminada_afuera(conexion)
                self._revertir(conexion)
                if externo:
                    raise _control_externo() from None
                raise traducir_error(error) from None
            except TransaccionInvalidadaError:
                # Ya es el diagnostico (de ``_exigir_confirmable``).
                self._revertir(conexion)
                raise
            except Exception as error:
                externo = iniciada and _terminada_afuera(conexion)
                self._revertir(conexion)
                if externo:
                    raise _control_externo() from error
                raise
            except BaseException:
                # KeyboardInterrupt y similares siguen como son; si lo
                # anterior pudo quedar confirmado, al menos queda en el log.
                if iniciada and _terminada_afuera(conexion):
                    logger.error("%s", _control_externo())
                self._revertir(conexion)
                raise
            self._confirmar(conexion)
        finally:
            # Antes de devolver la conexion: una copia del contexto que la
            # conserve ya no puede usarla.
            estado.activa = False
            # ``reset`` falla si se la cierra desde otro contexto (una
            # dependencia de FastAPI): aun asi la conexion vuelve al pool.
            try:
                _EN_CURSO.reset(token)
            finally:
                self._pool.putconn(conexion)

    @contextmanager
    def _unirse(self, actual: _EnCurso) -> Iterator[None]:
        """Anidada: sin BEGIN ni COMMIT propios; un fallo la invalida."""
        if actual.unidad is not self:
            raise PersistenciaError(
                "Ya hay una transaccion de otra unidad de trabajo en curso."
            )
        problema = actual.problema()
        if problema:
            raise PersistenciaError(problema)
        try:
            yield
        except psycopg.Error as error:
            actual.invalidada = True
            raise traducir_error(error) from None
        except BaseException:
            actual.invalidada = True
            raise

    def _tomar_conexion(self) -> psycopg.Connection:
        try:
            return self._pool.getconn()
        except PoolTimeout:
            raise PersistenciaNoDisponibleError(
                "No hubo una conexion libre a PostgreSQL a tiempo."
            ) from None
        except PoolClosed:
            raise PersistenciaError(
                "El pool de PostgreSQL esta cerrado."
            ) from None

    @staticmethod
    def _exigir_confirmable(estado: _EnCurso) -> None:
        if _terminada_afuera(estado.conexion):
            raise _control_externo()
        if estado.invalidada:
            raise TransaccionInvalidadaError(
                "Una operacion fallo dentro de la transaccion y el error se "
                "atrapo: se revirtio la transaccion en vez de confirmar una "
                "parte."
            )
        if estado.conexion.info.transaction_status != (
            TransactionStatus.INTRANS
        ):
            raise TransaccionInvalidadaError(
                "PostgreSQL aborto la transaccion (o se perdio la conexion) "
                "por un error que se atrapo: no se confirmo nada de ella."
            )

    @staticmethod
    def _confirmar(conexion: psycopg.Connection) -> None:
        try:
            conexion.commit()
        except psycopg.Error as error:
            codigo = sqlstate(error) or ""
            if conexion.closed or codigo.startswith(CLASE_CONEXION):
                incierto = PersistenciaError(
                    "Se perdio la conexion a PostgreSQL al confirmar: no se "
                    "sabe si se guardo (SQLSTATE "
                    f"{codigo or 'desconocido'})."
                )
                incierto.sqlstate = codigo or None
                raise incierto from None
            # La base rechazo el COMMIT (por ejemplo, una restriccion
            # diferida) y ya revirtio la transaccion.
            raise traducir_error(error) from None

    @staticmethod
    def _revertir(conexion: psycopg.Connection) -> None:
        """ROLLBACK; si falla, la conexion se cierra y el pool la descarta.

        Nunca tapa el error que provoco la reversion.
        """
        if conexion.closed:
            return
        try:
            conexion.rollback()
        except psycopg.Error as error:
            logger.warning(
                "No se pudo revertir la transaccion (SQLSTATE %s): se "
                "descarta la conexion.",
                sqlstate(error) or "desconocido",
            )
            conexion.close()


def _terminada_afuera(conexion: psycopg.Connection) -> bool:
    """Si la transaccion ya termino sin la unidad de trabajo.

    Despues del BEGIN, la conexion solo vuelve a IDLE con un COMMIT o un
    ROLLBACK, y esos los envia unicamente la unidad de trabajo.
    """
    return conexion.info.transaction_status == TransactionStatus.IDLE


def _control_externo() -> TransaccionInvalidadaError:
    return TransaccionInvalidadaError(
        "La transaccion se termino dentro del bloque con un COMMIT o un "
        "ROLLBACK enviado fuera de la unidad de trabajo: lo ejecutado pudo "
        "quedar confirmado y no se puede revertir. Revisar los datos de "
        "esta operacion."
    )
