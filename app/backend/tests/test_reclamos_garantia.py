"""Reclamos de garantia rechazados y su continuacion paga (DEC-MI-02; cierra
ABI-35 y ABI-34).

- Un reclamo rechazado queda registrado aparte (Orden original, trabajos,
  equipo, vigencia evaluada, motivo, excepciones pedidas, usuario y
  fecha); la Orden original no cambia y no se crea la Orden de garantia.
- Recepcion lo continua como reparacion paga de CLIENTE_EXTERNO con
  confirmacion, una sola vez, con cliente, equipo y falla precargados.
- Lo consultan Recepcion, Coordinacion RMA y Administracion.
"""

import pytest

from tests import test_autenticacion as auth
from tests.fixtures import api_salidas as f
from tests.fixtures import iteracion1 as it

app_supabase = auth.app_supabase


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


@pytest.fixture
def reloj(cliente):
    return it.instalar_reloj(cliente)


def test_un_reclamo_rechazado_se_registra_y_se_continua_una_vez(
    cliente, reloj
):
    origen = it.entregada_hace(cliente, reloj, 200)
    antes = f.ok(cliente.get(f"/api/orders/{origen}"))
    cantidad = len(f.ok(cliente.get("/api/orders")))

    respuesta = it.iniciar_garantia(cliente, origen)
    assert respuesta.status_code == 409
    error = respuesta.json()["error"]
    assert error["codigo"] == "GARANTIA_VENCIDA"
    reclamo_id = error["reclamo_id"]
    assert reclamo_id == "RGA-000001"
    # No se creo la Orden de garantia y la original no cambio.
    assert len(f.ok(cliente.get("/api/orders"))) == cantidad
    assert f.ok(cliente.get(f"/api/orders/{origen}")) == antes

    reclamo = f.ok(cliente.get(f"/api/warranty-claims/{reclamo_id}"))
    assert reclamo["orden_origen_id"] == origen
    assert reclamo["detalles_reclamados"] == ["DET-001"]
    assert reclamo["usuario_id"] == f.RECEPCION
    assert reclamo["resultado"] == "RECHAZADO"
    assert "vencida" in reclamo["motivo"]
    (vigencia,) = reclamo["vigencias"]
    assert vigencia["detalle_id"] == "DET-001"
    assert vigencia["vigente"] is False
    assert reclamo["equipo"]["modelo"] == antes["equipo"]["modelo"]
    assert reclamo["orden_continuacion_id"] is None
    assert [r["id"] for r in f.ok(cliente.get("/api/warranty-claims"))] == [
        reclamo_id
    ]

    def continuar(usuario=f.RECEPCION, confirmado=True):
        return cliente.post(
            f"/api/warranty-claims/{reclamo_id}/continue",
            json={"usuario_id": usuario, "confirmado": confirmado},
        )

    assert "confirmarlo" in f.conflicto(continuar(confirmado=False))
    f.conflicto(continuar(usuario=f.TECNICO))

    resultado = f.ok(continuar())
    nueva = f.ok(cliente.get(f"/api/orders/{resultado['orden_id']}"))
    assert nueva["origen"] == "CLIENTE_EXTERNO"
    assert nueva["cliente"]["id"] == antes["cliente"]["id"]
    assert nueva["equipo"]["modelo"] == antes["equipo"]["modelo"]
    assert nueva["equipo"]["id"] != antes["equipo"]["id"]
    assert (
        nueva["equipo"]["falla_reportada"]
        == antes["equipo"]["falla_reportada"]
    )
    assert reclamo_id in nueva["historial"][-1]["observacion"]
    assert resultado["reclamo"]["orden_continuacion_id"] == nueva["id"]
    assert resultado["reclamo"]["continuado_por"] == f.RECEPCION

    # Una sola vez: no se duplica la Orden.
    assert nueva["id"] in f.conflicto(continuar())
    assert f.ok(cliente.get(f"/api/orders/{origen}")) == antes


def test_con_sesion_solo_consultan_los_roles_habilitados(app_supabase):
    from fastapi.testclient import TestClient

    cliente = TestClient(app_supabase)
    for usuario, estado in (
        (f.TECNICO, 403),
        (f.RECEPCION, 200),
        (f.COORDINADOR, 200),
        (f.ADMINISTRADOR, 200),
    ):
        respuesta = cliente.get(
            "/api/warranty-claims", headers=auth.sesion(usuario)
        )
        assert respuesta.status_code == estado, (usuario, respuesta.text)
