"""Definicion de Detalles por HTTP, encadenada como la hace la UI.

Agregar un Detalle (``POST .../details`` o ``POST .../review/details``) y
finalizar la definicion (``POST .../definition/finalize``) son dos
intenciones distintas, con dos endpoints. Los tests que solo necesitan una
Orden ya definida usan estos atajos; los que prueban la separacion llaman a
cada endpoint por separado.
"""

from typing import Any

from fastapi.testclient import TestClient
from httpx import Response


def finalizar_definicion(
    cliente: TestClient, orden_id: str, usuario_id: str
) -> Response:
    """``POST /api/orders/{orden_id}/definition/finalize``."""
    return cliente.post(
        f"/api/orders/{orden_id}/definition/finalize",
        json={"usuario_id": usuario_id},
    )


def definir_y_finalizar(
    cliente: TestClient, orden_id: str, json: dict[str, Any]
) -> Response:
    """Agrega UN Detalle y finaliza la definicion.

    Si agregar el Detalle falla, devuelve esa respuesta sin finalizar.
    """
    agregado = cliente.post(f"/api/orders/{orden_id}/details", json=json)
    if agregado.status_code != 200:
        return agregado
    return finalizar_definicion(cliente, orden_id, json["usuario_id"])


def definir_desde_revision_y_finalizar(
    cliente: TestClient, orden_id: str, json: dict[str, Any]
) -> Response:
    """Agrega UN Detalle luego de la revision (075) y finaliza.

    Si agregar el Detalle falla, devuelve esa respuesta sin finalizar.
    """
    agregado = cliente.post(
        f"/api/orders/{orden_id}/review/details", json=json
    )
    if agregado.status_code != 200:
        return agregado
    return finalizar_definicion(cliente, orden_id, json["usuario_id"])
