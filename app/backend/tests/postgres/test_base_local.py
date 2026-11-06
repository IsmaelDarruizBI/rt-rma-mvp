"""Conexion a la base local descartable y traduccion de errores reales.

Las pruebas marcadas ``postgres`` necesitan ``RMA_TEST_DATABASE_URL``;
las demas corren siempre y no abren conexiones a ningun servidor
remoto.
"""

import pytest

from app.core.config import Settings
from app.repositories.exceptions import (
    ConflictoDeEscrituraError,
    PersistenciaError,
    RestriccionDeIntegridadError,
)
from app.storage.postgres import (
    conectar,
    configuracion_postgres,
    es_reintentable,
    servidor_unico,
    traducir_error,
)
from tests.postgres.base_local import (
    RAIZ_SUPABASE,
    archivos_sql,
    url_admin_local,
)

PASSWORD = "Clave-De-Prueba-No-Debe-Verse"


def _configuracion(url: str):
    return configuracion_postgres(
        Settings(_env_file=None, persistencia="postgres", database_url=url)
    )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://rma_api.ref:x@aws-1-us-west-2.pooler.supabase.com"
        ":6543/postgres",
        "postgresql://postgres:x@db.ref.supabase.co:5432/postgres",
        "postgresql://postgres@10.0.0.5:5432/postgres",
        "no-es-una-url",
        # Parecen locales, pero libpq conectaria a otro servidor.
        "postgresql://postgres@localhost/postgres?host=db.ref.supabase.co",
        "postgresql://postgres@127.0.0.1/postgres?hostaddr=203.0.113.9",
        "postgresql://postgres@localhost/postgres?service=remoto",
        "postgresql://postgres@localhost,db.ref.supabase.co/postgres",
    ],
)
def test_la_base_de_pruebas_rechaza_servidores_remotos(url):
    with pytest.raises(ValueError, match="PostgreSQL local"):
        url_admin_local(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres@127.0.0.1:54329/postgres?sslmode=disable",
        "postgres://postgres@[::1]:5432/rma",
        "postgresql://rma_api.ref:x@aws-1-us-west-2.pooler.supabase.com"
        ":6543/postgres?sslmode=verify-full",
    ],
)
def test_el_host_validado_es_el_que_usa_libpq(url):
    conninfo = pytest.importorskip("psycopg.conninfo")
    assert conninfo.conninfo_to_dict(url)["host"] == servidor_unico(url)


def test_la_base_de_pruebas_acepta_un_servidor_local():
    url = "postgresql://postgres@127.0.0.1:54329/postgres"
    assert url_admin_local(url) == url


def test_las_pruebas_cargan_migraciones_y_seeds_en_orden():
    archivos = [
        archivo.relative_to(RAIZ_SUPABASE).as_posix()
        for archivo in archivos_sql()
    ]
    assert len(archivos) >= 12
    assert archivos[0] == "migrations/20261102000100_base.sql"
    primera_seed = next(
        i for i, a in enumerate(archivos) if a.startswith("seeds/")
    )
    assert all(a.startswith("migrations/") for a in archivos[:primera_seed])
    assert archivos[-1].startswith("seeds/desarrollo/")


def test_un_fallo_de_conexion_no_expone_la_contrasena():
    pytest.importorskip("psycopg")
    # Puerto local cerrado: falla en el acto, sin salir de la maquina.
    configuracion = _configuracion(
        f"postgresql://usuario:{PASSWORD}@127.0.0.1:1/postgres"
    )
    with pytest.raises(PersistenciaError) as capturado:
        conectar(configuracion)
    assert PASSWORD not in str(capturado.value)
    assert capturado.value.__cause__ is None


@pytest.mark.postgres
def test_el_esquema_rma_queda_completo_y_consistente(postgres_descartable):
    with conectar(_configuracion(postgres_descartable)) as conexion:
        assert conexion.prepare_threshold is None
        assert conexion.info.server_version >= 150000
        aplicacion = conexion.execute("show application_name").fetchone()
        assert aplicacion == ("rt-rma-api",)
        conteo = conexion.execute(
            """
            select count(*) filter (where table_type = 'BASE TABLE'),
                   count(*) filter (where table_type = 'VIEW')
            from information_schema.tables
            where table_schema = 'rma'
            """
        ).fetchone()
        assert conteo == (45, 6)
        diferencias = conexion.execute(
            "select count(*) from rma.verificar_integridad()"
        ).fetchone()
        assert diferencias == (0,)


@pytest.mark.postgres
def test_set_local_limita_solo_su_transaccion(postgres_descartable):
    import psycopg

    with conectar(_configuracion(postgres_descartable)) as conexion:
        previo = conexion.execute("show statement_timeout").fetchone()
        with pytest.raises(psycopg.errors.QueryCanceled) as capturado:
            with conexion.transaction():
                conexion.execute("set local statement_timeout = '50ms'")
                conexion.execute("select pg_sleep(1)")
        posterior = conexion.execute("show statement_timeout").fetchone()

    assert posterior == previo
    assert not es_reintentable(capturado.value)
    traducido = traducir_error(capturado.value)
    assert isinstance(traducido, PersistenciaError)
    assert "57014" in str(traducido)


@pytest.mark.postgres
def test_un_bloqueo_vencido_es_reintentable(postgres_descartable):
    import psycopg

    configuracion = _configuracion(postgres_descartable)
    with conectar(configuracion) as a, conectar(configuracion) as b:
        with a.transaction():
            a.execute("select 1 from rma.empresa for update")
            with pytest.raises(psycopg.errors.LockNotAvailable) as capturado:
                with b.transaction():
                    b.execute("set local lock_timeout = '100ms'")
                    b.execute("select 1 from rma.empresa for update")

    assert es_reintentable(capturado.value)
    assert isinstance(
        traducir_error(capturado.value), ConflictoDeEscrituraError
    )


@pytest.mark.postgres
def test_una_violacion_de_integridad_no_es_un_conflicto(
    postgres_descartable,
):
    import psycopg

    with conectar(_configuracion(postgres_descartable)) as conexion:
        with pytest.raises(psycopg.errors.IntegrityError) as capturado:
            with conexion.transaction():
                # Reservado por encima del fisico: lo impide el esquema.
                conexion.execute(
                    "update rma.insumo set stock_reservado = stock_fisico + 1"
                )

    traducido = traducir_error(capturado.value)
    assert isinstance(traducido, RestriccionDeIntegridadError)
    assert not isinstance(traducido, ConflictoDeEscrituraError)
    assert not es_reintentable(capturado.value)
