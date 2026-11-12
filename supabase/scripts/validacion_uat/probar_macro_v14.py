# ruff: noqa: E501  (mensajes largos)
"""Validación funcional E2E de la macroiteración V1.4 en el UAT.

ESCRIBE en el UAT con datos FICTICIOS: crea Órdenes de prueba (cliente
«Cliente Ficticio E2E V14», teléfono 000-0000, IMEI de ejemplo), mueve stock
de prueba y cambia un precio y una Mesa de trabajo, que devuelve a su valor
original al terminar (también si falla una comprobación). No crea Tipos de
Reparación: ``tipo_reparacion`` no admite borrado y quedarían para siempre.
Los datos se eliminan después con el reinicio documentado
(``supabase/scripts/reinicio_uat/``), que es un paso aparte y autorizado.

Escenarios (los mismos recorridos que las pruebas automáticas, a través de
los helpers de ``app/backend/tests/fixtures``):

1. Evaluación técnica obligatoria, confirmación y trabajos adicionales.
2. Redefinición en la evaluación y descarte técnico.
3. Desistimiento total con una reparación activa (DC07C).
4. Antecedentes del equipo por IMEI y número de serie.
5. Reporte operativo.
6. Administración de Tipos de Reparación y de Mesas de trabajo.

Guardas: solo la API pública del UAT con el proyecto de São Paulo (o una API
local con ``--sin-autenticacion`` para ensayar); sin ``--escribir`` solo
verifica las precondiciones; si el UAT tiene Órdenes, no escribe nada.

    $env:SUPABASE_PUBLISHABLE_KEY = "<clave publicable de São Paulo>"
    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/probar_macro_v14.py --escribir --informe <archivo.json>

Pide las cuatro contraseñas sin eco, una sola vez, y las descarta después
de iniciar sesión. No imprime ni guarda tokens ni contraseñas: el informe
solo tiene los resultados y los códigos de las Órdenes creadas.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
import sys
import traceback
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "app" / "backend"))

import httpx  # noqa: E402

from tests.fixtures import api_salidas as f  # noqa: E402
from tests.fixtures import iteracion1 as it  # noqa: E402

API_UAT = "https://rt-rma-uat-api-nszqooxxla-rj.a.run.app"
SUPABASE_UAT = "https://pcdnmhzwhzymznojndrn.supabase.co"
DOMINIO = "usuarios.rma.invalid"
CUENTAS = {
    "recepcion": f.RECEPCION,
    "tecnico": f.TECNICO,
    "coordinacion": f.COORDINADOR,
    "administracion": f.ADMINISTRADOR,
}
CLIENTE = {
    "nombre_apellido": "Cliente Ficticio E2E V14",
    "telefono": "000-0000",
}
EQUIPO = {
    "marca": "Apple",
    "modelo": "iPhone 14",
    "falla_reportada": "E2E V14: no carga.",
}
IMEI = "490154203237518"
IMEI_CON_ESPACIOS = "49 0154 2032 37518"
IMEI_OTRO = "999999999999999"
SERIE = "E2EV14SERIE"
BATERIA, PLACA = "TR-001", "TR-002"
MESA = "EST-001"

resultados: list[dict] = []
creadas: list[str] = []


def anotar(escenario: str, nombre: str, ok: bool, detalle: str = "") -> bool:
    resultados.append(
        {
            "escenario": escenario,
            "comprobacion": nombre,
            "ok": bool(ok),
            "detalle": "" if ok else detalle[:300],
        }
    )
    print(
        f"  {'OK   ' if ok else 'FALLA'} {nombre}{(' - ' + detalle[:300]) if detalle and not ok else ''}"
    )
    return bool(ok)


class ClienteApi:
    """Lo mínimo de ``TestClient`` que usan los helpers, contra una API real.

    Cada pedido va con el token del usuario de su ``usuario_id`` (cuerpo o
    consulta): la API rechaza la suplantación, así que el actor del helper
    es también el de la sesión. Sin ``usuario_id`` usa ``como`` o Recepción.
    """

    def __init__(self, base: str, tokens: dict[str, str] | None) -> None:
        self._http = httpx.Client(base_url=base, timeout=90)
        self._tokens = tokens
        self._como: str | None = None

    @contextlib.contextmanager
    def como(self, usuario: str):
        anterior, self._como = self._como, usuario
        try:
            yield
        finally:
            self._como = anterior

    def _encabezados(self, json_, params, headers) -> dict:
        encabezados = dict(headers or {})
        if self._tokens is not None:
            usuario = (
                self._como
                or (json_ or {}).get("usuario_id")
                or (params or {}).get("usuario_id")
                or f.RECEPCION
            )
            encabezados["Authorization"] = f"Bearer {self._tokens[usuario]}"
        return encabezados

    def request(
        self,
        metodo,
        url,
        *,
        json=None,
        params=None,
        headers=None,
        content=None,
    ):
        return self._http.request(
            metodo,
            url,
            json=json,
            params=params,
            content=content,
            headers=self._encabezados(json, params, headers),
        )

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)

    def cerrar(self) -> None:
        self._tokens = None
        self._http.close()


def crear_ficticia(cliente, imei=None, serie=None) -> str:
    equipo = {**EQUIPO, "imei": imei, "numero_serie": serie}
    orden_id = f.ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": f.RECEPCION,
                "cliente": CLIENTE,
                "equipo": equipo,
            },
        )
    )["id"]
    creadas.append(orden_id)
    return orden_id


def orden(c, orden_id) -> dict:
    return f.ok(c.get(f"/api/orders/{orden_id}"))


def evaluar(
    c, orden_id, resultado, usuario=f.TECNICO, detalle="DET-001", **extra
):
    return c.post(
        f"/api/orders/{orden_id}/details/{detalle}/evaluation",
        json={"usuario_id": usuario, "resultado": resultado, **extra},
    )


def iniciar(c, orden_id, detalle="DET-001"):
    return c.post(
        f"/api/orders/{orden_id}/details/{detalle}/start",
        json={"usuario_id": f.TECNICO},
    )


def adicional(c, orden_id, tipo=PLACA, usuario=f.TECNICO):
    return c.post(
        f"/api/orders/{orden_id}/details/additional",
        json={"usuario_id": usuario, "tipo_reparacion_id": tipo},
    )


def pasos(o) -> list[str]:
    return [p["referencia_id"] for p in o["historial"]]


def rechazado(r) -> bool:
    """Rechazo de negocio o de permisos, sin cambios."""
    return r.status_code in (403, 409)


def stock(c, insumo: str) -> tuple[Decimal, Decimal]:
    for i in f.ok(c.get("/api/inventory")):
        if i["id"] == insumo:
            return Decimal(str(i["stock_fisico"])), Decimal(
                str(i["reservado"])
            )
    raise AssertionError(f"Insumo {insumo} inexistente")


def escenario(nombre: str):
    def decorar(funcion):
        def correr(*args):
            print(f"\n{nombre}")
            try:
                funcion(*args)
            except (
                Exception
            ) as error:  # una falla no frena los demás escenarios
                anotar(
                    nombre,
                    "el escenario terminó sin errores",
                    False,
                    f"{type(error).__name__}: {error}",
                )
                traceback.print_exc(limit=2, file=sys.stdout)

        return correr

    return decorar


# --- Escenarios -----------------------------------------------------------------


@escenario("1. Evaluación técnica obligatoria, confirmación y adicionales")
def evaluacion_y_adicionales(c, ctx):
    e = "1"
    a = f.definida(c, BATERIA)
    f.tomada(c, a)
    ctx["orden_evaluada"] = a
    o = orden(c, a)
    d = f.detalle(o, "DET-001")
    anotar(
        e,
        f"{a}: el trabajo de Recepción exige evaluación",
        d["origen_diagnostico"] == "RECEPCION"
        and d["requiere_evaluacion"] is True,
        str(d.get("origen_diagnostico")),
    )
    codigos = f.codigos(o)
    anotar(
        e,
        "se ofrece EVALUAR y no INICIAR",
        "EVALUAR_DETALLE" in codigos and "INICIAR_DETALLE" not in codigos,
        str(codigos),
    )
    r = iniciar(c, a)
    anotar(
        e,
        "iniciar sin evaluación es rechazado",
        r.status_code == 409 and "evaluacion" in r.text.lower(),
        f"HTTP {r.status_code}",
    )
    r = evaluar(c, a, "CONFIRMADO", usuario=f.RECEPCION)
    anotar(
        e, "Recepción no puede evaluar", rechazado(r), f"HTTP {r.status_code}"
    )
    antes = stock(c, ctx["insumo"])
    o = f.ok(
        evaluar(
            c,
            a,
            "CONFIRMADO",
            adicionales=[
                {"tipo_reparacion_id": PLACA, "observaciones": "E2E V14."}
            ],
        )
    )
    d1, d2 = f.detalle(o, "DET-001"), f.detalle(o, "DET-002")
    anotar(
        e,
        "CONFIRMADO del técnico titular",
        d1["evaluaciones"][-1]["resultado"] == "CONFIRMADO"
        and d1["evaluaciones"][-1]["usuario_id"] == f.TECNICO
        and d1["requiere_evaluacion"] is False,
    )
    anotar(
        e,
        "adicional de la evaluación: Detalle del técnico pendiente del cliente",
        d2["origen_diagnostico"] == "REVISION_TECNICA"
        and d2["estado_autorizacion"] == "PENDIENTE"
        and d2["tipo_reparacion_id"] == PLACA,
    )
    anotar(
        e,
        "la evaluación no reserva ni consume",
        o["ejecuciones"] == [] and stock(c, ctx["insumo"]) == antes,
        str(stock(c, ctx["insumo"])),
    )
    anotar(
        e,
        "historial 182 -> 183 -> 184 -> 128",
        all(
            p in pasos(o)
            for p in (
                "PROC-REP-182",
                "PROC-REP-183",
                "PROC-REP-184",
                "PROC-REP-128",
            )
        ),
    )
    ejecucion = f.iniciar(c, a)
    anotar(
        e,
        "con la evaluación se inicia y reserva",
        stock(c, ctx["insumo"]) == (antes[0], antes[1] + 1),
        str(stock(c, ctx["insumo"])),
    )
    o = orden(c, a)
    anotar(
        e,
        "AGREGAR_TRABAJO_ADICIONAL disponible durante la ejecución",
        "AGREGAR_TRABAJO_ADICIONAL"
        in [x["codigo"] for x in o["acciones_complementarias"]],
    )
    r = adicional(c, a, usuario=f.RECEPCION)
    anotar(
        e,
        "Recepción no registra adicionales",
        rechazado(r),
        f"HTTP {r.status_code}",
    )
    o = f.ok(adicional(c, a))
    d3 = f.detalle(o, "DET-003")
    anotar(
        e,
        "adicional durante la ejecución, sin interrumpirla",
        d3["estado_autorizacion"] == "PENDIENTE"
        and [x["estado"] for x in o["ejecuciones"]] == ["EN_PROGRESO"]
        and o["historial"][-1]["referencia_id"] == "PROC-REP-128",
    )
    f.ok(f.cerrar_ejecucion(c, a, ejecucion, insumo=ctx["insumo"]))
    anotar(
        e,
        "al completar se consume el insumo",
        stock(c, ctx["insumo"]) == (antes[0] - 1, antes[1]),
        str(stock(c, ctx["insumo"])),
    )


@escenario("2. Redefinición en la evaluación y descarte técnico")
def redefinicion_y_descarte(c, ctx):
    e = "2"
    b = f.definida(c, BATERIA)
    f.tomada(c, b)
    r = evaluar(c, b, "REQUIERE_REDEFINICION", observaciones="E2E V14.")
    anotar(
        e,
        "redefinir sin el nuevo Tipo es rechazado",
        r.status_code == 409,
        f"HTTP {r.status_code}",
    )
    r = evaluar(c, b, "REQUIERE_REDEFINICION", tipo_reparacion_id=PLACA)
    anotar(
        e,
        "redefinir sin motivo es rechazado",
        r.status_code == 409,
        f"HTTP {r.status_code}",
    )
    o = f.ok(
        evaluar(
            c,
            b,
            "REQUIERE_REDEFINICION",
            observaciones="E2E V14: es la placa.",
            tipo_reparacion_id=PLACA,
        )
    )
    d = f.detalle(o, "DET-001")
    anotar(
        e,
        f"{b}: redefinido por el técnico (v2, TR-002)",
        d["tipo_reparacion_id"] == PLACA
        and d["version_definicion"] == 2
        and d["origen_diagnostico"] == "REVISION_TECNICA"
        and d["requiere_evaluacion"] is False,
    )
    anotar(
        e,
        "vuelve a la autorización del cliente (127 -> 129)",
        d["estado_autorizacion"] == "PENDIENTE"
        and "PROC-REP-127" in pasos(o)
        and o["current_process"] == "PROC-REP-129",
        o["current_process"],
    )
    r = iniciar(c, b)
    anotar(
        e,
        "no se inicia sin la nueva autorización",
        r.status_code == 409,
        f"HTTP {r.status_code}",
    )
    o = f.ok(f.decidir(c, b, {"DET-001": "AUTORIZADO"}))
    if o.get("toma_activa") is None:
        if o["estado_workflow"] != "EN_COLA":
            f.ok(f.encolar(c, b, 3))
        f.tomar(c, b)
    r = iniciar(c, b)
    anotar(
        e,
        "autorizada, se inicia sin otra evaluación",
        r.status_code == 200,
        f"HTTP {r.status_code} {r.text[:150]}",
    )
    if r.status_code == 200:
        (activa,) = [
            x for x in r.json()["ejecuciones"] if x["estado"] == "EN_PROGRESO"
        ]
        f.ok(f.cerrar_ejecucion(c, b, activa["id"], cantidad=None))
    ctx["orden_redefinida"] = b
    ctx["precio_redefinida"] = f.detalle(orden(c, b), "DET-001")["precio"]

    x = f.definida(c, BATERIA)
    f.tomada(c, x)
    r = evaluar(c, x, "DESCARTADO")
    anotar(
        e,
        "descartar sin motivo es rechazado",
        r.status_code == 409,
        f"HTTP {r.status_code}",
    )
    o = f.ok(
        evaluar(
            c, x, "DESCARTADO", observaciones="E2E V14: falla de software."
        )
    )
    d = f.detalle(o, "DET-001")
    anotar(
        e,
        f"{x}: descarte técnico cancela el trabajo",
        d["estado"] == "CANCELADO"
        and d["cancelacion"]["origen"] == "DESCARTE_TECNICO"
        and d["cancelacion"]["usuario_id"] == f.TECNICO,
    )
    anotar(
        e,
        "la Orden queda abierta sin trabajos vigentes (307)",
        o["estado_workflow"] != "CANCELADA"
        and o["current_process"] == "PROC-REP-307",
        o["current_process"],
    )
    f.ok(f.devolver(c, x, recibido_por="Cliente Ficticio E2E V14"))
    anotar(
        e,
        "devolución y cancelación de la Orden",
        f.ok(f.cancelar_orden(c, x, motivo="E2E V14: prueba."))[
            "estado_workflow"
        ]
        == "CANCELADA",
    )


@escenario("3. Desistimiento total con reparación activa (DC07C)")
def desistimiento_total(c, ctx):
    e = "3"
    d = f.definida(c, BATERIA, PLACA)
    f.tomada(c, d)
    antes = stock(c, ctx["insumo"])
    ejecucion = f.iniciar(c, d, "DET-001")
    analisis = orden(c, d)["desistimiento"]
    anotar(
        e,
        f"{d}: análisis con DET-001 en ejecución",
        analisis["en_ejecucion"] == ["DET-001"]
        and analisis["bloqueantes"] == [],
        str(analisis)[:150],
    )
    cuerpo = {
        "usuario_id": f.RECEPCION,
        "canal": "TELEFONO",
        "motivo": "E2E V14: el cliente desiste.",
    }
    o = f.ok(c.post(f"/api/orders/{d}/withdrawal", json=cuerpo))
    anotar(
        e,
        "la solicitud queda en cada trabajo, sin cancelar todavía",
        all(
            f.detalle(o, x)["solicitud_desistimiento"]["usuario_id"]
            == f.RECEPCION
            and f.detalle(o, x)["cancelacion"] is None
            for x in ("DET-001", "DET-002")
        )
        and o["ejecuciones"][0]["estado"] == "EN_PROGRESO",
    )
    r = c.post(f"/api/orders/{d}/withdrawal", json=cuerpo)
    anotar(
        e,
        "no se duplica la solicitud",
        r.status_code == 409,
        f"HTTP {r.status_code}",
    )
    anotar(
        e,
        "el técnico ya no puede completar",
        "COMPLETAR_EJECUCION" not in f.codigos(orden(c, d)),
    )
    o = f.ok(
        it.interrumpir(
            c,
            d,
            ejecucion,
            estado_trabajo="E2E V14: equipo abierto, sin cambios.",
            reversible=True,
        )
    )
    anotar(
        e,
        "al interrumpir se cancelan juntos (211 -> 305)",
        all(
            f.detalle(o, x)["estado"] == "CANCELADO"
            and f.detalle(o, x)["cancelacion"]["origen"]
            == "DESISTIMIENTO_CLIENTE"
            for x in ("DET-001", "DET-002")
        )
        and "PROC-REP-305" in pasos(o),
    )
    anotar(
        e,
        "la reserva se libera sin consumo",
        stock(c, ctx["insumo"]) == antes,
        str(stock(c, ctx["insumo"])),
    )
    anotar(
        e,
        "DC31: la Orden sigue abierta (307)",
        o["current_process"] == "PROC-REP-307",
        o["current_process"],
    )
    f.ok(f.devolver(c, d, recibido_por="Cliente Ficticio E2E V14"))
    anotar(
        e,
        "devolución y cancelación de la Orden",
        f.ok(f.cancelar_orden(c, d, motivo="E2E V14: prueba."))[
            "estado_workflow"
        ]
        == "CANCELADA",
    )


@escenario("4. Antecedentes del equipo")
def antecedentes(c, ctx):
    e = "4"
    primera = crear_ficticia(c, IMEI, SERIE)
    segunda = crear_ficticia(c, IMEI_CON_ESPACIOS)
    otra = crear_ficticia(c, IMEI_OTRO)
    r = f.ok(
        c.get(
            "/api/equipment/history",
            params={"imei": IMEI, "excluir_orden_id": segunda},
        )
    )
    anotar(
        e,
        f"por IMEI (con espacios) encuentra solo {primera}",
        [x["orden_id"] for x in r["ordenes"]] == [primera]
        and r["ordenes"][0]["coincide_por"] == ["IMEI"],
        str([x["orden_id"] for x in r["ordenes"]]),
    )
    anotar(
        e,
        f"no mezcla otro equipo ({otra})",
        otra not in [x["orden_id"] for x in r["ordenes"]],
    )
    s = f.ok(
        c.get("/api/equipment/history", params={"numero_serie": SERIE.lower()})
    )
    anotar(
        e,
        "por número de serie, sin distinguir mayúsculas",
        [x["orden_id"] for x in s["ordenes"]] == [primera],
    )
    v = f.ok(c.get("/api/equipment/history"))
    anotar(
        e,
        "sin identificación no busca",
        v["sin_identificacion"] is True and v["ordenes"] == [],
    )
    claves = {
        "orden_id",
        "origen",
        "estado_workflow",
        "creada_en",
        "entregada_en",
        "falla_reportada",
        "orden_origen_id",
        "trabajos",
        "coincide_por",
    }
    anotar(
        e,
        "sin datos personales del cliente",
        set(r["ordenes"][0]) == claves
        and CLIENTE["nombre_apellido"] not in json.dumps(r)
        and CLIENTE["telefono"] not in json.dumps(r),
    )
    with c.como(f.TECNICO):
        anotar(
            e,
            "otro rol autenticado también consulta",
            c.get("/api/equipment/history", params={"imei": IMEI}).status_code
            == 200,
        )


@escenario("5. Reporte operativo")
def reporte(c, ctx):
    e = "5"
    with c.como(f.ADMINISTRADOR):
        rep = f.ok(c.get("/api/reports/operational"))
    total = sum(rep["ordenes_por_origen"].values())
    anotar(
        e,
        f"cuenta las {len(creadas)} Órdenes de la prueba",
        total == len(creadas),
        f"{total}",
    )
    anotar(
        e,
        "2 Órdenes canceladas",
        rep["ordenes_por_estado"].get("CANCELADA") == 2,
        str(rep["ordenes_por_estado"]),
    )
    tecnicos = {t["usuario_id"]: t for t in rep["trabajos_por_tecnico"]}
    anotar(
        e,
        "TECH-001 con 2 trabajos completados",
        tecnicos.get(f.TECNICO, {}).get("completadas") == 2,
        str(tecnicos)[:200],
    )
    consumo = {
        x["insumo_id"]: Decimal(str(x["cantidad"]))
        for x in rep["consumo_insumos"]
    }
    anotar(
        e,
        "consumo de 1 unidad del insumo de batería",
        consumo.get(ctx["insumo"]) == 1,
        str(consumo),
    )
    pendientes = [p["orden_id"] for p in rep["pendientes"]]
    anotar(
        e,
        "pendientes: la evaluada sí, las canceladas no",
        ctx.get("orden_evaluada") in pendientes
        and not set(pendientes) & set(ctx.get("canceladas", [])),
        str(pendientes),
    )
    texto = json.dumps(rep)
    anotar(
        e,
        "sin datos personales del cliente",
        CLIENTE["nombre_apellido"] not in texto
        and CLIENTE["telefono"] not in texto,
    )


@escenario("6. Administración de Tipos de Reparación y Mesas de trabajo")
def administracion(c, ctx):
    e = "6"
    if ctx["autenticado"]:
        for usuario in (f.RECEPCION, f.TECNICO, f.COORDINADOR):
            with c.como(usuario):
                r = c.get("/api/admin/catalog")
            anotar(
                e,
                f"{usuario} no ve la administración (403)",
                r.status_code == 403,
                f"HTTP {r.status_code}",
            )
    with c.como(f.ADMINISTRADOR):
        catalogo = f.ok(c.get("/api/admin/catalog"))
    anotar(
        e, "Administración: catálogo editable", catalogo["editable"] is True
    )
    tipo = next(t for t in catalogo["tipos"] if t["id"] == PLACA)
    mesa = next(m for m in catalogo["mesas"] if m["id"] == MESA)
    original = {
        k: tipo[k]
        for k in ("nombre", "precio", "puntaje", "garantia_dias", "activo")
    }
    tipos_mesa = list(mesa["tipos"])
    ctx["catalogo_original"] = {"tipo": original, "mesa": tipos_mesa}

    def editar(usuario, **cambios):
        return c.put(
            f"/api/admin/repair-types/{PLACA}",
            json={"usuario_id": usuario, **original, **cambios},
        )

    def mesa_con(usuario, tipos):
        return c.put(
            f"/api/admin/stations/{MESA}/repair-types",
            json={"usuario_id": usuario, "tipos": tipos},
        )

    nuevo_precio = str(Decimal(str(original["precio"])) + 5000)
    try:
        # Con sesión real lo rechaza el control de rol de la API (403); en el
        # ensayo local sin sesión, la regla del servicio (409).
        sin_permiso = 403 if ctx["autenticado"] else 409
        r = editar(f.RECEPCION, precio=nuevo_precio)
        anotar(
            e,
            f"Recepción no edita Tipos ({sin_permiso})",
            r.status_code == sin_permiso,
            f"HTTP {r.status_code}",
        )
        r = editar(f.ADMINISTRADOR)
        anotar(
            e,
            "una edición sin cambios es rechazada",
            r.status_code == 409,
            f"HTTP {r.status_code}",
        )
        for codigo in ("TR-OTROS", BATERIA):
            r = c.post(
                "/api/admin/repair-types",
                json={
                    "usuario_id": f.ADMINISTRADOR,
                    "codigo": codigo,
                    **original,
                },
            )
            anotar(
                e,
                f"alta con el código {codigo} es rechazada sin crear nada",
                r.status_code == 409,
                f"HTTP {r.status_code}",
            )
        f.ok(editar(f.ADMINISTRADOR, precio=nuevo_precio))
        with c.como(f.ADMINISTRADOR):
            cambios = f.ok(
                c.get(
                    "/api/admin/config-changes",
                    params={"entidad": "TIPO_REPARACION", "clave": PLACA},
                )
            )
        ultimo = cambios[-1] if cambios else {}
        anotar(
            e,
            f"cambio de precio auditado ({original['precio']} -> {nuevo_precio})",
            ultimo.get("campo") == "precio"
            and Decimal(ultimo.get("valor_anterior") or "-1")
            == Decimal(str(original["precio"]))
            and Decimal(ultimo.get("valor_nuevo") or "-1")
            == Decimal(nuevo_precio)
            and ultimo.get("usuario_id") == f.ADMINISTRADOR,
            str(ultimo),
        )
        if ctx.get("orden_redefinida"):
            precio = f.detalle(orden(c, ctx["orden_redefinida"]), "DET-001")[
                "precio"
            ]
            anotar(
                e,
                "lo ya registrado conserva su precio (BR-REP-015)",
                Decimal(str(precio)) == Decimal(str(ctx["precio_redefinida"])),
                str(precio),
            )
        r = mesa_con(f.TECNICO, [BATERIA])
        anotar(
            e,
            f"el técnico no configura Mesas ({sin_permiso})",
            r.status_code == sin_permiso,
            f"HTTP {r.status_code}",
        )
        r = mesa_con(f.ADMINISTRADOR, ["TR-999"])
        anotar(
            e,
            "un Tipo inexistente es rechazado",
            r.status_code == 409,
            f"HTTP {r.status_code}",
        )
        f.ok(mesa_con(f.ADMINISTRADOR, [BATERIA]))
        with c.como(f.ADMINISTRADOR):
            mesa_ahora = next(
                m
                for m in f.ok(c.get("/api/admin/catalog"))["mesas"]
                if m["id"] == MESA
            )
            cambios_mesa = f.ok(
                c.get(
                    "/api/admin/config-changes",
                    params={"entidad": "MESA_TRABAJO", "clave": MESA},
                )
            )
        anotar(
            e,
            f"{MESA} queda solo con {BATERIA}",
            mesa_ahora["tipos"] == [BATERIA],
            str(mesa_ahora["tipos"]),
        )
        anotar(
            e,
            "el cambio de la Mesa queda auditado",
            bool(cambios_mesa)
            and cambios_mesa[-1]["campo"] == "tipos_habilitados",
            str(cambios_mesa[-1:]),
        )
    finally:
        restaurar_catalogo(c, ctx)


def restaurar_catalogo(c, ctx) -> None:
    original = ctx.get("catalogo_original")
    if not original:
        return
    print("\n  Restauración del catálogo:")
    with c.como(f.ADMINISTRADOR):
        actual = f.ok(c.get("/api/admin/catalog"))
    tipo = next(t for t in actual["tipos"] if t["id"] == PLACA)
    if any(str(tipo[k]) != str(v) for k, v in original["tipo"].items()):
        r = c.put(
            f"/api/admin/repair-types/{PLACA}",
            json={"usuario_id": f.ADMINISTRADOR, **original["tipo"]},
        )
        anotar(
            "6",
            f"precio de {PLACA} restaurado",
            r.status_code == 200,
            f"HTTP {r.status_code}",
        )
    mesa = next(m for m in actual["mesas"] if m["id"] == MESA)
    if mesa["tipos"] != original["mesa"]:
        r = c.put(
            f"/api/admin/stations/{MESA}/repair-types",
            json={"usuario_id": f.ADMINISTRADOR, "tipos": original["mesa"]},
        )
        anotar(
            "6",
            f"Tipos de {MESA} restaurados",
            r.status_code == 200,
            f"HTTP {r.status_code}",
        )
    with c.como(f.ADMINISTRADOR):
        final = f.ok(c.get("/api/admin/catalog"))
    tipo = next(t for t in final["tipos"] if t["id"] == PLACA)
    mesa = next(m for m in final["mesas"] if m["id"] == MESA)
    anotar(
        "6",
        "catálogo igual al inicial",
        all(str(tipo[k]) == str(v) for k, v in original["tipo"].items())
        and mesa["tipos"] == original["mesa"],
        f"{tipo} {mesa}",
    )


# --- Principal ----------------------------------------------------------------


def iniciar_sesiones(
    supabase: str, publicable: str, api: str
) -> dict[str, str] | None:
    tokens: dict[str, str] = {}
    contrasenas = {
        u: getpass.getpass(f"Contraseña de '{u}' (no se muestra): ")
        for u in CUENTAS
    }
    print("\nSesiones:")
    for usuario, codigo in CUENTAS.items():
        r = httpx.post(
            f"{supabase}/auth/v1/token?grant_type=password",
            json={
                "email": f"{usuario}@{DOMINIO}",
                "password": contrasenas[usuario],
            },
            headers={"apikey": publicable},
            timeout=60,
        )
        token = r.json().get("access_token") if r.status_code == 200 else None
        yo = (
            httpx.get(
                f"{api}/api/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=60,
            )
            if token
            else None
        )
        ok = bool(
            yo is not None and yo.status_code == 200 and codigo in yo.text
        )
        anotar(
            "0",
            f"inicio de sesión de {usuario} y /api/me = {codigo}",
            ok,
            f"Auth HTTP {r.status_code}, /api/me HTTP {yo.status_code if yo is not None else '-'}",
        )
        if ok:
            tokens[codigo] = token
    contrasenas.clear()
    return tokens if len(tokens) == len(CUENTAS) else None


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
    ctx: dict = {"autenticado": tokens is not None}
    try:
        print("\nPrecondiciones:")
        ordenes = f.ok(c.get("/api/orders"))
        if not anotar(
            "0", f"el UAT no tiene Órdenes (hay {len(ordenes)})", ordenes == []
        ):
            print("Hay Órdenes: no se escribe nada.")
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
        tipos = {t["id"] for t in f.ok(c.get("/api/catalogs/repair-types"))}
        anotar(
            "0",
            "Tipos TR-001 y TR-002 en el catálogo",
            {BATERIA, PLACA} <= tipos,
            str(sorted(tipos)),
        )
        if not a.escribir:
            print("\nSin --escribir: solo precondiciones.")
            return finalizar(a, 0 if all(x["ok"] for x in resultados) else 1)

        f.crear = crear_ficticia  # los helpers crean con los datos ficticios
        evaluacion_y_adicionales(c, ctx)
        redefinicion_y_descarte(c, ctx)
        desistimiento_total(c, ctx)
        ctx["canceladas"] = [
            o["id"]
            for o in f.ok(c.get("/api/orders"))
            if o.get("estado_workflow") == "CANCELADA"
        ]
        antecedentes(c, ctx)
        reporte(c, ctx)
        administracion(c, ctx)
        ctx["stock_final"] = [str(x) for x in stock(c, ctx["insumo"])]
    finally:
        c.cerrar()
        if tokens:
            tokens.clear()
    print(f"\nÓrdenes creadas: {', '.join(creadas) or 'ninguna'}")
    print(
        f"Stock {ctx.get('insumo')}: inicial {ctx.get('stock_inicial')}, final {ctx.get('stock_final')}"
    )
    return finalizar(a, 0 if all(x["ok"] for x in resultados) else 1, ctx)


def finalizar(a, codigo: int, ctx: dict | None = None) -> int:
    fallas = [x for x in resultados if not x["ok"]]
    print(
        f"\nRESULTADO: {'OK' if not fallas else f'{len(fallas)} FALLAS'} ({len(resultados)} comprobaciones)"
    )
    if a.informe:
        datos = {
            "api": a.api,
            "comprobaciones": resultados,
            "ordenes_creadas": creadas,
            "stock": {
                k: (ctx or {}).get(k)
                for k in ("insumo", "stock_inicial", "stock_final")
            },
            "catalogo_original": (ctx or {}).get("catalogo_original"),
        }
        Path(a.informe).write_text(
            json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return codigo


if __name__ == "__main__":
    sys.exit(main())
