"""Accion del comando: el registro que exigen eventos y movimientos (E4).

En el esquema, cada evento del historial (``rma.evento_negocio``) y cada
movimiento de inventario referencian una ``rma.accion_usuario``
CONFIRMADA (columna ``accion_id NOT NULL``). Durante el Bloque A la crea
el repository la primera vez que la necesita en la transaccion (DA-3):
una sola por comando, sin clave de idempotencia, con el usuario de lo que
se esta registrando o, si no hay usuario, como proceso del sistema.

Se inserta dentro de la transaccion que la usa: si el comando se
revierte, la accion tambien (no quedan acciones huerfanas). En E6 la
capa de aplicacion la declarara de forma explicita, con su clave de
idempotencia y la respuesta del comando; esta misma fila es la que se
completara entonces.

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (DA-3, seccion 6).
"""

from typing import Any
from uuid import UUID

from .consultas import ESCRITURA, consulta
from .ejecutor import EjecutorSql
from .transaccion import UnidadDeTrabajoPostgres

PROCESO_SISTEMA = "SISTEMA"
_CLAVE = "accion_del_comando"

_REGISTRAR = consulta(
    "acciones.registrar_tecnica",
    """
    INSERT INTO rma.accion_usuario
        (usuario_id, proceso, operacion, resultado, orden_id)
    VALUES
        (%(usuario)s, %(proceso)s, %(operacion)s, 'CONFIRMADA', %(orden)s)
    RETURNING id
    """,
    modo=ESCRITURA,
)


def accion_del_comando(
    unidad: UnidadDeTrabajoPostgres,
    ejecutor: EjecutorSql,
    *,
    operacion: str,
    usuario: UUID | None,
    orden: UUID | None,
) -> UUID:
    """La accion CONFIRMADA de la transaccion en curso; la crea la primera
    vez. ``usuario`` es el responsable (``None``: proceso del sistema)."""
    datos: dict[str, Any] = unidad.datos_de_transaccion()
    accion = datos.get(_CLAVE)
    if accion is None:
        fila = ejecutor.fila(
            _REGISTRAR,
            {
                "usuario": usuario,
                "proceso": None if usuario else PROCESO_SISTEMA,
                "operacion": operacion,
                "orden": orden,
            },
        )
        accion = datos[_CLAVE] = fila.id
    return accion
