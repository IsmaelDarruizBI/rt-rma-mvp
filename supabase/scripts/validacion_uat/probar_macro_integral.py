# ruff: noqa: E501  (mensajes largos)
"""Validación funcional E2E de la macroiteración integral en el UAT.

ESCRIBE en el UAT con datos FICTICIOS: crea Órdenes de prueba (cliente
«Cliente Ficticio E2E V14», teléfono 000-0000), mueve stock de BAT-IP14
(ingresos de una compra, consumo, desperdicio y devolución) y registra una
compra a un proveedor ficticio. No crea Tipos de Reparación, insumos ni
Tipos de Equipo, y no cambia el control por lote de ningún insumo. El único
dato de catálogo que deja es el proveedor «Proveedor Ficticio E2E», que se
reutiliza en cada ejecución y queda inactivo al terminar (``proveedor`` no
admite borrado). Las Órdenes, la compra y los movimientos se eliminan
después con la limpieza selectiva (``reinicio_uat/05_linea_base_e2e.sql``
antes y ``06_limpiar_e2e.sql`` después), que conserva las Órdenes previas.
Es un paso aparte y autorizado.

Escenarios:

1. DC12 inactiva (ABI-42): sin Tipos de Equipo, sin checklist exigido y la
   actualización desde Ventas rechazada sin escribir.
2. Roles y permisos: catálogo con los permisos nuevos y sus roles iniciales.
3. Desperdicio y devolución sobre el stock existente, sin lote.
4. Compras: solicitud, orden de compra, recepción parcial reintentada con la
   misma clave de idempotencia, recepción de más rechazada y cierre.
5. Lotes: BAT-IP14 sigue sin lote y su stock es «sin lote identificado».
6. Catálogos operativos: motivos, parámetros y plantillas de WhatsApp.
7. Identidad del equipo por IMEI.
8. Garantías: check-in no realizado y corregido con motivo, entrega,
   garantía RMA vigente, y un trabajo con garantía en 0 días cuyo reclamo
   se rechaza y se continúa como Orden paga una sola vez.
9. Comunicaciones: mensaje preparado, intento registrado, confirmación
   manual una sola vez; nunca «entregado» ni «leído».

Guardas: las de ``probar_macro_v14.py`` (solo la API pública del UAT con São
Paulo, o una API local con ``--sin-autenticacion``; sin ``--escribir`` solo
precondiciones; si las Órdenes existentes no son exactamente las de
``--ordenes-previas``, no escribe). Para ensayar sobre una base local con
Órdenes sin declararlas, ``--permitir-ordenes`` (solo en local).

    $env:SUPABASE_PUBLISHABLE_KEY = "<clave publicable de São Paulo>"
    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/probar_macro_integral.py --escribir --informe <archivo.json>
"""

from __future__ import annotations

import argparse
import json
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

from tests.fixtures import custodia  # noqa: E402
from tests.fixtures import iteracion1 as it  # noqa: E402

PROVEEDOR = "Proveedor Ficticio E2E"
IMEI = "490154203237526"
D = Decimal


def definida_y_tomada(c) -> str:
    orden_id = f.definida(c, f.BATERIA)
    f.encolar(c, orden_id)
    f.tomar(c, orden_id)
    return orden_id


@escenario("1. DC12 inactiva hasta resolver ABI-42")
def dc12_inactiva(c, ctx):
    catalogo = f.ok(c.get("/api/catalogs/checklist"))
    anotar(
        "1",
        "sin Tipos de Equipo en el catálogo",
        catalogo["tipos"] == [],
        str(catalogo["tipos"])[:200],
    )
    origen = catalogo.get("origen") or {}
    anotar(
        "1",
        "la columna de Ventas no está definida",
        origen.get("definido") is False,
        str(origen),
    )
    r = c.post(
        "/api/admin/equipment-types/sync", json={"usuario_id": f.ADMINISTRADOR}
    )
    anotar(
        "1",
        "actualizar los tipos desde Ventas se rechaza (decisión pendiente), sin escribir",
        r.status_code == 409 and "pendiente" in r.text,
        f"HTTP {r.status_code}",
    )
    orden_id = base.crear_ficticia(c)
    o = orden(c, orden_id)
    anotar(
        "1",
        "una Orden nueva no exige el checklist",
        "Checklist de recepcion" not in o.get("informacion_faltante", []),
        str(o.get("informacion_faltante")),
    )
    anotar(
        "1",
        "la Orden no tiene tipo de equipo",
        o.get("tipo_equipo") is None,
        str(o.get("tipo_equipo")),
    )


@escenario("2. Roles y permisos configurables")
def roles_y_permisos(c, ctx):
    permisos = {
        p["codigo"]: p
        for p in f.ok(
            c.get(
                "/api/admin/permissions",
                params={"usuario_id": f.ADMINISTRADOR},
            )
        )
    }
    # Configuracion v2 (CFG-03): COMPRAS_GESTIONAR se dividio por accion;
    # el backend anterior lo sigue informando.
    anotar(
        "2",
        "permiso de crear OC en el catálogo",
        "OC_CREAR" in permisos or "COMPRAS_GESTIONAR" in permisos,
        str(sorted(permisos))[:200],
    )
    for codigo in (
        "COMPRAS_CONSULTAR",
        "DEVOLUCION_STOCK",
        "ORDENES_CONSULTAR",
        "INVENTARIO_CONSULTAR",
        "CHECKLIST_REGISTRAR",
    ):
        anotar(
            "2",
            f"permiso {codigo} en el catálogo",
            codigo in permisos,
            str(sorted(permisos))[:200],
        )
    consulta = permisos.get("ORDENES_CONSULTAR", {})
    anotar(
        "2",
        "la consulta de Órdenes sigue habilitada para los cuatro roles",
        sorted(consulta.get("vigentes", []))
        == ["ADMINISTRADOR", "COORDINADOR_RMA", "RECEPCION", "TECNICO"],
        str(consulta.get("vigentes")),
    )
    usuarios = f.ok(
        c.get("/api/admin/users", params={"usuario_id": f.ADMINISTRADOR})
    )
    admins = [
        u
        for u in usuarios
        if "ADMINISTRADOR" in (u.get("roles") or [u.get("rol")])
        and u.get("activo")
    ]
    anotar(
        "2",
        "hay al menos un Administrador activo",
        len(admins) >= 1,
        str(len(admins)),
    )
    if ctx["autenticado"]:
        with c.como(f.TECNICO):
            r = c.get(
                "/api/admin/permissions", params={"usuario_id": f.TECNICO}
            )
        anotar(
            "2",
            "Técnico no administra permisos (403)",
            r.status_code == 403,
            f"HTTP {r.status_code}",
        )


@escenario("3. Desperdicio y devolución sobre el stock existente")
def desperdicio_y_devolucion(c, ctx):
    insumo = ctx["insumo"]
    fisico0, reservado0 = stock(c, insumo)
    # Desperdicio: el técnico inutiliza la pieza; cierra la reserva como un
    # consumo.
    a = definida_y_tomada(c)
    ejecucion = f.iniciar(c, a)
    cerrada = c.post(
        f"/api/orders/{a}/executions/{ejecucion}/complete",
        json={
            "usuario_id": f.TECNICO,
            "insumos_utilizados": [
                {"insumo_id": insumo, "cantidad": "0", "desperdicio": "1"}
            ],
        },
    )
    anotar(
        "3",
        "cierre de la Ejecución con desperdicio",
        cerrada.status_code == 200,
        cerrada.text[:200],
    )
    fisico1, reservado1 = stock(c, insumo)
    anotar(
        "3",
        "el desperdicio baja el físico y cierra la reserva",
        (fisico1, reservado1) == (fisico0 - 1, reservado0),
        f"{fisico0}/{reservado0} -> {fisico1}/{reservado1}",
    )
    # Consumo normal y devolución al stock de lo consumido.
    b = definida_y_tomada(c)
    f.ejecutar(c, b)
    consumos = orden(c, b).get("consumos_insumo", [])
    anotar(
        "3",
        "la Orden informa su consumo",
        len(consumos) == 1,
        str(consumos)[:200],
    )
    if consumos:
        r = c.post(
            f"/api/orders/{b}/consumptions/{consumos[0]['id']}/return",
            json={
                "usuario_id": f.TECNICO,
                "cantidad": "1",
                "motivo": "E2E: no se usó.",
            },
        )
        anotar(
            "3",
            "Técnico no devuelve al stock (permiso DEVOLUCION_STOCK)",
            rechazado(r),
            f"HTTP {r.status_code}",
        )
        r = c.post(
            f"/api/orders/{b}/consumptions/{consumos[0]['id']}/return",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "cantidad": "1",
                "motivo": "E2E: no se usó.",
            },
        )
        anotar(
            "3",
            "Administración devuelve lo consumido",
            r.status_code == 200,
            r.text[:200],
        )
        devuelto = orden(c, b)["consumos_insumo"][0]["devuelto"]
        anotar(
            "3",
            "el consumo informa lo devuelto",
            D(str(devuelto)) == 1,
            str(devuelto),
        )
        r = c.post(
            f"/api/orders/{b}/consumptions/{consumos[0]['id']}/return",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "cantidad": "1",
                "motivo": "E2E: otra vez.",
            },
        )
        anotar(
            "3",
            "no se devuelve dos veces",
            rechazado(r),
            f"HTTP {r.status_code}",
        )
    fisico2, reservado2 = stock(c, insumo)
    anotar(
        "3",
        "consumo y devolución se compensan en el físico",
        (fisico2, reservado2) == (fisico1, reservado1),
        f"{fisico1}/{reservado1} -> {fisico2}/{reservado2}",
    )


def _proveedor(c, ctx) -> str:
    proveedores = f.ok(
        c.get("/api/admin/suppliers", params={"usuario_id": f.ADMINISTRADOR})
    )
    lista = (
        proveedores.get("proveedores", proveedores)
        if isinstance(proveedores, dict)
        else proveedores
    )
    existente = next((p for p in lista if p["nombre"] == PROVEEDOR), None)
    if existente is None:
        creado = f.ok(
            c.post(
                "/api/admin/suppliers",
                json={
                    "usuario_id": f.ADMINISTRADOR,
                    "nombre": PROVEEDOR,
                    "telefono": "000-0000",
                },
            )
        )
        ctx["proveedor"] = {"id": creado["id"], "nuevo": True}
        return creado["id"]
    ctx["proveedor"] = {"id": existente["id"], "nuevo": False}
    if not existente["activo"]:
        f.ok(
            c.put(
                f"/api/admin/suppliers/{existente['id']}",
                json={
                    "usuario_id": f.ADMINISTRADOR,
                    "nombre": PROVEEDOR,
                    "telefono": "000-0000",
                    "activo": True,
                },
            )
        )
    return existente["id"]


@escenario("4. Compras con recepciones parciales")
def compras(c, ctx):
    insumo = ctx["insumo"]
    estado = f.ok(c.get("/api/purchases/status"))
    anotar(
        "4",
        "Compras disponible (PostgreSQL)",
        estado.get("disponible") is True,
        str(estado),
    )
    r = c.post(
        "/api/purchases/requests",
        json={
            "usuario_id": f.TECNICO,
            "insumo_id": insumo,
            "cantidad": "3",
            "motivo": "E2E",
        },
    )
    anotar(
        "4",
        "Técnico no gestiona compras",
        rechazado(r),
        f"HTTP {r.status_code}",
    )
    proveedor = _proveedor(c, ctx)
    solicitud = f.ok(
        c.post(
            "/api/purchases/requests",
            json={
                "usuario_id": f.RECEPCION,
                "insumo_id": insumo,
                "cantidad": "3",
                "motivo": "E2E: reponer baterías.",
            },
        )
    )
    oc = f.ok(
        c.post(
            "/api/purchases/orders",
            json={
                "usuario_id": f.RECEPCION,
                "proveedor_id": proveedor,
                "items": [
                    {
                        "insumo_id": insumo,
                        "cantidad": "3",
                        "costo_unitario": "1000",
                    }
                ],
                "solicitudes": [solicitud["id"]],
            },
        )
    )
    ctx["orden_compra"] = oc["id"]
    oc = f.ok(
        c.post(
            f"/api/purchases/orders/{oc['id']}/confirm",
            json={"usuario_id": f.COORDINADOR},
        )
    )
    anotar(
        "4",
        "la OC registra quién la creó y quién la confirmó",
        (oc["creada_por"], oc["confirmada_por"])
        == (f.RECEPCION, f.COORDINADOR),
        str((oc["creada_por"], oc["confirmada_por"])),
    )
    fisico0, _ = stock(c, insumo)
    clave = f"e2e-integral-{uuid.uuid4()}"
    recepcion = {
        "usuario_id": f.RECEPCION,
        "lineas": [
            {"insumo_id": insumo, "cantidad": "2", "costo_unitario": "1100"}
        ],
        "remito": f"E2E-{clave[-6:]}",
    }
    primera = c.post(
        f"/api/purchases/orders/{oc['id']}/receipts",
        json=recepcion,
        headers={"Idempotency-Key": clave},
    )
    anotar(
        "4",
        "recepción parcial de 2 de 3",
        primera.status_code == 200
        and primera.json().get("estado") == "PARCIAL",
        primera.text[:200],
    )
    repetida = c.post(
        f"/api/purchases/orders/{oc['id']}/receipts",
        json=recepcion,
        headers={"Idempotency-Key": clave},
    )
    anotar(
        "4",
        "el reintento con la misma clave devuelve lo mismo sin duplicar",
        repetida.status_code == 200
        and len(repetida.json().get("recepciones", [])) == 1,
        f"HTTP {repetida.status_code}",
    )
    fisico1, _ = stock(c, insumo)
    anotar(
        "4",
        "el stock sube 2, una sola vez",
        fisico1 == fisico0 + 2,
        f"{fisico0} -> {fisico1}",
    )
    if primera.status_code == 200:
        linea = primera.json()["recepciones"][0]["lineas"][0]
        anotar(
            "4",
            "la diferencia de costo queda anotada",
            "1000" in (linea.get("diferencia") or ""),
            str(linea.get("diferencia")),
        )
    r = c.post(
        f"/api/purchases/orders/{oc['id']}/receipts",
        json={
            **recepcion,
            "lineas": [
                {
                    "insumo_id": insumo,
                    "cantidad": "2",
                    "costo_unitario": "1000",
                }
            ],
            "remito": None,
        },
    )
    anotar(
        "4",
        "no se recibe más de lo pendiente",
        rechazado(r),
        f"HTTP {r.status_code}",
    )
    final = f.ok(
        c.post(
            f"/api/purchases/orders/{oc['id']}/receipts",
            json={
                **recepcion,
                "lineas": [
                    {
                        "insumo_id": insumo,
                        "cantidad": "1",
                        "costo_unitario": "1000",
                    }
                ],
                "remito": None,
            },
        )
    )
    anotar(
        "4",
        "la OC queda RECIBIDA",
        final.get("estado") == "RECIBIDA",
        str(final.get("estado")),
    )
    costos = f.ok(c.get("/api/purchases/costs"))
    anotar(
        "4",
        "el costo real queda en el histórico",
        any(x["orden_compra_id"] == oc["id"] for x in costos),
        str(len(costos)),
    )
    fisico2, _ = stock(c, insumo)
    anotar(
        "4",
        "el stock subió 3 en total",
        fisico2 == fisico0 + 3,
        f"{fisico0} -> {fisico2}",
    )


@escenario("5. Lotes: el stock existente sigue sin lote")
def lotes(c, ctx):
    saldos = f.ok(c.get(f"/api/inventory/{ctx['insumo']}/lots"))
    anotar(
        "5",
        "BAT-IP14 sigue sin control por lote",
        saldos["control"] == "SIN_LOTE",
        saldos["control"],
    )
    anotar(
        "5",
        "sin lotes inventados",
        saldos["lotes"] == [],
        str(saldos["lotes"])[:200],
    )
    anotar(
        "5",
        "todo el físico es «sin lote identificado»",
        D(str(saldos["sin_lote_identificado"]))
        == D(str(saldos["stock_fisico"])),
        f"{saldos['sin_lote_identificado']} / {saldos['stock_fisico']}",
    )


@escenario("6. Catálogos operativos")
def catalogos(c, ctx):
    motivos = f.ok(
        c.get("/api/catalogs/reasons", params={"tipo": "CANCELACION"})
    )
    anotar(
        "6",
        "motivos de cancelación con «Otro»",
        any(m.get("requiere_descripcion") for m in motivos),
        str(len(motivos)),
    )
    parametros = f.ok(
        c.get("/api/admin/parameters", params={"usuario_id": f.ADMINISTRADOR})
    )
    valores = parametros.get("parametros", {})
    plazo = (
        valores.get("PLAZO_RETIRO_DIAS") if isinstance(valores, dict) else None
    )
    anotar(
        "6", "PLAZO_RETIRO_DIAS = 30", str(plazo) == "30", str(valores)[:200]
    )
    plantillas = f.ok(c.get("/api/communications/templates"))
    anotar(
        "6",
        "cinco plantillas de WhatsApp",
        len(plantillas.get("plantillas", [])) == 5,
        str(len(plantillas.get("plantillas", []))),
    )


@escenario("7. Identidad del equipo por IMEI")
def identidad(c, ctx):
    orden_id = base.crear_ficticia(c, imei=IMEI)
    r = f.ok(c.get("/api/equipment/identify", params={"imei": IMEI}))
    anotar(
        "7",
        "el IMEI identifica al equipo de la Orden",
        r.get("criterio") == "IMEI" and len(r.get("candidatos", [])) == 1,
        str(r)[:200],
    )
    anotar("7", "la Orden quedó creada", orden(c, orden_id)["id"] == orden_id)


def _reparada(c) -> str:
    """CLIENTE_EXTERNO ficticia, reparada y aprobada: lista para entregar."""
    orden_id = f.definida(c, f.BATERIA)
    f.tomada(c, orden_id)
    f.ejecutar(c, orden_id)
    f.ok(f.aprobar(c, orden_id, "DET-001"))
    return orden_id


@escenario(
    "8. Garantías: check-in corregido, garantía RMA y reclamo rechazado"
)
def garantias(c, ctx):
    # Check-in no realizado y su corrección con motivo (DEC-MI-05).
    origen = _reparada(c)
    f.ok(custodia.registrar_checkin(c, origen, realizado=False))
    sin_motivo = custodia.registrar_checkin(c, origen, realizado=True)
    anotar(
        "8",
        "corregir el check-in sin motivo se rechaza",
        rechazado(sin_motivo),
        f"HTTP {sin_motivo.status_code}",
    )
    corregida = f.ok(
        custodia.registrar_checkin(
            c, origen, realizado=True, motivo="E2E: se pudo probar el equipo."
        )
    )
    registros = corregida["recepcion"]["registros_checkin"]
    anotar(
        "8",
        "el check-in conserva las dos versiones y rige la corregida",
        [r["realizado"] for r in registros] == [False, True]
        and registros[-1]["motivo"] is not None
        and corregida["recepcion"]["datos"]["checkin"] is True,
        str([(r["realizado"], r["motivo"]) for r in registros]),
    )
    entregada = f.notificar_pagar_entregar(c, origen)
    anotar(
        "8",
        "la Orden se entrega",
        entregada["estado_workflow"] == "ENTREGADA",
        entregada["estado_workflow"],
    )
    # Garantía RMA dentro del plazo.
    r = it.iniciar_garantia(c, origen)
    anotar(
        "8",
        "garantía RMA vigente: se crea la Orden de garantía",
        r.status_code in (200, 201),
        r.text[:200],
    )
    if r.status_code in (200, 201):
        rma = r.json()
        base.creadas.append(rma["id"])
        anotar(
            "8",
            "la Orden de garantía referencia el trabajo de origen, vigente",
            (
                rma.get("origen"),
                rma.get("orden_origen_id"),
                rma.get("detalles_origen_ids"),
            )
            == ("RMA_GARANTIA_REPARACION", origen, ["DET-001"])
            and all(
                v["vigente"] for v in rma.get("vigencia_garantia_origen", [])
            ),
            str(
                (
                    rma.get("origen"),
                    rma.get("orden_origen_id"),
                    rma.get("detalles_origen_ids"),
                )
            ),
        )
    # Garantía en 0 días: sin garantía vigente, reclamo rechazado (DEC-MI-02).
    vencida = f.definida(c, f.BATERIA)
    ajuste = c.post(
        f"/api/orders/{vencida}/details/DET-001/warranty",
        json={
            "usuario_id": f.RECEPCION,
            "dias": 0,
            "motivo": "E2E: trabajo sin garantía.",
        },
    )
    anotar(
        "8",
        "Recepción fija el plazo del trabajo en 0 días",
        ajuste.status_code == 200,
        ajuste.text[:200],
    )
    f.tomada(c, vencida)
    f.ejecutar(c, vencida)
    f.ok(f.aprobar(c, vencida, "DET-001"))
    f.notificar_pagar_entregar(c, vencida)
    r = it.iniciar_garantia(c, vencida)
    error = r.json().get("error", {}) if r.status_code == 409 else {}
    reclamo = error.get("reclamo_id")
    anotar(
        "8",
        "sin garantía vigente se registra el reclamo rechazado",
        error.get("codigo") == "GARANTIA_VENCIDA" and bool(reclamo),
        r.text[:200],
    )
    if not reclamo:
        return
    detalle = f.ok(c.get(f"/api/warranty-claims/{reclamo}"))
    anotar(
        "8",
        "el reclamo queda RECHAZADO, de esa Orden",
        (detalle["resultado"], detalle["orden_origen_id"])
        == ("RECHAZADO", vencida),
        str((detalle["resultado"], detalle["orden_origen_id"])),
    )

    def continuar(usuario=f.RECEPCION, confirmado=True):
        return c.post(
            f"/api/warranty-claims/{reclamo}/continue",
            json={"usuario_id": usuario, "confirmado": confirmado},
        )

    anotar(
        "8",
        "continuar exige confirmarlo",
        rechazado(continuar(confirmado=False)),
    )
    anotar(
        "8",
        "Técnico no continúa un reclamo",
        rechazado(continuar(usuario=f.TECNICO)),
    )
    seguida = continuar()
    anotar(
        "8",
        "la continuación paga crea una Orden nueva",
        seguida.status_code in (200, 201),
        seguida.text[:200],
    )
    if seguida.status_code in (200, 201):
        base.creadas.append(seguida.json()["orden_id"])
        anotar("8", "se continúa una sola vez", rechazado(continuar()))


@escenario("9. Comunicaciones: WhatsApp asistido con confirmación manual")
def comunicaciones(c, ctx):
    orden_id = f.definida(c, f.BATERIA)
    preparado = f.ok(
        c.get(
            f"/api/orders/{orden_id}/messages/prepare",
            params={"plantilla": "INGRESO"},
        )
    )
    anotar(
        "9",
        "el mensaje se prepara completo para el teléfono del cliente",
        orden_id in preparado["mensaje"]
        and "{" not in preparado["mensaje"]
        and preparado["impedimento"] is None,
        str({k: preparado.get(k) for k in ("faltantes", "impedimento")}),
    )
    anotar(
        "9",
        "preparar no registra nada",
        orden(c, orden_id)["comunicaciones"] == [],
    )
    r = c.post(
        f"/api/orders/{orden_id}/messages",
        json={
            "usuario_id": f.TECNICO,
            "plantilla_codigo": "INGRESO",
            "mensaje": "E2E",
            "destinatario": preparado["destinatario"],
        },
    )
    anotar(
        "9",
        "Técnico no registra envíos",
        rechazado(r),
        f"HTTP {r.status_code}",
    )
    intento = f.ok(
        c.post(
            f"/api/orders/{orden_id}/messages",
            json={
                "usuario_id": f.RECEPCION,
                "plantilla_codigo": "INGRESO",
                "mensaje": "E2E: mensaje editado por Recepción.",
                "destinatario": preparado["destinatario"],
            },
        )
    )
    (comunicacion,) = intento["comunicaciones"]
    anotar(
        "9",
        "el intento queda registrado sin confirmar",
        comunicacion["confirmacion"] is None
        and comunicacion["usuario_id"] == f.RECEPCION,
    )
    ruta = f"/api/orders/{orden_id}/messages/{comunicacion['id']}/confirm"
    confirmada = f.ok(
        c.post(ruta, json={"usuario_id": f.RECEPCION, "enviado": True})
    )
    anotar(
        "9",
        "la confirmación manual queda registrada",
        confirmada["comunicaciones"][0]["confirmacion"]["enviado"] is True,
    )
    anotar(
        "9",
        "se confirma una sola vez",
        rechazado(
            c.post(ruta, json={"usuario_id": f.RECEPCION, "enviado": False})
        ),
    )
    texto = json.dumps(confirmada).upper().replace("FECHA_ENTREGA", "")
    anotar(
        "9",
        "nunca dice «entregado» ni «leído»",
        "ENTREGADO" not in texto and "LEIDO" not in texto,
    )


def cerrar_proveedor(c, ctx) -> None:
    """El proveedor ficticio queda inactivo (no admite borrado)."""
    proveedor = ctx.get("proveedor")
    if not proveedor:
        return
    r = c.put(
        f"/api/admin/suppliers/{proveedor['id']}",
        json={
            "usuario_id": f.ADMINISTRADOR,
            "nombre": PROVEEDOR,
            "telefono": "000-0000",
            "activo": False,
        },
    )
    anotar(
        "fin",
        "el proveedor ficticio queda inactivo",
        r.status_code == 200,
        f"HTTP {r.status_code}",
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
    p.add_argument(
        "--permitir-ordenes",
        action="store_true",
        help="solo en local: ensayar sobre una base que ya tiene Órdenes",
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
    if a.permitir_ordenes and not local:
        print("--permitir-ordenes solo se admite contra una API local.")
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
    ctx: dict = {"autenticado": tokens is not None}
    try:
        print("\nPrecondiciones:")
        if not a.permitir_ordenes and not base.ordenes_previas_coinciden(
            c, a.ordenes_previas
        ):
            print(
                "Las Órdenes existentes no son las declaradas: no se escribe nada."
            )
            return finalizar(a, 1)
        inventario = f.ok(c.get("/api/inventory"))
        bateria = [i for i in inventario if i.get("codigo") == "BAT-IP14"]
        if not anotar(
            "0",
            "insumo BAT-IP14 disponible",
            len(bateria) == 1,
            str([i.get("codigo") for i in inventario]),
        ):
            return finalizar(a, 1)
        ctx["insumo"] = bateria[0]["id"]
        ctx["stock_inicial"] = [str(x) for x in stock(c, ctx["insumo"])]
        fisico, reservado = stock(c, ctx["insumo"])
        anotar(
            "0",
            "stock suficiente para los escenarios (2 disponibles)",
            fisico - reservado >= 2,
            f"{fisico}/{reservado}",
        )
        if not a.escribir:
            print("\nSin --escribir: solo precondiciones.")
            return finalizar(
                a, 0 if all(x["ok"] for x in base.resultados) else 1
            )

        f.crear = base.crear_ficticia
        dc12_inactiva(c, ctx)
        roles_y_permisos(c, ctx)
        desperdicio_y_devolucion(c, ctx)
        compras(c, ctx)
        lotes(c, ctx)
        catalogos(c, ctx)
        identidad(c, ctx)
        garantias(c, ctx)
        comunicaciones(c, ctx)
        ctx["stock_final"] = [str(x) for x in stock(c, ctx["insumo"])]
    finally:
        try:
            cerrar_proveedor(c, ctx)
        finally:
            c.cerrar()
            if tokens:
                tokens.clear()
    print(f"\nÓrdenes creadas: {', '.join(base.creadas) or 'ninguna'}")
    print(f"Orden de compra: {ctx.get('orden_compra') or 'ninguna'}")
    print(
        f"Stock {ctx.get('insumo')}: inicial {ctx.get('stock_inicial')}, final {ctx.get('stock_final')}"
    )
    return finalizar(a, 0 if all(x["ok"] for x in base.resultados) else 1, ctx)


if __name__ == "__main__":
    sys.exit(main())
