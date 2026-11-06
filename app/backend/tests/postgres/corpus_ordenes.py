"""Corpus de Ordenes reales para el guardado por agregado (E4, A1, A2 y A4).

Corre flujos reales por la API en modo JSON y graba cada Orden que el
repository JSON guarda, en el orden en que se guarda. Cada paso es una
Orden valida del dominio, tal como la deja un comando.

``proyectar`` deja solo lo que PostgreSQL ya guarda. Quita los pagos, los
descuentos y los pasos del historial que referencian un pago (A3) y los
movimientos de insumo (A6, A7). Esas partes van a tablas propias, asi que
quitarlas no cambia como se guarda el resto.
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import OrdenReparacion, ResumenPago
from app.main import create_app
from app.storage.json.ordenes import JsonOrdenReparacionRepository
from tests.fixtures import api_salidas as f
from tests.fixtures import custodia as c
from tests.fixtures.api_definicion import definir_desde_revision_y_finalizar

DNI = "30111222"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def proyectar(orden: OrdenReparacion) -> OrdenReparacion:
    """La Orden con solo las partes que PostgreSQL ya guarda."""
    proyectada = orden.model_copy(deep=True)
    proyectada.movimientos_insumo = []
    proyectada.resumen_pago = ResumenPago()
    proyectada.descuentos = []
    proyectada.historial = [
        paso for paso in proyectada.historial if paso.pago_id is None
    ]
    return proyectada


def _crear_con_dni(cliente, cliente_id=None) -> str:
    datos = {"nombre_apellido": "Ana Paz", "telefono": "341-2", "dni": DNI}
    if cliente_id:
        datos["id"] = cliente_id
    return f.ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": f.RECEPCION,
                "cliente": datos,
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 13",
                    "falla_reportada": "No enciende.",
                    "imei": "356938035643809",
                    "color": "Negro",
                    "capacidad": "128 GB",
                },
            },
        )
    )


def _flujos(cliente: TestClient) -> None:
    # Dos Detalles, ingreso, toma, ejecucion completa con insumos,
    # control aprobado y otro rechazado.
    orden = f.crear(cliente)
    f.agregar(cliente, orden)
    f.agregar(cliente, orden, f.PANTALLA)
    f.finalizar(cliente, orden)
    f.tomada(cliente, orden)
    f.ejecutar(cliente, orden, "DET-001")
    f.ejecutar(cliente, orden, "DET-002", f.PANTALLA)
    f.ok(f.aprobar(cliente, orden, "DET-001"))
    f.ok(f.rechazar(cliente, orden, "DET-002"))
    # Ejecucion que pide redefinicion: revision tecnica y version nueva.
    redefinida = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, redefinida)
    ejecucion = f.iniciar(cliente, redefinida)
    f.ok(
        cliente.post(
            f"/api/orders/{redefinida}/executions/{ejecucion}"
            "/requires-redefinition",
            json={
                "usuario_id": f.TECNICO,
                "insumos_utilizados": [],
                "motivo": "Hace falta otra reparacion.",
            },
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{redefinida}/details/DET-001/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Placa danada."},
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{redefinida}/details/DET-001/redefine",
            json={
                "usuario_id": f.RECEPCION,
                "tipo_reparacion_id": f.PANTALLA,
            },
        )
    )
    # Ejecucion interrumpida y Detalle cancelado.
    interrumpida = f.definida(cliente, f.BATERIA, f.PANTALLA)
    f.tomada(cliente, interrumpida)
    ejecucion = f.iniciar(cliente, interrumpida)
    f.ok(
        f.cerrar_ejecucion(
            cliente, interrumpida, ejecucion, accion="interrupt", cantidad=""
        )
    )
    f.ok(f.cancelar_detalle(cliente, interrumpida, "DET-002"))
    # En revision, cancelada, RT interno y un cliente con DNI en dos Ordenes.
    f.por_revision(cliente, f.PANTALLA)
    f.ok(f.cancelar_orden(cliente, f.definida(cliente)))
    f.ok(
        cliente.post(
            "/api/orders/rt-interno",
            json={
                "usuario_id": f.RECEPCION,
                "referencia_rt": "RT-1",
                "equipo": {
                    "marca": "Samsung",
                    "modelo": "Galaxy S21",
                    "falla_reportada": "Pantalla rota.",
                },
            },
        )
    )
    primera = _crear_con_dni(cliente)
    _crear_con_dni(cliente, primera["cliente"]["id"])


def _tic() -> None:
    """Dos comandos de una persona nunca caen en el mismo instante, pero aca
    si podrian: el reloj de Windows avanza cada ~15 ms. El corpus no depende
    de eso."""
    time.sleep(0.02)


def _foto(cliente, orden_id, contenido, usuario=f.RECEPCION, nombre=None):
    _tic()
    parametros = {"usuario_id": usuario}
    if nombre:
        parametros["nombre"] = nombre
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/photos",
            params=parametros,
            content=contenido,
        )
    )


def _corregir_recepcion(cliente, orden_id, estado_fisico, **extra):
    _tic()
    return f.ok(
        cliente.put(
            f"/api/orders/{orden_id}/reception",
            json={
                "usuario_id": f.RECEPCION,
                "estado_fisico": estado_fisico,
                **extra,
            },
        )
    )


def _nota(cliente, orden_id, texto, interna=False):
    _tic()
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/reception/notes",
            json={
                "usuario_id": f.RECEPCION,
                "texto": texto,
                "interna": interna,
            },
        )
    )


def _reparada(cliente, *tipos) -> str:
    """Una Orden con sus trabajos ejecutados y aprobados."""
    orden = f.definida(cliente, *tipos)
    f.tomada(cliente, orden)
    f.ejecutar(cliente, orden, "DET-001")
    f.ok(f.aprobar(cliente, orden, "DET-001"))
    return orden


def _sin_reparar(cliente, orden_id) -> None:
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Sin arreglo."},
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/review/without-repair",
            json={"usuario_id": f.RECEPCION, "motivo": "No tiene arreglo."},
        )
    )


def _garantia(cliente, origen: str) -> str:
    garantia = f.ok(
        cliente.post(
            f"/api/orders/{origen}/warranty-rma",
            json={
                "usuario_id": f.RECEPCION,
                "detalle_origen_ids": ["DET-001"],
            },
        )
    )["id"]
    f.ok(
        cliente.post(
            f"/api/orders/{garantia}/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Cubierta."},
        )
    )
    f.ok(
        definir_desde_revision_y_finalizar(
            cliente,
            garantia,
            json={"usuario_id": f.RECEPCION, "tipo_reparacion_id": f.BATERIA},
        )
    )
    return garantia


def _flujos_de_salida(cliente: TestClient) -> None:
    """Recepcion, documentos, fotos, check-in, entrega y devolucion (A4)."""
    # Recepcion corregida, notas y fotos antes de definir los trabajos.
    orden = f.crear(cliente)
    _corregir_recepcion(cliente, orden, "Con rayones.")
    _corregir_recepcion(
        cliente,
        orden,
        "Con rayones y un golpe.",
        accesorios=["Funda", "Cargador"],
        observaciones="Trae funda.",
        notas_internas="Revisar el golpe.",
    )
    _nota(cliente, orden, "El cliente pide que lo llamen.")
    _nota(cliente, orden, "Cliente dificil.", interna=True)
    _foto(cliente, orden, JPEG, nombre="frente.jpg")
    _foto(cliente, orden, PNG, usuario=f.TECNICO)
    f.agregar(cliente, orden)
    f.finalizar(cliente, orden)
    f.autorizar_todo(cliente, orden)
    # Documentos: con otro contenido, una version nueva reemplaza a la
    # anterior. Una nota visible cambia el comprobante de recepcion.
    for numero in range(3):
        _nota(cliente, orden, f"Nota visible {numero}.")
        f.ok(
            cliente.post(
                f"/api/orders/{orden}/documents/reception-receipt",
                json={
                    "usuario_id": f.RECEPCION,
                    "motivo": f"Se agrego la nota {numero}.",
                },
            )
        )
    f.ok(
        cliente.post(
            f"/api/orders/{orden}/documents/authorization-receipt",
            json={"usuario_id": f.RECEPCION},
        )
    )
    # Nota despues de decidir la custodia.
    _nota(cliente, orden, "Retira el hermano.")
    # Taller, check-in repetido con otro resultado y entrega.
    f.tomada(cliente, orden)
    f.ejecutar(cliente, orden, "DET-001")
    f.ok(f.aprobar(cliente, orden, "DET-001"))
    _tic()
    f.ok(c.registrar_checkin(cliente, orden, realizado=False))
    _tic()
    f.ok(c.registrar_checkin(cliente, orden, realizado=True))
    f.notificar_pagar_entregar(cliente, orden)

    # Comprobante de autorizacion: lo pide Recepcion, por el camino de
    # revision, con la decision del cliente ya registrada.
    autorizada = f.por_revision(cliente, f.BATERIA)
    f.autorizar_todo(cliente, autorizada)
    f.ok(
        cliente.post(
            f"/api/orders/{autorizada}/documents/authorization-receipt",
            json={"usuario_id": f.RECEPCION},
        )
    )

    # Cancelada con devolucion del equipo.
    cancelada = f.definida(cliente)
    f.ok(f.cancelar_orden(cliente, cancelada))
    f.ok(f.devolver(cliente, cancelada))

    # Cancelada sin que el equipo haya ingresado.
    nunca = f.crear(cliente)
    f.ok(f.cancelar_orden(cliente, nunca))
    f.ok(c.no_recibido(cliente, nunca))

    # Sin reparacion: se entrega como devolucion, con la Orden ENTREGADA.
    sin_reparacion = f.crear(cliente)
    f.ok(
        cliente.post(
            f"/api/orders/{sin_reparacion}/send-to-review",
            json={"usuario_id": f.RECEPCION},
        )
    )
    c.confirmar_recepcion(cliente, sin_reparacion)
    _sin_reparar(cliente, sin_reparacion)
    f.notificar_pagar_entregar(cliente, sin_reparacion)

    # RT interno, de punta a punta: sin salida en el dominio.
    rt = f.ok(
        cliente.post(
            "/api/orders/rt-interno",
            json={
                "usuario_id": f.RECEPCION,
                "referencia_rt": "RT-2",
                "equipo": {
                    "marca": "Samsung",
                    "modelo": "Galaxy S22",
                    "falla_reportada": "No carga.",
                },
            },
        )
    )["id"]
    f.ok(
        cliente.post(
            f"/api/orders/{rt}/send-to-review",
            json={"usuario_id": f.RECEPCION},
        )
    )
    c.confirmar_recepcion(cliente, rt)
    _sin_reparar(cliente, rt)
    f.ok(cliente.post(f"/api/orders/{rt}/inform-rt", json={}))
    f.ok(
        cliente.post(
            f"/api/orders/{rt}/return-rt",
            json={"usuario_id": f.ADMINISTRADOR},
        )
    )

    # Garantia RMA de punta a punta: nace de una Orden entregada.
    origen = _reparada(cliente)
    f.notificar_pagar_entregar(cliente, origen)
    garantia = _garantia(cliente, origen)
    f.tomada(cliente, garantia)
    f.ejecutar(cliente, garantia, "DET-001")
    f.ok(f.aprobar(cliente, garantia, "DET-001"))
    # Una garantia no se cobra: se notifica y se entrega.
    f.ok(
        cliente.post(
            f"/api/orders/{garantia}/notify",
            json={"usuario_id": f.RECEPCION},
        )
    )
    f.ok(c.entregar(cliente, garantia, f.ADMINISTRADOR))


def armar_corpus(directorio: Path) -> list[OrdenReparacion]:
    """Cada Orden que guardan los flujos, en orden, ya proyectada."""
    f.sembrar(directorio)
    grabadas: list[OrdenReparacion] = []
    original = JsonOrdenReparacionRepository.guardar

    def grabar(self, orden):
        original(self, orden)
        grabadas.append(proyectar(orden))

    with pytest.MonkeyPatch.context() as parche:
        parche.setattr(JsonOrdenReparacionRepository, "guardar", grabar)
        configuracion = Settings(
            data_dir=directorio, fotos_dir=directorio / "fotos"
        )
        with TestClient(create_app(configuracion)) as cliente:
            _flujos(cliente)
            _flujos_de_salida(cliente)
    return grabadas
