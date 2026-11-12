"""Macroiteracion V1.4 con los permisos minimos de ``rma_backend``.

En Supabase la API conecta como ``rma_api``, miembro de ``rma_backend``. Las
pruebas de la macroiteracion corren aca con un rol de login local con esos
mismos permisos: evaluacion tecnica (insert en ``evaluacion_tecnica``),
reparaciones adicionales, descarte y la administracion de catalogos (alta y
edicion de Tipos, retiro de un tipo de una Mesa con DELETE en
``mesa_tipo_reparacion``, auditoria con columna identity y la vista
``historial_precio``). Las aserciones sobre la base leen como administrador.
"""

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.storage.postgres import (  # noqa: E402
    AjustesPostgres,
    configuracion_postgres,
)
from app.storage.postgres.ordenes import (  # noqa: E402
    PostgresOrdenReparacionRepository,
)
from app.storage.postgres.transaccion import (  # noqa: E402
    UnidadDeTrabajoPostgres,
    abrir_pool,
)
from tests.postgres import test_configuracion_postgres as config  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres import test_permisos_rma_backend as permisos  # noqa: E402
from tests.postgres.test_configuracion_postgres import (  # noqa: E402,F401
    test_alta_y_edicion_de_un_tipo_con_su_auditoria,
    test_tipos_habilitados_de_una_mesa,
    test_un_cambio_de_precio_no_altera_lo_registrado,
)
from tests.postgres.test_macro_v14_postgres import (  # noqa: E402,F401
    test_v14_antecedentes_y_reporte_en_postgres,
    test_v14_descarte_tecnico_se_guarda,
    test_v14_evaluacion_confirmada_se_guarda_y_se_relee,
    test_v14_redefinicion_en_la_evaluacion_se_guarda,
    test_v14_reparaciones_adicionales_se_guardan,
)

base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api
admin = config.admin
url_rma_backend = permisos.url_rma_backend


@pytest.fixture
def armar(base, url_rma_backend):
    pools = []

    def _armar(**valores):
        configuracion = configuracion_postgres(
            Settings(
                _env_file=None,
                persistencia="postgres",
                database_url=url_rma_backend,
            )
        )
        ajustes = AjustesPostgres(**{"pool_max": 3, **valores})
        pool = abrir_pool(configuracion, ajustes)
        pool.wait(10)
        pools.append(pool)
        unidad = UnidadDeTrabajoPostgres(pool, ajustes)
        return PostgresOrdenReparacionRepository(unidad), unidad

    yield _armar
    for pool in pools:
        pool.close()


def test_la_api_de_estas_pruebas_conecta_con_el_rol_minimo(admin, base):
    """Sin esto, las pruebas importadas podrian pasar como superusuario."""
    admin.get("/api/admin/catalog")
    with psycopg.connect(base, autocommit=True) as conexion:
        usuarios = {
            fila[0]
            for fila in conexion.execute(
                "select usename from pg_stat_activity where datname = "
                "current_database() and pid <> pg_backend_pid()"
            ).fetchall()
        }
        superusuario = conexion.execute(
            "select rolsuper from pg_roles where rolname = %s", (permisos.ROL,)
        ).fetchone()
    assert usuarios == {permisos.ROL}
    assert superusuario == (False,)
