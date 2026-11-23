# ruff: noqa: E501  (mensajes largos)
"""Validación E2E de la iteración de UX de Recepción en el UAT.

ESCRIBE en el UAT con datos FICTICIOS (cliente «Cliente Ficticio E2E UX»,
teléfono 000-0000): crea Órdenes de prueba, registra cobros y devoluciones,
consume una unidad de BAT-IP14 por Orden reparada y cambia el recargo de
Transferencia a 3 % mientras dura la prueba, para restaurarlo a 2 % al
terminar (también si falla: ``finally``). Las Órdenes, los movimientos y la
auditoría de ese cambio se eliminan después con la limpieza selectiva
(``reinicio_uat/05_linea_base_e2e.sql`` antes y ``06_limpiar_e2e.sql``
después), que conserva las Órdenes previas y aborta si el catálogo de
medios de pago no quedó igual. No crea Tipos de Reparación ni insumos.

Escenarios:

1. Ingreso: alta con trabajo inicial, texto único de observaciones (sin
   copiarlo al estado físico) y sin IMEI; un alta cuyo trabajo falla no
   crea nada.
2. Comprobante de ingreso: observaciones una vez, «sin DNI», identificador
   del equipo y espacio de conformidad; imprimir/descargar no emite otro.
3. Medios de pago: Transferencia 2 %; Recepción no lo cambia; sin cambios
   no se registra nada.
4. Recargos (DEC-UX-13): reparto proporcional entre los trabajos, copia
   histórica del porcentaje (2 % y después 3 %), sin duplicados, y
   comprobante de cobro con importes finales y sin línea de recargo; saldo
   y conciliación.
5. Devoluciones (DEC-UX-14): parcial, repetida (rechazada) y sucesiva con
   su proporción de recargo; total con todo el recargo; saldo en cero.
6. Cancelaciones: un trabajo y una Orden.
7. WhatsApp asistido: mensaje preparado sin registrar nada.

Guardas: las de ``probar_macro_v14.py`` (solo la API pública del UAT con São
Paulo, o una API local con ``--sin-autenticacion``; sin ``--escribir`` solo
precondiciones; si las Órdenes existentes no son exactamente las de
``--ordenes-previas``, no escribe).

    $env:SUPABASE_PUBLISHABLE_KEY = "<clave publicable de São Paulo>"
    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/probar_ux_recepcion.py --escribir --ordenes-previas OR-000001 --informe <archivo.json>
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from decimal import Decimal
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
    finalizar,
    iniciar_sesiones,
    orden,
    rechazado,
    stock,
)

from app.domain.recargos import distribuir, recargo_de  # noqa: E402
from tests.fixtures import custodia  # noqa: E402
from tests.fixtures.ingreso_inicial import del_tipo  # noqa: E402

D = Decimal
CLIENTE = {
    "nombre_apellido": "Cliente Ficticio E2E UX",
    "telefono": "000-0000",
}
TEXTO = "E2E UX: no carga. Rayón en la tapa."
OTROS = "TR-OTROS"
TRANSFERENCIA = "TRANSFERENCIA"


def alta(c, trabajo=f.BATERIA) -> dict:
    cuerpo = {
        "usuario_id": f.RECEPCION,
        "cliente": CLIENTE,
        "equipo": {
            "marca": "Apple",
            "modelo": "iPhone 14",
            "falla_reportada": TEXTO,
        },
        "recepcion": {
            "observaciones": TEXTO,
            "observaciones_unificadas": True,
            # DEC-AJ-07: la pantalla la pide siempre; el comprobante la exige.
            "funcionalidades_verificadas": True,
        },
        "trabajo_inicial": trabajo,
    }
    r = c.post("/api/orders", json=cuerpo)
    if r.status_code < 300:
        base.creadas.append(r.json()["id"])
    return r


def otros(c, orden_id, precio: str) -> dict:
    return f.ok(
        c.post(
            f"/api/orders/{orden_id}/details",
            json={
                "usuario_id": f.RECEPCION,
                "tipo_reparacion_id": OTROS,
                "descripcion": "E2E UX: trabajo de prueba",
                "precio": precio,
            },
        )
    )


def ingresada(c, precio_otros: str) -> str:
    """Alta con batería como trabajo inicial, «Otros» y el comprobante."""
    orden_id = f.ok(alta(c))["id"]
    otros(c, orden_id, precio_otros)
    f.ok(
        c.post(
            f"/api/orders/{orden_id}/documents/intake-receipt",
            json={"usuario_id": f.RECEPCION},
        )
    )
    return orden_id


def pagar(c, orden_id, monto, metodo=TRANSFERENCIA, operacion=None):
    return c.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": f.RECEPCION,
            "monto": str(monto),
            "metodo": metodo,
            "operacion_id": operacion,
        },
    )


def devolver(c, orden_id, pago_id, monto, operacion=None):
    return c.post(
        f"/api/orders/{orden_id}/refunds",
        json={
            "usuario_id": f.RECEPCION,
            "pago_id": pago_id,
            "monto": str(monto),
            "medio": TRANSFERENCIA,
            "motivo": "E2E UX: trabajo cancelado.",
            "operacion_id": operacion,
        },
    )


def recargo_medio(c, codigo=TRANSFERENCIA) -> D:
    with c.como(f.ADMINISTRADOR):
        medios = f.ok(c.get("/api/admin/payment-methods"))["medios"]
    return D(
        next(m for m in medios if m["id"] == codigo)["recargo_porcentaje"]
    )


def fijar_recargo(c, porcentaje: str):
    return c.put(
        f"/api/admin/payment-methods/{TRANSFERENCIA}",
        json={"usuario_id": f.ADMINISTRADOR, "recargo_porcentaje": porcentaje},
    )


def elegibles(o) -> list[tuple[str, D]]:
    return [
        (d["id"], D(d["precio"]))
        for d in o["reparaciones_detail"]
        if d["estado"] != "CANCELADO"
    ]


def reparto(pago) -> dict[str, D]:
    return {
        a["detalle_id"]: D(a["importe"]) for a in pago["recargo_distribucion"]
    }


@escenario("1. Ingreso con trabajo inicial, texto único y sin IMEI")
def ingreso(c, ctx):
    antes = len(f.ok(c.get("/api/orders")))
    r = alta(c, trabajo="TR-INEXISTENTE-E2E")
    anotar(
        "1",
        "un alta cuyo trabajo falla se rechaza",
        r.status_code in (404, 409),
        f"HTTP {r.status_code}",
    )
    anotar(
        "1",
        "y no crea ninguna Orden",
        len(f.ok(c.get("/api/orders"))) == antes,
    )
    o = f.ok(alta(c))
    detalles = o["reparaciones_detail"]
    anotar(
        "1",
        "el trabajo inicial se agrega en la misma operación",
        [d["tipo_reparacion_id"] for d in detalles] == [f.BATERIA],
        str(detalles)[:200],
    )
    datos = o["recepcion"]["datos"]
    anotar(
        "1",
        "texto único con su marca y sin estado físico copiado",
        (
            datos["observaciones"],
            datos["observaciones_unificadas"],
            datos["estado_fisico"],
        )
        == (TEXTO, True, None),
        str(datos),
    )
    anotar(
        "1",
        "sin IMEI: identificador interno del equipo",
        o["equipo"]["id"].startswith("EQP-") and not o["equipo"].get("imei"),
        str(o["equipo"])[:200],
    )
    ctx["ingreso"] = o["id"]


@escenario("2. Comprobante de ingreso")
def comprobante(c, ctx):
    orden_id = ctx["ingreso"]
    f.ok(
        c.post(
            f"/api/orders/{orden_id}/documents/intake-receipt",
            json={"usuario_id": f.RECEPCION},
        )
    )
    (documento,) = del_tipo(c, orden_id, "COMPROBANTE_INGRESO")
    ruta = f"/api/orders/{orden_id}/documents/{documento['id']}/pdf"
    primero = c.get(ruta)
    anotar(
        "2",
        "el PDF se descarga",
        primero.status_code == 200,
        f"HTTP {primero.status_code}",
    )
    pdf = primero.content.decode("cp1252", errors="replace")
    anotar(
        "2",
        "observaciones una vez, sin estado físico aparte",
        pdf.count("Observaciones del equipo:") == 1
        and "Estado físico" not in pdf,
    )
    equipo = orden(c, orden_id)["equipo"]["id"]
    anotar(
        "2",
        "con «sin DNI», el identificador y la conformidad",
        "(sin DNI) Tj" in pdf
        and f"({equipo}) Tj" in pdf
        and "Conformidad del cliente" in pdf,
    )
    segundo = c.get(ruta)
    anotar(
        "2",
        "imprimir o descargar otra vez da el mismo PDF y no emite otro",
        segundo.content == primero.content
        and len(del_tipo(c, orden_id, "COMPROBANTE_INGRESO")) == 1,
    )


@escenario("3. Configuración de medios de pago")
def medios(c, ctx):
    anotar(
        "3",
        "Transferencia con 2 %",
        recargo_medio(c) == D("2"),
        str(recargo_medio(c)),
    )
    r = c.put(
        f"/api/admin/payment-methods/{TRANSFERENCIA}",
        json={"usuario_id": f.RECEPCION, "recargo_porcentaje": "5"},
    )
    anotar(
        "3",
        "Recepción no cambia el recargo",
        rechazado(r),
        f"HTTP {r.status_code}",
    )
    r = fijar_recargo(c, "2")
    anotar(
        "3",
        "el mismo valor no registra cambios",
        r.status_code == 409 and "no hay cambios" in r.text,
        f"HTTP {r.status_code}",
    )
    anotar("3", "el recargo sigue en 2 %", recargo_medio(c) == D("2"))


@escenario("4. Recargos repartidos entre los trabajos y comprobante de cobro")
def recargos(c, ctx):
    a = ingresada(c, "50000")
    ctx["cobro"] = a
    o = orden(c, a)
    # Anticipo por transferencia al 2 %.
    operacion = f"e2e-ux-{uuid.uuid4()}"
    o = f.ok(pagar(c, a, "30000", operacion=operacion))
    pago = o["pagos"][-1]
    esperado = dict(distribuir(recargo_de(D(30000), D(2)), elegibles(o)))
    anotar(
        "4",
        "recargo del 2 % sobre lo cobrado",
        (D(pago["recargo_porcentaje"]), D(pago["recargo_importe"]))
        == (D(2), D(600)),
        str(pago)[:200],
    )
    anotar(
        "4",
        "repartido en proporción a los trabajos",
        reparto(pago) == esperado and sum(reparto(pago).values()) == D(600),
        str(pago["recargo_distribucion"]),
    )
    r = pagar(c, a, "30000", operacion=operacion)
    anotar(
        "4",
        "el mismo cobro no se registra dos veces",
        rechazado(r) and len(orden(c, a)["pagos"]) == 1,
        f"HTTP {r.status_code}",
    )
    resumen = orden(c, a)["resumen"]
    anotar(
        "4",
        "el saldo se calcula sobre el importe",
        D(resumen["saldo"]) == D(resumen["total"]) - D(30000),
        str(resumen["saldo"]),
    )
    # El porcentaje cambia: lo registrado conserva su copia.
    r = fijar_recargo(c, "3")
    ctx["recargo_cambiado"] = r.status_code == 200
    anotar(
        "4",
        "Administración cambia el recargo a 3 %",
        r.status_code == 200,
        r.text[:200],
    )
    f.tomada(c, a)
    f.ejecutar(c, a, "DET-001")
    ejecucion = f.iniciar(c, a, "DET-002")
    f.ok(f.cerrar_ejecucion(c, a, ejecucion, cantidad=""))
    f.ok(f.aprobar(c, a, "DET-001"))
    f.ok(f.aprobar(c, a, "DET-002"))
    o = f.ok(
        c.post(f"/api/orders/{a}/notify", json={"usuario_id": f.RECEPCION})
    )
    saldo = D(o["resumen"]["saldo"])
    o = f.ok(pagar(c, a, saldo))
    primero, segundo = o["pagos"]
    anotar(
        "4",
        "el pago anterior conserva el 2 % y el nuevo usa el 3 %",
        (D(primero["recargo_porcentaje"]), D(segundo["recargo_porcentaje"]))
        == (D(2), D(3)),
    )
    anotar("4", "y su reparto no cambió", reparto(primero) == esperado)
    restaurar(c, ctx)
    entregada = f.ok(custodia.entregar(c, a, f.ADMINISTRADOR))
    anotar(
        "4",
        "la Orden se entrega con saldo cero",
        entregada["estado_workflow"] == "ENTREGADA"
        and D(entregada["resumen"]["saldo"]) == 0,
    )
    (doc,) = del_tipo(c, a, "COMPROBANTE_ENTREGA")
    x = doc["contenido"]
    recargo_total = D(primero["recargo_importe"]) + D(
        segundo["recargo_importe"]
    )
    finales = [
        D(t["precio"]) + D(t["recargo"]) for t in x["trabajos_realizados"]
    ]
    anotar(
        "4",
        "cada trabajo con su parte del recargo",
        sum(D(t["recargo"]) for t in x["trabajos_realizados"])
        == recargo_total
        == D(x["recargo_incorporado"]),
        str([t["recargo"] for t in x["trabajos_realizados"]]),
    )
    total = D(x["total"]) + D(x["recargo_incorporado"])
    cobrado = D(x["pagado"]) + D(x["recargo_cobrado"])
    anotar(
        "4",
        "importes finales: la suma de los trabajos es el total y el total cobrado",
        sum(finales) == total == cobrado,
        f"{finales} {total} {cobrado}",
    )
    anotar(
        "4",
        "sin línea de recargo: solo trabajos, pagos y devoluciones",
        all(
            "recargo" not in t["nombre"].lower()
            for t in x["trabajos_realizados"]
        )
        and len(x["pagos"]) == 2,
    )
    anotar(
        "4",
        "conciliación: total - cobrado + devuelto = saldo = 0",
        total - cobrado + D(x["devuelto"]) + D(x["recargo_devuelto"])
        == D(x["saldo"])
        == 0,
    )


def restaurar(c, ctx) -> None:
    """Deja Transferencia en 2 % (idempotente)."""
    if recargo_medio(c) != D("2"):
        r = fijar_recargo(c, "2")
        anotar(
            "4",
            "recargo de Transferencia restaurado a 2 %",
            r.status_code == 200,
            r.text[:200],
        )
    ctx["recargo_cambiado"] = False


@escenario("5. Devoluciones con la proporción del recargo")
def devoluciones(c, ctx):
    b = ingresada(c, "40000")
    total = D(orden(c, b)["resumen"]["total"])
    pago = f.ok(pagar(c, b, total))["pagos"][-1]
    recargo_pago = D(pago["recargo_importe"])
    f.ok(f.cancelar_detalle(c, b, "DET-002"))
    operacion = f"e2e-ux-{uuid.uuid4()}"
    o = f.ok(devolver(c, b, pago["id"], "20000", operacion))
    primera = o["devoluciones_dinero"][-1]
    esperado = (D(20000) * recargo_pago / total).quantize(D("0.01"))
    anotar(
        "5",
        "devolución parcial con su proporción del recargo",
        D(primera["recargo_importe"]) == esperado
        and D(primera["total_reintegrado"]) == D(20000) + esperado,
        str(primera),
    )
    r = devolver(c, b, pago["id"], "20000", operacion)
    anotar(
        "5",
        "la misma devolución no se registra dos veces",
        rechazado(r) and len(orden(c, b)["devoluciones_dinero"]) == 1,
        f"HTTP {r.status_code}",
    )
    o = f.ok(devolver(c, b, pago["id"], "20000"))
    anotar(
        "5",
        "devolución sucesiva",
        len(o["devoluciones_dinero"]) == 2 and D(o["resumen"]["saldo"]) == 0,
        o["resumen"]["saldo"],
    )
    anotar(
        "5",
        "nunca más recargo que el cobrado",
        sum(D(d["recargo_importe"]) for d in o["devoluciones_dinero"])
        <= recargo_pago,
    )
    r = devolver(c, b, pago["id"], "1")
    anotar(
        "5",
        "sin saldo a favor no se devuelve más",
        rechazado(r),
        f"HTTP {r.status_code}",
    )
    # Devolución total: un solo trabajo, cancelado, todo vuelve.
    cc = f.ok(alta(c))["id"]
    f.ok(
        c.post(
            f"/api/orders/{cc}/documents/intake-receipt",
            json={"usuario_id": f.RECEPCION},
        )
    )
    total = D(orden(c, cc)["resumen"]["total"])
    pago = f.ok(pagar(c, cc, total))["pagos"][-1]
    f.ok(f.cancelar_detalle(c, cc, "DET-001"))
    o = f.ok(devolver(c, cc, pago["id"], total))
    (dev,) = o["devoluciones_dinero"]
    anotar(
        "5",
        "devolución total con todo el recargo",
        D(dev["recargo_importe"]) == D(pago["recargo_importe"])
        and D(dev["total_reintegrado"]) == total + D(pago["recargo_importe"]),
        str(dev),
    )
    anotar(
        "5",
        "saldo cero y sin recargo neto",
        D(o["resumen"]["saldo"]) == 0
        and D(o["resumen"]["recargo_cobrado"])
        == D(o["resumen"]["recargo_devuelto"]),
    )


@escenario("6. Cancelación de un trabajo y de una Orden")
def cancelaciones(c, ctx):
    o = orden(c, ctx["ingreso"])
    acciones = [
        a["codigo"]
        for a in o["acciones_cancelacion"] + o["acciones_disponibles"]
    ]
    anotar(
        "6",
        "cancelar el trabajo y la Orden disponibles",
        "CANCELAR_DETALLE" in acciones and "CANCELAR_ORDEN" in acciones,
        str(acciones),
    )
    d = f.ok(alta(c))["id"]
    # DC31: antes de cancelar se define la custodia (aca, nunca ingreso).
    f.ok(custodia.no_recibido(c, d, motivo="E2E UX: el equipo nunca ingresó."))
    r = c.post(
        f"/api/orders/{d}/cancel",
        json={"usuario_id": f.RECEPCION, "motivo": ""},
    )
    anotar(
        "6",
        "cancelar la Orden exige motivo",
        r.status_code in (409, 422),
        f"HTTP {r.status_code}",
    )
    cancelada = f.ok(f.cancelar_orden(c, d))
    anotar(
        "6",
        "la Orden queda cancelada",
        cancelada["estado_workflow"] == "CANCELADA",
        cancelada["estado_workflow"],
    )


@escenario("7. WhatsApp asistido")
def whatsapp(c, ctx):
    orden_id = ctx["ingreso"]
    preparado = f.ok(
        c.get(
            f"/api/orders/{orden_id}/messages/prepare",
            params={"plantilla": "INGRESO"},
        )
    )
    anotar(
        "7",
        "mensaje preparado para el cliente",
        orden_id in preparado["mensaje"] and preparado["impedimento"] is None,
        str(preparado.get("impedimento")),
    )
    anotar(
        "7",
        "preparar no registra nada",
        orden(c, orden_id)["comunicaciones"] == [],
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--api", default=API_UAT)
    p.add_argument("--supabase-url", default=SUPABASE_UAT)
    p.add_argument(
        "--sin-autenticacion",
        action="store_true",
        help="ensayo contra una API local en modo demo",
    )
    p.add_argument(
        "--escribir",
        action="store_true",
        help="crea los datos ficticios (sin esto, solo precondiciones)",
    )
    base.agregar_ordenes_previas(p)
    p.add_argument(
        "--informe",
        help="archivo JSON con los resultados (sin tokens ni contraseñas)",
    )
    a = p.parse_args()
    api = a.api.rstrip("/")
    local = api.startswith(("http://127.0.0.1", "http://localhost"))
    if a.sin_autenticacion != local or (
        not local
        and (api != API_UAT or a.supabase_url.rstrip("/") != SUPABASE_UAT)
    ):
        print(
            "Destino no permitido: la API pública del UAT con São Paulo, o una API local con --sin-autenticacion."
        )
        return 2

    tokens = None
    if not a.sin_autenticacion:
        publicable = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
        if not publicable.startswith("sb_publishable_"):
            print(
                "Falta SUPABASE_PUBLISHABLE_KEY (la clave publicable de São Paulo)."
            )
            return 2
        tokens = iniciar_sesiones(a.supabase_url.rstrip("/"), publicable, api)
        if tokens is None:
            return finalizar(a, 1)
    c = ClienteApi(api, tokens)
    ctx: dict = {}
    try:
        print("\nPrecondiciones:")
        if not base.ordenes_previas_coinciden(c, a.ordenes_previas):
            print(
                "Las Órdenes existentes no son las declaradas: no se escribe nada."
            )
            return finalizar(a, 1)
        if not anotar(
            "0",
            "Transferencia con 2 % antes de empezar",
            recargo_medio(c) == D("2"),
            str(recargo_medio(c)),
        ):
            return finalizar(a, 1)
        inventario = f.ok(c.get("/api/inventory"))
        bateria = [i for i in inventario if i.get("codigo") == "BAT-IP14"]
        if not anotar("0", "insumo BAT-IP14 disponible", len(bateria) == 1):
            return finalizar(a, 1)
        ctx["insumo"] = bateria[0]["id"]
        fisico, reservado = stock(c, ctx["insumo"])
        ctx["stock_inicial"] = [str(fisico), str(reservado)]
        anotar(
            "0",
            "stock suficiente (1 disponible)",
            fisico - reservado >= 1,
            f"{fisico}/{reservado}",
        )
        if not a.escribir:
            print("\nSin --escribir: solo precondiciones.")
            return finalizar(
                a, 0 if all(x["ok"] for x in base.resultados) else 1
            )
        ingreso(c, ctx)
        comprobante(c, ctx)
        medios(c, ctx)
        recargos(c, ctx)
        devoluciones(c, ctx)
        cancelaciones(c, ctx)
        whatsapp(c, ctx)
        ctx["stock_final"] = [str(x) for x in stock(c, ctx["insumo"])]
    finally:
        try:
            if ctx.get("recargo_cambiado") or (
                a.escribir and recargo_medio(c) != D("2")
            ):
                restaurar(c, ctx)
            anotar(
                "x", "Transferencia quedó en 2 %", recargo_medio(c) == D("2")
            )
        finally:
            c.cerrar()
            if tokens:
                tokens.clear()
    print(f"\nÓrdenes creadas: {', '.join(base.creadas) or 'ninguna'}")
    print(
        f"Stock {ctx.get('insumo')}: inicial {ctx.get('stock_inicial')}, final {ctx.get('stock_final')}"
    )
    return finalizar(a, 0 if all(x["ok"] for x in base.resultados) else 1, ctx)


if __name__ == "__main__":
    sys.exit(main())
