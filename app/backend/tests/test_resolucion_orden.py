"""Suite unitaria de ``resolver_situacion_orden`` (BR-REP-012).

Cubre la matriz de prioridad completa del contrato, incluidas las
combinaciones que HP-REP-001 todavia no puede alcanzar por API. Es una
funcion pura sobre una lista de Detalles, asi que se construyen
directamente -sin Orden, sin services, sin fecha- con el minimo de
campos que ``ReparacionDetail`` exige.
"""

from decimal import Decimal
from types import SimpleNamespace

from app.domain.models import (
    CondicionReparacionDetail,
    EstadoReparacionDetail,
    ReparacionDetail,
)
from app.services.resolucion import (
    ResultadoEvaluacionOrden,
    resolver_situacion_orden,
)

SIN_BLOQUEO = CondicionReparacionDetail.SIN_BLOQUEO
REQUIERE_DEFINICION = CondicionReparacionDetail.REQUIERE_DEFINICION
BLOQUEADO_POR_RECURSOS = CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS


def _detalle(
    *,
    id: str = "DET-001",
    estado: EstadoReparacionDetail = EstadoReparacionDetail.DEFINIDO,
    condicion: CondicionReparacionDetail = SIN_BLOQUEO,
) -> ReparacionDetail:
    return ReparacionDetail(
        id=id,
        tipo_reparacion_id="TREP-001",
        precio=Decimal("0"),
        puntaje=0,
        garantia_dias=0,
        estado=estado,
        condicion=condicion,
    )


# --- Prioridad 0: SIN_DETALLES ------------------------------------------


def test_sin_detalles():
    assert resolver_situacion_orden([]) == (
        ResultadoEvaluacionOrden.SIN_DETALLES
    )


# --- Prioridad 2: COMPLETA -----------------------------------------------


def test_un_detalle_completo():
    detalle = _detalle(estado=EstadoReparacionDetail.COMPLETO)
    assert resolver_situacion_orden([detalle]) == (
        ResultadoEvaluacionOrden.COMPLETA
    )


def test_varios_detalles_todos_completos():
    detalles = [
        _detalle(id="DET-001", estado=EstadoReparacionDetail.COMPLETO),
        _detalle(id="DET-002", estado=EstadoReparacionDetail.COMPLETO),
    ]
    assert resolver_situacion_orden(detalles) == (
        ResultadoEvaluacionOrden.COMPLETA
    )


# --- Prioridad 3: EN_EJECUCION --------------------------------------------


def test_un_detalle_en_ejecucion():
    detalle = _detalle(estado=EstadoReparacionDetail.EN_PROGRESO)
    assert resolver_situacion_orden([detalle]) == (
        ResultadoEvaluacionOrden.EN_EJECUCION
    )


def test_en_ejecucion_tiene_prioridad_sobre_trabajable():
    en_ejecucion = _detalle(
        id="DET-001", estado=EstadoReparacionDetail.EN_PROGRESO
    )
    trabajable = _detalle(id="DET-002", condicion=SIN_BLOQUEO)
    assert resolver_situacion_orden([en_ejecucion, trabajable]) == (
        ResultadoEvaluacionOrden.EN_EJECUCION
    )


# --- Prioridad 4: ABIERTA_TRABAJABLE --------------------------------------


def test_un_detalle_trabajable():
    detalle = _detalle(condicion=SIN_BLOQUEO)
    assert resolver_situacion_orden([detalle]) == (
        ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE
    )


def test_un_completo_y_un_trabajable_es_abierta_trabajable():
    """No todos terminales: el trabajable manda, no se mezcla con COMPLETA."""
    completo = _detalle(id="DET-001", estado=EstadoReparacionDetail.COMPLETO)
    trabajable = _detalle(id="DET-002", condicion=SIN_BLOQUEO)
    assert resolver_situacion_orden([completo, trabajable]) == (
        ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE
    )


def test_trabajable_tiene_prioridad_sobre_requiere_revision():
    trabajable = _detalle(id="DET-001", condicion=SIN_BLOQUEO)
    requiere_revision = _detalle(id="DET-002", condicion=REQUIERE_DEFINICION)
    assert resolver_situacion_orden([trabajable, requiere_revision]) == (
        ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE
    )


# --- Prioridad 5: REQUIERE_REVISION ---------------------------------------


def test_un_detalle_requiere_revision():
    detalle = _detalle(condicion=REQUIERE_DEFINICION)
    assert resolver_situacion_orden([detalle]) == (
        ResultadoEvaluacionOrden.REQUIERE_REVISION
    )


def test_requiere_revision_tiene_prioridad_sobre_pendiente_recursos():
    requiere_revision = _detalle(id="DET-001", condicion=REQUIERE_DEFINICION)
    bloqueado = _detalle(id="DET-002", condicion=BLOQUEADO_POR_RECURSOS)
    assert resolver_situacion_orden([requiere_revision, bloqueado]) == (
        ResultadoEvaluacionOrden.REQUIERE_REVISION
    )


# --- Prioridad 6: PENDIENTE_RECURSOS --------------------------------------


def test_un_detalle_bloqueado_por_recursos():
    detalle = _detalle(condicion=BLOQUEADO_POR_RECURSOS)
    assert resolver_situacion_orden([detalle]) == (
        ResultadoEvaluacionOrden.PENDIENTE_RECURSOS
    )


# --- Fail-safe: CONTEXTO_INCONSISTENTE ------------------------------------


def test_contexto_inconsistente_es_el_fail_safe_sin_lanzar():
    """Una combinacion imposible con el catalogo actual no debe lanzar.

    Con los tres valores reales de ``EstadoReparacionDetail`` y los tres
    de ``CondicionReparacionDetail`` no existe ninguna combinacion que
    caiga fuera de las prioridades 0 a 6 -es la garantia de que el
    resolver es TOTAL sobre el dominio actual-. Para probar que el
    fail-safe en si mismo funciona -y no lanza- se construye un objeto
    con un ``estado``/``condicion`` fuera de esos enums (algo que
    Pydantic nunca dejaria persistir en un ``ReparacionDetail`` real,
    pero que sirve para ejercitar la ultima linea del resolver).
    """
    detalle_imposible = SimpleNamespace(estado="ALGO_RARO", condicion=None)

    assert resolver_situacion_orden([detalle_imposible]) == (
        ResultadoEvaluacionOrden.CONTEXTO_INCONSISTENTE
    )


# --- Es funcion pura: no requiere una Orden ni tiene side effects --------


def test_es_una_funcion_pura_sobre_la_lista_recibida():
    detalles = [_detalle(estado=EstadoReparacionDetail.COMPLETO)]

    resultado_1 = resolver_situacion_orden(detalles)
    resultado_2 = resolver_situacion_orden(detalles)

    assert resultado_1 == resultado_2 == ResultadoEvaluacionOrden.COMPLETA
    # La lista de entrada no se toco.
    assert detalles[0].estado is EstadoReparacionDetail.COMPLETO
