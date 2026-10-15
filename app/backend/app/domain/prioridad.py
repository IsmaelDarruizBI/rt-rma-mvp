"""Prioridad de la Orden (PROC-REP-150): una sola convencion.

| Valor | Significado |
|---|---|
| 1 | Urgente: maxima prioridad |
| 2 | Alta |
| 3 | Media |
| 4 | Normal: la predeterminada |

Cuanto menor el numero, mayor la prioridad. Es la unica interpretacion:
el frontend recibe la tabla por ``GET /api/catalogs/priorities`` y cada
Orden del listado trae su texto («Prioridad 1 · Urgente») y su lugar en
este criterio, asi que no la vuelve a interpretar.

``OrdenReparacion.prioridad == 0`` significa "todavia sin prioridad": es
el valor anterior a PROC-REP-150, no una prioridad. La predeterminada (4)
solo se propone al priorizar; nunca se asigna antes.

Datos historicos: un valor fuera de 1-4 guardado antes de esta convencion
se conserva tal cual -no se migra ni se invierte-. Se muestra como fuera
de la escala y, al ordenar, va despues de 4 (de menor a mayor) y antes de
las Ordenes sin prioridad. Solo las priorizaciones nuevas se validan
contra 1-4.
"""

from datetime import datetime

from .models import OrdenReparacion
from .models.enums import EstadoWorkflow

PRIORIDAD_URGENTE = 1
PRIORIDAD_NORMAL = 4
PRIORIDAD_PREDETERMINADA = PRIORIDAD_NORMAL
SIN_PRIORIDAD = 0

NOMBRES_DE_PRIORIDAD: dict[int, str] = {
    1: "Urgente",
    2: "Alta",
    3: "Media",
    4: "Normal",
}

FUERA_DE_ESCALA = "Fuera de la escala 1-4"


def es_prioridad_valida(valor: int) -> bool:
    """Admitida para una priorizacion nueva (PROC-REP-150)."""
    return valor in NOMBRES_DE_PRIORIDAD


def nombre_de_prioridad(valor: int) -> str | None:
    """«Urgente», «Normal»...; ``None`` si la Orden no tiene prioridad."""
    if valor == SIN_PRIORIDAD:
        return None
    return NOMBRES_DE_PRIORIDAD.get(valor, FUERA_DE_ESCALA)


def texto_de_prioridad(valor: int) -> str | None:
    """«Prioridad 1 · Urgente»; ``None`` si no tiene prioridad."""
    nombre = nombre_de_prioridad(valor)
    return f"Prioridad {valor} · {nombre}" if nombre else None


def prioridad_vigente(orden: OrdenReparacion) -> int | None:
    """La prioridad que cuenta para ordenar el trabajo.

    ``None`` si la Orden no se priorizo, ya cerro o se cancelo: ahi su
    prioridad es historia, no un orden de atencion. No modifica la Orden.
    """
    if (
        orden.prioridad == SIN_PRIORIDAD
        or orden.esta_cerrada
        or orden.estado_workflow is EstadoWorkflow.CANCELADA
    ):
        return None
    return orden.prioridad


def clave_de_prioridad(
    orden: OrdenReparacion,
) -> tuple[bool, int, datetime, str]:
    """Criterio unico para ordenar por prioridad (listado y cola de taller).

    Primero 1, despues 2, 3 y 4 (y los valores historicos mayores); al
    final las Ordenes sin prioridad vigente. Con la misma prioridad va
    primero la que ingreso antes y, a igual ingreso, el menor numero de
    Orden: el resultado es estable.
    """
    vigente = prioridad_vigente(orden)
    return (vigente is None, vigente or 0, orden.created_at, orden.id)
