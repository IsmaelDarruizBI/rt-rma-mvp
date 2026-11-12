"""Corpus de Ordenes reales para el guardado por agregado (E4 y E5).

Corre flujos reales por la API en modo JSON y graba cada Orden que el
repository JSON guarda, en el orden en que se guarda. Cada paso es una
Orden valida del dominio, tal como la deja un comando.

Desde A7 PostgreSQL guarda la Orden entera, tambien sus movimientos de
insumo: el corpus no quita nada. Antes de los flujos se guarda el stock
inicial del catalogo (``insumos_iniciales.json``): la base arranca con ese
stock y el libro lo mueve igual que los flujos JSON.
"""

import time
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import OrdenReparacion
from app.main import create_app
from app.storage.json.ordenes import JsonOrdenReparacionRepository
from tests.fixtures import api_salidas as f
from tests.fixtures import custodia as c
from tests.fixtures import iteracion1 as it1
from tests.fixtures.api_definicion import definir_desde_revision_y_finalizar

DNI = "30111222"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


ARCHIVO_STOCK_INICIAL = "insumos_iniciales.json"


def proyectar(orden: OrdenReparacion) -> OrdenReparacion:
    """La Orden tal cual: PostgreSQL ya guarda todas sus partes (A7)."""
    return orden.model_copy(deep=True)


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
                "usuario_id": f.TECNICO,
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
    # En revision, sin trabajos vigentes (DC31: todos los trabajos
    # cancelados, la Orden abierta), RT interno y un cliente con DNI en dos
    # Ordenes.
    f.por_revision(cliente, f.PANTALLA)
    f.ok(f.cancelar_detalle(cliente, f.definida(cliente), "DET-001"))
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

    # Cancelada con devolucion del equipo (DC31: devolucion y despues la
    # cancelacion explicita, que cierra).
    cancelada = f.definida(cliente)
    f.ok(f.cancelar_detalle(cliente, cancelada, "DET-001"))
    f.ok(f.devolver(cliente, cancelada))
    f.ok(f.cancelar_orden(cliente, cancelada))

    # Cancelada sin que el equipo haya ingresado.
    nunca = f.crear(cliente)
    f.ok(c.no_recibido(cliente, nunca))
    f.ok(f.cancelar_orden(cliente, nunca))

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


def _pagar(cliente, orden_id, monto, metodo="EFECTIVO", **extra) -> dict:
    _tic()
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": f.RECEPCION,
                "monto": monto,
                "metodo": metodo,
                **extra,
            },
        )
    )


def _descuento(cliente, orden_id, tipo, valor, motivo) -> dict:
    _tic()
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/discount",
            json={
                "usuario_id": f.RECEPCION,
                "tipo": tipo,
                "valor": valor,
                "motivo": motivo,
            },
        )
    )


def _ultimo_pago(orden: dict) -> str:
    return orden["pagos"][-1]["id"]


def _flujos_financieros(cliente: TestClient) -> None:
    """Anticipos, anulacion, descuentos, pago final y devoluciones (A3)."""
    # Dos anticipos (uno anulado), descuentos que se cambian y se quitan,
    # un Detalle cancelado y el pago final al entregar.
    orden = f.definida(cliente, f.BATERIA, f.PANTALLA)
    _pagar(cliente, orden, "10000", operacion_id="op-a3-1", referencia="Sena")
    anulado = _ultimo_pago(
        _pagar(cliente, orden, "5000", "TRANSFERENCIA", operacion_id="op-2")
    )
    _tic()
    f.ok(
        cliente.post(
            f"/api/orders/{orden}/payments/{anulado}/void",
            json={"usuario_id": f.ADMINISTRADOR, "motivo": "Mal cargado."},
        )
    )
    _descuento(cliente, orden, "PORCENTAJE", "10", "Promocion.")
    _descuento(cliente, orden, "IMPORTE", "2000", "Convenio.")
    _descuento(cliente, orden, None, None, "Fin del convenio.")
    _descuento(cliente, orden, "IMPORTE", "1500.5", "Acuerdo.")
    _tic()
    f.ok(f.cancelar_detalle(cliente, orden, "DET-002"))
    f.tomada(cliente, orden)
    f.ejecutar(cliente, orden, "DET-001")
    f.ok(f.aprobar(cliente, orden, "DET-001"))
    # En el cierre: un pago parcial y el final, que salda la cuenta.
    f.ok(
        cliente.post(
            f"/api/orders/{orden}/notify", json={"usuario_id": f.RECEPCION}
        )
    )
    _pagar(cliente, orden, "20000", "TARJETA_CREDITO")
    f.notificar_pagar_entregar(cliente, orden)

    # Pago completo, Orden cancelada y el credito devuelto en dos partes.
    cancelada = f.definida(cliente, f.BATERIA)
    saldo = f.ok(cliente.get(f"/api/orders/{cancelada}"))["resumen"]["saldo"]
    pago = _ultimo_pago(_pagar(cliente, cancelada, saldo, "TARJETA_DEBITO"))
    _tic()
    f.ok(f.cancelar_detalle(cliente, cancelada, "DET-001"))
    for monto, medio in (("1000", "EFECTIVO"), (None, "TRANSFERENCIA")):
        credito = f.ok(cliente.get(f"/api/orders/{cancelada}"))["resumen"][
            "saldo"
        ]
        _tic()
        f.ok(
            cliente.post(
                f"/api/orders/{cancelada}/refunds",
                json={
                    "usuario_id": f.ADMINISTRADOR,
                    "pago_id": pago,
                    "monto": monto or str(-Decimal(credito)),
                    "medio": medio,
                    "motivo": "Se cancelo el trabajo.",
                    "operacion_id": f"dev-{medio}",
                },
            )
        )
    f.ok(f.devolver(cliente, cancelada))
    f.ok(f.cancelar_orden(cliente, cancelada))


def _flujos_iteracion1(cliente: TestClient) -> None:
    """Iteracion 1 (V1.4): HP-REP-003 con 036 vigente, VAR-REP-039/041/042
    y el circuito DC31 despues del desistimiento. La garantia vencida se
    arma con el reloj del contexto corrido hacia atras; al terminar se
    restituye."""
    # Con pantallas: las baterias del stock inicial ya las usaron los
    # flujos anteriores.
    contexto = cliente.app.state.contexto
    reloj = it1.instalar_reloj(cliente)
    try:
        it1.recorrido_garantia_vigente(cliente, f.PANTALLA)
        it1.recorrido_garantia_con_excepcion(cliente, reloj, f.PANTALLA)
        it1.recorrido_cortesia_con_pagos(cliente, f.PANTALLA)
        desistida = it1.recorrido_desistimiento_en_ejecucion(
            cliente, f.PANTALLA
        )
        # Sin trabajos vigentes la toma ya se libero: DC31 sigue con la
        # devolucion del equipo y la cancelacion explicita de la Orden.
        f.ok(f.devolver(cliente, desistida))
        f.ok(f.cancelar_orden(cliente, desistida))
    finally:
        cliente.app.state.contexto = contexto


def armar_corpus(directorio: Path) -> list[OrdenReparacion]:
    """Cada Orden que guardan los flujos, en orden, ya proyectada."""
    f.sembrar(directorio)
    (directorio / ARCHIVO_STOCK_INICIAL).write_bytes(
        (directorio / "catalogs" / "insumos.json").read_bytes()
    )
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
            _flujos_financieros(cliente)
            _flujos_iteracion1(cliente)
    return grabadas
