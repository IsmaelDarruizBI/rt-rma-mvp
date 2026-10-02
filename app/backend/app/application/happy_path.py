"""Fachada de compatibilidad: lectura del avance de una Orden.

Hasta Slice 0 (MVP v2 - Foundation) este modulo concentraba el progreso
y las acciones disponibles, ambos acoplados a HP-REP-001 por diseno. Se
dividio en dos modulos generalizables por Origen:

    ``application.progreso``   -> ``progreso()``, ``PasoProgreso``
    ``application.acciones``   -> ``acciones_disponibles()``,
                                   ``AccionDisponible``

Este modulo se conserva como fachada -no se elimina- porque no vale la
pena romper importaciones existentes por una reorganizacion interna:
``NODOS_HAPPY_PATH`` sigue siendo la ruta de HP-REP-001 (ahora vive en
``application.progreso`` como la entrada de CLIENTE_EXTERNO de
``_RUTAS_POR_ORIGEN``), y las demas funciones se re-exportan tal cual.
"""

from .acciones import (
    ACCION_AGREGAR_DETALLE,
    ACCION_APROBAR_CONTROL,
    ACCION_COMPLETAR_EJECUCION,
    ACCION_ENCOLAR,
    ACCION_ENTREGAR,
    ACCION_INICIAR_DETALLE,
    ACCION_NOTIFICAR,
    ACCION_REGISTRAR_PAGO,
    ACCION_TOMAR,
    AccionDisponible,
    acciones_disponibles,
    detalle_trabajable,
)
from .progreso import _RUTA_CLIENTE_EXTERNO as NODOS_HAPPY_PATH
from .progreso import PasoProgreso as PasoHappyPath
from .progreso import nodos_alcanzados, progreso

__all__ = [
    "NODOS_HAPPY_PATH",
    "PasoHappyPath",
    "ACCION_AGREGAR_DETALLE",
    "ACCION_ENCOLAR",
    "ACCION_TOMAR",
    "ACCION_INICIAR_DETALLE",
    "ACCION_COMPLETAR_EJECUCION",
    "ACCION_APROBAR_CONTROL",
    "ACCION_NOTIFICAR",
    "ACCION_REGISTRAR_PAGO",
    "ACCION_ENTREGAR",
    "AccionDisponible",
    "nodos_alcanzados",
    "progreso",
    "detalle_trabajable",
    "acciones_disponibles",
]
