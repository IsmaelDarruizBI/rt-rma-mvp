"""Motivos operativos (DEC-MI-15) y retiro demorado (DEC-MI-14).

- Cancelar o interrumpir con un motivo del catalogo de su tipo; «Otro»
  exige descripcion; sin motivo de catalogo, el texto libre de siempre. El
  texto registrado copia el nombre del motivo.
- Retiro demorado: vencido el plazo desde el aviso de equipo listo, la
  Orden se alerta en las bandejas y admite seguimientos; sigue abierta.
"""

from datetime import timedelta

import pytest

from tests.fixtures import api_salidas as f
from tests.fixtures import iteracion1 as it


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _cancelar(cliente, orden_id, **cuerpo):
    return cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/cancel",
        json={"usuario_id": f.RECEPCION, **cuerpo},
    )


def test_motivos_de_catalogo_y_texto_libre(cliente):
    motivos = f.ok(cliente.get("/api/catalogs/reasons?tipo=CANCELACION"))
    assert [(m["codigo"], m["requiere_descripcion"]) for m in motivos] == [
        ("CANC-OTRO", True)
    ]
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)

    assert "exige una descripcion" in f.conflicto(
        _cancelar(cliente, orden_id, motivo_codigo="CANC-OTRO")
    )
    assert "No existe el motivo" in f.conflicto(
        _cancelar(cliente, orden_id, motivo_codigo="INT-OTRO", motivo="x")
    )
    # Sin motivo ni catalogo: invalido.
    assert _cancelar(cliente, orden_id).status_code == 422

    orden = f.ok(
        _cancelar(
            cliente,
            orden_id,
            motivo_codigo="CANC-OTRO",
            motivo="El cliente vende el equipo.",
        )
    )
    cancelacion = f.detalle(orden, "DET-001")["cancelacion"]
    assert cancelacion["motivo"] == "Otro: El cliente vende el equipo."

    # Texto libre, como siempre.
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-002/cancel",
            json={"usuario_id": f.RECEPCION, "motivo": "Duplicado."},
        )
    )
    assert f.detalle(orden, "DET-002")["cancelacion"]["motivo"] == "Duplicado."


def test_la_configuracion_operativa_es_de_solo_lectura_en_json(cliente):
    datos = f.ok(cliente.get("/api/admin/parameters"))
    assert datos == {
        "editable": False,
        "parametros": {"PLAZO_RETIRO_DIAS": "30"},
    }
    assert "PostgreSQL" in f.conflicto(
        cliente.put(
            "/api/admin/parameters/PLAZO_RETIRO_DIAS",
            json={"usuario_id": f.ADMINISTRADOR, "valor": "10"},
        )
    )
    assert f.ok(cliente.get("/api/admin/reasons"))["editable"] is False


def _lista_y_avisada(cliente) -> str:
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id, "DET-001", f.BATERIA)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": f.RECEPCION}
        )
    )
    return orden_id


def test_retiro_demorado_alerta_y_admite_seguimientos(cliente):
    reloj = it.instalar_reloj(cliente)
    orden_id = _lista_y_avisada(cliente)
    assert (
        f.ok(cliente.get(f"/api/orders/{orden_id}"))["retiro_demorado_dias"]
        is None
    )

    reloj.desplazamiento = timedelta(days=31)
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert orden["retiro_demorado_dias"] == 31
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    bandejas = f.ok(cliente.get(f"/api/work/inbox?usuario_id={f.RECEPCION}"))[
        "bandejas"
    ]
    (demorado,) = [b for b in bandejas if b["codigo"] == "RETIRO_DEMORADO"]
    assert [o["orden"]["id"] for o in demorado["ordenes"]] == [orden_id]

    f.conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/pickup-followups",
            json={"usuario_id": f.TECNICO, "nota": "Llame."},
        )
    )
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/pickup-followups",
            json={
                "usuario_id": f.RECEPCION,
                "nota": "Se llamo; no atendio.",
                "canal": "TELEFONO",
            },
        )
    )
    (seguimiento,) = orden["seguimientos_retiro"]
    assert (seguimiento["usuario_id"], seguimiento["canal"]) == (
        f.RECEPCION,
        "TELEFONO",
    )
    # Nunca se cierra por vencimiento.
    assert orden["cerrada"] is False
