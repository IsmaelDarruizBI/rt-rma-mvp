"""Fixtures de las pruebas contra un PostgreSQL local descartable."""

import os
from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest

from tests.postgres.base_local import (
    VARIABLE,
    borrar_base,
    crear_base,
    url_admin_local,
)


@pytest.fixture(scope="session")
def postgres_descartable() -> Iterator[str]:
    """URL de una base nueva con el esquema ``rma``; se borra al final.

    Sin ``RMA_TEST_DATABASE_URL`` la prueba se saltea. Una URL que no sea
    local hace fallar la prueba: nunca se toca un servidor remoto.
    """
    url = os.environ.get(VARIABLE)
    if not url:
        pytest.skip(f"{VARIABLE} no esta definida: sin PostgreSQL local.")
    try:
        url_admin = url_admin_local(url)
    except ValueError as error:
        pytest.fail(str(error))
    pytest.importorskip("psycopg")
    url_base = crear_base(url_admin)
    try:
        yield url_base
    finally:
        borrar_base(url_admin, urlsplit(url_base).path.lstrip("/"))
