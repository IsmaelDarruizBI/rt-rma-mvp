"""Pagos, anulaciones, devoluciones de dinero y cierre financiero (HTTP).

    POST /api/orders/{id}/payments                 anticipo, parcial o final
    POST /api/orders/{id}/payments/{pago_id}/void  anulacion administrativa
    POST /api/orders/{id}/refunds                  devolucion de dinero
    GET  /api/orders/{id}/finances                 saldo, credito, movimientos
    GET  /api/catalogs/payment-methods             medios de pago

Saldo = Total - Pagado valido + Devuelto (BR-REP-038). Ninguna Orden
termina comercialmente con saldo pendiente ni con credito a favor del
cliente sin devolver. Catalogos propios en ``tmp_path`` con los importes de
los ejemplos: Detalles de 100.000, 80.000 y 70.000 (sin insumos).
"""

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import (
    EstacionTrabajo,
    OrdenReparacion,
    TipoReparacion,
    TipoReparacionEstacion,
)
from app.main import create_app
from app.storage.json.base import escribir_json_atomico
from tests.fixtures.api_definicion import definir_y_finalizar
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    COORDINADOR,
    ESTACION,
    RECEPCION,
    TECNICO,
    agregar,
    aprobar,
    archivo,
    cancelar_detalle,
    cancelar_orden,
    cerrar_ejecucion,
    cliente_http,
    codigos,
    conflicto,
    crear,
    decidir,
    devolver,
    finalizar,
    ids,
    iniciar,
    ok,
    repo_ordenes,
    tomada,
)
from tests.test_api_hp_rep_002 import TIPO, _crear_orden_rt, _sembrar_catalogos

T100 = "TR-100"
T080 = "TR-080"
T070 = "TR-070"
_PRECIOS = {T100: "100000", T080: "80000", T070: "70000"}


def _sembrar_tipos(directorio) -> None:
    catalogos = directorio / "catalogs"
    escribir_json_atomico(
        catalogos / "tipos_reparacion.json",
        [
            TipoReparacion(
                id=tipo,
                nombre=f"Reparacion {tipo}",
                precio=Decimal(precio),
                puntaje=1,
                garantia_dias=30,
            ).model_dump(mode="json")
            for tipo, precio in _PRECIOS.items()
        ],
    )
    escribir_json_atomico(catalogos / "tipo_reparacion_insumos.json", [])
    escribir_json_atomico(
        catalogos / "estaciones.json",
        [EstacionTrabajo(id=ESTACION, nombre="Mesa 1").model_dump()],
    )
    escribir_json_atomico(
        catalogos / "tipo_reparacion_estaciones.json",
        [
            TipoReparacionEstacion(
                tipo_reparacion_id=tipo, estacion_id=ESTACION
            ).model_dump()
            for tipo in _PRECIOS
        ],
    )


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        _sembrar_tipos(tmp_path)
        yield test_client


def pagar(
    cliente,
    orden_id,
    monto,
    metodo="EFECTIVO",
    usuario=RECEPCION,
    referencia=None,
    operacion_id=None,
):
    return cliente.post(
        f"/api/orders/{orden_id}/payments",
        json={
            "usuario_id": usuario,
            "monto": str(monto),
            "metodo": metodo,
            "referencia": referencia,
            "operacion_id": operacion_id,
        },
    )


def anular(
    cliente,
    orden_id,
    pago_id,
    motivo="Cargado dos veces.",
    usuario=ADMINISTRADOR,
):
    return cliente.post(
        f"/api/orders/{orden_id}/payments/{pago_id}/void",
        json={"usuario_id": usuario, "motivo": motivo},
    )


def reintegrar(
    cliente,
    orden_id,
    pago_id,
    monto,
    medio="EFECTIVO",
    usuario=RECEPCION,
    motivo="Se cancelaron trabajos.",
    referencia=None,
    operacion_id=None,
):
    return cliente.post(
        f"/api/orders/{orden_id}/refunds",
        json={
            "usuario_id": usuario,
            "pago_id": pago_id,
            "monto": str(monto),
            "medio": medio,
            "motivo": motivo,
            "referencia": referencia,
            "operacion_id": operacion_id,
        },
    )


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _resumen(orden: dict) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    r = orden["resumen"]
    return (
        Decimal(r["total"]),
        Decimal(r["pagado"]),
        Decimal(r["devuelto"]),
        Decimal(r["saldo"]),
    )


def _autorizada(cliente, *tipos) -> str:
    """CLIENTE_EXTERNO definida, con todos los Detalles autorizados."""
    orden_id = crear(cliente)
    for tipo in tipos:
        agregar(cliente, orden_id, tipo)
    finalizar(cliente, orden_id)
    ok(
        decidir(
            cliente,
            orden_id,
            {f"DET-{i:03d}": "AUTORIZADO" for i in range(1, len(tipos) + 1)},
        )
    )
    return orden_id


def _ejecutar(cliente, orden_id, detalle_id) -> dict:
    ejecucion_id = iniciar(cliente, orden_id, detalle_id)
    return ok(cerrar_ejecucion(cliente, orden_id, ejecucion_id, cantidad=""))


def _hasta_reparacion_lista(cliente, orden_id, *detalles) -> dict:
    tomada(cliente, orden_id)
    orden = {}
    for detalle_id in detalles:
        orden = _ejecutar(cliente, orden_id, detalle_id)
    for detalle_id in detalles:
        orden = ok(aprobar(cliente, orden_id, detalle_id))
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    return orden


def _ultimo_pago(orden: dict) -> dict:
    return orden["pagos"][-1]


def _financieras(orden: dict) -> list[tuple[str, str | None]]:
    return [(a["codigo"], a["pago_id"]) for a in orden["acciones_financieras"]]


# --- 1/2/3. Anticipo, parcial y final ----------------------------------------


def test_1_anticipo_se_registra_sin_mover_el_proceso(cliente):
    orden_id = _autorizada(cliente, T100)
    antes = _orden(cliente, orden_id)["current_process"]

    orden = ok(pagar(cliente, orden_id, "40000", referencia="Seña"))

    pago = _ultimo_pago(orden)
    assert pago["tipo_pago"] == "ANTICIPO"
    assert pago["monto"] == "40000"
    assert pago["metodo"] == "EFECTIVO"
    assert pago["usuario_id"] == RECEPCION
    assert pago["referencia"] == "Seña"
    assert pago["vigente"] is True and pago["anulacion"] is None
    assert orden["current_process"] == antes
    assert orden["historial"][-1]["referencia_id"] == "ACC-REP-020"
    assert _resumen(orden) == (
        Decimal("100000"),
        Decimal("40000"),
        Decimal("0"),
        Decimal("60000"),
    )
    assert orden["resumen"]["situacion_financiera"] == "SALDO_PENDIENTE"
    assert orden["resumen"]["estado_pago"] == "PARCIAL"


def test_2_caso_a_pagos_parciales(cliente):
    orden_id = _autorizada(cliente, T100)
    ok(pagar(cliente, orden_id, "30000"))
    _hasta_reparacion_lista(cliente, orden_id, "DET-001")

    orden = ok(pagar(cliente, orden_id, "40000", metodo="TRANSFERENCIA"))

    assert [p["tipo_pago"] for p in orden["pagos"]] == ["ANTICIPO", "PARCIAL"]
    assert _resumen(orden)[3] == Decimal("30000")
    assert orden["resumen"]["estado_pago"] == "PARCIAL"


def test_3_pago_final_salda_y_permite_entregar(cliente):
    orden_id = _autorizada(cliente, T100)
    _hasta_reparacion_lista(cliente, orden_id, "DET-001")
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )
    assert ids(orden)[-2:] == ["PROC-REP-265", "PROC-REP-266"]

    orden = ok(pagar(cliente, orden_id, "100000", metodo="TARJETA_DEBITO"))

    assert _ultimo_pago(orden)["tipo_pago"] == "FINAL"
    assert orden["puede_entregar"] is True
    assert orden["resumen"]["situacion_financiera"] == "SALDADA"
    entregada = ok(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": ADMINISTRADOR},
        )
    )
    assert entregada["estado_workflow"] == "ENTREGADA"


# --- 4/5/6/7. Medios, importes, sobrepago y duplicados -----------------------


def test_4_medios_de_pago_del_catalogo(cliente, tmp_path):
    medios = ok(cliente.get("/api/catalogs/payment-methods"))
    assert [m["id"] for m in medios] == [
        "EFECTIVO",
        "TRANSFERENCIA",
        "TARJETA_DEBITO",
        "TARJETA_CREDITO",
        "OTRO",
    ]
    orden_id = _autorizada(cliente, T100)
    for medio in ("TRANSFERENCIA", "TARJETA_CREDITO"):
        ok(pagar(cliente, orden_id, "10000", metodo=medio))
    assert "no existe" in conflicto(pagar(cliente, orden_id, "1", "CHEQUE"))

    # El catalogo se configura con un archivo, sin tocar la logica.
    escribir_json_atomico(
        tmp_path / "catalogs" / "medios_pago.json",
        [
            {"id": "EFECTIVO", "nombre": "Efectivo"},
            {"id": "CHEQUE", "nombre": "Cheque", "admite_devolucion": False},
            {"id": "TRANSFERENCIA", "nombre": "Transf.", "activo": False},
        ],
    )
    assert [
        m["id"] for m in ok(cliente.get("/api/catalogs/payment-methods"))
    ] == [
        "EFECTIVO",
        "CHEQUE",
        "TRANSFERENCIA",
    ]
    ok(pagar(cliente, orden_id, "1000", "CHEQUE"))
    assert "no esta activo" in conflicto(
        pagar(cliente, orden_id, "1000", "TRANSFERENCIA")
    )
    orden = _orden(cliente, orden_id)
    assert [p["metodo"] for p in orden["pagos"]] == [
        "TRANSFERENCIA",
        "TARJETA_CREDITO",
        "CHEQUE",
    ]


@pytest.mark.parametrize("monto", ["0", "-10", "abc"])
def test_5_importe_invalido_es_un_request_mal_formado(cliente, monto):
    orden_id = _autorizada(cliente, T100)
    respuesta = pagar(cliente, orden_id, monto)
    assert respuesta.status_code == 422, respuesta.text


def test_5_importe_con_mas_de_dos_decimales(cliente, tmp_path):
    orden_id = _autorizada(cliente, T100)
    antes = archivo(tmp_path, orden_id)

    assert "dos decimales" in conflicto(pagar(cliente, orden_id, "10.005"))

    assert archivo(tmp_path, orden_id) == antes
    orden = ok(pagar(cliente, orden_id, "10.50"))
    assert _resumen(orden)[3] == Decimal("99989.50")


def test_6_no_se_cobra_de_mas(cliente, tmp_path):
    orden_id = _autorizada(cliente, T100)
    assert "supera el saldo" in conflicto(
        pagar(cliente, orden_id, "100000.01")
    )
    ok(pagar(cliente, orden_id, "100000"))
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(pagar(cliente, orden_id, "1"))

    assert "No hay saldo pendiente" in mensaje
    assert archivo(tmp_path, orden_id) == antes
    assert ("REGISTRAR_PAGO", None) not in _financieras(
        _orden(cliente, orden_id)
    )


def test_7_un_pago_repetido_no_se_duplica(cliente, tmp_path):
    orden_id = _autorizada(cliente, T100)
    ok(pagar(cliente, orden_id, "20000", operacion_id="op-1"))
    ok(pagar(cliente, orden_id, "5000", "TRANSFERENCIA", referencia="TRF-77"))
    antes = archivo(tmp_path, orden_id)

    assert "no se duplica" in conflicto(
        pagar(cliente, orden_id, "20000", operacion_id="op-1")
    )
    assert "TRF-77" in conflicto(
        pagar(cliente, orden_id, "5000", "TRANSFERENCIA", referencia="trf-77")
    )

    assert archivo(tmp_path, orden_id) == antes
    assert len(_orden(cliente, orden_id)["pagos"]) == 2


# --- 8/9/10. Anulacion -------------------------------------------------------


def test_8_caso_d_anulacion_conserva_el_pago(cliente):
    orden_id = _autorizada(cliente, T100)
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "50000")))["id"]
    assert ("ANULAR_PAGO", pago_id) in _financieras(_orden(cliente, orden_id))

    orden = ok(anular(cliente, orden_id, pago_id))

    (pago,) = orden["pagos"]
    assert pago["monto"] == "50000"
    assert pago["vigente"] is False
    assert pago["anulacion"]["usuario_id"] == ADMINISTRADOR
    assert pago["anulacion"]["motivo"] == "Cargado dos veces."
    assert _resumen(orden) == (
        Decimal("100000"),
        Decimal("0"),
        Decimal("0"),
        Decimal("100000"),
    )
    paso = orden["historial"][-1]
    assert (paso["referencia_id"], paso["accion"]) == (
        "ACC-REP-021",
        "ANULAR_PAGO",
    )
    assert "Cargado dos veces." in paso["observacion"]
    assert ("ANULAR_PAGO", pago_id) not in _financieras(orden)
    # Se puede volver a cobrar lo que se anulo.
    ok(pagar(cliente, orden_id, "50000"))


def test_9_no_se_anula_dos_veces(cliente):
    orden_id = _autorizada(cliente, T100)
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "50000")))["id"]
    ok(anular(cliente, orden_id, pago_id))
    despues = _orden(cliente, orden_id)

    assert "ya fue anulado" in conflicto(anular(cliente, orden_id, pago_id))

    assert _orden(cliente, orden_id) == despues
    respuesta = anular(cliente, orden_id, "PAG-NO-EXISTE")
    assert respuesta.status_code == 404, respuesta.text
    assert anular(cliente, orden_id, pago_id, motivo="").status_code == 422
    assert "motivo" in conflicto(
        anular(cliente, orden_id, pago_id, motivo="  ")
    )


def test_10_no_se_anula_un_pago_con_devoluciones(cliente):
    orden_id = _autorizada(cliente, T100, T080)
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "150000")))["id"]
    ok(cancelar_detalle(cliente, orden_id, "DET-002"))
    ok(reintegrar(cliente, orden_id, pago_id, "30000"))

    mensaje = conflicto(anular(cliente, orden_id, pago_id))

    assert "devoluciones" in mensaje
    assert ("ANULAR_PAGO", pago_id) not in _financieras(
        _orden(cliente, orden_id)
    )


# --- 11-16. Devoluciones y saldos --------------------------------------------


def test_11_12_16_caso_c_cancelacion_parcial_y_devoluciones(cliente):
    orden_id = _autorizada(cliente, T070, T080)
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "100000")))["id"]

    orden = ok(cancelar_detalle(cliente, orden_id, "DET-002"))

    assert _resumen(orden) == (
        Decimal("70000"),
        Decimal("100000"),
        Decimal("0"),
        Decimal("-30000"),
    )
    assert orden["resumen"]["credito_a_favor"] == "30000"
    assert orden["resumen"]["estado_pago"] == "SALDO_A_FAVOR"
    assert orden["resumen"]["situacion_financiera"] == "SALDO_A_FAVOR"
    assert ("REGISTRAR_DEVOLUCION_DINERO", None) in _financieras(orden)
    assert ("REGISTRAR_PAGO", None) not in _financieras(orden)

    # 11: parcial.
    orden = ok(reintegrar(cliente, orden_id, pago_id, "10000"))
    assert _resumen(orden)[2:] == (Decimal("10000"), Decimal("-20000"))
    (devolucion,) = orden["devoluciones_dinero"]
    assert devolucion["pago_id"] == pago_id
    assert devolucion["medio"] == "EFECTIVO"
    assert devolucion["usuario_id"] == RECEPCION
    assert devolucion["motivo"] == "Se cancelaron trabajos."
    paso = orden["historial"][-1]
    assert (paso["referencia_id"], paso["accion"]) == (
        "ACC-REP-022",
        "REGISTRAR_DEVOLUCION_DINERO",
    )
    # 12: completa.
    orden = ok(
        reintegrar(cliente, orden_id, pago_id, "20000", "TRANSFERENCIA")
    )
    assert _resumen(orden) == (
        Decimal("70000"),
        Decimal("100000"),
        Decimal("30000"),
        Decimal("0"),
    )
    # El anticipo original no cambio.
    (pago,) = orden["pagos"]
    assert (pago["monto"], pago["vigente"]) == ("100000", True)
    assert (pago["devuelto"], pago["devolvible"]) == ("30000", "70000")
    assert ("REGISTRAR_DEVOLUCION_DINERO", None) not in _financieras(orden)

    # Movimientos en orden cronologico.
    finanzas = ok(cliente.get(f"/api/orders/{orden_id}/finances"))
    assert [
        (m["tipo"], m["monto"], m["efecto"]) for m in finanzas["movimientos"]
    ] == [
        ("PAGO", "100000", "-100000"),
        ("DEVOLUCION", "10000", "10000"),
        ("DEVOLUCION", "20000", "20000"),
    ]
    assert finanzas["resumen"]["saldo"] == "0"


def test_13_no_se_devuelve_mas_que_el_credito(cliente, tmp_path):
    orden_id = _autorizada(cliente, T070, T080)
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "100000")))["id"]
    # Sin credito todavia: no hay nada que devolver.
    assert "saldo a favor" in conflicto(
        reintegrar(cliente, orden_id, pago_id, "1")
    )
    ok(cancelar_detalle(cliente, orden_id, "DET-002"))
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(reintegrar(cliente, orden_id, pago_id, "30000.01"))

    assert "supera el saldo a favor" in mensaje
    assert archivo(tmp_path, orden_id) == antes


def test_14_no_se_devuelve_mas_que_lo_que_queda_del_pago(cliente):
    orden_id = _autorizada(cliente, T100)
    primero = _ultimo_pago(ok(pagar(cliente, orden_id, "30000")))["id"]
    segundo = _ultimo_pago(ok(pagar(cliente, orden_id, "70000")))["id"]
    ok(
        cancelar_orden(cliente, orden_id, "El cliente desiste.")
    )  # credito 100000

    mensaje = conflicto(reintegrar(cliente, orden_id, primero, "50000"))

    assert f"del Pago {primero} (30000)" in mensaje
    ok(reintegrar(cliente, orden_id, primero, "30000"))
    assert "(0)" in conflicto(reintegrar(cliente, orden_id, primero, "1"))
    orden = ok(reintegrar(cliente, orden_id, segundo, "70000"))
    assert _resumen(orden)[3] == Decimal("0")


def test_15_caso_b_saldo_despues_de_cancelar_todo(cliente):
    orden_id = _autorizada(cliente, T100)
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "40000")))["id"]

    orden = ok(cancelar_orden(cliente, orden_id, "El cliente desiste."))

    assert orden["estado_workflow"] == "CANCELADA"
    assert _resumen(orden) == (
        Decimal("0"),
        Decimal("40000"),
        Decimal("0"),
        Decimal("-40000"),
    )
    assert "PAGO" not in ",".join(codigos(orden))
    conflicto(pagar(cliente, orden_id, "1"))

    orden = ok(reintegrar(cliente, orden_id, pago_id, "40000"))
    assert _resumen(orden) == (
        Decimal("0"),
        Decimal("40000"),
        Decimal("40000"),
        Decimal("0"),
    )


def test_devolucion_valida_medio_motivo_rol_y_duplicados(cliente, tmp_path):
    orden_id = _autorizada(cliente, T100)
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "40000")))["id"]
    ok(cancelar_orden(cliente, orden_id, "Desiste."))
    escribir_json_atomico(
        tmp_path / "catalogs" / "medios_pago.json",
        [
            {"id": "EFECTIVO", "nombre": "Efectivo"},
            {"id": "CHEQUE", "nombre": "Cheque", "admite_devolucion": False},
        ],
    )
    antes = archivo(tmp_path, orden_id)

    assert "no admite devoluciones" in conflicto(
        reintegrar(cliente, orden_id, pago_id, "1000", "CHEQUE")
    )
    assert "motivo" in conflicto(
        reintegrar(cliente, orden_id, pago_id, "1000", motivo="   ")
    )
    for usuario in (TECNICO, COORDINADOR):
        conflicto(
            reintegrar(cliente, orden_id, pago_id, "1000", usuario=usuario)
        )
    assert archivo(tmp_path, orden_id) == antes

    ok(reintegrar(cliente, orden_id, pago_id, "1000", operacion_id="d-1"))
    assert "no se duplica" in conflicto(
        reintegrar(cliente, orden_id, pago_id, "1000", operacion_id="d-1")
    )
    ok(
        reintegrar(
            cliente,
            orden_id,
            pago_id,
            "500",
            usuario=ADMINISTRADOR,
            referencia="R-1",
        )
    )
    assert "R-1" in conflicto(
        reintegrar(cliente, orden_id, pago_id, "500", referencia="r-1")
    )
    assert len(_orden(cliente, orden_id)["devoluciones_dinero"]) == 2


# --- 17/18/19. Cierre de una Orden cancelada con anticipo --------------------


def test_17_18_devolucion_fisica_antes_que_la_financiera(cliente):
    orden_id = _autorizada(cliente, T100)
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "40000")))["id"]
    orden = ok(cancelar_orden(cliente, orden_id, "Desiste."))
    assert orden["devolucion_pendiente"] is True

    orden = ok(devolver(cliente, orden_id, recibido_por="Cliente"))

    # El equipo se devolvio, pero el dinero no: la Orden sigue abierta.
    assert orden["devolucion"]["recibido_por"] == "Cliente"
    assert orden["devolucion_pendiente"] is False
    assert orden["cerrada"] is False
    assert orden["current_process"] == "PROC-REP-268"
    assert (
        "pendiente de devolver: 40000" in orden["historial"][-1]["observacion"]
    )
    assert codigos(orden) == []
    assert _financieras(orden)[0] == ("REGISTRAR_DEVOLUCION_DINERO", None)
    conflicto(devolver(cliente, orden_id, recibido_por="Otra vez"))

    orden = ok(reintegrar(cliente, orden_id, pago_id, "40000"))

    assert orden["cerrada"] is True
    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["current_process"] == "EVT-REP-999"
    assert ids(orden)[-2:] == ["ACC-REP-022", "PROC-REP-268"]
    assert (
        orden["historial"][-1]["observacion"] == "Sin saldo a favor pendiente"
    )
    conflicto(pagar(cliente, orden_id, "1"), codigo="ORDEN_CERRADA")


def test_19_devolucion_financiera_antes_que_la_fisica(cliente):
    orden_id = _autorizada(cliente, T100)
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "40000")))["id"]
    ok(cancelar_orden(cliente, orden_id, "Desiste."))

    orden = ok(reintegrar(cliente, orden_id, pago_id, "40000"))

    # El dinero se devolvio, pero el equipo no: sigue abierta.
    assert orden["cerrada"] is False
    assert orden["devolucion_pendiente"] is True
    assert codigos(orden) == ["REGISTRAR_DEVOLUCION"]

    orden = ok(devolver(cliente, orden_id, recibido_por="Cliente"))

    assert orden["cerrada"] is True
    assert ids(orden)[-2:] == ["PROC-REP-270", "PROC-REP-268"]
    assert orden["estado_workflow"] == "CANCELADA"


def test_cancelada_sin_custodia_con_seña_espera_la_devolucion(cliente):
    """Seña antes de definir nada; se cancela sin que el equipo quede en
    custodia (sin comprobante): solo falta devolver el dinero."""
    orden_id = crear(cliente)
    orden = ok(pagar(cliente, orden_id, "15000", referencia="Seña revision"))
    assert _ultimo_pago(orden)["tipo_pago"] == "ANTICIPO"
    assert _resumen(orden)[3] == Decimal("-15000")
    pago_id = _ultimo_pago(orden)["id"]

    orden = ok(cancelar_orden(cliente, orden_id, "No deja el equipo."))

    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["devolucion_pendiente"] is False
    assert orden["cerrada"] is False
    assert orden["current_process"] == "PROC-REP-268"

    orden = ok(reintegrar(cliente, orden_id, pago_id, "15000"))
    assert orden["cerrada"] is True


# --- 20/21. Entrega y cierre con saldo distinto de cero ----------------------


def test_20_no_se_entrega_con_saldo_a_favor(cliente):
    orden_id = _autorizada(cliente, T070, T080)
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "100000")))["id"]
    ok(cancelar_detalle(cliente, orden_id, "DET-002"))
    _hasta_reparacion_lista(cliente, orden_id, "DET-001")

    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )

    assert orden["puede_entregar"] is False
    assert (
        orden["historial"][-1]["observacion"]
        == "Saldo -30000: a favor del cliente"
    )
    assert "PROC-REP-266" not in ids(orden)
    mensaje = conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": ADMINISTRADOR},
        )
    )
    assert "saldo a favor del cliente: 30000" in mensaje

    orden = ok(reintegrar(cliente, orden_id, pago_id, "30000"))
    assert orden["puede_entregar"] is True
    assert ids(orden)[-2:] == ["ACC-REP-022", "PROC-REP-265"]
    entregada = ok(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": ADMINISTRADOR},
        )
    )
    assert entregada["estado_workflow"] == "ENTREGADA"


def test_21_no_se_entrega_con_saldo_pendiente(cliente):
    orden_id = _autorizada(cliente, T100)
    ok(pagar(cliente, orden_id, "40000"))
    _hasta_reparacion_lista(cliente, orden_id, "DET-001")
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )

    mensaje = conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": ADMINISTRADOR},
        )
    )

    # Bloqueada en PROC-REP-266 (saldo pendiente): no hay 265 aprobado.
    assert "PROC-REP-266" in mensaje
    assert ids(_orden(cliente, orden_id))[-1] == "PROC-REP-266"
    # Anular un pago en el cierre vuelve a bloquear la entrega.
    orden = ok(pagar(cliente, orden_id, "60000"))
    assert orden["puede_entregar"] is True
    orden = ok(anular(cliente, orden_id, _ultimo_pago(orden)["id"]))
    assert orden["puede_entregar"] is False
    assert ids(orden)[-3:] == ["ACC-REP-021", "PROC-REP-265", "PROC-REP-266"]


# --- 22/23. Orden cerrada y permisos -----------------------------------------


def test_22_no_hay_movimientos_sobre_una_orden_cerrada(cliente, tmp_path):
    orden_id = _autorizada(cliente, T100)
    _hasta_reparacion_lista(cliente, orden_id, "DET-001")
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "100000")))["id"]
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": ADMINISTRADOR},
        )
    )
    antes = archivo(tmp_path, orden_id)

    conflicto(pagar(cliente, orden_id, "1"), codigo="ORDEN_CERRADA")
    conflicto(anular(cliente, orden_id, pago_id), codigo="ORDEN_CERRADA")
    conflicto(
        reintegrar(cliente, orden_id, pago_id, "1"), codigo="ORDEN_CERRADA"
    )

    assert archivo(tmp_path, orden_id) == antes
    assert _orden(cliente, orden_id)["acciones_financieras"] == []


def test_23_permisos_por_rol(cliente, tmp_path):
    orden_id = _autorizada(cliente, T100)
    conflicto(pagar(cliente, orden_id, "1000", usuario=TECNICO))
    for usuario in (RECEPCION, COORDINADOR, ADMINISTRADOR):
        ok(pagar(cliente, orden_id, "1000", usuario=usuario))
    pago_id = _orden(cliente, orden_id)["pagos"][0]["id"]
    antes = archivo(tmp_path, orden_id)

    for usuario in (RECEPCION, COORDINADOR, TECNICO):
        conflicto(anular(cliente, orden_id, pago_id, usuario=usuario))

    assert archivo(tmp_path, orden_id) == antes
    roles = {
        a["codigo"]: a["roles"]
        for a in _orden(cliente, orden_id)["acciones_financieras"]
    }
    assert roles["REGISTRAR_PAGO"] == [
        "ADMINISTRADOR",
        "RECEPCION",
        "COORDINADOR_RMA",
    ]
    assert roles["ANULAR_PAGO"] == ["ADMINISTRADOR"]


def test_otros_origenes_no_tienen_movimientos(tmp_path):
    _sembrar_catalogos(tmp_path, stock="5")
    with TestClient(create_app(Settings(data_dir=tmp_path))) as http:
        orden_id = _crear_orden_rt(http)
        orden = ok(
            definir_y_finalizar(
                http,
                orden_id,
                json={"usuario_id": "RECEP-001", "tipo_reparacion_id": TIPO},
            )
        )
        assert orden["acciones_financieras"] == []
        assert orden["resumen"]["situacion_financiera"] == "NO_COBRABLE"
        conflicto(pagar(http, orden_id, "1"))
        conflicto(reintegrar(http, orden_id, "PAG-X", "1"))


# --- 24. JSON anterior -------------------------------------------------------


def test_24_json_anterior_sin_campos_financieros(cliente, tmp_path):
    orden_id = _autorizada(cliente, T100)
    ok(pagar(cliente, orden_id, "30000"))
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    crudo = json.loads(ruta.read_text(encoding="utf-8"))
    crudo["resumen_pago"].pop("devoluciones")
    for pago in crudo["resumen_pago"]["pagos"]:
        for campo in ("referencia", "operacion_id", "anulacion"):
            pago.pop(campo)
        pago["tipo_pago"] = "PAGO"  # valor anterior a PARCIAL/FINAL
    ruta.write_text(json.dumps(crudo), encoding="utf-8")

    legado = _orden(cliente, orden_id)

    assert legado["pagos"][0]["tipo_pago"] == "PAGO"
    assert legado["pagos"][0]["vigente"] is True
    assert legado["devoluciones_dinero"] == []
    assert _resumen(legado)[3] == Decimal("70000")
    assert isinstance(
        OrdenReparacion.model_validate(json.loads(ruta.read_text("utf-8"))),
        OrdenReparacion,
    )
    # Los derivados no se persisten.
    ok(pagar(cliente, orden_id, "1000"))
    crudo = json.loads(ruta.read_text(encoding="utf-8"))
    assert {"pagado", "devuelto"}.isdisjoint(crudo["resumen_pago"])
    assert "saldo" not in crudo
    ok(anular(cliente, orden_id, legado["pagos"][0]["id"]))
    assert repo_ordenes(tmp_path).obtener(
        orden_id
    ).resumen_pago.pagado == Decimal("1000")


# --- Circuitos por HTTP ------------------------------------------------------


def test_circuito_a_anticipo_ejecucion_pago_final_entrega(cliente):
    orden_id = _autorizada(cliente, T100)
    ok(pagar(cliente, orden_id, "40000", referencia="Seña"))
    _hasta_reparacion_lista(cliente, orden_id, "DET-001")
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )
    assert orden["historial"][-2]["observacion"] == "Saldo 60000"

    orden = ok(pagar(cliente, orden_id, "60000", metodo="TARJETA_CREDITO"))
    assert [p["tipo_pago"] for p in orden["pagos"]] == ["ANTICIPO", "FINAL"]
    entregada = ok(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": ADMINISTRADOR},
        )
    )

    assert entregada["estado_workflow"] == "ENTREGADA"
    assert entregada["cerrada"] is True
    assert entregada["resumen"]["situacion_financiera"] == "SALDADA"


def test_circuito_b_seña_desistimiento_devoluciones_y_cierre(cliente):
    orden_id = crear(cliente)
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "40000")))["id"]
    agregar(cliente, orden_id, T100)
    finalizar(cliente, orden_id)
    ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    assert _resumen(_orden(cliente, orden_id))[3] == Decimal("60000")

    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/withdrawal",
            json={
                "usuario_id": RECEPCION,
                "canal": "TELEFONO",
                "motivo": "Ya no lo quiere.",
            },
        )
    )
    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["resumen"]["credito_a_favor"] == "40000"

    orden = ok(devolver(cliente, orden_id, recibido_por="Cliente"))
    assert orden["cerrada"] is False
    orden = ok(
        reintegrar(cliente, orden_id, pago_id, "40000", "TRANSFERENCIA")
    )

    assert orden["cerrada"] is True
    assert orden["estado_workflow"] == "CANCELADA"
    assert _resumen(orden) == (
        Decimal("0"),
        Decimal("40000"),
        Decimal("40000"),
        Decimal("0"),
    )


def test_circuito_c_autorizacion_parcial_credito_y_entrega(cliente):
    orden_id = crear(cliente)
    agregar(cliente, orden_id, T070)
    agregar(cliente, orden_id, T080)
    finalizar(cliente, orden_id)
    ok(
        decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"})
    )  # DET-002 pendiente
    pago_id = _ultimo_pago(ok(pagar(cliente, orden_id, "100000")))["id"]
    orden = ok(decidir(cliente, orden_id, {"DET-002": "RECHAZADO"}))
    assert _resumen(orden)[3] == Decimal("-30000")

    orden = ok(reintegrar(cliente, orden_id, pago_id, "30000"))
    assert _resumen(orden)[3] == Decimal("0")
    lista = _hasta_reparacion_lista(cliente, orden_id, "DET-001")
    assert lista["resumen"]["situacion_financiera"] == "SALDADA"
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )
    assert orden["puede_entregar"] is True
    entregada = ok(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": ADMINISTRADOR},
        )
    )
    assert entregada["estado_workflow"] == "ENTREGADA"
