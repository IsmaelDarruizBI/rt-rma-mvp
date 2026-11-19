# ruff: noqa: E501  (mensajes largos)
"""Ensayo LOCAL de compatibilidad de Configuracion v2 (fase E).

Solo contra un PostgreSQL local y descartable (nunca Supabase). Procesos
reales de uvicorn sobre una base con TODAS las migraciones (Reparacion RT y
Configuracion v2):

1. El backend publicado (``--anterior``, exportado con ``git archive``)
   arranca sobre la base migrada y sigue dando altas como antes: con
   codigos tipeados, con su ``max()+1`` de proveedores, y un duplicado que
   solo difiere en mayusculas es un conflicto, no un 500.
2. La version nueva lee lo que creo el publicado y genera sus codigos sin
   chocar con ellos; acepta el cuerpo de un cliente anterior (codigo y
   plazo generico informados); informa el alias ``COMPRAS_GESTIONAR``; el
   alta sin plazo generico toma el de con check-in; solo dos plantillas
   visibles y ninguna borrada.
3. Vuelta atras: el publicado otra vez sobre la base, despues de las altas
   de la version nueva, lista todo y sigue dando altas; la version nueva
   vuelve y saltea los codigos que el publicado uso mientras tanto.

    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/ensayar_configuracion_v2.py --anterior fd434ef

Sin credenciales: el servidor local confia en las conexiones locales.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import ensayar_persistencia_catalogo as comun  # noqa: E402

BACKEND = comun.BACKEND
BASE = "rma_ensayo_configuracion_v2"
ADMIN = "ADMIN-001"
RECEPCION = "RECEP-001"

resultados: list[dict] = []


def anotar(paso: str, nombre: str, ok: bool, detalle: str = "") -> bool:
    resultados.append({"paso": paso, "comprobacion": nombre, "ok": bool(ok), "detalle": detalle})
    print(f"  {'OK   ' if ok else 'FALLA'} [{paso}] {nombre}" + ("" if ok else f" — {detalle[:300]}"), flush=True)
    return bool(ok)


def tipo(**campos) -> dict:
    return {"usuario_id": ADMIN, "nombre": "Ensayo", "precio": "1000", "puntaje": 1, **campos}


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--admin-url", default="postgresql://postgres@127.0.0.1:55432/postgres")
    p.add_argument("--anterior", required=True, help="commit del backend publicado")
    p.add_argument("--puerto", type=int, default=8894)
    p.add_argument("--informe")
    a = p.parse_args()

    import httpx

    from tests.fixtures.catalogo_ventas import (
        escribir_csv as escribir_catalogo,
    )

    carpeta = Path(tempfile.mkdtemp(prefix="rma-ensayo-cfg-"))
    registro = carpeta / "registro.txt"
    catalogo = escribir_catalogo(carpeta / "catalogo.csv")
    cwd = carpeta / "cwd"  # sin .env
    cwd.mkdir()
    comun.BASE = BASE
    url_admin = a.admin_url
    try:
        url = comun.preparar_base(url_admin)
        url_api = comun.url_base(url_admin, BASE, comun.ROL_API)
        anterior = comun.exportar(a.anterior, carpeta / "anterior")

        def http(base: str, metodo: str, ruta: str, **kw):
            return httpx.request(metodo, f"{base}{ruta}", timeout=60, **kw)

        # --- 1. El publicado sobre la base migrada --------------------------
        print(f"1. Backend publicado ({a.anterior}) sobre la base migrada", flush=True)
        with comun.servidor(anterior, comun.entorno(url_api, carpeta / "datos-1", catalogo), a.puerto, registro, cwd) as (b, _):
            anotar("1", "arranca y lista Ordenes", http(b, "GET", "/api/orders").status_code == 200)
            r = http(b, "POST", "/api/admin/repair-types", json=tipo(codigo="TR-ANT1", garantia_dias=60))
            anotar("1", "da de alta un tipo con codigo tipeado", r.status_code == 200, r.text)
            r = http(b, "POST", "/api/admin/repair-types", json=tipo(codigo="tr-ant1", garantia_dias=60))
            anotar("1", "un duplicado en minusculas es un conflicto, no un 500", 400 <= r.status_code < 500, f"{r.status_code} {r.text[:200]}")
            r = http(b, "POST", "/api/admin/supplies", json={"usuario_id": ADMIN, "clave": "INS-ANT1", "codigo": "SKU-ANT1", "nombre": "Insumo anterior"})
            anotar("1", "da de alta un insumo con clave y codigo tipeados", r.status_code == 200, r.text)
            r = http(b, "POST", "/api/admin/reasons", json={"usuario_id": ADMIN, "tipo": "CANCELACION", "nombre": "Anterior", "codigo": "CANC-ANT"})
            anotar("1", "da de alta un motivo con codigo tipeado", r.status_code == 200, r.text)
            r = http(b, "POST", "/api/admin/suppliers", json={"usuario_id": ADMIN, "nombre": "Proveedor anterior"})
            anotar("1", "da de alta un proveedor (max+1)", r.status_code == 200 and r.json()["id"] == "PRV-0001", r.text)
            r = http(b, "GET", "/api/admin/permissions")
            anotar("1", "su catalogo de permisos sigue teniendo COMPRAS_GESTIONAR", r.status_code == 200 and any(x["codigo"] == "COMPRAS_GESTIONAR" for x in r.json()), r.text[:200])

        # --- 2. La version nueva ---------------------------------------------
        print("2. Version nueva sobre lo que creo el publicado", flush=True)
        with comun.servidor(BACKEND, comun.entorno(url_api, carpeta / "datos-2", catalogo), a.puerto, registro, cwd) as (b, _):
            tipos = {t["id"] for t in http(b, "GET", "/api/admin/catalog").json()["tipos"]}
            anotar("2", "lee el tipo del publicado", "TR-ANT1" in tipos, json.dumps(sorted(tipos)))
            r = http(b, "POST", "/api/admin/repair-types", json=tipo(garantia_con_checkin=120))
            nuevo = r.json() if r.status_code == 200 else {}
            anotar("2", "genera el codigo del tipo (TR-NNN) sin chocar", r.status_code == 200 and nuevo["id"].startswith("TR-") and nuevo["id"] not in tipos, r.text)
            anotar("2", "el plazo generico de un alta toma el de con check-in (DF-1)", nuevo.get("garantia_dias") == 120, json.dumps(nuevo))
            r = http(b, "POST", "/api/admin/repair-types", json=tipo(codigo="TR-CLI-ANT", garantia_dias=45))
            anotar("2", "acepta el cuerpo de un cliente anterior (codigo y plazo informados)", r.status_code == 200 and r.json()["garantia_dias"] == 45, r.text)
            r = http(b, "POST", "/api/admin/repair-types", json=tipo(codigo="tr-ant1"))
            anotar("2", "un duplicado en minusculas es 409", r.status_code == 409, r.text)
            r = http(b, "POST", "/api/admin/supplies", json={"usuario_id": ADMIN, "nombre": "Insumo nuevo"})
            anotar("2", "genera el codigo del insumo (INS-NNN = codigo)", r.status_code == 200 and r.json()["id"] == r.json()["codigo"] and r.json()["id"].startswith("INS-"), r.text)
            r = http(b, "POST", "/api/admin/reasons", json={"usuario_id": ADMIN, "tipo": "CANCELACION", "nombre": "Nuevo"})
            anotar("2", "genera el codigo del motivo (CANC-NNN)", r.status_code == 200 and r.json()["codigo"].startswith("CANC-0"), r.text)
            r = http(b, "POST", "/api/admin/suppliers", json={"usuario_id": ADMIN, "nombre": "Proveedor nuevo"})
            anotar("2", "el proveedor saltea el del publicado (PRV-0002)", r.status_code == 200 and r.json()["id"] == "PRV-0002", r.text)
            usuarios = {u["id"]: u for u in http(b, "GET", "/api/catalogs/users").json()}
            permisos_recepcion = usuarios[RECEPCION].get("permisos", [])
            anotar("2", "informa el alias COMPRAS_GESTIONAR al frontend publicado", "COMPRAS_GESTIONAR" in permisos_recepcion and "OC_CREAR" in permisos_recepcion, json.dumps(permisos_recepcion)[:300])
            plantillas = http(b, "GET", "/api/communications/templates").json()["plantillas"]
            anotar("2", "solo INGRESO y LISTO_PARA_RETIRAR visibles; ninguna borrada",
                   sorted(p["codigo"] for p in plantillas if p["visible"]) == ["INGRESO", "LISTO_PARA_RETIRAR"] and len(plantillas) == 5 and all(p["activa"] for p in plantillas),
                   json.dumps([(p["codigo"], p["visible"]) for p in plantillas]))
            r = http(b, "GET", "/api/admin/parameters")
            anotar("2", "el plazo de retiro sigue en el backend", r.status_code == 200 and "PLAZO_RETIRO_DIAS" in r.json()["parametros"], r.text[:200])

        # --- 3. Vuelta atras y vuelta adelante -------------------------------
        print("3. Vuelta atras al publicado y regreso a la version nueva", flush=True)
        with comun.servidor(anterior, comun.entorno(url_api, carpeta / "datos-3", catalogo), a.puerto, registro, cwd) as (b, _):
            tipos = {t["id"] for t in http(b, "GET", "/api/admin/catalog").json()["tipos"]}
            anotar("3", "el publicado lista los tipos creados por la version nueva", nuevo.get("id") in tipos, json.dumps(sorted(tipos)))
            r = http(b, "POST", "/api/admin/suppliers", json={"usuario_id": ADMIN, "nombre": "Otro proveedor anterior"})
            anotar("3", "el publicado sigue dando de alta proveedores (PRV-0003)", r.status_code == 200 and r.json()["id"] == "PRV-0003", r.text)
            r = http(b, "GET", "/api/admin/supplies")
            anotar("3", "el publicado lista los insumos nuevos", r.status_code == 200 and len(r.json()["insumos"]) >= 3, r.text[:200])
        with comun.servidor(BACKEND, comun.entorno(url_api, carpeta / "datos-4", catalogo), a.puerto, registro, cwd) as (b, _):
            r = http(b, "POST", "/api/admin/suppliers", json={"usuario_id": ADMIN, "nombre": "Proveedor despues de volver"})
            anotar("3", "la version nueva saltea lo que creo el publicado (PRV-0004)", r.status_code == 200 and r.json()["id"] == "PRV-0004", r.text)
        historicos = comun.filas(url, "select codigo from rma.tipo_reparacion where codigo in ('TR-001', 'TR-002', 'TR-ANT1', 'TR-CLI-ANT') order by codigo")
        anotar("3", "ningun codigo historico cambio", [c for (c,) in historicos] == ["TR-001", "TR-002", "TR-ANT1", "TR-CLI-ANT"], json.dumps(historicos))
        errores = registro.read_text(encoding="utf-8", errors="replace")
        anotar("3", "ningun 500 en los registros de los servidores", '" 500 ' not in errores)
    except Exception:  # noqa: BLE001
        anotar("-", "el ensayo termino sin errores", False, traceback.format_exc())
    finally:
        try:
            import psycopg

            with psycopg.connect(url_admin, autocommit=True) as admin:
                admin.execute(f"drop database if exists {BASE} with (force)")
        except Exception:  # noqa: BLE001
            pass

    fallas = [r for r in resultados if not r["ok"]]
    if a.informe:
        Path(a.informe).write_text(json.dumps({"resultados": resultados}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRESULTADO: {'OK' if not fallas else 'FALLA'} ({len(resultados) - len(fallas)} de {len(resultados)})")
    print(f"Carpeta del ensayo: {carpeta}")
    return 0 if not fallas else 1


if __name__ == "__main__":
    raise SystemExit(main())
