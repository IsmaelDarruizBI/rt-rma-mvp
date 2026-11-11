# ruff: noqa: E501  (mensajes y cadenas largas)
"""Crea el rol de solo lectura del respaldo y guarda su conexión, sin mostrarla.

El Job de respaldo NO usa la credencial de administración de la base. Usa
``rma_respaldo``:

- ``LOGIN`` y ``BYPASSRLS``: ``auth.users`` y ``auth.identities`` tienen RLS
  y ``pg_dump`` no respalda tablas filtradas.
- Miembro de ``pg_read_all_data`` con ``INHERIT TRUE, SET FALSE``: lectura de
  tablas y secuencias, y ``USAGE`` sobre los esquemas (``auth`` incluido),
  sin escritura ni DDL. No puede hacer ``SET ROLE`` a ese rol.
- ``default_transaction_read_only = on``, límite de 2 conexiones y
  ``statement_timeout`` de 5 minutos.

La contraseña es aleatoria (32 bytes, base64url) y vive solo en memoria:

1. Secret Manager recibe la cadena completa del pooler en **modo sesión**
   (puerto 5432, el que admite ``pg_dump``), con ``sslmode=verify-full`` y la CA
   montada en el Job, por la entrada estándar de ``gcloud``.
2. El SQL del rol lleva solo el verificador SCRAM-SHA-256 y llega a
   ``supabase db query --remote=<ref>`` por la entrada estándar: la contraseña
   en texto plano nunca viaja a la base ni se escribe en disco.

``crear`` exige que el secreto exista y no tenga versiones activas (nunca
sobrescribe una credencial) y que el rol no exista. ``rotar`` exige un rol
existente y al menos una versión activa; la anterior se deshabilita a mano
después de verificar la nueva. Uso, con autorización y la CLI de Supabase con
sesión:

    python supabase/scripts/respaldo/crear_secreto_respaldo.py crear \\
        --proyecto-gcp rosariotecno-460217 --secreto rma-uat-respaldo-db-url \\
        --project-ref pcdnmhzwhzymznojndrn \\
        --pooler-host aws-0-sa-east-1.pooler.supabase.com
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
CA_EN_EL_JOB = "/respaldos/_herramientas/supabase-ca.crt"
CLI = ["supabase@3.1.0"]


def verificador_scram(clave: str, iteraciones: int = 4096) -> str:
    sal = secrets.token_bytes(16)
    salada = hashlib.pbkdf2_hmac(
        "sha256", clave.encode(), sal, iteraciones, 32
    )
    cliente = hmac.new(salada, b"Client Key", "sha256").digest()
    almacenada = hashlib.sha256(cliente).digest()
    servidor = hmac.new(salada, b"Server Key", "sha256").digest()
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"SCRAM-SHA-256${iteraciones}:{b64(sal)}${b64(almacenada)}:{b64(servidor)}"


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("modo", choices=["crear", "rotar"])
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
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not gcloud or not npx:
        print("Faltan gcloud o npx.", file=sys.stderr)
        return 2

    def correr(orden: list[str], entrada: str | None = None):
        return subprocess.run(
            orden,
            cwd=RAIZ,
            input=entrada,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    proyecto = f"--project={a.proyecto_gcp}"
    if correr([gcloud, "secrets", "describe", a.secreto, proyecto]).returncode:
        print(
            f"El secreto {a.secreto} no existe: crearlo antes, con su permiso de acceso.",
            file=sys.stderr,
        )
        return 1
    versiones = correr(
        [
            gcloud,
            "secrets",
            "versions",
            "list",
            a.secreto,
            proyecto,
            "--filter=state=ENABLED",
            "--format=value(name)",
        ]
    )
    activas = len(versiones.stdout.split())
    if a.modo == "crear" and activas:
        print(
            f"El secreto ya tiene {activas} versión(es) activa(s): «crear» no sobrescribe credenciales.",
            file=sys.stderr,
        )
        return 1
    if a.modo == "rotar" and not activas:
        print(
            "El secreto no tiene versiones activas: usá «crear».",
            file=sys.stderr,
        )
        return 1

    clave = secrets.token_urlsafe(32)
    verificador = verificador_scram(clave)
    cadena = (
        f"postgresql://rma_respaldo.{a.project_ref}:{clave}@{a.pooler_host}:5432/postgres"
        f"?sslmode=verify-full&sslrootcert={CA_EN_EL_JOB}"
    )

    def ocultar(texto: str) -> str:
        for valor in (clave, verificador, cadena):
            texto = texto.replace(valor, "<oculto>")
        texto = re.sub(r"SCRAM-SHA-256\$\S+", "<oculto>", texto)
        return re.sub(r"postgres(ql)?://\S+", "<oculto>", texto)

    agregado = correr(
        [
            gcloud,
            "secrets",
            "versions",
            "add",
            a.secreto,
            "--data-file=-",
            proyecto,
            "--format=value(name)",
        ],
        cadena,
    )
    if agregado.returncode:
        print(
            "No se pudo guardar la versión del secreto: "
            + ocultar(agregado.stderr).splitlines()[0],
            file=sys.stderr,
        )
        print(
            "No se aplicó el SQL: el rol no se crea sin su credencial guardada.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Secreto {a.secreto}: versión {agregado.stdout.strip().split('/')[-1]} guardada."
    )

    if a.modo == "crear":
        sql = "\n".join(
            [
                f"create role rma_respaldo login bypassrls connection limit 2 password '{verificador}';",
                "grant pg_read_all_data to rma_respaldo with inherit true, set false;",
                "alter role rma_respaldo set default_transaction_read_only = on;",
                "alter role rma_respaldo set statement_timeout = '300s';",
                "comment on role rma_respaldo is 'Respaldo diario del UAT (Cloud Run Job rt-rma-respaldo-db): solo lectura, pg_read_all_data y BYPASSRLS para auth.';",
            ]
        )
    else:
        sql = f"alter role rma_respaldo password '{verificador}';"
    aplicado = correr(
        [npx, "-y", *CLI, "db", "query", f"--remote={a.project_ref}", "--yes"],
        sql,
    )
    salida = ocultar(f"{aplicado.stdout}\n{aplicado.stderr}")
    if aplicado.returncode or re.search(r'"_tag"\s*:\s*"Error"', salida):
        print(
            "El SQL del rol falló: la versión del secreto quedó guardada sin un rol que la use.",
            file=sys.stderr,
        )
        print(
            "\n".join(
                linea
                for linea in salida.splitlines()
                if re.search("error|message", linea, re.I)
            )[:600],
            file=sys.stderr,
        )
        return 1
    print(
        f"rma_respaldo: {'creado' if a.modo == 'crear' else 'contraseña rotada'} en {a.project_ref}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
