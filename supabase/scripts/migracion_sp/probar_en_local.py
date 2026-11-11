# ruff: noqa: E501  (SQL y mensajes largos: partirlos no los hace más claros)
"""Prueba de punta a punta de migrar_uat.py, solo con la pila local.

Requiere ``supabase start`` (base, Auth y gateway) y Docker. No toca ningún
proyecto remoto ni usa datos reales:

- «Origen» (Oregón simulado): la base ``origen_prueba`` dentro del clúster
  local, con las 20 migraciones, las cargas de referencia y de desarrollo, y
  un esquema ``auth`` mínimo con cuatro cuentas ficticias. Sus hashes bcrypt
  salen de contraseñas aleatorias que solo existen en la memoria de esta
  prueba.
- «Destino» (São Paulo simulado): la base local principal, reiniciada solo
  con migraciones (``db reset --no-seed``), con el Auth real de la pila.

Comprueba: comparación de esquema, carga de maestros (y su repetición sin
cambios), cuentas con el mismo id y hash (y su repetición), inicio de sesión
de las cuatro con su contraseña original, token con ``sub`` igual al id, y
la verificación final.

    app/backend/.venv/Scripts/python supabase/scripts/migracion_sp/probar_en_local.py
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
sys.path.insert(0, str(AQUI))
import migrar_uat as m  # noqa: E402

ORIGEN = "postgresql://postgres:postgres@127.0.0.1:54322/origen_prueba"
CUENTAS = {
    "RECEP-001": "recepcion",
    "TECH-001": "tecnico",
    "COORD-001": "coordinacion",
    "ADMIN-001": "administracion",
}
DOMINIO = "usuarios.rma.invalid"


def cli(*args: str, entrada: str | None = None) -> str:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    r = subprocess.run(
        [npx, "-y", *m.CLI, *args],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=entrada,
        timeout=900,
    )
    if r.returncode != 0:
        raise SystemExit(
            f"Falló supabase {' '.join(args[:2])}: {r.stderr[-800:]}"
        )
    return r.stdout


def psql_origen(sql: str) -> None:
    """Varias sentencias en la base de origen simulada, con psql dentro del contenedor."""
    r = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "supabase_db_rt-rma-mvp",
            "psql",
            "-q",
            "-U",
            "postgres",
            "-d",
            "origen_prueba",
            "-v",
            "ON_ERROR_STOP=1",
            "--single-transaction",
        ],
        input=sql,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    if r.returncode != 0:
        raise SystemExit(f"Falló psql en origen_prueba: {r.stderr[-800:]}")


def paso(texto: str) -> None:
    print(f"\n== {texto}")


def exigir(condicion: bool, texto: str) -> None:
    print(f"  {'OK   ' if condicion else 'FALLA'} {texto}")
    if not condicion:
        raise SystemExit(1)


def iniciar_sesion(api: str, publicable: str, email: str, clave: str):
    pedido = urllib.request.Request(
        api + "/auth/v1/token?grant_type=password",
        data=json.dumps({"email": email, "password": clave}).encode(),
        method="POST",
        headers={"apikey": publicable, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}


def main() -> int:
    estado = json.loads(cli("status", "-o", "json"))
    api, publicable = estado["API_URL"], estado["PUBLISHABLE_KEY"]

    paso("Destino: base local reiniciada solo con migraciones")
    cli("db", "reset", "--no-seed", "--yes")

    paso("Origen simulado: base origen_prueba")
    m.consultar(
        "local", "drop database if exists origen_prueba", escribir=True
    )
    m.consultar("local", "create database origen_prueba", escribir=True)
    cli("db", "push", f"--remote={ORIGEN}", "--yes")
    for semilla in sorted(
        (RAIZ / "supabase" / "seeds" / "referencia_operativa").glob("*.sql")
    ) + sorted((RAIZ / "supabase" / "seeds" / "desarrollo").glob("*.sql")):
        psql_origen(semilla.read_text(encoding="utf-8"))

    claves = {codigo: secrets.token_urlsafe(18) for codigo in CUENTAS}
    ids = {codigo: str(uuid.uuid4()) for codigo in CUENTAS}
    filas = ",\n".join(
        f"('{ids[c]}', '{u}@{DOMINIO}', extensions.crypt('{claves[c]}', extensions.gen_salt('bf', 10)), '{c}')"
        for c, u in CUENTAS.items()
    )
    psql_origen(f"""
      create schema if not exists extensions;
      create extension if not exists pgcrypto with schema extensions;
      create schema if not exists auth;
      create table auth.users (id uuid primary key, email text, encrypted_password text,
                               email_confirmed_at timestamptz default now(), banned_until timestamptz);
      create table auth.identities (user_id uuid, provider text, provider_id text);
      create temp table v (id uuid, email text, hash text, codigo text);
      insert into v values {filas};
      insert into auth.users (id, email, encrypted_password) select id, email, hash from v;
      insert into auth.identities select id, 'email', id::text from v;
      update rma.usuario u set auth_user_id = v.id, email = v.email from v where v.codigo = u.codigo;""")

    paso("comparar (esquema y referencia iguales; maestros todavía no)")
    a, b = m.huella(ORIGEN), m.huella("local")
    for clave in sorted(a):
        if clave.startswith(
            ("esquema.", "permisos.", "migraciones", "referencia.")
        ):
            exigir(a[clave] == b.get(clave), f"{clave} igual")

    paso("maestros --aplicar, dos veces (idempotente)")
    exigir(
        m.cargar_maestros(ORIGEN, "local", aplicar=True),
        "primera carga igual al origen",
    )
    antes = m.huella("local")
    exigir(
        m.cargar_maestros(ORIGEN, "local", aplicar=True),
        "segunda carga igual al origen",
    )
    exigir(m.huella("local") == antes, "la segunda carga no cambió nada")

    paso("cuentas --aplicar, dos veces (idempotente)")
    os.environ["SUPABASE_SECRET_KEY_DESTINO"] = estado["SECRET_KEY"]
    exigir(
        m.migrar_cuentas(ORIGEN, "local", api, aplicar=True),
        "cuentas creadas con el mismo id y hash",
    )
    exigir(
        m.migrar_cuentas(ORIGEN, "local", api, aplicar=True),
        "repetición sin cambios",
    )

    paso("inicio de sesión con la contraseña original")
    for codigo, usuario in CUENTAS.items():
        st, cuerpo = iniciar_sesion(
            api, publicable, f"{usuario}@{DOMINIO}", claves[codigo]
        )
        token = cuerpo.get("access_token", "")
        carga = (
            json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
            if token
            else {}
        )
        exigir(
            st == 200 and carga.get("sub") == ids[codigo],
            f"{usuario}: HTTP {st}, sub igual al id original",
        )
        st, _ = iniciar_sesion(
            api, publicable, f"{usuario}@{DOMINIO}", claves[codigo] + "x"
        )
        exigir(st == 400, f"{usuario}: contraseña incorrecta rechazada")
    claves.clear()

    paso("verificar (destino local)")
    stock = m.uno(
        ORIGEN,
        "select string_agg(i.codigo || '=' || i.stock_fisico, ',') from rma.insumo i where i.stock_fisico > 0",
    )
    exigir(
        m.main(
            [
                "verificar",
                "--destino",
                "local",
                "--stock",
                stock,
                "--sin-rma-api",
            ]
        )
        == 0,
        "verificación final",
    )

    paso("limpieza")
    m.consultar("local", "drop database origen_prueba", escribir=True)
    print("\nPRUEBA LOCAL: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
