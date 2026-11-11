# ruff: noqa: E501  (mensajes y cadenas largas)
"""Guarda en Secret Manager la conexión del respaldo, sin mostrarla.

Pide la contraseña del rol administrador de la base (la del panel de
Supabase) sin eco, arma en memoria la cadena del pooler en modo sesión
(puerto 5432, el que admite pg_dump) con ``sslmode=verify-full`` y la CA
montada en el Job, y la entrega a ``gcloud secrets versions add`` por la
entrada estándar. No escribe la cadena en disco ni la imprime.

El secreto tiene que existir y quedar con acceso solo para la cuenta de
servicio del Job de respaldo (ver docs/RESPALDOS.md). Uso, con autorización:

    python supabase/scripts/respaldo/crear_secreto_respaldo.py \\
        --proyecto-gcp rosariotecno-460217 --secreto rma-uat-respaldo-db-url \\
        --project-ref pcdnmhzwhzymznojndrn \\
        --pooler-host aws-0-sa-east-1.pooler.supabase.com
"""

from __future__ import annotations

import argparse
import getpass
import re
import shutil
import subprocess
import sys
from urllib.parse import quote

CA_EN_EL_JOB = "/respaldos/_herramientas/supabase-ca.crt"


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--proyecto-gcp", required=True)
    p.add_argument("--secreto", required=True)
    p.add_argument("--project-ref", required=True)
    p.add_argument("--pooler-host", required=True)
    a = p.parse_args()
    if not re.fullmatch(r"[a-z0-9]{20}", a.project_ref) or not re.fullmatch(
        r"[a-z0-9.-]+\.pooler\.supabase\.com", a.pooler_host
    ):
        print(
            "project-ref o pooler-host con formato inesperado.",
            file=sys.stderr,
        )
        return 2
    gcloud = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not gcloud:
        print("No se encontró gcloud.", file=sys.stderr)
        return 2

    existe = subprocess.run(
        [
            gcloud,
            "secrets",
            "describe",
            a.secreto,
            f"--project={a.proyecto_gcp}",
            "--format=value(name)",
        ],
        capture_output=True,
        text=True,
    )
    if existe.returncode != 0:
        print(
            f"El secreto {a.secreto} no existe: crearlo antes, con su permiso de acceso.",
            file=sys.stderr,
        )
        return 1

    clave = getpass.getpass(
        "Contraseña del administrador de la base (no se muestra): "
    )
    if not clave:
        print("Sin contraseña: no se guarda nada.", file=sys.stderr)
        return 1
    cadena = (
        f"postgresql://postgres.{a.project_ref}:{quote(clave, safe='')}@{a.pooler_host}:5432/postgres"
        f"?sslmode=verify-full&sslrootcert={CA_EN_EL_JOB}"
    )
    del clave
    resultado = subprocess.run(
        [
            gcloud,
            "secrets",
            "versions",
            "add",
            a.secreto,
            "--data-file=-",
            f"--project={a.proyecto_gcp}",
            "--format=value(name)",
        ],
        input=cadena,
        capture_output=True,
        text=True,
    )
    del cadena
    if resultado.returncode != 0:
        print("No se pudo guardar la versión del secreto.", file=sys.stderr)
        return 1
    print(
        f"Secreto {a.secreto}: versión {resultado.stdout.strip().split('/')[-1]} guardada."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
