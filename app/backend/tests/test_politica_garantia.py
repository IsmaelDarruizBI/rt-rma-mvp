"""Politica de garantia por Tipo de Reparacion (DEC-MI-01) y correccion del
check-in (DEC-MI-05).

- Cada Tipo configura el plazo con check-in realizado y no realizado; el
  Detalle copia esa politica al definirse.
- El check-in se exige para entregar solo si algun trabajo realizado tiene
  garantia mayor a cero.
- Trabajos dentro de una garantia RMA: nuevo plazo, plazo restante o sin
  garantia, segun la politica del Tipo. Sin definir (ABI-38), como antes.
- Corregir un check-in ya registrado exige motivo.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests import test_api_hp_rep_003 as hp3
from tests.fixtures.custodia import entregar, registrar_checkin
from tests.test_api_hp_rep_002 import (
    ADMINISTRADOR,
    RECEPCION,
    TIPO,
    _sembrar_catalogos,
)


def _cliente(directorio, **politica):
    _sembrar_catalogos(directorio)
    ruta = directorio / "catalogs" / "tipos_reparacion.json"
    tipos = json.loads(ruta.read_text("utf-8"))
    for tipo in tipos:
        if tipo["id"] == TIPO:
            tipo.update(politica)
    ruta.write_text(json.dumps(tipos), "utf-8")
    return TestClient(create_app(Settings(data_dir=directorio)))


def _entregar_garantia(cliente, origen_id) -> dict:
    respuesta = hp3._garantia_definida(cliente, origen_id)
    assert respuesta.status_code == 200, respuesta.text
    orden_id = respuesta.json()["id"]
    hp3._circuito_tecnico(cliente, orden_id)
    cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
    )
    entregada = entregar(cliente, orden_id, ADMINISTRADOR)
    assert entregada.status_code == 200, entregada.text
    return entregada.json()


def _garantia(orden, detalle="DET-001") -> int:
    (d,) = [x for x in orden["reparaciones_detail"] if x["id"] == detalle]
    return d["garantia_dias"]


def test_los_plazos_del_tipo_segun_el_checkin(tmp_path):
    with _cliente(
        tmp_path, garantia_con_checkin=120, garantia_sin_checkin=45
    ) as cliente:
        origen = hp3._orden_entregada(cliente)
        # entregar() registra el check-in realizado si falta.
        assert _garantia(origen) == 120
        assert origen["recepcion"]["registros_checkin"][-1]["realizado"]


@pytest.mark.parametrize(
    ("politica", "esperada"),
    [
        ("SIN_GARANTIA", 0),
        ("PLAZO_RESTANTE", 120),
        ("NUEVO_PLAZO", 90),
        (None, 90),
    ],
)
def test_politica_de_los_trabajos_en_garantia_rma(
    tmp_path, politica, esperada
):
    with _cliente(
        tmp_path,
        garantia_dias=90,
        garantia_con_checkin=120,
        politica_garantia_rma=politica,
    ) as cliente:
        origen = hp3._orden_entregada(cliente)
        assert _garantia(origen) == 120
        garantia = _entregar_garantia(cliente, origen["id"])
        assert garantia["estado_workflow"] == "ENTREGADA"
        assert _garantia(garantia) == esperada


def test_sin_garantia_no_se_exige_el_checkin(tmp_path):
    with _cliente(
        tmp_path,
        garantia_dias=0,
        garantia_con_checkin=0,
        garantia_sin_checkin=0,
    ) as cliente:
        origen = hp3._orden_entregada(cliente)
        assert origen["estado_workflow"] == "ENTREGADA"
        assert origen["recepcion"]["registros_checkin"] == []
        assert _garantia(origen) == 0


def test_corregir_el_checkin_exige_motivo(tmp_path):
    with _cliente(tmp_path) as cliente:
        orden = cliente.post(
            "/api/orders",
            json={
                "usuario_id": RECEPCION,
                "cliente": {"nombre": "Cliente", "telefono": "341-0"},
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 14",
                    "falla_reportada": "No carga.",
                },
            },
        ).json()
        orden_id = orden["id"]
        hp3.definir_y_finalizar(
            cliente,
            orden_id,
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": TIPO},
        )
        hp3._circuito_tecnico(cliente, orden_id)
        assert registrar_checkin(cliente, orden_id, False).status_code == 200
        sin_motivo = registrar_checkin(cliente, orden_id, True)
        assert sin_motivo.status_code == 409
        assert "motivo" in sin_motivo.json()["error"]["mensaje"]
        corregido = registrar_checkin(
            cliente, orden_id, True, motivo="Se probo con otro cargador."
        )
        assert corregido.status_code == 200, corregido.text
        registros = corregido.json()["recepcion"]["registros_checkin"]
        assert [(r["realizado"], r.get("motivo")) for r in registros] == [
            (False, None),
            (True, "Se probo con otro cargador."),
        ]
        assert _garantia(corregido.json()) == 90
