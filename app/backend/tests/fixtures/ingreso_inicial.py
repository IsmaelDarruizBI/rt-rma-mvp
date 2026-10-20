"""Atajos HTTP del ingreso inicial simplificado (iteracion 1 del UAT).

Crear la Orden con los datos de recepcion completos, cargar los trabajos
y generar el comprobante de ingreso y autorizacion: confirma, finaliza,
autoriza y deja la Orden en la cola con prioridad 4. Catalogos propios
en ``tmp_path`` (``api_salidas.sembrar``), nunca los DEMO.
"""

from .api_salidas import BATERIA, RECEPCION, agregar, ok

ESTADO_FISICO = "Pantalla con un rayon leve."
OBSERVACIONES = "El cliente pide conservar los datos."
NOTA_INTERNA = "Cliente conflictivo: confirmar todo por escrito."


def crear_con_recepcion(
    cliente,
    *,
    checkin: bool | None = True,
    estado_fisico: str | None = ESTADO_FISICO,
    observaciones: str | None = OBSERVACIONES,
    notas_internas: str | None = NOTA_INTERNA,
    accesorios: tuple[str, ...] = ("Cargador",),
) -> str:
    """CLIENTE_EXTERNO recien creada, con los datos del ingreso."""
    return ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": RECEPCION,
                "cliente": {"nombre": "Ana Gomez", "telefono": "341-555"},
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 14",
                    "falla_reportada": "La bateria dura poco.",
                    "imei": "356789012345678",
                },
                "recepcion": {
                    "estado_fisico": estado_fisico,
                    "accesorios": list(accesorios),
                    "observaciones": observaciones,
                    "notas_internas": notas_internas,
                    "checkin": checkin,
                },
            },
        )
    )["id"]


def generar_ingreso(cliente, orden_id, usuario=RECEPCION, canal=None):
    """``POST .../documents/intake-receipt`` (la respuesta, sin validar)."""
    cuerpo = {"usuario_id": usuario}
    if canal is not None:
        cuerpo["canal"] = canal
    return cliente.post(
        f"/api/orders/{orden_id}/documents/intake-receipt", json=cuerpo
    )


def ingresada(cliente, *tipos, checkin: bool | None = True) -> str:
    """Creada, con sus trabajos y el comprobante de ingreso generado."""
    orden_id = crear_con_recepcion(cliente, checkin=checkin)
    for tipo in tipos or (BATERIA,):
        agregar(cliente, orden_id, tipo)
    ok(generar_ingreso(cliente, orden_id))
    return orden_id


def agregar_otros(
    cliente,
    orden_id,
    descripcion="Limpieza de puerto de carga",
    precio="15000",
    usuario=RECEPCION,
):
    """``POST .../details`` con un trabajo "Otros" (la respuesta)."""
    return cliente.post(
        f"/api/orders/{orden_id}/details",
        json={
            "usuario_id": usuario,
            "tipo_reparacion_id": "TR-OTROS",
            "descripcion": descripcion,
            "precio": precio,
        },
    )


def documentos(cliente, orden_id) -> list[dict]:
    return ok(cliente.get(f"/api/orders/{orden_id}/documents"))["emitidos"]


def del_tipo(cliente, orden_id, tipo: str) -> list[dict]:
    return [d for d in documentos(cliente, orden_id) if d["tipo"] == tipo]


def complementarias(orden: dict) -> list[tuple[str, str | None]]:
    return [
        (a["codigo"], a["detalle_id"])
        for a in orden["acciones_complementarias"]
    ]
