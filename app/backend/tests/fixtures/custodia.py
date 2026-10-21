"""Atajos HTTP de recepcion fisica y entrega (MVP v2: documentos y custodia).

Desde el registro de custodia, entregar o devolver un equipo exige su
recepcion fisica CONFIRMADA (el comprobante de recepcion ya no la prueba)
y quien lo retira. Los tests de flujo anteriores, que no tratan sobre la
custodia, la confirman de forma explicita con estos atajos: lo que
verifican no cambia.

Ingreso inicial de CLIENTE_EXTERNO (iteracion 1 del UAT): la recepcion se
confirma al generar el comprobante de ingreso y autorizacion, nunca por
separado. Ahi estos atajos solo dejan el dato que el comprobante exige (el
estado fisico).

Check-in (UAT-009): se registra antes de la entrega, con la reparacion
lista. ``entregar`` lo registra (realizado) si la Orden lo ofrece y
todavia no lo tiene.
"""

RECEPCION = "RECEP-001"
ADMINISTRADOR = "ADMIN-001"
ESTADO_FISICO = "Sin golpes ni marcas; pantalla sana."
RECEPTOR = {
    "recibido_por": "Titular de la Orden",
    "identificacion_receptor": "DNI 30111222",
}


def en_ingreso_inicial(orden: dict) -> bool:
    """CLIENTE_EXTERNO en REQUERIMIENTO con la definicion abierta."""
    pasos = {paso["referencia_id"] for paso in orden["historial"]}
    return (
        orden["origen"] == "CLIENTE_EXTERNO"
        and orden["estado_workflow"] == "REQUERIMIENTO"
        and not {"PROC-REP-080", "PROC-REP-129"} & pasos
    )


def preparar_ingreso(cliente, orden_id: str, usuario=RECEPCION) -> dict:
    """Registra el estado fisico si falta; devuelve la Orden.

    Es el dato que exige el comprobante de ingreso y autorizacion (el
    check-in ya no: se registra antes de la entrega). Lo que ya este
    registrado se conserva.
    """
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    datos = (orden["recepcion"] or {}).get("datos") or {}
    if datos.get("estado_fisico"):
        return orden
    respuesta = cliente.put(
        f"/api/orders/{orden_id}/reception",
        json={
            "usuario_id": usuario,
            "estado_fisico": ESTADO_FISICO,
            "accesorios": datos.get("accesorios") or [],
            "observaciones": datos.get("observaciones"),
            "notas_internas": datos.get("notas_internas"),
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def registrar_checkin(
    cliente, orden_id: str, realizado: bool = True, usuario=RECEPCION
):
    """``POST .../checkin``: si se pudieron verificar las funciones."""
    return cliente.post(
        f"/api/orders/{orden_id}/checkin",
        json={"usuario_id": usuario, "realizado": realizado},
    )


def checkin_si_falta(cliente, orden_id: str, usuario=RECEPCION) -> dict:
    """Registra el check-in (realizado) si la Orden lo ofrece y no lo tiene.

    Es el paso previo a la entrega de una Orden de Cliente Externo con
    trabajos realizados; en las demas no hace nada.
    """
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    ofrecido = any(
        accion["codigo"] == "REGISTRAR_CHECKIN"
        for accion in orden["acciones_disponibles"]
    )
    if not ofrecido or orden["recepcion"]["datos"]["checkin"] is not None:
        return orden
    respuesta = registrar_checkin(cliente, orden_id, usuario=usuario)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def confirmar_recepcion(cliente, orden_id: str, usuario=RECEPCION) -> dict:
    """Confirma la recepcion fisica si esta pendiente; devuelve la Orden.

    Si el ingreso no tiene estado fisico, lo registra antes (la
    confirmacion lo exige). Sobre una Orden ya confirmada, cerrada o sin
    confirmacion requerida no hace nada. En el ingreso inicial de
    CLIENTE_EXTERNO solo prepara los datos: confirma el comprobante.
    """
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    if orden["custodia"]["estado"] != "PENDIENTE_CONFIRMACION":
        return orden
    if en_ingreso_inicial(orden):
        return preparar_ingreso(cliente, orden_id, usuario)
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
    """``POST .../deliver`` con la custodia confirmada, el check-in (si
    corresponde) y quien retira."""
    confirmar_recepcion(cliente, orden_id)
    checkin_si_falta(cliente, orden_id)
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
