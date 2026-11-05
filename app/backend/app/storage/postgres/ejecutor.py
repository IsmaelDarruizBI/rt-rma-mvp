"""Contrato del ejecutor SQL restringido de los repositories (E3).

Los repositories PostgreSQL nunca reciben una conexion de psycopg: piden
a la unidad de trabajo un lector (``lectura()``) o un ejecutor
(``ejecutor()``) y le pasan consultas registradas
(``app.storage.postgres.consultas``) con sus parametros. La
implementacion vive en ``transaccion.py``, junto a la transaccion que
controla.

En cada operacion se verifica que la transaccion siga vigente, que la
use el flujo que la abrio y que el lector o ejecutor sea de ESTA
transaccion (uno guardado de una anterior se rechaza). Si una operacion
falla, la transaccion queda invalidada: lo que siga se rechaza sin ir al
servidor y la unidad de trabajo revierte todo. Los resultados son filas
materializadas (tuplas con nombre), nunca cursores.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple, Protocol

from .consultas import Consulta

Parametros = Sequence[Any] | Mapping[str, Any]
Fila = NamedTuple


class LectorSql(Protocol):
    """Solo lectura: ejecuta unicamente consultas registradas como
    ``LECTURA`` (una de ``ESCRITURA`` se rechaza sin enviarla e invalida
    la transaccion) y no cambia el caracter de la transaccion que usa."""

    def filas(
        self, consulta: Consulta, parametros: Parametros = ()
    ) -> list[Any]:
        """Todas las filas del resultado, materializadas."""
        ...

    def fila(self, consulta: Consulta, parametros: Parametros = ()) -> Any:
        """La primera fila, o ``None`` si no hay ninguna."""
        ...


class EjecutorSql(LectorSql, Protocol):
    """Lectura y escritura dentro de la transaccion de un comando."""

    def ejecutar(self, consulta: Consulta, parametros: Parametros = ()) -> int:
        """Ejecuta y devuelve la cantidad de filas afectadas."""
        ...

    def ejecutar_lote(
        self, consulta: Consulta, lotes: Iterable[Parametros]
    ) -> None:
        """La misma consulta con cada juego de parametros."""
        ...
