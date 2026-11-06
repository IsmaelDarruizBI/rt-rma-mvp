"""Cargas iniciales sobre la base local (QA-E3-5 y DE3-1).

Escenarios:

- A: base nueva (migraciones y cargas).
- B: base anterior a E3, con datos y relaciones; despues la migracion de
  E3 y las cargas.

En los dos, cada insumo queda con la clave del dominio y su codigo, y
cada relacion de las fuentes queda en la base, sin perder ni duplicar
nada. Volver a aplicar las cargas no cambia nada. Una identidad existente
que no coincide con las fuentes no se pisa: la carga falla con el detalle.
"""

import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import pytest

psycopg = pytest.importorskip("psycopg")

from tests.postgres.base_local import (  # noqa: E402
    archivos_sql,
    borrar_base,
    crear_base,
    url_admin_local,
)

FUENTES = Path(__file__).resolve().parents[2] / "data" / "catalogs"
MIGRACION_E3 = "_e3_catalogos.sql"


def _fuente(nombre):
    return json.loads((FUENTES / nombre).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def admin(postgres_descartable):
    url = urlsplit(postgres_descartable)
    return url_admin_local(url._replace(path="/postgres").geturl())


@pytest.fixture
def base(admin):
    """Fabrica de bases con los SQL que pasen ``filtro``."""
    nombres = []

    def _crear(filtro):
        url = crear_base(admin, [a for a in archivos_sql() if filtro(a)])
        nombres.append(urlsplit(url).path.lstrip("/"))
        return url

    yield _crear
    for nombre in nombres:
        borrar_base(admin, nombre)


def _migraciones_previas(archivo):
    """Las migraciones anteriores a la de E3 (por nombre: las posteriores,
    como la de E4, suponen sus columnas)."""
    e3 = next(a for a in archivos_sql() if a.name.endswith(MIGRACION_E3))
    return archivo.parent.name == "migrations" and archivo.name < e3.name


def _migraciones(archivo):
    return archivo.parent.name == "migrations"


def _cargas():
    return [a for a in archivos_sql() if a.parent.name != "migrations"]


def _aplicar_cargas(conexion):
    for archivo in _cargas():
        conexion.execute(archivo.read_text(encoding="utf-8"))


def _identidades(conexion):
    insumos = set(
        conexion.execute("select clave, codigo from rma.insumo").fetchall()
    )
    previstos = conexion.execute(
        "select t.codigo, i.clave, i.codigo, x.cantidad"
        " from rma.tipo_reparacion_insumo x"
        " join rma.tipo_reparacion t on t.id = x.tipo_reparacion_id"
        " join rma.insumo i on i.id = x.insumo_id"
    ).fetchall()
    mesas = conexion.execute(
        "select m.codigo, t.codigo from rma.mesa_tipo_reparacion x"
        " join rma.mesa_trabajo m on m.id = x.mesa_trabajo_id"
        " join rma.tipo_reparacion t on t.id = x.tipo_reparacion_id"
    ).fetchall()
    roles = conexion.execute(
        "select u.codigo, r.codigo from rma.usuario_rol ur"
        " join rma.usuario u on u.id = ur.usuario_id"
        " join rma.rol r on r.id = ur.rol_id"
    ).fetchall()
    return insumos, previstos, mesas, roles


def _esperado():
    insumos = _fuente("insumos.json")
    codigo = {i["id"]: i["codigo"] for i in insumos}
    return (
        {(i["id"], i["codigo"]) for i in insumos},
        [
            (x["tipo_reparacion_id"], x["insumo_id"], codigo[x["insumo_id"]])
            + (Decimal(x["cantidad"]),)
            for x in _fuente("tipo_reparacion_insumos.json")
        ],
        [
            (x["estacion_id"], x["tipo_reparacion_id"])
            for x in _fuente("tipo_reparacion_estaciones.json")
        ],
        [(u["id"], u["rol"]) for u in _fuente("usuarios.json")],
    )


def _foto(conexion):
    """Todo lo que una carga repetida no deberia cambiar."""
    consultas = (
        "select id, clave, codigo, nombre, stock_fisico, modificado_en"
        " from rma.insumo order by id",
        "select id, codigo, orden, modificado_en from rma.usuario order by id",
        "select id, codigo, orden from rma.medio_pago order by id",
        "select * from rma.tipo_reparacion_insumo order by 1, 2",
        "select * from rma.mesa_tipo_reparacion order by 1, 2",
        "select * from rma.usuario_rol order by 1, 2",
        "select id, codigo, insumo_id, cantidad"
        " from rma.movimiento_inventario order by id",
        "select count(*) from rma.accion_usuario",
    )
    return [conexion.execute(c).fetchall() for c in consultas]


def _sin_orden(identidades):
    insumos, *relaciones = identidades
    return (insumos, *(sorted(r) for r in relaciones))


def test_a_base_nueva_cada_identidad_y_relacion_de_las_fuentes(base):
    url = base(lambda a: True)
    with psycopg.connect(url, autocommit=True) as conexion:
        assert _sin_orden(_identidades(conexion)) == _sin_orden(_esperado())
        foto = _foto(conexion)
        _aplicar_cargas(conexion)  # idempotente
        assert _foto(conexion) == foto


PREVIOS_A_E3 = """
insert into rma.tipo_reparacion
  (codigo, nombre, precio, puntaje, garantia_dias, activo)
values ('TR-001', 'Cambio bateria iPhone 14', 80000, 10, 90, true);
insert into rma.insumo (codigo, nombre, activo)
values ('BAT-IP14', 'Bateria iPhone 14', true),
       ('OTRO-1', 'Insumo creado fuera de las fuentes', true);
insert into rma.tipo_reparacion_insumo
  (tipo_reparacion_id, insumo_id, cantidad)
select t.id, i.id, 1 from rma.tipo_reparacion t, rma.insumo i
where t.codigo = 'TR-001' and i.codigo = 'BAT-IP14';
with a as (
  insert into rma.accion_usuario (proceso, operacion, resultado)
  values ('CARGA_INICIAL_DESARROLLO', 'INGRESO_STOCK_INICIAL', 'CONFIRMADA')
  returning id
)
insert into rma.movimiento_inventario
  (codigo, tipo, insumo_id, cantidad, motivo_texto, accion_id)
select 'MST-INICIAL-BAT-IP14', 'INGRESO', i.id, 2,
       'Saldo inicial de desarrollo', a.id
from a, rma.insumo i where i.codigo = 'BAT-IP14';
"""


AUTORIZACION_E3 = "set rma.migracion_e3 = 'estrategia_identidad_aprobada'"


def _migrar_e3(conexion):
    """Como el paso aprobado de E8: con la autorizacion en la sesion."""
    conexion.execute(AUTORIZACION_E3)
    conexion.execute(_migracion_e3())


def _migracion_e3():
    return next(
        a for a in archivos_sql() if a.name.endswith(MIGRACION_E3)
    ).read_text(encoding="utf-8")


def test_b_base_anterior_a_e3_conserva_relaciones_y_fija_la_clave(base):
    url = base(_migraciones_previas)
    with psycopg.connect(url, autocommit=True) as conexion:
        conexion.execute(PREVIOS_A_E3)
        antes = dict(
            conexion.execute("select codigo, id from rma.insumo").fetchall()
        )
        relacion = conexion.execute(
            "select tipo_reparacion_id, insumo_id"
            " from rma.tipo_reparacion_insumo"
        ).fetchall()
        _migrar_e3(conexion)
        # La migracion completa la clave provisoria con el codigo.
        assert set(
            conexion.execute("select clave, codigo from rma.insumo").fetchall()
        ) == {("BAT-IP14", "BAT-IP14"), ("OTRO-1", "OTRO-1")}
        _aplicar_cargas(conexion)
        insumos, previstos, mesas, roles = _identidades(conexion)
        esperado = _esperado()
        # La carga fija la clave del dominio; la fila ajena queda como estaba.
        assert insumos == esperado[0] | {("OTRO-1", "OTRO-1")}
        assert sorted(previstos) == sorted(esperado[1])
        assert sorted(mesas) == sorted(esperado[2])
        assert sorted(roles) == sorted(esperado[3])
        # Mismas filas (mismo uuid): nada se borro ni se duplico.
        assert (
            dict(
                conexion.execute(
                    "select codigo, id from rma.insumo"
                ).fetchall()
            )
            == antes
        )
        assert (
            conexion.execute(
                "select tipo_reparacion_id, insumo_id"
                " from rma.tipo_reparacion_insumo"
            ).fetchall()
            == relacion
        )
        assert conexion.execute(
            "select count(*), sum(cantidad) from rma.movimiento_inventario"
        ).fetchone() == (1, Decimal(2))
        # Idempotente.
        foto = _foto(conexion)
        _aplicar_cargas(conexion)
        assert _foto(conexion) == foto


def _carga_desarrollo():
    return next(
        a for a in _cargas() if a.parent.name == "desarrollo"
    ).read_text(encoding="utf-8")


def _referencia(conexion):
    for archivo in _cargas():
        if archivo.parent.name == "referencia_operativa":
            conexion.execute(archivo.read_text(encoding="utf-8"))


def test_una_identidad_existente_distinta_no_se_pisa(base):
    """BAT-IP14 ya tiene otra clave del dominio (no la provisoria): la
    carga no la cambia y falla diciendo que insumo no quedo como en las
    fuentes."""
    url = base(_migraciones)
    with psycopg.connect(url, autocommit=True) as conexion:
        _referencia(conexion)
        conexion.execute(
            "insert into rma.insumo (clave, codigo, nombre)"
            " values ('INS-777', 'BAT-IP14', 'Bateria')"
        )
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="insumos con su clave y su código sin cargar: "
            "INS-001 / BAT-IP14",
        ):
            conexion.execute(_carga_desarrollo())
        assert conexion.execute(
            "select clave from rma.insumo where codigo = 'BAT-IP14'"
        ).fetchone() == ("INS-777",)
        # Aplicada entera, la carga fallida no dejo nada.
        assert conexion.execute(
            "select count(*) from rma.tipo_reparacion_insumo"
        ).fetchone() == (0,)


def _sentencias(texto):
    """La carga sentencia por sentencia, como ``psql -f`` sin
    ``ON_ERROR_STOP``: cada bloque separado por una linea en blanco."""
    return [
        bloque
        for bloque in texto.split("\n\n")
        if any(
            linea.strip() and not linea.startswith("--")
            for linea in bloque.splitlines()
        )
    ]


def test_un_insumo_ajeno_con_el_id_del_dominio_no_recibe_relaciones(base):
    """Un insumo creado fuera de la aplicacion con codigo 'INS-001' (el id
    del dominio de BAT-IP14) en una base anterior a E3. Aun aplicando la
    carga sentencia por sentencia, ninguna relacion apunta a la fila ajena
    y la verificacion lo informa."""
    url = base(_migraciones_previas)
    with psycopg.connect(url, autocommit=True) as conexion:
        conexion.execute(
            "insert into rma.insumo (codigo, nombre)"
            " values ('INS-001', 'Ajeno')"
        )
        _migrar_e3(conexion)
        _referencia(conexion)
        errores = []
        for sentencia in _sentencias(_carga_desarrollo()):
            try:
                conexion.execute(sentencia)
            except psycopg.Error as error:
                errores.append(str(error))
        assert any("insumo_clave_unica" in e for e in errores)
        assert any(
            "insumos con su clave y su código sin cargar: INS-001 / BAT-IP14"
            in e
            for e in errores
        )
        assert conexion.execute(
            "select count(*) from rma.tipo_reparacion_insumo x"
            " join rma.insumo i on i.id = x.insumo_id"
            " where i.codigo = 'INS-001'"
        ).fetchone() == (0,)


# --- QAF-13: la migracion de E3 no se aplica sobre datos sin autorizacion ---


@pytest.mark.parametrize(
    "existente",
    [
        "insert into rma.insumo (codigo, nombre) values ('BAT-IP14', 'B')",
        "insert into rma.usuario (codigo, nombre) values ('U-1', 'Uno')",
        "insert into rma.medio_pago (codigo, nombre) values ('EFECTIVO', 'E')",
    ],
    ids=["insumo", "usuario", "medio_pago"],
)
def test_la_migracion_e3_exige_la_estrategia_aprobada_si_hay_datos(
    base, existente
):
    """Como seria DEV/UAT: con datos cargados y sin la autorizacion del
    paso de E8, la migracion falla antes de cambiar nada. Con ella, se
    aplica."""
    url = base(_migraciones_previas)
    with psycopg.connect(url, autocommit=True) as conexion:
        conexion.execute(existente)
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="sin la estrategia de identidad aprobada",
        ):
            conexion.execute(_migracion_e3())
        columnas = conexion.execute(
            "select count(*) from information_schema.columns"
            " where table_schema = 'rma'"
            " and column_name in ('clave', 'orden')"
        ).fetchone()
        assert columnas == (0,)  # atomica: nada a medias
        # Un valor cualquiera no autoriza.
        conexion.execute("set rma.migracion_e3 = 'si'")
        with pytest.raises(psycopg.errors.RaiseException):
            conexion.execute(_migracion_e3())
        _migrar_e3(conexion)
        assert conexion.execute(
            "select count(*) from information_schema.columns"
            " where table_schema = 'rma'"
            " and column_name in ('clave', 'orden')"
        ).fetchone() == (3,)


def test_la_migracion_e3_en_una_base_vacia_no_necesita_autorizacion(base):
    url = base(_migraciones_previas)
    with psycopg.connect(url, autocommit=True) as conexion:
        conexion.execute(_migracion_e3())
        _aplicar_cargas(conexion)
        assert _sin_orden(_identidades(conexion)) == _sin_orden(_esperado())


# --- QAF-8: el stock no se registra sobre otra identidad --------------------


def test_el_stock_no_se_registra_sobre_otra_identidad(base):
    """BAT-IP14 ya tiene otra clave del dominio. Aun aplicando la carga
    sentencia por sentencia, el bloque de stock confirma la identidad antes
    de tocar nada y falla con el detalle: ningun INGRESO para esa fila."""
    url = base(_migraciones)
    with psycopg.connect(url, autocommit=True) as conexion:
        _referencia(conexion)
        conexion.execute(
            "insert into rma.insumo (clave, codigo, nombre)"
            " values ('INS-777', 'BAT-IP14', 'Bateria')"
        )
        errores = []
        for sentencia in _sentencias(_carga_desarrollo()):
            try:
                conexion.execute(sentencia)
            except psycopg.Error as error:
                errores.append(str(error))
        assert any(
            "stock inicial sin registrar, insumos sin su clave y su código: "
            "INS-001 / BAT-IP14" in e
            for e in errores
        )
        assert conexion.execute(
            "select count(*) from rma.movimiento_inventario"
        ).fetchone() == (0,)
        assert conexion.execute(
            "select clave, stock_fisico from rma.insumo"
            " where codigo = 'BAT-IP14'"
        ).fetchone() == ("INS-777", Decimal(0))
