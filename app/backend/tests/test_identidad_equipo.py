"""Identidad del Equipo (DEC-MI-11).

- Se busca por IMEI; si no hay coincidencias, por numero de serie.
  Coincidencia exacta: nunca por similitud.
- Recepcion elige el Equipo (su ID) o «Ninguno» (sin ID: identidad nueva).
  Reusar una identidad exige compartir el IMEI o el numero de serie.
- El historial de una identidad son todas sus Ordenes.
- Una vinculacion erronea se corrige con motivo y queda auditada.
"""

import pytest

from tests.fixtures import api_salidas as f


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _ingresar(cliente, **equipo) -> dict:
    return cliente.post(
        "/api/orders",
        json={
            "usuario_id": f.RECEPCION,
            "cliente": {"nombre_apellido": "Ana Perez", "telefono": "341-1"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "No carga.",
                **equipo,
            },
        },
    )


def _identificar(cliente, **params) -> dict:
    return f.ok(cliente.get("/api/equipment/identify", params=params))


def test_identificar_por_imei_despues_por_serie_nunca_por_similitud(
    cliente,
):
    primera = f.ok(_ingresar(cliente, imei="356 111", numero_serie="S-1"))
    equipo_id = primera["equipo"]["id"]

    por_imei = _identificar(cliente, imei="356111", numero_serie="OTRA")
    assert por_imei["criterio"] == "IMEI"
    assert [c["equipo_id"] for c in por_imei["candidatos"]] == [equipo_id]
    assert por_imei["candidatos"][0]["ordenes"] == [primera["id"]]

    por_serie = _identificar(cliente, imei="999", numero_serie="s-1")
    assert por_serie["criterio"] == "NUMERO_SERIE"
    # Parecido no es igual.
    assert _identificar(cliente, imei="35611") == {
        "criterio": None,
        "candidatos": [],
    }
    assert _identificar(cliente) == {"criterio": None, "candidatos": []}


def test_reusar_la_identidad_exige_el_mismo_imei_o_serie(cliente):
    primera = f.ok(_ingresar(cliente, imei="356111"))
    equipo_id = primera["equipo"]["id"]

    assert "similitud" in f.conflicto(
        _ingresar(cliente, id=equipo_id, imei="356222")
    )
    segunda = f.ok(_ingresar(cliente, id=equipo_id, imei="356111"))
    assert segunda["equipo"]["id"] == equipo_id
    # «Ninguno»: sin ID, identidad nueva aunque el IMEI coincida.
    tercera = f.ok(_ingresar(cliente, imei="356111"))
    assert tercera["equipo"]["id"] != equipo_id

    historial = f.ok(cliente.get(f"/api/equipment/{equipo_id}/orders"))
    assert [o["orden_id"] for o in historial["ordenes"]] == [
        segunda["id"],
        primera["id"],
    ]


def test_corregir_una_vinculacion_erronea(cliente):
    primera = f.ok(_ingresar(cliente, imei="356111"))
    equipo_id = primera["equipo"]["id"]
    segunda = f.ok(_ingresar(cliente, id=equipo_id, imei="356111"))
    ruta = f"/api/orders/{segunda['id']}/equipment-link"

    f.conflicto(
        cliente.post(
            ruta, json={"usuario_id": f.TECNICO, "motivo": "Era otro."}
        )
    )
    assert (
        cliente.post(ruta, json={"usuario_id": f.RECEPCION}).status_code == 422
    )
    assert (
        cliente.post(
            ruta,
            json={
                "usuario_id": f.RECEPCION,
                "equipo_id": "EQP-NO",
                "motivo": "x",
            },
        ).status_code
        == 404
    )

    orden = f.ok(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.COORDINADOR,
                "motivo": "El cliente trajo otro equipo con IMEI repetido.",
            },
        )
    )
    nuevo = orden["equipo"]["id"]
    assert nuevo != equipo_id
    (correccion,) = orden["correcciones_equipo"]
    assert (
        correccion["equipo_anterior_id"],
        correccion["equipo_nuevo_id"],
        correccion["usuario_id"],
    ) == (equipo_id, nuevo, f.COORDINADOR)
    # El historial de cada identidad queda con lo suyo.
    assert [
        o["orden_id"]
        for o in f.ok(cliente.get(f"/api/equipment/{equipo_id}/orders"))[
            "ordenes"
        ]
    ] == [primera["id"]]
    assert [
        o["orden_id"]
        for o in f.ok(cliente.get(f"/api/equipment/{nuevo}/orders"))["ordenes"]
    ] == [segunda["id"]]
