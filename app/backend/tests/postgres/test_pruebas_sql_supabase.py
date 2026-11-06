"""Las pruebas SQL de ``supabase/tests`` sobre una base local nueva.

Cada archivo aborta con un error si una regla no se cumple. Corren en orden
y comparten la base, que se borra al final: ``00_utilidades.sql`` crea lo que
usan los demas y ``99_limpieza.sql`` lo quita.
"""

import os
from urllib.parse import urlsplit

import pytest

from tests.postgres.base_local import (
    RAIZ_SUPABASE,
    VARIABLE,
    borrar_base,
    crear_base,
    url_admin_local,
)


def test_las_pruebas_sql_de_supabase():
    url = os.environ.get(VARIABLE)
    if not url:
        pytest.skip(f"{VARIABLE} no esta definida: sin PostgreSQL local.")
    psycopg = pytest.importorskip("psycopg")
    admin = url_admin_local(url)
    base = crear_base(admin)
    archivos = sorted((RAIZ_SUPABASE / "tests").glob("*.sql"))
    assert archivos
    try:
        with psycopg.connect(base, autocommit=True) as conexion:
            for archivo in archivos:
                conexion.execute(archivo.read_text(encoding="utf-8"))
    finally:
        borrar_base(admin, urlsplit(base).path.lstrip("/"))
