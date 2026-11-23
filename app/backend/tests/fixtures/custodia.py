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

Ingreso sin trabajos (DEC-AJ-05): el comprobante de recepcion que se
genera al enviar a revision confirma tambien la custodia, y exige lo mismo
que el de ingreso: ``enviar_a_revision`` deja esos datos antes de enviarla.

Verificacion del ingreso (DEC-AJ-07): la respuesta a «¿Se pudieron
verificar las funcionalidades del equipo?» es obligatoria para recibir el
equipo con el comprobante; ``preparar_ingreso`` la registra (Si) si falta.
Es informativa: no es el check-in de entrega.

Check-in (UAT-009): se registra antes de la entrega, con la reparacion
lista. ``entregar`` lo registra (realizado) si la Orden lo ofrece y
todavia no lo tiene. DEC-AJ-04 permite registrarlo dentro de la misma
entrega; ``tests/test_entrega_y_garantia.py`` cubre ese camino.
"""

RECEPCION = "RECEP-001"
ADMINISTRADOR = "ADMIN-001"
ESTADO_FISICO = "Sin golpes ni marcas; pantalla sana."
# DEC-AJ-09 (P-05): retira el titular; no se pide otro dato ni el DNI.
RECEPTOR: dict = {"retira_otra_persona": False}


def en_ingreso_inicial(orden: dict) -> bool:
    """CLIENTE_EXTERNO en REQUERIMIENTO con la definicion abierta."""
    pasos = {paso["referencia_id"] for paso in orden["historial"]}
    return (
        orden["origen"] == "CLIENTE_EXTERNO"
        and orden["estado_workflow"] == "REQUERIMIENTO"
        and not {"PROC-REP-080", "PROC-REP-129"} & pasos
    )


def preparar_ingreso(cliente, orden_id: str, usuario=RECEPCION) -> dict:
    """Registra el estado fisico y la verificacion del ingreso si faltan;
    devuelve la Orden.

    Son los datos que exige recibir el equipo con el comprobante (el de
    ingreso y autorizacion o, sin trabajos, el de recepcion; DEC-AJ-05 y
    DEC-AJ-07). El check-in no: se registra antes de la entrega. Lo que ya
    este registrado se conserva.
    """
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    datos = (orden["recepcion"] or {}).get("datos") or {}
    if (
        datos.get("estado_fisico")
        and datos.get("funcionalidades_verificadas") is not None
    ):
        return orden
    respuesta = cliente.put(
        f"/api/orders/{orden_id}/reception",
        json={
            "usuario_id": usuario,
            "estado_fisico": datos.get("estado_fisico") or ESTADO_FISICO,
            "accesorios": datos.get("accesorios") or [],
            "observaciones": datos.get("observaciones"),
            "notas_internas": datos.get("notas_internas"),
            "observaciones_unificadas": datos.get(
                "observaciones_unificadas", False
            ),
            "funcionalidades_verificadas": (
                True
                if datos.get("funcionalidades_verificadas") is None
                else datos["funcionalidades_verificadas"]
            ),
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def enviar_a_revision(cliente, orden_id: str, usuario=RECEPCION):
    """``POST .../send-to-review`` (la respuesta, sin validar).

    En Cliente Externo con la custodia pendiente, antes deja los datos que
    exige el comprobante de recepcion, que la confirma (DEC-AJ-05).
    """
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    if (
        orden["origen"] == "CLIENTE_EXTERNO"
        and orden["custodia"]["estado"] == "PENDIENTE_CONFIRMACION"
    ):
        preparar_ingreso(cliente, orden_id)
    return cliente.post(
        f"/api/orders/{orden_id}/send-to-review",
        json={"usuario_id": usuario},
    )


def registrar_checkin(
    cliente,
    orden_id: str,
    realizado: bool = True,
    usuario=RECEPCION,
    motivo: str | None = None,
):
    """``POST .../checkin``: si se pudieron verificar las funciones.

    ``motivo``: el de una correccion (DEC-MI-05)."""
    return cliente.post(
        f"/api/orders/{orden_id}/checkin",
        json={"usuario_id": usuario, "realizado": realizado, "motivo": motivo},
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


def revision_anterior_sin_custodia(cliente, orden_id: str) -> dict:
    """Una Orden de Cliente Externo enviada a revision ANTES de DEC-AJ-05:
    con el comprobante de recepcion emitido y la custodia sin confirmar,
    como quedaron las Ordenes del UAT.

    Hoy ese comprobante confirma la custodia en el mismo acto. Para probar
    lo que sigue valiendo con la custodia pendiente (equipo no recibido,
    ejecucion bloqueada, entrega bloqueada) se envia con el flujo vigente y
    despues el archivo queda como lo dejaba el anterior: sin la
    confirmacion ni su paso, y el comprobante con la custodia pendiente.
    Devuelve la Orden leida por la API.
    """
    import json

    respuesta = enviar_a_revision(cliente, orden_id)
    assert respuesta.status_code == 200, respuesta.text
    directorio = cliente.app.state.settings.data_dir
    ruta = directorio / "ordenes" / f"{orden_id}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["recepcion"]["confirmacion"] = None
    datos["historial"] = [
        paso
        for paso in datos["historial"]
        if paso["referencia_id"] != "ACC-REP-024"
    ]
    for documento in datos["documentos"]["emitidos"]:
        contenido = documento["contenido"]
        if contenido["tipo"] == "COMPROBANTE_RECEPCION":
            contenido["recepcion_fisica"] = "PENDIENTE_CONFIRMACION"
            contenido["confirmada_por"] = None
            contenido["confirmada_en"] = None
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    orden = cliente.get(f"/api/orders/{orden_id}").json()
    assert orden["custodia"]["estado"] == "PENDIENTE_CONFIRMACION"
    return orden
