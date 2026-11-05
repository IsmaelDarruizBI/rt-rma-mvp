"""``ModelosEquipoRepository`` sobre PostgreSQL (E3).

Lee ``rma.modelo_equipo``, cargado desde el mismo JSON que usa la
implementacion JSON (``app/datos/modelos_equipo.json``). Orden del
catalogo: por codigo (``MOD-0001``...), que es el orden del archivo.
Los modelos inactivos tambien se devuelven: una Orden puede
referenciarlos.
"""

from app.domain.models import ModeloEquipo

from .consultas import LECTURA, consulta
from .transaccion import UnidadDeTrabajoPostgres

_COLUMNAS = """
    SELECT codigo, marca, modelo, variante, numeros_modelo, activo
    FROM rma.modelo_equipo
"""
_MODELOS = consulta(
    "modelos_equipo.listar",
    _COLUMNAS
    + """
    ORDER BY codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_MODELO = consulta(
    "modelos_equipo.obtener",
    _COLUMNAS
    + """
    WHERE codigo = %(codigo)s
    """,
    modo=LECTURA,
)


class PostgresModelosEquipoRepository:
    """Implementa ``ModelosEquipoRepository`` sobre la base."""

    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    def listar_modelos(self) -> list[ModeloEquipo]:
        with self._unidad.lectura() as lector:
            return [_modelo(f) for f in lector.filas(_MODELOS)]

    def obtener_modelo(self, modelo_id: str) -> ModeloEquipo | None:
        with self._unidad.lectura() as lector:
            fila = lector.fila(_MODELO, {"codigo": modelo_id})
        return _modelo(fila) if fila is not None else None


def _modelo(f) -> ModeloEquipo:
    return ModeloEquipo(
        id=f.codigo,
        marca=f.marca,
        modelo=f.modelo,
        variante=f.variante,
        numeros_modelo=tuple(f.numeros_modelo),
        activo=f.activo,
    )
