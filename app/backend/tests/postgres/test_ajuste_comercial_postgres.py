"""Ajuste Comercial con reversion, correccion y recalculos sobre PostgreSQL
(DEC-AJ-10; ``20261124000100_ajuste_comercial_reversion.sql``).

- La reversion es el unico UPDATE de ``rma.descuento``, una sola vez y con
  la Orden abierta; borrar o cambiar otra columna se rechaza.
- La relectura devuelve lo mismo que la API (ids, evidencia, reversion,
  ``corrige_a`` y recalculos).
- La vista ``rma.v_orden_saldo`` excluye los registros revertidos y da el
  mismo saldo que el dominio en cada paso.
- Cada operacion queda en el historial como EV-REP-041.
"""

from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api


def _ajustar(cliente, orden_id, tipo, valor, detalle_id=None, **extra):
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/discount",
            json={
                "usuario_id": f.COORDINADOR,
                "tipo": tipo,
                "valor": valor,
                "motivo": "Acuerdo.",
                "detalle_id": detalle_id,
                **extra,
            },
        )
    )


def _revertir(cliente, orden_id, ajuste_id):
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/adjustments/{ajuste_id}/revert",
            json={"usuario_id": f.ADMINISTRADOR, "motivo": "Error."},
        )
    )


def _corregir(cliente, orden_id, ajuste_id, tipo, valor, clase="DESCUENTO"):
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/adjustments/{ajuste_id}/correct",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "tipo": tipo,
                "valor": valor,
                "clase": clase,
                "motivo": "Correccion.",
            },
        )
    )


def _vista(url, orden_id):
    ((total, aplicado, saldo),) = _sql(
        url,
        """
        select v.total, v.descuento_aplicado, v.saldo
        from rma.v_orden_saldo v join rma.orden o on o.id = v.orden_id
        where o.codigo = %s
        """,
        (orden_id,),
    )
    return total, aplicado, saldo


def _coincide(url, orden) -> None:
    """La vista y el dominio (la API) dan lo mismo."""
    resumen = orden["resumen"]
    assert _vista(url, orden["id"]) == (
        Decimal(resumen["total"]),
        Decimal(resumen["descuento_aplicado"]),
        Decimal(resumen["saldo"]),
    )


def _releida_igual(cliente, orden) -> None:
    releida = f.ok(cliente.get(f"/api/orders/{orden['id']}"))
    assert releida == {k: v for k, v in orden.items() if k != "puede_entregar"}


def test_reversion_y_correccion_la_vista_coincide_en_cada_paso(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    pasos = [
        _ajustar(cliente, orden_id, "PORCENTAJE", "10", "DET-002"),
        _ajustar(cliente, orden_id, "PORCENTAJE", "10"),
        _ajustar(cliente, orden_id, "IMPORTE", "5000"),
    ]
    registros = pasos[-1]["descuentos"]
    # Revertir el vigente de la Orden: vuelve el 10 %.
    pasos.append(_revertir(cliente, orden_id, registros[2]["id"]))
    # Corregir el del trabajo a una cortesia de importe fijo.
    pasos.append(
        _corregir(
            cliente,
            orden_id,
            registros[0]["id"],
            "IMPORTE",
            "2500",
            "CORTESIA",
        )
    )
    for paso in pasos:
        assert paso["id"] == orden_id
    _coincide(base, pasos[-1])
    # 130000 - 2500 = 127500; 10 % de la Orden = 12750.
    assert Decimal(pasos[-1]["resumen"]["total"]) == Decimal("114750")
    _releida_igual(cliente, pasos[-1])

    filas = _sql(
        base,
        """
        select d.codigo, x.codigo, d.clase, d.tipo, d.valor,
               d.precio_original, d.importe_aplicado, d.precio_final,
               c.codigo, r.codigo, d.reversion_motivo
        from rma.descuento d
        join rma.orden o on o.id = d.orden_id
        left join rma.detalle x on x.id = d.detalle_id
        left join rma.descuento c on c.id = d.corrige_a
        left join rma.usuario r on r.id = d.revertido_por
        where o.codigo = %s order by d.posicion
        """,
        (orden_id,),
    )
    ids = [r["id"] for r in pasos[-1]["descuentos"]]
    assert [fila[0] for fila in filas] == ids
    assert [fila[1:] for fila in filas] == [
        (
            "DET-002",
            "DESCUENTO",
            "PORCENTAJE",
            Decimal("10.00"),
            Decimal("50000.00"),
            Decimal("5000.00"),
            Decimal("45000.00"),
            None,
            f.ADMINISTRADOR,
            "Correccion.",
        ),
        (
            None,
            "DESCUENTO",
            "PORCENTAJE",
            Decimal("10.00"),
            Decimal("125000.00"),
            Decimal("12500.00"),
            Decimal("112500.00"),
            None,
            None,
            None,
        ),
        (
            None,
            "DESCUENTO",
            "IMPORTE",
            Decimal("5000.00"),
            Decimal("125000.00"),
            Decimal("5000.00"),
            Decimal("120000.00"),
            None,
            f.ADMINISTRADOR,
            "Error.",
        ),
        (
            "DET-002",
            "CORTESIA",
            "IMPORTE",
            Decimal("2500.00"),
            Decimal("50000.00"),
            Decimal("2500.00"),
            Decimal("47500.00"),
            ids[0],
            None,
            None,
        ),
    ]
    eventos = _sql(
        base,
        """
        select e.historial_accion, t.codigo
        from rma.evento_negocio e
        join rma.tipo_evento t on t.id = e.tipo_evento_id
        join rma.orden o on o.id = e.orden_id
        where o.codigo = %s and e.historial_referencia_id = 'ACC-REP-072'
        order by e.secuencia
        """,
        (orden_id,),
    )
    assert eventos == [
        ("APLICAR_AJUSTE_COMERCIAL", "EV-REP-041"),
        ("APLICAR_AJUSTE_COMERCIAL", "EV-REP-041"),
        ("CAMBIAR_AJUSTE_COMERCIAL", "EV-REP-041"),
        ("REVERTIR_AJUSTE_COMERCIAL", "EV-REP-041"),
        ("CORREGIR_AJUSTE_COMERCIAL", "EV-REP-041"),
    ]
    assert _sql(base, "select count(*) from rma.verificar_integridad()") == [
        (0,)
    ]


def test_revertir_todo_deja_la_vista_sin_ajustes(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    _ajustar(cliente, orden_id, "PORCENTAJE", "10")
    _ajustar(cliente, orden_id, None, None)
    orden = _ajustar(cliente, orden_id, "IMPORTE", "5000")
    revertida = _revertir(cliente, orden_id, orden["descuentos"][-1]["id"])
    assert revertida["resumen"]["descuento"] is None
    _coincide(base, revertida)
    assert _vista(base, orden_id)[1] == Decimal("0")
    _releida_igual(cliente, revertida)


def test_el_recalculo_por_cancelacion_se_guarda(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    _ajustar(cliente, orden_id, "PORCENTAJE", "10", "DET-002")
    _ajustar(cliente, orden_id, "PORCENTAJE", "10")
    cancelada = f.ok(f.cancelar_detalle(cliente, orden_id, "DET-002"))

    assert len(cancelada["recalculos_ajuste"]) == 2
    _coincide(base, cancelada)
    _releida_igual(cliente, cancelada)
    assert _sql(
        base,
        """
        select r.causa, x.codigo, r.precio_anterior, r.precio_nuevo,
               r.importe_anterior, r.importe_nuevo, r.posicion
        from rma.descuento_recalculo r
        join rma.orden o on o.id = r.orden_id
        left join rma.detalle x on x.id = r.detalle_id
        where o.codigo = %s order by r.posicion
        """,
        (orden_id,),
    ) == [
        (
            "CANCELACION",
            "DET-002",
            Decimal("50000.00"),
            Decimal("0.00"),
            Decimal("5000.00"),
            Decimal("0.00"),
            1,
        ),
        (
            "CANCELACION",
            None,
            Decimal("125000.00"),
            Decimal("80000.00"),
            Decimal("12500.00"),
            Decimal("8000.00"),
            2,
        ),
    ]
    # El recalculo es inmutable.
    with pytest.raises(psycopg.errors.RestrictViolation):
        _sql(base, "update rma.descuento_recalculo set causa = 'REDEFINICION'")


def test_el_trigger_solo_admite_la_reversion_una_vez(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    orden = _ajustar(cliente, orden_id, "PORCENTAJE", "10")
    codigo = orden["descuentos"][0]["id"]
    filtro = "where codigo = %s"

    # Cambiar otra columna, o borrar, se rechaza.
    for sentencia in (
        f"update rma.descuento set valor = 20 {filtro}",
        f"update rma.descuento set motivo = 'Otro' {filtro}",
        f"delete from rma.descuento {filtro}",
    ):
        with pytest.raises(psycopg.errors.RestrictViolation):
            _sql(base, sentencia, (codigo,))
    # Una reversion incompleta viola el CHECK.
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(
            base,
            f"update rma.descuento set revertido_en = now() {filtro}",
            (codigo,),
        )
    revertir = f"""
        update rma.descuento
        set revertido_en = now(), reversion_motivo = 'Error.',
            revertido_por = (select id from rma.usuario where codigo = %s)
        {filtro}
    """
    _sql(base, revertir + " returning id", (f.ADMINISTRADOR, codigo))
    # Una sola vez.
    with pytest.raises(psycopg.errors.RestrictViolation):
        _sql(base, revertir + " returning id", (f.ADMINISTRADOR, codigo))
    # Una correccion apunta a un ajuste revertido del mismo destino.
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(
            base,
            """
            insert into rma.descuento
                (orden_id, tipo, valor, motivo, usuario_id, clase, codigo,
                 detalle_id, corrige_a)
            select d.orden_id, 'IMPORTE', 10, 'Mal.', d.usuario_id,
                   'DESCUENTO', 'AJ-X',
                   (select id from rma.detalle where orden_id = d.orden_id
                    limit 1),
                   d.id
            from rma.descuento d where d.codigo = %s
            returning id
            """,
            (codigo,),
        )


def test_con_la_orden_cerrada_no_se_revierte_en_la_base(api, base):
    _, cliente = api
    orden_id = f.definida(cliente, f.BATERIA)
    orden = _ajustar(cliente, orden_id, "IMPORTE", "1000")
    codigo = orden["descuentos"][0]["id"]
    f.tomar(cliente, orden_id, f.TECNICO)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    entregada = f.notificar_pagar_entregar(cliente, orden_id)
    assert entregada["estado_workflow"] == "ENTREGADA"

    with pytest.raises(psycopg.errors.RestrictViolation):
        _sql(
            base,
            """
            update rma.descuento
            set revertido_en = now(), reversion_motivo = 'Tarde.',
                revertido_por = usuario_id
            where codigo = %s returning id
            """,
            (codigo,),
        )


def test_la_migracion_es_aditiva(base):
    columnas = _sql(
        base,
        """
        select column_name, is_nullable from information_schema.columns
        where table_schema = 'rma' and table_name = 'descuento'
          and column_name in (
            'codigo', 'precio_original', 'importe_aplicado', 'precio_final',
            'corrige_a', 'revertido_por', 'revertido_en', 'reversion_motivo'
          )
        order by 1
        """,
    )
    assert [c for _, c in columnas] == ["YES"] * 8
    assert _sql(
        base,
        "select visible_historial_actual from rma.tipo_evento "
        "where codigo = 'EV-REP-041'",
    ) == [(True,)]
