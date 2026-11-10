"""Ordenes CANCELADA y abiertas del circuito anterior a DC31.

Antes de DC31, cancelar todos los Detalles dejaba la Orden CANCELADA y
abierta, esperando la custodia, la devolucion del equipo o la del dinero
(por ejemplo OR-000003, OR-000006 y OR-000009 en UAT). Hoy ya no se
producen: cancelar la Orden la cierra en el mismo acto. Para probar la
compatibilidad se arma el mismo estado persistido: los Detalles se
cancelan con el flujo vigente y despues el archivo de la Orden queda como
lo dejaba el resolver anterior (CANCELADA, en PROC-REP-211).
"""

import json

from tests.fixtures.api_salidas import cancelar_detalle, ok


def cancelada_heredada(cliente, directorio, orden_id: str) -> dict:
    """Cancela los Detalles pendientes y deja la Orden como la dejaba el
    circuito anterior. Devuelve la Orden leida por la API."""
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    for detalle in orden["reparaciones_detail"]:
        if detalle["estado"] == "DEFINIDO":
            ok(cancelar_detalle(cliente, orden_id, detalle["id"]))
    ruta = directorio / "ordenes" / f"{orden_id}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["estado_workflow"] = "CANCELADA"
    # Con Detalles la dejaba el resolver (211); sin Detalles, la cancelacion
    # explicita de entonces (306).
    datos["current_process"] = (
        "PROC-REP-211" if datos["reparaciones_detail"] else "PROC-REP-306"
    )
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return ok(cliente.get(f"/api/orders/{orden_id}"))
