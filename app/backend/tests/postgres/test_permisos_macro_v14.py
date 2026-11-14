"""Macroiteracion V1.4 con los permisos minimos de ``rma_backend``.

En Supabase la API conecta como ``rma_api``, miembro de ``rma_backend``. Las
pruebas de la macroiteracion corren aca con un rol de login local con esos
mismos permisos: evaluacion tecnica (insert en ``evaluacion_tecnica``),
reparaciones adicionales, descarte y la administracion de catalogos (alta y
edicion de Tipos, retiro de un tipo de una Mesa con DELETE en
``mesa_tipo_reparacion``, auditoria con columna identity y la vista
``historial_precio``), motivos, parametros y seguimientos del retiro. Las
aserciones sobre la base leen como administrador.
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
from tests.postgres.test_ajuste_por_detalle_postgres import (  # noqa: E402,F401
    test_ajuste_por_detalle_se_guarda_y_la_vista_coincide,
)
from tests.postgres.test_checklist_postgres import (  # noqa: E402,F401
    cliente_checklist,
    test_checklist_configurable_con_copia_y_versiones,
)
from tests.postgres.test_compras_postgres import (  # noqa: E402,F401
    contexto_compras,
    test_circuito_completo_con_recepciones_parciales,
    test_dos_recepciones_a_la_vez_no_superan_lo_pedido,
    test_series_un_ingreso_por_unidad,
)
from tests.postgres.test_comunicaciones_postgres import (  # noqa: E402,F401
    cliente_com,
    test_intento_y_confirmacion_se_guardan_inmutables,
    test_plantilla_comercial_exige_consentimiento,
)
from tests.postgres.test_configuracion_postgres import (  # noqa: E402,F401
    test_alta_y_edicion_de_un_tipo_con_su_auditoria,
    test_tipos_habilitados_de_una_mesa,
    test_un_cambio_de_precio_no_altera_lo_registrado,
)
from tests.postgres.test_firmas_postgres import (  # noqa: E402,F401
    cliente_firmas,
    test_firma_de_un_documento_con_la_orden_entregada,
)
from tests.postgres.test_identidad_equipo_postgres import (  # noqa: E402,F401
    test_identidad_compartida_y_correccion_en_postgres,
)
from tests.postgres.test_insumos_admin_postgres import (  # noqa: E402,F401
    cliente_insumos,
    test_alta_y_edicion_de_un_insumo_auditadas,
)
from tests.postgres.test_lotes_postgres import (  # noqa: E402,F401
    lotes,
    taller,
    test_desperdicio_y_devolucion_sin_lote,
    test_lotes_ingreso_consumo_devolucion_y_transicion,
    test_series_de_a_una_y_nunca_dos_veces,
)
from tests.postgres.test_macro_v14_postgres import (  # noqa: E402,F401
    test_v14_antecedentes_y_reporte_en_postgres,
    test_v14_descarte_tecnico_se_guarda,
    test_v14_evaluacion_confirmada_se_guarda_y_se_relee,
    test_v14_redefinicion_en_la_evaluacion_se_guarda,
    test_v14_reparaciones_adicionales_se_guardan,
)
from tests.postgres.test_motivos_retiro_postgres import (  # noqa: E402,F401
    cliente,
    test_motivos_y_parametros_administrados_con_auditoria,
    test_retiro_demorado_y_seguimientos_en_postgres,
)
from tests.postgres.test_reclamos_garantia_postgres import (  # noqa: E402,F401
    test_reclamo_rechazado_y_continuacion_en_postgres,
)
from tests.postgres.test_roles_permisos_postgres import (  # noqa: E402,F401
    test_asignar_un_segundo_rol_y_actuar_con_el,
    test_nunca_sin_administrador,
    test_un_permiso_configurado_rige_en_el_pedido_siguiente,
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
