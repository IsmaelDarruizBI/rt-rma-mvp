# ruff: noqa: E501  (mensajes largos)
"""Tiempos de lectura de la API del UAT, para comparar Oregón y São Paulo.

Solo hace GET: no crea Órdenes ni cambia datos. Inicia sesión una vez con
Supabase Auth (contraseña pedida sin eco) y repite cada lectura con pausas,
descartando la primera (arranque y pool). Informa mediana y p90 del tiempo
total visto por el cliente y del encabezado ``Server-Timing`` si existe.

    SUPABASE_PUBLISHABLE_KEY=<clave publicable> \\
    app/backend/.venv/Scripts/python supabase/scripts/migracion_sp/medir_api.py \\
        --backend https://<etiqueta>---rt-rma-uat-api-....run.app \\
        --supabase-url https://<ref>.supabase.co [--usuario administracion] [--repeticiones 10]

Las mismas lecturas, con el mismo usuario, en las dos revisiones (una por
proyecto), una detrás de la otra. El viaje a la base se estima con la
diferencia entre una lectura de 3 viajes y una de 6 (ver el plan, sección 8).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

DOMINIO = "usuarios.rma.invalid"
CODIGOS = {
    "administracion": "ADMIN-001",
    "coordinacion": "COORD-001",
    "recepcion": "RECEP-001",
    "tecnico": "TECH-001",
}


def pedir(
    url: str,
    token: str | None = None,
    cuerpo: dict | None = None,
    apikey: str | None = None,
):
    encabezados = {"Content-Type": "application/json"}
    if token:
        encabezados["Authorization"] = f"Bearer {token}"
    if apikey:
        encabezados["apikey"] = apikey
    pedido = urllib.request.Request(
        url,
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        method="POST" if cuerpo is not None else "GET",
        headers=encabezados,
    )
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(pedido, timeout=60) as r:
            datos = r.read()
            return r.status, time.perf_counter() - inicio, datos
    except urllib.error.HTTPError as e:
        return e.code, time.perf_counter() - inicio, b""


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--backend", required=True)
    p.add_argument("--supabase-url", required=True)
    p.add_argument(
        "--usuario", default="administracion", choices=sorted(CODIGOS)
    )
    p.add_argument("--repeticiones", type=int, default=10)
    p.add_argument("--pausa", type=float, default=3.0)
    a = p.parse_args()
    publicable = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    if not publicable.startswith("sb_publishable_"):
        print(
            "Falta SUPABASE_PUBLISHABLE_KEY (la clave publicable del proyecto)."
        )
        return 2
    backend = a.backend.rstrip("/")
    codigo = CODIGOS[a.usuario]

    clave = getpass.getpass(f"Contraseña de '{a.usuario}' (no se muestra): ")
    estado, _, datos = pedir(
        a.supabase_url.rstrip("/") + "/auth/v1/token?grant_type=password",
        cuerpo={"email": f"{a.usuario}@{DOMINIO}", "password": clave},
        apikey=publicable,
    )
    del clave
    token = (
        json.loads(datos or b"{}").get("access_token")
        if estado == 200
        else None
    )
    if not token:
        print(f"No se pudo iniciar sesión (HTTP {estado}).")
        return 1

    _, _, inventario = pedir(backend + "/api/inventory", token)
    try:
        lista = json.loads(inventario or b"[]")
        primer_insumo = (
            lista[0] if isinstance(lista, list) and lista else {}
        ).get("id")
    except ValueError:
        primer_insumo = None

    lecturas = [
        ("sesión /api/me", "/api/me"),
        ("usuarios", "/api/catalogs/users"),
        ("tipos de reparación", "/api/catalogs/repair-types"),
        ("estaciones", "/api/catalogs/stations"),
        ("listar Órdenes", "/api/orders"),
        ("Inicio", f"/api/work/inbox?usuario_id={codigo}"),
        ("Taller", f"/api/work/workshop?usuario_id={codigo}"),
        ("Inventario", "/api/inventory"),
    ]
    if primer_insumo:
        lecturas.append(
            ("detalle de insumo", f"/api/inventory/{primer_insumo}")
        )

    print(
        f"Backend {backend}, usuario {a.usuario}, {a.repeticiones} repeticiones (más una descartada), pausa {a.pausa} s\n"
    )
    print(f"{'lectura':<22}{'HTTP':>6}{'mediana':>10}{'p90':>10}{'mín':>10}")
    for nombre, ruta in lecturas:
        tiempos, estados = [], set()
        for i in range(a.repeticiones + 1):
            estado, segundos, _ = pedir(backend + ruta, token)
            estados.add(estado)
            if i:
                tiempos.append(segundos)
            time.sleep(a.pausa)
        tiempos.sort()
        p90 = tiempos[max(0, round(0.9 * len(tiempos)) - 1)]
        print(
            f"{nombre:<22}{'/'.join(map(str, sorted(estados))):>6}{statistics.median(tiempos):>9.3f}s{p90:>9.3f}s{tiempos[0]:>9.3f}s"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
