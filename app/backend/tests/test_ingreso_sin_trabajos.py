"""Ajustes funcionales, bloque 3: ingreso (modo JSON, por HTTP).

- DEC-AJ-05 (BF-04): la Orden se crea sin trabajos estandarizados y con el
  «Trabajo solicitado» en texto libre; el comprobante de recepcion que se
  genera al enviarla a revision confirma la custodia en el mismo acto. El
  tecnico define despues los trabajos y el cliente los autoriza. Con
  trabajos sigue la operacion unica de BR-REP-046.
- DEC-AJ-07 (BF-08): «¿Se pudieron verificar las funcionalidades del
  equipo?» es obligatoria para recibir el equipo, se guarda con la
  recepcion (y sus versiones), sale en los comprobantes y es informativa:
  no es el check-in de entrega ni cambia la garantia.
- DEC-AJ-08 (BF-06): «Crear y generar el comprobante» encadena dos
  comandos idempotentes (la cadena en si es del frontend).

DEC-AJ-06 (IMEI no disponible e IMEI real): ``test_imei_no_disponible.py``.
"""

import pytest

from tests.fixtures import api_salidas as f
from tests.fixtures import iteracion1 as it
from tests.fixtures.custodia import RECEPTOR

IMEI_REAL = "356789012345678"
OTRO_IMEI = "490154203237518"
TRABAJO = "Cambiar la bateria y revisar el boton de encendido."
MOTIVO_IMEI = "El cliente trajo la caja con el IMEI."


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _crear(
    cliente,
    *,
    verificadas: bool | None = True,
    observaciones_verificacion: str | None = None,
    trabajo_solicitado: str | None = TRABAJO,
    imei: str | None = None,
    imei_no_disponible: bool = False,
    trabajo_inicial: str | None = None,
):
    """Lo que manda «Nueva orden»: observaciones del equipo unificadas,
    trabajo solicitado y la verificacion del ingreso."""
    equipo = {
        "marca": "Apple",
        "modelo": "iPhone 13",
        "falla_reportada": "No carga. Rayon en la tapa.",
    }
    if imei:
        equipo["imei"] = imei
    recepcion = {
        "observaciones": "No carga. Rayon en la tapa.",
        "observaciones_unificadas": True,
        "trabajo_solicitado": trabajo_solicitado,
        "funcionalidades_verificadas": verificadas,
        "observaciones_verificacion": observaciones_verificacion,
        "imei_no_disponible": imei_no_disponible,
    }
    cuerpo = {
        "usuario_id": f.RECEPCION,
        "cliente": {"nombre_apellido": "Ana Gomez", "telefono": "341-555"},
        "equipo": equipo,
        "recepcion": recepcion,
    }
    if trabajo_inicial:
        cuerpo["trabajo_inicial"] = trabajo_inicial
    return cliente.post("/api/orders", json=cuerpo)


def _orden(cliente, orden_id) -> dict:
    return f.ok(cliente.get(f"/api/orders/{orden_id}"))


def _enviar(cliente, orden_id, usuario=f.RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/send-to-review",
        json={"usuario_id": usuario},
    )


def _ingreso(cliente, orden_id, canal=None):
    cuerpo = {"usuario_id": f.RECEPCION}
    if canal:
        cuerpo["canal"] = canal
    return cliente.post(
        f"/api/orders/{orden_id}/documents/intake-receipt", json=cuerpo
    )


def _emitidos(cliente, orden_id, tipo=None) -> list[dict]:
    emitidos = f.ok(cliente.get(f"/api/orders/{orden_id}/documents"))[
        "emitidos"
    ]
    return [d for d in emitidos if tipo is None or d["tipo"] == tipo]


def _pdf(cliente, orden_id, documento_id) -> str:
    respuesta = cliente.get(
        f"/api/orders/{orden_id}/documents/{documento_id}/pdf"
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.content.decode("cp1252")


def _custodia(orden) -> list[str]:
    return [a["codigo"] for a in orden["acciones_custodia"]]


# --- DEC-AJ-05: ingreso sin trabajos estandarizados --------------------------


def test_se_crea_sin_trabajos_con_el_trabajo_solicitado(cliente):
    orden = f.ok(_crear(cliente))

    assert orden["reparaciones_detail"] == []
    datos = orden["recepcion"]["datos"]
    assert datos["trabajo_solicitado"] == TRABAJO
    # Campo propio: no se mezcla con las observaciones del equipo.
    assert datos["observaciones"] == "No carga. Rayon en la tapa."
    assert "ENVIAR_A_REVISION" in f.codigos(orden)

    # Se corrige antes de recibir el equipo, con su version.
    corregida = f.ok(
        cliente.put(
            f"/api/orders/{orden['id']}/reception",
            json={
                "usuario_id": f.RECEPCION,
                "observaciones": datos["observaciones"],
                "observaciones_unificadas": True,
                "trabajo_solicitado": "Solo la bateria.",
                "motivo": "El cliente cambio el pedido.",
            },
        )
    )
    assert corregida["recepcion"]["datos"]["trabajo_solicitado"] == (
        "Solo la bateria."
    )
    (version,) = corregida["recepcion"]["versiones_anteriores"]
    assert version["datos"]["trabajo_solicitado"] == TRABAJO
    assert {"campo": "trabajo_solicitado"} in [
        {"campo": c["campo"]} for c in version["cambios"]
    ]
    # Lo que el pedido no trae (la verificacion) queda como estaba.
    assert corregida["recepcion"]["datos"]["funcionalidades_verificadas"]


def test_el_comprobante_de_recepcion_confirma_la_custodia(cliente, tmp_path):
    orden_id = f.ok(_crear(cliente))["id"]

    orden = f.ok(_enviar(cliente, orden_id))

    assert orden["estado_workflow"] == "EN_REVISION"
    assert orden["custodia"]["estado"] == "EN_CUSTODIA"
    assert orden["custodia"]["confirmada_por"] == f.RECEPCION
    assert f.ids(orden)[-5:] == [
        "PROC-REP-045",
        "PROC-REP-055",
        "ACC-REP-024",
        "PROC-REP-050",
        "PROC-REP-060",
    ]
    (comprobante,) = _emitidos(cliente, orden_id, "COMPROBANTE_RECEPCION")
    contenido = comprobante["contenido"]
    assert contenido["recepcion_fisica"] == "EN_CUSTODIA"
    assert contenido["confirmada_por"]["id"] == f.RECEPCION
    assert contenido["trabajo_solicitado"] == TRABAJO
    assert contenido["funcionalidades_verificadas"] is True
    # Ni trabajos ni precios: no autoriza nada.
    assert "trabajos" not in contenido
    assert "CONFIRMAR_RECEPCION" not in _custodia(orden)

    # Reintento («Crear y generar» o doble clic): no duplica nada.
    antes = f.archivo(tmp_path, orden_id)
    f.ok(_enviar(cliente, orden_id))
    assert f.archivo(tmp_path, orden_id) == antes


def test_sin_estado_ni_verificacion_no_se_recibe_ni_queda_nada(
    cliente, tmp_path
):
    orden_id = f.crear(cliente)  # sin datos del ingreso (cliente de la API)
    orden = _orden(cliente, orden_id)
    (enviar,) = [
        a
        for a in orden["acciones_disponibles"]
        if a["codigo"] == "ENVIAR_A_REVISION"
    ]
    assert "estado fisico" in enviar["bloqueo"]
    assert "verificar las funcionalidades" in enviar["bloqueo"]
    antes = f.archivo(tmp_path, orden_id)

    mensaje = f.conflicto(_enviar(cliente, orden_id))

    assert "verificar las funcionalidades" in mensaje
    assert f.archivo(tmp_path, orden_id) == antes


def test_rt_interno_sigue_sin_comprobante_ni_confirmacion(cliente):
    from tests.test_api_hp_rep_002 import _crear_orden_rt

    orden_id = _crear_orden_rt(cliente)
    orden = f.ok(_enviar(cliente, orden_id))

    assert orden["estado_workflow"] == "EN_REVISION"
    assert "ACC-REP-024" not in f.ids(orden)
    assert "PROC-REP-060" not in f.ids(orden)
    assert orden["recepcion"]["confirmacion"] is None


def test_despues_el_tecnico_define_y_el_cliente_autoriza(cliente):
    orden_id = f.ok(_crear(cliente))["id"]
    f.ok(_enviar(cliente, orden_id))
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Bateria agotada."},
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/review/details",
            json={"usuario_id": f.TECNICO, "tipo_reparacion_id": f.BATERIA},
        )
    )
    orden = f.finalizar(cliente, orden_id)
    # Los trabajos esperan al cliente (PROC-REP-129): nada se autorizo solo.
    assert orden["current_process"] == "PROC-REP-129"
    (detalle,) = orden["reparaciones_detail"]
    assert detalle["estado_autorizacion"] == "PENDIENTE"

    orden = f.ok(f.decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))

    assert orden["estado_workflow"] == "HABILITADA"
    # Con la custodia confirmada el tecnico puede trabajar.
    f.tomada(cliente, orden_id)
    f.iniciar(cliente, orden_id)


def test_con_trabajos_sigue_el_comprobante_de_ingreso(cliente):
    orden = f.ok(_crear(cliente, trabajo_inicial=f.BATERIA))
    assert "ENVIAR_A_REVISION" not in f.codigos(orden)

    orden = f.ok(_ingreso(cliente, orden["id"], canal="PRESENCIAL"))

    assert orden["custodia"]["estado"] == "EN_CUSTODIA"
    assert orden["reparaciones_detail"][0]["estado_autorizacion"] == (
        "AUTORIZADO"
    )
    (ingreso,) = _emitidos(cliente, orden["id"], "COMPROBANTE_INGRESO")
    assert ingreso["contenido"]["trabajo_solicitado"] == TRABAJO
    assert ingreso["contenido"]["trabajos"][0]["canal"] == "PRESENCIAL"
    assert _emitidos(cliente, orden["id"], "COMPROBANTE_RECEPCION") == []


# --- DEC-AJ-08: crear y generar (dos comandos idempotentes) ------------------


def test_crear_y_generar_con_trabajos_es_idempotente(cliente, tmp_path):
    orden_id = f.ok(_crear(cliente, trabajo_inicial=f.BATERIA))["id"]
    # El canal llega preseleccionado y se puede cambiar: se registra.
    f.ok(_ingreso(cliente, orden_id, canal="TELEFONO"))
    antes = f.archivo(tmp_path, orden_id)

    f.ok(_ingreso(cliente, orden_id, canal="TELEFONO"))

    assert f.archivo(tmp_path, orden_id) == antes
    (ingreso,) = _emitidos(cliente, orden_id, "COMPROBANTE_INGRESO")
    assert ingreso["contenido"]["trabajos"][0]["canal"] == "TELEFONO"


def test_crear_y_generar_sin_trabajos_es_idempotente(cliente):
    orden_id = f.ok(_crear(cliente))["id"]
    for _ in range(2):
        f.ok(_enviar(cliente, orden_id))
    assert len(_emitidos(cliente, orden_id, "COMPROBANTE_RECEPCION")) == 1


def test_si_falla_el_comprobante_la_orden_queda_creada(cliente):
    """Creada sin la verificacion (por la API): el comprobante se rechaza
    y la Orden queda para completarlo despues."""
    orden_id = f.ok(_crear(cliente, verificadas=None))["id"]
    assert "verificar las funcionalidades" in f.conflicto(
        _enviar(cliente, orden_id)
    )
    orden = _orden(cliente, orden_id)
    assert orden["estado_workflow"] == "REQUERIMIENTO"
    assert _emitidos(cliente, orden_id) == []


# --- DEC-AJ-07: verificacion de funcionalidades al ingresar ------------------


def test_la_verificacion_es_obligatoria_para_el_comprobante_de_ingreso(
    cliente, tmp_path
):
    orden_id = f.ok(
        _crear(cliente, verificadas=None, trabajo_inicial=f.BATERIA)
    )["id"]
    (generar,) = [
        a
        for a in _orden(cliente, orden_id)["acciones_disponibles"]
        if a["codigo"] == "GENERAR_COMPROBANTE_INGRESO"
    ]
    assert "verificar las funcionalidades" in generar["bloqueo"]
    antes = f.archivo(tmp_path, orden_id)
    assert "verificar las funcionalidades" in f.conflicto(
        _ingreso(cliente, orden_id)
    )
    assert f.archivo(tmp_path, orden_id) == antes

    # Responderla por primera vez es registrarla: no pide motivo.
    orden = f.ok(
        cliente.put(
            f"/api/orders/{orden_id}/reception",
            json={
                "usuario_id": f.RECEPCION,
                "observaciones": "No carga. Rayon en la tapa.",
                "observaciones_unificadas": True,
                "funcionalidades_verificadas": False,
                "observaciones_verificacion": "No enciende.",
            },
        )
    )
    datos = orden["recepcion"]["datos"]
    assert datos["funcionalidades_verificadas"] is False
    assert datos["observaciones_verificacion"] == "No enciende."
    # Cambiar la respuesta es una correccion: exige motivo y versiona.
    cambio = {
        "usuario_id": f.RECEPCION,
        "observaciones": "No carga. Rayon en la tapa.",
        "observaciones_unificadas": True,
        "funcionalidades_verificadas": True,
    }
    assert "motivo" in f.conflicto(
        cliente.put(f"/api/orders/{orden_id}/reception", json=cambio)
    )
    orden = f.ok(
        cliente.put(
            f"/api/orders/{orden_id}/reception",
            json={**cambio, "motivo": "Se pudo verificar despues."},
        )
    )
    version = orden["recepcion"]["versiones_anteriores"][-1]
    assert version["datos"]["funcionalidades_verificadas"] is False
    assert {
        "campo": "funcionalidades_verificadas",
        "anterior": "No",
        "nuevo": "Si",
    } in version["cambios"]

    f.ok(_ingreso(cliente, orden_id))


def test_la_verificacion_sale_en_los_comprobantes(cliente):
    orden_id = f.ok(
        _crear(
            cliente,
            verificadas=False,
            observaciones_verificacion="La pantalla no responde.",
            trabajo_inicial=f.BATERIA,
        )
    )["id"]
    f.ok(_ingreso(cliente, orden_id))

    (ingreso,) = _emitidos(cliente, orden_id, "COMPROBANTE_INGRESO")
    contenido = ingreso["contenido"]
    assert contenido["funcionalidades_verificadas"] is False
    assert contenido["observaciones_verificacion"] == (
        "La pantalla no responde."
    )
    # No es el check-in de entrega.
    assert contenido["checkin"] is None
    texto = _pdf(cliente, orden_id, ingreso["id"])
    assert "Funcionalidades verificadas al ingresar:" in texto
    assert "No. La pantalla no responde." in texto
    assert "Trabajo solicitado:" in texto
    assert TRABAJO in texto


def _entregada(cliente, verificadas: bool, checkin: bool) -> dict:
    orden_id = f.ok(
        _crear(cliente, verificadas=verificadas, trabajo_inicial=f.BATERIA)
    )["id"]
    f.ok(_ingreso(cliente, orden_id))
    orden = _orden(cliente, orden_id)
    # La respuesta del ingreso no es (ni anticipa) el check-in de entrega.
    assert orden["recepcion"]["datos"]["checkin"] is None
    assert orden["recepcion"]["registros_checkin"] == []
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    it.pagar(cliente, orden_id, "80000")
    # Sin la respuesta del check-in la entrega se sigue rechazando.
    assert "check-in" in f.conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": f.ADMINISTRADOR, **RECEPTOR},
        )
    )
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "checkin": checkin,
                **RECEPTOR,
            },
        )
    )


def test_la_verificacion_no_cambia_la_garantia(cliente):
    garantias = {}
    for verificadas in (True, False):
        for checkin in (True, False):
            orden = _entregada(cliente, verificadas, checkin)
            (detalle,) = orden["reparaciones_detail"]
            garantias[verificadas, checkin] = detalle["garantia_dias"]
    # Solo el check-in de entrega fija el plazo (BR-REP-045): 90 con
    # check-in y 30 sin el, respondiera lo que respondiera el ingreso.
    assert garantias == {
        (True, True): 90,
        (False, True): 90,
        (True, False): 30,
        (False, False): 30,
    }
