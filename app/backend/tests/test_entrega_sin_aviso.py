"""DEC-AJ-03 (BF-20): avisar al cliente deja de ser obligatorio para entregar.

- Toda entrega al cliente (CLIENTE_EXTERNO, tambien SIN_REPARACION, y la
  garantia RMA) se ofrece y se acepta sin aviso: la entrega evalua la
  condicion de entrega (PROC-REP-265) directamente.
- El aviso (PROC-REP-260) sigue siendo una accion opcional y registrable
  hasta la entrega; un WhatsApp de equipo listo confirmado como enviado
  cuenta como el aviso y lo registra una sola vez.
- El retiro demorado corre desde que la Orden esta lista para retirar; la
  fecha del aviso queda aparte.
- El camino RT_INTERNO (informar a Gestion RT y devolver) no cambia.
- Siguen los controles de saldo, custodia y check-in.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.fixtures import api_salidas as f
from tests.fixtures import iteracion1 as it
from tests.fixtures.api_definicion import definir_desde_revision_y_finalizar
from tests.fixtures.custodia import (
    checkin_si_falta,
    entregar,
    enviar_a_revision,
)


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _lista(cliente) -> str:
    """CLIENTE_EXTERNO reparada y aprobada (REPARACION_LISTA), sin aviso."""
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id)
    orden = f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    return orden_id


def _orden(cliente, orden_id) -> dict:
    return f.ok(cliente.get(f"/api/orders/{orden_id}"))


def _notificar(cliente, orden_id, usuario=f.RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/notify", json={"usuario_id": usuario}
    )


def _whatsapp(cliente, orden_id, plantilla="LISTO_PARA_RETIRAR", enviado=True):
    """Intento de WhatsApp con la plantilla y su confirmacion manual."""
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/messages",
            json={
                "usuario_id": f.RECEPCION,
                "plantilla_codigo": plantilla,
                "mensaje": "Hola! Tu equipo esta listo para retirar.",
            },
        )
    )
    comunicacion_id = orden["comunicaciones"][-1]["id"]
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/messages/{comunicacion_id}/confirm",
            json={"usuario_id": f.RECEPCION, "enviado": enviado},
        )
    )


def _avisos(orden) -> int:
    return f.ids(orden).count("PROC-REP-260")


# --- Entrega sin aviso -------------------------------------------------------


def test_cliente_externo_se_entrega_sin_aviso(cliente):
    orden_id = _lista(cliente)
    orden = it.pagar(cliente, orden_id, "80000")
    # Pagar con la Orden en 240 no mueve el proceso.
    assert orden["current_process"] == "PROC-REP-240"
    assert {"NOTIFICAR", "ENTREGAR"} <= set(f.codigos(orden))

    orden = f.ok(entregar(cliente, orden_id))

    assert orden["estado_workflow"] == "ENTREGADA"
    historial = f.ids(orden)
    assert "PROC-REP-260" not in historial
    assert historial[-4:] == [
        "PROC-REP-250",
        "PROC-REP-265",
        "PROC-REP-280",
        "PROC-REP-270",
    ]
    assert orden["historial"][-3]["observacion"] == "Saldo 0"
    assert orden["fecha_aviso"] is None


def test_sin_reparacion_se_entrega_sin_aviso(cliente):
    orden_id = f.crear(cliente)
    # DEC-AJ-05: el comprobante de recepcion confirma la custodia.
    f.ok(enviar_a_revision(cliente, orden_id))
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Sin falla."},
        )
    )
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/review/without-repair",
            json={"usuario_id": f.RECEPCION, "motivo": "No corresponde."},
        )
    )
    assert orden["finalizada_sin_reparacion"] is True
    assert {"NOTIFICAR", "ENTREGAR"} <= set(f.codigos(orden))
    assert orden["situacion"]["codigo"] == "LISTA_PARA_ENTREGAR"

    orden = f.ok(entregar(cliente, orden_id))

    assert orden["estado_workflow"] == "ENTREGADA"
    assert "PROC-REP-260" not in f.ids(orden)
    assert f.ids(orden)[-4:] == [
        "PROC-REP-250",
        "PROC-REP-265",
        "PROC-REP-280",
        "PROC-REP-270",
    ]
    assert orden["documentos"]["garantia_reparacion"]["generado"] is False


def test_garantia_rma_se_entrega_sin_aviso(cliente):
    garantia_id = it.recorrido_garantia_vigente(cliente)
    f.ok(
        cliente.post(
            f"/api/orders/{garantia_id}/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Cubierta."},
        )
    )
    f.ok(
        definir_desde_revision_y_finalizar(
            cliente,
            garantia_id,
            json={"usuario_id": f.RECEPCION, "tipo_reparacion_id": f.BATERIA},
        )
    )
    f.tomada(cliente, garantia_id)
    f.ejecutar(cliente, garantia_id)
    orden = f.ok(f.aprobar(cliente, garantia_id, "DET-001"))
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    assert "ENTREGAR" in f.codigos(orden)

    orden = f.ok(entregar(cliente, garantia_id))

    assert orden["estado_workflow"] == "ENTREGADA"
    assert "PROC-REP-260" not in f.ids(orden)
    paso_265 = [
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-265"
    ]
    assert paso_265[-1]["observacion"] == "NO_COBRABLE_POR_ORIGEN"


def test_sin_aviso_el_saldo_sigue_bloqueando_la_entrega(cliente):
    orden_id = _lista(cliente)
    checkin_si_falta(cliente, orden_id)

    # Con saldo la entrega no se ofrece ni se acepta.
    assert "ENTREGAR" not in f.codigos(_orden(cliente, orden_id))
    mensaje = f.conflicto(entregar(cliente, orden_id))

    assert "saldo pendiente" in mensaje
    orden = _orden(cliente, orden_id)
    assert orden["entrega"] is None
    # El rechazo no deja pasos a medias: ni 250 ni 265.
    assert orden["current_process"] == "PROC-REP-240"
    assert "PROC-REP-265" not in f.ids(orden)


# --- Camino RT sin cambios ---------------------------------------------------


@pytest.fixture
def cliente_rt(tmp_path):
    from tests.test_api_hp_rep_002 import _sembrar_catalogos

    _sembrar_catalogos(tmp_path)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
        yield test_client


def test_rt_interno_sigue_informando_y_devolviendo(cliente_rt):
    from tests.test_api_hp_rep_002 import (
        ADMINISTRADOR,
        _hasta_reparacion_lista_rt,
    )

    orden_id = _hasta_reparacion_lista_rt(cliente_rt)
    orden = _orden(cliente_rt, orden_id)
    assert f.codigos(orden) == ["INFORMAR_RT"]
    assert orden["situacion"]["titulo"] == "Pendiente de informar a Gestión RT"

    # No hay entrega comercial para RT_INTERNO.
    f.conflicto(
        cliente_rt.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": ADMINISTRADOR},
        )
    )
    orden = f.ok(cliente_rt.post(f"/api/orders/{orden_id}/inform-rt", json={}))
    assert f.codigos(orden) == ["DEVOLVER_RT"]
    orden = f.ok(
        cliente_rt.post(
            f"/api/orders/{orden_id}/return-rt",
            json={"usuario_id": ADMINISTRADOR},
        )
    )
    assert f.ids(orden)[-3:] == [
        "PROC-REP-250",
        "PROC-REP-290",
        "PROC-REP-270",
    ]
    assert orden["estado_workflow"] != "ENTREGADA"
    assert orden["retiro_demorado_dias"] is None


# --- El aviso, opcional y registrable ----------------------------------------


def test_el_aviso_opcional_se_registra_y_no_cambia_la_entrega(cliente):
    orden_id = _lista(cliente)
    orden = _orden(cliente, orden_id)
    assert orden["situacion"]["codigo"] == "PENDIENTE_COBRO"
    tareas = [t["titulo"] for t in orden["situacion"]["tareas"]]
    assert tareas == [
        "Registrar el pago pendiente",
        "Avisar al cliente (opcional)",
    ]

    orden = f.ok(_notificar(cliente, orden_id))
    assert f.ids(orden)[-4:] == [
        "PROC-REP-250",
        "PROC-REP-260",
        "PROC-REP-265",
        "PROC-REP-266",
    ]
    aviso = next(
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-260"
    )
    assert aviso["usuario_id"] == f.RECEPCION
    assert orden["fecha_aviso"] == aviso["fecha"]
    assert "NOTIFICAR" not in f.codigos(orden)

    it.pagar(cliente, orden_id, "80000")
    orden = f.ok(entregar(cliente, orden_id))
    assert _avisos(orden) == 1
    # Con el aviso hecho, 265 ya se evaluo con el pago: no se repite 250.
    assert f.ids(orden).count("PROC-REP-250") == 1
    assert f.ids(orden)[-2:] == ["PROC-REP-280", "PROC-REP-270"]


def test_whatsapp_listo_para_retirar_confirmado_registra_el_aviso_una_vez(
    cliente,
):
    orden_id = _lista(cliente)

    # Otra plantilla, o el mismo mensaje no enviado, no son el aviso.
    orden = _whatsapp(cliente, orden_id, plantilla="INGRESO")
    assert _avisos(orden) == 0
    orden = _whatsapp(cliente, orden_id, enviado=False)
    assert _avisos(orden) == 0

    orden = _whatsapp(cliente, orden_id)
    assert _avisos(orden) == 1
    aviso = next(
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-260"
    )
    assert aviso["usuario_id"] == f.RECEPCION
    assert (
        aviso["observacion"] == f"WhatsApp {orden['comunicaciones'][-1]['id']}"
    )
    assert f.ids(orden)[-3:] == [
        "PROC-REP-260",
        "PROC-REP-265",
        "PROC-REP-266",
    ]
    assert "NOTIFICAR" not in f.codigos(orden)

    # Un segundo envio confirmado no duplica el aviso.
    orden = _whatsapp(cliente, orden_id)
    assert _avisos(orden) == 1


def test_whatsapp_antes_de_que_este_lista_no_registra_el_aviso(cliente):
    orden_id = f.definida(cliente, f.BATERIA)

    orden = _whatsapp(cliente, orden_id)

    assert _avisos(orden) == 0
    assert orden["comunicaciones"][-1]["confirmacion"]["enviado"] is True


# --- Retiro demorado desde que esta lista ------------------------------------


def test_retiro_demorado_cuenta_desde_que_esta_lista_y_conserva_el_aviso(
    cliente,
):
    reloj = it.instalar_reloj(cliente)
    orden_id = _lista(cliente)
    lista = _orden(cliente, orden_id)["lista_para_retirar_desde"]
    assert lista is not None

    # Sin aviso, el plazo igual corre.
    reloj.desplazamiento = timedelta(days=10)
    orden = f.ok(_notificar(cliente, orden_id))
    assert orden["fecha_aviso"] > lista

    reloj.desplazamiento = timedelta(days=31)
    orden = _orden(cliente, orden_id)
    # Desde el aviso serian 21 dias (sin demora); desde que esta lista, 31.
    assert orden["retiro_demorado_dias"] == 31
    assert orden["lista_para_retirar_desde"] == lista
    assert orden["fecha_aviso"] is not None
    bandejas = f.ok(cliente.get(f"/api/work/inbox?usuario_id={f.RECEPCION}"))[
        "bandejas"
    ]
    (demorado,) = [b for b in bandejas if b["codigo"] == "RETIRO_DEMORADO"]
    (item,) = demorado["ordenes"]
    assert item["orden"]["id"] == orden_id
    assert "desde que esta lista para retirar" in item["tarea"]


def test_retiro_demorado_sin_aviso_admite_seguimientos(cliente):
    reloj = it.instalar_reloj(cliente)
    orden_id = _lista(cliente)

    reloj.desplazamiento = timedelta(days=30)
    orden = _orden(cliente, orden_id)
    assert orden["retiro_demorado_dias"] == 30
    assert orden["fecha_aviso"] is None

    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/pickup-followups",
            json={"usuario_id": f.RECEPCION, "nota": "Se llamo al cliente."},
        )
    )
    assert len(orden["seguimientos_retiro"]) == 1
    assert orden["cerrada"] is False


def test_sin_estar_lista_no_hay_retiro_que_seguir(cliente):
    orden_id = f.definida(cliente, f.BATERIA)

    orden = _orden(cliente, orden_id)

    assert orden["lista_para_retirar_desde"] is None
    assert "no esta lista para retirar" in f.conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/pickup-followups",
            json={"usuario_id": f.RECEPCION, "nota": "x"},
        )
    )
