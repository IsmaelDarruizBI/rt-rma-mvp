# ruff: noqa: E501  (SQL y mensajes largos)
"""Ensayo LOCAL de Reparacion RT, etapa 1 (tareas 1.4 y 1.8).

Solo contra un PostgreSQL local y descartable (nunca Supabase), con los
productos ficticios (``generar_productos_rt_ficticios.py``). Procesos reales
de uvicorn, que se matan sin apagado ordenado:

1. Una instancia sincroniza; se la mata y se borra su carpeta; otra, con
   una carpeta vacia y SIN origen configurado, ve la misma copia (reinicio
   y escalado a cero: nada depende del disco ni de la memoria).
2. Un proceso muere A MITAD de una sincronizacion (origen lento, ``kill``):
   la copia intacta; mientras la reserva vale, otra sincronizacion recibe
   409; al vencer, la siguiente la marca INTERRUMPIDA y sincroniza.
3. Compatibilidad con el backend publicado (``--anterior``, exportado con
   ``git archive``) sobre la base con la migracion nueva: arranca, lista y
   crea Ordenes y sincroniza el catalogo de Ventas; la version nueva lee lo
   que creo, y la copia de Productos RT no cambio.
4. Nada sensible: ni ``producto_passcode`` ni los valores ``NO-LEER`` ni IMEI
   en los registros de los servidores ni en la base fuera de la copia.

    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/ensayar_reparacion_rt.py --anterior fd434ef

Sin credenciales: el servidor local confia en las conexiones locales.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import ensayar_persistencia_catalogo as comun  # noqa: E402

BACKEND = comun.BACKEND
BASE = "rma_ensayo_reparacion_rt"
RESERVA_S = 10
ADMIN = "ADMIN-001"
RECEPCION = "RECEP-001"

resultados: list[dict] = []


def anotar(paso: str, nombre: str, ok: bool, detalle: str = "") -> bool:
    resultados.append(
        {"paso": paso, "comprobacion": nombre, "ok": bool(ok), "detalle": detalle}
    )
    print(
        f"  {'OK   ' if ok else 'FALLA'} [{paso}] {nombre}"
        + ("" if ok else f" — {detalle[:300]}"),
        flush=True,
    )
    return bool(ok)


def entorno(url_api: str, datos: Path, productos: Path | None, tipos: Path, catalogo: Path) -> dict:
    valores = comun.entorno(url_api, datos, catalogo)
    valores["RMA_SINCRONIZACION_RESERVA_S"] = str(RESERVA_S)
    if productos is None:
        valores["RMA_PRODUCTOS_RT_ORIGEN"] = "ninguno"
    else:
        valores |= {
            "RMA_PRODUCTOS_RT_ORIGEN": "archivo",
            "RMA_PRODUCTOS_RT_ARCHIVO": str(productos),
            "RMA_PRODUCTOS_RT_TIPOS_ARCHIVO": str(tipos),
        }
    return valores


def huella(url: str) -> tuple:
    return comun.filas(
        url,
        "select count(*), md5(coalesce(string_agg(t::text, '|' order by t.producto_id), ''))"
        " from rma.producto_rt t",
    )[0]


def intentos(url: str, copia: str = "PRODUCTOS_RT") -> list[str]:
    return [
        r
        for (r,) in comun.filas(
            url,
            "select resultado from rma.sincronizacion_origen where copia = %s"
            " order by iniciada_en, id",
            (copia,),
        )
    ]


SINCRONIZAR_LENTO = """
import time
from dataclasses import replace
from app.core.config import get_settings
from app.application.contexto import construir_contexto
from app.application.productos_rt import sincronizar_productos_rt
contexto = construir_contexto(get_settings())
real = contexto.proveedor_productos_rt
class Lento:
    descripcion = real.descripcion
    def leer(self):
        print("LEYENDO", flush=True)
        time.sleep(120)
        return real.leer()
contexto = replace(contexto, proveedor_productos_rt=Lento())
sincronizar_productos_rt(contexto, usuario_id="ADMIN-001")
"""


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--admin-url", default="postgresql://postgres@127.0.0.1:55432/postgres")
    p.add_argument("--anterior", required=True, help="commit del backend publicado")
    p.add_argument("--puerto", type=int, default=8893)
    p.add_argument("--informe")
    a = p.parse_args()

    import httpx

    from tests.fixtures import productos_rt as ficticios
    from tests.fixtures.catalogo_ventas import (
        escribir_csv as escribir_catalogo,
    )

    carpeta = Path(tempfile.mkdtemp(prefix="rma-ensayo-rt-"))
    registro = carpeta / "registro.txt"
    productos = ficticios.escribir_csv(carpeta / "producto.csv")
    tipos = ficticios.escribir_tipos(carpeta / "tipo_producto.csv")
    catalogo = escribir_catalogo(carpeta / "catalogo.csv")
    cwd = carpeta / "cwd"  # sin .env
    cwd.mkdir()

    comun.BASE = BASE
    url_admin = a.admin_url
    try:
        url = comun.preparar_base(url_admin)
        url_api = comun.url_base(url_admin, BASE, comun.ROL_API)
        puerto = a.puerto

        # --- 1. Reinicio y escalado a cero ---------------------------------
        print("1. Reinicio y escalado a cero", flush=True)
        datos_a = carpeta / "datos-a"
        with comun.servidor(BACKEND, entorno(url_api, datos_a, productos, tipos, catalogo), puerto, registro, cwd) as (base_http, _):
            r = httpx.post(f"{base_http}/api/rt-products/sync", params={"usuario_id": ADMIN}, timeout=60)
            exitosa = r.json()
            anotar("1", "la primera sincronizacion es EXITOSA", r.status_code == 200 and exitosa.get("resultado") == "EXITOSA", r.text)
            anotar("1", "14 en reparacion", exitosa.get("contadores", {}).get("en_reparacion") == ficticios.EN_REPARACION, r.text)
            antes = httpx.get(f"{base_http}/api/rt-products", params={"tamano": 100}, timeout=30).json()
        shutil.rmtree(datos_a, ignore_errors=True)
        huella_1 = huella(url)
        datos_b = carpeta / "datos-b"
        with comun.servidor(BACKEND, entorno(url_api, datos_b, None, tipos, catalogo), puerto, registro, cwd) as (base_http, _):
            despues = httpx.get(f"{base_http}/api/rt-products", params={"tamano": 100}, timeout=30).json()
            anotar("1", "otra instancia, sin carpeta ni origen, ve la misma copia",
                   [x["producto_id"] for x in despues["productos"]] == [x["producto_id"] for x in antes["productos"]]
                   and despues["copia"]["ultima_exitosa"]["id"] == exitosa["id"], json.dumps(despues["copia"])[:300])
            anotar("1", "sin origen no se puede sincronizar (409) y no registra intentos",
                   httpx.post(f"{base_http}/api/rt-products/sync", params={"usuario_id": ADMIN}, timeout=30).status_code == 409
                   and intentos(url) == ["EXITOSA"])
            anotar("1", "las cantidades por sede son las del archivo ficticio",
                   {s["sede"]: s["cantidad"] for s in despues["sedes"] if s["cantidad"]} == ficticios.EN_REPARACION_POR_SEDE,
                   json.dumps(despues["sedes"]))

        # --- 2. Proceso muerto a mitad de la sincronizacion ---------------
        print("2. Proceso muerto a mitad de la sincronizacion", flush=True)
        variables = entorno(url_api, carpeta / "datos-c", productos, tipos, catalogo)
        lento = subprocess.Popen(
            [sys.executable, "-c", SINCRONIZAR_LENTO],
            cwd=cwd,
            env=variables | {"PYTHONPATH": str(BACKEND)},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        linea = lento.stdout.readline()
        anotar("2", "la sincronizacion lenta reservo y esta leyendo", "LEYENDO" in linea, linea)
        lento.kill()
        lento.wait(15)
        anotar("2", "la copia quedo intacta", huella(url) == huella_1)
        with comun.servidor(BACKEND, variables, puerto, registro, cwd) as (base_http, _):
            ocupada = httpx.post(f"{base_http}/api/rt-products/sync", params={"usuario_id": ADMIN}, timeout=30)
            anotar("2", "mientras la reserva vale: 409 SINCRONIZACION_EN_CURSO",
                   ocupada.status_code == 409 and ocupada.json()["error"]["codigo"] == "SINCRONIZACION_EN_CURSO", ocupada.text)
            time.sleep(RESERVA_S + 2)
            luego = httpx.post(f"{base_http}/api/rt-products/sync", params={"usuario_id": ADMIN}, timeout=60)
            anotar("2", "al vencer: INTERRUMPIDA y la siguiente EXITOSA",
                   luego.status_code == 200 and intentos(url) == ["EXITOSA", "INTERRUMPIDA", "EXITOSA"], f"{luego.text[:200]} {intentos(url)}")
            anotar("2", "la copia no cambio (mismos datos)", huella(url)[0] == huella_1[0])
        huella_2 = huella(url)

        # --- 3. Backend publicado sobre la migracion nueva -----------------
        print(f"3. Backend publicado ({a.anterior}) sobre la migracion nueva", flush=True)
        anterior = comun.exportar(a.anterior, carpeta / "anterior")
        variables_ant = comun.entorno(url_api, carpeta / "datos-ant", catalogo)
        with comun.servidor(anterior, variables_ant, puerto, registro, cwd) as (base_http, _):
            ordenes = httpx.get(f"{base_http}/api/orders", timeout=30)
            anotar("3", "el publicado arranca y lista Ordenes", ordenes.status_code == 200, ordenes.text[:200])
            creada = httpx.post(
                f"{base_http}/api/orders/rt-interno",
                json={"usuario_id": RECEPCION, "referencia_rt": ficticios.ID_CON_REFERENCIA,
                      "equipo": {"marca": "Apple", "modelo": "iPhone 12", "falla_reportada": "Ingreso ficticio."}},
                timeout=30,
            )
            anotar("3", "el publicado crea una Orden RT manual", creada.status_code == 201, creada.text[:200])
            orden_id = creada.json().get("id") if creada.status_code == 201 else None
            ventas = httpx.post(f"{base_http}/api/catalogs/equipment/sync", params={"usuario_id": ADMIN}, timeout=60)
            anotar("3", "el publicado sincroniza el catalogo de Ventas", ventas.status_code == 200 and ventas.json()["resultado"] == "EXITOSA", ventas.text[:200])
            anotar("3", "el publicado no tiene la ruta de Productos RT (404)",
                   httpx.get(f"{base_http}/api/rt-products", timeout=30).status_code == 404)
        anotar("3", "la copia de Productos RT no cambio", huella(url) == huella_2)
        with comun.servidor(BACKEND, entorno(url_api, carpeta / "datos-d", None, tipos, catalogo), puerto, registro, cwd) as (base_http, _):
            ficha = httpx.get(f"{base_http}/api/rt-products/{ficticios.ID_CON_REFERENCIA}", timeout=30).json()
            sugeridas = [c["orden_id"] for c in ficha["producto"]["coincidencias_sugeridas"]]
            anotar("3", "la version nueva sugiere (no vincula) la Orden creada por el publicado", orden_id in sugeridas, json.dumps(sugeridas))
            anotar("3", "la version nueva lee la Orden del publicado",
                   orden_id is not None and httpx.get(f"{base_http}/api/orders/{orden_id}", timeout=30).status_code == 200)

        # --- 4. Nada sensible ----------------------------------------------
        print("4. Datos sensibles", flush=True)
        texto = registro.read_text(encoding="utf-8", errors="replace")
        anotar("4", "los registros no tienen valores NO-LEER", ficticios.VALOR_SENSIBLE not in texto)
        anotar("4", "los registros no tienen IMEI", all(ficticios.imei_ficticio(n) not in texto for n in range(1, 23)))
        base_texto = comun.filas(url, "select coalesce(string_agg(t::text, '|'), '') from rma.producto_rt t")[0][0]
        anotar("4", "la copia no tiene valores NO-LEER", ficticios.VALOR_SENSIBLE not in base_texto)
        columnas = {c for (c,) in comun.filas(url, "select column_name from information_schema.columns where table_schema = 'rma' and table_name = 'producto_rt'")}
        anotar("4", "ninguna columna de passcode, precios ni personas",
               not any(x in c for c in columnas for x in ("passcode", "precio", "documento", "comentario", "creado_por", "eliminado_por")),
               ", ".join(sorted(columnas)))
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
