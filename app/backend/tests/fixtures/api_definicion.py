"""Definicion de Detalles por HTTP, encadenada como la hace la UI.

Agregar un Detalle (``POST .../details`` o ``POST .../review/details``) y
finalizar la definicion (``POST .../definition/finalize``) son dos
intenciones distintas, con dos endpoints. Los tests que solo necesitan una
Orden ya definida usan estos atajos; los que prueban la separacion llaman a
cada endpoint por separado.

En CLIENTE_EXTERNO, finalizar deja los Detalles pendientes de autorizacion
del cliente (BR-REP-028): nada se ejecuta sin ella. Por eso los atajos, por
defecto, registran ademas la autorizacion del cliente con el endpoint real
(``POST .../authorizations``), como lo haria Recepcion. No es una
autorizacion implicita: es una llamada explicita, visible en el historial
(PROC-REP-046/047). ``autorizar=False`` deja los Detalles pendientes.

Tambien confirman la recepcion fisica del equipo antes de definir:
sin custodia confirmada no se inicia ninguna Ejecucion, y estos atajos
preparan Ordenes que van a ejecutarse. Es la confirmacion explicita de
Recepcion (``POST .../reception/confirm``), no una custodia presumida.
"""

from typing import Any

from fastapi.testclient import TestClient
from httpx import Response

from .custodia import confirmar_recepcion

RECEPCION_ID = "RECEP-001"


def finalizar_definicion(
    cliente: TestClient, orden_id: str, usuario_id: str
) -> Response:
    """``POST /api/orders/{orden_id}/definition/finalize``."""
    return cliente.post(
        f"/api/orders/{orden_id}/definition/finalize",
        json={"usuario_id": usuario_id},
    )


def registrar_decision(
    cliente: TestClient,
    orden_id: str,
    decisiones: dict[str, str],
    *,
    usuario_id: str = RECEPCION_ID,
    canal: str = "PRESENCIAL",
    observaciones: str | None = None,
) -> Response:
    """``POST /api/orders/{orden_id}/authorizations``.

    ``decisiones``: ``{detalle_id: "AUTORIZADO" | "RECHAZADO"}``, sobre la
    definicion vigente de cada Detalle (se lee de la Orden).
    """
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    versiones = {
        detalle["id"]: detalle["version_definicion"]
        for detalle in orden["reparaciones_detail"]
    }
    return cliente.post(
        f"/api/orders/{orden_id}/authorizations",
        json={
            "usuario_id": usuario_id,
            "canal": canal,
            "observaciones": observaciones,
            "decisiones": [
                {
                    "detalle_id": detalle_id,
                    "version_definicion": versiones.get(detalle_id, 1),
                    "resultado": resultado,
                }
                for detalle_id, resultado in decisiones.items()
            ],
        },
    )


def autorizar_pendientes(
    cliente: TestClient,
    orden_id: str,
    respuesta: Response,
) -> Response:
    """El cliente autoriza todos los Detalles pendientes, si corresponde.

    Solo si la Orden ofrece registrar la decision (``acciones_autorizacion``
    con REGISTRAR_DECISION_CLIENTE); si no -otro Origen, o nada pendiente-,
    devuelve ``respuesta`` tal cual.
    """
    if respuesta.status_code != 200:
        return respuesta
    orden = respuesta.json()
    if not any(
        accion["codigo"] == "REGISTRAR_DECISION_CLIENTE"
        for accion in orden.get("acciones_autorizacion", [])
    ):
        return respuesta
    pendientes = {
        detalle["id"]: "AUTORIZADO"
        for detalle in orden["reparaciones_detail"]
        if detalle["estado_autorizacion"] == "PENDIENTE"
    }
    return registrar_decision(cliente, orden_id, pendientes)


def definir_y_finalizar(
    cliente: TestClient,
    orden_id: str,
    json: dict[str, Any],
    *,
    autorizar: bool = True,
) -> Response:
    """Agrega UN Detalle, finaliza la definicion y (CLIENTE_EXTERNO) autoriza.

    Si agregar el Detalle falla, devuelve esa respuesta sin finalizar.
    """
    confirmar_recepcion(cliente, orden_id)
    agregado = cliente.post(f"/api/orders/{orden_id}/details", json=json)
    if agregado.status_code != 200:
        return agregado
    finalizada = finalizar_definicion(cliente, orden_id, json["usuario_id"])
    if not autorizar:
        return finalizada
    return autorizar_pendientes(cliente, orden_id, finalizada)


def definir_desde_revision_y_finalizar(
    cliente: TestClient,
    orden_id: str,
    json: dict[str, Any],
    *,
    autorizar: bool = True,
) -> Response:
    """Agrega UN Detalle luego de la revision (075), finaliza y autoriza.

    Si agregar el Detalle falla, devuelve esa respuesta sin finalizar.
    """
    confirmar_recepcion(cliente, orden_id)
    agregado = cliente.post(
        f"/api/orders/{orden_id}/review/details", json=json
    )
    if agregado.status_code != 200:
        return agregado
    finalizada = finalizar_definicion(cliente, orden_id, json["usuario_id"])
    if not autorizar:
        return finalizada
    return autorizar_pendientes(cliente, orden_id, finalizada)
