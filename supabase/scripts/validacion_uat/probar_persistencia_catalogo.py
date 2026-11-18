# ruff: noqa: E501  (mensajes largos)
"""Bloque C, C8: la copia del catalogo de Ventas sobrevive al escalado a cero.

Dos fases, con la espera entre medio (``docs/DESPLIEGUE_UAT.md``, seccion 10):

    sincronizar  inicia sesion como Administracion, sincroniza el catalogo y
                 guarda en ``--estado`` lo que quedo (ultima exitosa,
                 vigentes, elegibles). Sin tokens ni contrasenas.
    comprobar    despues de que Cloud Run llego a 0 instancias: vuelve a
                 leer el estado (el pedido provoca el arranque en frio) y lo
                 compara con el guardado.

    $env:SUPABASE_PUBLISHABLE_KEY = "<clave publicable de São Paulo>"
    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/probar_persistencia_catalogo.py --fase sincronizar --estado $env:TEMP\\catalogo-c8.json
    (esperar 0 instancias: verificar_escalado_uat.py y Cloud Monitoring)
    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/probar_persistencia_catalogo.py --fase comprobar --estado $env:TEMP\\catalogo-c8.json

La contrasena de Administracion se pide sin eco y no se guarda. Contra una API
local en modo demo: ``--api http://127.0.0.1:8000 --sin-autenticacion``.
Lee el catalogo de Ventas (la hoja que el UAT ya lee) y actualiza su copia:
crea un intento de sincronizacion y las filas de la copia, como el boton de
sincronizar. No crea Ordenes ni otros datos.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

import httpx

API_UAT = "https://rt-rma-uat-api-nszqooxxla-rj.a.run.app"
SUPABASE_UAT = "https://pcdnmhzwhzymznojndrn.supabase.co"
CUENTA = "administracion@usuarios.rma.invalid"
ADMINISTRADOR = "ADMIN-001"


def token_administracion(supabase: str, api: str) -> str | None:
    publicable = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    if not publicable.startswith("sb_publishable_"):
        print(
            "Falta SUPABASE_PUBLISHABLE_KEY (la clave publicable de São Paulo)."
        )
        return None
    contrasena = getpass.getpass(
        "Contraseña de 'administracion' (no se muestra): "
    )
    r = httpx.post(
        f"{supabase}/auth/v1/token?grant_type=password",
        json={"email": CUENTA, "password": contrasena},
        headers={"apikey": publicable},
        timeout=60,
    )
    contrasena = ""
    token = r.json().get("access_token") if r.status_code == 200 else None
    if not token:
        print(f"No se pudo iniciar sesión (Auth HTTP {r.status_code}).")
        return None
    yo = httpx.get(
        f"{api}/api/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=90,
    )
    if yo.status_code != 200 or ADMINISTRADOR not in yo.text:
        print(f"/api/me no es {ADMINISTRADOR} (HTTP {yo.status_code}).")
        return None
    return token


def resumen(estado: dict) -> dict:
    ultima = estado.get("ultima_exitosa") or {}
    return {
        "ultima_exitosa": ultima.get("id"),
        "finalizada_en": ultima.get("finalizada_en"),
        "vigentes": estado.get("vigentes"),
        "elegibles": estado.get("elegibles"),
    }


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--fase", choices=("sincronizar", "comprobar"), required=True
    )
    p.add_argument(
        "--estado",
        required=True,
        help="archivo JSON con el estado guardado (sin secretos)",
    )
    p.add_argument("--api", default=API_UAT)
    p.add_argument("--supabase-url", default=SUPABASE_UAT)
    p.add_argument(
        "--sin-autenticacion",
        action="store_true",
        help="API local en modo demo",
    )
    a = p.parse_args()
    api = a.api.rstrip("/")
    local = api.startswith(("http://127.0.0.1", "http://localhost"))
    if a.sin_autenticacion != local or (
        not local
        and (api != API_UAT or a.supabase_url.rstrip("/") != SUPABASE_UAT)
    ):
        print(
            "Destino no permitido: la API pública del UAT, o una API local con --sin-autenticacion."
        )
        return 2

    encabezados = {}
    if not a.sin_autenticacion:
        token = token_administracion(a.supabase_url.rstrip("/"), api)
        if token is None:
            return 1
        encabezados["Authorization"] = f"Bearer {token}"
    cliente = httpx.Client(base_url=api, headers=encabezados, timeout=120)
    archivo = Path(a.estado)
    try:
        if a.fase == "sincronizar":
            r = cliente.post(
                "/api/catalogs/equipment/sync",
                params={"usuario_id": ADMINISTRADOR},
            )
            if r.status_code != 200 or r.json().get("resultado") != "EXITOSA":
                print(
                    f"FALLA: la sincronización no fue EXITOSA (HTTP {r.status_code}): {r.text[:300]}"
                )
                return 1
            print(
                f"OK    sincronización {r.json()['id']}: {r.json()['vigentes']} vigentes, {r.json()['elegibles']} elegibles"
            )
            estado = cliente.get("/api/catalogs/equipment")
            estado.raise_for_status()
            guardado = resumen(estado.json()["estado"])
            archivo.write_text(
                json.dumps(guardado, indent=2), encoding="utf-8"
            )
            print(f"OK    estado guardado en {archivo}: {guardado}")
            print(
                "\nAhora: esperar a que Cloud Run llegue a 0 instancias y correr --fase comprobar."
            )
            return 0
        guardado = json.loads(archivo.read_text(encoding="utf-8"))
        r = cliente.get("/api/catalogs/equipment")
        if r.status_code != 200:
            print(
                f"FALLA: GET del catálogo HTTP {r.status_code}: {r.text[:300]}"
            )
            return 1
        ahora = resumen(r.json()["estado"])
        iguales = ahora == guardado and guardado["ultima_exitosa"] is not None
        print(
            f"{'OK   ' if iguales else 'FALLA'} después del escalado a cero: {ahora}"
        )
        if not iguales:
            print(f"      guardado antes: {guardado}")
        print(f"\nRESULTADO: {'OK' if iguales else 'FALLA'}")
        return 0 if iguales else 1
    finally:
        cliente.headers.pop("Authorization", None)
        cliente.close()


if __name__ == "__main__":
    sys.exit(main())
