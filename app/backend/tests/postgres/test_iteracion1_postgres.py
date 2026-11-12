"""Iteracion 1 (V1.4) en PostgreSQL: DC15B, DC07 y DC11.

Contra la base local descartable, con el corpus de flujos reales, que ya
incluye HP-REP-003 con la garantia vigente y VAR-REP-039/041/042
(``corpus_ordenes.py``).
La prueba de A1 (``test_cada_paso_de_los_flujos_vuelve_identico``) ya
verifica que cada paso se relee identico; aca se verifica que el corpus
los cubre, que quedan en las columnas nuevas de la migracion
``20261111000100_it1_alineacion_v14.sql`` y que el historial usa los
tipos de evento que les corresponden.
"""

import pytest

pytest.importorskip("psycopg_pool")

from app.domain.models.enums import ClaseAjuste  # noqa: E402
from app.repositories.exceptions import PersistenciaError  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import (  # noqa: E402
    _guardar_paso,
    _sql,
)

# Las bases y el corpus son los de las pruebas de A1 y A2.
armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla


def _ultimas(corpus):
    return {o.id: o for o in corpus[1]}


def _cargar(repo, unidad, pasos):
    vistos = set()
    for paso in pasos:
        _guardar_paso(repo, unidad, paso, paso.id in vistos)
        vistos.add(paso.id)


def test_it1_el_corpus_cubre_la_iteracion(corpus):
    ultimas = _ultimas(corpus).values()
    vigencias = [v for o in ultimas for v in o.vigencia_garantia_origen]
    assert {v.vigente for v in vigencias} == {True, False}
    assert any(o.excepcion_garantia for o in ultimas)
    assert any(
        d.clase is ClaseAjuste.CORTESIA for o in ultimas for d in o.descuentos
    )
    assert any(
        d.solicitud_desistimiento and d.cancelacion
        for o in ultimas
        for d in o.reparaciones_detail
    )
    assert any(
        e.estado_trabajo and e.reversible is not None
        for o in ultimas
        for e in o.ejecuciones
    )


def test_it1_las_columnas_nuevas_y_el_historial(armar, base, corpus):
    repo, unidad = armar()
    _cargar(repo, unidad, corpus[1])
    for orden in _ultimas(corpus).values():
        assert repo.obtener(orden.id) == orden

    excepciones = _sql(
        base,
        """
        select o.codigo, u.codigo, o.excepcion_garantia_motivo
        from rma.orden o join rma.usuario u on u.id = o.excepcion_garantia_por
        """,
    )
    assert len(excepciones) == 1
    assert excepciones[0][1] == "COORD-001"
    assert {
        fila[0]
        for fila in _sql(
            base,
            "select garantia_vigente from rma.orden_detalle_origen "
            "where garantia_vigente is not null",
        )
    } == {True, False}
    assert ("CORTESIA",) in _sql(
        base, "select distinct clase from rma.descuento"
    )
    assert _sql(
        base,
        """
        select count(*) from rma.detalle
        where desistimiento_solicitado_por is not null
          and cancelado_en > desistimiento_solicitado_en
        """,
    ) == [(1,)]
    assert _sql(
        base,
        """
        select estado, reversible from rma.ejecucion
        where estado_trabajo is not null
        """,
    ) == [("INTERRUMPIDO", True)]

    eventos = {
        (fila[0], fila[1])
        for fila in _sql(
            base,
            """
            select e.historial_referencia_id, t.codigo
            from rma.evento_negocio e
            join rma.tipo_evento t on t.id = e.tipo_evento_id
            where e.historial_referencia_id in
                ('PROC-REP-036', 'PROC-REP-046')
            """,
        )
    }
    assert ("PROC-REP-036", "EV-SIS-001") in eventos  # Vigente
    assert ("PROC-REP-036", "EV-REP-052") in eventos  # Excepcion autorizada
    # Desistimiento solicitado.
    assert ("PROC-REP-046", "EV-REP-046") in eventos


def test_it1_la_validacion_de_la_garantia_no_cambia(armar, base, corpus):
    """La vigencia evaluada y la excepcion se fijan al crear la Orden RMA."""
    repo, unidad = armar()
    _cargar(repo, unidad, corpus[1])
    (garantia,) = [
        o for o in _ultimas(corpus).values() if o.excepcion_garantia
    ]
    with pytest.raises(PersistenciaError, match="garantia"):
        with unidad.transaccion():
            orden = repo.obtener_para_modificar(garantia.id)
            orden.excepcion_garantia = orden.excepcion_garantia.model_copy(
                update={"motivo": "Otro motivo."}
            )
            repo.guardar(orden)
    assert repo.obtener(garantia.id) == garantia
