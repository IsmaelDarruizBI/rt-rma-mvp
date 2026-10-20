"""Atajos HTTP para las salidas del proceso: cancelacion y rechazo.

Catalogos propios en ``tmp_path`` (nunca los DEMO del repositorio): dos
Tipos de Reparacion con su insumo y stock holgado, para poder ejecutar,
rechazar y volver a ejecutar sin quedarse sin unidades, y dos tecnicos.
"""

import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app.application import construir_contexto
from app.core.config import Settings
from app.domain.models import (
    EstacionTrabajo,
    Insumo,
    RolUsuario,
    TipoReparacion,
    TipoReparacionEstacion,
    TipoReparacionInsumos,
    Usuario,
)
from app.main import create_app
from app.storage.json.base import escribir_json_atomico

from . import custodia
from .custodia import entregar

RECEPCION = "RECEP-001"
COORDINADOR = "COORD-001"
TECNICO = "TECH-001"
TECNICO_B = "TECH-002"
ADMINISTRADOR = "ADMIN-001"
ESTACION = "EST-001"
BATERIA = "TR-001"
PANTALLA = "TR-002"
INSUMO_BATERIA = "INS-001"
INSUMO_PANTALLA = "INS-002"
MOTIVO = "El cliente desiste de este trabajo."

_INSUMO_DE = {BATERIA: INSUMO_BATERIA, PANTALLA: INSUMO_PANTALLA}


def sembrar(directorio, stock: str = "5") -> None:
    catalogos = {
        "tipos_reparacion.json": [
            TipoReparacion(
                id=BATERIA,
                nombre="Cambio de bateria",
                precio=Decimal("80000"),
                puntaje=10,
                garantia_dias=90,
            ),
            TipoReparacion(
                id=PANTALLA,
                nombre="Cambio de pantalla",
                precio=Decimal("50000"),
                puntaje=5,
                garantia_dias=60,
            ),
        ],
        "insumos.json": [
            Insumo(
                id=INSUMO_BATERIA,
                codigo="BAT",
                nombre="Bateria",
                stock_fisico=Decimal(stock),
            ),
            Insumo(
                id=INSUMO_PANTALLA,
                codigo="PANT",
                nombre="Pantalla",
                stock_fisico=Decimal(stock),
            ),
        ],
        "tipo_reparacion_insumos.json": [
            TipoReparacionInsumos(
                tipo_reparacion_id=tipo,
                insumo_id=insumo,
                cantidad=Decimal("1"),
            )
            for tipo, insumo in _INSUMO_DE.items()
        ],
        "estaciones.json": [EstacionTrabajo(id=ESTACION, nombre="Mesa 1")],
        "tipo_reparacion_estaciones.json": [
            TipoReparacionEstacion(
                tipo_reparacion_id=tipo, estacion_id=ESTACION
            )
            for tipo in _INSUMO_DE
        ],
        "usuarios.json": [
            Usuario(
                id=RECEPCION, nombre="Recepcion", rol=RolUsuario.RECEPCION
            ),
            Usuario(
                id=COORDINADOR,
                nombre="Coordinacion",
                rol=RolUsuario.COORDINADOR_RMA,
            ),
            Usuario(id=TECNICO, nombre="Tecnico A", rol=RolUsuario.TECNICO),
            Usuario(id=TECNICO_B, nombre="Tecnico B", rol=RolUsuario.TECNICO),
            Usuario(
                id=ADMINISTRADOR,
                nombre="Administracion",
                rol=RolUsuario.ADMINISTRADOR,
            ),
        ],
    }
    for archivo, entidades in catalogos.items():
        escribir_json_atomico(
            directorio / "catalogs" / archivo,
            [entidad.model_dump(mode="json") for entidad in entidades],
        )


def cliente_http(directorio, stock: str = "5") -> TestClient:
    sembrar(directorio, stock)
    return TestClient(create_app(Settings(data_dir=directorio)))


def repo_ordenes(directorio):
    return construir_contexto(Settings(data_dir=directorio)).ordenes


def stock(directorio, insumo_id: str = INSUMO_BATERIA) -> Decimal:
    ruta = directorio / "catalogs" / "insumos.json"
    for insumo in json.loads(ruta.read_text(encoding="utf-8")):
        if insumo["id"] == insumo_id:
            return Decimal(str(insumo["stock_fisico"]))
    raise AssertionError(insumo_id)


def archivo(directorio, orden_id: str) -> bytes:
    return (directorio / "ordenes" / f"{orden_id}.json").read_bytes()


def ids(orden: dict) -> list[str]:
    return [p["referencia_id"] for p in orden["historial"]]


def codigos(orden: dict) -> list[str]:
    return [a["codigo"] for a in orden["acciones_disponibles"]]


def codigos_cancelacion(orden: dict) -> list[tuple[str, str | None]]:
    return [
        (a["codigo"], a["detalle_id"]) for a in orden["acciones_cancelacion"]
    ]


def detalle(orden: dict, detalle_id: str) -> dict:
    return next(
        d for d in orden["reparaciones_detail"] if d["id"] == detalle_id
    )


def ok(respuesta) -> dict:
    assert respuesta.status_code < 300, respuesta.text
    return respuesta.json()


def conflicto(respuesta, codigo: str = "PRECONDICION_INVALIDA") -> str:
    assert respuesta.status_code == 409, respuesta.text
    error = respuesta.json()["error"]
    assert error["codigo"] == codigo, error
    return error["mensaje"]


# --- Recorrido ---------------------------------------------------------------


def crear(cliente: TestClient) -> str:
    return ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": RECEPCION,
                "cliente": {"nombre": "Cliente", "telefono": "341-1"},
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 14",
                    "falla_reportada": "No carga.",
                },
            },
        )
    )["id"]


def agregar(cliente, orden_id, tipo=BATERIA) -> dict:
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/details",
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": tipo},
        )
    )


def generar_ingreso(cliente, orden_id) -> dict:
    """Comprobante de ingreso y autorizacion (ingreso inicial).

    Prepara el estado fisico y el check-in si faltan y lo genera: confirma
    la recepcion, cierra la definicion, autoriza los trabajos cargados y
    deja la Orden en la cola con prioridad 4.
    """
    custodia.preparar_ingreso(cliente, orden_id)
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/documents/intake-receipt",
            json={"usuario_id": RECEPCION},
        )
    )


def finalizar(cliente, orden_id, confirmar_recepcion=True) -> dict:
    """Finaliza la definicion y devuelve esa respuesta.

    Con ``confirmar_recepcion`` (default) Recepcion confirma ademas la
    recepcion fisica del equipo: estos tests asumen el equipo en custodia
    desde aqui, como antes lo aproximaba el comprobante emitido al
    finalizar. Ahora es una confirmacion explicita.

    En el ingreso inicial de CLIENTE_EXTERNO la definicion se cierra con el
    comprobante de ingreso y autorizacion (``generar_ingreso``): los
    trabajos quedan autorizados y la Orden en la cola.
    """
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    if custodia.en_ingreso_inicial(orden):
        return generar_ingreso(cliente, orden_id)
    respuesta = ok(
        cliente.post(
            f"/api/orders/{orden_id}/definition/finalize",
            json={"usuario_id": RECEPCION},
        )
    )
    if confirmar_recepcion:
        custodia.confirmar_recepcion(cliente, orden_id)
    return respuesta


def decidir(
    cliente,
    orden_id,
    decisiones: dict[str, str],
    *,
    canal="WHATSAPP",
    observaciones=None,
    usuario=RECEPCION,
    versiones: dict[str, int] | None = None,
):
    """``POST .../authorizations``: {detalle_id: AUTORIZADO | RECHAZADO}.

    La version de cada Detalle es la vigente, salvo que ``versiones`` la
    fije (para probar una respuesta vieja).
    """
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    vigentes = {
        d["id"]: d["version_definicion"] for d in orden["reparaciones_detail"]
    }
    vigentes.update(versiones or {})
    return cliente.post(
        f"/api/orders/{orden_id}/authorizations",
        json={
            "usuario_id": usuario,
            "canal": canal,
            "observaciones": observaciones,
            "decisiones": [
                {
                    "detalle_id": detalle_id,
                    "version_definicion": vigentes.get(detalle_id, 1),
                    "resultado": resultado,
                }
                for detalle_id, resultado in decisiones.items()
            ],
        },
    )


def autorizar_todo(cliente, orden_id) -> dict:
    """El cliente autoriza todos los Detalles pendientes (explicito).

    Sin pendientes (por ejemplo, ya autorizados con el comprobante de
    ingreso) devuelve la Orden sin registrar nada.
    """
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    if not any(
        d["estado_autorizacion"] == "PENDIENTE"
        for d in orden["reparaciones_detail"]
    ):
        return orden
    return ok(
        decidir(
            cliente,
            orden_id,
            {
                d["id"]: "AUTORIZADO"
                for d in orden["reparaciones_detail"]
                if d["estado_autorizacion"] == "PENDIENTE"
            },
        )
    )


def definida(cliente, *tipos, autorizar=True) -> str:
    """CLIENTE_EXTERNO con esos Detalles, definida y autorizada.

    Con ``autorizar`` (default) es el ingreso inicial: el comprobante de
    ingreso autoriza los trabajos y la Orden queda en la cola. Sin
    autorizar, los trabajos quedan pendientes de la decision explicita del
    cliente (BR-REP-028), que en CLIENTE_EXTERNO llega por el camino de la
    revision tecnica (``por_revision``).
    """
    if not autorizar:
        return por_revision(cliente, *tipos)
    orden_id = crear(cliente)
    for tipo in tipos or (BATERIA,):
        agregar(cliente, orden_id, tipo)
    finalizar(cliente, orden_id)
    return orden_id


def por_revision(cliente, *tipos) -> str:
    """CLIENTE_EXTERNO definida por el camino de revision (065 -> 075).

    Recepcion la envia a revision, confirma la recepcion, el tecnico la
    revisa y Recepcion carga los trabajos y finaliza: quedan pendientes de
    la decision explicita del cliente (PROC-REP-129).
    """
    orden_id = crear(cliente)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/send-to-review",
            json={"usuario_id": RECEPCION},
        )
    )
    custodia.confirmar_recepcion(cliente, orden_id)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/technical-review",
            json={"usuario_id": TECNICO, "resultado": "Diagnostico."},
        )
    )
    for tipo in tipos or (BATERIA,):
        ok(
            cliente.post(
                f"/api/orders/{orden_id}/review/details",
                json={"usuario_id": RECEPCION, "tipo_reparacion_id": tipo},
            )
        )
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/definition/finalize",
            json={"usuario_id": RECEPCION},
        )
    )
    return orden_id


def encolar(cliente, orden_id, prioridad=3, usuario=COORDINADOR):
    """Ingresa la Orden a la cola con esa prioridad (PROC-REP-150 -> 170).

    Si ya entro sola con el comprobante de ingreso (prioridad 4), deja la
    prioridad pedida con el cambio de prioridad (ACC-REP-007). Devuelve la
    respuesta HTTP.
    """
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    if orden["estado_workflow"] != "EN_COLA":
        return cliente.post(
            f"/api/orders/{orden_id}/queue",
            json={"usuario_id": usuario, "prioridad": prioridad},
        )
    if orden["prioridad"] == prioridad:
        return cliente.get(f"/api/orders/{orden_id}")
    return cliente.post(
        f"/api/orders/{orden_id}/priority",
        json={"usuario_id": usuario, "prioridad": prioridad},
    )


def tomada(cliente, orden_id, tecnico=TECNICO) -> dict:
    ok(encolar(cliente, orden_id, 3))
    return tomar(cliente, orden_id, tecnico)


def tomar(cliente, orden_id, tecnico=TECNICO) -> dict:
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": tecnico, "estacion_id": ESTACION},
        )
    )


def iniciar(cliente, orden_id, detalle_id="DET-001", tecnico=TECNICO) -> str:
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/{detalle_id}/start",
            json={"usuario_id": tecnico},
        )
    )
    (activa,) = [
        e for e in orden["ejecuciones"] if e["estado"] == "EN_PROGRESO"
    ]
    return activa["id"]


def cerrar_ejecucion(
    cliente,
    orden_id,
    ejecucion_id,
    accion="complete",
    tecnico=TECNICO,
    insumo=INSUMO_BATERIA,
    cantidad="1",
):
    utilizados = (
        [{"insumo_id": insumo, "cantidad": cantidad}] if cantidad else []
    )
    # Interrumpir (y pedir redefinicion) exigen motivo.
    motivo = {} if accion == "complete" else {"motivo": "Falta una pieza."}
    return cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/{accion}",
        json={
            "usuario_id": tecnico,
            "insumos_utilizados": utilizados,
            **motivo,
        },
    )


def ejecutar(cliente, orden_id, detalle_id="DET-001", tipo=BATERIA) -> dict:
    """Inicia y completa ESE Detalle con su insumo (toma ya activa)."""
    ejecucion_id = iniciar(cliente, orden_id, detalle_id)
    return ok(
        cerrar_ejecucion(
            cliente, orden_id, ejecucion_id, insumo=_INSUMO_DE[tipo]
        )
    )


def aprobar(cliente, orden_id, detalle_id, usuario=RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/control/approve",
        json={"usuario_id": usuario, "detalle_id": detalle_id},
    )


def rechazar(
    cliente,
    orden_id,
    detalle_id,
    motivo="La bateria no carga.",
    usuario=RECEPCION,
):
    return cliente.post(
        f"/api/orders/{orden_id}/control/reject",
        json={
            "usuario_id": usuario,
            "detalle_id": detalle_id,
            "motivo": motivo,
        },
    )


def cancelar_detalle(
    cliente, orden_id, detalle_id, motivo=MOTIVO, usuario=RECEPCION
):
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/cancel",
        json={"usuario_id": usuario, "motivo": motivo},
    )


def cancelar_orden(cliente, orden_id, motivo=MOTIVO, usuario=RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/cancel",
        json={"usuario_id": usuario, "motivo": motivo},
    )


def devolver(cliente, orden_id, recibido_por="Cliente", usuario=RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/return-equipment",
        json={"usuario_id": usuario, "recibido_por": recibido_por},
    )


def notificar_pagar_entregar(cliente, orden_id) -> dict:
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )
    saldo = Decimal(orden["resumen"]["saldo"])
    if saldo > 0:
        ok(
            cliente.post(
                f"/api/orders/{orden_id}/payments",
                json={
                    "usuario_id": RECEPCION,
                    "monto": str(saldo),
                    "metodo": "EFECTIVO",
                },
            )
        )
    return ok(entregar(cliente, orden_id, ADMINISTRADOR))
