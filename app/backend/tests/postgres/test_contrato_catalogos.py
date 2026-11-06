"""Catalogos: el mismo contrato y los mismos resultados en JSON y en
PostgreSQL (E3-B). Tambien la migracion de E3 y la integridad.

La implementacion JSON lee los catalogos de demostracion
(``app/backend/data/catalogs``); la PostgreSQL, la base local cargada con
las mismas fuentes (``supabase/scripts/generar_datos_iniciales.cjs``).
Sin ``RMA_TEST_DATABASE_URL`` corren solo las de JSON.

Diseno: ``docs/postgresql/e3-catalogos-diseno.md`` (secciones 4 y 6).
"""

import shutil
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.core.config import Settings
from app.domain.models import (
    DATOS_EMPRESA_PREDETERMINADOS,
    MEDIOS_PAGO_PREDETERMINADOS,
    TIPO_REPARACION_OTROS,
)
from app.repositories.exceptions import (
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)
from app.storage import JsonCatalogosRepository, JsonModelosEquipoRepository

DATOS_DEMO = Path(__file__).resolve().parents[2] / "data" / "catalogs"
LISTADOS = (
    "listar_tipos_reparacion",
    "listar_insumos",
    "listar_tipo_reparacion_insumos",
    "listar_estaciones",
    "listar_tipo_reparacion_estaciones",
    "listar_usuarios",
    "listar_medios_pago",
)
ETIQUETAS = {
    "obtener_tipo_reparacion": "Tipo de Reparacion",
    "obtener_insumo": "Insumo",
    "obtener_estacion": "Estacion de Trabajo",
    "obtener_usuario": "Usuario",
    "obtener_medio_pago": "Medio de pago",
}


def _json(tmp_path):
    destino = tmp_path / "catalogs"
    shutil.copytree(DATOS_DEMO, destino)
    return (
        JsonCatalogosRepository(destino),
        JsonModelosEquipoRepository(Settings().modelos_equipo_archivo),
    )


def _postgres(url):
    pytest.importorskip("psycopg_pool")
    from app.storage.postgres import AjustesPostgres, configuracion_postgres
    from app.storage.postgres.catalogos import PostgresCatalogosRepository
    from app.storage.postgres.modelos_equipo import (
        PostgresModelosEquipoRepository,
    )
    from app.storage.postgres.transaccion import (
        UnidadDeTrabajoPostgres,
        abrir_pool,
    )

    configuracion = configuracion_postgres(
        Settings(_env_file=None, persistencia="postgres", database_url=url)
    )
    ajustes = AjustesPostgres(pool_max=2)
    pool = abrir_pool(configuracion, ajustes)
    unidad = UnidadDeTrabajoPostgres(pool, ajustes)
    return (
        PostgresCatalogosRepository(unidad),
        PostgresModelosEquipoRepository(unidad),
        pool,
    )


@pytest.fixture(scope="module")
def postgres(request):
    url = request.getfixturevalue("postgres_descartable")
    catalogos, modelos, pool = _postgres(url)
    yield catalogos, modelos
    pool.close()


@pytest.fixture(params=["json", "postgres"])
def impl(request, tmp_path):
    if request.param == "json":
        return _json(tmp_path)
    return request.getfixturevalue("postgres")


# --- Equivalencia: mismos datos, mismo orden, misma representacion -----------


@pytest.mark.parametrize("metodo", LISTADOS)
def test_cada_listado_es_identico_en_json_y_postgres(
    metodo, tmp_path, postgres
):
    de_json = getattr(_json(tmp_path)[0], metodo)()
    de_postgres = getattr(postgres[0], metodo)()
    assert de_postgres == de_json
    # Lo que ve la API: tambien la forma de los numeros (80000, no 80000.00).
    assert [m.model_dump(mode="json") for m in de_postgres] == [
        m.model_dump(mode="json") for m in de_json
    ]


def test_empresa_y_modelos_identicos_en_json_y_postgres(tmp_path, postgres):
    catalogos, modelos = _json(tmp_path)
    assert postgres[0].obtener_datos_empresa() == (
        catalogos.obtener_datos_empresa()
    )
    assert postgres[1].listar_modelos() == modelos.listar_modelos()
    assert [
        m.model_dump(mode="json") for m in postgres[1].listar_modelos()
    ] == [m.model_dump(mode="json") for m in modelos.listar_modelos()]


# --- Contrato (cada implementacion) ------------------------------------------


def test_obtener_devuelve_lo_mismo_que_el_listado(impl):
    catalogos, modelos = impl[0], impl[1]
    for metodo_lista, metodo in (
        ("listar_tipos_reparacion", "obtener_tipo_reparacion"),
        ("listar_insumos", "obtener_insumo"),
        ("listar_estaciones", "obtener_estacion"),
        ("listar_usuarios", "obtener_usuario"),
        ("listar_medios_pago", "obtener_medio_pago"),
    ):
        for entidad in getattr(catalogos, metodo_lista)():
            assert getattr(catalogos, metodo)(entidad.id) == entidad
    for modelo in modelos.listar_modelos():
        assert modelos.obtener_modelo(modelo.id) == modelo


@pytest.mark.parametrize("metodo", sorted(ETIQUETAS))
def test_no_encontrado_con_el_mismo_mensaje(impl, metodo):
    with pytest.raises(EntidadPersistidaNoEncontradaError) as capturado:
        getattr(impl[0], metodo)("NO-EXISTE")
    assert (
        str(capturado.value) == f"No existe el {ETIQUETAS[metodo]} NO-EXISTE"
    )
    assert impl[1].obtener_modelo("MOD-9999") is None


def test_tr_otros_no_es_parte_del_catalogo(impl):
    catalogos = impl[0]
    assert TIPO_REPARACION_OTROS not in [
        t.id for t in catalogos.listar_tipos_reparacion()
    ]
    with pytest.raises(EntidadPersistidaNoEncontradaError):
        catalogos.obtener_tipo_reparacion(TIPO_REPARACION_OTROS)


def test_orden_de_usuarios_y_medios_de_pago(impl):
    catalogos = impl[0]
    assert [u.id for u in catalogos.listar_usuarios()] == [
        "RECEP-001",
        "COORD-001",
        "TECH-001",
        "ADMIN-001",
    ]
    assert catalogos.listar_medios_pago() == list(MEDIOS_PAGO_PREDETERMINADOS)


def test_el_insumo_conserva_id_y_codigo(impl):
    (insumo,) = impl[0].listar_insumos()
    assert (insumo.id, insumo.codigo) == ("INS-001", "BAT-IP14")
    assert insumo.unidad is None and insumo.stock_fisico == Decimal("2")
    assert [p.insumo_id for p in impl[0].listar_tipo_reparacion_insumos()] == [
        "INS-001"
    ]


def test_los_36_modelos_en_el_orden_del_catalogo(impl):
    ids = [m.id for m in impl[1].listar_modelos()]
    assert len(ids) == 36 and ids == sorted(ids)


# --- Solo PostgreSQL ---------------------------------------------------------


def test_el_stock_se_escribe_solo_dentro_de_un_comando(postgres):
    """E5 (A7): el historial son los ingresos y ajustes de un usuario; el
    saldo inicial de desarrollo, cargado por el sistema, no lo es (en JSON
    vive en el catalogo). Escribir exige la transaccion del comando."""
    catalogos = postgres[0]
    assert catalogos.listar_movimientos_stock() == []
    for llamada in (
        lambda: catalogos.actualizar_stock_insumo("INS-001", Decimal("1")),
        lambda: catalogos.registrar_movimiento_stock(None),
    ):
        with pytest.raises(PersistenciaError, match="transaccion"):
            llamada()


def test_la_lectura_no_espera_filas_bloqueadas(postgres, postgres_descartable):
    import time

    import psycopg

    catalogos = postgres[0]
    antes = catalogos.listar_insumos()
    with psycopg.connect(postgres_descartable) as otra:
        # Otra transaccion cambia y bloquea filas, sin confirmar.
        otra.execute("update rma.insumo set nombre = 'Sin confirmar'")
        otra.execute("select 1 from rma.usuario for update")
        inicio = time.monotonic()
        insumos = catalogos.listar_insumos()
        usuarios = catalogos.listar_usuarios()
        demora = time.monotonic() - inicio
        otra.rollback()
    # Ni espera los bloqueos (lock_timeout es 5 s) ni ve lo no confirmado.
    assert demora < 2
    assert insumos == antes
    assert usuarios


@pytest.fixture(scope="module")
def admin(postgres_descartable):
    from tests.postgres.base_local import url_admin_local

    url = urlsplit(postgres_descartable)
    return url_admin_local(url._replace(path="/postgres").geturl())


def _base(admin, filtro):
    """Una base aparte con los SQL de ``archivos_sql()`` que pasen
    ``filtro``; devuelve (url, nombre)."""
    from tests.postgres.base_local import archivos_sql, crear_base

    url = crear_base(admin, [a for a in archivos_sql() if filtro(a)])
    return url, urlsplit(url).path.lstrip("/")


def _solo_migraciones(archivo):
    return archivo.parent.name == "migrations"


@pytest.fixture
def base_vacia(admin):
    from tests.postgres.base_local import borrar_base

    url, nombre = _base(admin, _solo_migraciones)
    yield url
    borrar_base(admin, nombre)


def test_sin_filas_listas_vacias_y_predeterminados(base_vacia):
    catalogos, modelos, pool = _postgres(base_vacia)
    try:
        for metodo in LISTADOS:
            if metodo != "listar_medios_pago":
                assert getattr(catalogos, metodo)() == []
        assert catalogos.listar_medios_pago() == list(
            MEDIOS_PAGO_PREDETERMINADOS
        )
        assert catalogos.obtener_medio_pago("EFECTIVO").nombre == "Efectivo"
        assert catalogos.obtener_datos_empresa() == (
            DATOS_EMPRESA_PREDETERMINADOS
        )
        assert modelos.listar_modelos() == []
    finally:
        pool.close()


def _sql(url, texto, parametros=None):
    import psycopg

    with psycopg.connect(url, autocommit=True) as conexion:
        conexion.execute(texto, parametros)


def test_numeros_enteros_decimales_y_limites(base_vacia, tmp_path):
    """Los mismos valores cargados en JSON y en PostgreSQL dan el mismo
    modelo y la misma representacion en la API."""
    _sql(
        base_vacia,
        """
        insert into rma.tipo_reparacion
          (codigo, nombre, precio, puntaje, garantia_dias) values
          ('TR-A', 'Cero', 0, 0, 0),
          ('TR-B', 'Decimal', 12345.5, 1, 30),
          ('TR-C', 'Limite', 999999999999.99, 2, 90);
        insert into rma.insumo (clave, codigo, nombre, unidad) values
          ('INS-A', 'COD-A', 'Insumo A', 'ml');
        insert into rma.tipo_reparacion_insumo values (
          (select id from rma.tipo_reparacion where codigo = 'TR-B'),
          (select id from rma.insumo where clave = 'INS-A'), 0.250);
        insert into rma.accion_usuario (proceso, operacion, resultado)
          values ('PRUEBA', 'STOCK', 'CONFIRMADA');
        insert into rma.movimiento_inventario
          (codigo, tipo, insumo_id, cantidad, motivo_texto, accion_id)
          values ('MST-A', 'INGRESO',
            (select id from rma.insumo where clave = 'INS-A'), 1.250,
            'prueba', (select id from rma.accion_usuario limit 1));
        """,
    )
    import json

    directorio = tmp_path / "numeros"
    directorio.mkdir()
    tipos = [
        {
            "id": "TR-A",
            "nombre": "Cero",
            "precio": "0",
            "puntaje": 0,
            "garantia_dias": 0,
        },
        {
            "id": "TR-B",
            "nombre": "Decimal",
            "precio": "12345.5",
            "puntaje": 1,
            "garantia_dias": 30,
        },
        {
            "id": "TR-C",
            "nombre": "Limite",
            "precio": "999999999999.99",
            "puntaje": 2,
            "garantia_dias": 90,
        },
    ]
    (directorio / "tipos_reparacion.json").write_text(json.dumps(tipos))
    (directorio / "insumos.json").write_text(
        json.dumps(
            [
                {
                    "id": "INS-A",
                    "codigo": "COD-A",
                    "nombre": "Insumo A",
                    "unidad": "ml",
                    "stock_fisico": "1.25",
                },
            ]
        )
    )
    (directorio / "tipo_reparacion_insumos.json").write_text(
        json.dumps(
            [
                {
                    "tipo_reparacion_id": "TR-B",
                    "insumo_id": "INS-A",
                    "cantidad": "0.25",
                },
            ]
        )
    )
    de_json = JsonCatalogosRepository(directorio)
    catalogos, _, pool = _postgres(base_vacia)
    try:
        for metodo in (
            "listar_tipos_reparacion",
            "listar_insumos",
            "listar_tipo_reparacion_insumos",
        ):
            pg = getattr(catalogos, metodo)()
            js = getattr(de_json, metodo)()
            assert pg == js
            assert [m.model_dump(mode="json") for m in pg] == [
                m.model_dump(mode="json") for m in js
            ]
        precios = [str(t.precio) for t in catalogos.listar_tipos_reparacion()]
        assert precios == ["0", "12345.5", "999999999999.99"]
    finally:
        pool.close()


def test_un_usuario_sin_rol_o_con_dos_roles_es_un_error(base_vacia):
    _sql(
        base_vacia,
        """
        insert into rma.usuario (codigo, nombre) values
          ('U-SIN', 'Sin rol'), ('U-DOS', 'Dos roles'), ('U-UNO', 'Uno');
        insert into rma.usuario_rol (usuario_id, rol_id)
          select u.id, r.id from rma.usuario u, rma.rol r
          where (u.codigo = 'U-DOS' and r.codigo in ('TECNICO', 'RECEPCION'))
             or (u.codigo = 'U-UNO' and r.codigo = 'TECNICO');
        """,
    )
    catalogos, _, pool = _postgres(base_vacia)
    try:
        assert catalogos.obtener_usuario("U-UNO").rol.value == "TECNICO"
        for codigo, roles in (("U-SIN", 0), ("U-DOS", 2)):
            with pytest.raises(PersistenciaError, match=f"{roles} roles"):
                catalogos.obtener_usuario(codigo)
        with pytest.raises(PersistenciaError, match="roles"):
            catalogos.listar_usuarios()
    finally:
        pool.close()


def test_integridad_de_la_clave_y_las_relaciones(base_vacia):
    """Restricciones que PostgreSQL agrega a JSON (diferencias admisibles):
    clave unica y no vacia, y nada de insumos previstos huerfanos."""
    import psycopg

    _sql(
        base_vacia,
        "insert into rma.insumo (clave, codigo, nombre) values "
        "('INS-1', 'C-1', 'Uno')",
    )
    for texto, error in (
        (
            "insert into rma.insumo (clave, codigo, nombre) values "
            "('INS-1', 'C-2', 'Repetida')",
            psycopg.errors.UniqueViolation,
        ),
        (
            "insert into rma.insumo (clave, codigo, nombre) values "
            "('  ', 'C-3', 'Vacia')",
            psycopg.errors.CheckViolation,
        ),
        (
            # La clave por defecto (el codigo) choca con una existente.
            "insert into rma.insumo (codigo, nombre) values ('INS-1', 'X')",
            psycopg.errors.UniqueViolation,
        ),
        (
            "insert into rma.tipo_reparacion_insumo values "
            "(gen_random_uuid(), (select id from rma.insumo limit 1), 1)",
            psycopg.errors.ForeignKeyViolation,
        ),
    ):
        with pytest.raises(error):
            _sql(base_vacia, texto)
    # Un alta sin clave toma su codigo (trigger de la migracion de E3).
    _sql(
        base_vacia,
        "insert into rma.insumo (codigo, nombre) values ('C-4', 'Sin clave')",
    )
    with psycopg.connect(base_vacia, autocommit=True) as conexion:
        assert conexion.execute(
            "select clave from rma.insumo where codigo = 'C-4'"
        ).fetchone() == ("C-4",)


def test_la_migracion_conserva_los_insumos_y_la_carga_fija_la_clave(admin):
    """Filas anteriores a E3: la migracion las conserva y las completa con
    su codigo; la carga regenerada fija la clave del dominio y el orden, y
    volver a aplicarla no cambia nada."""
    import psycopg

    from tests.postgres.base_local import archivos_sql, borrar_base

    migracion_e3 = next(
        a for a in archivos_sql() if a.name.endswith("_e3_catalogos.sql")
    )
    url, nombre = _base(
        # Las anteriores a E3: las posteriores suponen sus columnas.
        admin,
        lambda a: _solo_migraciones(a) and a.name < migracion_e3.name,
    )
    try:
        with psycopg.connect(url, autocommit=True) as conexion:
            conexion.execute(
                "insert into rma.insumo (codigo, nombre) values "
                "('BAT-IP14', 'Bateria iPhone 14'), ('OTRO-1', 'Otro');"
                "insert into rma.usuario (codigo, nombre) values "
                "('ADMIN-001', 'Administracion Demo')"
            )
            # Con la autorizacion del paso de E8 (QAF-13): hay datos.
            conexion.execute(
                "set rma.migracion_e3 = 'estrategia_identidad_aprobada'"
            )
            conexion.execute(migracion_e3.read_text(encoding="utf-8"))
            assert conexion.execute(
                "select codigo, clave from rma.insumo order by codigo"
            ).fetchall() == [("BAT-IP14", "BAT-IP14"), ("OTRO-1", "OTRO-1")]
            cargas = [
                a for a in archivos_sql() if a.parent.name != "migrations"
            ]
            for archivo in cargas:
                conexion.execute(archivo.read_text(encoding="utf-8"))
            estado = conexion.execute(
                "select codigo, clave, modificado_en from rma.insumo "
                "order by codigo"
            ).fetchall()
            assert [(c, k) for c, k, _ in estado] == [
                ("BAT-IP14", "INS-001"),
                ("OTRO-1", "OTRO-1"),
            ]
            ordenes = conexion.execute(
                "select codigo, orden from rma.usuario order by orden"
            ).fetchall()
            assert ordenes == [
                ("RECEP-001", 1),
                ("COORD-001", 2),
                ("TECH-001", 3),
                ("ADMIN-001", 4),
            ]
            # Idempotente: otra vez las cargas, sin cambios.
            for archivo in cargas:
                conexion.execute(archivo.read_text(encoding="utf-8"))
            assert (
                conexion.execute(
                    "select codigo, clave, modificado_en from rma.insumo "
                    "order by codigo"
                ).fetchall()
                == estado
            )
            assert (
                conexion.execute(
                    "select count(*) from rma.movimiento_inventario"
                ).fetchone()[0]
                == 1
            )
    finally:
        borrar_base(admin, nombre)
