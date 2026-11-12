"""Flujos HTTP de la iteracion 1 (alineacion con la baseline V1.4).

Los usan las pruebas de escenario (``test_iteracion1_v14.py``) y el corpus
de PostgreSQL (``tests/postgres/corpus_ordenes.py``): el mismo recorrido se
verifica en JSON y se guarda y relee en PostgreSQL.

* HP-REP-003: garantia RMA vigente (PROC-REP-036 "Vigente").
* VAR-REP-038: garantia vencida sin excepcion: no se crea la Orden
  (EVT-REP-998).
* VAR-REP-039: garantia vencida; solo con una excepcion autorizada.
* VAR-REP-041: cortesia total con pagos previos: saldo a favor, devolucion
  obligatoria y entrega bloqueada hasta devolver.
* VAR-REP-042: desistimiento con el Detalle en ejecucion: la solicitud, la
  interrupcion del tecnico y la cancelacion efectiva por separado.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from . import api_salidas as f

COORDINADOR = f.COORDINADOR
MOTIVO_EXCEPCION = "Falla de fabrica del repuesto; lo autoriza Coordinacion."
MOTIVO_CORTESIA = "Compensacion por la demora en la entrega."


class RelojDesplazado:
    """Reloj del contexto: la hora real corrida ``desplazamiento``."""

    def __init__(self) -> None:
        self.desplazamiento = timedelta(0)

    def __call__(self) -> datetime:
        return datetime.now(timezone.utc) + self.desplazamiento


def instalar_reloj(cliente: TestClient) -> RelojDesplazado:
    reloj = RelojDesplazado()
    app = cliente.app
    app.state.contexto = replace(app.state.contexto, ahora=reloj)
    return reloj


def entregada(cliente: TestClient, *tipos: str) -> str:
    """CLIENTE_EXTERNO definida, reparada, aprobada, cobrada y entregada."""
    tipos = tipos or (f.BATERIA,)
    orden_id = f.definida(cliente, *tipos)
    f.tomada(cliente, orden_id)
    for numero, tipo in enumerate(tipos, 1):
        f.ejecutar(cliente, orden_id, f"DET-{numero:03d}", tipo)
    for numero in range(1, len(tipos) + 1):
        f.ok(f.aprobar(cliente, orden_id, f"DET-{numero:03d}"))
    orden = f.notificar_pagar_entregar(cliente, orden_id)
    assert orden["estado_workflow"] == "ENTREGADA", orden["estado_workflow"]
    return orden_id


def entregada_hace(
    cliente: TestClient, reloj: RelojDesplazado, dias: int, *tipos: str
) -> str:
    """Como ``entregada`` pero con todo ocurrido hace ``dias`` dias."""
    reloj.desplazamiento = -timedelta(days=dias)
    try:
        return entregada(cliente, *tipos)
    finally:
        reloj.desplazamiento = timedelta(0)


def iniciar_garantia(
    cliente: TestClient,
    origen_id: str,
    detalle_origen_ids=("DET-001",),
    usuario: str = f.RECEPCION,
    motivo_excepcion: str | None = None,
):
    cuerpo = {
        "usuario_id": usuario,
        "detalle_origen_ids": list(detalle_origen_ids),
    }
    if motivo_excepcion is not None:
        cuerpo["motivo_excepcion"] = motivo_excepcion
    return cliente.post(f"/api/orders/{origen_id}/warranty-rma", json=cuerpo)


def ajuste_comercial(
    cliente: TestClient,
    orden_id: str,
    *,
    clase: str = "CORTESIA",
    tipo: str | None = "PORCENTAJE",
    valor: str | None = "100",
    usuario: str = f.ADMINISTRADOR,
    motivo: str = MOTIVO_CORTESIA,
):
    return cliente.post(
        f"/api/orders/{orden_id}/discount",
        json={
            "usuario_id": usuario,
            "clase": clase,
            "tipo": tipo,
            "valor": valor,
            "motivo": motivo,
        },
    )


def pagar(cliente: TestClient, orden_id: str, monto: str) -> dict:
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": f.RECEPCION,
                "monto": monto,
                "metodo": "EFECTIVO",
            },
        )
    )


def devolver_dinero(
    cliente: TestClient,
    orden_id: str,
    pago_id: str,
    monto: str,
    operacion_id: str = "it1-devolucion",
):
    return cliente.post(
        f"/api/orders/{orden_id}/refunds",
        json={
            "usuario_id": f.ADMINISTRADOR,
            "pago_id": pago_id,
            "monto": monto,
            "medio": "EFECTIVO",
            "motivo": "Cortesia total: se devuelve lo cobrado.",
            "operacion_id": operacion_id,
        },
    )


def desistir_detalle(
    cliente: TestClient,
    orden_id: str,
    detalle_id: str,
    motivo: str = "El cliente ya no quiere la reparacion.",
    canal: str = "TELEFONO",
    usuario: str = f.RECEPCION,
):
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/withdrawal",
        json={"usuario_id": usuario, "canal": canal, "motivo": motivo},
    )


def interrumpir(
    cliente: TestClient,
    orden_id: str,
    ejecucion_id: str,
    *,
    estado_trabajo: str | None = None,
    reversible: bool | None = None,
    insumos: list | None = None,
):
    cuerpo = {
        "usuario_id": f.TECNICO,
        "insumos_utilizados": insumos or [],
        "motivo": "El cliente desistio del trabajo.",
    }
    if estado_trabajo is not None:
        cuerpo["estado_trabajo"] = estado_trabajo
    if reversible is not None:
        cuerpo["reversible"] = reversible
    return cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/interrupt",
        json=cuerpo,
    )


# --- Recorridos completos (los usa tambien el corpus de PostgreSQL) ----------


def recorrido_garantia_vigente(
    cliente: TestClient, tipo: str = f.BATERIA
) -> str:
    """HP-REP-003 (036 "Si"): la garantia RMA de un Detalle vigente."""
    origen = entregada(cliente, tipo)
    return f.ok(iniciar_garantia(cliente, origen))["id"]


def recorrido_garantia_con_excepcion(
    cliente: TestClient, reloj: RelojDesplazado, tipo: str = f.BATERIA
) -> str:
    """VAR-REP-039: garantia vencida (entregada hace 200 dias, 90 o 60 de
    garantia) que Coordinacion autoriza como excepcion."""
    origen = entregada_hace(cliente, reloj, 200, tipo)
    return f.ok(
        iniciar_garantia(
            cliente,
            origen,
            usuario=COORDINADOR,
            motivo_excepcion=MOTIVO_EXCEPCION,
        )
    )["id"]


def recorrido_cortesia_con_pagos(
    cliente: TestClient, tipo: str = f.BATERIA
) -> str:
    """VAR-REP-041: anticipo, cortesia total, reparacion, devolucion del
    saldo a favor y entrega."""
    orden_id = f.definida(cliente, tipo)
    orden = pagar(cliente, orden_id, "30000")
    pago_id = orden["pagos"][-1]["id"]
    f.ok(ajuste_comercial(cliente, orden_id))
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id, "DET-001", tipo)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify",
            json={"usuario_id": f.RECEPCION},
        )
    )
    credito = -Decimal(orden["resumen"]["saldo"])
    assert credito == Decimal("30000")
    # El importe como lo escribe una persona (PostgreSQL no guarda los
    # ceros de mas: ver test_a3_un_importe_con_ceros_vuelve_sin_ellos).
    f.ok(devolver_dinero(cliente, orden_id, pago_id, "30000"))
    f.ok(f.entregar(cliente, orden_id, f.ADMINISTRADOR))
    return orden_id


def recorrido_desistimiento_en_ejecucion(
    cliente: TestClient, tipo: str = f.BATERIA
) -> str:
    """VAR-REP-042: solicitud de desistimiento con la Ejecucion en curso,
    interrupcion con el estado del trabajo y cancelacion efectiva; despues
    el circuito DC31 (devolver el equipo y cancelar la Orden)."""
    orden_id = f.definida(cliente, tipo)
    f.tomada(cliente, orden_id)
    ejecucion_id = f.iniciar(cliente, orden_id)
    f.ok(desistir_detalle(cliente, orden_id, "DET-001"))
    f.ok(
        interrumpir(
            cliente,
            orden_id,
            ejecucion_id,
            estado_trabajo="Equipo abierto; bateria sin reemplazar.",
            reversible=True,
        )
    )
    return orden_id
