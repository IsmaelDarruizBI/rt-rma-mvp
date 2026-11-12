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

import psycopg  # noqa: E402

from app.domain.models.enums import ClaseAjuste  # noqa: E402
from app.repositories.exceptions import PersistenciaError  # noqa: E402
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.fixtures import iteracion1 as it  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.sembrado import fijar_stock  # noqa: E402
from tests.postgres.test_ordenes_postgres import (  # noqa: E402
    _guardar_paso,
    _sql,
)

# Las bases y el corpus son los de las pruebas de A1 y A2.
armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
# La API sobre PostgreSQL con el registro de acciones (idempotencia, B1).
api = idem.api


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
    assert any(v.excepcion for v in vigencias)
    cortesias = [
        d for o in ultimas for d in o.descuentos
        if d.clase is ClaseAjuste.CORTESIA
    ]
    # DEC-IT1-02: parcial (50 %) y despues modificada a total.
    assert {d.valor for d in cortesias} >= {50, 100}
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

    # La excepcion es de cada Detalle vencido, con quien la autorizo.
    excepciones = _sql(
        base,
        """
        select d.codigo, u.codigo, x.garantia_vigente, x.garantia_vence
        from rma.orden_detalle_origen x
        join rma.detalle d on d.id = x.detalle_id
        join rma.usuario u on u.id = x.excepcion_por
        order by u.codigo
        """,
    )
    assert [(fila[1], fila[2]) for fila in excepciones] == [
        ("COORD-001", False)
    ]
    assert all(fila[3] is not None for fila in excepciones)
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
    garantia = next(
        o
        for o in _ultimas(corpus).values()
        if any(v.excepcion for v in o.vigencia_garantia_origen)
    )
    with pytest.raises(PersistenciaError, match="garantia"):
        with unidad.transaccion():
            orden = repo.obtener_para_modificar(garantia.id)
            orden.vigencia_garantia_origen = [
                v.model_copy(
                    update={
                        "excepcion": v.excepcion.model_copy(
                            update={"motivo": "Otro motivo."}
                        )
                    }
                )
                if v.excepcion
                else v
                for v in orden.vigencia_garantia_origen
            ]
            repo.guardar(orden)
    assert repo.obtener(garantia.id) == garantia


def test_it1_un_ajuste_reintentado_se_registra_una_vez(api, base):
    """DEC-IT1-02: un envio duplicado (misma Idempotency-Key) no genera un
    segundo ajuste; devuelve la misma respuesta."""
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    primera = it.ajuste_comercial(
        cliente, orden_id, valor="30", usuario=f.RECEPCION, clave="cort-1"
    )
    segunda = it.ajuste_comercial(
        cliente, orden_id, valor="30", usuario=f.RECEPCION, clave="cort-1"
    )
    assert primera.status_code == segunda.status_code == 200
    assert segunda.json() == primera.json()
    assert _sql(base, "select count(*), max(clase) from rma.descuento") == [
        (1, "CORTESIA")
    ]


def test_it1_garantia_por_trabajo_se_guarda_y_se_relee(api, base):
    """DEC-IT1-03 en PostgreSQL: tres trabajos, solo DET-002 vencido y
    admitido con su excepcion; cada uno conserva su evaluacion y la
    excepcion queda solo en DET-002. El pedido sin excepcion no deja nada."""
    app, cliente = api
    with psycopg.connect(base, autocommit=True) as conexion:
        fijar_stock(conexion, f.INSUMO_BATERIA, 10)
    reloj = it.instalar_reloj(cliente)
    origen = it.entregada_con_vigencias_distintas(cliente, reloj)
    ordenes_antes = _sql(base, "select count(*) from rma.orden")
    todos = ("DET-001", "DET-002", "DET-003")

    f.conflicto(
        it.iniciar_garantia(cliente, origen, todos), codigo="GARANTIA_VENCIDA"
    )
    assert _sql(base, "select count(*) from rma.orden") == ordenes_antes

    garantia = f.ok(
        it.iniciar_garantia(
            cliente,
            origen,
            todos,
            excepciones={"DET-002": it.MOTIVO_EXCEPCION},
        )
    )
    filas = _sql(
        base,
        """
        select d.codigo, x.garantia_vigente, u.codigo, x.excepcion_motivo
        from rma.orden_detalle_origen x
        join rma.orden o on o.id = x.orden_id
        join rma.detalle d on d.id = x.detalle_id
        left join rma.usuario u on u.id = x.excepcion_por
        where o.codigo = %s
        order by x.posicion
        """,
        (garantia["id"],),
    )
    assert filas == [
        ("DET-001", True, None, None),
        ("DET-002", False, "RECEP-001", it.MOTIVO_EXCEPCION),
        ("DET-003", True, None, None),
    ]
    # Relectura: la misma respuesta que al crearla.
    leida = f.ok(cliente.get(f"/api/orders/{garantia['id']}"))
    assert (
        leida["vigencia_garantia_origen"]
        == garantia["vigencia_garantia_origen"]
    )
    tipos = _sql(
        base,
        """
        select t.codigo from rma.evento_negocio e
        join rma.tipo_evento t on t.id = e.tipo_evento_id
        join rma.orden o on o.id = e.orden_id
        where o.codigo = %s and e.historial_referencia_id = 'PROC-REP-036'
        order by e.secuencia
        """,
        (garantia["id"],),
    )
    assert tipos == [("EV-SIS-001",), ("EV-REP-052",)]
