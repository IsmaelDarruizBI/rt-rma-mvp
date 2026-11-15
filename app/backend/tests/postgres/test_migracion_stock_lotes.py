"""Migracion del stock existente a lotes (DEC-MI-10) sobre datos reales del
esquema anterior.

Se arma una base con las migraciones ANTERIORES a
``20261113000900_lotes_inventario.sql``, se cargan movimientos con ese
esquema (ingresos, reservas abiertas y cerradas, consumo, liberacion y
ajuste) y recien despues se aplican 0900 en adelante. Se concilia:

- el stock fisico, el reservado y cada movimiento quedan iguales (nada se
  duplica ni se pierde);
- todos los insumos quedan SIN_LOTE, ningun movimiento recibe un lote
  inventado y el stock sin lote identificado es el fisico;
- las reservas abiertas antes de migrar se consumen o se cierran por
  desperdicio despues, y no se pueden cerrar dos veces;
- al pasar el insumo a LOTE el stock previo queda «sin lote
  identificado» y un lote nuevo no puede salir con mas de su saldo;
- ``verificar_integridad()`` queda vacio en cada paso.
"""

from urllib.parse import urlsplit

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from tests.postgres.base_local import (  # noqa: E402
    RAIZ_SUPABASE,
    archivos_sql,
    borrar_base,
    crear_base,
)
from tests.postgres.test_ordenes_postgres import (  # noqa: E402
    _ejecutar,
    _sql,
    corpus,  # noqa: F401
    plantilla,  # noqa: F401
)

MIGRACION_LOTES = "20261113000900_lotes_inventario.sql"

DATOS_PREVIOS = """
select rma_pruebas.preparar_orden('MIG');
do $$
declare
  v_insumo uuid;
  v_otro uuid;
  v_accion uuid := rma_pruebas.id('accion_MIG');
  v_usuario uuid := rma_pruebas.id('usuario_MIG');
  v_orden uuid := rma_pruebas.id('orden_MIG');
  v_detalle uuid := rma_pruebas.id('detalle_MIG');
  v_ejecucion uuid;
  v_cerrada uuid;
  v_motivo uuid;
begin
  insert into rma.insumo (codigo, nombre) values ('MIG-BAT', 'Bateria')
    returning id into v_insumo;
  insert into rma.insumo (codigo, nombre) values ('MIG-PAN', 'Pantalla')
    returning id into v_otro;
  insert into rma.motivo_ajuste (codigo, descripcion, aplica_a)
    values ('MIG_NEG', 'Rotura', 'NEGATIVO') returning id into v_motivo;

  insert into rma.movimiento_inventario
    (codigo, tipo, insumo_id, cantidad, motivo_texto, usuario_id,
     accion_id, referencia)
  values
    ('MIG-I1', 'INGRESO', v_insumo, 10, 'Compra', v_usuario, v_accion, 'R-1'),
    ('MIG-I2', 'INGRESO', v_otro, 4, 'Compra', v_usuario, v_accion, 'R-2');

  -- Una reserva que se cierra antes de migrar (consumo 2, libera 1).
  insert into rma.movimiento_inventario
    (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id, accion_id)
  values ('MIG-R1', 'RESERVA', v_insumo, 3, v_orden, v_detalle, v_accion)
  returning id into v_cerrada;
  insert into rma.ejecucion
    (codigo, orden_id, detalle_id, detalle_version_id, toma_id, usuario_id)
  values ('EJE-MIG', v_orden, v_detalle, rma_pruebas.id('version_MIG'),
          rma_pruebas.id('toma_MIG'), v_usuario)
  returning id into v_ejecucion;
  insert into rma.ejecucion_insumo
    (ejecucion_id, insumo_id, cantidad_utilizada)
  values (v_ejecucion, v_insumo, 2);
  insert into rma.movimiento_inventario
    (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id, ejecucion_id,
     movimiento_origen_id, accion_id)
  values
    ('MIG-C1', 'CONSUMO', v_insumo, 2, v_orden, v_detalle,
     v_ejecucion, v_cerrada, v_accion),
    ('MIG-L1', 'LIBERACION_RESERVA', v_insumo, 1, v_orden, v_detalle,
     v_ejecucion, v_cerrada, v_accion);

  -- Dos reservas que quedan ABIERTAS al migrar.
  insert into rma.movimiento_inventario
    (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id, accion_id)
  values ('MIG-R2', 'RESERVA', v_insumo, 2, v_orden, v_detalle, v_accion),
         ('MIG-R3', 'RESERVA', v_otro, 1, v_orden, v_detalle, v_accion);

  insert into rma.movimiento_inventario
    (codigo, tipo, insumo_id, cantidad, motivo_ajuste_id, motivo_texto,
     usuario_id, accion_id)
  values ('MIG-A1', 'AJUSTE_NEGATIVO', v_insumo, 1, v_motivo, 'Rotura',
          v_usuario, v_accion);
end $$;
"""

SALDOS = """
select codigo, stock_fisico, stock_reservado, control
  from rma.insumo where left(codigo, 4) = 'MIG-' order by codigo
"""
LIBRO = """
select m.codigo, m.tipo, m.cantidad, m.stock_fisico_resultante,
       m.stock_reservado_resultante
  from rma.movimiento_inventario m order by m.codigo
"""


def _antes_de_lotes() -> list:
    return [
        a
        for a in archivos_sql()
        if a.parent.name == "migrations" and a.name < MIGRACION_LOTES
    ]


def _desde_lotes() -> list:
    return [
        a
        for a in archivos_sql()
        if a.parent.name == "migrations" and a.name >= MIGRACION_LOTES
    ]


def _crudo(url, texto: str) -> None:
    """Un script SQL tal cual (sin parametros: ``%`` no es un marcador)."""
    with psycopg.connect(url, autocommit=True) as conexion:
        conexion.execute(texto)


def _integridad(url) -> list:
    return _sql(url, "select * from rma.verificar_integridad()")


@pytest.fixture
def base_previa(plantilla):  # noqa: F811
    admin, _ = plantilla
    url = crear_base(admin, _antes_de_lotes())
    try:
        _crudo(
            url,
            (RAIZ_SUPABASE / "tests" / "00_utilidades.sql").read_text(
                encoding="utf-8"
            ),
        )
        _crudo(url, DATOS_PREVIOS)
        yield url
    finally:
        borrar_base(admin, urlsplit(url).path.lstrip("/"))


def test_la_migracion_concilia_stock_y_reservas_existentes(base_previa):
    url = base_previa
    saldos = _sql(
        url,
        "select codigo, stock_fisico, stock_reservado from rma.insumo "
        "where left(codigo, 4) = 'MIG-' order by codigo",
    )
    # Bateria: 10 - 2 consumidas - 1 rota = 7, con 2 reservadas abiertas.
    assert [(c, float(f), float(r)) for c, f, r in saldos] == [
        ("MIG-BAT", 7.0, 2.0),
        ("MIG-PAN", 4.0, 1.0),
    ]
    # Los datos previos son validos en el esquema anterior.
    assert _integridad(url) == []
    libro = _sql(url, LIBRO)

    for migracion in _desde_lotes():
        _crudo(url, migracion.read_text(encoding="utf-8"))

    # Nada se duplica ni se pierde: saldos y libro identicos.
    assert [
        (c, float(f), float(r), k) for c, f, r, k in _sql(url, SALDOS)
    ] == [
        ("MIG-BAT", 7.0, 2.0, "SIN_LOTE"),
        ("MIG-PAN", 4.0, 1.0, "SIN_LOTE"),
    ]
    assert _sql(url, LIBRO) == libro
    # Ningun lote inventado: el stock existente es «sin lote identificado».
    assert _sql(url, "select count(*) from rma.lote_insumo") == [(0,)]
    assert _sql(
        url,
        "select count(*) from rma.movimiento_inventario "
        "where lote_id is not null",
    ) == [(0,)]
    assert _sql(url, "select count(*) from rma.v_saldo_lote") == [(0,)]
    assert _integridad(url) == []

    # Las reservas abiertas siguen operativas: una se consume, la otra se
    # cierra por desperdicio (DEC-MI-10); ninguna se cierra dos veces. Otra
    # Ejecucion, con lo declarado por el tecnico (ya con desperdicio).
    _crudo(
        url,
        """
        insert into rma.ejecucion
          (codigo, orden_id, detalle_id, detalle_version_id, toma_id,
           usuario_id, estado, fin)
        select 'EJE-MIG2', orden_id, detalle_id, detalle_version_id, toma_id,
               usuario_id, 'COMPLETADO', now() + interval '1 minute'
          from rma.ejecucion where codigo = 'EJE-MIG';
        insert into rma.ejecucion_insumo
          (ejecucion_id, insumo_id, cantidad_utilizada, desperdicio)
        select e.id, i.id, case i.codigo when 'MIG-BAT' then 2 else 0 end,
               case i.codigo when 'MIG-PAN' then 1 else 0 end
          from rma.ejecucion e, rma.insumo i
         where e.codigo = 'EJE-MIG2' and left(i.codigo, 4) = 'MIG-';
        """,
    )
    _ejecutar(
        url,
        """
        insert into rma.movimiento_inventario
          (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id,
           ejecucion_id, movimiento_origen_id, accion_id)
        select 'MIG-C2', 'CONSUMO', r.insumo_id, 2, r.orden_id, r.detalle_id,
               e.id, r.id, r.accion_id
          from rma.movimiento_inventario r, rma.ejecucion e
         where r.codigo = 'MIG-R2' and e.codigo = 'EJE-MIG2'
        """,
    )
    _ejecutar(
        url,
        """
        insert into rma.movimiento_inventario
          (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id,
           ejecucion_id, movimiento_origen_id, accion_id)
        select 'MIG-D3', 'DESPERDICIO', r.insumo_id, 1, r.orden_id,
               r.detalle_id,
               e.id, r.id, r.accion_id
          from rma.movimiento_inventario r, rma.ejecucion e
         where r.codigo = 'MIG-R3' and e.codigo = 'EJE-MIG2'
        """,
    )
    with pytest.raises(psycopg.Error):
        _ejecutar(
            url,
            """
            insert into rma.movimiento_inventario
              (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id,
               ejecucion_id, movimiento_origen_id, accion_id)
            select 'MIG-C3', 'CONSUMO', r.insumo_id, 1, r.orden_id,
                   r.detalle_id, e.id, r.id, r.accion_id
              from rma.movimiento_inventario r, rma.ejecucion e
             where r.codigo = 'MIG-R2' and e.codigo = 'EJE-MIG2'
            """,
        )
    assert [
        (c, float(f), float(r), k) for c, f, r, k in _sql(url, SALDOS)
    ] == [
        ("MIG-BAT", 5.0, 0.0, "SIN_LOTE"),
        ("MIG-PAN", 3.0, 0.0, "SIN_LOTE"),
    ]
    assert _integridad(url) == []


def test_pasar_a_lote_deja_el_stock_previo_sin_lote_identificado(base_previa):
    url = base_previa
    for migracion in _desde_lotes():
        _crudo(url, migracion.read_text(encoding="utf-8"))
    _ejecutar(
        url, "update rma.insumo set control = 'LOTE' where codigo = 'MIG-BAT'"
    )
    # Un ingreso nuevo con lote; el stock previo (7) sigue sin lote.
    _ejecutar(
        url,
        """
        insert into rma.lote_insumo
          (codigo, insumo_id, numero, origen, usuario_id, registrado_en)
        select 'LOT-MIG-1', i.id, 'L-1', 'INGRESO_MANUAL', u.id, now()
          from rma.insumo i, rma.usuario u
         where i.codigo = 'MIG-BAT' and u.codigo = 'USR-MIG'
        """,
    )
    _ejecutar(
        url,
        """
        insert into rma.movimiento_inventario
          (codigo, tipo, insumo_id, cantidad, motivo_texto, usuario_id,
           accion_id, referencia, lote_id)
        select 'MIG-I3', 'INGRESO', i.id, 3, 'Compra', m.usuario_id,
               m.accion_id, 'R-3', l.id
          from rma.insumo i, rma.lote_insumo l, rma.movimiento_inventario m
         where i.codigo = 'MIG-BAT' and l.codigo = 'LOT-MIG-1'
           and m.codigo = 'MIG-I1'
        """,
    )
    saldos = _sql(
        url,
        """
        select i.stock_fisico,
               coalesce((select sum(v.saldo) from rma.v_saldo_lote v
                          where v.insumo_id = i.id), 0)
          from rma.insumo i where i.codigo = 'MIG-BAT'
        """,
    )
    fisico, en_lotes = saldos[0]
    assert (float(fisico), float(en_lotes)) == (10.0, 3.0)
    # Sin lote identificado = 10 - 3 = 7: exactamente el stock anterior.
    assert float(fisico) - float(en_lotes) == 7.0
    # El lote no puede quedar negativo.
    with pytest.raises(psycopg.Error):
        _ejecutar(
            url,
            """
            insert into rma.movimiento_inventario
              (codigo, tipo, insumo_id, cantidad, motivo_ajuste_id,
               motivo_texto, usuario_id, accion_id, lote_id)
            select 'MIG-A2', 'AJUSTE_NEGATIVO', i.id, 4, a.id, 'Conteo',
                   m.usuario_id, m.accion_id, l.id
              from rma.insumo i, rma.lote_insumo l, rma.motivo_ajuste a,
                   rma.movimiento_inventario m
             where i.codigo = 'MIG-BAT' and l.codigo = 'LOT-MIG-1'
               and a.codigo = 'MIG_NEG' and m.codigo = 'MIG-I1'
            """,
        )
    assert _integridad(url) == []
