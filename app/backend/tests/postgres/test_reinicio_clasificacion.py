"""Cada tabla del esquema completo está clasificada para el reinicio.

Si una migración agrega una tabla a ``rma`` sin clasificarla en
``01_reiniciar.sql`` y ``06_limpiar_e2e.sql``, los dos scripts abortan en el
UAT. Esta prueba lo detecta antes, en CI.
"""

import pytest

from tests.test_scripts_reinicio_uat import _texto, lista

pytestmark = pytest.mark.postgres


def test_todas_las_tablas_de_rma_estan_clasificadas(postgres_descartable):
    import psycopg

    with psycopg.connect(postgres_descartable) as conexion:
        tablas = {
            t
            for (t,) in conexion.execute(
                "select c.relname from pg_class c"
                " join pg_namespace n on n.oid = c.relnamespace"
                " where n.nspname = 'rma' and c.relkind in ('r', 'p')"
            )
        }
    texto = _texto("06_limpiar_e2e.sql")
    clasificadas = set(lista(texto, "c_operativas")) | set(
        lista(texto, "c_maestras")
    )
    assert tablas - clasificadas == set()
    assert clasificadas - tablas == set()
