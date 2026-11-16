"""Iteracion de UX de Recepcion (docs/ux-recepcion.md), modo JSON.

- UX-02: el identificador interno del Equipo (``EQP-…``) sale en la Orden y
  en el comprobante, con o sin IMEI; nunca es un IMEI ficticio.
- UX-03: con un solo texto («Observaciones del equipo») el comprobante lo
  muestra una vez; las Ordenes anteriores, con textos distintos, siguen
  mostrando «Falla declarada» y «Observaciones» por separado.
- UX-06: el comprobante de ingreso muestra el DNI (o «sin DNI») y tiene un
  espacio para la firma y la aclaracion del cliente.
"""

import re

import pytest

from tests.fixtures.api_salidas import (
    BATERIA,
    RECEPCION,
    agregar,
    cliente_http,
    ok,
)
from tests.fixtures.ingreso_inicial import del_tipo, generar_ingreso

TEXTO = "No carga. Rayon en la tapa. Sin chip."


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def _crear(cliente, *, dni=None, imei=None, falla=TEXTO, observaciones=TEXTO):
    datos_cliente = {"nombre_apellido": "Ana Gomez", "telefono": "341-555"}
    if dni:
        datos_cliente["dni"] = dni
    equipo = {
        "marca": "Apple",
        "modelo": "iPhone 14",
        "falla_reportada": falla,
    }
    if imei:
        equipo["imei"] = imei
    return ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": RECEPCION,
                "cliente": datos_cliente,
                "equipo": equipo,
                # UX-03: la pantalla manda el mismo texto como falla,
                # estado fisico y observacion visible.
                "recepcion": {
                    "observaciones": observaciones,
                    "estado_fisico": observaciones,
                },
            },
        )
    )


def _pdf(cliente, orden_id) -> str:
    agregar(cliente, orden_id, BATERIA)
    ok(generar_ingreso(cliente, orden_id))
    (documento,) = del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")
    respuesta = cliente.get(
        f"/api/orders/{orden_id}/documents/{documento['id']}/pdf"
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.content.decode("cp1252")


def test_ux02_sin_imei_el_equipo_tiene_su_identificador(cliente):
    orden = _crear(cliente)
    identificador = orden["equipo"]["id"]
    assert re.fullmatch(r"EQP-[0-9a-f]{12}", identificador)
    assert orden["equipo"].get("imei") in (None, "")
    pdf = _pdf(cliente, orden["id"])
    assert f"({identificador}) Tj" in pdf
    assert "(IMEI:) Tj" not in pdf


def test_ux02_dos_equipos_sin_imei_son_identidades_distintas(cliente):
    primero = _crear(cliente)["equipo"]["id"]
    segundo = _crear(cliente)["equipo"]["id"]
    assert primero != segundo


def test_ux03_observaciones_unificadas_salen_una_vez(cliente):
    pdf = _pdf(cliente, _crear(cliente)["id"])
    assert pdf.count(TEXTO) == 1
    assert "Observaciones del equipo: " + TEXTO in pdf
    assert "Falla declarada" not in pdf
    assert "Estado físico" not in pdf


def test_ux03_orden_anterior_conserva_sus_dos_textos(cliente):
    orden = _crear(
        cliente, falla="No carga.", observaciones="Rayon en la tapa."
    )
    pdf = _pdf(cliente, orden["id"])
    assert "Falla declarada: No carga." in pdf
    assert "(Rayon en la tapa.) Tj" in pdf
    assert "(Estado físico:) Tj" in pdf
    assert "Observaciones del equipo" not in pdf


def test_ux06_comprobante_con_dni_identificador_y_firma(cliente):
    orden = _crear(cliente, dni="30111222", imei="356789012345678")
    pdf = _pdf(cliente, orden["id"])
    assert "(30111222) Tj" in pdf
    assert "(356789012345678) Tj" in pdf
    assert f"({orden['equipo']['id']}) Tj" in pdf
    assert "(Conformidad del cliente con la recepción del equipo) Tj" in pdf
    for etiqueta in ("Firma", "Aclaración"):
        assert f"({etiqueta}) Tj" in pdf


def test_ux06_sin_dni_lo_dice_y_no_lo_inventa(cliente):
    pdf = _pdf(cliente, _crear(cliente)["id"])
    assert "(sin DNI) Tj" in pdf


def test_ux02_el_imei_real_se_asocia_despues_y_conserva_el_identificador(
    cliente,
):
    orden = _crear(cliente)
    identificador = orden["equipo"]["id"]
    corregida = ok(
        cliente.put(
            f"/api/orders/{orden['id']}/reception",
            json={
                "usuario_id": RECEPCION,
                "estado_fisico": TEXTO,
                "observaciones": TEXTO,
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 14",
                    "falla_reportada": TEXTO,
                    "imei": "356789012345678",
                },
            },
        )
    )
    assert corregida["equipo"]["id"] == identificador
    assert corregida["equipo"]["imei"] == "356789012345678"
    # La version anterior (sin IMEI) queda en el historial del ingreso.
    anteriores = corregida["recepcion"]["versiones_anteriores"]
    assert anteriores and not anteriores[-1]["equipo"].get("imei")
    pdf = _pdf(cliente, orden["id"])
    assert f"({identificador}) Tj" in pdf and "(356789012345678) Tj" in pdf
