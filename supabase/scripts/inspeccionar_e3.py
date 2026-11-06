"""Inspeccion de SOLO LECTURA de Supabase DEV/UAT para la migracion de E3.

Cada consulta corre en su propia transaccion ``READ ONLY``: no puede
escribir. No imprime la cadena de conexion ni datos personales (de los
usuarios, solo codigo, estado y roles; de los clientes, solo cantidades).

Uso (desde app/backend, con el entorno virtual):

    .venv/Scripts/python ../../supabase/scripts/inspeccionar_e3.py \\
        --proyecto-gcp <proyecto> --secreto rma-uat-database-url

o con la cadena en ``RMA_DB_URL`` (nunca en un archivo versionado).
Requiere ``gcloud`` autenticado para leer Secret Manager.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import psycopg

CA_SUPABASE = next(
    (Path(__file__).resolve().parents[2] / "app/backend/app/datos").glob(
        "*.crt"
    )
)

CONSULTAS = {
    "migraciones aplicadas": (
        "select version, name from supabase_migrations.schema_migrations "
        "order by version"
    ),
    "columnas de E3 a E6 ya presentes": """
        select table_name, column_name from information_schema.columns
        where table_schema = 'rma' and (table_name, column_name) in (
          ('insumo','clave'), ('usuario','orden'), ('medio_pago','orden'),
          ('recepcion_version','posicion'), ('pago','operacion_id'),
          ('movimiento_inventario','posicion'), ('accion_usuario','huella'))
        order by 1, 2""",
    "cantidades": """
        select 'insumo', count(*) from rma.insumo
        union all select 'usuario', count(*) from rma.usuario
        union all select 'medio_pago', count(*) from rma.medio_pago
        union all select 'tipo_reparacion', count(*) from rma.tipo_reparacion
        union all select 'tipo_reparacion_insumo', count(*)
          from rma.tipo_reparacion_insumo
        union all select 'mesa_trabajo', count(*) from rma.mesa_trabajo
        union all select 'modelo_equipo', count(*) from rma.modelo_equipo
        union all select 'cliente', count(*) from rma.cliente
        union all select 'equipo', count(*) from rma.equipo
        union all select 'orden', count(*) from rma.orden
        union all select 'movimiento_inventario', count(*)
          from rma.movimiento_inventario
        union all select 'pago', count(*) from rma.pago
        union all select 'foto', count(*) from rma.foto
        union all select 'accion_usuario', count(*) from rma.accion_usuario""",
    "insumos": (
        "select codigo, nombre, activo, stock_fisico, stock_reservado "
        "from rma.insumo order by codigo"
    ),
    "referencias a insumos": """
        select i.codigo,
          (select count(*) from rma.tipo_reparacion_insumo t
            where t.insumo_id = i.id) as previstos,
          (select count(*) from rma.movimiento_inventario m
            where m.insumo_id = i.id) as movimientos,
          (select count(*) from rma.ejecucion_insumo e
            where e.insumo_id = i.id) as utilizados
        from rma.insumo i order by i.codigo""",
    "usuarios (sin nombres)": """
        select u.codigo, u.activo,
          array_agg(r.codigo order by r.codigo) filter (where r.id is not null)
        from rma.usuario u
        left join rma.usuario_rol ur on ur.usuario_id = u.id
        left join rma.rol r on r.id = ur.rol_id
        group by u.codigo, u.activo order by u.codigo""",
    "medios de pago": (
        "select codigo, nombre, activo from rma.medio_pago order by codigo"
    ),
    "rol de la conexion": """
        select current_user, r.rolsuper, r.rolinherit, r.rolbypassrls,
          r.rolcreaterole, r.rolcreatedb,
          array(select b.rolname from pg_auth_members m
                join pg_roles b on b.oid = m.roleid
                where m.member = r.oid order by 1)
        from pg_roles r where r.rolname = current_user""",
    "privilegios efectivos": """
        select
          has_table_privilege('rma.orden', 'UPDATE') as orden_update,
          has_column_privilege('rma.insumo', 'activo', 'UPDATE')
            as insumo_activo_update,
          has_column_privilege('rma.insumo', 'stock_fisico', 'UPDATE')
            as insumo_stock_update,
          has_table_privilege('rma.movimiento_inventario', 'INSERT')
            as libro_insert,
          has_table_privilege('rma.movimiento_inventario', 'DELETE')
            as libro_delete,
          has_table_privilege('rma.orden', 'DELETE') as orden_delete,
          has_table_privilege('rma.pago', 'TRUNCATE') as pago_truncate,
          has_schema_privilege('rma', 'CREATE') as esquema_create,
          has_database_privilege(current_database(), 'TEMP') as temp""",
}


def _url(argumentos) -> str:
    if argumentos.secreto:
        resultado = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "access",
                "latest",
                f"--secret={argumentos.secreto}",
                f"--project={argumentos.proyecto_gcp}",
            ],
            capture_output=True,
            text=True,
            shell=sys.platform == "win32",
        )
        if resultado.returncode != 0:
            primera = (resultado.stderr or "").strip().splitlines()[:1]
            sys.exit(f"No se pudo leer el secreto: {primera}")
        return resultado.stdout.strip()
    url = os.environ.get("RMA_DB_URL")
    if not url:
        sys.exit("Falta --secreto/--proyecto-gcp o RMA_DB_URL.")
    return url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proyecto-gcp")
    parser.add_argument("--secreto")
    # TLS verify-full con la CA de Supabase que viaja con la app.
    with psycopg.connect(
        _url(parser.parse_args()),
        autocommit=True,
        prepare_threshold=None,
        sslrootcert=str(CA_SUPABASE),
    ) as conexion:
        for titulo, sql in CONSULTAS.items():
            print(f"\n## {titulo}")
            try:
                with conexion.transaction():
                    conexion.execute("set transaction read only")
                    for fila in conexion.execute(sql).fetchall():
                        print("  ", *fila)
            except psycopg.Error as error:
                print("   (sin acceso o no existe:", type(error).__name__, ")")


if __name__ == "__main__":
    main()
