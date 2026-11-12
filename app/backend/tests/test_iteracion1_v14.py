"""Iteracion 1: escenarios de la baseline V1.4 por HTTP (modo JSON).

* DC15B, vigencia de la garantia de origen al iniciar la garantia RMA
  (PROC-REP-036): vigente sigue HP-REP-003; VAR-REP-038, vencida sin
  excepcion, termina en EVT-REP-998 sin crear la Orden; VAR-REP-039,
  vencida con excepcion autorizada y auditada.
* VAR-REP-041 (DC11): cortesia total con pagos previos.
* VAR-REP-042 (DC07): desistimiento con el Detalle en ejecucion.
* DC06: definir y redefinir luego de la revision es del Tecnico; las
  decisiones del cliente siguen en Recepcion.

Los mismos recorridos se guardan y releen en PostgreSQL desde el corpus
(``tests/postgres/corpus_ordenes.py``).
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from tests.fixtures import api_salidas as f
from tests.fixtures import iteracion1 as it


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path) as test_client:
        yield test_client


@pytest.fixture
def reloj(cliente):
    return it.instalar_reloj(cliente)


def _orden(cliente, orden_id) -> dict:
    return f.ok(cliente.get(f"/api/orders/{orden_id}"))


def _pasos(orden: dict) -> list[tuple[str, str | None]]:
    return [(p["referencia_id"], p["accion"]) for p in orden["historial"]]


def _cantidad_de_ordenes(tmp_path) -> int:
    return len(list((tmp_path / "ordenes").glob("OR-*.json")))


# --- HP-REP-003 (036 "Si"): garantia vigente ---------------------------------


def test_hp_rep_003_garantia_vigente(cliente):
    origen = it.entregada(cliente)
    disponible = _orden(cliente, origen)["garantia_por_detalle"]
    assert [(g["detalle_id"], g["vigente"]) for g in disponible] == [
        ("DET-001", True)
    ]
    (iniciar,) = _orden(cliente, origen)["acciones_disponibles"]
    assert iniciar["roles"] == ["RECEPCION"]

    garantia = f.ok(it.iniciar_garantia(cliente, origen))

    # Trazabilidad con la Orden y el Detalle de origen.
    assert garantia["origen"] == "RMA_GARANTIA_REPARACION"
    assert garantia["orden_origen_id"] == origen
    assert garantia["detalles_origen_ids"] == ["DET-001"]
    (vigencia,) = garantia["vigencia_garantia_origen"]
    assert vigencia["detalle_id"] == "DET-001"
    assert vigencia["vigente"] is True
    assert vigencia["garantia_dias"] == 90
    assert vigencia["vence"] == disponible[0]["vence"]
    assert garantia["excepcion_garantia"] is None
    # 035 -> 036 (Vigente) -> 040; sigue como HP-REP-003.
    pasos = _pasos(garantia)
    assert pasos[:3] == [
        ("PROC-REP-035", pasos[0][1]),
        ("PROC-REP-036", "VALIDAR_VIGENCIA_GARANTIA"),
        ("PROC-REP-040", pasos[2][1]),
    ]
    assert garantia["historial"][1]["observacion"] == "Vigente"
    assert garantia["estado_workflow"] == "EN_REVISION"


def test_hp_rep_003_no_se_pide_excepcion_si_esta_vigente(cliente, tmp_path):
    origen = it.entregada(cliente)
    antes = _cantidad_de_ordenes(tmp_path)

    mensaje = f.conflicto(
        it.iniciar_garantia(
            cliente,
            origen,
            usuario=it.COORDINADOR,
            motivo_excepcion=it.MOTIVO_EXCEPCION,
        )
    )

    assert "vigente" in mensaje.lower()
    assert _cantidad_de_ordenes(tmp_path) == antes


# --- VAR-REP-038 (sin excepcion) y VAR-REP-039 (con excepcion) --------------


def test_var_rep_038_vencida_sin_excepcion_no_crea_la_orden(
    cliente, reloj, tmp_path
):
    origen = it.entregada_hace(cliente, reloj, 200)
    (disponible,) = _orden(cliente, origen)["garantia_por_detalle"]
    assert disponible["vigente"] is False
    # Vencida: iniciar la garantia tambien lo ve quien autoriza la excepcion.
    (iniciar,) = _orden(cliente, origen)["acciones_disponibles"]
    assert iniciar["codigo"] == "INICIAR_GARANTIA_RMA"
    assert iniciar["roles"] == [
        "RECEPCION",
        "COORDINADOR_RMA",
        "ADMINISTRADOR",
    ]
    antes = _cantidad_de_ordenes(tmp_path)
    origen_antes = f.archivo(tmp_path, origen)

    mensaje = f.conflicto(
        it.iniciar_garantia(cliente, origen), codigo="GARANTIA_VENCIDA"
    )

    assert "DET-001" in mensaje
    assert _cantidad_de_ordenes(tmp_path) == antes
    assert f.archivo(tmp_path, origen) == origen_antes


@pytest.mark.parametrize("usuario", [f.RECEPCION, f.TECNICO])
def test_var_rep_039_la_excepcion_exige_un_usuario_autorizado(
    cliente, reloj, tmp_path, usuario
):
    origen = it.entregada_hace(cliente, reloj, 200)
    antes = _cantidad_de_ordenes(tmp_path)

    mensaje = f.conflicto(
        it.iniciar_garantia(
            cliente,
            origen,
            usuario=usuario,
            motivo_excepcion=it.MOTIVO_EXCEPCION,
        )
    )

    assert "rol" in mensaje
    assert _cantidad_de_ordenes(tmp_path) == antes


@pytest.mark.parametrize("motivo", [None, "   "])
def test_var_rep_039_el_autorizado_sin_motivo_tampoco(
    cliente, reloj, tmp_path, motivo
):
    """Sin motivo no hay excepcion: el inicio comun es de Recepcion."""
    origen = it.entregada_hace(cliente, reloj, 200)
    antes = _cantidad_de_ordenes(tmp_path)
    mensaje = f.conflicto(
        it.iniciar_garantia(
            cliente, origen, usuario=it.COORDINADOR, motivo_excepcion=motivo
        )
    )
    assert "RECEPCION" in mensaje
    assert _cantidad_de_ordenes(tmp_path) == antes


@pytest.mark.parametrize("usuario", [it.COORDINADOR, f.ADMINISTRADOR])
def test_var_rep_039_excepcion_autorizada_y_auditada(cliente, reloj, usuario):
    origen = it.entregada_hace(cliente, reloj, 200)

    garantia = f.ok(
        it.iniciar_garantia(
            cliente,
            origen,
            usuario=usuario,
            motivo_excepcion=it.MOTIVO_EXCEPCION,
        )
    )

    excepcion = garantia["excepcion_garantia"]
    assert excepcion["usuario_id"] == usuario
    assert excepcion["motivo"] == it.MOTIVO_EXCEPCION
    assert excepcion["fecha"]
    (vigencia,) = garantia["vigencia_garantia_origen"]
    assert vigencia["vigente"] is False
    assert vigencia["vence"]
    assert garantia["orden_origen_id"] == origen
    paso_036 = garantia["historial"][1]
    assert paso_036["referencia_id"] == "PROC-REP-036"
    assert paso_036["accion"] == "AUTORIZAR_EXCEPCION_GARANTIA"
    assert paso_036["usuario_id"] == usuario
    assert it.MOTIVO_EXCEPCION in paso_036["observacion"]
    assert "DET-001" in paso_036["observacion"]
    # Sigue como HP-REP-003: revision tecnica obligatoria.
    assert garantia["estado_workflow"] == "EN_REVISION"
    assert "REALIZAR_REVISION" in f.codigos(garantia)


def test_var_rep_039_mezcla_de_vigentes_y_vencidos_exige_la_excepcion(
    cliente, reloj
):
    """Un reclamo con algun Detalle vencido exige la excepcion (provisional:
    no se separa en dos Ordenes)."""
    reloj.desplazamiento = -timedelta(days=75)
    origen = f.definida(cliente, f.BATERIA, f.PANTALLA)
    # Bateria: 90 dias (vigente). Pantalla: 30 dias (vencida).
    f.ok(
        cliente.post(
            f"/api/orders/{origen}/details/DET-002/warranty",
            json={
                "usuario_id": f.RECEPCION,
                "dias": 30,
                "motivo": "Garantia reducida del repuesto.",
            },
        )
    )
    f.tomada(cliente, origen)
    f.ejecutar(cliente, origen, "DET-001", f.BATERIA)
    f.ejecutar(cliente, origen, "DET-002", f.PANTALLA)
    f.ok(f.aprobar(cliente, origen, "DET-001"))
    f.ok(f.aprobar(cliente, origen, "DET-002"))
    f.notificar_pagar_entregar(cliente, origen)
    reloj.desplazamiento = timedelta(0)
    disponibles = {
        g["detalle_id"]: g["vigente"]
        for g in _orden(cliente, origen)["garantia_por_detalle"]
    }
    assert disponibles == {"DET-001": True, "DET-002": False}

    mensaje = f.conflicto(
        it.iniciar_garantia(cliente, origen, ("DET-001", "DET-002")),
        codigo="GARANTIA_VENCIDA",
    )
    assert "DET-002" in mensaje and "DET-001" not in mensaje
    # Solo el vigente pasa sin excepcion.
    f.ok(it.iniciar_garantia(cliente, origen, ("DET-001",)))


# --- VAR-REP-041: cortesia total con pagos previos ---------------------------


def test_var_rep_041_cortesia_total_con_pagos_previos(cliente):
    orden_id = f.definida(cliente)
    orden = it.pagar(cliente, orden_id, "30000")
    pago_id = orden["pagos"][-1]["id"]
    assert "OTORGAR_CORTESIA" in [
        a["codigo"] for a in orden["acciones_financieras"]
    ]

    orden = f.ok(it.ajuste_comercial(cliente, orden_id))

    # La cortesia se conserva como ajuste; los pagos tambien.
    assert orden["descuentos"][-1]["clase"] == "CORTESIA"
    assert orden["descuentos"][-1]["usuario_id"] == f.ADMINISTRADOR
    assert [p["id"] for p in orden["pagos"]] == [pago_id]
    assert Decimal(orden["resumen"]["total"]) == 0
    assert Decimal(orden["resumen"]["saldo"]) == Decimal("-30000")
    assert Decimal(orden["resumen"]["credito_a_favor"]) == Decimal("30000")
    # No se otorga dos veces: con la cortesia vigente solo se ofrece quitarla.
    financieras = {a["codigo"]: a for a in orden["acciones_financieras"]}
    assert "OTORGAR_CORTESIA" not in financieras
    assert financieras["APLICAR_DESCUENTO"]["roles"] == ["ADMINISTRADOR"]

    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify",
            json={"usuario_id": f.RECEPCION},
        )
    )

    # Con la devolucion pendiente no se entrega.
    f.conflicto(f.entregar(cliente, orden_id, f.ADMINISTRADOR))
    assert _orden(cliente, orden_id)["estado_workflow"] != "ENTREGADA"

    orden = f.ok(it.devolver_dinero(cliente, orden_id, pago_id, "30000"))
    assert Decimal(orden["resumen"]["saldo"]) == 0
    # Sin duplicados: ni otra devolucion por encima del credito...
    f.conflicto(
        it.devolver_dinero(cliente, orden_id, pago_id, "1", "it1-otra")
    )
    # ...ni el reintento de la misma operacion.
    assert "no se duplica" in f.conflicto(
        it.devolver_dinero(cliente, orden_id, pago_id, "30000")
    )
    assert len(_orden(cliente, orden_id)["devoluciones_dinero"]) == 1

    orden = f.ok(f.entregar(cliente, orden_id, f.ADMINISTRADOR))
    assert orden["estado_workflow"] == "ENTREGADA"
    assert [p["id"] for p in orden["pagos"]] == [pago_id]


@pytest.mark.parametrize("usuario", [f.RECEPCION, it.COORDINADOR, f.TECNICO])
def test_var_rep_041_la_cortesia_solo_la_otorga_administracion(
    cliente, tmp_path, usuario
):
    orden_id = f.definida(cliente)
    antes = f.archivo(tmp_path, orden_id)
    f.conflicto(it.ajuste_comercial(cliente, orden_id, usuario=usuario))
    assert f.archivo(tmp_path, orden_id) == antes


def test_var_rep_041_la_cortesia_es_total(cliente, tmp_path):
    orden_id = f.definida(cliente)
    antes = f.archivo(tmp_path, orden_id)
    mensaje = f.conflicto(
        it.ajuste_comercial(cliente, orden_id, valor="50")
    )
    assert "total" in mensaje
    assert f.archivo(tmp_path, orden_id) == antes


def test_var_rep_041_quitar_la_cortesia_tambien_es_de_administracion(
    cliente,
):
    orden_id = f.definida(cliente)
    f.ok(it.ajuste_comercial(cliente, orden_id))
    f.conflicto(
        it.ajuste_comercial(
            cliente,
            orden_id,
            clase="DESCUENTO",
            tipo=None,
            valor=None,
            usuario=f.RECEPCION,
            motivo="Se quita.",
        )
    )
    orden = f.ok(
        it.ajuste_comercial(
            cliente,
            orden_id,
            clase="DESCUENTO",
            tipo=None,
            valor=None,
            motivo="Se quita la cortesia.",
        )
    )
    assert orden["descuentos"][-1]["clase"] == "CORTESIA"
    assert orden["descuentos"][-1]["tipo"] is None
    assert Decimal(orden["resumen"]["total"]) == Decimal("80000")


def test_un_descuento_sigue_sin_dejar_el_total_bajo_lo_cobrado(cliente):
    """El descuento comun conserva su regla anterior (BR-REP-016)."""
    orden_id = f.definida(cliente)
    it.pagar(cliente, orden_id, "70000")
    f.conflicto(
        it.ajuste_comercial(
            cliente,
            orden_id,
            clase="DESCUENTO",
            valor="50",
            usuario=f.RECEPCION,
            motivo="Rebaja.",
        )
    )


# --- VAR-REP-042: desistimiento con el Detalle en ejecucion ------------------


def test_var_rep_042_solicitud_interrupcion_y_cancelacion(cliente):
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)
    ejecucion_id = f.iniciar(cliente, orden_id)
    ofrecidas = [
        (a["codigo"], a["detalle_id"])
        for a in _orden(cliente, orden_id)["acciones_autorizacion"]
    ]
    assert ("DESISTIR_DETALLE", "DET-001") in ofrecidas

    # 1. La solicitud (Recepcion): no cancela ni toca la Ejecucion.
    orden = f.ok(it.desistir_detalle(cliente, orden_id, "DET-001"))
    detalle = f.detalle(orden, "DET-001")
    assert detalle["estado"] == "EN_PROGRESO"
    assert detalle["cancelacion"] is None
    solicitud = detalle["solicitud_desistimiento"]
    assert solicitud["usuario_id"] == f.RECEPCION
    assert solicitud["canal"] == "TELEFONO"
    assert orden["ejecuciones"][0]["estado"] == "EN_PROGRESO"
    assert ("PROC-REP-046", "SOLICITAR_DESISTIMIENTO_CLIENTE") in _pasos(
        orden
    )
    # No se duplica la solicitud.
    f.conflicto(it.desistir_detalle(cliente, orden_id, "DET-001"))
    # Al tecnico solo se le ofrece interrumpir; ya no se ofrece desistir.
    situacion = _orden(cliente, orden_id)["situacion"]
    (tarea,) = situacion["tareas"]
    assert tarea["titulo"] == "Interrumpir el trabajo"
    assert [a["codigo"] for a in tarea["acciones"]] == [
        "INTERRUMPIR_EJECUCION"
    ]
    codigos = f.codigos(_orden(cliente, orden_id))
    assert "INTERRUMPIR_EJECUCION" in codigos
    assert "COMPLETAR_EJECUCION" not in codigos
    assert "REQUIERE_REDEFINICION" not in codigos
    assert ("DESISTIR_DETALLE", "DET-001") not in [
        (a["codigo"], a["detalle_id"])
        for a in _orden(cliente, orden_id)["acciones_autorizacion"]
    ]

    # 2. El tecnico no completa ni redefine: interrumpe.
    f.conflicto(f.cerrar_ejecucion(cliente, orden_id, ejecucion_id))
    f.conflicto(
        f.cerrar_ejecucion(
            cliente, orden_id, ejecucion_id, "requires-redefinition"
        )
    )
    # Sin el estado del trabajo y si es reversible, no.
    f.conflicto(it.interrumpir(cliente, orden_id, ejecucion_id))

    # 3. Interrupcion y cancelacion efectiva, separadas de la solicitud.
    orden = f.ok(
        it.interrumpir(
            cliente,
            orden_id,
            ejecucion_id,
            estado_trabajo="Equipo abierto; bateria sin reemplazar.",
            reversible=True,
        )
    )
    (ejecucion,) = orden["ejecuciones"]
    assert ejecucion["estado"] == "INTERRUMPIDO"
    assert ejecucion["estado_trabajo"].startswith("Equipo abierto")
    assert ejecucion["reversible"] is True
    detalle = f.detalle(orden, "DET-001")
    assert detalle["estado"] == "CANCELADO"
    assert detalle["cancelacion"]["origen"] == "DESISTIMIENTO_CLIENTE"
    assert detalle["solicitud_desistimiento"] == solicitud
    pasos = _pasos(orden)
    solicitado = pasos.index(
        ("PROC-REP-046", "SOLICITAR_DESISTIMIENTO_CLIENTE")
    )
    interrumpido = max(
        i for i, (ref, _) in enumerate(pasos) if ref == "PROC-REP-200"
    )
    cancelado = max(
        i for i, (ref, _) in enumerate(pasos) if ref == "PROC-REP-300"
    )
    assert solicitado < interrumpido < cancelado

    # DC31: cancelar el unico trabajo no cancela la Orden.
    assert orden["estado_workflow"] != "CANCELADA"
    assert orden["current_process"] == "PROC-REP-307"


def test_var_rep_042_luego_sigue_el_circuito_dc31(cliente):
    orden_id = it.recorrido_desistimiento_en_ejecucion(cliente)
    orden = _orden(cliente, orden_id)
    assert orden["estado_workflow"] != "CANCELADA"
    # Sin trabajos vigentes la toma ya se libero.
    assert orden["toma_activa"] is None
    f.ok(f.devolver(cliente, orden_id))
    orden = f.ok(f.cancelar_orden(cliente, orden_id))
    assert orden["estado_workflow"] == "CANCELADA"


def test_var_rep_042_otro_detalle_no_espera_la_ejecucion(cliente):
    """Desistir de un Detalle que NO se esta ejecutando sigue siendo
    inmediato (sin solicitud pendiente)."""
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    f.tomada(cliente, orden_id)
    f.iniciar(cliente, orden_id, "DET-001")
    orden = f.ok(it.desistir_detalle(cliente, orden_id, "DET-002"))
    assert f.detalle(orden, "DET-002")["estado"] == "CANCELADO"
    assert f.detalle(orden, "DET-001")["solicitud_desistimiento"] is None


# --- DC06: el Tecnico define; Recepcion gestiona al cliente ------------------


def test_dc06_el_tecnico_define_y_recepcion_registra_la_decision(cliente):
    orden_id = f.por_revision(cliente, f.BATERIA)
    orden = _orden(cliente, orden_id)
    # La decision del cliente sigue en Recepcion.
    (decision,) = [
        a
        for a in orden["acciones_autorizacion"]
        if a["codigo"] == "REGISTRAR_DECISION_CLIENTE"
    ]
    assert decision["roles"] == ["RECEPCION"]
    (definir,) = [
        p
        for p in orden["historial"]
        if p["referencia_id"] == "PROC-REP-075"
    ]
    assert definir["usuario_id"] == f.TECNICO
