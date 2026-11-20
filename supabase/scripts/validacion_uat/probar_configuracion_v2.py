# ruff: noqa: E501  (mensajes largos)
"""Validación funcional E2E de Configuración v2 en el UAT (CFG-01 a CFG-08).

Con ``--escribir`` ESCRIBE en el UAT solo filas de catálogo FICTICIAS para
probar los códigos automáticos: tipos de reparación, un motivo, un insumo y
un proveedor con nombre «Ficticio E2E …», que quedan INACTIVOS al terminar
(los catálogos no admiten borrado y sus códigos no se reutilizan). No crea
Órdenes, no mueve stock y no cambia permisos. La limpieza selectiva
(``reinicio_uat/05_linea_base_e2e.sql`` antes y ``06_limpiar_e2e.sql``
después) borra su auditoría, conserva esas filas inactivas y vuelve las
secuencias a la línea de base; aborta si alguna quedó activa.

Escenarios:

1. Matriz de permisos con las cuatro cuentas (con sesión real): cada
   sección responde 200 a quien tiene el permiso predeterminado y 403 al
   resto; lo sensible, solo Administración.
2. Compras mantiene sus accesos (DF-4): Recepción, Coordinación RMA y
   Administración tienen las cinco acciones (y el alias del frontend
   anterior); el Técnico, ninguna. Las acciones se prueban sin escribir:
   un cuerpo vacío pasa el permiso (422) o se corta (403).
3. Códigos automáticos y concurrencia (CFG-01): altas sin código en
   paralelo (códigos distintos), formatos, el código informado por un
   cliente anterior se respeta, un duplicado en minúsculas es 409 y ningún
   código histórico cambia. El plazo genérico de un alta toma el de con
   check-in (DF-1).
4. Plantillas (DF-3) y plazo de retiro (CFG-07): solo dos visibles, ninguna
   borrada ni desactivada; el parámetro sigue en el backend.

Guardas: las de ``probar_macro_v14.py`` (solo la API pública del UAT con São
Paulo, o una API local con ``--sin-autenticacion``; sin ``--escribir`` solo
lectura). La matriz de 403 exige sesión real: en local se omite.

    $env:SUPABASE_PUBLISHABLE_KEY = "<clave publicable de São Paulo>"
    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/probar_configuracion_v2.py --escribir --ordenes-previas OR-000001,... --informe <archivo.json>
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probar_macro_v14 as base  # noqa: E402
from probar_macro_v14 import (  # noqa: E402
    API_UAT,
    SUPABASE_UAT,
    ClienteApi,
    anotar,
    escenario,
    f,
    iniciar_sesiones,
)

ROLES = {
    "ADMINISTRADOR": f.ADMINISTRADOR,
    "RECEPCION": f.RECEPCION,
    "COORDINADOR_RMA": f.COORDINADOR,
    "TECNICO": f.TECNICO,
}
TODOS = set(ROLES)
GESTION = {"RECEPCION", "COORDINADOR_RMA", "ADMINISTRADOR"}
SOLO_ADMIN = {"ADMINISTRADOR"}
COMPRAS = ("COMPRA_SOLICITAR", "OC_CREAR", "OC_CONFIRMAR", "OC_CANCELAR", "COMPRA_RECIBIR")
MARCA = uuid.uuid4().hex[:6].upper()
FICTICIO = "Ficticio E2E"

# Lecturas: ruta -> roles que la ven con los permisos predeterminados.
LECTURAS = {
    "/api/orders": TODOS,
    "/api/work/inbox": TODOS,
    "/api/work/workshop": TODOS,
    "/api/inventory": TODOS,
    "/api/purchases/orders": GESTION,
    "/api/rt-products": GESTION,
    "/api/admin/catalog": SOLO_ADMIN,
    "/api/admin/supplies": SOLO_ADMIN,
    "/api/admin/reasons": SOLO_ADMIN,
    "/api/admin/checklist": SOLO_ADMIN,
    "/api/admin/message-templates": SOLO_ADMIN,
    "/api/admin/suppliers": SOLO_ADMIN,
    "/api/admin/users": SOLO_ADMIN,
    "/api/admin/permissions": SOLO_ADMIN,
    "/api/admin/parameters": SOLO_ADMIN,
    "/api/admin/payment-methods": SOLO_ADMIN,
    "/api/admin/config-changes": SOLO_ADMIN,
}
# Acciones de Compras: ruta -> permiso. Un cuerpo vacío no escribe nada.
ACCIONES_COMPRAS = {
    "/api/purchases/requests": "COMPRA_SOLICITAR",
    "/api/purchases/orders": "OC_CREAR",
    "/api/purchases/orders/OC-NO-EXISTE/confirm": "OC_CONFIRMAR",
    "/api/purchases/orders/OC-NO-EXISTE/cancel": "OC_CANCELAR",
    "/api/purchases/orders/OC-NO-EXISTE/receipts": "COMPRA_RECIBIR",
}

creados: list[tuple[str, str, dict]] = []  # (tipo, codigo, cuerpo para desactivar)


@escenario("1. Matriz de permisos con las cuatro cuentas")
def matriz(c, ctx):
    if not ctx["autenticado"]:
        anotar("1", "la matriz de 403 exige sesión real (se omite en local)", True)
        return
    for ruta, permitidos in LECTURAS.items():
        for rol, usuario in ROLES.items():
            # Las bandejas exigen usuario_id (el mismo contrato que usa el
            # frontend, api/trabajo.ts): sin él, 422 antes de evaluar permisos.
            params = {"usuario_id": usuario} if ruta.startswith("/api/work/") else None
            with c.como(usuario):
                r = c.get(ruta, params=params)
            esperado = 200 if rol in permitidos else 403
            anotar("1", f"{ruta} con {rol}: {esperado}", r.status_code == esperado, f"HTTP {r.status_code}")
    with c.como(f.RECEPCION):
        auditoria = c.get("/api/admin/config-changes", params={"entidad": "INSUMO"})
    anotar("1", "Recepción no ve la auditoría de insumos sin el permiso (403)", auditoria.status_code == 403, f"HTTP {auditoria.status_code}")


@escenario("2. Compras mantiene sus accesos")
def compras(c, ctx):
    for rol, usuario in ROLES.items():
        with c.como(usuario):
            yo = c.get("/api/me") if ctx["autenticado"] else None
        if yo is not None:
            permisos = set(f.ok(yo).get("permisos", []))
            tiene = rol in GESTION
            anotar("2", f"{rol}: las cinco acciones de Compras", all((p in permisos) is tiene for p in COMPRAS), str(sorted(permisos & set(COMPRAS))))
            anotar("2", f"{rol}: alias COMPRAS_GESTIONAR para el frontend anterior", ("COMPRAS_GESTIONAR" in permisos) is tiene, "")
            anotar("2", f"{rol}: proveedores solo Administración", ("PROVEEDOR_GESTIONAR" in permisos) is (rol == "ADMINISTRADOR"), "")
        if not ctx["autenticado"]:
            continue
        for ruta, permiso in ACCIONES_COMPRAS.items():
            with c.como(usuario):
                r = c.post(ruta, json={})
            if rol in GESTION:
                ok = r.status_code in (404, 409, 422)
                esperado = "pasa el permiso (404, 409 o 422, sin escribir)"
            else:
                ok = r.status_code == 403
                esperado = "403"
            anotar("2", f"{permiso} con {rol}: {esperado}", ok, f"HTTP {r.status_code}")


def _tipo(nombre: str, **extra) -> dict:
    return {
        "usuario_id": f.ADMINISTRADOR,
        "nombre": f"{FICTICIO} {nombre} {MARCA}",
        "precio": "1000",
        "puntaje": 1,
        "garantia_con_checkin": 120,
        "garantia_sin_checkin": 45,
        **extra,
    }


def _registrar(tipo: str, codigo: str, cuerpo: dict) -> None:
    creados.append((tipo, codigo, cuerpo))


@escenario("3. Códigos automáticos y concurrencia")
def codigos(c, ctx):
    historicos_tipos = {t["id"] for t in f.ok(c.get("/api/admin/catalog"))["tipos"]}
    historicos_insumos = {(i["id"], i["codigo"]) for i in f.ok(c.get("/api/admin/supplies"))["insumos"]}
    ctx["historicos"] = sorted(historicos_tipos)

    # Dos altas sin código en paralelo, cada una con su propio cliente HTTP.
    resultados: dict[str, object] = {}

    def alta(nombre: str):
        propio = ClienteApi(c._http.base_url.__str__().rstrip("/"), c._tokens)
        try:
            resultados[nombre] = propio.post("/api/admin/repair-types", json=_tipo(nombre))
        finally:
            propio.cerrar()

    hilos = [threading.Thread(target=alta, args=(n,)) for n in ("Tipo A", "Tipo B")]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(120)
    codigos_paralelos = []
    for nombre, r in resultados.items():
        if r.status_code == 200:
            datos = r.json()
            _registrar("tipo", datos["id"], _tipo(nombre))
            codigos_paralelos.append(datos["id"])
            anotar("3", f"alta sin código ({nombre}): formato TR-NNN", re.fullmatch(r"TR-\d{3,}", datos["id"]) is not None, datos["id"])
            anotar("3", f"alta sin plazo genérico ({nombre}): toma el de con check-in (DF-1)", datos.get("garantia_dias") == 120, str(datos.get("garantia_dias")))
        else:
            anotar("3", f"alta sin código ({nombre})", False, f"HTTP {r.status_code} {r.text[:200]}")
    anotar("3", "dos altas simultáneas reciben códigos distintos", len(set(codigos_paralelos)) == 2, str(codigos_paralelos))
    anotar("3", "ningún código generado repite uno histórico", not (set(codigos_paralelos) & historicos_tipos), str(codigos_paralelos))

    # Cliente anterior: informa el código; se respeta.
    informado = f"TR-E2E-{MARCA}"
    r = c.post("/api/admin/repair-types", json=_tipo("Tipo informado", codigo=informado))
    if anotar("3", "un código informado por un cliente anterior se respeta", r.status_code == 200 and r.json()["id"] == informado, f"HTTP {r.status_code} {r.text[:200]}"):
        _registrar("tipo", informado, _tipo("Tipo informado"))
    r = c.post("/api/admin/repair-types", json=_tipo("Tipo duplicado", codigo=informado.lower()))
    anotar("3", "un duplicado que solo difiere en mayúsculas es 409, no 500", r.status_code == 409, f"HTTP {r.status_code}")
    if r.status_code == 200:  # no debería: igual se deja inactivo
        _registrar("tipo", r.json()["id"], _tipo("Tipo duplicado"))

    # Motivo, insumo y proveedor sin código.
    cuerpo_motivo = {"usuario_id": f.ADMINISTRADOR, "tipo": "CANCELACION", "nombre": f"{FICTICIO} Motivo {MARCA}"}
    r = c.post("/api/admin/reasons", json=cuerpo_motivo)
    if anotar("3", "motivo sin código: CANC-NNN", r.status_code == 200 and re.fullmatch(r"CANC-\d{3,}", r.json()["codigo"]) is not None, f"HTTP {r.status_code} {r.text[:200]}"):
        _registrar("motivo", r.json()["codigo"], cuerpo_motivo)
    cuerpo_insumo = {"usuario_id": f.ADMINISTRADOR, "nombre": f"{FICTICIO} Insumo {MARCA}", "unidad": "unidad"}
    r = c.post("/api/admin/supplies", json=cuerpo_insumo)
    if r.status_code == 200:
        datos = r.json()
        _registrar("insumo", datos["id"], cuerpo_insumo)
        anotar("3", "insumo sin código: INS-NNN e igual al código (D4)", re.fullmatch(r"INS-\d{3,}", datos["id"]) is not None and datos["codigo"] == datos["id"], f"{datos['id']} / {datos['codigo']}")
        anotar("3", "el insumo generado no repite uno histórico", datos["id"] not in {x for par in historicos_insumos for x in par}, datos["id"])
    else:
        anotar("3", "insumo sin código", False, f"HTTP {r.status_code} {r.text[:200]}")
    cuerpo_proveedor = {"usuario_id": f.ADMINISTRADOR, "nombre": f"{FICTICIO} Proveedor {MARCA}"}
    r = c.post("/api/admin/suppliers", json=cuerpo_proveedor)
    if anotar("3", "proveedor sin código: PRV-NNNN", r.status_code == 200 and re.fullmatch(r"PRV-\d{4,}", r.json()["id"]) is not None, f"HTTP {r.status_code} {r.text[:200]}"):
        _registrar("proveedor", r.json()["id"], cuerpo_proveedor)

    despues = {t["id"] for t in f.ok(c.get("/api/admin/catalog"))["tipos"]}
    anotar("3", "los códigos históricos siguen todos", historicos_tipos <= despues, "")


@escenario("4. Plantillas y plazo de retiro")
def plantillas_y_plazo(c, ctx):
    plantillas = f.ok(c.get("/api/communications/templates"))["plantillas"]
    visibles = sorted(p["codigo"] for p in plantillas if p.get("visible"))
    anotar("4", "solo Ingreso y Equipo listo para retirar visibles (DF-3)", visibles == ["INGRESO", "LISTO_PARA_RETIRAR"], str(visibles))
    anotar("4", "ninguna plantilla borrada ni desactivada", len(plantillas) >= 5 and all(p["activa"] for p in plantillas), str([(p["codigo"], p["activa"]) for p in plantillas]))
    with c.como(f.ADMINISTRADOR):
        parametros = f.ok(c.get("/api/admin/parameters"))["parametros"]
    anotar("4", "el plazo de retiro sigue en el backend (CFG-07)", "PLAZO_RETIRO_DIAS" in parametros, str(parametros))


def desactivar(c) -> None:
    """Deja inactivo todo lo que creó (la limpieza lo exige)."""
    rutas = {
        "tipo": "/api/admin/repair-types/{}",
        "motivo": "/api/admin/reasons/{}",
        "insumo": "/api/admin/supplies/{}",
        "proveedor": "/api/admin/suppliers/{}",
    }
    for tipo, codigo, cuerpo in creados:
        r = c.put(rutas[tipo].format(codigo), json={**cuerpo, "activo": False})
        anotar("fin", f"{tipo} {codigo} queda inactivo", r.status_code == 200, f"HTTP {r.status_code} {r.text[:200]}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default=API_UAT)
    p.add_argument("--supabase-url", default=SUPABASE_UAT)
    p.add_argument("--sin-autenticacion", action="store_true", help="ensayo contra una API local en modo demo")
    p.add_argument("--escribir", action="store_true", help="crea los catálogos ficticios (sin esto, solo lectura)")
    p.add_argument("--permitir-ordenes", action="store_true", help="solo en local: ensayar sobre una base que ya tiene Órdenes")
    base.agregar_ordenes_previas(p)
    p.add_argument("--informe", help="archivo JSON con los resultados (sin tokens ni contraseñas)")
    a = p.parse_args()
    api = a.api.rstrip("/")
    local = api.startswith(("http://127.0.0.1", "http://localhost"))
    if a.sin_autenticacion != local or (not local and (api != API_UAT or a.supabase_url.rstrip("/") != SUPABASE_UAT)):
        print("Destino no permitido: la API pública del UAT con São Paulo, o una API local con --sin-autenticacion.")
        return 2
    if a.permitir_ordenes and not local:
        print("--permitir-ordenes solo se admite contra una API local.")
        return 2
    tokens = None
    if not a.sin_autenticacion:
        publicable = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
        if not publicable.startswith("sb_publishable_"):
            print("Falta SUPABASE_PUBLISHABLE_KEY (la clave publicable de São Paulo).")
            return 2
        tokens = iniciar_sesiones(a.supabase_url.rstrip("/"), publicable, api)
        if tokens is None:
            return base.finalizar(a, 1)
    c = ClienteApi(api, tokens)
    ctx: dict = {"autenticado": tokens is not None}
    try:
        print("\nPrecondiciones:")
        if not a.permitir_ordenes and not base.ordenes_previas_coinciden(c, a.ordenes_previas):
            print("Las Órdenes existentes no son las declaradas: no se escribe nada.")
            return base.finalizar(a, 1)
        matriz(c, ctx)
        compras(c, ctx)
        plantillas_y_plazo(c, ctx)
        if not a.escribir:
            print("\nSin --escribir: solo lectura.")
        else:
            with c.como(f.ADMINISTRADOR):
                codigos(c, ctx)
    finally:
        try:
            with c.como(f.ADMINISTRADOR):
                desactivar(c)
        finally:
            c.cerrar()
            if tokens:
                tokens.clear()
    print(f"\nCatálogos ficticios creados (inactivos): {', '.join(f'{t} {x}' for t, x, _ in creados) or 'ninguno'}")
    return base.finalizar(a, 0 if all(x["ok"] for x in base.resultados) else 1, ctx)


if __name__ == "__main__":
    sys.exit(main())
