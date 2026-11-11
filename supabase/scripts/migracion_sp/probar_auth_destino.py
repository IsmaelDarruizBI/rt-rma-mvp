# ruff: noqa: E501  (mensajes largos)
"""Prueba de compatibilidad del Auth del proyecto nuevo (etapa 3 del plan).

Comprueba, con UNA cuenta ficticia que siempre se borra, que el proyecto
acepta el mecanismo de la migración: crear una cuenta con un ``id`` elegido y
un ``password_hash`` bcrypt, e iniciar sesión con la contraseña original.

1. Las claves de firma publicadas (JWKS) incluyen ES256.
2. Crea la cuenta A con una contraseña aleatoria (solo en memoria).
3. Lee el hash de A desde la base (CLI, solo lectura, en memoria) y borra A.
4. Crea la cuenta B con OTRO id, el mismo email y ``password_hash`` = ese hash.
5. Inicia sesión con la contraseña original: token ES256, ``sub`` = id de B.
6. Rechaza una contraseña incorrecta; B tiene su identidad ``email``.
7. Borra B y confirma que ninguna de las dos existe.

No usa cuentas ni datos reales, no imprime contraseñas, hashes ni claves.

    SUPABASE_PUBLISHABLE_KEY_DESTINO=<clave publicable del proyecto nuevo> \\
    app/backend/.venv/Scripts/python supabase/scripts/migracion_sp/probar_auth_destino.py --ref <ref nuevo>

La clave secreta del proyecto nuevo se pide sin eco (o se lee de
SUPABASE_SECRET_KEY_DESTINO). ``--local`` usa la pila de ``supabase start``.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import secrets
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import migrar_uat as m  # noqa: E402

DOMINIO = "usuarios.rma.invalid"


def parte(token: str, indice: int) -> dict:
    texto = token.split(".")[indice]
    return json.loads(
        base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))
    )


def iniciar_sesion(
    admin: m.AdminAuth, publicable: str, email: str, clave: str
):
    publico = m.AdminAuth(admin.base[: -len("/auth/v1")], publicable)
    return publico.pedir(
        "POST",
        "/token?grant_type=password",
        {"email": email, "password": clave},
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    destino = p.add_mutually_exclusive_group(required=True)
    destino.add_argument("--ref", help="project ref del proyecto nuevo")
    destino.add_argument("--local", action="store_true")
    a = p.parse_args()

    if a.local:
        npx = shutil.which("npx") or shutil.which("npx.cmd")
        salida = subprocess.run(
            [npx, "-y", *m.CLI, "status", "-o", "json"],
            cwd=m.RAIZ,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
        estado = json.loads(salida[salida.find("{") :])
        base, base_db = estado["API_URL"], "local"
        secreta, publicable = estado["SECRET_KEY"], estado["PUBLISHABLE_KEY"]
    else:
        base, base_db = f"https://{a.ref}.supabase.co", a.ref
        publicable = os.environ.get("SUPABASE_PUBLISHABLE_KEY_DESTINO", "")
        if not publicable.startswith("sb_publishable_"):
            print(
                "Falta SUPABASE_PUBLISHABLE_KEY_DESTINO (clave publicable del proyecto nuevo)."
            )
            return 2
        secreta = os.environ.get(
            "SUPABASE_SECRET_KEY_DESTINO"
        ) or getpass.getpass(
            "Clave secreta del proyecto nuevo (no se muestra): "
        )

    admin = m.AdminAuth(base, secreta)
    email = f"prueba-hash-{secrets.token_hex(4)}@{DOMINIO}"
    clave = secrets.token_urlsafe(24)
    id_b = str(uuid.uuid4())
    creadas: list[str] = []
    resultados: list[tuple[str, bool]] = []

    def anotar(texto: str, ok: bool) -> bool:
        resultados.append((texto, ok))
        print(f"  {'OK   ' if ok else 'FALLA'} {texto}")
        return ok

    try:
        estado, jwks = m.AdminAuth(base, publicable).pedir(
            "GET", "/.well-known/jwks.json"
        )
        algoritmos = sorted(
            {k.get("alg") for k in jwks.get("keys", [])} - {None}
        )
        anotar(
            f"JWKS publica ES256 (algoritmos: {', '.join(algoritmos) or 'ninguno'})",
            estado == 200 and "ES256" in algoritmos,
        )

        estado, cuenta = admin.pedir(
            "POST",
            "/admin/users",
            {"email": email, "password": clave, "email_confirm": True},
        )
        id_a = cuenta.get("id")
        if not anotar(
            "cuenta A creada con contraseña",
            estado in (200, 201) and bool(id_a),
        ):
            return 1
        creadas.append(id_a)

        hash_a = m.uno(
            base_db,
            f"select encrypted_password from auth.users where id = '{id_a}'",
        )
        anotar(
            "hash de A con formato bcrypt (leído en memoria)",
            bool(m.BCRYPT.match(hash_a or "")),
        )
        estado, _ = admin.pedir("DELETE", f"/admin/users/{id_a}")
        anotar("cuenta A borrada", estado in (200, 204))
        creadas.remove(id_a)

        estado, cuenta = admin.pedir(
            "POST",
            "/admin/users",
            {
                "id": id_b,
                "email": email,
                "password_hash": hash_a,
                "email_confirm": True,
            },
        )
        hash_a = None
        if not anotar(
            "cuenta B creada con otro id y password_hash",
            estado in (200, 201) and cuenta.get("id") == id_b,
        ):
            print(f"        HTTP {estado} {cuenta}")
            return 1
        creadas.append(id_b)

        estado, sesion = iniciar_sesion(admin, publicable, email, clave)
        token = sesion.get("access_token", "")
        encabezado, carga = (
            (parte(token, 0), parte(token, 1)) if token else ({}, {})
        )
        anotar(
            "inicio de sesión de B con la contraseña original",
            estado == 200 and bool(token),
        )
        anotar(
            f"token: alg {encabezado.get('alg')}, sub = id de B, email",
            carga.get("sub") == id_b
            and carga.get("email") == email
            and (encabezado.get("alg") == "ES256" or a.local),
        )
        estado, _ = iniciar_sesion(admin, publicable, email, clave + "x")
        anotar("contraseña incorrecta rechazada", estado == 400)
        identidad = m.uno(
            base_db,
            f"select count(*) from auth.identities where user_id = '{id_b}' and provider = 'email' and provider_id = '{id_b}'",
        )
        anotar("identidad email de B", identidad == 1)
    finally:
        clave = None
        for cuenta_id in list(creadas):
            estado, _ = admin.pedir("DELETE", f"/admin/users/{cuenta_id}")
            if estado in (200, 204):
                creadas.remove(cuenta_id)
        restantes = m.uno(
            base_db, f"select count(*) from auth.users where email = '{email}'"
        )
        anotar(
            "cuenta de prueba eliminada (no queda ninguna)",
            restantes == 0 and not creadas,
        )

    ok = all(r for _, r in resultados)
    print(
        "RESULTADO:",
        "COMPATIBLE"
        if ok
        else "NO COMPATIBLE: usar contraseñas nuevas y revinculación",
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
