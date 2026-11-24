"""Clasificacion de insumos y compatibilidad sobre PostgreSQL (DEC-AJ-14).

Migracion ``20261124000500_clasificacion_insumos.sql``:

- aditiva: ``categoria_insumo`` (dos niveles, CAT-NNN), ``fabricante_repuesto``
  (FAB-NNN), cuatro columnas opcionales en ``insumo`` e
  ``insumo_compatibilidad``; ningun insumo queda clasificado ni con modelos
  (universal), y no hay movimientos nuevos;
- la base exige los dos niveles, el padre fijo, los nombres unicos entre
  pares, el codigo fijo y que nada se borre (salvo la compatibilidad, que es
  un conjunto que se reemplaza y se audita);
- Configuracion: categorias, fabricantes y la clasificacion del insumo con
  ``INSUMO_GESTIONAR``, auditados; la compatibilidad se reemplaza junto con
  el insumo, en la misma transaccion.
"""

from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.application import operativa as app_operativa  # noqa: E402
from app.repositories.exceptions import PersistenciaError  # noqa: E402
from app.storage.postgres.catalogos import (  # noqa: E402
    PostgresCatalogosRepository,
)
from app.storage.postgres.configuracion import (  # noqa: E402
    PostgresConfiguracionRepository,
)
from app.storage.postgres.modelos_equipo import (  # noqa: E402
    PostgresModelosEquipoRepository,
)
from app.storage.postgres.operativa import (  # noqa: E402
    PostgresConfiguracionOperativa,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _ejecutar, _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api


@pytest.fixture
def admin(api):
    app, cliente = api
    contexto = app.state.contexto
    unidad = contexto.unidad_de_trabajo
    app.state.contexto = replace(
        contexto,
        catalogos=PostgresCatalogosRepository(unidad),
        operativa=PostgresConfiguracionOperativa(unidad),
        configuracion=PostgresConfiguracionRepository(unidad),
        modelos_equipo=PostgresModelosEquipoRepository(unidad),
    )
    return app, cliente


def _alta(cliente, ruta, **cuerpo):
    return f.ok(
        cliente.post(ruta, json={"usuario_id": f.ADMINISTRADOR, **cuerpo})
    )


def _auditoria(url, entidad, clave):
    return _sql(
        url,
        """
        select campo, valor_anterior, valor_nuevo
          from rma.cambio_configuracion
         where entidad = %s and clave = %s
         order by secuencia
        """,
        (entidad, clave),
    )


# --- Migracion ---------------------------------------------------------------


def test_la_migracion_es_aditiva_y_no_clasifica_nada(base):
    assert (
        _sql(
            base,
            """
        select count(*) filter (where categoria_id is not null
                                   or fabricante_id is not null
                                   or variante is not null
                                   or codigo_fabricante is not null),
               count(*)
          from rma.insumo
        """,
        )[0][0]
        == 0
    )
    assert _sql(base, "select count(*) from rma.insumo_compatibilidad") == [
        (0,)
    ]
    assert _sql(base, "select count(*) from rma.categoria_insumo") == [(0,)]
    assert _sql(base, "select count(*) from rma.fabricante_repuesto") == [(0,)]
    columnas = dict(
        _sql(
            base,
            """
            select column_name, is_nullable from information_schema.columns
             where table_schema = 'rma' and table_name = 'insumo'
               and column_name in ('categoria_id', 'fabricante_id',
                                   'variante', 'codigo_fabricante')
            """,
        )
    )
    assert columnas == {
        "categoria_id": "YES",
        "fabricante_id": "YES",
        "variante": "YES",
        "codigo_fabricante": "YES",
    }
    assert _sql(
        base,
        "select rma.siguiente_codigo('CAT'), rma.siguiente_codigo('FAB')",
    ) == [("CAT-001", "FAB-001")]
    privilegios = _sql(
        base,
        """
        select has_column_privilege('rma_backend', 'rma.categoria_insumo',
                                    'nombre', 'UPDATE'),
               has_column_privilege('rma_backend', 'rma.categoria_insumo',
                                    'padre_id', 'UPDATE'),
               has_table_privilege('rma_backend', 'rma.categoria_insumo',
                                   'DELETE'),
               has_table_privilege('rma_backend', 'rma.fabricante_repuesto',
                                   'DELETE'),
               has_column_privilege('rma_backend', 'rma.fabricante_repuesto',
                                    'codigo', 'UPDATE'),
               has_table_privilege('rma_backend', 'rma.insumo_compatibilidad',
                                   'DELETE'),
               has_column_privilege('rma_backend', 'rma.insumo',
                                    'categoria_id', 'UPDATE'),
               has_column_privilege('rma_backend', 'rma.insumo',
                                    'stock_fisico', 'UPDATE')
        """,
    )
    assert privilegios == [
        (True, False, False, False, False, True, True, False)
    ]
    (definicion,) = _sql(
        base,
        """
        select pg_get_constraintdef(oid) from pg_constraint
         where conname = 'cambio_configuracion_entidad_check'
        """,
    )[0]
    assert "'CATEGORIA_INSUMO'" in definicion
    assert "'FABRICANTE_REPUESTO'" in definicion
    assert "'PRECIO_MODELO'" in definicion


def test_la_base_exige_dos_niveles_nombres_unicos_y_sin_borrado(base):
    _ejecutar(
        base,
        """
        insert into rma.categoria_insumo (codigo, nombre) values
          ('CAT-101', 'Módulos'), ('CAT-102', 'Baterías');
        insert into rma.categoria_insumo (codigo, nombre, padre_id)
          select 'CAT-103', 'OLED', id from rma.categoria_insumo
           where codigo = 'CAT-101';
        insert into rma.fabricante_repuesto (codigo, nombre)
          values ('FAB-101', 'Acme');
        """,
    )
    rechazos = [
        # Un tercer nivel.
        """insert into rma.categoria_insumo (codigo, nombre, padre_id)
           select 'CAT-104', 'X', id from rma.categoria_insumo
            where codigo = 'CAT-103'""",
        # El padre no cambia, ni hacia una categoria ni a ninguno.
        """update rma.categoria_insumo
              set padre_id = (select id from rma.categoria_insumo
                               where codigo = 'CAT-102')
            where codigo = 'CAT-103'""",
        "update rma.categoria_insumo set padre_id = null "
        "where codigo = 'CAT-103'",
        # Nombres repetidos entre pares, sin distinguir mayusculas.
        "insert into rma.categoria_insumo (codigo, nombre) "
        "values ('CAT-105', ' módulos ')",
        """insert into rma.categoria_insumo (codigo, nombre, padre_id)
           select 'CAT-106', 'oled', id from rma.categoria_insumo
            where codigo = 'CAT-101'""",
        "insert into rma.fabricante_repuesto (codigo, nombre) "
        "values ('FAB-102', 'ACME')",
        # Formato del codigo y codigo fijo.
        "insert into rma.categoria_insumo (codigo, nombre) "
        "values ('CAT-1', 'Z')",
        "update rma.categoria_insumo set codigo = 'CAT-199' "
        "where codigo = 'CAT-102'",
        "update rma.fabricante_repuesto set codigo = 'FAB-199' "
        "where codigo = 'FAB-101'",
        # Sin borrado.
        "delete from rma.categoria_insumo where codigo = 'CAT-102'",
        "delete from rma.fabricante_repuesto where codigo = 'FAB-101'",
        # Variante o codigo del fabricante en blanco.
        "update rma.insumo set variante = '  '",
        "update rma.insumo set codigo_fabricante = ''",
    ]
    for sentencia in rechazos:
        with pytest.raises(psycopg.Error):
            _ejecutar(base, sentencia)
    # El mismo nombre en otro nivel si se admite.
    _ejecutar(
        base,
        "insert into rma.categoria_insumo (codigo, nombre) "
        "values ('CAT-107', 'OLED')",
    )


# --- Administracion por la API -----------------------------------------------


def test_categorias_y_fabricantes_auditados(admin, base):
    _, cliente = admin
    modulos = _alta(cliente, "/api/admin/supply-categories", nombre="Módulos")
    assert modulos["id"] == "CAT-001"
    assert modulos["padre_id"] is None
    oled = _alta(
        cliente,
        "/api/admin/supply-categories",
        nombre="OLED",
        padre_id="CAT-001",
    )
    assert (oled["id"], oled["padre_id"]) == ("CAT-002", "CAT-001")
    assert "dos niveles" in f.conflicto(
        cliente.post(
            "/api/admin/supply-categories",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Z",
                "padre_id": "CAT-002",
            },
        )
    )
    assert "Ya existe CAT-002" in f.conflicto(
        cliente.post(
            "/api/admin/supply-categories",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "oled",
                "padre_id": "CAT-001",
            },
        )
    )
    # Sin el permiso de insumos, no.
    f.conflicto(
        cliente.post(
            "/api/admin/supply-categories",
            json={"usuario_id": f.RECEPCION, "nombre": "Flex"},
        )
    )
    editada = f.ok(
        cliente.put(
            "/api/admin/supply-categories/CAT-002",
            json={"usuario_id": f.ADMINISTRADOR, "nombre": "OLED premium"},
        )
    )
    assert (editada["nombre"], editada["padre_id"]) == (
        "OLED premium",
        "CAT-001",
    )
    assert "no cambia de nivel" in f.conflicto(
        cliente.put(
            "/api/admin/supply-categories/CAT-002",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "OLED premium",
                "padre_id": "CAT-009",
            },
        )
    )
    acme = _alta(cliente, "/api/admin/supply-manufacturers", nombre="Acme")
    assert acme["id"] == "FAB-001"
    assert "Ya existe" in f.conflicto(
        cliente.post(
            "/api/admin/supply-manufacturers",
            json={"usuario_id": f.ADMINISTRADOR, "nombre": " ACME "},
        )
    )
    f.ok(
        cliente.put(
            "/api/admin/supply-manufacturers/FAB-001",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Acme",
                "activo": False,
            },
        )
    )
    assert _auditoria(base, "CATEGORIA_INSUMO", "CAT-002") == [
        ("nombre", None, "OLED"),
        ("padre_id", None, "CAT-001"),
        ("activo", None, "true"),
        ("nombre", "OLED", "OLED premium"),
    ]
    assert ("activo", "true", "false") in _auditoria(
        base, "FABRICANTE_REPUESTO", "FAB-001"
    )
    for lectura in (
        f.ok(cliente.get("/api/admin/supply-classification")),
        f.ok(cliente.get("/api/catalogs/supply-classification")),
    ):
        assert [
            (c["id"], c["padre_id"], c["activo"])
            for c in lectura["categorias"]
        ] == [("CAT-001", None, True), ("CAT-002", "CAT-001", True)]
        assert [(x["id"], x["activo"]) for x in lectura["fabricantes"]] == [
            ("FAB-001", False)
        ]
        assert len(lectura["modelos"]) == 36
    assert f.ok(cliente.get("/api/admin/supply-classification"))["editable"]
    historial = f.ok(
        cliente.get(
            "/api/admin/config-changes",
            params={"entidad": "CATEGORIA_INSUMO", "clave": "CAT-001"},
        )
    )
    assert {c["campo"] for c in historial} == {"nombre", "activo"}


def test_clasificacion_y_compatibilidad_del_insumo(admin, base):
    _, cliente = admin
    _alta(cliente, "/api/admin/supply-categories", nombre="Baterías")
    _alta(cliente, "/api/admin/supply-manufacturers", nombre="Acme")
    _ejecutar(
        base,
        "update rma.modelo_equipo set activo = false "
        "where codigo = 'MOD-0003'",
    )
    stock_antes = _sql(base, "select count(*) from rma.movimiento_inventario")
    insumo = _alta(
        cliente,
        "/api/admin/supplies",
        nombre="Batería iPhone 14",
        categoria_id="cat-001",
        fabricante_id="FAB-001",
        variante="  alta  capacidad ",
        codigo_fabricante="APN-661",
        modelos_compatibles=["MOD-0002", "mod-0001", "MOD-0002"],
    )
    clave = insumo["id"]
    assert insumo["categoria_id"] == "CAT-001"
    assert insumo["variante"] == "alta capacidad"
    assert insumo["modelos_compatibles"] == ["MOD-0001", "MOD-0002"]
    (leido,) = [
        i
        for i in f.ok(cliente.get("/api/admin/supplies"))["insumos"]
        if i["id"] == clave
    ]
    assert (
        leido["categoria_id"],
        leido["fabricante_id"],
        leido["variante"],
        leido["codigo_fabricante"],
        leido["modelos_compatibles"],
    ) == (
        "CAT-001",
        "FAB-001",
        "alta capacidad",
        "APN-661",
        ["MOD-0001", "MOD-0002"],
    )
    (situacion,) = [
        i for i in f.ok(cliente.get("/api/inventory")) if i["id"] == clave
    ]
    assert situacion["modelos_compatibles"] == ["MOD-0001", "MOD-0002"]
    # Busqueda por el codigo del fabricante.
    assert [
        i["id"]
        for i in f.ok(
            cliente.get("/api/inventory", params={"buscar": "apn-6"})
        )
    ] == [clave]
    # Un modelo dado de baja no se agrega; uno desconocido tampoco. Nada
    # cambia (tampoco el nombre del mismo pedido).
    for modelos, mensaje in (
        (["MOD-0001", "MOD-0003"], "dados de baja"),
        (["MOD-9999"], "No existen"),
    ):
        assert mensaje in f.conflicto(
            cliente.put(
                f"/api/admin/supplies/{clave}",
                json={
                    "usuario_id": f.ADMINISTRADOR,
                    "nombre": "Otro nombre",
                    "modelos_compatibles": modelos,
                },
            )
        )
    assert _sql(
        base, "select nombre from rma.insumo where clave = %s", (clave,)
    ) == [("Batería iPhone 14",)]
    # Reemplazo del conjunto: se quita MOD-0001 y se agrega MOD-0004. Lo que
    # el pedido no trae se conserva.
    editado = f.ok(
        cliente.put(
            f"/api/admin/supplies/{clave}",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Batería iPhone 14",
                "modelos_compatibles": ["MOD-0004", "MOD-0002"],
            },
        )
    )
    assert editado["modelos_compatibles"] == ["MOD-0002", "MOD-0004"]
    assert (editado["categoria_id"], editado["fabricante_id"]) == (
        "CAT-001",
        "FAB-001",
    )
    assert _sql(
        base,
        """
        select m.codigo from rma.insumo_compatibilidad x
          join rma.modelo_equipo m on m.id = x.modelo_equipo_id
          join rma.insumo i on i.id = x.insumo_id
         where i.clave = %s order by 1
        """,
        (clave,),
    ) == [("MOD-0002",), ("MOD-0004",)]
    # Un modelo dado de baja que el insumo ya tenia se conserva.
    _ejecutar(
        base,
        "update rma.modelo_equipo set activo = false "
        "where codigo = 'MOD-0004'",
    )
    f.ok(
        cliente.put(
            f"/api/admin/supplies/{clave}",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Batería iPhone 14",
                "modelos_compatibles": ["MOD-0002", "MOD-0004", "MOD-0005"],
            },
        )
    )
    # Volver a universal y desclasificar.
    universal = f.ok(
        cliente.put(
            f"/api/admin/supplies/{clave}",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Batería iPhone 14",
                "categoria_id": None,
                "fabricante_id": None,
                "modelos_compatibles": [],
            },
        )
    )
    assert universal["modelos_compatibles"] == []
    assert universal["categoria_id"] is None
    assert universal["variante"] == "alta capacidad"
    auditoria = _auditoria(base, "INSUMO", clave)
    assert ("categoria", None, "CAT-001") in auditoria
    assert ("fabricante", None, "FAB-001") in auditoria
    assert ("codigo_fabricante", None, "APN-661") in auditoria
    assert [a for a in auditoria if a[0] == "compatibilidad"] == [
        ("compatibilidad", None, "MOD-0001, MOD-0002"),
        ("compatibilidad", "MOD-0001, MOD-0002", "MOD-0002, MOD-0004"),
        (
            "compatibilidad",
            "MOD-0002, MOD-0004",
            "MOD-0002, MOD-0004, MOD-0005",
        ),
        ("compatibilidad", "MOD-0002, MOD-0004, MOD-0005", None),
    ]
    assert ("categoria", "CAT-001", None) in auditoria
    # D-14.5: la clasificacion no mueve stock.
    assert (
        _sql(base, "select count(*) from rma.movimiento_inventario")
        == stock_antes
    )


def test_categoria_o_fabricante_de_baja_no_se_asignan(admin, base):
    _, cliente = admin
    _alta(cliente, "/api/admin/supply-categories", nombre="Flex")
    _alta(
        cliente,
        "/api/admin/supply-categories",
        nombre="Carga",
        padre_id="CAT-001",
    )
    insumo = _alta(
        cliente,
        "/api/admin/supplies",
        nombre="Flex de carga",
        categoria_id="CAT-002",
    )
    f.ok(
        cliente.put(
            "/api/admin/supply-categories/CAT-001",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Flex",
                "activo": False,
            },
        )
    )
    # El insumo la conserva y se puede seguir editando.
    f.ok(
        cliente.put(
            f"/api/admin/supplies/{insumo['id']}",
            json={"usuario_id": f.ADMINISTRADOR, "nombre": "Flex de carga 2"},
        )
    )
    # Pero no se asigna a otro: la subcategoria de una categoria de baja
    # tampoco.
    assert "dada de baja" in f.conflicto(
        cliente.post(
            "/api/admin/supplies",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Otro flex",
                "categoria_id": "CAT-002",
            },
        )
    )
    assert "dada de baja" in f.conflicto(
        cliente.post(
            "/api/admin/supply-categories",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Botones",
                "padre_id": "CAT-001",
            },
        )
    )


def test_la_compatibilidad_se_escribe_con_el_insumo_o_nada(
    admin, base, monkeypatch
):
    """Si la compatibilidad no queda como se pidio (un modelo que no existe
    y paso la validacion), se revierte tambien el insumo y su auditoria."""
    app, cliente = admin
    insumo = _alta(cliente, "/api/admin/supplies", nombre="Adhesivo")
    clave = insumo["id"]
    auditoria = _auditoria(base, "INSUMO", clave)
    monkeypatch.setattr(
        app_operativa, "validar_clasificacion", lambda *a, **k: None
    )
    with pytest.raises(PersistenciaError):
        app_operativa.guardar_insumo(
            app.state.contexto,
            usuario_id=f.ADMINISTRADOR,
            clave=clave,
            nombre="Adhesivo B-7000",
            unidad="unidad",
            activo=True,
            nuevo=False,
            modelos_compatibles=["MOD-0001", "MOD-9999"],
        )
    assert _sql(
        base, "select nombre from rma.insumo where clave = %s", (clave,)
    ) == [("Adhesivo",)]
    assert _sql(base, "select count(*) from rma.insumo_compatibilidad") == [
        (0,)
    ]
    assert _auditoria(base, "INSUMO", clave) == auditoria
