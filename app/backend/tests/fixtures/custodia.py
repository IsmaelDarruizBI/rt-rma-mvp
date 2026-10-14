"""Atajos HTTP de recepcion fisica y entrega (MVP v2: documentos y custodia).

Desde el registro de custodia, entregar o devolver un equipo exige su
recepcion fisica CONFIRMADA (el comprobante de recepcion ya no la prueba)
y quien lo retira. Los tests de flujo anteriores, que no tratan sobre la
custodia, la confirman de forma explicita con estos atajos: lo que
verifican no cambia.
"""

RECEPCION = "RECEP-001"
ADMINISTRADOR = "ADMIN-001"
ESTADO_FISICO = "Sin golpes ni marcas; pantalla sana."
RECEPTOR = {
    "recibido_por": "Titular de la Orden",
    "identificacion_receptor": "DNI 30111222",
}


def confirmar_recepcion(cliente, orden_id: str, usuario=RECEPCION) -> dict:
    """Confirma la recepcion fisica si esta pendiente; devuelve la Orden.

    Si el ingreso no tiene estado fisico, lo registra antes (la
    confirmacion lo exige). Sobre una Orden ya confirmada, cerrada o sin
    confirmacion requerida no hace nada.
    """
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    if orden["custodia"]["estado"] != "PENDIENTE_CONFIRMACION":
        return orden
    if not orden["recepcion"]["datos"]["estado_fisico"]:
        respuesta = cliente.put(
            f"/api/orders/{orden_id}/reception",
            json={"usuario_id": usuario, "estado_fisico": ESTADO_FISICO},
        )
        assert respuesta.status_code == 200, respuesta.text
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/reception/confirm",
        json={"usuario_id": usuario},
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def entregar(cliente, orden_id: str, usuario=ADMINISTRADOR):
    """``POST .../deliver`` con la custodia confirmada y quien retira."""
    confirmar_recepcion(cliente, orden_id)
    return cliente.post(
        f"/api/orders/{orden_id}/deliver",
        json={"usuario_id": usuario, **RECEPTOR},
    )


def no_recibido(
    cliente,
    orden_id: str,
    motivo="El cliente nunca trajo el equipo.",
    usuario=RECEPCION,
):
    """``POST .../reception/not-received``: el equipo nunca ingreso."""
    return cliente.post(
        f"/api/orders/{orden_id}/reception/not-received",
        json={"usuario_id": usuario, "motivo": motivo},
    )
