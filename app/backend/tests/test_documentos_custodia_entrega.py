"""MVP v2: recepcion fisica, custodia, entrega y documentos.

Cubre los casos 1-24 del alcance y los circuitos A (cliente externo), B
(cancelacion) y C (garantia RMA) por HTTP, con catalogos y datos en
``tmp_path`` y un reloj controlado (la garantia depende de la fecha de
entrega).

Reglas que se verifican:

- comprobante de recepcion != custodia: la custodia se confirma aparte;
- los datos del ingreso se corrigen antes de confirmar, conservando la
  version anterior; despues solo se agregan observaciones;
- la entrega exige custodia confirmada y quien retira; la devolucion por
  cancelacion no convierte la Orden en ENTREGADA;
- los documentos emitidos son snapshots inmutables, versionados y sin
  duplicados por reintento;
- la garantia usa el plazo de cada Detalle desde la entrega efectiva.
"""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services import vencimiento_garantia
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    PANTALLA,
    RECEPCION,
    TECNICO,
    agregar,
    aprobar,
    archivo,
    autorizar_todo,
    cancelar_detalle,
    cancelar_orden,
    conflicto,
    ejecutar,
    finalizar,
    ids,
    ok,
    sembrar,
    tomada,
)

ARGENTINA = timezone(timedelta(hours=-3))
INICIO = datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc)
IMEI = "356938035643809"
ESTADO = "Raya leve en la tapa trasera; pantalla sin marcas."
RETIRA = {
    "recibido_por": "Maria Gomez",
    "identificacion_receptor": "DNI 28111222",
    "observaciones": "Retira la titular; se prueba el equipo en el mostrador.",
}


class Reloj:
    """Reloj del contexto de aplicacion, controlado por el test."""

    def __init__(self, inicio: datetime) -> None:
        self.ahora = inicio

    def __call__(self) -> datetime:
        return self.ahora

    def avanzar(self, **delta) -> None:
        self.ahora += timedelta(**delta)


@pytest.fixture
def reloj():
    return Reloj(INICIO)


@pytest.fixture
def cliente(tmp_path, reloj):
    sembrar(tmp_path)
    app = create_app(Settings(data_dir=tmp_path))
    app.state.contexto = replace(app.state.contexto, ahora=reloj)
    with TestClient(app) as test_client:
        yield test_client


# --- Atajos ------------------------------------------------------------------


def _ingresar(
    cliente,
    *,
    imei=IMEI,
    numero_serie=None,
    estado_fisico=ESTADO,
    accesorios=("Cargador", "Funda"),
    observaciones="El cliente pide conservar los datos.",
) -> str:
    return ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": RECEPCION,
                "cliente": {
                    "nombre": "Maria Gomez",
                    "telefono": "341-555-0101",
                    "email": "maria@example.com",
                },
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 14",
                    "falla_reportada": "La bateria dura poco.",
                    "imei": imei,
                    "numero_serie": numero_serie,
                },
                "recepcion": {
                    "estado_fisico": estado_fisico,
                    "accesorios": list(accesorios),
                    "observaciones": observaciones,
                },
            },
        )
    )["id"]


def _confirmar(cliente, orden_id, observaciones=None, usuario=RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/reception/confirm",
        json={"usuario_id": usuario, "observaciones": observaciones},
    )


def _corregir(cliente, orden_id, **datos):
    return cliente.put(
        f"/api/orders/{orden_id}/reception",
        json={"usuario_id": RECEPCION, **datos},
    )


def _nota(cliente, orden_id, texto):
    return cliente.post(
        f"/api/orders/{orden_id}/reception/notes",
        json={"usuario_id": RECEPCION, "texto": texto},
    )


def _definida(cliente, *tipos, confirmar=True) -> str:
    """Ingreso con datos fisicos, Detalles, definicion y autorizacion."""
    orden_id = _ingresar(cliente)
    if confirmar:
        ok(_confirmar(cliente, orden_id))
    for tipo in tipos or (BATERIA,):
        agregar(cliente, orden_id, tipo)
    finalizar(cliente, orden_id, confirmar_recepcion=False)
    autorizar_todo(cliente, orden_id)
    return orden_id


def _reparada(cliente, orden_id, *detalles) -> dict:
    """Toma, ejecuta y aprueba cada Detalle: REPARACION_LISTA."""
    tomada(cliente, orden_id)
    tipos = {"DET-001": BATERIA, "DET-002": PANTALLA}
    for detalle_id in detalles or ("DET-001",):
        ejecutar(cliente, orden_id, detalle_id, tipos[detalle_id])
    orden = None
    for detalle_id in detalles or ("DET-001",):
        orden = ok(aprobar(cliente, orden_id, detalle_id))
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    return orden


def _notificar(cliente, orden_id) -> dict:
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )


def _pagar(cliente, orden_id, monto, metodo="EFECTIVO") -> dict:
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={"usuario_id": RECEPCION, "monto": monto, "metodo": metodo},
        )
    )


def _devolver_dinero(cliente, orden_id, pago_id, monto) -> dict:
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/refunds",
            json={
                "usuario_id": RECEPCION,
                "pago_id": pago_id,
                "monto": monto,
                "medio": "TRANSFERENCIA",
                "motivo": "Trabajo cancelado.",
            },
        )
    )


def _entregar(cliente, orden_id, usuario=ADMINISTRADOR, **receptor):
    return cliente.post(
        f"/api/orders/{orden_id}/deliver",
        json={"usuario_id": usuario, **receptor},
    )


def _devolver_equipo(cliente, orden_id, **extra):
    return cliente.post(
        f"/api/orders/{orden_id}/return-equipment",
        json={"usuario_id": RECEPCION, "recibido_por": "Maria Gomez", **extra},
    )


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _documentos(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}/documents"))


def _vigente(cliente, orden_id, tipo) -> dict:
    (documento,) = [
        documento
        for documento in _documentos(cliente, orden_id)["emitidos"]
        if documento["tipo"] == tipo and documento["vigente"]
    ]
    return documento


def _lista_y_cobrada(cliente, *tipos) -> str:
    """Reparada, notificada y pagada: lista para entregar."""
    orden_id = _definida(cliente, *tipos)
    _reparada(
        cliente, orden_id, *[f"DET-{i:03d}" for i in range(1, len(tipos) + 1)]
    )
    orden = _notificar(cliente, orden_id)
    _pagar(cliente, orden_id, orden["resumen"]["saldo"])
    return orden_id


def _sin_recepcion(tmp_path, orden_id) -> None:
    """Simula una Orden JSON anterior: sin registro de recepcion."""
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos.pop("recepcion")
    ruta.write_text(json.dumps(datos), encoding="utf-8")


# --- 1/2. Datos fisicos de recepcion -----------------------------------------


def test_1_datos_fisicos_de_recepcion(cliente):
    orden_id = _ingresar(cliente, imei=None, numero_serie="SN-C02XK1")

    orden = _orden(cliente, orden_id)

    # Sin IMEI (no todo equipo lo tiene): alcanza otro identificador.
    assert orden["equipo"]["imei"] is None
    assert orden["equipo"]["numero_serie"] == "SN-C02XK1"
    recepcion = orden["recepcion"]
    assert recepcion["registro"] == "INGRESO"
    assert recepcion["datos"] == {
        "estado_fisico": ESTADO,
        "accesorios": ["Cargador", "Funda"],
        "observaciones": "El cliente pide conservar los datos.",
    }
    assert recepcion["registrado_por"] == RECEPCION
    assert recepcion["registrado_en"].startswith("2026-10-01T13:00")
    # Crear la Orden no prueba que el equipo este en el local.
    assert recepcion["confirmacion"] is None
    assert orden["custodia"]["estado"] == "PENDIENTE_CONFIRMACION"
    assert ok(cliente.get(f"/api/orders/{orden_id}/custody"))["custodia"][
        "estado"
    ] == ("PENDIENTE_CONFIRMACION")


def test_2_accesorios_y_observaciones(cliente, reloj):
    orden_id = _ingresar(cliente, accesorios=("Cargador", "  ", " Funda "))
    assert _orden(cliente, orden_id)["recepcion"]["datos"]["accesorios"] == [
        "Cargador",
        "Funda",
    ]

    reloj.avanzar(minutes=5)
    # Correccion antes de confirmar: conserva la version anterior.
    orden = ok(
        _corregir(
            cliente,
            orden_id,
            estado_fisico="Pantalla astillada en la esquina superior.",
            accesorios=["Cargador", "Funda", "Chip"],
            observaciones="Se recibe con chip.",
            equipo={
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "La bateria dura poco.",
                "imei": "356938035643817",
            },
        )
    )
    recepcion = orden["recepcion"]
    assert recepcion["datos"]["accesorios"] == ["Cargador", "Funda", "Chip"]
    assert orden["equipo"]["imei"] == "356938035643817"
    (anterior,) = recepcion["versiones_anteriores"]
    assert anterior["datos"]["estado_fisico"] == ESTADO
    assert anterior["equipo"]["imei"] == IMEI
    assert anterior["reemplazado_por"] == RECEPCION
    assert ids(orden)[-1] == "ACC-REP-023"
    # Mismos datos otra vez: nada nuevo (un reintento no versiona).
    mismo = ok(
        _corregir(
            cliente,
            orden_id,
            estado_fisico="Pantalla astillada en la esquina superior.",
            accesorios=["Cargador", "Funda", "Chip"],
            observaciones="Se recibe con chip.",
        )
    )
    assert len(mismo["recepcion"]["versiones_anteriores"]) == 1

    ok(_confirmar(cliente, orden_id))
    # Confirmada: los datos no se corrigen, se complementan.
    mensaje = conflicto(_corregir(cliente, orden_id, estado_fisico="Otro"))
    assert "observacion complementaria" in mensaje
    orden = ok(_nota(cliente, orden_id, "El cliente aviso que tiene clave."))
    (nota,) = orden["recepcion"]["notas"]
    assert nota["texto"] == "El cliente aviso que tiene clave."
    assert nota["usuario_id"] == RECEPCION
    assert orden["recepcion"]["datos"]["estado_fisico"].startswith("Pantalla")
    conflicto(_nota(cliente, orden_id, "   "))


# --- 3/4. Comprobante de recepcion -------------------------------------------


def test_3_comprobante_de_recepcion_emitido(cliente):
    orden_id = _ingresar(cliente)
    ok(_confirmar(cliente, orden_id))
    agregar(cliente, orden_id, BATERIA)

    # Antes de PROC-REP-060 solo hay vista previa, que no guarda nada.
    previa = ok(
        cliente.get(
            f"/api/orders/{orden_id}/documents/preview/COMPROBANTE_RECEPCION"
        )
    )
    assert previa["vista_previa"] is True
    assert _documentos(cliente, orden_id)["emitidos"] == []
    conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/documents/reception-receipt",
            json={"usuario_id": RECEPCION},
        )
    )

    finalizar(cliente, orden_id, confirmar_recepcion=False)

    documento = _vigente(cliente, orden_id, "COMPROBANTE_RECEPCION")
    assert documento["id"] == f"{orden_id}-REC-01"
    assert documento["version"] == 1
    assert documento["usuario_id"] == RECEPCION
    contenido = documento["contenido"]
    assert contenido["empresa"]["nombre"] == "Rosario Tecno"
    assert contenido["orden_id"] == orden_id
    assert contenido["fecha_ingreso"].startswith("2026-10-01T13:00")
    assert contenido["cliente"]["nombre"] == "Maria Gomez"
    assert contenido["equipo"]["imei"] == IMEI
    assert contenido["equipo"]["falla_reportada"] == "La bateria dura poco."
    assert contenido["estado_fisico"] == ESTADO
    assert contenido["accesorios"] == ["Cargador", "Funda"]
    assert contenido["registrado_por"] == {
        "id": RECEPCION,
        "nombre": "Recepcion",
    }
    assert contenido["recepcion_fisica"] == "EN_CUSTODIA"
    assert contenido["confirmada_por"]["id"] == RECEPCION
    # Las marcas del proceso siguen igual.
    marcas = _documentos(cliente, orden_id)["marcas"]
    assert marcas["comprobante_recepcion"]["generado"] is True


def test_4_el_comprobante_no_implica_autorizacion_comercial(cliente):
    orden_id = _ingresar(cliente)
    agregar(cliente, orden_id, BATERIA)
    agregar(cliente, orden_id, PANTALLA)
    orden = finalizar(cliente, orden_id, confirmar_recepcion=False)
    # La propuesta queda pendiente de autorizacion del cliente.
    assert {
        d["estado_autorizacion"] for d in orden["reparaciones_detail"]
    } == {"PENDIENTE"}

    contenido = _vigente(cliente, orden_id, "COMPROBANTE_RECEPCION")[
        "contenido"
    ]

    # Ni trabajos ni precios: no presenta la propuesta como aprobada.
    texto = json.dumps(contenido)
    assert "DET-00" not in texto
    assert "80000" not in texto and "50000" not in texto
    assert "No implica autorizacion de reparaciones" in contenido["leyenda"]


# --- 5/6. Custodia independiente del comprobante -----------------------------


def test_5_la_custodia_se_confirma_aparte_del_comprobante(cliente):
    # Comprobante emitido sin custodia confirmada.
    con_comprobante = _ingresar(cliente)
    agregar(cliente, con_comprobante, BATERIA)
    orden = finalizar(cliente, con_comprobante, confirmar_recepcion=False)
    assert orden["custodia"]["comprobante_recepcion_emitido"] is True
    assert orden["custodia"]["estado"] == "PENDIENTE_CONFIRMACION"
    contenido = _vigente(cliente, con_comprobante, "COMPROBANTE_RECEPCION")[
        "contenido"
    ]
    assert contenido["recepcion_fisica"] == "PENDIENTE_CONFIRMACION"
    assert contenido["confirmada_por"] is None

    # Custodia confirmada sin comprobante emitido.
    sin_comprobante = _ingresar(cliente)
    orden = ok(_confirmar(cliente, sin_comprobante, "Queda en el local."))
    assert orden["custodia"]["estado"] == "EN_CUSTODIA"
    assert orden["custodia"]["comprobante_recepcion_emitido"] is False
    assert orden["custodia"]["confirmada_por"] == RECEPCION
    assert orden["custodia"]["confirmada_en"].startswith("2026-10-01")
    assert orden["recepcion"]["confirmacion"]["observaciones"] == (
        "Queda en el local."
    )
    assert ids(orden)[-1] == "ACC-REP-024"
    # Una sola confirmacion; un tecnico no confirma.
    conflicto(_confirmar(cliente, sin_comprobante))
    otra = _ingresar(cliente)
    conflicto(_confirmar(cliente, otra, usuario=TECNICO))
    # Sin estado fisico no se confirma.
    sin_estado = _ingresar(cliente, estado_fisico=None)
    assert "estado fisico" in conflicto(_confirmar(cliente, sin_estado))


def test_6_orden_anterior_se_regulariza_antes_de_entregar(cliente, tmp_path):
    # Una Orden reparada y guardada antes del registro de recepcion.
    orden_id = _definida(cliente)
    _reparada(cliente, orden_id)
    _pagar(
        cliente, orden_id, _notificar(cliente, orden_id)["resumen"]["saldo"]
    )
    _sin_recepcion(tmp_path, orden_id)

    orden = _orden(cliente, orden_id)
    assert orden["recepcion"] is None
    assert orden["custodia"]["estado"] == "SIN_REGISTRO"
    # Ni el comprobante emitido ni la Orden anterior presumen la custodia.
    assert orden["custodia"]["comprobante_recepcion_emitido"] is True
    assert ("REGISTRAR_DATOS_RECEPCION") in [
        accion["codigo"] for accion in orden["acciones_custodia"]
    ]
    mensaje = conflicto(_entregar(cliente, orden_id, **RETIRA))
    assert "anterior al registro de recepcion" in mensaje
    assert "Registra primero" in conflicto(_confirmar(cliente, orden_id))

    orden = ok(_corregir(cliente, orden_id, estado_fisico="Sin danos."))
    assert orden["recepcion"]["registro"] == "REGULARIZACION"
    assert "justifique" in conflicto(_confirmar(cliente, orden_id))
    orden = ok(
        _confirmar(cliente, orden_id, "Equipo verificado en el deposito.")
    )
    assert orden["custodia"]["estado"] == "EN_CUSTODIA"
    assert "Regularizacion" in orden["historial"][-1]["observacion"]

    entregada = ok(_entregar(cliente, orden_id, **RETIRA))
    assert entregada["estado_workflow"] == "ENTREGADA"


# --- 7/8. Documentos inmutables y sin duplicados -----------------------------


def test_7_un_documento_emitido_no_cambia(cliente, reloj, tmp_path):
    orden_id = _ingresar(cliente)
    agregar(cliente, orden_id, BATERIA)
    finalizar(cliente, orden_id, confirmar_recepcion=False)
    original = _vigente(cliente, orden_id, "COMPROBANTE_RECEPCION")

    reloj.avanzar(minutes=10)
    ok(_corregir(cliente, orden_id, estado_fisico="Tapa trasera rota."))

    # El emitido conserva lo que se entrego; la Orden tiene el dato nuevo.
    guardado = ok(
        cliente.get(f"/api/orders/{orden_id}/documents/{original['id']}")
    )
    assert guardado["contenido"] == original["contenido"]
    assert guardado["contenido"]["estado_fisico"] == ESTADO
    previa = ok(
        cliente.get(
            f"/api/orders/{orden_id}/documents/preview/COMPROBANTE_RECEPCION"
        )
    )
    assert previa["contenido"]["estado_fisico"] == "Tapa trasera rota."

    # Version nueva: con motivo, referencia a la anterior y la conserva.
    assert "motivo" in conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/documents/reception-receipt",
            json={"usuario_id": RECEPCION},
        )
    )
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/documents/reception-receipt",
            json={
                "usuario_id": RECEPCION,
                "motivo": "Estado fisico corregido",
            },
        )
    )
    assert [(d["id"], d["vigente"]) for d in orden["documentos_emitidos"]] == [
        (f"{orden_id}-REC-01", False),
        (f"{orden_id}-REC-02", True),
    ]
    nueva = _vigente(cliente, orden_id, "COMPROBANTE_RECEPCION")
    assert nueva["reemplaza_a"] == original["id"]
    assert nueva["motivo"] == "Estado fisico corregido"
    assert nueva["contenido"]["estado_fisico"] == "Tapa trasera rota."
    assert ids(orden)[-1] == "ACC-REP-026"
    assert (
        ok(cliente.get(f"/api/orders/{orden_id}/documents/{original['id']}"))[
            "contenido"
        ]
        == (original["contenido"])
    )
    assert (
        cliente.get(f"/api/orders/{orden_id}/documents/NO-EXISTE").status_code
        == 404
    )


def test_8_un_reintento_no_duplica_documentos(cliente, tmp_path):
    orden_id = _ingresar(cliente)
    agregar(cliente, orden_id, BATERIA)
    finalizar(cliente, orden_id, confirmar_recepcion=False)
    antes = archivo(tmp_path, orden_id)

    # Mismo contenido: devuelve el vigente, sin version ni traza nueva.
    for _ in range(2):
        orden = ok(
            cliente.post(
                f"/api/orders/{orden_id}/documents/reception-receipt",
                json={"usuario_id": RECEPCION, "motivo": "Reimpresion"},
            )
        )
        assert len(orden["documentos_emitidos"]) == 1
    assert archivo(tmp_path, orden_id) == antes

    ok(_confirmar(cliente, orden_id))
    for _ in range(2):
        orden = ok(
            cliente.post(
                f"/api/orders/{orden_id}/documents/reception-receipt",
                json={
                    "usuario_id": RECEPCION,
                    "motivo": "Custodia confirmada",
                },
            )
        )
    assert [d["version"] for d in orden["documentos_emitidos"]] == [1, 2]


# --- 9/10. Entrega con receptor, una sola vez --------------------------------


def test_9_entrega_con_persona_receptora_identificada(cliente):
    orden_id = _lista_y_cobrada(cliente)

    assert "quien retira" in conflicto(_entregar(cliente, orden_id))
    assert "quien retira" in conflicto(
        _entregar(cliente, orden_id, recibido_por="   ")
    )
    orden = ok(_entregar(cliente, orden_id, **RETIRA))

    entrega = orden["entrega"]
    assert entrega == {
        "tipo": "REPARACION_TERMINADA",
        "entregado_por": ADMINISTRADOR,
        "recibido_por": "Maria Gomez",
        "identificacion_receptor": "DNI 28111222",
        "fecha": entrega["fecha"],
        "observaciones": RETIRA["observaciones"],
    }
    assert orden["custodia"]["estado"] == "ENTREGADO"
    paso = orden["historial"][-1]
    assert paso["referencia_id"] == "PROC-REP-270"
    assert paso["observacion"] == "Retira: Maria Gomez (DNI 28111222)"
    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["devolucion"] is None


def test_10_no_se_entrega_dos_veces(cliente, tmp_path):
    orden_id = _lista_y_cobrada(cliente)
    ok(_entregar(cliente, orden_id, **RETIRA))
    antes = archivo(tmp_path, orden_id)

    conflicto(_entregar(cliente, orden_id, **RETIRA), "ORDEN_CERRADA")

    assert archivo(tmp_path, orden_id) == antes
    tipos = [d["tipo"] for d in _documentos(cliente, orden_id)["emitidos"]]
    assert tipos == [
        "COMPROBANTE_RECEPCION",
        "COMPROBANTE_ENTREGA",
        "GARANTIA",
    ]


# --- 11/12/13. Condicion financiera de la entrega ----------------------------


def test_11_no_se_entrega_con_saldo_pendiente(cliente):
    orden_id = _definida(cliente)
    _reparada(cliente, orden_id)
    _notificar(cliente, orden_id)

    mensaje = conflicto(_entregar(cliente, orden_id, **RETIRA))

    # Con saldo la Orden espera el cobro en PROC-REP-266.
    assert "PROC-REP-266" in mensaje
    orden = _orden(cliente, orden_id)
    assert orden["resumen"]["saldo"] == "80000"
    assert orden["entrega"] is None
    assert orden["documentos_emitidos"][-1]["tipo"] == "COMPROBANTE_RECEPCION"


def _con_credito(cliente) -> tuple[str, str]:
    """Anticipo del total y un Detalle cancelado: saldo a favor 50000."""
    orden_id = _definida(cliente, BATERIA, PANTALLA)
    orden = _pagar(cliente, orden_id, "130000", metodo="TARJETA_DEBITO")
    pago_id = orden["pagos"][-1]["id"]
    ok(cancelar_detalle(cliente, orden_id, "DET-002"))
    _reparada(cliente, orden_id, "DET-001")
    orden = _notificar(cliente, orden_id)
    assert orden["resumen"]["saldo"] == "-50000"
    return orden_id, pago_id


def test_12_no_se_entrega_con_credito_a_favor(cliente):
    orden_id, _ = _con_credito(cliente)

    mensaje = conflicto(_entregar(cliente, orden_id, **RETIRA))

    assert "saldo a favor del cliente" in mensaje


def test_13_17_entrega_despues_del_cierre_financiero(cliente):
    orden_id, pago_id = _con_credito(cliente)
    _devolver_dinero(cliente, orden_id, pago_id, "50000")

    orden = ok(_entregar(cliente, orden_id, **RETIRA))

    assert orden["estado_workflow"] == "ENTREGADA"
    contenido = _vigente(cliente, orden_id, "COMPROBANTE_ENTREGA")["contenido"]
    assert contenido["saldo"] == "0"
    assert contenido["total"] == "80000"
    assert [p["monto"] for p in contenido["pagos"]] == ["130000"]
    assert contenido["pagos"][0]["medio"] == "Tarjeta de debito"
    assert [d["monto"] for d in contenido["devoluciones_dinero"]] == ["50000"]
    # 17: el cancelado figura aparte, no realizado ni cobrado.
    assert [t["detalle_id"] for t in contenido["trabajos_realizados"]] == [
        "DET-001"
    ]
    (cancelado,) = contenido["trabajos_cancelados"]
    assert cancelado["detalle_id"] == "DET-002"
    assert cancelado["nombre"] == "Cambio de pantalla"
    assert cancelado["origen_cancelacion"] == "INTERNA"
    garantia = _vigente(cliente, orden_id, "GARANTIA")["contenido"]
    assert [c["detalle_id"] for c in garantia["coberturas"]] == ["DET-001"]


# --- 14/15. Devolucion por cancelacion ---------------------------------------


def test_14_la_devolucion_por_cancelacion_no_es_una_entrega(cliente):
    orden_id = _definida(cliente)
    ok(cancelar_orden(cliente, orden_id))
    # La entrega comercial no aplica a una Orden CANCELADA.
    conflicto(_entregar(cliente, orden_id, **RETIRA))

    orden = ok(
        _devolver_equipo(
            cliente, orden_id, identificacion_receptor="DNI 28111222"
        )
    )

    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["entrega"] is None
    assert orden["devolucion"]["tipo"] == "DEVOLUCION_SIN_REPARACION"
    assert orden["devolucion"]["identificacion_receptor"] == "DNI 28111222"
    assert orden["custodia"]["estado"] == "DEVUELTO"
    assert orden["documentos"]["comprobante_final"]["generado"] is False
    (comprobante,) = [
        d
        for d in _documentos(cliente, orden_id)["emitidos"]
        if d["tipo"] == "COMPROBANTE_ENTREGA"
    ]
    contenido = comprobante["contenido"]
    assert contenido["tipo_entrega"] == "DEVOLUCION_SIN_REPARACION"
    assert contenido["estado_final"] == "CANCELADA"
    assert contenido["trabajos_realizados"] == []
    assert contenido["resultado"].startswith("Orden cancelada")
    assert "GARANTIA" not in [
        d["tipo"] for d in _documentos(cliente, orden_id)["emitidos"]
    ]


def test_15_devolucion_fisica_y_financiera_en_cualquier_orden(cliente):
    # Primero el equipo, despues el dinero.
    primero_equipo = _definida(cliente)
    pago = _pagar(cliente, primero_equipo, "30000")["pagos"][-1]["id"]
    ok(cancelar_orden(cliente, primero_equipo))
    orden = ok(_devolver_equipo(cliente, primero_equipo))
    assert orden["cerrada"] is False  # falta devolver el dinero
    contenido = _vigente(cliente, primero_equipo, "COMPROBANTE_ENTREGA")[
        "contenido"
    ]
    assert contenido["saldo"] == "-30000"
    orden = _devolver_dinero(cliente, primero_equipo, pago, "30000")
    assert orden["cerrada"] is True
    assert orden["estado_workflow"] == "CANCELADA"

    # Primero el dinero, despues el equipo.
    primero_dinero = _definida(cliente)
    pago = _pagar(cliente, primero_dinero, "30000")["pagos"][-1]["id"]
    ok(cancelar_orden(cliente, primero_dinero))
    orden = _devolver_dinero(cliente, primero_dinero, pago, "30000")
    assert orden["cerrada"] is False  # falta devolver el equipo
    assert orden["devolucion_pendiente"] is True
    orden = ok(_devolver_equipo(cliente, primero_dinero))
    assert orden["cerrada"] is True
    assert orden["estado_workflow"] == "CANCELADA"
    contenido = _vigente(cliente, primero_dinero, "COMPROBANTE_ENTREGA")[
        "contenido"
    ]
    assert contenido["saldo"] == "0"


# --- 16. Comprobante final ---------------------------------------------------


def test_16_comprobante_final(cliente, reloj):
    orden_id = _lista_y_cobrada(cliente)
    previa = ok(
        cliente.get(
            f"/api/orders/{orden_id}/documents/preview/COMPROBANTE_ENTREGA"
        )
    )
    assert previa["contenido"]["recibido_por"] is None
    assert previa["contenido"]["fecha_entrega"] is None
    reloj.avanzar(days=2)

    ok(_entregar(cliente, orden_id, **RETIRA))

    documento = _vigente(cliente, orden_id, "COMPROBANTE_ENTREGA")
    assert documento["id"] == f"{orden_id}-ENT-01"
    contenido = documento["contenido"]
    assert contenido["tipo_entrega"] == "REPARACION_TERMINADA"
    assert contenido["estado_final"] == "ENTREGADA"
    assert contenido["fecha_entrega"].startswith("2026-10-03T13:00")
    assert contenido["recibido_por"] == "Maria Gomez"
    assert contenido["identificacion_receptor"] == "DNI 28111222"
    assert contenido["observaciones_entrega"] == RETIRA["observaciones"]
    assert contenido["entregado_por"] == {
        "id": ADMINISTRADOR,
        "nombre": "Administracion",
    }
    assert contenido["trabajos_realizados"] == [
        {
            "detalle_id": "DET-001",
            "tipo_reparacion_id": BATERIA,
            "nombre": "Cambio de bateria",
            "precio": "80000",
            "detalle_origen_id": None,
        }
    ]
    assert contenido["cobrable"] is True
    assert (contenido["total"], contenido["saldo"]) == ("80000", "0")
    assert (
        contenido["resultado"] == "Reparacion terminada y aprobada en control"
    )
    assert contenido["cliente"]["nombre"] == "Maria Gomez"
    assert contenido["equipo"]["imei"] == IMEI


# --- 18/19/20. Garantia ------------------------------------------------------


def test_18_19_cada_trabajo_con_su_plazo(cliente):
    orden_id = _lista_y_cobrada(cliente, BATERIA, PANTALLA)

    ok(_entregar(cliente, orden_id, **RETIRA))

    garantia = _vigente(cliente, orden_id, "GARANTIA")
    assert garantia["id"] == f"{orden_id}-GAR-01"
    coberturas = {
        c["detalle_id"]: (c["nombre"], c["garantia_dias"], c["vence"])
        for c in garantia["contenido"]["coberturas"]
    }
    # 2026-10-01 10:00 en Argentina: + 90 y + 60 dias.
    assert coberturas == {
        "DET-001": ("Cambio de bateria", 90, "2026-12-30"),
        "DET-002": ("Cambio de pantalla", 60, "2026-11-30"),
    }
    assert garantia["contenido"]["condiciones"] is None


def test_20_la_garantia_empieza_con_la_entrega(cliente, reloj):
    orden_id = _definida(cliente)
    _reparada(cliente, orden_id)
    _pagar(
        cliente, orden_id, _notificar(cliente, orden_id)["resumen"]["saldo"]
    )
    # Se retira 18 dias despues de terminado, a las 23:30 de Argentina.
    reloj.ahora = datetime(2026, 10, 20, 2, 30, tzinfo=timezone.utc)

    orden = ok(_entregar(cliente, orden_id, **RETIRA))

    contenido = _vigente(cliente, orden_id, "GARANTIA")["contenido"]
    assert contenido["fecha_inicio"] == orden["entrega"]["fecha"]
    assert contenido["fecha_inicio"].startswith("2026-10-20T02:30")
    # Dia local de la entrega (19/10) + 90, no el de la reparacion (01/10).
    (cobertura,) = contenido["coberturas"]
    assert cobertura["vence"] == "2027-01-17"
    assert vencimiento_garantia(
        datetime(2026, 10, 20, 2, 30, tzinfo=timezone.utc), 90, ARGENTINA
    ) == date(2027, 1, 17)
    assert vencimiento_garantia(None, 90, ARGENTINA) is None
    assert vencimiento_garantia(INICIO, 0, ARGENTINA) is None


# --- 21. Garantia RMA --------------------------------------------------------


def _garantia_rma(cliente, origen_id) -> str:
    """Garantia RMA de DET-001, revisada, definida y autorizada por defecto."""
    rma_id = ok(
        cliente.post(
            f"/api/orders/{origen_id}/warranty-rma",
            json={
                "usuario_id": RECEPCION,
                "detalle_origen_ids": ["DET-001"],
                "recepcion": {
                    "estado_fisico": "Bateria hinchada; sin golpes.",
                    "accesorios": ["Cargador"],
                },
            },
        )
    )["id"]
    ok(
        cliente.post(
            f"/api/orders/{rma_id}/technical-review",
            json={"usuario_id": TECNICO, "resultado": "Bateria defectuosa."},
        )
    )
    ok(
        cliente.post(
            f"/api/orders/{rma_id}/review/details",
            json={
                "usuario_id": RECEPCION,
                "tipo_reparacion_id": BATERIA,
                "detalle_origen_id": "DET-001",
            },
        )
    )
    finalizar(cliente, rma_id, confirmar_recepcion=False)
    return rma_id


def test_21_garantia_rma_vinculada_a_la_orden_original(cliente, tmp_path):
    origen_id = _lista_y_cobrada(cliente)
    ok(_entregar(cliente, origen_id, **RETIRA))
    origen_antes = archivo(tmp_path, origen_id)

    rma_id = _garantia_rma(cliente, origen_id)

    recepcion = _vigente(cliente, rma_id, "COMPROBANTE_RECEPCION")["contenido"]
    assert recepcion["orden_origen_id"] == origen_id
    assert recepcion["detalles_reclamados"][0]["detalle_id"] == "DET-001"
    assert recepcion["detalles_reclamados"][0]["nombre"] == "Cambio de bateria"
    assert "garantia" in recepcion["leyenda"]
    assert recepcion["estado_fisico"] == "Bateria hinchada; sin golpes."

    ok(_confirmar(cliente, rma_id))
    _reparada(cliente, rma_id)
    _notificar(cliente, rma_id)
    orden = ok(_entregar(cliente, rma_id, **RETIRA))

    assert orden["estado_workflow"] == "ENTREGADA"
    final = _vigente(cliente, rma_id, "COMPROBANTE_ENTREGA")["contenido"]
    assert final["cobrable"] is False
    assert final["total"] is None and final["pagos"] == []
    assert final["trabajos_realizados"][0]["precio"] is None
    assert final["trabajos_realizados"][0]["detalle_origen_id"] == "DET-001"
    assert f"Garantia de la Orden {origen_id}: sin cargo" in final["resultado"]
    garantia = _vigente(cliente, rma_id, "GARANTIA")["contenido"]
    assert garantia["orden_origen_id"] == origen_id
    assert [d["detalle_id"] for d in garantia["detalles_reclamados"]] == [
        "DET-001"
    ]
    assert garantia["coberturas"][0]["detalle_origen_id"] == "DET-001"
    # La Orden original no se toca.
    assert archivo(tmp_path, origen_id) == origen_antes


# --- 22/23/24. Orden cerrada, RT_INTERNO y JSON anterior ---------------------


def test_22_una_orden_cerrada_se_consulta_sin_acciones(cliente, tmp_path):
    orden_id = _lista_y_cobrada(cliente)
    ok(_entregar(cliente, orden_id, **RETIRA))
    antes = archivo(tmp_path, orden_id)

    documentos = _documentos(cliente, orden_id)
    assert documentos["cerrada"] is True
    assert len(documentos["emitidos"]) == 3
    for documento in documentos["emitidos"]:
        ok(cliente.get(f"/api/orders/{orden_id}/documents/{documento['id']}"))
    custodia = ok(cliente.get(f"/api/orders/{orden_id}/custody"))
    assert custodia["custodia"]["estado"] == "ENTREGADO"
    assert custodia["custodia"]["salida"]["recibido_por"] == "Maria Gomez"
    assert _orden(cliente, orden_id)["acciones_custodia"] == []
    assert documentos["previsualizables"] == ["COMPROBANTE_RECEPCION"]

    for respuesta in (
        _corregir(cliente, orden_id, estado_fisico="x"),
        _confirmar(cliente, orden_id),
        _nota(cliente, orden_id, "x"),
        cliente.post(
            f"/api/orders/{orden_id}/documents/reception-receipt",
            json={"usuario_id": RECEPCION, "motivo": "x"},
        ),
    ):
        conflicto(respuesta, "ORDEN_CERRADA")
    assert archivo(tmp_path, orden_id) == antes


def test_23_rt_interno_sin_documentos_ni_cobro(cliente):
    orden_id = ok(
        cliente.post(
            "/api/orders/rt-interno",
            json={
                "usuario_id": RECEPCION,
                "equipo": {
                    "marca": "Motorola",
                    "modelo": "Moto G84",
                    "falla_reportada": "No enciende.",
                    "numero_serie": "ZY22H",
                },
                "referencia_rt": "RT-0042",
                "recepcion": {"estado_fisico": "Usado, sin golpes."},
            },
        )
    )["id"]
    orden = _orden(cliente, orden_id)
    # Circuito de Gestion RT: no requiere confirmacion de recepcion.
    assert orden["custodia"]["estado"] == "EN_CUSTODIA"
    assert orden["custodia"]["confirmacion_requerida"] is False
    assert orden["recepcion"]["datos"]["estado_fisico"] == "Usado, sin golpes."
    conflicto(_confirmar(cliente, orden_id))

    agregar(cliente, orden_id, BATERIA)
    finalizar(cliente, orden_id, confirmar_recepcion=False)
    _reparada(cliente, orden_id)
    ok(cliente.post(f"/api/orders/{orden_id}/inform-rt"))
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/return-rt",
            json={"usuario_id": ADMINISTRADOR},
        )
    )

    assert orden["cerrada"] is True
    assert orden["pagos"] == []
    assert orden["custodia"]["estado"] == "DEVUELTO"
    documentos = _documentos(cliente, orden_id)
    assert documentos["emitidos"] == []
    assert documentos["previsualizables"] == []
    conflicto(
        cliente.get(
            f"/api/orders/{orden_id}/documents/preview/COMPROBANTE_RECEPCION"
        )
    )


def test_24_ordenes_json_anteriores_siguen_cargando(cliente, tmp_path):
    entregada = _lista_y_cobrada(cliente)
    ok(_entregar(cliente, entregada, **RETIRA))
    cancelada = _definida(cliente)
    ok(cancelar_orden(cliente, cancelada))
    ok(_devolver_equipo(cliente, cancelada))
    for orden_id in (entregada, cancelada):
        ruta = tmp_path / "ordenes" / f"{orden_id}.json"
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        for campo in ("recepcion", "entrega"):
            datos.pop(campo)
        datos["documentos"].pop("emitidos")
        if datos["devolucion"]:
            datos["devolucion"].pop("tipo")
            datos["devolucion"].pop("identificacion_receptor")
        ruta.write_text(json.dumps(datos), encoding="utf-8")

    orden = _orden(cliente, entregada)
    assert orden["custodia"]["estado"] == "ENTREGADO"
    assert orden["entrega"] is None
    assert orden["documentos"]["comprobante_final"]["generado"] is True
    documentos = _documentos(cliente, entregada)
    # La marca existe, pero no hay copia del documento: no se inventa.
    assert documentos["emitidos"] == []
    assert documentos["marcas"]["garantia_reparacion"]["generado"] is True

    orden = _orden(cliente, cancelada)
    assert orden["devolucion"]["tipo"] == "DEVOLUCION_SIN_REPARACION"
    assert orden["custodia"]["estado"] == "DEVUELTO"


# --- Circuitos ---------------------------------------------------------------


def test_circuito_a_cliente_externo(cliente, reloj):
    """Ingreso con accesorios y estado -> recepcion -> definicion ->
    autorizacion -> reparacion -> control -> pago -> entrega -> comprobante
    final y garantia."""
    orden_id = _ingresar(cliente)
    ok(_confirmar(cliente, orden_id))
    agregar(cliente, orden_id, BATERIA)
    finalizar(cliente, orden_id, confirmar_recepcion=False)
    autorizar_todo(cliente, orden_id)
    reloj.avanzar(hours=3)
    _reparada(cliente, orden_id)
    _pagar(
        cliente, orden_id, _notificar(cliente, orden_id)["resumen"]["saldo"]
    )
    reloj.avanzar(days=1)

    orden = ok(_entregar(cliente, orden_id, **RETIRA))

    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["current_process"] == "EVT-REP-999"
    assert [d["id"] for d in orden["documentos_emitidos"]] == [
        f"{orden_id}-REC-01",
        f"{orden_id}-ENT-01",
        f"{orden_id}-GAR-01",
    ]
    garantia = _vigente(cliente, orden_id, "GARANTIA")["contenido"]
    assert garantia["coberturas"][0]["vence"] == "2026-12-31"


def test_circuito_b_cancelacion(cliente):
    """Ingreso -> recepcion -> anticipo -> desistimiento -> devolucion
    financiera -> devolucion fisica -> cierre CANCELADA."""
    orden_id = _definida(cliente)
    pago_id = _pagar(cliente, orden_id, "40000")["pagos"][-1]["id"]

    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/withdrawal",
            json={
                "usuario_id": RECEPCION,
                "canal": "TELEFONO",
                "motivo": "Ya no quiere repararlo.",
            },
        )
    )
    assert orden["estado_workflow"] == "CANCELADA"
    orden = _devolver_dinero(cliente, orden_id, pago_id, "40000")
    assert orden["devolucion_pendiente"] is True
    orden = ok(
        _devolver_equipo(
            cliente, orden_id, identificacion_receptor="DNI 28111222"
        )
    )

    assert orden["estado_workflow"] == "CANCELADA"
    assert orden["cerrada"] is True
    assert orden["custodia"]["estado"] == "DEVUELTO"
    contenido = _vigente(cliente, orden_id, "COMPROBANTE_ENTREGA")["contenido"]
    assert contenido["tipo_entrega"] == "DEVOLUCION_SIN_REPARACION"
    assert contenido["saldo"] == "0"
    assert {
        t["origen_cancelacion"] for t in contenido["trabajos_cancelados"]
    } == {"DESISTIMIENTO_CLIENTE"}


def test_circuito_c_garantia_rma(cliente, tmp_path):
    """OR original entregada -> garantia RMA vinculada -> revision ->
    reparacion -> entrega sin cobro comercial."""
    origen_id = _lista_y_cobrada(cliente)
    ok(_entregar(cliente, origen_id, **RETIRA))

    rma_id = _garantia_rma(cliente, origen_id)
    # Sin custodia confirmada no se trabaja el equipo, aunque no haya cobro.
    tomada(cliente, rma_id)
    mensaje = conflicto(
        cliente.post(
            f"/api/orders/{rma_id}/details/DET-001/start",
            json={"usuario_id": TECNICO},
        )
    )
    assert "Debe confirmarse la recepcion fisica" in mensaje
    ok(_confirmar(cliente, rma_id, "Se recibio en el mostrador."))
    ejecutar(cliente, rma_id, "DET-001", BATERIA)
    ok(aprobar(cliente, rma_id, "DET-001"))
    _notificar(cliente, rma_id)
    orden = ok(_entregar(cliente, rma_id, **RETIRA))

    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["pagos"] == []
    assert orden["orden_origen_id"] == origen_id
    assert _vigente(cliente, rma_id, "GARANTIA")["contenido"]["coberturas"]
    # El total es nominal: lo que hubiera costado, sin cobro.
    assert orden["resumen"]["condicion_comercial"] == "NO_COBRABLE"
    assert Decimal(orden["resumen"]["total"]) == Decimal("80000")
