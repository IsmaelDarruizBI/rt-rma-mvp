"""Unidad de trabajo: el limite transaccional de un comando (E1).

Todo comando que lee, valida y escribe lo hace dentro de una sola
transaccion, abierta por el caso de uso:

    with contexto.transaccion():
        cargar -> validar -> aplicar los services -> guardar

Contrato comun a todas las implementaciones:

- Reentrante: una transaccion abierta dentro de otra se une a la
  exterior. No hay savepoints; solo la exterior termina la transaccion.
- Se abre en la capa de aplicacion, nunca en una dependencia de FastAPI.
- Adentro no se llama a servicios externos (fotos, fuente por DNI,
  catalogo de Ventas): una llamada lenta retendria bloqueos y una
  reversion no la deshace.
- Solo la unidad de trabajo controla la transaccion (BEGIN, COMMIT,
  ROLLBACK). Los repositories nunca confirman ni revierten, ni ejecutan
  SQL de control transaccional.
- La transaccion es del flujo que la abrio: una tarea o un hilo creados
  dentro de ella (que heredan el contexto) no la usan, ni mientras sigue
  abierta ni despues. Mientras sigue abierta tampoco pueden abrir otra;
  cuando termino, abren la suya.

Lo que garantiza cada implementacion es distinto, y no se presume mas:

- JSON (``app.application.concurrencia``): exclusion mutua dentro del
  proceso. NO es atomica: lo escrito antes de un fallo queda escrito.
- PostgreSQL (``app.storage.postgres.transaccion``): una transaccion de
  la base, con COMMIT o ROLLBACK de todo, mientras nadie mas la controle.
"""

from contextlib import AbstractContextManager
from typing import Protocol


class UnidadDeTrabajo(Protocol):
    """Abre transacciones y sabe si hay una en curso."""

    def transaccion(self) -> AbstractContextManager[None]:
        """Transaccion nueva, o la que ya esta en curso (reentrante)."""
        ...

    def en_curso(self) -> bool:
        """Si quien llama esta dentro de una transaccion."""
        ...
