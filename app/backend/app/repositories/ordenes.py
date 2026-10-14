"""Contrato de persistencia de Ordenes de Reparacion.

Define QUE necesita la aplicacion, nunca COMO se guarda. La
implementacion JSON vive en ``app.storage.json``; manana puede ser
Cloud Storage o una base de datos sin que el dominio ni los services se
enteren.
"""

from typing import Protocol, runtime_checkable

from app.domain.models import OrdenReparacion


@runtime_checkable
class OrdenReparacionRepository(Protocol):
    """Acceso a las Ordenes persistidas."""

    def obtener(self, orden_id: str) -> OrdenReparacion:
        """Devuelve la Orden.

        Lanza ``EntidadPersistidaNoEncontradaError`` si no existe.
        """
        ...

    def guardar(self, orden: OrdenReparacion) -> None:
        """Crea la Orden o reemplaza la version guardada.

        Es idempotente: guardar dos veces la misma Orden deja una sola
        copia.

        Nunca pisa en silencio otra escritura (E4): si la version guardada
        cambio desde que se leyo la que llega -o ya esta cerrada-, lanza
        ``ConflictoDeEscrituraError`` y no escribe nada.
        """
        ...

    def listar(self) -> list[OrdenReparacion]:
        """Devuelve todas las Ordenes persistidas."""
        ...
