"""Codigos automaticos de catalogos y compras (Configuracion v2, CFG-01).

Los genera la base: ``rma.siguiente_codigo(prefijo)`` toma el numero
siguiente de la secuencia del prefijo, lo formatea sin truncar y saltea
los codigos ya usados (cargados a mano o por un backend anterior). La
secuencia nunca repite, asi que dos altas concurrentes reciben codigos
distintos sin bloquear filas; un alta que falla deja un hueco (aprobado).

Se pide dentro de la transaccion del alta: ``nextval`` no funciona en una
transaccion de solo lectura.
"""

from .consultas import ESCRITURA, consulta
from .transaccion import UnidadDeTrabajoPostgres

PREFIJOS = frozenset(
    {"TR", "CANC", "INT", "INS", "PRV", "CHK", "SC", "OC", "RGA", "MOD"}
)

_SIGUIENTE = consulta(
    "codigos.siguiente",
    "SELECT rma.siguiente_codigo(%(prefijo)s) AS codigo",
    modo=ESCRITURA,
)


def reservar_codigo(unidad: UnidadDeTrabajoPostgres, prefijo: str) -> str:
    """El codigo siguiente libre de ``prefijo`` (``TR-003``, ``OC-000014``)."""
    if prefijo not in PREFIJOS:
        raise ValueError(f"Prefijo de codigo desconocido: {prefijo}")
    fila = unidad.ejecutor().fila(_SIGUIENTE, {"prefijo": prefijo})
    return fila.codigo
