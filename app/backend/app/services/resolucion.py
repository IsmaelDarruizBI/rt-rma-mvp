"""Resolver puro de la situacion agregada de la Orden (BR-REP-012, 211).

BR-REP-012 define la matriz completa de prioridad sobre propiedades
derivadas de los Detalles:

    0. cantidad_detalles == 0                    -> SIN_DETALLES
    1. todos terminales y todos cancelados        -> TODO_CANCELADO
    2. todos terminales, al menos uno completo    -> COMPLETA
    3. existe un Detalle en ejecucion             -> EN_EJECUCION
    4. existe un Detalle trabajable               -> ABIERTA_TRABAJABLE
    5. ninguno trabajable, alguno requiere        -> REQUIERE_REVISION
       revision
    6. ninguno trabajable, alguno bloqueado       -> PENDIENTE_RECURSOS
       por recursos
    fail-safe: nada de lo anterior aplica         -> CONTEXTO_INCONSISTENTE
    con detalles > 0

``resolver_situacion_orden`` es la unica funcion de este modulo: pura,
determinista y sin excepciones para ningun resultado de negocio
legitimo. ``CONTEXTO_INCONSISTENTE`` es el fail-safe TECNICO para una
combinacion que la invariante del dominio no deberia producir -no un
estado de negocio-, y tampoco lanza: un estado legitimo o inconsistente
siempre puede CLASIFICARSE, lo que se haga con esa clasificacion es
responsabilidad de quien la use
(``app.services.ordenes.evaluar_situacion_orden`` para PROC-REP-211).

``TODO_CANCELADO`` (prioridad 1) depende de que un Detalle pueda estar
CANCELADO. La Cancelacion (BR-REP-014, FEAT-REP-009) esta fuera del
scope de MVP v2: ``EstadoReparacionDetail`` no tiene ese valor todavia,
asi que esta rama queda formalmente completa -fiel a la matriz del
contrato- pero inalcanzable con el catalogo actual.
"""

from collections.abc import Sequence
from enum import Enum

from app.domain.models import (
    CondicionReparacionDetail,
    EstadoReparacionDetail,
    ReparacionDetail,
)


class ResultadoEvaluacionOrden(str, Enum):
    """Los ocho resultados que BR-REP-012 contempla para PROC-REP-211.

    Que este resolver sepa clasificar un resultado no significa que
    exista un comando de la API que lo alcance: en Slice 0 solo
    ``COMPLETA`` es alcanzable end-to-end. Los demas ya estan
    clasificados y testeados para que los slices que conectan
    EXC-REP-001..004, VAR-REP-003 y la Cancelacion no tengan que tocar
    el resolver.
    """

    SIN_DETALLES = "SIN_DETALLES"
    TODO_CANCELADO = "TODO_CANCELADO"
    COMPLETA = "COMPLETA"
    EN_EJECUCION = "EN_EJECUCION"
    ABIERTA_TRABAJABLE = "ABIERTA_TRABAJABLE"
    REQUIERE_REVISION = "REQUIERE_REVISION"
    PENDIENTE_RECURSOS = "PENDIENTE_RECURSOS"
    CONTEXTO_INCONSISTENTE = "CONTEXTO_INCONSISTENTE"


def _es_completo(detalle: ReparacionDetail) -> bool:
    return detalle.estado is EstadoReparacionDetail.COMPLETO


def _es_cancelado(detalle: ReparacionDetail) -> bool:
    # Reservado para BR-REP-014 (Cancelacion, fuera de MVP v2):
    # EstadoReparacionDetail todavia no tiene un valor CANCELADO, asi
    # que ningun Detalle real puede cumplir esto hoy.
    return False


def _es_terminal(detalle: ReparacionDetail) -> bool:
    return _es_completo(detalle) or _es_cancelado(detalle)


def _esta_en_ejecucion(detalle: ReparacionDetail) -> bool:
    return detalle.estado is EstadoReparacionDetail.EN_PROGRESO


def _es_trabajable(detalle: ReparacionDetail) -> bool:
    return (
        detalle.estado is EstadoReparacionDetail.DEFINIDO
        and detalle.condicion is CondicionReparacionDetail.SIN_BLOQUEO
    )


def _requiere_revision(detalle: ReparacionDetail) -> bool:
    return (
        detalle.estado is EstadoReparacionDetail.DEFINIDO
        and detalle.condicion is CondicionReparacionDetail.REQUIERE_DEFINICION
    )


def _bloqueado_por_recursos(detalle: ReparacionDetail) -> bool:
    return (
        detalle.estado is EstadoReparacionDetail.DEFINIDO
        and detalle.condicion
        is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    )


def resolver_situacion_orden(
    detalles: Sequence[ReparacionDetail],
) -> ResultadoEvaluacionOrden:
    """Clasifica la situacion agregada segun la matriz de BR-REP-012.

    Funcion pura: no recibe la Orden, no la modifica, no registra nada
    en el historial y no lanza excepciones por un resultado de negocio
    legitimo. Aplicar ese resultado -registrar el paso, decidir si se
    cierra la toma activa- es responsabilidad de quien la invoca.
    """
    if not detalles:
        return ResultadoEvaluacionOrden.SIN_DETALLES

    todos_terminales = all(_es_terminal(detalle) for detalle in detalles)

    if todos_terminales:
        if all(_es_cancelado(detalle) for detalle in detalles):
            return ResultadoEvaluacionOrden.TODO_CANCELADO
        if any(_es_completo(detalle) for detalle in detalles):
            return ResultadoEvaluacionOrden.COMPLETA
        # Todos terminales, ninguno completo ni cancelado: con el
        # catalogo actual (sin CANCELADO) esto es inalcanzable, pero se
        # deja clasificado en vez de asumido para no ocultar una futura
        # invariante rota.
        return ResultadoEvaluacionOrden.CONTEXTO_INCONSISTENTE

    if any(_esta_en_ejecucion(detalle) for detalle in detalles):
        return ResultadoEvaluacionOrden.EN_EJECUCION

    if any(_es_trabajable(detalle) for detalle in detalles):
        return ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE

    if any(_requiere_revision(detalle) for detalle in detalles):
        return ResultadoEvaluacionOrden.REQUIERE_REVISION

    if any(_bloqueado_por_recursos(detalle) for detalle in detalles):
        return ResultadoEvaluacionOrden.PENDIENTE_RECURSOS

    return ResultadoEvaluacionOrden.CONTEXTO_INCONSISTENTE
