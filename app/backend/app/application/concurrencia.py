"""Unidad de trabajo JSON: la seccion critica de Ordenes e inventario.

Un unico lock de proceso serializa TODA operacion que modifica una Orden
o el stock (E4, MVP v2). Los casos de uso lo toman con
``contexto.transaccion()`` (E1), que con JSON es este lock. Cubre la
secuencia completa de cada comando, no solo la escritura:

    cargar la Orden -> validar -> aplicar los services -> guardar

Si el lock rodeara solo el guardado, dos pedidos podrian leer la misma
version, validar cada uno contra ella y guardar uno detras del otro: el
segundo pisaria al primero sin que nadie se entere. Lo usan:

- ``orden_para_modificar`` (``app.application.modificacion``), por donde
  pasa todo comando que cambia una Orden existente;
- las altas, que numeran ``OR-XXXXXX`` sobre lo persistido;
- los comandos que leen las reservas de TODAS las Ordenes o reescriben el
  stock del catalogo: PROC-REP-185 (reserva real), PROC-REP-210
  (consumo), la autorizacion del cliente, la redefinicion, los recursos,
  el ingreso inicial, la revalidacion y los movimientos operativos. Abren
  ``contexto.transaccion()`` antes de ``orden_para_modificar``: con
  PostgreSQL, esos son los que tendran que bloquear tambien los insumos.

Es reentrante a proposito: un comando que ya esta en la seccion critica
puede entrar de nuevo (por ejemplo, la reserva dentro de una Orden que se
esta modificando) sin bloquearse a si mismo. Como es el UNICO lock de la
capa de aplicacion, no hay orden de adquisicion que pueda trabarse.

Por debajo, el repository JSON rechaza igual una version obsoleta
(``ConflictoDeEscrituraError``): es la red por si algun camino se salteara
esta seccion.

LO QUE NO GARANTIZA
-------------------
Exclusion mutua no es atomicidad. Una operacion que escribe varios
archivos (el consumo escribe el stock y despues la Orden) puede quedar a
mitad si falla en el medio: nada se revierte solo, y por eso PROC-REP-210
compensa el stock a mano. La unidad de trabajo PostgreSQL si revierte
todo; esta no.

ALCANCE Y LIMITACION DELIBERADA
-------------------------------
``LOCK_INVENTARIO`` es un ``threading.RLock`` de modulo: protege la
concurrencia DENTRO DE UN UNICO PROCESO Python. No es un lock
distribuido y no protege nada si el backend corre con varios workers,
varias instancias o varios contenedores apuntando al mismo directorio de
datos.

Por eso el MVP se sirve con **un solo worker de uvicorn**:

    uvicorn app.main:app --workers 1

JSON es el almacenamiento de las pruebas funcionales, no la solucion
definitiva para operar con varias instancias. Con PostgreSQL la exclusion
mutua la resuelve la base (una transaccion, un ``SELECT ... FOR
UPDATE``), no este modulo.
"""

import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

LOCK_INVENTARIO = threading.RLock()


class UnidadDeTrabajoJson:
    """Exclusion mutua de proceso con el contrato de ``UnidadDeTrabajo``.

    Todas las instancias que comparten un lock son la misma seccion
    critica: por defecto, ``LOCK_INVENTARIO``, como antes de E1.
    """

    def __init__(self, lock: threading.RLock = LOCK_INVENTARIO) -> None:
        self._lock = lock
        # Profundidad por hilo: el RLock tambien es por hilo.
        self._local = threading.local()

    @contextmanager
    def transaccion(self) -> Iterator[None]:
        """Toma el lock (reentrante) hasta el final del bloque."""
        with self._lock:
            self._local.nivel = self._nivel() + 1
            try:
                yield
            finally:
                self._local.nivel -= 1

    def lectura_consistente(self) -> AbstractContextManager[None]:
        """La seccion critica: una escritura no se mete en el medio."""
        return self.transaccion()

    def en_curso(self) -> bool:
        """Si este hilo esta dentro de la seccion critica."""
        return self._nivel() > 0

    def _nivel(self) -> int:
        return getattr(self._local, "nivel", 0)


# La seccion critica unica de la aplicacion con JSON.
UNIDAD_DE_TRABAJO_JSON = UnidadDeTrabajoJson()
