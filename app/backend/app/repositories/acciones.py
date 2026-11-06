"""Contrato del registro de acciones con clave de idempotencia (E6, B1).

Una operacion que crea registros en cada llamada puede llegar con una clave
de idempotencia (encabezado ``Idempotency-Key``). El registro, dentro de la
transaccion del comando:

- ``iniciar``: registra la accion CONFIRMADA con su clave y su huella. Si la
  misma clave ya esta confirmada con la misma huella, devuelve la respuesta
  guardada y el comando no se ejecuta. Con otra huella,
  ``ClaveReutilizadaError``. Si otra solicitud con la misma clave sigue en
  curso, espera a que termine.
- ``completar``: guarda la respuesta que se devolvio, en la misma
  transaccion: se confirma junto con el comando o no se confirma.
- ``rechazar``: despues del ROLLBACK, en otra transaccion, deja la accion
  RECHAZADA para auditoria. No bloquea un reintento con la misma clave.

Solo PostgreSQL lo implementa: JSON no tiene registro de acciones y el
contexto lo deja en ``None`` (la clave se ignora). Diseno:
``docs/postgresql/e4-e7-diseno-integrado.md`` (secciones 6 y 20).
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RespuestaGuardada:
    """La respuesta HTTP de una operacion ya confirmada."""

    estado: int
    cuerpo: Any


class RegistroDeAcciones(Protocol):
    def iniciar(
        self, *, operacion: str, usuario_id: str, clave: str, huella: str
    ) -> RespuestaGuardada | None:
        """``None``: la operacion es nueva y el comando sigue."""
        ...

    def completar(
        self, *, respuesta: RespuestaGuardada, orden_id: str | None
    ) -> None: ...

    def recuperar(
        self, *, operacion: str, usuario_id: str, clave: str, huella: str
    ) -> RespuestaGuardada | None:
        """Con otra conexion, la respuesta confirmada de esa clave y huella
        (B2: despues de un COMMIT incierto). ``None``: no aparece."""
        ...

    def rechazar(
        self,
        *,
        operacion: str,
        usuario_id: str,
        clave: str,
        huella: str,
        motivo: str,
        respuesta: RespuestaGuardada,
    ) -> None: ...
