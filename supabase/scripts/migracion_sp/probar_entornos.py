# ruff: noqa: E501  (mensajes largos)
"""Aislamiento entre Oregón y São Paulo, y lecturas autenticadas (etapa 7).

Solo hace GET y no crea ni modifica datos. Con UNA contraseña (la misma
cuenta existe en los dos proyectos, con la misma contraseña), inicia sesión
en Supabase Auth de Oregón y de São Paulo y comprueba:

- el token de São Paulo entra en la revisión de São Paulo y NO en la de Oregón;
- el token de Oregón entra en la revisión de Oregón y NO en la de São Paulo;
- en São Paulo, por la API: ``/api/me`` es el usuario esperado, catálogos,
  Inicio y Taller responden, cero Órdenes y el stock esperado.

Imprime solo OK/FALLA, códigos HTTP y conteos: nunca tokens ni contraseñas.

    $env:SUPABASE_PUBLISHABLE_KEY_ORIGEN  = "<clave publicable de Oregón>"
    $env:SUPABASE_PUBLISHABLE_KEY_DESTINO = "<clave publicable de São Paulo>"
    app/backend/.venv/Scripts/python supabase/scripts/migracion_sp/probar_entornos.py
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

ENTORNOS = {
    "Oregón": {
        "supabase": "https://okcscsglnujnxtgobjfw.supabase.co",
        "api": "https://auth---rt-rma-uat-api-nszqooxxla-rj.a.run.app",
        "clave": "SUPABASE_PUBLISHABLE_KEY_ORIGEN",
    },
    "São Paulo": {
        "supabase": "https://pcdnmhzwhzymznojndrn.supabase.co",
        "api": "https://saopaulo---rt-rma-uat-api-nszqooxxla-rj.a.run.app",
        "clave": "SUPABASE_PUBLISHABLE_KEY_DESTINO",
    },
}
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
    try:
        with urllib.request.urlopen(pedido, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, None


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--usuario", default="administracion", choices=sorted(CODIGOS)
    )
    p.add_argument(
        "--stock",
        default="BAT-IP14=10",
        help="código=disponible esperado en São Paulo",
    )
    a = p.parse_args()
    claves = {n: os.environ.get(e["clave"], "") for n, e in ENTORNOS.items()}
    if not all(c.startswith("sb_publishable_") for c in claves.values()):
        print(
            "Faltan SUPABASE_PUBLISHABLE_KEY_ORIGEN y/o SUPABASE_PUBLISHABLE_KEY_DESTINO."
        )
        return 2

    clave = getpass.getpass(f"Contraseña de '{a.usuario}' (no se muestra): ")
    tokens = {}
    for nombre, e in ENTORNOS.items():
        estado, datos = pedir(
            e["supabase"] + "/auth/v1/token?grant_type=password",
            cuerpo={"email": f"{a.usuario}@{DOMINIO}", "password": clave},
            apikey=claves[nombre],
        )
        tokens[nombre] = (
            (datos or {}).get("access_token") if estado == 200 else None
        )
    del clave

    resultados = []

    def anotar(texto: str, ok: bool) -> None:
        resultados.append(ok)
        print(f"  {'OK   ' if ok else 'FALLA'} {texto}")

    for nombre in ENTORNOS:
        anotar(f"inicio de sesión en Supabase {nombre}", bool(tokens[nombre]))
    if not all(tokens.values()):
        return 1

    print("\nAislamiento de tokens (/api/me):")
    for emisor in ENTORNOS:
        for revision, e in ENTORNOS.items():
            estado, cuerpo = pedir(e["api"] + "/api/me", tokens[emisor])
            esperado = 200 if emisor == revision else 401
            anotar(
                f"token de {emisor} en la revisión de {revision}: HTTP {estado} (esperado {esperado})",
                estado == esperado,
            )
            if estado == 200:
                anotar(
                    f"  /api/me en {revision} es {CODIGOS[a.usuario]}",
                    CODIGOS[a.usuario] in json.dumps(cuerpo),
                )

    print("\nLecturas autenticadas en São Paulo:")
    api, token = ENTORNOS["São Paulo"]["api"], tokens["São Paulo"]
    codigo = CODIGOS[a.usuario]
    for nombre, ruta in [
        ("usuarios", "/api/catalogs/users"),
        ("tipos de reparación", "/api/catalogs/repair-types"),
        ("estaciones", "/api/catalogs/stations"),
        ("medios de pago", "/api/catalogs/payment-methods"),
        ("Inicio", f"/api/work/inbox?usuario_id={codigo}"),
        ("Taller", f"/api/work/workshop?usuario_id={codigo}"),
    ]:
        estado, cuerpo = pedir(api + ruta, token)
        cantidad = len(cuerpo) if isinstance(cuerpo, list) else "-"
        anotar(f"{nombre}: HTTP {estado}, elementos {cantidad}", estado == 200)
    estado, ordenes = pedir(api + "/api/orders", token)
    anotar(
        f"Órdenes: HTTP {estado}, cantidad {len(ordenes) if isinstance(ordenes, list) else '-'} (esperado 0)",
        estado == 200 and ordenes == [],
    )
    estado, inventario = pedir(api + "/api/inventory", token)
    esperado = dict(x.split("=") for x in a.stock.split(","))
    actual = (
        {i["codigo"]: str(i["disponible"]) for i in inventario or []}
        if estado == 200
        else {}
    )
    anotar(
        f"Inventario: HTTP {estado}, {actual} (esperado disponible {esperado})",
        estado == 200
        and all(
            float(actual.get(k, "nan")) == float(v)
            for k, v in esperado.items()
        ),
    )
    tokens.clear()

    ok = all(resultados)
    print("\nRESULTADO:", "OK" if ok else "CON FALLAS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
