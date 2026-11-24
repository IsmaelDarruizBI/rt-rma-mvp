"""Stock minimo por insumo (DEC-AJ-11, BR-REP-049).

Funciones puras, la unica fuente de la regla para Inventario, Inicio y
Compras:

    SIN_MINIMO                         el insumo no tiene minimo: no alerta
    SUFICIENTE                         disponible >= minimo
    BAJO_MINIMO                        disponible < minimo y lo pedido no
                                       alcanza (disponible + en camino <
                                       minimo)
    BAJO_MINIMO_REPOSICION_SOLICITADA  disponible < minimo, pero lo pedido
                                       lo cubre (disponible + en camino >=
                                       minimo)

- Se compara con el DISPONIBLE (fisico - reservado pendiente), no solo con
  el fisico (D-11.1).
- «En camino» es lo que ya calcula Compras: solicitudes pendientes y
  Ordenes de compra en borrador, confirmadas o parciales, por lo que falta
  recibir (11.1, resolucion del punto 7). En el modo JSON no hay Compras:
  en camino es cero.
- No es un faltante: el faltante (disponible o fisico negativos) sigue
  aparte y sin cambios (``SituacionInsumo.faltante``).
"""

from collections.abc import Mapping
from decimal import Decimal
from enum import Enum

CERO = Decimal("0")


class EstadoReposicion(str, Enum):
    SIN_MINIMO = "SIN_MINIMO"
    SUFICIENTE = "SUFICIENTE"
    BAJO_MINIMO = "BAJO_MINIMO"
    BAJO_MINIMO_REPOSICION_SOLICITADA = "BAJO_MINIMO_REPOSICION_SOLICITADA"


ESTADOS_BAJO_MINIMO = (
    EstadoReposicion.BAJO_MINIMO,
    EstadoReposicion.BAJO_MINIMO_REPOSICION_SOLICITADA,
)


def estado_reposicion(
    *,
    stock_minimo: Decimal | None,
    disponible: Decimal,
    en_camino: Decimal = CERO,
) -> EstadoReposicion:
    """Estado del insumo frente a su minimo (ver el docstring del modulo)."""
    if stock_minimo is None:
        return EstadoReposicion.SIN_MINIMO
    if disponible >= stock_minimo:
        return EstadoReposicion.SUFICIENTE
    if disponible + max(en_camino, CERO) >= stock_minimo:
        return EstadoReposicion.BAJO_MINIMO_REPOSICION_SOLICITADA
    return EstadoReposicion.BAJO_MINIMO


def bajo_minimo(estado: EstadoReposicion) -> bool:
    return estado in ESTADOS_BAJO_MINIMO


def cantidad_a_reponer(
    *,
    stock_minimo: Decimal | None,
    demanda: Decimal,
    disponible: Decimal,
    en_camino: Decimal,
) -> tuple[Decimal, Decimal]:
    """Cuanto sugerir comprar, separado por causa: ``(por_faltante,
    por_minimo)``. Su suma es la cantidad sugerida.

    - Sin minimo: la formula de siempre, ``demanda - disponible - en
      camino`` si es positiva (todo es faltante).
    - Con minimo: ``max(0, demanda + minimo - disponible - en camino)``.
      La parte por faltante es lo que pide la demanda sola; el resto es
      la reposicion hasta el minimo.

    Lo que ya esta en camino (solicitudes pendientes y Ordenes de compra
    abiertas) se descuenta: no se duplican solicitudes.
    """
    por_faltante = max(demanda - disponible - en_camino, CERO)
    if stock_minimo is None:
        return por_faltante, CERO
    total = max(demanda + stock_minimo - disponible - en_camino, CERO)
    return por_faltante, total - por_faltante


def en_camino_de(
    en_camino: Mapping[str, Decimal] | None, insumo_id: str
) -> Decimal:
    return (en_camino or {}).get(insumo_id, CERO)
