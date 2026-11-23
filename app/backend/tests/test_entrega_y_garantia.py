"""DEC-AJ-04 (BF-18): cierre y entrega simplificados.

- Un solo «Comprobante de entrega y garantía» para las entregas nuevas: el
  comprobante final con la garantia de cada trabajo (y los terminos, en la
  vista imprimible). No se emite el certificado de garantia aparte; los ya
  emitidos se siguen leyendo.
- El check-in faltante se registra en la misma confirmacion de la entrega,
  en una sola operacion: si algo falla, no queda nada registrado.
- El cobro sigue aparte: para entregar el Saldo debe ser exactamente 0.
- La custodia sin confirmar es el ``bloqueo`` de ENTREGAR (lo informa el
  backend).
- La correccion del check-in sigue exigiendo motivo (DEC-MI-05).
"""

import json
from datetime import timedelta

import pytest

from app.domain.models import DatosEmpresa
from app.services import ContextoDocumentos, registrar_documento
from app.services.documentos import contenido_garantia
from tests.fixtures import api_salidas as f
from tests.fixtures import iteracion1 as it
from tests.fixtures.custodia import registrar_checkin

RETIRA = {"recibido_por": "Maria Gomez"}


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _lista_y_pagada(cliente) -> str:
    """CLIENTE_EXTERNO reparada, aprobada y pagada, sin check-in ni aviso."""
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    orden = it.pagar(cliente, orden_id, "80000")
    assert orden["recepcion"]["datos"]["checkin"] is None
    return orden_id


def _entregar(cliente, orden_id, usuario=f.ADMINISTRADOR, **cuerpo):
    return cliente.post(
        f"/api/orders/{orden_id}/deliver",
        json={"usuario_id": usuario, **RETIRA, **cuerpo},
    )


def _orden(cliente, orden_id) -> dict:
    return f.ok(cliente.get(f"/api/orders/{orden_id}"))


def _documentos(cliente, orden_id) -> dict:
    return f.ok(cliente.get(f"/api/orders/{orden_id}/documents"))


def _accion(orden, codigo) -> dict | None:
    return next(
        (a for a in orden["acciones_disponibles"] if a["codigo"] == codigo),
        None,
    )


# --- Check-in dentro de la entrega -------------------------------------------


def test_checkin_y_entrega_en_una_sola_confirmacion(cliente):
    orden_id = _lista_y_pagada(cliente)
    orden = _orden(cliente, orden_id)
    # El check-in no bloquea la accion: se pide en el formulario.
    assert _accion(orden, "ENTREGAR")["bloqueo"] is None
    assert orden["situacion"]["codigo"] == "LISTA_PARA_ENTREGAR"

    orden = f.ok(_entregar(cliente, orden_id, checkin=False))

    assert orden["estado_workflow"] == "ENTREGADA"
    (registro,) = orden["recepcion"]["registros_checkin"]
    assert (registro["realizado"], registro["usuario_id"]) == (
        False,
        f.ADMINISTRADOR,
    )
    # 250 (sin aviso) -> 269 (check-in) -> 265 -> 280 -> 270, todo junto.
    assert f.ids(orden)[-5:] == [
        "PROC-REP-250",
        "PROC-REP-269",
        "PROC-REP-265",
        "PROC-REP-280",
        "PROC-REP-270",
    ]
    paso_269 = orden["historial"][-4]
    assert paso_269["usuario_id"] == f.ADMINISTRADOR
    assert paso_269["fecha"] == orden["entrega"]["fecha"]
    # Sin verificar las funciones basicas: garantia de 30 dias.
    comprobante = next(
        d
        for d in _documentos(cliente, orden_id)["emitidos"]
        if d["tipo"] == "COMPROBANTE_ENTREGA"
    )["contenido"]
    assert comprobante["checkin"] is False
    assert comprobante["trabajos_realizados"][0]["garantia_dias"] == 30


def test_checkin_en_la_entrega_despues_del_aviso_revalida_265(cliente):
    orden_id = _lista_y_pagada(cliente)
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify",
            json={"usuario_id": f.RECEPCION},
        )
    )

    orden = f.ok(_entregar(cliente, orden_id, checkin=True))

    # Ya estaba en 265: el check-in (269) obliga a revalidarlo.
    assert f.ids(orden)[-4:] == [
        "PROC-REP-269",
        "PROC-REP-265",
        "PROC-REP-280",
        "PROC-REP-270",
    ]
    assert f.ids(orden).count("PROC-REP-250") == 1


def test_sin_checkin_la_entrega_se_rechaza_sin_cambios(cliente, tmp_path):
    orden_id = _lista_y_pagada(cliente)
    antes = f.archivo(tmp_path, orden_id)

    assert "check-in" in f.conflicto(_entregar(cliente, orden_id))

    assert f.archivo(tmp_path, orden_id) == antes


def test_saldo_distinto_de_cero_no_registra_el_checkin(cliente, tmp_path):
    """Una sola operacion: si el saldo bloquea, el check-in no queda."""
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    it.pagar(cliente, orden_id, "30000")
    antes = f.archivo(tmp_path, orden_id)

    mensaje = f.conflicto(_entregar(cliente, orden_id, checkin=True))

    assert "saldo pendiente" in mensaje
    assert f.archivo(tmp_path, orden_id) == antes
    orden = _orden(cliente, orden_id)
    assert orden["recepcion"]["registros_checkin"] == []
    assert "ENTREGAR" not in f.codigos(orden)


def test_la_correccion_del_checkin_en_la_entrega_exige_motivo(cliente):
    orden_id = _lista_y_pagada(cliente)
    f.ok(registrar_checkin(cliente, orden_id, realizado=True))

    # Mismo valor: nada que corregir.
    assert "motivo" in f.conflicto(_entregar(cliente, orden_id, checkin=False))
    orden = f.ok(
        _entregar(
            cliente,
            orden_id,
            checkin=False,
            checkin_motivo="No encendio la camara al probarlo.",
        )
    )

    registros = orden["recepcion"]["registros_checkin"]
    assert [r["realizado"] for r in registros] == [True, False]
    assert registros[-1]["motivo"] == "No encendio la camara al probarlo."
    # Corregir no es registrar el que faltaba: no hay 269.
    assert "PROC-REP-269" not in f.ids(orden)


def test_solo_entregan_los_roles_de_entrega(cliente, tmp_path):
    orden_id = _lista_y_pagada(cliente)
    antes = f.archivo(tmp_path, orden_id)

    f.conflicto(_entregar(cliente, orden_id, usuario=f.TECNICO, checkin=True))
    f.conflicto(
        _entregar(cliente, orden_id, usuario=f.COORDINADOR, checkin=True)
    )

    assert f.archivo(tmp_path, orden_id) == antes
    f.ok(_entregar(cliente, orden_id, usuario=f.RECEPCION, checkin=True))


# --- Custodia como bloqueo ---------------------------------------------------


def test_la_custodia_sin_confirmar_es_el_bloqueo_de_entregar(cliente):
    # DEC-AJ-05: en Cliente Externo el comprobante de recepcion ya confirma
    # la custodia; la garantia RMA la sigue confirmando aparte, asi que es
    # la que llega a entregar con la custodia pendiente.
    orden_id = it.recorrido_garantia_vigente(cliente)
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
    assert orden["custodia"]["estado"] == "PENDIENTE_CONFIRMACION"
    assert _accion(orden, "ENTREGAR")["bloqueo"] == (
        "Falta confirmar la recepción física del equipo"
    )
    assert "recepcion fisica" in f.conflicto(_entregar(cliente, orden_id))

    from tests.fixtures.custodia import confirmar_recepcion

    orden = confirmar_recepcion(cliente, orden_id)
    assert _accion(orden, "ENTREGAR")["bloqueo"] is None
    f.ok(_entregar(cliente, orden_id))


# --- Un solo documento -------------------------------------------------------


def test_un_solo_comprobante_de_entrega_y_garantia(cliente):
    orden_id = _lista_y_pagada(cliente)
    previsualizables = _documentos(cliente, orden_id)["previsualizables"]
    assert "GARANTIA" not in previsualizables
    assert "COMPROBANTE_ENTREGA" in previsualizables
    previa = f.ok(
        cliente.get(
            f"/api/orders/{orden_id}/documents/preview/COMPROBANTE_ENTREGA"
        )
    )["contenido"]
    assert previa["entrega_y_garantia"] is True

    orden = f.ok(_entregar(cliente, orden_id, checkin=True))

    documentos = _documentos(cliente, orden_id)["emitidos"]
    assert [d["tipo"] for d in documentos] == [
        "COMPROBANTE_INGRESO",
        "COMPROBANTE_ENTREGA",
    ]
    contenido = documentos[-1]["contenido"]
    assert contenido["entrega_y_garantia"] is True
    assert contenido["tipo_entrega"] == "REPARACION_TERMINADA"
    (trabajo,) = contenido["trabajos_realizados"]
    assert (trabajo["garantia_dias"], trabajo["garantia_vence"]) != (0, None)
    # La marca del proceso dice que la garantia se emitio (en este
    # comprobante).
    assert orden["documentos"]["garantia_reparacion"]["generado"] is True


def test_sin_reparacion_es_un_comprobante_de_devolucion(cliente):
    orden_id = f.crear(cliente)
    # DEC-AJ-05: el comprobante de recepcion confirma la custodia.
    from tests.fixtures.custodia import enviar_a_revision

    f.ok(enviar_a_revision(cliente, orden_id))
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Sin falla."},
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/review/without-repair",
            json={"usuario_id": f.RECEPCION, "motivo": "No corresponde."},
        )
    )

    f.ok(_entregar(cliente, orden_id))

    (comprobante,) = [
        d
        for d in _documentos(cliente, orden_id)["emitidos"]
        if d["tipo"] == "COMPROBANTE_ENTREGA"
    ]
    assert comprobante["contenido"]["tipo_entrega"] == (
        "DEVOLUCION_SIN_REPARACION"
    )
    assert comprobante["contenido"]["entrega_y_garantia"] is False


def test_un_certificado_ya_emitido_se_sigue_leyendo(cliente, tmp_path):
    """Los certificados de garantia anteriores son inmutables y legibles."""
    orden_id = _lista_y_pagada(cliente)
    f.ok(_entregar(cliente, orden_id, checkin=True))
    repo = f.repo_ordenes(tmp_path)
    orden = repo.obtener(orden_id)
    contenido = contenido_garantia(
        orden, ContextoDocumentos(empresa=DatosEmpresa(nombre="Rosario Tecno"))
    )
    _, certificado, creado = registrar_documento(
        orden,
        contenido=contenido,
        fecha=orden.updated_at + timedelta(seconds=1),
        usuario_id=f.ADMINISTRADOR,
    )
    assert creado
    # Una Orden cerrada no se reescribe: el certificado se agrega al JSON
    # como lo dejo una entrega anterior a DEC-AJ-04.
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["documentos"]["emitidos"].append(certificado.model_dump(mode="json"))
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    documentos = _documentos(cliente, orden_id)
    assert [d["tipo"] for d in documentos["emitidos"]][-1] == "GARANTIA"
    leido = f.ok(
        cliente.get(f"/api/orders/{orden_id}/documents/{certificado.id}")
    )
    assert leido["contenido"]["tipo"] == "GARANTIA"
    assert leido["contenido"]["coberturas"][0]["detalle_id"] == "DET-001"
