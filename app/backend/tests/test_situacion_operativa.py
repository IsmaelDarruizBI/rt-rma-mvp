"""Situacion operativa de la Orden (``OrdenOut.situacion``), por HTTP.

Solo lectura para la pantalla: que esta pasando, a quien le toca y que
sigue. Se deriva de las acciones que la Orden ya publica -cada tarea
apunta a esas mismas acciones-, conserva los estados mixtos como avisos y
resume el avance en seis etapas. No cambia ninguna regla: consultarla no
modifica la Orden.
"""

import json

from tests.fixtures.api_salidas import (
    BATERIA,
    COORDINADOR,
    ESTACION,
    PANTALLA,
    RECEPCION,
    TECNICO,
    agregar,
    aprobar,
    archivo,
    cancelar_orden,
    cerrar_ejecucion,
    crear,
    decidir,
    definida,
    finalizar,
    iniciar,
    ok,
    tomada,
)
from tests.fixtures.custodia import (
    confirmar_recepcion,
    entregar,
    registrar_checkin,
)
from tests.test_api_hp_rep_002 import _crear_orden_rt
from tests.test_inventario_operativo import _cliente


def _revisada(cliente, *tipos) -> str:
    """Revisada y definida (camino de revision), con los trabajos
    esperando la decision del cliente y la recepcion SIN confirmar.

    En CLIENTE_EXTERNO el ingreso inicial confirma y autoriza con el
    comprobante de ingreso: estos estados quedan del camino de revision.
    """
    orden_id = crear(cliente)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/send-to-review",
            json={"usuario_id": RECEPCION},
        )
    )
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/technical-review",
            json={"usuario_id": TECNICO, "resultado": "Diagnostico."},
        )
    )
    for tipo in tipos or (BATERIA,):
        ok(
            cliente.post(
                f"/api/orders/{orden_id}/review/details",
                json={"usuario_id": RECEPCION, "tipo_reparacion_id": tipo},
            )
        )
    finalizar(cliente, orden_id, confirmar_recepcion=False)
    return orden_id


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _situacion(cliente, orden_id) -> dict:
    return _orden(cliente, orden_id)["situacion"]


def _codigos(tarea: dict) -> list[str]:
    return [accion["codigo"] for accion in tarea["acciones"]]


def _etapas(situacion: dict) -> dict[str, str]:
    return {etapa["codigo"]: etapa["estado"] for etapa in situacion["etapas"]}


def _avisos(situacion: dict) -> list[str]:
    return [aviso["codigo"] for aviso in situacion["avisos"]]


def _notificar(cliente, orden_id):
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )


def _pagar(cliente, orden_id, monto):
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": RECEPCION,
                "monto": monto,
                "metodo": "EFECTIVO",
            },
        )
    )


def _reparada(cliente) -> str:
    """Una bateria reparada y con el control aprobado."""
    orden_id = definida(cliente)
    tomada(cliente, orden_id)
    ok(cerrar_ejecucion(cliente, orden_id, iniciar(cliente, orden_id)))
    ok(aprobar(cliente, orden_id, "DET-001"))
    return orden_id


# --- Ingreso y definicion ----------------------------------------------------


def test_recien_creada_pendiente_de_recepcion_y_de_definicion(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = crear(cliente)

        situacion = _situacion(cliente, orden_id)

        assert situacion["codigo"] == "PENDIENTE_RECEPCION"
        assert situacion["titulo"] == "Pendiente de recepción"
        # Ingreso inicial (MVP v2): cargar los trabajos y generar el
        # comprobante de ingreso, que confirma la recepcion. No hay una
        # tarea suelta de confirmacion.
        (cargar,) = situacion["tareas"]
        assert cargar["titulo"] == "Cargar los trabajos"
        assert _codigos(cargar) == ["AGREGAR_DETALLE", "ENVIAR_A_REVISION"]
        assert cargar["responsable"] == "Recepción"
        assert situacion["responsable"] == cargar["responsable"]
        assert situacion["desde"] is not None
        assert _etapas(situacion) == {
            "INGRESO": "EN_CURSO",
            "AUTORIZACION": "PENDIENTE",
            "REPUESTOS": "PENDIENTE",
            "TALLER": "PENDIENTE",
            "CONTROL": "PENDIENTE",
            "ENTREGA": "PENDIENTE",
        }


def test_con_trabajos_cargados_genera_el_comprobante_de_ingreso(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = crear(cliente)
        agregar(cliente, orden_id)

        situacion = _situacion(cliente, orden_id)

        # 2 cargar los trabajos, 3 generar el comprobante de ingreso.
        assert situacion["codigo"] == "PENDIENTE_RECEPCION"
        (generar,) = situacion["tareas"]
        assert generar["titulo"] == (
            "Generar el comprobante de ingreso y autorización"
        )
        assert _codigos(generar) == [
            "AGREGAR_DETALLE",
            "GENERAR_COMPROBANTE_INGRESO",
        ]
        # Sin estado fisico, el motivo dice que falta. El check-in ya no
        # (se registra antes de la entrega, UAT-009).
        assert "estado fisico" in generar["motivo"]
        assert "check-in" not in generar["motivo"]
        accion = generar["acciones"][1]
        assert accion["bloqueo"].startswith("Para generarlo falta")
        assert situacion["avisos"] == []


def test_con_recepcion_confirmada_queda_pendiente_de_definicion(tmp_path):
    """Una Orden anterior a la iteracion 1, con la recepcion confirmada
    por separado: solo le falta el comprobante de ingreso."""
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = crear(cliente)
        confirmar_recepcion(cliente, orden_id)  # prepara los datos
        agregar(cliente, orden_id)
        ruta = tmp_path / "ordenes" / f"{orden_id}.json"
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        datos["recepcion"]["confirmacion"] = {
            "usuario_id": RECEPCION,
            "fecha": datos["created_at"],
            "observaciones": None,
        }
        ruta.write_text(json.dumps(datos), encoding="utf-8")

        situacion = _situacion(cliente, orden_id)

        assert situacion["codigo"] == "PENDIENTE_DEFINICION"
        (tarea,) = situacion["tareas"]
        assert tarea["titulo"] == (
            "Generar el comprobante de ingreso y autorización"
        )
        assert _codigos(tarea) == [
            "AGREGAR_DETALLE",
            "GENERAR_COMPROBANTE_INGRESO",
        ]
        assert situacion["avisos"] == []


def test_esperando_autorizacion_del_cliente(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _revisada(cliente)
        confirmar_recepcion(cliente, orden_id)

        situacion = _situacion(cliente, orden_id)

        assert situacion["codigo"] == "ESPERANDO_AUTORIZACION"
        assert "Cambio" in situacion["descripcion"]
        (tarea,) = situacion["tareas"]
        assert _codigos(tarea) == ["REGISTRAR_DECISION_CLIENTE"]
        assert tarea["responsable"] == "Recepción"
        historial = _orden(cliente, orden_id)["historial"]
        espera = [p for p in historial if p["referencia_id"] == "PROC-REP-129"]
        assert situacion["desde"] == espera[-1]["fecha"]
        assert _etapas(situacion)["AUTORIZACION"] == "EN_CURSO"
        assert _etapas(situacion)["INGRESO"] == "COMPLETA"


# --- Recursos, prioridad, cola y taller --------------------------------------


def test_esperando_repuestos_en_100_y_en_120(tmp_path):
    with _cliente(tmp_path, stock_bateria="0") as cliente:
        orden_id = definida(cliente)

        situacion = _situacion(cliente, orden_id)
        assert situacion["codigo"] == "ESPERANDO_RECURSOS"
        assert situacion["responsable"] == "Coordinación RMA"
        esperar, forzar = situacion["tareas"]
        assert _codigos(esperar) == ["ESPERAR_RECURSOS"]
        assert esperar["responsable"] == "Cualquier usuario"
        assert _codigos(forzar) == ["OVERRIDE_RECURSOS"]
        assert forzar["responsable"] == "Coordinación RMA"
        assert _etapas(situacion)["REPUESTOS"] == "EN_CURSO"

        ok(cliente.post(f"/api/orders/{orden_id}/resources/wait"))
        revalidar, _ = _situacion(cliente, orden_id)["tareas"]
        assert _codigos(revalidar) == ["REVALIDAR_RECURSOS"]


def test_pendiente_de_prioridad_en_cola_y_tomada(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        # Fuera del ingreso inicial (revision) no entra sola a la cola.
        orden_id = definida(cliente, autorizar=False)
        ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
        situacion = _situacion(cliente, orden_id)
        assert situacion["codigo"] == "PENDIENTE_PRIORIDAD"
        assert situacion["responsable"] == "Recepción o Coordinación RMA"

        ok(
            cliente.post(
                f"/api/orders/{orden_id}/queue",
                json={"usuario_id": COORDINADOR, "prioridad": 4},
            )
        )
        situacion = _situacion(cliente, orden_id)
        assert situacion["codigo"] == "EN_COLA"
        assert situacion["titulo"] == "En cola (prioridad 4 · Normal)"
        (tarea,) = situacion["tareas"]
        assert _codigos(tarea) == ["TOMAR"]
        assert tarea["responsable"] == "Técnico"
        assert _etapas(situacion)["TALLER"] == "EN_CURSO"

        ok(
            cliente.post(
                f"/api/orders/{orden_id}/take",
                json={"usuario_id": TECNICO, "estacion_id": ESTACION},
            )
        )
        situacion = _situacion(cliente, orden_id)
        assert situacion["codigo"] == "TOMADA"
        (tarea,) = situacion["tareas"]
        assert _codigos(tarea) == ["INICIAR_DETALLE"]
        assert tarea["acciones"][0]["usuario_id"] == TECNICO
        assert situacion["responsable"] == "Técnico titular"
        toma = _orden(cliente, orden_id)["toma_activa"]
        assert situacion["desde"] == toma["inicio"]


def test_tomada_sin_custodia_la_recepcion_es_lo_que_sigue(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _revisada(cliente)
        ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
        tomada(cliente, orden_id)

        situacion = _situacion(cliente, orden_id)

        assert situacion["codigo"] == "PENDIENTE_RECEPCION"
        (tarea,) = situacion["tareas"]
        assert _codigos(tarea) == ["CONFIRMAR_RECEPCION"]
        assert "RECEPCION_PENDIENTE" not in _avisos(situacion)


def test_en_reparacion_completar_o_interrumpir(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente)
        tomada(cliente, orden_id)
        ejecucion_id = iniciar(cliente, orden_id)

        situacion = _situacion(cliente, orden_id)

        assert situacion["codigo"] == "EN_REPARACION"
        assert "Cambio" in situacion["descripcion"]
        (tarea,) = situacion["tareas"]
        # Interrumpir es la otra salida de la misma Ejecucion: va en la
        # tarea. Pedir la redefinicion sigue siendo especial.
        assert _codigos(tarea) == [
            "COMPLETAR_EJECUCION",
            "INTERRUMPIR_EJECUCION",
        ]
        for accion in tarea["acciones"]:
            assert accion["ejecucion_id"] == ejecucion_id
            assert accion["usuario_id"] == TECNICO
        ejecucion = _orden(cliente, orden_id)["ejecuciones"][0]
        assert situacion["desde"] == ejecucion["inicio"]


def test_requiere_revision_tecnica_y_redefinicion(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente)
        tomada(cliente, orden_id)
        ejecucion_id = iniciar(cliente, orden_id)
        ok(
            cliente.post(
                f"/api/orders/{orden_id}/executions/{ejecucion_id}"
                "/requires-redefinition",
                json={
                    "usuario_id": TECNICO,
                    "insumos_utilizados": [],
                    "motivo": "Es la placa.",
                },
            )
        )

        situacion = _situacion(cliente, orden_id)
        assert situacion["codigo"] == "REQUIERE_REVISION_TECNICA"
        (revisar,) = situacion["tareas"]
        assert _codigos(revisar) == ["REVISAR_DETALLE"]

        ok(
            cliente.post(
                f"/api/orders/{orden_id}/details/DET-001/technical-review",
                json={"usuario_id": TECNICO, "resultado": "Placa"},
            )
        )
        (redefinir,) = _situacion(cliente, orden_id)["tareas"]
        assert _codigos(redefinir) == ["REDEFINIR_DETALLE"]
        assert redefinir["responsable"] == "Recepción"


def test_control_de_la_reparacion_aprobar_o_rechazar(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente)
        tomada(cliente, orden_id)
        ok(cerrar_ejecucion(cliente, orden_id, iniciar(cliente, orden_id)))

        situacion = _situacion(cliente, orden_id)

        assert situacion["codigo"] == "CONTROL_TECNICO"
        (tarea,) = situacion["tareas"]
        assert _codigos(tarea) == ["APROBAR_CONTROL", "RECHAZAR_CONTROL"]
        etapas = _etapas(situacion)
        assert (etapas["TALLER"], etapas["CONTROL"]) == (
            "COMPLETA",
            "EN_CURSO",
        )


# --- Cierre ------------------------------------------------------------------


def test_aviso_cobro_y_entrega(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _reparada(cliente)

        situacion = _situacion(cliente, orden_id)
        assert situacion["codigo"] == "PENDIENTE_NOTIFICACION"
        assert _codigos(situacion["tareas"][0]) == ["NOTIFICAR"]
        # El saldo no se oculta aunque lo principal sea avisar.
        assert _avisos(situacion) == ["SALDO_PENDIENTE"]

        saldo = _notificar(cliente, orden_id)["resumen"]["saldo"]
        situacion = _situacion(cliente, orden_id)
        assert situacion["codigo"] == "PENDIENTE_COBRO"
        (tarea,) = situacion["tareas"]
        assert _codigos(tarea) == ["REGISTRAR_PAGO"]
        assert "80.000,00" in situacion["descripcion"]
        assert situacion["avisos"] == []

        _pagar(cliente, orden_id, saldo)
        situacion = _situacion(cliente, orden_id)
        # Avisada y saldada: antes de entregar falta el check-in. Es solo
        # presentacion: el workflow sigue en REPARACION_LISTA.
        assert situacion["codigo"] == "PENDIENTE_CHECKIN"
        assert situacion["titulo"] == (
            "Pendiente de verificación de funciones básicas"
        )
        checkin, entrega = situacion["tareas"]
        assert _codigos(checkin) == ["REGISTRAR_CHECKIN"]
        assert _codigos(entrega) == ["ENTREGAR"]
        assert entrega["acciones"][0]["bloqueo"] == (
            "Falta registrar el check-in"
        )

        ok(registrar_checkin(cliente, orden_id))
        situacion = _situacion(cliente, orden_id)
        assert situacion["codigo"] == "LISTA_PARA_ENTREGAR"
        assert situacion["titulo"] == "Lista para entregar"
        (entrega,) = situacion["tareas"]
        assert _codigos(entrega) == ["ENTREGAR"]
        assert _etapas(situacion)["ENTREGA"] == "EN_CURSO"

        ok(entregar(cliente, orden_id))
        situacion = _situacion(cliente, orden_id)
        assert (situacion["codigo"], situacion["titulo"]) == (
            "CERRADA",
            "Entregada",
        )
        assert situacion["tareas"] == [] and situacion["avisos"] == []
        assert (
            situacion["desde"] == _orden(cliente, orden_id)["entrega"]["fecha"]
        )
        assert set(_etapas(situacion).values()) == {"COMPLETA"}


def test_cancelada_pendiente_de_devolver_el_equipo(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente)
        ok(cancelar_orden(cliente, orden_id))

        situacion = _situacion(cliente, orden_id)

        assert situacion["codigo"] == "CANCELADA_PENDIENTE_DEVOLUCION"
        assert situacion["titulo"] == "Cancelada: devolver el equipo"
        (tarea,) = situacion["tareas"]
        assert _codigos(tarea) == ["REGISTRAR_DEVOLUCION"]
        assert _etapas(situacion)["ENTREGA"] == "EN_CURSO"


def test_rt_interno_informa_a_gestion_rt_sin_autorizacion(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _crear_orden_rt(cliente)
        agregar(cliente, orden_id, BATERIA)
        finalizar(cliente, orden_id, confirmar_recepcion=False)
        tomada(cliente, orden_id)
        ok(cerrar_ejecucion(cliente, orden_id, iniciar(cliente, orden_id)))
        ok(aprobar(cliente, orden_id, "DET-001"))

        situacion = _situacion(cliente, orden_id)

        assert situacion["codigo"] == "PENDIENTE_NOTIFICACION"
        (tarea,) = situacion["tareas"]
        assert _codigos(tarea) == ["INFORMAR_RT"]
        assert tarea["responsable"] == "Cualquier usuario"
        assert _etapas(situacion)["AUTORIZACION"] == "NO_APLICA"
        assert situacion["avisos"] == []


# --- Estados mixtos y solo lectura -------------------------------------------


def test_estado_mixto_conserva_los_bloqueos_secundarios(tmp_path):
    with _cliente(tmp_path, stock_bateria="5", stock_pantalla="0") as cliente:
        orden_id = _revisada(cliente, BATERIA, PANTALLA, PANTALLA)
        ok(
            decidir(
                cliente,
                orden_id,
                {"DET-001": "AUTORIZADO", "DET-002": "AUTORIZADO"},
            )
        )

        situacion = _situacion(cliente, orden_id)

        # Lo principal es lo trabajable; lo demas sigue a la vista.
        assert situacion["codigo"] == "PENDIENTE_PRIORIDAD"
        avisos = {aviso["codigo"]: aviso for aviso in situacion["avisos"]}
        assert set(avisos) == {
            "RECEPCION_PENDIENTE",
            "AUTORIZACION_PENDIENTE",
            "SIN_REPUESTOS",
        }
        assert _codigos(avisos["AUTORIZACION_PENDIENTE"]) == [
            "REGISTRAR_DECISION_CLIENTE"
        ]
        assert [
            (a["codigo"], a["detalle_id"])
            for a in avisos["SIN_REPUESTOS"]["acciones"]
        ] == [("OVERRIDE_RECURSOS", "DET-002")]
        etapas = _etapas(situacion)
        assert etapas["AUTORIZACION"] == "EN_CURSO"
        assert etapas["REPUESTOS"] == "EN_CURSO"


def test_las_tareas_apuntan_a_acciones_que_la_orden_ya_publica(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        ordenes = [crear(cliente), definida(cliente), _reparada(cliente)]
        for orden_id in ordenes:
            orden = _orden(cliente, orden_id)
            publicadas = [
                accion
                for grupo in (
                    "acciones_disponibles",
                    "acciones_autorizacion",
                    "acciones_financieras",
                    "acciones_custodia",
                )
                for accion in orden[grupo]
            ]
            situacion = orden["situacion"]
            for tarea in situacion["tareas"]:
                for accion in tarea["acciones"]:
                    assert accion in publicadas
            for aviso in situacion["avisos"]:
                for accion in aviso["acciones"]:
                    assert accion in publicadas


def test_consultar_la_situacion_no_modifica_la_orden(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente)
        antes = archivo(tmp_path, orden_id)

        for _ in range(3):
            assert _situacion(cliente, orden_id)["codigo"]

        assert archivo(tmp_path, orden_id) == antes
