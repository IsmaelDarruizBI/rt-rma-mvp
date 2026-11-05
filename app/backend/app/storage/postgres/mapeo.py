"""Reglas de mapeo entre las tablas de PostgreSQL y el dominio (E3).

- Identificador: el ``id`` del dominio es la columna ``codigo`` (en
  ``rma.insumo``, la columna ``clave``: el codigo operativo es otro
  dato). El ``uuid`` tecnico no sale del repository.
- Numeros (DE3-3): ``numeric(p, s)`` devuelve la escala de la columna
  (``80000.00``). El dominio y la API usan el numero tal como se cargo
  en JSON (``80000``): se quitan los ceros de mas, sin pasar por float y
  sin notacion exponencial. El valor no cambia; solo su representacion.
"""

from decimal import Decimal


def decimal_sin_ceros(valor: Decimal) -> Decimal:
    """El mismo numero sin ceros decimales de mas.

    ``80000.00`` -> ``80000``; ``1.500`` -> ``1.5``; ``0.000`` -> ``0``.
    """
    if not isinstance(valor, Decimal):
        raise TypeError(f"Se esperaba un Decimal, no {type(valor).__name__}.")
    if not valor.is_finite():
        raise ValueError(f"Un numero de la base no es finito: {valor}.")
    if valor == valor.to_integral_value():
        return valor.quantize(Decimal(1))
    return valor.normalize()
