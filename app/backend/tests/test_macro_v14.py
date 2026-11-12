"""Macroiteracion V1.4: escenarios por HTTP (modo JSON).

A. Evaluacion tecnica (BR-REP-035/036, PROC-REP-182/183/184): HP-REP-001
   con 182 -> 183 CONFIRMADO -> 184 -> 182 -> 174, DESCARTADO y
   REQUIERE_REDEFINICION (VAR-REP-019), roles y Detalles del tecnico.
B. Desistimiento total guiado con una Ejecucion activa (DC07C, VAR-REP-043).
F. Antecedentes del Equipo por IMEI o numero de serie (BR-REP-022).
K. Reporte operativo, primera version.
"""

from decimal import Decimal

import pytest

from tests.fixtures import api_salidas as f
from tests.fixtures import iteracion1 as it
from tests.fixtures.api_definicion import definir_y_finalizar


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _orden(cliente, orden_id) -> dict:
    return f.ok(cliente.get(f"/api/orders/{orden_id}"))


def _evaluar(cliente, orden_id, resultado, *, usuario=f.TECNICO, **extra):
    return cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/evaluation",
        json={"usuario_id": usuario, "resultado": resultado, **extra},
    )


def _iniciar(cliente, orden_id, detalle_id="DET-001"):
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/start",
        json={"usuario_id": f.TECNICO},
    )


def _pasos(orden):
    return [(p["referencia_id"], p["observacion"]) for p in orden["historial"]]


# --- A. Evaluacion tecnica ---------------------------------------------------


@pytest.mark.v14_evaluacion
def test_hp_rep_001_v14_evalua_antes_de_iniciar(cliente):
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)
    orden = _orden(cliente, orden_id)
    detalle = f.detalle(orden, "DET-001")
    assert detalle["origen_diagnostico"] == "RECEPCION"
    assert detalle["requiere_evaluacion"] is True
    # Al tecnico se le ofrece evaluar, no iniciar.
    codigos = f.codigos(orden)
    assert "EVALUAR_DETALLE" in codigos and "INICIAR_DETALLE" not in codigos
    (tarea,) = orden["situacion"]["tareas"]
    assert tarea["titulo"] == "Evaluar el trabajo antes de empezar"

    # Sin evaluacion vigente no se reserva ni se inicia (BR-REP-035).
    assert "evaluacion tecnica" in f.conflicto(_iniciar(cliente, orden_id))

    orden = f.ok(_evaluar(cliente, orden_id, "CONFIRMADO"))
    (evaluacion,) = f.detalle(orden, "DET-001")["evaluaciones"]
    assert evaluacion["resultado"] == "CONFIRMADO"
    assert evaluacion["version_definicion"] == 1
    assert evaluacion["usuario_id"] == f.TECNICO
    assert f.detalle(orden, "DET-001")["requiere_evaluacion"] is False
    # La evaluacion no reserva ni consume nada.
    assert orden["ejecuciones"] == []
    assert not [
        m
        for m in orden.get("movimientos_insumo", [])
        if m["tipo"] == "RESERVA"
    ]

    orden = f.ok(_iniciar(cliente, orden_id))
    ids = [ref for ref, _ in _pasos(orden)]
    tramo = ids[ids.index("PROC-REP-182") :]
    assert tramo[:7] == [
        "PROC-REP-182",
        "PROC-REP-183",
        "PROC-REP-184",
        "PROC-REP-181",
        "PROC-REP-182",
        "PROC-REP-174",
        "PROC-REP-185",
    ]
    decisiones = [obs for ref, obs in _pasos(orden) if ref == "PROC-REP-182"]
    assert decisiones == [
        "Requiere evaluacion tecnica",
        "No requiere evaluacion tecnica",
    ]


@pytest.mark.v14_evaluacion
def test_evaluacion_descartado_cancela_por_descarte_tecnico(cliente):
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)
    f.conflicto(_evaluar(cliente, orden_id, "DESCARTADO"))  # sin motivo

    orden = f.ok(
        _evaluar(
            cliente,
            orden_id,
            "DESCARTADO",
            observaciones="La bateria esta bien; falla de software.",
        )
    )

    detalle = f.detalle(orden, "DET-001")
    assert detalle["estado"] == "CANCELADO"
    assert detalle["cancelacion"]["origen"] == "DESCARTE_TECNICO"
    assert detalle["cancelacion"]["usuario_id"] == f.TECNICO
    assert detalle["evaluaciones"][-1]["resultado"] == "DESCARTADO"
    # DC31: cancelar el unico trabajo no cancela la Orden.
    assert orden["estado_workflow"] != "CANCELADA"
    assert orden["current_process"] == "PROC-REP-307"


@pytest.mark.v14_evaluacion
def test_var_rep_019_evaluacion_requiere_redefinicion(cliente):
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)
    # Sin la nueva definicion, o sin motivo, no.
    f.conflicto(
        _evaluar(
            cliente, orden_id, "REQUIERE_REDEFINICION", observaciones="Pin."
        )
    )
    f.conflicto(
        _evaluar(
            cliente,
            orden_id,
            "REQUIERE_REDEFINICION",
            tipo_reparacion_id=f.PANTALLA,
        )
    )

    orden = f.ok(
        _evaluar(
            cliente,
            orden_id,
            "REQUIERE_REDEFINICION",
            observaciones="No es la bateria: es la pantalla.",
            tipo_reparacion_id=f.PANTALLA,
        )
    )

    detalle = f.detalle(orden, "DET-001")
    assert detalle["tipo_reparacion_id"] == f.PANTALLA
    assert detalle["version_definicion"] == 2
    assert len(detalle["definiciones_anteriores"]) == 1
    # La nueva la diagnostico el tecnico: queda validada por el mismo acto.
    assert detalle["origen_diagnostico"] == "REVISION_TECNICA"
    assert detalle["requiere_evaluacion"] is False
    # La autorizacion anterior ya no vale: Recepcion consulta al cliente.
    assert detalle["estado_autorizacion"] == "PENDIENTE"
    assert "PROC-REP-127" in [ref for ref, _ in _pasos(orden)]
    assert orden["current_process"] == "PROC-REP-129"
    f.conflicto(_iniciar(cliente, orden_id))


@pytest.mark.v14_evaluacion
@pytest.mark.parametrize("usuario", [f.RECEPCION, f.COORDINADOR])
def test_evaluacion_solo_la_hace_el_tecnico(cliente, usuario):
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)
    f.conflicto(_evaluar(cliente, orden_id, "CONFIRMADO", usuario=usuario))
    # Otro tecnico, que no es el titular de la toma.
    f.conflicto(
        _evaluar(cliente, orden_id, "CONFIRMADO", usuario=f.TECNICO_B),
        codigo="TOMA_DE_OTRO_TECNICO",
    )


@pytest.mark.v14_evaluacion
def test_detalle_del_tecnico_no_requiere_evaluacion(cliente):
    orden_id = f.por_revision(cliente, f.BATERIA)
    detalle = f.detalle(_orden(cliente, orden_id), "DET-001")
    assert detalle["origen_diagnostico"] == "REVISION_TECNICA"
    assert detalle["requiere_evaluacion"] is False


def test_detalle_anterior_sin_origen_no_requiere_evaluacion(cliente):
    """Datos anteriores a la evaluacion: no se bloquean."""
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)
    detalle = f.detalle(_orden(cliente, orden_id), "DET-001")
    assert detalle["origen_diagnostico"] is None
    f.ok(_iniciar(cliente, orden_id))


# --- A1. La transicion no deja omitir la evaluacion -------------------------
#
# El modo de transicion (Detalle sin origen del diagnostico) existe solo para
# los datos anteriores a BR-REP-035. Una Orden nueva nunca lo genera: todo
# camino de alta fija el origen, el cliente no puede elegirlo y sin
# evaluacion no hay Ejecucion en ningun Origen.


def _crear_rt(cliente) -> str:
    orden_id = f.ok(
        cliente.post(
            "/api/orders/rt-interno",
            json={
                "usuario_id": f.RECEPCION,
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 13",
                    "falla_reportada": "No enciende.",
                },
                "referencia_rt": "RT-INGRESO-0010",
            },
        )
    )["id"]
    f.ok(
        definir_y_finalizar(
            cliente,
            orden_id,
            json={"usuario_id": f.RECEPCION, "tipo_reparacion_id": f.BATERIA},
        )
    )
    return orden_id


@pytest.mark.v14_evaluacion
def test_toda_alta_de_una_orden_nueva_fija_el_origen(cliente):
    externa = f.definida(cliente, f.BATERIA)  # 070, Recepcion
    revisada = f.por_revision(cliente, f.BATERIA)  # 075, Tecnico
    interna = _crear_rt(cliente)  # 070 en RT_INTERNO
    f.tomada(cliente, externa)
    f.ok(_adicional(cliente, externa))  # 128, Tecnico
    f.ok(  # 183 REQUIERE_REDEFINICION -> 127
        _evaluar(
            cliente,
            externa,
            "REQUIERE_REDEFINICION",
            observaciones="Es la pantalla.",
            tipo_reparacion_id=f.PANTALLA,
        )
    )

    origenes = {
        (orden_id, d["id"]): d["origen_diagnostico"]
        for orden_id in (externa, revisada, interna)
        for d in _orden(cliente, orden_id)["reparaciones_detail"]
    }
    assert None not in origenes.values()
    assert origenes == {
        (externa, "DET-001"): "REVISION_TECNICA",  # redefinido por el tecnico
        (externa, "DET-002"): "REVISION_TECNICA",  # adicional
        (revisada, "DET-001"): "REVISION_TECNICA",
        (interna, "DET-001"): "RECEPCION",
    }


@pytest.mark.v14_evaluacion
def test_el_origen_no_se_elige_desde_la_api(cliente):
    orden_id = f.crear(cliente)
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details",
            json={
                "usuario_id": f.RECEPCION,
                "tipo_reparacion_id": f.BATERIA,
                "origen_diagnostico": "REVISION_TECNICA",
                "evaluaciones": [
                    {
                        "version_definicion": 1,
                        "resultado": "CONFIRMADO",
                        "usuario_id": f.TECNICO,
                        "fecha": "2026-11-12T00:00:00Z",
                    }
                ],
            },
        )
    )
    detalle = f.detalle(orden, "DET-001")
    assert detalle["origen_diagnostico"] == "RECEPCION"
    assert detalle["evaluaciones"] == []
    assert detalle["requiere_evaluacion"] is True


@pytest.mark.v14_evaluacion
def test_rt_interno_tambien_exige_la_evaluacion(cliente):
    orden_id = _crear_rt(cliente)
    f.tomada(cliente, orden_id)
    assert "evaluacion tecnica" in f.conflicto(_iniciar(cliente, orden_id))
    f.ok(_evaluar(cliente, orden_id, "CONFIRMADO"))
    f.ok(_iniciar(cliente, orden_id))


def test_un_detalle_de_transicion_que_se_redefine_entra_al_circuito_v14(
    cliente,
):
    """Sin la marca: el Detalle nace sin origen (dato anterior). Si el
    tecnico lo redefine, la definicion nueva es suya (REVISION_TECNICA):
    ya no es un dato de transicion."""
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)
    ejecucion_id = f.iniciar(cliente, orden_id)
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion_id}"
            "/requires-redefinition",
            json={
                "usuario_id": f.TECNICO,
                "insumos_utilizados": [],
                "motivo": "No es la bateria.",
            },
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Es la pantalla."},
        )
    )
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/redefine",
            json={"usuario_id": f.TECNICO, "tipo_reparacion_id": f.PANTALLA},
        )
    )
    assert f.detalle(orden, "DET-001")["origen_diagnostico"] == (
        "REVISION_TECNICA"
    )


# --- A2. Reparaciones adicionales (PROC-REP-184 -> 128, BR-REP-037) ----------


def _adicional(cliente, orden_id, tipo=f.PANTALLA, usuario=f.TECNICO):
    return cliente.post(
        f"/api/orders/{orden_id}/details/additional",
        json={"usuario_id": usuario, "tipo_reparacion_id": tipo},
    )


@pytest.mark.v14_evaluacion
def test_evaluacion_confirmada_con_reparaciones_adicionales(cliente):
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)

    orden = f.ok(
        _evaluar(
            cliente,
            orden_id,
            "CONFIRMADO",
            adicionales=[
                {"tipo_reparacion_id": f.PANTALLA},
                {"tipo_reparacion_id": f.BATERIA, "observaciones": "Otra."},
            ],
        )
    )

    # Cada adicional es un Detalle nuevo del tecnico, pendiente del cliente.
    for nuevo in ("DET-002", "DET-003"):
        detalle = f.detalle(orden, nuevo)
        assert detalle["origen_diagnostico"] == "REVISION_TECNICA"
        assert detalle["estado_autorizacion"] == "PENDIENTE"
        assert detalle["requiere_evaluacion"] is False
    assert f.detalle(orden, "DET-003")["observaciones"] == "Otra."
    tramo = _pasos(orden)[-6:]
    assert tramo == [
        ("PROC-REP-183", "CONFIRMADO (definicion v1)"),
        ("PROC-REP-184", "Otra reparacion adicional por registrar"),
        ("PROC-REP-128", "Detectado en la evaluacion tecnica de DET-001"),
        ("PROC-REP-184", "Otra reparacion adicional por registrar"),
        ("PROC-REP-128", "Detectado en la evaluacion tecnica de DET-001"),
        ("PROC-REP-184", "Original CONFIRMADO"),
    ]
    # El original sigue a ejecucion sin esperar la decision del cliente.
    assert f.detalle(orden, "DET-001")["estado_autorizacion"] == "AUTORIZADO"
    assert ("INICIAR_DETALLE", "DET-001") in [
        (a["codigo"], a["detalle_id"]) for a in orden["acciones_disponibles"]
    ]
    f.ok(_iniciar(cliente, orden_id))
    # Recepcion resuelve despues, por su carril.
    orden = f.ok(f.decidir(cliente, orden_id, {"DET-002": "AUTORIZADO"}))
    assert f.detalle(orden, "DET-002")["estado_autorizacion"] == "AUTORIZADO"
    assert orden["ejecuciones"][0]["estado"] == "EN_PROGRESO"


@pytest.mark.v14_evaluacion
def test_descarte_del_unico_detalle_con_una_adicional_no_deja_la_orden_vacia(
    cliente,
):
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)

    orden = f.ok(
        _evaluar(
            cliente,
            orden_id,
            "DESCARTADO",
            observaciones="No es la bateria.",
            adicionales=[{"tipo_reparacion_id": f.PANTALLA}],
        )
    )

    assert f.detalle(orden, "DET-001")["estado"] == "CANCELADO"
    assert f.detalle(orden, "DET-002")["estado_autorizacion"] == "PENDIENTE"
    # El resolver corre despues de registrar la adicional: espera al
    # cliente (129), no "sin trabajos vigentes" (307).
    assert orden["current_process"] == "PROC-REP-129"
    assert orden["situacion"]["codigo"] != "SIN_TRABAJOS_VIGENTES"


def test_adicional_durante_la_ejecucion_no_la_interrumpe(cliente):
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)
    ejecucion_id = f.iniciar(cliente, orden_id)
    orden = _orden(cliente, orden_id)
    assert "AGREGAR_TRABAJO_ADICIONAL" in [
        a["codigo"] for a in orden["acciones_complementarias"]
    ]

    orden = f.ok(_adicional(cliente, orden_id))

    detalle = f.detalle(orden, "DET-002")
    assert detalle["estado_autorizacion"] == "PENDIENTE"
    assert detalle["tipo_reparacion_id"] == f.PANTALLA
    assert [e["id"] for e in orden["ejecuciones"]] == [ejecucion_id]
    assert orden["ejecuciones"][0]["estado"] == "EN_PROGRESO"
    assert orden["toma_activa"]["usuario_id"] == f.TECNICO
    paso = orden["historial"][-1]
    assert (paso["referencia_id"], paso["usuario_id"]) == (
        "PROC-REP-128",
        f.TECNICO,
    )
    assert paso["observacion"] == "Detectado durante la ejecucion"


@pytest.mark.parametrize("usuario", [f.RECEPCION, f.COORDINADOR])
def test_adicional_solo_la_registra_el_tecnico(cliente, usuario):
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)
    f.conflicto(_adicional(cliente, orden_id, usuario=usuario))
    f.conflicto(
        _adicional(cliente, orden_id, usuario=f.TECNICO_B),
        codigo="TOMA_DE_OTRO_TECNICO",
    )


def test_adicional_exige_la_toma_y_un_tipo_del_catalogo(cliente):
    orden_id = f.definida(cliente)
    f.conflicto(_adicional(cliente, orden_id))  # sin toma
    f.tomada(cliente, orden_id)
    # «Otros» no es una fila del catalogo: su precio manual es de Recepcion.
    respuesta = _adicional(cliente, orden_id, tipo="TR-OTROS")
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["codigo"] == "NO_ENCONTRADO"


def test_adicional_en_rt_interno_pasa_por_la_factibilidad(cliente):
    orden_id = f.ok(
        cliente.post(
            "/api/orders/rt-interno",
            json={
                "usuario_id": f.RECEPCION,
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 13",
                    "falla_reportada": "No enciende.",
                },
                "referencia_rt": "RT-INGRESO-0009",
            },
        )
    )["id"]
    f.ok(
        definir_y_finalizar(
            cliente,
            orden_id,
            json={"usuario_id": f.RECEPCION, "tipo_reparacion_id": f.BATERIA},
        )
    )
    f.tomada(cliente, orden_id)

    orden = f.ok(_adicional(cliente, orden_id))

    detalle = f.detalle(orden, "DET-002")
    assert detalle["condicion"] == "SIN_BLOQUEO"
    ids = [ref for ref, _ in _pasos(orden)]
    assert ids[-4:-1] == ["PROC-REP-128", "PROC-REP-080", "PROC-REP-090"]


# --- B. Desistimiento total guiado (DC07C) -----------------------------------


def test_var_rep_043_desistimiento_total_guiado(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    f.tomada(cliente, orden_id)
    ejecucion_id = f.iniciar(cliente, orden_id, "DET-001")
    analisis = _orden(cliente, orden_id)["desistimiento"]
    assert analisis["en_ejecucion"] == ["DET-001"]
    assert analisis["bloqueantes"] == []

    # 1. La solicitud total: nada se cancela todavia.
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/withdrawal",
            json={
                "usuario_id": f.RECEPCION,
                "canal": "TELEFONO",
                "motivo": "No quiere seguir con la reparacion.",
            },
        )
    )
    for detalle_id in ("DET-001", "DET-002"):
        detalle = f.detalle(orden, detalle_id)
        solicitud = detalle["solicitud_desistimiento"]
        assert solicitud["usuario_id"] == f.RECEPCION
        assert detalle["cancelacion"] is None
    assert orden["ejecuciones"][0]["estado"] == "EN_PROGRESO"
    # No se duplica.
    f.conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/withdrawal",
            json={
                "usuario_id": f.RECEPCION,
                "canal": "TELEFONO",
                "motivo": "x",
            },
        )
    )
    # El tecnico solo puede interrumpir.
    assert "COMPLETAR_EJECUCION" not in f.codigos(_orden(cliente, orden_id))

    # 2. Interrupcion y cancelacion efectiva conjunta (211 -> 305).
    orden = f.ok(
        it.interrumpir(
            cliente,
            orden_id,
            ejecucion_id,
            estado_trabajo="Equipo abierto, sin cambios.",
            reversible=True,
        )
    )
    for detalle_id in ("DET-001", "DET-002"):
        detalle = f.detalle(orden, detalle_id)
        assert detalle["estado"] == "CANCELADO"
        assert detalle["cancelacion"]["origen"] == "DESISTIMIENTO_CLIENTE"
        assert detalle["cancelacion"]["usuario_id"] == f.TECNICO
    assert "PROC-REP-305" in [ref for ref, _ in _pasos(orden)]
    # DC31: la Orden sigue abierta sin trabajos vigentes.
    assert orden["current_process"] == "PROC-REP-307"
    f.ok(f.devolver(cliente, orden_id))
    orden = f.ok(f.cancelar_orden(cliente, orden_id))
    assert orden["estado_workflow"] == "CANCELADA"


def test_desistimiento_total_conserva_lo_completo(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id, "DET-001", f.BATERIA)
    ejecucion_id = f.iniciar(cliente, orden_id, "DET-002")
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/withdrawal",
            json={
                "usuario_id": f.RECEPCION,
                "canal": "EMAIL",
                "motivo": "Basta.",
            },
        )
    )
    orden = f.ok(
        it.interrumpir(
            cliente,
            orden_id,
            ejecucion_id,
            estado_trabajo="Pantalla sin colocar.",
            reversible=False,
        )
    )
    assert f.detalle(orden, "DET-001")["estado"] == "COMPLETO"
    assert f.detalle(orden, "DET-002")["estado"] == "CANCELADO"
    assert f.detalle(orden, "DET-003")["estado"] == "CANCELADO"
    assert orden["estado_workflow"] != "CANCELADA"


# --- F. Antecedentes del Equipo ---------------------------------------------


def _crear_con_imei(cliente, imei, serie=None) -> str:
    return f.ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": f.RECEPCION,
                "cliente": {"nombre_apellido": "Cliente", "telefono": "341-1"},
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 14",
                    "falla_reportada": "No carga.",
                    "imei": imei,
                    "numero_serie": serie,
                },
            },
        )
    )["id"]


def test_antecedentes_del_equipo_por_imei_y_serie(cliente):
    primera = _crear_con_imei(cliente, "356938035643809", "F2LX1")
    segunda = _crear_con_imei(cliente, "35 6938 0356 43809")
    otra = _crear_con_imei(cliente, "999999999999999")

    resultado = f.ok(
        cliente.get(
            "/api/equipment/history",
            params={"imei": "356938035643809", "excluir_orden_id": segunda},
        )
    )
    assert resultado["sin_identificacion"] is False
    assert [o["orden_id"] for o in resultado["ordenes"]] == [primera]
    assert resultado["ordenes"][0]["coincide_por"] == ["IMEI"]
    por_serie = f.ok(
        cliente.get(
            "/api/equipment/history", params={"numero_serie": "f2lx1"}
        )
    )
    assert [o["orden_id"] for o in por_serie["ordenes"]] == [primera]
    assert otra not in [o["orden_id"] for o in resultado["ordenes"]]
    vacio = f.ok(cliente.get("/api/equipment/history"))
    assert vacio["sin_identificacion"] is True and vacio["ordenes"] == []
    # Sin datos del cliente: quien consulta ve el equipo y sus trabajos.
    assert set(resultado["ordenes"][0]) == {
        "orden_id",
        "origen",
        "estado_workflow",
        "creada_en",
        "entregada_en",
        "falla_reportada",
        "orden_origen_id",
        "trabajos",
        "coincide_por",
    }
    assert "Cliente" not in str(resultado) and "341-1" not in str(resultado)


# --- K. Reporte operativo ---------------------------------------------------


def test_reporte_operativo(cliente):
    entregada = it.entregada(cliente)
    abierta = f.definida(cliente, f.BATERIA)
    it.pagar(cliente, abierta, "10000")

    reporte = f.ok(cliente.get("/api/reports/operational"))

    assert reporte["ordenes_por_estado"]["ENTREGADA"] == 1
    assert sum(reporte["ordenes_por_origen"].values()) == 2
    (tecnico,) = reporte["trabajos_por_tecnico"]
    assert tecnico["usuario_id"] == f.TECNICO
    assert tecnico["completadas"] == 1 and tecnico["puntaje"] == 10
    (estacion,) = reporte["tiempos_por_estacion"]
    assert estacion["estacion_id"] == f.ESTACION
    assert estacion["ejecuciones"] == 1
    assert [p["orden_id"] for p in reporte["pendientes"]] == [abierta]
    assert entregada not in [p["orden_id"] for p in reporte["pendientes"]]
    assert reporte["consumo_insumos"] == [
        {"insumo_id": f.INSUMO_BATERIA, "cantidad": "1"}
    ]
    assert Decimal(reporte["cobros"]["cobrado"]) == Decimal("90000")
    # Solo agregados: ningun dato personal del cliente.
    texto = str(reporte)
    for orden_id in (entregada, abierta):
        cliente_orden = _orden(cliente, orden_id)["cliente"]
        assert cliente_orden["nombre_apellido"] not in texto
        assert cliente_orden["telefono"] not in texto
    assert Decimal(reporte["cobros"]["saldo_pendiente_ordenes_abiertas"]) == (
        Decimal("70000")
    )
