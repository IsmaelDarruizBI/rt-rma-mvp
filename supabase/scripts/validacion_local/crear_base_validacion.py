# ruff: noqa: E501  (comando de ejemplo largo)
"""(Re)crea la base LOCAL de validación manual ``rma_validacion``.

Aplica, en orden, los mismos SQL que las pruebas ``tests/postgres``
(``base_local.archivos_sql()``): las migraciones, las cargas de referencia
y la carga de desarrollo (usuarios de demostración, TR-001, TR-002, la Mesa
EST-001 e INS-001). Si la base ya existía, la borra y la crea de nuevo:
todo lo cargado en ella se pierde.

Guardas:

- solo un PostgreSQL local (127.0.0.1 o localhost), con la misma regla de
  las pruebas (``url_admin_local``);
- solo la base ``rma_validacion``: cualquier otro nombre se rechaza antes
  de conectarse. ``rma_dev``, ``rma_ensayo_integral`` y las demás no se
  tocan.

Uso (desde cualquier carpeta; mejor con el ``.ps1`` de al lado):

    app/backend/.venv/Scripts/python supabase/scripts/validacion_local/crear_base_validacion.py

Esperado: «56 archivos SQL; 80 tablas en rma».
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
BACKEND = RAIZ / "app" / "backend"
sys.path.insert(0, str(BACKEND))

BASE_PERMITIDA = "rma_validacion"
URL_ADMIN = "postgresql://postgres@127.0.0.1:54329/postgres"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base",
        default=BASE_PERMITIDA,
        help="Nombre de la base. Solo se admite «rma_validacion».",
    )
    parser.add_argument(
        "--url-admin",
        default=URL_ADMIN,
        help="Conexión de administración al PostgreSQL local.",
    )
    args = parser.parse_args()

    if args.base != BASE_PERMITIDA:
        print(
            f"Rechazado: este script solo (re)crea «{BASE_PERMITIDA}», "
            f"no «{args.base}».",
            file=sys.stderr,
        )
        return 2

    import psycopg
    from psycopg import sql

    from tests.postgres.base_local import (
        ROLES_SUPABASE,
        archivos_sql,
        url_admin_local,
        url_de_base,
    )

    try:
        admin = url_admin_local(args.url_admin)
    except ValueError as error:
        print(f"Rechazado: {error}", file=sys.stderr)
        return 2

    archivos = archivos_sql()
    with psycopg.connect(admin, autocommit=True) as conexion:
        for rol in ROLES_SUPABASE:
            existe = conexion.execute(
                "select 1 from pg_roles where rolname = %s", (rol,)
            ).fetchone()
            if not existe:
                conexion.execute(
                    sql.SQL("create role {} nologin").format(
                        sql.Identifier(rol)
                    )
                )
        # «with (force)» corta las conexiones abiertas (por ejemplo, un
        # backend que quedó corriendo sobre esta base).
        conexion.execute(
            sql.SQL("drop database if exists {} with (force)").format(
                sql.Identifier(BASE_PERMITIDA)
            )
        )
        conexion.execute(
            sql.SQL("create database {}").format(
                sql.Identifier(BASE_PERMITIDA)
            )
        )

    url = url_de_base(admin, BASE_PERMITIDA)
    with psycopg.connect(url, autocommit=True) as conexion:
        for archivo in archivos:
            conexion.execute(archivo.read_text(encoding="utf-8"))
        tablas = conexion.execute(
            "select count(*) from information_schema.tables"
            " where table_schema = 'rma' and table_type = 'BASE TABLE'"
        ).fetchone()[0]

    print(f"{len(archivos)} archivos SQL; {tablas} tablas en rma")
    print(f"Base lista: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
