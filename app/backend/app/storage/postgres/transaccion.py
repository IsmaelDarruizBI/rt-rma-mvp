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
   ``PersistenciaNoDisponibleError`` (503); si habia lugar pero la base
   no respondio, ``PersistenciaSinConexionError`` (E3, L2).
3. ``BEGIN`` y los ``SET LOCAL`` de ``lock_timeout`` y
   ``statement_timeout``, en un solo envio. Terminan con la transaccion:
   nunca pasan al proximo uso de la conexion. Si la conexion del pool
   estaba cortada (el ``BEGIN`` falla por un error de conexion), se
   descarta y se toma otra una sola vez: no es un reintento de la
   transaccion, porque no se ejecuto nada (E3, M2). Si la otra tambien
   esta cortada: ``PersistenciaSinConexionError`` (503, QA-E3-2).
4. Fija la transaccion en una ``ContextVar``. Los repositories trabajan
   con ``ejecutor()`` o ``lectura()`` (E3): nunca reciben la conexion.
5. Bloque sin errores: ``COMMIT``. Con una excepcion: ``ROLLBACK`` y la
   excepcion sigue; las de psycopg, traducidas y sin encadenar (su texto
   puede citar valores de las filas).
6. Siempre: la transaccion deja de estar vigente, la ``ContextVar``
   vuelve a su valor anterior y la conexion vuelve al pool, o se cierra
   si su estado es dudoso: un control transaccional externo, una
   interrupcion durante el ``BEGIN`` o una conexion que no quedo fuera de
   toda transaccion (``IDLE``).

``lectura()`` (E3, DE3-4): dentro de una transaccion del mismo flujo, la
usa tal como esta (de escritura o no); si no hay ninguna, abre una
transaccion breve ``BEGIN READ ONLY`` con los mismos ``SET LOCAL``, que
termina con ``ROLLBACK``. Su lector solo ejecuta consultas registradas
como ``LECTURA`` (QA-E3-3): una de ``ESCRITURA`` se rechaza sin enviarla
e invalida la transaccion, tambien dentro de un comando que escribe. No
cambia el caracter de la transaccion que usa. Dentro de una lectura no se
abre una transaccion de escritura.

Estado de sesion (QA-E3-1): lo que una consulta deje en la sesion (un
ajuste, una tabla temporal, un bloqueo advisory de sesion) no lo deshace
el ``ROLLBACK`` ni se detecta al devolver la conexion. Con Supavisor en
modo transaccion, ademas, quedaria en una conexion del servidor que usan
otros clientes, asi que limpiar el pool propio no alcanzaria. Se evita
antes: el registro rechaza las formas conocidas (``consultas.py``) y los
privilegios del rol son la otra barrera.

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
``en_curso()`` devuelve ``False`` en esa copia, y su lector o ejecutor se
rechazan. Mientras la del padre sigue abierta, la copia tampoco puede
abrir otra (``PersistenciaError``). Cuando termino, si: abre una propia,
con su conexion, y al salir la ``ContextVar`` vuelve a la heredada.

Control transaccional: solo esta unidad envia ``BEGIN``, ``COMMIT`` y
``ROLLBACK``. El ejecutor solo acepta consultas registradas
(``consultas.py``), que no pueden contener control transaccional ni de
sesion, y fuerza el protocolo extendido (una sentencia por envio). Si
igual la conexion queda fuera de la transaccion, ``TransaccionInvalidadaError``
avisa que lo ejecutado pudo quedar confirmado, y la conexion se descarta.

Sin reintentos automaticos: un conflicto llega como
``ConflictoDeEscrituraError`` (409) con ``reintentable`` informado.
"""

import asyncio
import logging
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import namedtuple_row
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout

from app.repositories.exceptions import (
    PersistenciaError,
    PersistenciaNoDisponibleError,
    PersistenciaSinConexionError,
    TransaccionInvalidadaError,
)

from .ajustes import AjustesPostgres, validar_ajustes
from .conexion import NOMBRE_APLICACION, ConfiguracionPostgres
from .consultas import ESCRITURA, LECTURA, Consulta, Modo, exigir_registrada
from .ejecutor import EjecutorSql, LectorSql, Parametros
from .errores import sqlstate, traducir_error

logger = logging.getLogger(__name__)

# Clase 08: la conexion se perdio. Si pasa en el COMMIT, no se sabe si la
# base llego a confirmar.
CLASE_CONEXION = "08"
# El servidor cerro la conexion (administrador, caida o reinicio).
SQLSTATE_CONEXION_CERRADA = frozenset({"57P01", "57P02", "57P03"})


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
    ``descartar``: el estado de la conexion es dudoso y no vuelve al pool.
    ``datos``: lo que los repositories guardan mientras dura la
    transaccion (instantaneas del agregado, la accion del comando). Se
    pierde con ella: nada queda viejo para la siguiente.
    """

    unidad: "UnidadDeTrabajoPostgres"
    conexion: psycopg.Connection
    dueno: tuple[int, object | None]
    invalidada: bool = False
    activa: bool = True
    solo_lectura: bool = False
    descartar: bool = False
    datos: dict[str, Any] = field(default_factory=dict)

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

    ``pool_max_idle_s``: el pool cierra las conexiones que superan
    ``pool_min`` y estan ociosas desde hace mas de ese tiempo, de a una
    por intervalo. Las ``pool_min`` conexiones nunca se renuevan por
    inactividad: si el servidor o el pooler las corta, las cubre el
    reemplazo unico del ``BEGIN`` (M2).
    """
    validar_ajustes(ajustes)
    pool = ConnectionPool(
        configuracion.conninfo.get_secret_value(),
        kwargs={**configuracion.argumentos_conexion(), "autocommit": True},
        min_size=ajustes.pool_min,
        max_size=ajustes.pool_max,
        timeout=ajustes.pool_espera_s,
        max_idle=ajustes.pool_max_idle_s,
        name=NOMBRE_APLICACION,
        open=False,
    )
    pool.open(wait=False)
    return pool


def cerrar_pool(pool: ConnectionPool, espera_s: float = 5.0) -> None:
    """Cierra el pool (para el apagado de la aplicacion, L8).

    Cierra enseguida las conexiones ociosas y deja de entregar conexiones.
    ``espera_s`` es lo que espera a los hilos internos del pool, no a las
    conexiones en uso: una transaccion en curso sigue y su conexion se
    cierra al devolverla. Por eso el apagado tiene que dejar terminar los
    pedidos antes de llamarla.
    """
    pool.close(timeout=espera_s)


class UnidadDeTrabajoPostgres:
    """Transacciones sobre las conexiones de un pool."""

    def __init__(self, pool: ConnectionPool, ajustes: AjustesPostgres):
        validar_ajustes(ajustes)
        self._pool = pool
        # Enteros validados: no hay nada que escapar.
        limites = (
            f"SET LOCAL lock_timeout = {int(ajustes.lock_timeout_ms)}; "
            "SET LOCAL statement_timeout = "
            f"{int(ajustes.statement_timeout_ms)}"
        )
        self._inicio = f"BEGIN; {limites}"
        # Lectura breve: REPEATABLE READ, asi las consultas de un agregado
        # o de una respuesta ven el mismo instante (DA-4, F-09).
        self._inicio_lectura = (
            f"BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; {limites}"
        )
        # Conexiones entregadas por esta unidad y no devueltas: distingue
        # el pool agotado de la base que no responde (L2).
        self._en_uso = 0
        self._candado = threading.Lock()

    def en_curso(self) -> bool:
        """Si este flujo esta dentro de una transaccion vigente de esta
        unidad (una copia del contexto nunca lo esta)."""
        actual = _EN_CURSO.get()
        return (
            actual is not None
            and actual.unidad is self
            and actual.problema() is None
        )

    def _conexion_actual(self) -> psycopg.Connection:
        """La conexion de la transaccion en curso (solo para esta unidad y
        sus pruebas: los repositories usan ``ejecutor()`` o ``lectura()``).

        Fuera de una transaccion es un error: ningun repository lee ni
        escribe por su cuenta.
        """
        return self._vigente().conexion

    def datos_de_transaccion(self) -> dict[str, Any]:
        """Almacen de la transaccion en curso de este flujo (E4).

        Los repositories guardan aca lo que vale solo mientras dura la
        transaccion: la instantanea de un agregado cargado para
        modificarlo y la accion del comando. Fuera de una transaccion
        propia es un error, como ``ejecutor()``.
        """
        return self._vigente().datos

    def ejecutor(self) -> EjecutorSql:
        """El ejecutor de la transaccion de escritura en curso."""
        actual = self._vigente()
        if actual.solo_lectura:
            raise PersistenciaError(
                "La transaccion en curso es de solo lectura: un comando que "
                "escribe abre la suya con contexto.transaccion()."
            )
        return _Ejecutor(actual)

    @contextmanager
    def lectura(self) -> Iterator[LectorSql]:
        """Un lector: el de la transaccion en curso de este flujo o, si no
        hay ninguna, el de una transaccion breve de solo lectura."""
        actual = _EN_CURSO.get()
        if actual is not None and actual.activa:
            self._exigir_propia(actual)
            yield _Lector(actual)
            return
        with self._abrir(solo_lectura=True) as estado:
            yield _Lector(estado)

    @contextmanager
    def transaccion(self) -> Iterator[None]:
        """Transaccion nueva, o la que ya esta en curso."""
        actual = _EN_CURSO.get()
        if actual is not None and actual.activa:
            if actual.unidad is self and actual.solo_lectura:
                raise PersistenciaError(
                    "No se abre una transaccion de escritura dentro de una "
                    "lectura."
                )
            with self._unirse(actual):
                yield
            return

        # Sin transaccion, o con la heredada de un contexto copiado que ya
        # termino: se abre una propia, con otra conexion del pool.
        with self._abrir(solo_lectura=False):
            yield

    # --- Interno ---------------------------------------------------------

    def _vigente(self) -> _EnCurso:
        actual = _EN_CURSO.get()
        if actual is None or actual.unidad is not self:
            raise PersistenciaError(
                "Acceso a PostgreSQL fuera de una transaccion: el caso de "
                "uso debe abrirla con contexto.transaccion()."
            )
        problema = actual.problema()
        if problema:
            raise PersistenciaError(problema)
        return actual

    def _exigir_propia(self, actual: _EnCurso) -> None:
        if actual.unidad is not self:
            raise PersistenciaError(
                "Ya hay una transaccion de otra unidad de trabajo en curso."
            )
        problema = actual.problema()
        if problema:
            raise PersistenciaError(problema)

    @contextmanager
    def _abrir(self, *, solo_lectura: bool) -> Iterator[_EnCurso]:
        conexion = self._iniciar(solo_lectura)
        try:
            estado = _EnCurso(
                unidad=self,
                conexion=conexion,
                dueno=_flujo_actual(),
                solo_lectura=solo_lectura,
            )
            token = _EN_CURSO.set(estado)
        except BaseException:
            # Entre el BEGIN y el bloque: la conexion tiene una transaccion
            # abierta y nadie la usa. Se cierra (QAF-3).
            self._devolver(conexion, descartar=True)
            raise
        try:
            try:
                yield estado
                self._exigir_confirmable(estado)
            except psycopg.Error as error:
                externo = _terminada_afuera(conexion)
                self._revertir(conexion)
                if externo:
                    estado.descartar = True
                    raise _control_externo() from None
                raise traducir_error(error) from None
            except TransaccionInvalidadaError:
                # Ya es el diagnostico (de ``_exigir_confirmable`` o del
                # ejecutor).
                if _terminada_afuera(conexion):
                    estado.descartar = True
                self._revertir(conexion)
                raise
            except Exception as error:
                externo = _terminada_afuera(conexion)
                self._revertir(conexion)
                if externo:
                    estado.descartar = True
                    raise _control_externo() from error
                raise
            except BaseException:
                # KeyboardInterrupt y similares siguen como son; si lo
                # anterior pudo quedar confirmado, al menos queda en el log.
                if _terminada_afuera(conexion):
                    estado.descartar = True
                    logger.error("%s", _control_externo())
                self._revertir(conexion)
                raise
            if solo_lectura:
                self._revertir(conexion)
            else:
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
                self._devolver(conexion, descartar=estado.descartar)

    def _iniciar(self, solo_lectura: bool) -> psycopg.Connection:
        """Una conexion con la transaccion ya abierta (BEGIN + SET LOCAL).

        Si la conexion del pool estaba cortada, se descarta y se toma otra
        una sola vez (M2): todavia no se ejecuto nada del comando. Si la
        otra tambien lo esta, ``PersistenciaSinConexionError`` (QA-E3-2):
        sin mas intentos, y el pool repone las descartadas.
        """
        inicio = self._inicio_lectura if solo_lectura else self._inicio
        for intento in (1, 2):
            conexion = self._tomar_conexion()
            try:
                conexion.execute(inicio)
                return conexion
            except psycopg.Error as error:
                cortada = _conexion_cortada(conexion, error)
                try:
                    self._revertir(conexion)
                except BaseException:
                    # Una interrupcion en la limpieza (QAF-3): este bloque
                    # es un manejador, asi que el ``except BaseException``
                    # de abajo no la ve. La conexion queda dudosa: se cierra
                    # y el contador vuelve atras.
                    self._devolver(conexion, descartar=True)
                    raise
                self._devolver(conexion, descartar=cortada)
                if not cortada:
                    raise traducir_error(error) from None
                logger.warning(
                    "La conexion del pool estaba cortada (SQLSTATE %s): se "
                    "descarta%s.",
                    sqlstate(error) or "desconocido",
                    " y se toma otra" if intento == 1 else "",
                )
                if intento == 2:
                    raise PersistenciaSinConexionError(
                        "Las conexiones a PostgreSQL estaban cortadas: no se "
                        "ejecuto nada; el pool las esta reponiendo."
                    ) from None
            except BaseException:
                # Una interrupcion (KeyboardInterrupt...) en pleno BEGIN deja
                # la conexion en un estado desconocido: se cierra, y el
                # contador vuelve atras.
                self._devolver(conexion, descartar=True)
                raise
        raise AssertionError("inalcanzable")  # pragma: no cover

    @contextmanager
    def _unirse(self, actual: _EnCurso) -> Iterator[None]:
        """Anidada: sin BEGIN ni COMMIT propios; un fallo la invalida."""
        self._exigir_propia(actual)
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
            conexion = self._pool.getconn()
        except PoolTimeout:
            if self._en_uso < self._pool.max_size:
                # Habia lugar en el pool: no se pudo conectar a tiempo.
                raise PersistenciaSinConexionError(
                    "No se pudo establecer una conexion a PostgreSQL a tiempo."
                ) from None
            raise PersistenciaNoDisponibleError(
                "No hubo una conexion libre a PostgreSQL a tiempo."
            ) from None
        except PoolClosed:
            raise PersistenciaError(
                "El pool de PostgreSQL esta cerrado."
            ) from None
        try:
            with self._candado:
                self._en_uso += 1
        except BaseException:
            # Entregada pero no contada: vuelve al pool tal como vino.
            self._pool.putconn(conexion)
            raise
        return conexion

    def _devolver(
        self, conexion: psycopg.Connection, *, descartar: bool
    ) -> None:
        """Devuelve la conexion al pool; si su estado es dudoso, la cierra
        antes (el pool descarta las cerradas). Tambien es dudosa la que no
        quedo fuera de toda transaccion (``IDLE``)."""
        try:
            if not conexion.closed and (
                descartar
                or conexion.info.transaction_status != TransactionStatus.IDLE
            ):
                conexion.close()
        finally:
            with self._candado:
                self._en_uso -= 1
            self._pool.putconn(conexion)

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


# --- Lector y ejecutor restringidos (E3, QA-2 y QA-3) -------------------


class _Lector:
    """Lee dentro de la transaccion a la que esta atado: solo consultas
    registradas como ``LECTURA``. Nunca expone la conexion ni cursores:
    las filas salen materializadas."""

    __slots__ = ("_estado",)
    _MODOS: frozenset[Modo] = frozenset({LECTURA})

    def __init__(self, estado: _EnCurso) -> None:
        self._estado = estado

    def filas(
        self, consulta: Consulta, parametros: Parametros = ()
    ) -> list[Any]:
        return self._correr(consulta, parametros, lambda c: c.fetchall())

    def fila(self, consulta: Consulta, parametros: Parametros = ()) -> Any:
        return self._correr(consulta, parametros, lambda c: c.fetchone())

    def _correr(
        self,
        consulta: Consulta,
        parametros: Parametros,
        resultado: Callable[[psycopg.Cursor], Any],
        *,
        lote: Iterable[Parametros] | None = None,
    ) -> Any:
        registrada = exigir_registrada(consulta)
        estado = self._estado
        if registrada.modo not in self._MODOS:
            # Un error de programacion: no se envia nada y, si la
            # transaccion es la de este flujo, ya no se confirma.
            if _EN_CURSO.get() is estado:
                estado.invalidada = True
            raise TypeError(
                f"La consulta {registrada.nombre} es de escritura: el lector "
                "solo ejecuta consultas registradas como LECTURA."
            )
        conexion = _conexion_vigente(estado)
        try:
            # Binario: protocolo extendido, una sola sentencia por envio.
            with conexion.cursor(
                binary=True, row_factory=namedtuple_row
            ) as cursor:
                if lote is None:
                    cursor.execute(registrada.sql, parametros, binary=True)
                else:
                    cursor.executemany(registrada.sql, lote)
                salida = resultado(cursor)
        except psycopg.Error as error:
            estado.invalidada = True
            raise traducir_error(error) from None
        if _terminada_afuera(conexion):
            # Ninguna consulta registrada termina la transaccion: si paso,
            # el estado de la conexion es dudoso.
            estado.invalidada = True
            estado.descartar = True
            raise _control_externo()
        return salida


class _Ejecutor(_Lector):
    """Lee y escribe dentro de la transaccion de un comando."""

    __slots__ = ()
    _MODOS: frozenset[Modo] = frozenset({LECTURA, ESCRITURA})

    def ejecutar(self, consulta: Consulta, parametros: Parametros = ()) -> int:
        return self._correr(consulta, parametros, lambda c: c.rowcount)

    def ejecutar_lote(
        self, consulta: Consulta, lotes: Iterable[Parametros]
    ) -> None:
        self._correr(consulta, (), lambda c: None, lote=list(lotes))


def _conexion_vigente(estado: _EnCurso) -> psycopg.Connection:
    """La conexion, si el lector o ejecutor todavia puede usarla."""
    if _EN_CURSO.get() is not estado:
        raise PersistenciaError(
            "El lector o ejecutor es de otra transaccion, o de una que ya "
            "termino: hay que pedir uno nuevo a la unidad de trabajo."
        )
    problema = estado.problema()
    if problema:
        raise PersistenciaError(problema)
    conexion = estado.conexion
    situacion = conexion.info.transaction_status
    if estado.invalidada or situacion == TransactionStatus.INERROR:
        raise TransaccionInvalidadaError(
            "La transaccion ya fallo: no se ejecuta nada mas en ella."
        )
    if situacion != TransactionStatus.INTRANS:
        estado.invalidada = True
        estado.descartar = True
        raise TransaccionInvalidadaError(
            "La conexion ya no esta dentro de la transaccion: no se "
            "ejecuta nada mas en ella."
        )
    return conexion


def _conexion_cortada(
    conexion: psycopg.Connection, error: psycopg.Error
) -> bool:
    """Si el error es de una conexion que ya no sirve (no de la consulta)."""
    codigo = sqlstate(error) or ""
    return (
        conexion.closed
        or codigo.startswith(CLASE_CONEXION)
        or codigo in SQLSTATE_CONEXION_CERRADA
    )


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
