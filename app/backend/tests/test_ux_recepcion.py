"""Iteracion de UX de Recepcion (docs/ux-recepcion.md), modo JSON.

- UX-02: el identificador interno del Equipo (``EQP-…``) sale en la Orden y
  en el comprobante, con o sin IMEI; nunca es un IMEI ficticio.
- UX-03 (DEC-UX-03, revisado): el texto unico «Observaciones del equipo» se
  registra como observacion visible con la marca ``observaciones_unificadas``
  y como falla declarada; NO se copia al estado fisico. Ese texto cumple el
  requisito del estado fisico (comprobante y confirmacion de la recepcion).
  Lo registrado antes conserva sus datos separados y su significado.
- UX-04 (DEC-UX-04, revisado): el trabajo inicial se agrega en la misma
  operacion que el alta; si falla, no se crea nada.
- UX-06: el comprobante de ingreso muestra el DNI (o «sin DNI») y tiene un
  espacio para la firma y la aclaracion del cliente.
"""

import re

import pytest

from tests.fixtures.api_salidas import (
    BATERIA,
    PANTALLA,
    RECEPCION,
    agregar,
    cliente_http,
    conflicto,
    ok,
)
from tests.fixtures.ingreso_inicial import del_tipo, generar_ingreso

TEXTO = "No carga. Rayon en la tapa. Sin chip."


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def _cuerpo(*, dni=None, imei=None, unificado=True, trabajo=None) -> dict:
    datos_cliente = {"nombre_apellido": "Ana Gomez", "telefono": "341-555"}
    if dni:
        datos_cliente["dni"] = dni
    equipo = {
        "marca": "Apple",
        "modelo": "iPhone 14",
        "falla_reportada": TEXTO,
    }
    if imei:
        equipo["imei"] = imei
    if unificado:
        # Lo que manda la pantalla: el texto unico, sin estado fisico.
        recepcion = {"observaciones": TEXTO, "observaciones_unificadas": True}
    else:
        equipo["falla_reportada"] = "No carga."
        recepcion = {
            "estado_fisico": "Golpe en la esquina.",
            "observaciones": "Rayon en la tapa.",
        }
    cuerpo = {
        "usuario_id": RECEPCION,
        "cliente": datos_cliente,
        "equipo": equipo,
        "recepcion": recepcion,
    }
    if trabajo:
        cuerpo["trabajo_inicial"] = trabajo
    return cuerpo


def _crear(cliente, **datos) -> dict:
    return ok(cliente.post("/api/orders", json=_cuerpo(**datos)))


def _pdf(cliente, orden_id, agregar_trabajo=True) -> str:
    if agregar_trabajo:
        agregar(cliente, orden_id, BATERIA)
    ok(generar_ingreso(cliente, orden_id))
    (documento,) = del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")
    respuesta = cliente.get(
        f"/api/orders/{orden_id}/documents/{documento['id']}/pdf"
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.content.decode("cp1252")


# --- UX-02 -------------------------------------------------------------------


def test_ux02_sin_imei_el_equipo_tiene_su_identificador(cliente):
    orden = _crear(cliente)
    identificador = orden["equipo"]["id"]
    assert re.fullmatch(r"EQP-[0-9a-f]{12}", identificador)
    assert orden["equipo"].get("imei") in (None, "")
    pdf = _pdf(cliente, orden["id"])
    assert f"({identificador}) Tj" in pdf
    assert "(IMEI:) Tj" not in pdf


def test_ux02_dos_equipos_sin_imei_son_identidades_distintas(cliente):
    assert _crear(cliente)["equipo"]["id"] != _crear(cliente)["equipo"]["id"]


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
                "observaciones": TEXTO,
                "observaciones_unificadas": True,
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
    assert corregida["recepcion"]["datos"]["observaciones_unificadas"] is True
    pdf = _pdf(cliente, orden["id"])
    assert f"({identificador}) Tj" in pdf and "(356789012345678) Tj" in pdf


# --- UX-03 -------------------------------------------------------------------


def test_ux03_el_texto_unico_no_se_copia_al_estado_fisico(cliente):
    datos = _crear(cliente)["recepcion"]["datos"]
    assert datos["observaciones"] == TEXTO
    assert datos["observaciones_unificadas"] is True
    assert datos["estado_fisico"] is None


def test_ux03_el_texto_unico_cumple_el_requisito_del_estado_fisico(cliente):
    """Sin estado fisico aparte, el comprobante se genera y confirma la
    recepcion: el texto unico incluye el estado estetico."""
    orden = _crear(cliente)
    pdf = _pdf(cliente, orden["id"])
    assert pdf.count(TEXTO) == 1
    assert "Observaciones del equipo: " + TEXTO in pdf
    assert "Falla declarada" not in pdf
    assert "Estado físico" not in pdf
    confirmada = ok(cliente.get(f"/api/orders/{orden['id']}"))
    assert confirmada["recepcion"]["confirmacion"] is not None


def test_ux03_sin_marca_un_texto_suelto_no_reemplaza_al_estado_fisico(
    cliente,
):
    """Compatibilidad: sin la marca, observaciones sin estado fisico no
    alcanzan (como antes)."""
    cuerpo = _cuerpo()
    cuerpo["recepcion"] = {"observaciones": TEXTO}
    orden = ok(cliente.post("/api/orders", json=cuerpo))
    agregar(cliente, orden["id"], BATERIA)
    assert "estado fisico" in conflicto(generar_ingreso(cliente, orden["id"]))


def test_ux03_registro_anterior_conserva_sus_datos_separados(cliente):
    orden = _crear(cliente, unificado=False)
    assert orden["recepcion"]["datos"]["observaciones_unificadas"] is False
    pdf = _pdf(cliente, orden["id"])
    assert "Falla declarada: No carga." in pdf
    assert "(Rayon en la tapa.) Tj" in pdf
    assert "(Golpe en la esquina.) Tj" in pdf
    assert "Observaciones del equipo:" not in pdf


# --- UX-04 -------------------------------------------------------------------


def test_ux04_el_trabajo_inicial_se_agrega_en_la_misma_operacion(cliente):
    orden = _crear(cliente, trabajo=BATERIA)
    (detalle,) = orden["reparaciones_detail"]
    assert detalle["tipo_reparacion_id"] == BATERIA
    # El mismo resultado que agregarlo despues con el comando de la Orden.
    otra = _crear(cliente)
    agregada = agregar(cliente, otra["id"], BATERIA)
    (esperado,) = agregada["reparaciones_detail"]
    for campo in (
        "estado",
        "estado_autorizacion",
        "origen_diagnostico",
        "requiere_evaluacion",
        "precio",
    ):
        assert detalle.get(campo) == esperado.get(campo), campo
    pdf = _pdf(cliente, orden["id"], agregar_trabajo=False)
    assert "Cambio de bateria" in pdf


def test_ux04_si_el_trabajo_falla_no_se_crea_nada(cliente):
    antes = ok(cliente.get("/api/orders"))
    for invalido in ("TR-INEXISTENTE", "TR-OTROS"):
        respuesta = cliente.post("/api/orders", json=_cuerpo(trabajo=invalido))
        assert respuesta.status_code in (404, 409), respuesta.text
    assert ok(cliente.get("/api/orders")) == antes
    # Reintentar con un trabajo valido crea UNA Orden, con su trabajo.
    orden = _crear(cliente, trabajo=PANTALLA)
    assert len(orden["reparaciones_detail"]) == 1
    assert len(ok(cliente.get("/api/orders"))) == len(antes) + 1


def test_ux04_rt_interno_tambien_admite_el_trabajo_inicial(cliente):
    orden = ok(
        cliente.post(
            "/api/orders/rt-interno",
            json={
                "usuario_id": RECEPCION,
                "equipo": {
                    "marca": "Motorola",
                    "modelo": "Moto G84",
                    "falla_reportada": TEXTO,
                },
                "referencia_rt": "RT-1",
                "recepcion": {
                    "observaciones": TEXTO,
                    "observaciones_unificadas": True,
                },
                "trabajo_inicial": BATERIA,
            },
        )
    )
    assert [d["tipo_reparacion_id"] for d in orden["reparaciones_detail"]] == [
        BATERIA
    ]


# --- UX-06 -------------------------------------------------------------------


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
