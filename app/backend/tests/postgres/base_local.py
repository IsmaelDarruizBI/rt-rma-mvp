"""PostgreSQL local y descartable para las pruebas ``postgres``.

``RMA_TEST_DATABASE_URL`` apunta a un servidor LOCAL (PostgreSQL 15 o
posterior) con un usuario que pueda crear bases y roles, por ejemplo
``postgresql://postgres@127.0.0.1:54329/postgres``. Sin la variable,
esas pruebas se saltean: la suite ordinaria nunca abre conexiones.

Cada sesion de pytest crea una base nueva (``rma_prueba_<hex>``), le
aplica ``supabase/migrations``, ``supabase/seeds/referencia_operativa`` y
``supabase/seeds/desarrollo`` (datos ficticios), y la borra al terminar.
Una URL a un servidor remoto -Supabase incluido- se rechaza siempre.

Efecto fuera de la base: crea en el servidor los roles de Supabase que
las migraciones revocan (``anon``, ``authenticated``, ``service_role``) y
la migracion de acceso crea ``rma_backend``. Son roles sin login.
"""

import uuid
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.storage.postgres.conexion import HOSTS_LOCALES, servidor_unico

VARIABLE = "RMA_TEST_DATABASE_URL"
RAIZ_SUPABASE = Path(__file__).resolve().parents[4] / "supabase"
CARPETAS_SQL = (
    "migrations",
    "seeds/referencia_operativa",
    "seeds/desarrollo",
)
ROLES_SUPABASE = ("anon", "authenticated", "service_role")


def url_admin_local(url: str) -> str:
    """Devuelve ``url`` si es de un servidor local; si no, ValueError.

    Misma regla que la conexion de la app: el host de la URL tiene que
    ser el unico destino (sin ``host``/``hostaddr``/``service``).
    """
    try:
        host = servidor_unico(url)
    except ValueError:
        host = None
    if host not in HOSTS_LOCALES:
        raise ValueError(
            f"{VARIABLE} tiene que apuntar a un PostgreSQL local "
            "(localhost): las pruebas crean y borran bases."
        )
    return url


def url_de_base(url_admin: str, nombre: str) -> str:
    """La misma conexion, apuntando a la base ``nombre``."""
    return urlunsplit(urlsplit(url_admin)._replace(path=f"/{nombre}"))


def archivos_sql() -> list[Path]:
    """Migraciones y cargas iniciales, en el orden en que se aplican."""
    archivos: list[Path] = []
    for carpeta in CARPETAS_SQL:
        archivos += sorted((RAIZ_SUPABASE / carpeta).glob("*.sql"))
    return archivos


def crear_base(url_admin: str, archivos: Sequence[Path] | None = None) -> str:
    """Crea una base con el esquema ``rma`` cargado; devuelve su URL.

    ``archivos``: los SQL a aplicar, en orden (por defecto, todos los de
    ``archivos_sql()``). Sirve para probar una migracion sobre datos
    anteriores o una base sin cargas.
    """
    import psycopg
    from psycopg import sql

    nombre = f"rma_prueba_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(url_admin, autocommit=True) as admin:
        # Primero los roles: si fallan, no queda una base sin borrar.
        for rol in ROLES_SUPABASE:
            existe = admin.execute(
                "select 1 from pg_roles where rolname = %s", (rol,)
            ).fetchone()
            if not existe:
                admin.execute(
                    sql.SQL("create role {} nologin").format(
                        sql.Identifier(rol)
                    )
                )
        admin.execute(
            sql.SQL("create database {}").format(sql.Identifier(nombre))
        )
    url = url_de_base(url_admin, nombre)
    try:
        with psycopg.connect(url, autocommit=True) as conexion:
            for archivo in archivos_sql() if archivos is None else archivos:
                # Sin parametros: psycopg manda el archivo entero, con
                # todas sus sentencias, en una sola consulta simple.
                conexion.execute(archivo.read_text(encoding="utf-8"))
    except BaseException:
        borrar_base(url_admin, nombre)
        raise
    return url


def clonar_base(url_admin: str, plantilla: str) -> str:
    """Una base nueva, copia de ``plantilla`` (``CREATE DATABASE ...
    TEMPLATE``); devuelve su URL. Aisla cada prueba sin volver a aplicar
    migraciones ni cargas. La plantilla no puede tener conexiones abiertas.
    """
    import psycopg
    from psycopg import sql

    nombre = f"rma_prueba_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(url_admin, autocommit=True) as admin:
        admin.execute(
            sql.SQL("create database {} template {}").format(
                sql.Identifier(nombre), sql.Identifier(plantilla)
            )
        )
    return url_de_base(url_admin, nombre)


def borrar_base(url_admin: str, nombre: str) -> None:
    """Borra la base aunque queden conexiones abiertas."""
    import psycopg
    from psycopg import sql

    with psycopg.connect(url_admin, autocommit=True) as admin:
        admin.execute(
            sql.SQL("drop database if exists {} with (force)").format(
                sql.Identifier(nombre)
            )
        )
