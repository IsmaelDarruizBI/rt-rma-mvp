# ruff: noqa: E501  (mensajes largos)
"""Reparacion RT, etapa 1: E2E de la copia de Productos RT (tarea 1.8).

Dos juegos de datos (``--datos``):

- ``ficticios`` (por defecto): el origen configurado es la planilla de
  prueba cargada con ``producto.csv`` de
  ``generar_productos_rt_ficticios.py``; los resultados esperados son los de
  esos datos.
- ``reales``: el origen del UAT desde el 20/11/2026, una copia de Producto
  con IMPORTRANGE autorizada solo para la consulta de Reparacion RT
  (docs/DESPLIEGUE_UAT.md, seccion 12). Sin resultados fijos: coherencia
  entre la sincronizacion, el listado, las sedes, los filtros, las
  busquedas y la ficha. Nunca imprime ni guarda un IMEI completo (la busqueda
  por IMEI usa sus ultimos 4 digitos, porque la URL queda en los registros
  de Cloud Run) y el estado guardado es una huella de los IDs.

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
import hashlib
import json
import re
import sys
from collections import Counter
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
TAMANO = 100
# Campos que puede tener la ficha (ProductoRtOut). Cualquier otro, o un
# nombre que sugiera un dato excluido, es una falla.
CAMPOS_FICHA = {
    "producto_id", "imei", "imei_valido", "imei_repetido", "modelo",
    "capacidad", "color", "descripcion_tipo", "sede", "estado_gestion_rt",
    "en_reparacion", "en_reparacion_desde", "salio_de_reparacion_en",
    "eliminado_en_origen", "presente_en_origen", "avisos",
    "coincidencias_sugeridas", "imei_normalizado", "imei_luhn_valido",
    "tipo_producto_id", "tipo_producto_encontrado", "tipo_producto_eliminado",
    "categoria", "subcategoria", "bateria", "detalle_estetico", "defecto",
    "toma_rt", "tipo_reparacion_origen", "repuesto", "creado_en_origen",
    "conflicto_origen", "cambio_identidad", "identidad_anterior",
    "primera_vez_visto_en", "sincronizado_en",
}  # fmt: skip
EXCLUIDOS = ("passcode", "precio", "documento", "creado_por", "comentario", "movimiento", "app_id")

resultados: list[tuple[str, bool, str]] = []


def ocultar(texto: str) -> str:
    """Nunca un IMEI completo en la salida: toda secuencia de 8 o más dígitos
    queda con sus últimos 4."""
    return re.sub(r"\d{8,}", lambda m: "*" * (len(m.group()) - 4) + m.group()[-4:], texto)


def anotar(nombre: str, ok: bool, detalle: str = "") -> bool:
    resultados.append((nombre, bool(ok), ocultar(detalle)))
    print(ocultar(f"{'OK   ' if ok else 'FALLA'} {nombre}" + ("" if ok else f" — {detalle[:300]}")), flush=True)
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


# --- Datos reales (la copia de Producto con IMPORTRANGE) -----------------
#
# Sin resultados esperados fijos: comprueba la coherencia de lo que hay. Nunca
# imprime ni guarda un IMEI: las búsquedas por IMEI usan sus últimos 4
# dígitos (la URL queda en los registros de Cloud Run), la salida pasa por
# ``ocultar`` y el estado guardado es una huella de los IDs, no los datos.


def todos(cliente: httpx.Client, **params) -> tuple[int, list[dict]]:
    productos: list[dict] = []
    pagina, total = 1, 0
    while True:
        datos = cliente.get(RUTA, params={**params, "tamano": TAMANO, "pagina": pagina}).json()
        total = datos["total"]
        productos += datos["productos"]
        if len(productos) >= total or not datos["productos"]:
            return total, productos
        pagina += 1


def resumen_reales(cliente: httpx.Client) -> dict:
    datos = cliente.get(RUTA, params={"tamano": 1}).json()
    _, productos = todos(cliente)
    ultima = datos["copia"]["ultima_exitosa"] or {}
    return {
        "ultima_exitosa": ultima.get("id"),
        "datos_del": datos["copia"]["datos_del"],
        "total": datos["total"],
        "huella_ids": hashlib.sha256("\n".join(sorted(p["producto_id"] for p in productos)).encode()).hexdigest(),
        "sedes": {s["sede"] or "": s["cantidad"] for s in datos["sedes"]},
    }


def sincronizar_reales(cliente: httpx.Client) -> dict | None:
    antes = cliente.get(RUTA, params={"tamano": 1}).json()["copia"]
    if not anotar("la copia está habilitada y tiene origen", antes["habilitado"] and antes["sincronizable"], f"habilitado={antes['habilitado']} sincronizable={antes['sincronizable']}"):
        return None
    print(f"      origen configurado: {antes['origen']}; filtro: {antes['filtro']}")
    r = cliente.post(f"{RUTA}/sync", params={"usuario_id": ADMINISTRADOR})
    textos = [r.text]
    if not anotar("la sincronización es EXITOSA", r.status_code == 200 and r.json().get("resultado") == "EXITOSA", f"HTTP {r.status_code}: {r.text[:300]}"):
        return None
    sync = r.json()
    c = sync["contadores"]
    print(f"      contadores: {json.dumps(c, ensure_ascii=False)}")
    print(f"      avisos de la sincronización: {len(sync['avisos'])}")
    anotar("hay filas leídas y productos en Reparacion", c.get("leidos", 0) > 0 and c.get("en_reparacion", 0) > 0, json.dumps(c))

    # «producto_status = Reparacion»: el valor exacto que cuenta como en Reparacion.
    filtro = antes["filtro"].split("=", 1)[-1].strip()
    total, productos = todos(cliente)
    anotar("el listado tiene los productos en Reparacion de la sincronización", total == c.get("en_reparacion") == len(productos), f"listado {total} ({len(productos)} leídos), contador {c.get('en_reparacion')}")
    anotar(f"todos los listados están en «{filtro}» exacto", all(p["en_reparacion"] and p["estado_gestion_rt"] == filtro for p in productos), str(Counter(p["estado_gestion_rt"] for p in productos if p["estado_gestion_rt"] != filtro)))
    anotar("ids únicos en el listado", len({p["producto_id"] for p in productos}) == len(productos))
    total_fuera, fuera = todos(cliente, incluir_fuera="true")
    otros = [p for p in fuera if not p["en_reparacion"]]
    anotar("«mostrar los que salieron» agrega solo productos fuera de Reparacion", total_fuera == total + len(otros) and all(p["estado_gestion_rt"] != filtro or p["eliminado_en_origen"] or not p["presente_en_origen"] for p in otros), f"{total_fuera} = {total} + {len(otros)}")
    print(f"      fuera de Reparacion en la copia: {len(otros)}")

    datos = cliente.get(RUTA, params={"tamano": 1}).json()
    sedes = {s["sede"]: s["cantidad"] for s in datos["sedes"]}
    print(f"      sedes: {json.dumps({(k or '(sin sede)'): v for k, v in sedes.items()}, ensure_ascii=False)}; no confirmadas: {[s['sede'] for s in datos['sedes'] if not s['confirmada']]}")
    por_sede = Counter(p["sede"] for p in productos)
    anotar("las cantidades por sede coinciden con el listado", all(sedes.get(s, 0) == n for s, n in por_sede.items()) and sum(sedes.values()) == total, f"{dict(por_sede)} vs {sedes}")
    for sede, n in sorted(((s, n) for s, n in sedes.items() if s and n), key=lambda x: -x[1])[:3]:
        t, lista = todos(cliente, sede=sede)
        anotar(f"filtro de sede «{sede}»", t == n and all(p["sede"] == sede for p in lista), f"{t} de {n}")

    muestra = productos[:1] + productos[len(productos) // 2 : len(productos) // 2 + 1] + productos[-1:]
    for p in {x["producto_id"]: x for x in muestra}.values():
        anotar(f"búsqueda por ID {p['producto_id']}", p["producto_id"] in ids(cliente.get(RUTA, params={"q": p["producto_id"]}).json()))
    con_imei = [p for p in productos if p["imei"] and p["imei_valido"]]
    print(f"      con IMEI válido: {len(con_imei)} de {total}; IMEI repetido: {sum(p['imei_repetido'] for p in productos)}")
    if con_imei:
        p = con_imei[len(con_imei) // 2]
        _, encontrados = todos(cliente, q=p["imei"][-4:])
        anotar(f"búsqueda por los últimos 4 dígitos del IMEI ({p['producto_id']})", p["producto_id"] in {x["producto_id"] for x in encontrados})
    con_modelo = [p for p in productos if p["modelo"]]
    if con_modelo:
        p = con_modelo[0]
        _, encontrados = todos(cliente, q=p["modelo"])
        anotar(f"búsqueda por modelo «{p['modelo']}»", p["producto_id"] in {x["producto_id"] for x in encontrados})

    _, con = todos(cliente, orden_rma="CON_SUGERENCIAS")
    _, sin = todos(cliente, orden_rma="SIN_COINCIDENCIAS")
    anotar("los filtros de Orden RMA se reparten el total", len(con) + len(sin) == total, f"{len(con)} + {len(sin)}")
    for producto in con:
        for coincidencia in producto["coincidencias_sugeridas"]:
            print(ocultar(f"      aviso: {producto['producto_id']} coincide con {coincidencia['orden_id']} por {coincidencia['criterios']} (solo sugerencia)"))
    print(f"      avisos por producto: {json.dumps(Counter(a for p in productos for a in p['avisos']), ensure_ascii=False)}")

    for p in {x["producto_id"]: x for x in muestra}.values():
        ficha = cliente.get(f"{RUTA}/{p['producto_id']}")
        textos.append(ficha.text)
        f = ficha.json()["producto"]
        anotar(f"ficha de {p['producto_id']}: solo campos permitidos", ficha.status_code == 200 and set(f) <= CAMPOS_FICHA, str(sorted(set(f) - CAMPOS_FICHA)))
        anotar(f"ficha de {p['producto_id']}: coincide con el listado", (f["sede"], f["estado_gestion_rt"], f["modelo"]) == (p["sede"], p["estado_gestion_rt"], p["modelo"]))
    anotar("un producto que no está: 404", cliente.get(f"{RUTA}/no-existe-e2e").status_code == 404)
    intentos = cliente.get(f"{RUTA}/syncs")
    textos.append(intentos.text)
    claves = " ".join(re.findall(r'"([a-z_]+)":', " ".join(textos)))
    anotar("ninguna columna excluida en las respuestas", not any(x in claves for x in EXCLUIDOS), str([x for x in EXCLUIDOS if x in claves]))
    imeis = {p["imei"] for p in fuera if p["imei"]}
    avisos = json.dumps(sync["avisos"]) + json.dumps([s["avisos"] for s in intentos.json()])
    anotar("los avisos de la sincronización no tienen IMEI", not any(i in avisos for i in imeis if len(i) >= 8))
    return resumen_reales(cliente)


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fase", choices=("sincronizar", "comprobar"), required=True)
    p.add_argument("--estado", required=True, help="archivo JSON con lo guardado (sin secretos)")
    p.add_argument("--api", default=API_UAT)
    p.add_argument("--supabase-url", default=SUPABASE_UAT)
    p.add_argument("--sin-autenticacion", action="store_true", help="API local en modo demo")
    p.add_argument("--datos", choices=("ficticios", "reales"), default="ficticios", help="ficticios: la planilla de prueba (resultados fijos); reales: la copia de Producto (coherencia, sin IMEI en la salida)")
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
        reales = a.datos == "reales"
        if a.fase == "sincronizar":
            guardado = sincronizar_reales(cliente) if reales else sincronizar(cliente, ficticios)
            if guardado is not None:
                archivo.write_text(json.dumps(guardado, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"      estado guardado en {archivo}")
                print("\nAhora: esperar a que Cloud Run llegue a 0 instancias y correr --fase comprobar.")
        else:
            guardado = json.loads(archivo.read_text(encoding="utf-8"))
            ahora = resumen_reales(cliente) if reales else resumen(cliente)
            anotar("después del escalado a cero, la misma copia", ahora == guardado and guardado["ultima_exitosa"] is not None, f"ahora {ahora}, antes {guardado}")
    finally:
        cliente.headers.pop("Authorization", None)
        cliente.close()
    fallas = [r for r in resultados if not r[1]]
    print(f"\nRESULTADO: {'OK' if resultados and not fallas else 'FALLA'} ({len(resultados) - len(fallas)} de {len(resultados)})")
    return 0 if resultados and not fallas else 1


if __name__ == "__main__":
    sys.exit(main())
