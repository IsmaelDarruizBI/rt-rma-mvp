"""Seccion critica de las Ordenes y del inventario del MVP.

Un unico lock de proceso serializa TODA operacion que modifica una Orden
o el stock (E4, MVP v2). Cubre la secuencia completa de cada comando, no
solo la escritura:

    cargar la Orden -> validar -> aplicar los services -> guardar

Si el lock rodeara solo el guardado, dos pedidos podrian leer la misma
version, validar cada uno contra ella y guardar uno detras del otro: el
segundo pisaria al primero sin que nadie se entere. Lo usan:

- ``orden_para_modificar`` (``app.application.modificacion``), por donde
  pasa todo comando que cambia una Orden existente;
- las altas, que numeran ``OR-XXXXXX`` sobre lo persistido;
- PROC-REP-185 (reserva real) y PROC-REP-210 (consumo), que leen las
  reservas de TODAS las Ordenes y reescriben el stock del catalogo.

Es reentrante a proposito: un comando que ya esta en la seccion critica
puede entrar de nuevo (por ejemplo, la reserva dentro de una Orden que se
esta modificando) sin bloquearse a si mismo. Como es el UNICO lock de la
capa de aplicacion, no hay orden de adquisicion que pueda trabarse.

Por debajo, el repository JSON rechaza igual una version obsoleta
(``ConflictoDeEscrituraError``): es la red por si algun camino se salteara
esta seccion.

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
definitiva para operar con varias instancias. Cuando el almacenamiento
deje de ser JSON sobre el filesystem, la exclusion mutua debera
resolverla el motor de persistencia (una transaccion, un
``SELECT ... FOR UPDATE``, un control de version en la base), no este
modulo.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

LOCK_INVENTARIO = threading.RLock()


@contextmanager
def seccion_critica_ordenes() -> Iterator[None]:
    """Serializa la lectura-validacion-escritura de una Orden (E4)."""
    with LOCK_INVENTARIO:
        yield


@contextmanager
def seccion_critica_inventario() -> Iterator[None]:
    """Serializa la lectura-validacion-escritura de stock reservado.

    Es la misma seccion critica que ``seccion_critica_ordenes``: un solo
    lock para Ordenes e inventario. Se conserva el nombre en los comandos
    que, ademas de su Orden, leen las reservas de las demas o reescriben
    el stock del catalogo, para que eso quede explicito:

        cargar Orden -> cargar reservas globales -> validar
        disponibilidad -> generar RESERVA -> guardar Orden
    """
    with LOCK_INVENTARIO:
        yield
