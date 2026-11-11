# ruff: noqa: E501  (mensajes largos)
"""Recorridos funcionales críticos sobre la revisión de São Paulo (etapa 7).

ESCRIBE en la base de São Paulo: crea Órdenes ficticias y mueve stock. Solo
corre contra la revisión sin tráfico ``saopaulo---…`` y el proyecto
``pcdnmhzwhzymznojndrn``: cualquier otro destino se rechaza. Después se
devuelve São Paulo a cero Órdenes con el reinicio (plan, sección 15).

Recorridos:

A. Permisos sin escritura: suplantación por consulta y por cuerpo (403),
   técnico sin permiso de stock (403), mantenimiento solo Administración.
B. Reparación completa (HP-REP-001): alta con clave de idempotencia y su
   reintento, recepción, Detalle, comprobante de ingreso, prioridad, toma,
   inicio (reserva), cierre de la ejecución (consumo), control, aviso, pago
   con clave (reintento y clave reutilizada), check-in y entrega.
   Stock esperado: 10/0 -> 10/1 (reserva) -> 9/0 (consumo).
C. DC31: cancelar un Detalle, cancelación bloqueada con el equipo en el
   local, último Detalle -> SIN_TRABAJOS_VIGENTES, devolución, cancelación
   explícita por Coordinación, Orden cerrada sin acciones y fuera de Inicio
   y Taller.
D. Ingreso de stock con clave y reintento: 9 -> 10.

Al final: tiempos de cada comando (para comparar con la tabla de
``00017-wer``) y las Órdenes creadas.

    $env:SUPABASE_PUBLISHABLE_KEY_DESTINO = "<clave publicable de São Paulo>"
    app/backend/.venv/Scripts/python supabase/scripts/migracion_sp/probar_recorridos.py

Pide las cuatro contraseñas sin eco. No imprime tokens ni contraseñas.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BACKEND = "https://saopaulo---rt-rma-uat-api-nszqooxxla-rj.a.run.app"
SUPABASE = "https://pcdnmhzwhzymznojndrn.supabase.co"
DOMINIO = "usuarios.rma.invalid"
CUENTAS = {
    "recepcion": "RECEP-001",
    "tecnico": "TECH-001",
    "coordinacion": "COORD-001",
    "administracion": "ADMIN-001",
}
RECEPTOR = {
    "recibido_por": "Titular de prueba",
    "identificacion_receptor": "DNI 00000000",
}
GRUPOS_ACCIONES = (
    "acciones_disponibles",
    "acciones_cancelacion",
    "acciones_autorizacion",
    "acciones_financieras",
    "acciones_custodia",
    "acciones_complementarias",
)

fallos = 0
tiempos: list[tuple[str, float]] = []
creadas: list[str] = []


def informar(nombre: str, ok: bool, detalle: str = "") -> bool:
    global fallos
    fallos += 0 if ok else 1
    print(
        f"  {'OK   ' if ok else 'ERROR'} {nombre}{(' - ' + detalle) if detalle and not ok else ''}"
    )
    return ok


def pedir(metodo, url, cuerpo=None, token=None, apikey=None, clave=None):
    encabezados = {"Content-Type": "application/json"}
    if token:
        encabezados["Authorization"] = f"Bearer {token}"
    if apikey:
        encabezados["apikey"] = apikey
    if clave:
        encabezados["Idempotency-Key"] = clave
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    req = urllib.request.Request(
        url, data=datos, method=metodo, headers=encabezados
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "null")
        except ValueError:
            return e.code, None


def api(
    metodo, ruta, token, cuerpo=None, clave=None, medir: str | None = None
):
    inicio = time.perf_counter()
    estado, respuesta = pedir(
        metodo, BACKEND + ruta, cuerpo, token, clave=clave
    )
    if medir:
        tiempos.append((medir, time.perf_counter() - inicio))
    return estado, respuesta


def error(cuerpo) -> str | None:
    return (
        (cuerpo or {}).get("error", {}).get("codigo")
        if isinstance(cuerpo, dict)
        else None
    )


def stock(token, insumo_id) -> tuple[float, float]:
    _, inventario = api("GET", "/api/inventory", token)
    fila = next((i for i in inventario or [] if i["id"] == insumo_id), {})
    return float(fila.get("stock_fisico", "nan")), float(
        fila.get("reservado", "nan")
    )


def ids_en(bandejas) -> set[str]:
    return {
        i["orden"]["id"]
        for b in (bandejas or {}).get("bandejas", [])
        for i in b["ordenes"]
    }


def nueva_orden(
    rec, etiqueta: str, medir: str | None = None, clave: str | None = None
):
    cuerpo = {
        "usuario_id": "RECEP-001",
        "cliente": {
            "nombre_apellido": f"PRUEBA SP {etiqueta} {time.strftime('%Y-%m-%d %H:%M')}",
            "telefono": "0000",
        },
        "equipo": {
            "marca": "Apple",
            "modelo": "iPhone 14",
            "falla_reportada": "Prueba funcional de São Paulo, no reparar.",
        },
    }
    estado, orden = api(
        "POST", "/api/orders", rec, cuerpo, clave=clave, medir=medir
    )
    if estado == 201:
        creadas.append(orden["id"])
    return estado, orden, cuerpo


def main() -> int:
    publicable = os.environ.get("SUPABASE_PUBLISHABLE_KEY_DESTINO", "")
    if not publicable.startswith("sb_publishable_"):
        print(
            "Falta SUPABASE_PUBLISHABLE_KEY_DESTINO (clave publicable de São Paulo)."
        )
        return 2
    if "saopaulo---" not in BACKEND or "pcdnmhzwhzymznojndrn" not in SUPABASE:
        print(
            "Destino no permitido: solo la revisión saopaulo--- y el proyecto de São Paulo."
        )
        return 2

    print(f"Backend: {BACKEND}\nSupabase: {SUPABASE}\n")
    tokens = {}
    for usuario, codigo in CUENTAS.items():
        clave = getpass.getpass(f"Contraseña de '{usuario}' (no se muestra): ")
        estado, datos = pedir(
            "POST",
            f"{SUPABASE}/auth/v1/token?grant_type=password",
            {"email": f"{usuario}@{DOMINIO}", "password": clave},
            apikey=publicable,
        )
        del clave
        token = (datos or {}).get("access_token") if estado == 200 else None
        if token:
            estado, yo = api("GET", "/api/me", token)
            token = (
                token if estado == 200 and codigo in json.dumps(yo) else None
            )
        if not informar(
            f"sesión de {usuario} ({codigo})", bool(token), f"HTTP {estado}"
        ):
            return 1
        tokens[usuario] = token
    rec, tec, coo, adm = (
        tokens[u]
        for u in ("recepcion", "tecnico", "coordinacion", "administracion")
    )

    # Punto de partida: São Paulo recién migrado.
    _, ordenes = api("GET", "/api/orders", rec)
    _, inventario = api("GET", "/api/inventory", rec)
    insumo = next(
        (i for i in inventario or [] if i["codigo"] == "BAT-IP14"), None
    )
    if not informar(
        "punto de partida: cero Órdenes y BAT-IP14 10/0",
        ordenes == []
        and insumo is not None
        and float(insumo["stock_fisico"]) == 10
        and float(insumo["reservado"]) == 0,
    ):
        print(
            "  No se ejecutan recorridos con escritura fuera del estado inicial."
        )
        return 1
    insumo_id = insumo["id"]
    _, tipos = api("GET", "/api/catalogs/repair-types", rec)
    _, estaciones = api("GET", "/api/catalogs/stations", tec)
    tipo_bateria = next(
        t["id"]
        for t in tipos
        if t["id"] == "TR-001" or "bater" in t.get("nombre", "").lower()
    )
    tipos_dc31 = [t["id"] for t in tipos if t.get("activo", True)][:2]
    estacion = estaciones[0]["id"]

    print("\nA. Permisos")
    estado, cuerpo = api("GET", "/api/work/inbox?usuario_id=TECH-001", rec)
    informar(
        "suplantación por consulta -> 403",
        estado == 403 and error(cuerpo) == "IDENTIDAD_NO_COINCIDE",
        f"{estado} {error(cuerpo)}",
    )
    estado, cuerpo = api(
        "POST",
        "/api/orders",
        rec,
        {
            "usuario_id": "ADMIN-001",
            "cliente": {"nombre_apellido": "X", "telefono": "1"},
            "equipo": {"marca": "X", "modelo": "X"},
        },
    )
    informar(
        "suplantación por cuerpo -> 403",
        estado == 403 and error(cuerpo) == "IDENTIDAD_NO_COINCIDE",
        f"{estado} {error(cuerpo)}",
    )
    estado, cuerpo = api(
        "POST",
        f"/api/inventory/{insumo_id}/receipts",
        tec,
        {"usuario_id": "TECH-001", "cantidad": "1", "motivo": "prueba"},
    )
    informar(
        "técnico sin permiso de stock -> 403",
        estado == 403 and error(cuerpo) == "ROL_NO_AUTORIZADO",
        f"{estado} {error(cuerpo)}",
    )
    estado, cuerpo = api(
        "POST", "/api/maintenance/photos/cleanup?usuario_id=RECEP-001", rec
    )
    informar(
        "mantenimiento solo Administración -> 403",
        estado == 403 and error(cuerpo) == "ROL_NO_AUTORIZADO",
        f"{estado} {error(cuerpo)}",
    )

    print("\nB. Reparación completa (HP-REP-001)")
    clave_alta = "sp-alta-" + uuid.uuid4().hex
    estado, orden, cuerpo_alta = nueva_orden(
        rec, "HP", medir="Alta de Orden", clave=clave_alta
    )
    if not informar("alta", estado == 201, f"{estado} {error(orden)}"):
        return 1
    oid = orden["id"]
    print(f"      Orden: {oid}")
    estado, repetida = api(
        "POST",
        "/api/orders",
        rec,
        cuerpo_alta,
        clave=clave_alta,
        medir="Reintento idempotente",
    )
    informar(
        "reintento del alta con la misma clave: la misma Orden",
        estado in (200, 201) and (repetida or {}).get("id") == oid,
        f"{estado}",
    )
    estado, _ = api(
        "PUT",
        f"/api/orders/{oid}/reception",
        rec,
        {
            "usuario_id": "RECEP-001",
            "estado_fisico": "Sin golpes; pantalla sana.",
            "accesorios": [],
            "observaciones": None,
            "notas_internas": None,
        },
    )
    informar("recepción: estado físico", estado == 200, str(estado))
    estado, orden = api(
        "POST",
        f"/api/orders/{oid}/details",
        rec,
        {"usuario_id": "RECEP-001", "tipo_reparacion_id": tipo_bateria},
        medir="Agregar trabajo",
    )
    informar("Detalle de batería", estado == 200, f"{estado} {error(orden)}")
    detalle = orden["reparaciones_detail"][0]["id"] if estado == 200 else None
    estado, orden = api(
        "POST",
        f"/api/orders/{oid}/documents/intake-receipt",
        rec,
        {"usuario_id": "RECEP-001"},
        medir="Comprobante de ingreso",
    )
    informar(
        "comprobante de ingreso: EN_COLA",
        estado == 200 and orden["estado_workflow"] == "EN_COLA",
        f"{estado} {(orden or {}).get('estado_workflow')}",
    )
    estado, orden = api(
        "POST",
        f"/api/orders/{oid}/priority",
        coo,
        {"usuario_id": "COORD-001", "prioridad": 1},
    )
    informar(
        "prioridad urgente (Coordinación)",
        estado == 200 and orden["prioridad"] == 1,
        f"{estado}",
    )
    estado, orden = api(
        "POST",
        f"/api/orders/{oid}/take",
        tec,
        {"usuario_id": "TECH-001", "estacion_id": estacion},
    )
    informar("toma del técnico", estado == 200, f"{estado} {error(orden)}")
    estado, orden = api(
        "POST",
        f"/api/orders/{oid}/details/{detalle}/start",
        tec,
        {"usuario_id": "TECH-001"},
        medir="Iniciar trabajo",
    )
    informar(
        "inicio: EN_REPARACION",
        estado == 200 and orden["estado_workflow"] == "EN_REPARACION",
        f"{estado} {error(orden)}",
    )
    ejecucion = orden["ejecuciones"][0]["id"] if estado == 200 else None
    informar(
        "stock con la reserva: 10/1",
        stock(rec, insumo_id) == (10.0, 1.0),
        str(stock(rec, insumo_id)),
    )
    estado, orden = api(
        "POST",
        f"/api/orders/{oid}/executions/{ejecucion}/complete",
        tec,
        {
            "usuario_id": "TECH-001",
            "insumos_utilizados": [{"insumo_id": insumo_id, "cantidad": "1"}],
            "observaciones": "Prueba de São Paulo.",
        },
        medir="Cerrar ejecución",
    )
    informar(
        "ejecución completada",
        estado == 200 and orden["ejecuciones"][0]["estado"] == "COMPLETADO",
        f"{estado} {error(orden)}",
    )
    informar(
        "stock con el consumo: 9/0",
        stock(rec, insumo_id) == (9.0, 0.0),
        str(stock(rec, insumo_id)),
    )
    estado, orden = api(
        "POST",
        f"/api/orders/{oid}/control/approve",
        rec,
        {"usuario_id": "RECEP-001", "observaciones": "Funciona."},
    )
    informar(
        "control aprobado: REPARACION_LISTA",
        estado == 200 and orden["estado_workflow"] == "REPARACION_LISTA",
        f"{estado} {error(orden)}",
    )
    estado, aviso = api(
        "POST", f"/api/orders/{oid}/notify", rec, {"usuario_id": "RECEP-001"}
    )
    saldo = (aviso or {}).get("resumen", {}).get("saldo")
    informar(
        "aviso al cliente con saldo pendiente",
        estado == 200 and saldo not in (None, "0"),
        f"{estado} saldo {saldo}",
    )
    clave_pago = "sp-pago-" + uuid.uuid4().hex
    pago = {"usuario_id": "ADMIN-001", "monto": saldo, "metodo": "EFECTIVO"}
    estado, p1 = api(
        "POST",
        f"/api/orders/{oid}/payments",
        adm,
        pago,
        clave=clave_pago,
        medir="Registrar pago",
    )
    estado2, p2 = api(
        "POST", f"/api/orders/{oid}/payments", adm, pago, clave=clave_pago
    )
    informar(
        "pago y reintento con la misma clave: un solo pago",
        estado == 200
        and estado2 == 200
        and (p1 or {}).get("resumen", {}).get("saldo") == "0"
        and p1 == p2,
        f"{estado}/{estado2}",
    )
    estado, cuerpo = api(
        "POST",
        f"/api/orders/{oid}/payments",
        adm,
        {**pago, "monto": "1"},
        clave=clave_pago,
    )
    informar(
        "misma clave con otro monto -> CLAVE_REUTILIZADA",
        estado == 422 and error(cuerpo) == "CLAVE_REUTILIZADA",
        f"{estado} {error(cuerpo)}",
    )
    _, orden = api("GET", f"/api/orders/{oid}", rec)
    if (
        any(
            a["codigo"] == "REGISTRAR_CHECKIN"
            for a in orden["acciones_disponibles"]
        )
        and orden["recepcion"]["datos"]["checkin"] is None
    ):
        estado, _ = api(
            "POST",
            f"/api/orders/{oid}/checkin",
            rec,
            {"usuario_id": "RECEP-001", "realizado": True},
        )
        informar("check-in previo a la entrega", estado == 200, str(estado))
    estado, orden = api(
        "POST",
        f"/api/orders/{oid}/deliver",
        adm,
        {"usuario_id": "ADMIN-001", **RECEPTOR},
        medir="Entregar",
    )
    informar(
        "entrega: ENTREGADA y cerrada",
        estado == 200
        and orden["estado_workflow"] == "ENTREGADA"
        and orden["cerrada"] is True,
        f"{estado} {error(orden)}",
    )
    if estado == 200:
        informar(
            "comprobante final y garantía generados",
            orden["documentos"]["comprobante_final"]["generado"]
            and orden["documentos"]["garantia_reparacion"]["generado"],
        )

    print("\nC. DC31")
    estado, orden, _ = nueva_orden(rec, "DC31")
    if not informar(
        "alta de la Orden DC31", estado == 201, f"{estado} {error(orden)}"
    ):
        return 1
    oid31 = orden["id"]
    print(f"      Orden: {oid31}")
    for t in tipos_dc31:
        api(
            "POST",
            f"/api/orders/{oid31}/details",
            rec,
            {"usuario_id": "RECEP-001", "tipo_reparacion_id": t},
        )
    api(
        "PUT",
        f"/api/orders/{oid31}/reception",
        rec,
        {
            "usuario_id": "RECEP-001",
            "estado_fisico": "Equipo de prueba.",
            "accesorios": [],
            "observaciones": None,
            "notas_internas": None,
        },
    )
    estado, orden = api(
        "POST",
        f"/api/orders/{oid31}/documents/intake-receipt",
        rec,
        {"usuario_id": "RECEP-001"},
    )
    informar("ingreso con dos Detalles", estado == 200, str(estado))
    estado, orden = api(
        "POST",
        f"/api/orders/{oid31}/details/DET-001/cancel",
        rec,
        {"usuario_id": "RECEP-001", "motivo": "Prueba DC31"},
    )
    informar(
        "cancelar un Detalle no cancela la Orden",
        estado == 200
        and orden["estado_workflow"] != "CANCELADA"
        and orden["situacion"]["codigo"] != "SIN_TRABAJOS_VIGENTES",
        str(estado),
    )
    _, antes = api("GET", f"/api/orders/{oid31}", rec)
    estado, _ = api(
        "POST",
        f"/api/orders/{oid31}/cancel",
        rec,
        {"usuario_id": "RECEP-001", "motivo": "Prueba DC31"},
    )
    _, despues = api("GET", f"/api/orders/{oid31}", rec)
    informar(
        "cancelar con el equipo en el local se rechaza sin cambios",
        estado == 409 and len(antes["historial"]) == len(despues["historial"]),
        str(estado),
    )
    estado, orden = api(
        "POST",
        f"/api/orders/{oid31}/details/DET-002/cancel",
        rec,
        {"usuario_id": "RECEP-001", "motivo": "Prueba DC31"},
    )
    informar(
        "último Detalle -> SIN_TRABAJOS_VIGENTES, abierta",
        estado == 200
        and orden["situacion"]["codigo"] == "SIN_TRABAJOS_VIGENTES"
        and orden["cerrada"] is False,
        str(estado),
    )
    estado, orden = api(
        "POST",
        f"/api/orders/{oid31}/return-equipment",
        rec,
        {"usuario_id": "RECEP-001", "recibido_por": "Prueba DC31"},
    )
    informar(
        "devolución física antes de cancelar",
        estado == 200 and orden["devolucion"] is not None,
        str(estado),
    )
    estado, orden = api(
        "POST",
        f"/api/orders/{oid31}/cancel",
        coo,
        {"usuario_id": "COORD-001", "motivo": "Prueba DC31: cierre"},
        medir="Cancelar Orden",
    )
    informar(
        "cancelación explícita: CANCELADA y cerrada",
        estado == 200
        and orden["estado_workflow"] == "CANCELADA"
        and orden["cerrada"] is True,
        str(estado),
    )
    informar(
        "Orden cancelada sin acciones operativas",
        estado == 200 and all(orden[g] == [] for g in GRUPOS_ACCIONES),
    )
    estado, _ = api(
        "POST",
        f"/api/orders/{oid31}/payments",
        rec,
        {"usuario_id": "RECEP-001", "monto": "1", "metodo": "EFECTIVO"},
    )
    informar(
        "comando sobre la Orden cerrada -> 409", estado == 409, str(estado)
    )
    en_inicio = any(
        oid31
        in ids_en(api("GET", f"/api/work/inbox?usuario_id={c}", tokens[u])[1])
        for u, c in CUENTAS.items()
    )
    en_taller = oid31 in ids_en(
        api("GET", "/api/work/workshop?usuario_id=TECH-001", tec)[1]
    )
    informar(
        "no aparece en Inicio ni en Taller", not en_inicio and not en_taller
    )

    print("\nD. Ingreso de stock")
    clave_ingreso = "sp-ingreso-" + uuid.uuid4().hex
    ingreso = {
        "usuario_id": "COORD-001",
        "cantidad": "1",
        "motivo": "Prueba de São Paulo",
    }
    estado, _ = api(
        "POST",
        f"/api/inventory/{insumo_id}/receipts",
        coo,
        ingreso,
        clave=clave_ingreso,
        medir="Ingreso de stock",
    )
    estado2, _ = api(
        "POST",
        f"/api/inventory/{insumo_id}/receipts",
        coo,
        ingreso,
        clave=clave_ingreso,
    )
    informar(
        "ingreso y reintento con la misma clave",
        estado == 200 and estado2 == 200,
        f"{estado}/{estado2}",
    )
    informar(
        "stock final: 10/0 (un solo ingreso)",
        stock(rec, insumo_id) == (10.0, 0.0),
        str(stock(rec, insumo_id)),
    )
    tokens.clear()

    print("\nTiempos de los comandos (cliente):")
    for nombre, segundos in tiempos:
        print(f"  {nombre:<24}{segundos:>8.3f} s")
    print(
        f"\nÓrdenes creadas (para el reinicio): {', '.join(creadas) or 'ninguna'}"
    )
    print(
        f"\nRESULTADO: {'TODO OK' if fallos == 0 else str(fallos) + ' verificación(es) con ERROR'}"
    )
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
