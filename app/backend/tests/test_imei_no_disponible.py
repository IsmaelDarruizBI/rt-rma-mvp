"""Ajustes funcionales, bloque 3: IMEI no disponible e IMEI real
(DEC-AJ-06, BF-05; modo JSON, por HTTP).

- «IMEI no disponible» deja el IMEI vacio (nunca uno ficticio) y el equipo
  se identifica con su ``EQP-…``, aclarado en la Orden y el comprobante.
- «Registrar el IMEI real»: tambien con la custodia confirmada y hasta la
  entrega, con motivo, el permiso de la correccion del ingreso y la misma
  auditoria (version y paso del historial, sin el IMEI en la observacion,
  P1-18). Si el IMEI ya es de otro Equipo avisa y no los vincula (DEC-MI-11).
"""

import json

import pytest

from tests.fixtures import api_salidas as f
from tests.test_ingreso_sin_trabajos import (
    IMEI_REAL,
    MOTIVO_IMEI,
    OTRO_IMEI,
    _crear,
    _custodia,
    _emitidos,
    _entregada,
    _ingreso,
    _orden,
    _pdf,
)


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _registrar_imei(
    cliente,
    orden_id,
    imei=IMEI_REAL,
    motivo=MOTIVO_IMEI,
    usuario=f.RECEPCION,
    confirmado=False,
):
    return cliente.post(
        f"/api/orders/{orden_id}/real-imei",
        json={
            "usuario_id": usuario,
            "imei": imei,
            "motivo": motivo,
            "confirmado": confirmado,
        },
    )


# --- DEC-AJ-06: IMEI no disponible e IMEI real -------------------------------


def test_imei_no_disponible_deja_el_imei_vacio_y_usa_el_identificador(
    cliente,
):
    orden = f.ok(
        _crear(cliente, imei_no_disponible=True, trabajo_inicial=f.BATERIA)
    )

    assert orden["equipo"]["imei"] is None
    assert orden["equipo"]["id"].startswith("EQP-")
    assert orden["recepcion"]["datos"]["imei_no_disponible"] is True
    f.ok(_ingreso(cliente, orden["id"]))
    (ingreso,) = _emitidos(cliente, orden["id"], "COMPROBANTE_INGRESO")
    assert ingreso["contenido"]["imei_no_disponible"] is True
    texto = _pdf(cliente, orden["id"], ingreso["id"])
    assert orden["equipo"]["id"] in texto
    assert "no disponible" in texto and "identificador provisorio" in texto


def test_imei_no_disponible_no_convive_con_un_imei(cliente, tmp_path):
    mensaje = f.conflicto(
        _crear(cliente, imei=IMEI_REAL, imei_no_disponible=True)
    )
    assert "IMEI no disponible" in mensaje
    assert not (tmp_path / "ordenes").exists() or not list(
        (tmp_path / "ordenes").glob("*.json")
    )


def test_el_imei_real_se_registra_con_la_custodia_confirmada(cliente):
    orden = f.ok(
        _crear(cliente, imei_no_disponible=True, trabajo_inicial=f.BATERIA)
    )
    orden_id, equipo_id = orden["id"], orden["equipo"]["id"]
    orden = f.ok(_ingreso(cliente, orden_id))
    assert orden["custodia"]["estado"] == "EN_CUSTODIA"
    assert "REGISTRAR_IMEI_REAL" in _custodia(orden)
    (ingreso,) = _emitidos(cliente, orden_id, "COMPROBANTE_INGRESO")
    datos_antes = orden["recepcion"]["datos"]

    # Sin motivo no se registra.
    respuesta = _registrar_imei(cliente, orden_id, motivo="  ")
    assert respuesta.status_code in (409, 422), respuesta.text

    orden = f.ok(_registrar_imei(cliente, orden_id, imei=f" {IMEI_REAL} "))

    assert orden["equipo"]["imei"] == IMEI_REAL
    # El identificador interno no cambia ni se fusiona con otro Equipo.
    assert orden["equipo"]["id"] == equipo_id
    # Auditoria como las correcciones del ingreso: version con motivo y
    # el cambio; los datos de la recepcion ya decididos no cambian.
    version = orden["recepcion"]["versiones_anteriores"][-1]
    assert version["motivo"] == MOTIVO_IMEI
    assert version["reemplazado_por"] == f.RECEPCION
    assert version["equipo"]["imei"] is None
    assert version["cambios"] == [
        {"campo": "equipo.imei", "anterior": None, "nuevo": IMEI_REAL}
    ]
    assert orden["recepcion"]["datos"] == datos_antes
    paso = orden["historial"][-1]
    assert (paso["referencia_id"], paso["accion"]) == (
        "ACC-REP-023",
        "REGISTRAR_IMEI_REAL",
    )
    assert MOTIVO_IMEI in paso["observacion"]
    # El IMEI no va al historial (P1-18).
    assert IMEI_REAL not in paso["observacion"]
    # El comprobante emitido no cambia.
    (despues,) = _emitidos(cliente, orden_id, "COMPROBANTE_INGRESO")
    assert despues["contenido"] == ingreso["contenido"]
    # Ya tiene IMEI: la accion no se ofrece y no se registra otro.
    assert "REGISTRAR_IMEI_REAL" not in _custodia(orden)
    assert "ya tiene IMEI" in f.conflicto(
        _registrar_imei(cliente, orden_id, imei=OTRO_IMEI)
    )


def test_registrar_el_imei_real_exige_el_permiso_de_correccion(cliente):
    orden_id = f.ok(_crear(cliente, imei_no_disponible=True))["id"]
    f.conflicto(_registrar_imei(cliente, orden_id, usuario=f.TECNICO))
    # Coordinacion RMA corrige el ingreso (DEC-MI-07).
    orden = f.ok(_registrar_imei(cliente, orden_id, usuario=f.COORDINADOR))
    assert orden["equipo"]["imei"] == IMEI_REAL


def test_el_imei_real_no_se_registra_despues_de_la_entrega(cliente):
    orden = _entregada(cliente, verificadas=True, checkin=True)
    assert orden["equipo"]["imei"] is None
    assert orden["estado_workflow"] == "ENTREGADA"
    assert "REGISTRAR_IMEI_REAL" not in _custodia(orden)

    respuesta = _registrar_imei(cliente, orden["id"])

    assert respuesta.status_code == 409, respuesta.text
    assert _orden(cliente, orden["id"])["equipo"]["imei"] is None


def test_un_imei_de_otro_equipo_avisa_y_no_vincula(cliente, tmp_path):
    otra = f.ok(_crear(cliente, imei=IMEI_REAL))
    orden = f.ok(_crear(cliente, imei_no_disponible=True))
    orden_id = orden["id"]
    antes = f.archivo(tmp_path, orden_id)

    respuesta = _registrar_imei(cliente, orden_id)

    mensaje = f.conflicto(respuesta, "CONFIRMACION_REQUERIDA")
    assert otra["equipo"]["id"] in mensaje
    assert IMEI_REAL not in mensaje
    assert f.archivo(tmp_path, orden_id) == antes

    registrada = f.ok(_registrar_imei(cliente, orden_id, confirmado=True))

    assert registrada["equipo"]["imei"] == IMEI_REAL
    # No se fusiona: sigue siendo su propio Equipo.
    assert registrada["equipo"]["id"] == orden["equipo"]["id"]
    assert registrada["equipo"]["id"] != otra["equipo"]["id"]
    assert otra["equipo"]["id"] in registrada["historial"][-1]["observacion"]
    guardada = json.loads(f.archivo(tmp_path, orden_id))
    assert guardada["equipo"]["imei"] == IMEI_REAL
