# ruff: noqa: E501  (mensajes largos)
"""Reparacion RT, etapa 1: E2E contra la PLANILLA DE PRUEBA (tarea 1.8).

Requiere que el origen configurado (``RMA_PRODUCTOS_RT_PLANILLA`` y
``RMA_PRODUCTOS_RT_GID``) sea la planilla de prueba cargada con
``producto.csv`` de ``generar_productos_rt_ficticios.py``: los resultados
esperados son los de esos datos ficticios. NUNCA la planilla real de
Gestion RT (docs/reparacion-rt-discovery.md, seccion 3.3).

Dos fases, con la espera entre medio (``docs/DESPLIEGUE_UAT.md``,
seccion 11):

    sincronizar  inicia sesion como Administracion, sincroniza, comprueba
                 contadores, sedes, busquedas, filtros, ficha, avisos y que
                 nada sensible aparezca; guarda en ``--estado`` lo que quedo
                 (sin tokens ni contrasenas).
    comprobar    despues de que Cloud Run llego a 0 instancias: vuelve a
                 leer (arranque en frio) y lo compara con lo guardado.

    $env:SUPABASE_PUBLISHABLE_KEY = "<clave publicable de São Paulo>"
    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/probar_reparacion_rt.py --fase sincronizar --estado $env:TEMP\\reparacion-rt.json
    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/probar_reparacion_rt.py --fase comprobar --estado $env:TEMP\\reparacion-rt.json

La contrasena de Administracion se pide sin eco y no se guarda. Contra una
API local en modo demo: ``--api http://127.0.0.1:8000 --sin-autenticacion``.
Escribe solo la copia de Productos RT y su intento (como el boton
Actualizar): no crea Ordenes ni otros datos, y no escribe en Gestion RT.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(RAIZ / "app" / "backend"))

from probar_persistencia_catalogo import (  # noqa: E402
    ADMINISTRADOR,
    API_UAT,
    SUPABASE_UAT,
    token_administracion,
)

RUTA = "/api/rt-products"

resultados: list[tuple[str, bool, str]] = []


def anotar(nombre: str, ok: bool, detalle: str = "") -> bool:
    resultados.append((nombre, bool(ok), detalle))
    print(f"{'OK   ' if ok else 'FALLA'} {nombre}" + ("" if ok else f" — {detalle[:300]}"), flush=True)
    return bool(ok)


def ids(listado: dict) -> list[str]:
    return [p["producto_id"] for p in listado["productos"]]


def resumen(cliente: httpx.Client) -> dict:
    listado = cliente.get(RUTA, params={"tamano": 100}).json()
    ultima = listado["copia"]["ultima_exitosa"] or {}
    return {
        "ultima_exitosa": ultima.get("id"),
        "datos_del": listado["copia"]["datos_del"],
        "total": listado["total"],
        "productos": ids(listado),
        "sedes": {s["sede"] or "": s["cantidad"] for s in listado["sedes"]},
    }


def sincronizar(cliente: httpx.Client, ficticios) -> dict | None:
    antes = cliente.get(RUTA).json()["copia"]
    if not anotar("la copia está habilitada y tiene origen", antes["habilitado"] and antes["sincronizable"], json.dumps(antes)[:300]):
        return None
    print(f"      origen configurado: {antes['origen']}")
    r = cliente.post(f"{RUTA}/sync", params={"usuario_id": ADMINISTRADOR})
    textos = [r.text]
    if not anotar("la sincronización es EXITOSA", r.status_code == 200 and r.json().get("resultado") == "EXITOSA", f"HTTP {r.status_code}: {r.text[:300]}"):
        return None
    c = r.json()["contadores"]
    esperados = {
        "leidos": ficticios.LEIDOS,
        "descartados": ficticios.DESCARTADOS,
        "duplicados": len(ficticios.DUPLICADOS),
        "en_reparacion": ficticios.EN_REPARACION,
        "imei_repetidos": 2,
    }
    if not anotar(
        "los contadores son los de los datos ficticios",
        all(c.get(k) == v for k, v in esperados.items()),
        f"obtenidos {c}, esperados {esperados}. ¿El origen es la planilla de prueba?",
    ):
        return None
    listado = cliente.get(RUTA, params={"tamano": 100})
    textos.append(listado.text)
    datos = listado.json()
    sedes = {s["sede"]: s["cantidad"] for s in datos["sedes"] if s["cantidad"]}
    anotar("las cantidades por sede", sedes == ficticios.EN_REPARACION_POR_SEDE, json.dumps(sedes))
    anotar("la sede no confirmada se informa", any(s["sede"] == "Rosario Norte" and not s["confirmada"] for s in datos["sedes"]))
    busquedas = {
        "900002": {"900002"},
        ficticios.imei_ficticio(3): {"900003"},
        "pro máx": {"900002", "900003", "900021", "900022"},
    }
    for q, esperado in busquedas.items():
        obtenido = set(ids(cliente.get(RUTA, params={"q": q}).json()))
        anotar(f"búsqueda «{q}»", obtenido == esperado, f"{sorted(obtenido)}")
    ultimos = ficticios.imei_ficticio(3)[-4:]
    anotar("búsqueda por los últimos 4 dígitos del IMEI", "900003" in ids(cliente.get(RUTA, params={"q": ultimos}).json()))
    centro = set(ids(cliente.get(RUTA, params={"sede": "Centro"}).json()))
    anotar("filtro de sede", centro == {"900003", "900004", "900005"}, f"{sorted(centro)}")
    fuera = cliente.get(RUTA, params={"incluir_fuera": "true", "tamano": 100}).json()
    # Con historia previa en la copia puede haber más (los que salieron).
    anotar("«mostrar los que salieron» incluye a los que están en reparación", fuera["total"] >= ficticios.EN_REPARACION, str(fuera["total"]))
    con = cliente.get(RUTA, params={"orden_rma": "CON_SUGERENCIAS"}).json()
    sin = cliente.get(RUTA, params={"orden_rma": "SIN_COINCIDENCIAS"}).json()
    anotar("los filtros de Orden RMA se reparten el total", con["total"] + sin["total"] == ficticios.EN_REPARACION, f"{con['total']} + {sin['total']}")
    for producto in con["productos"]:
        for coincidencia in producto["coincidencias_sugeridas"]:
            print(f"      aviso: {producto['producto_id']} coincide con {coincidencia['orden_id']} por {coincidencia['criterios']} (solo sugerencia)")
    ficha = cliente.get(f"{RUTA}/900002")
    textos.append(ficha.text)
    p = ficha.json()["producto"]
    anotar("ficha con el equipo del TipoProducto", (p["modelo"], p["capacidad"]) == ("iPhone 12 Pro Max", "256 GB"), json.dumps(p)[:300])
    anotar("la ficha no expone vínculos ni datos internos", not {"vinculos", "orden_activa", "historial", "texto_busqueda", "huella"} & set(p))
    avisos = {
        "900004": "SIN_IMEI",
        "900005": "IMEI_INVALIDO",
        "900007": "TIPO_NO_ENCONTRADO",
        "900008": "TIPO_ELIMINADO",
        "900009": "IMEI_REPETIDO",
        "900012": "SEDE_NO_CONFIRMADA",
    }
    for pid, aviso in avisos.items():
        respuesta = cliente.get(f"{RUTA}/{pid}")
        textos.append(respuesta.text)
        anotar(f"aviso {aviso} en {pid}", aviso in respuesta.json()["producto"]["avisos"])
    anotar("un producto que no está: 404", cliente.get(f"{RUTA}/no-existe").status_code == 404)
    intentos = cliente.get(f"{RUTA}/syncs")
    textos.append(intentos.text)
    texto = " ".join(textos)
    anotar("ningún valor NO-LEER en las respuestas", ficticios.VALOR_SENSIBLE not in texto)
    anotar("los avisos de la sincronización no tienen IMEI", all(ficticios.imei_ficticio(n) not in json.dumps(r.json()["avisos"]) for n in range(1, 23)))
    return resumen(cliente)


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fase", choices=("sincronizar", "comprobar"), required=True)
    p.add_argument("--estado", required=True, help="archivo JSON con lo guardado (sin secretos)")
    p.add_argument("--api", default=API_UAT)
    p.add_argument("--supabase-url", default=SUPABASE_UAT)
    p.add_argument("--sin-autenticacion", action="store_true", help="API local en modo demo")
    a = p.parse_args()
    api = a.api.rstrip("/")
    local = api.startswith(("http://127.0.0.1", "http://localhost"))
    if a.sin_autenticacion != local or (not local and (api != API_UAT or a.supabase_url.rstrip("/") != SUPABASE_UAT)):
        print("Destino no permitido: la API pública del UAT, o una API local con --sin-autenticacion.")
        return 2

    from tests.fixtures import productos_rt as ficticios

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
            guardado = sincronizar(cliente, ficticios)
            if guardado is not None:
                archivo.write_text(json.dumps(guardado, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"      estado guardado en {archivo}")
                print("\nAhora: esperar a que Cloud Run llegue a 0 instancias y correr --fase comprobar.")
        else:
            guardado = json.loads(archivo.read_text(encoding="utf-8"))
            ahora = resumen(cliente)
            anotar("después del escalado a cero, la misma copia", ahora == guardado and guardado["ultima_exitosa"] is not None, f"ahora {ahora}, antes {guardado}")
    finally:
        cliente.headers.pop("Authorization", None)
        cliente.close()
    fallas = [r for r in resultados if not r[1]]
    print(f"\nRESULTADO: {'OK' if resultados and not fallas else 'FALLA'} ({len(resultados) - len(fallas)} de {len(resultados)})")
    return 0 if resultados and not fallas else 1


if __name__ == "__main__":
    sys.exit(main())
