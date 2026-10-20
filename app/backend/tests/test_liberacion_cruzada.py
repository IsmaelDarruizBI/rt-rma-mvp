"""Liberar una Orden tomada por otro tecnico (iteracion 1 del UAT).

Cualquier tecnico (o Coordinacion) puede liberar la Orden de otro: el
aviso dice quien la tiene, exige confirmacion y motivo. Si hay una
reparacion en curso se interrumpe con la logica de siempre (lo usado se
consume, lo reservado vuelve). La Orden vuelve a la cola y otro tecnico
la puede tomar. Queda el titular anterior, quien libero, cuando, el
motivo y el estado de la Orden y de cada trabajo.
"""

import threading
from decimal import Decimal

import pytest

from app.application import (
    AccionDisponible,
    construir_contexto,
    liberar_orden,
    puede_ejecutar,
)
from app.core.config import Settings
from app.domain.models import RolUsuario, Usuario
from tests.fixtures.api_salidas import (
    COORDINADOR,
    INSUMO_BATERIA,
    RECEPCION,
    TECNICO,
    TECNICO_B,
    aprobar,
    archivo,
    cerrar_ejecucion,
    cliente_http,
    conflicto,
    ejecutar,
    ids,
    iniciar,
    notificar_pagar_entregar,
    ok,
    stock,
    tomar,
)
from tests.fixtures.ingreso_inicial import complementarias, ingresada

MOTIVO = "TECH-001 no vino hoy y el cliente espera."


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path, stock="5") as test_client:
        yield test_client


def _liberar(
    cliente,
    orden_id,
    usuario=TECNICO_B,
    motivo=MOTIVO,
    confirmado=True,
    **extra,
):
    return cliente.post(
        f"/api/orders/{orden_id}/release",
        json={
            "usuario_id": usuario,
            "motivo": motivo,
            "confirmado": confirmado,
            **extra,
        },
    )


def _ejecutar_como(cliente, orden_id, tecnico):
    ejecucion_id = iniciar(cliente, orden_id, tecnico=tecnico)
    return ok(
        cerrar_ejecucion(cliente, orden_id, ejecucion_id, tecnico=tecnico)
    )


def _reservas(cliente, insumo=INSUMO_BATERIA) -> list[dict]:
    return ok(cliente.get(f"/api/inventory/{insumo}"))["reservas"]


def _accion(orden) -> dict:
    (accion,) = [
        a
        for a in orden["acciones_complementarias"]
        if a["codigo"] == "LIBERAR_ORDEN_AJENA"
    ]
    return accion


def test_se_ofrece_a_los_demas_y_no_al_titular(cliente):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)

    accion = _accion(ok(cliente.get(f"/api/orders/{orden_id}")))

    assert accion["usuario_excluido_id"] == TECNICO
    assert TECNICO in accion["etiqueta"]
    assert set(accion["roles"]) == {"TECNICO", "COORDINADOR_RMA"}
    disponible = AccionDisponible(
        codigo=accion["codigo"],
        etiqueta=accion["etiqueta"],
        roles=(RolUsuario.TECNICO, RolUsuario.COORDINADOR_RMA),
        usuario_excluido_id=accion["usuario_excluido_id"],
    )
    titular = Usuario(id=TECNICO, nombre="A", rol=RolUsuario.TECNICO)
    otro = Usuario(id=TECNICO_B, nombre="B", rol=RolUsuario.TECNICO)
    recepcion = Usuario(id=RECEPCION, nombre="R", rol=RolUsuario.RECEPCION)
    assert not puede_ejecutar(disponible, titular)
    assert puede_ejecutar(disponible, otro)
    assert not puede_ejecutar(disponible, recepcion)


def test_pide_confirmacion_con_el_aviso_de_quien_la_tiene(cliente, tmp_path):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(
        _liberar(cliente, orden_id, confirmado=False), "CONFIRMACION_REQUERIDA"
    )
    assert TECNICO in mensaje
    assert "cola" in mensaje
    sin_motivo = conflicto(_liberar(cliente, orden_id, motivo="  "))
    assert "motivo" in sin_motivo
    conflicto(_liberar(cliente, orden_id, usuario=RECEPCION))

    assert archivo(tmp_path, orden_id) == antes


def test_libera_vuelve_a_la_cola_y_otro_la_retoma(cliente):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)

    orden = ok(_liberar(cliente, orden_id))

    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["toma_activa"] is None
    (toma,) = orden["tomas"]
    assert toma["usuario_id"] == TECNICO
    assert toma["estado"] == "CERRADA"
    assert toma["liberada_por"] == TECNICO_B
    assert toma["motivo_liberacion"] == MOTIVO
    assert ids(orden)[-2:] == ["PROC-REP-213", "PROC-REP-170"]
    liberacion = orden["historial"][-2]
    assert liberacion["usuario_id"] == TECNICO_B
    assert liberacion["fecha"] is not None
    for dato in (TECNICO, TECNICO_B, MOTIVO, "DET-001 DEFINIDO"):
        assert dato in liberacion["observacion"]

    retomada = tomar(cliente, orden_id, TECNICO_B)
    assert retomada["toma_activa"]["usuario_id"] == TECNICO_B
    _ejecutar_como(cliente, orden_id, TECNICO_B)
    ok(aprobar(cliente, orden_id, "DET-001"))
    assert notificar_pagar_entregar(cliente, orden_id)["estado_workflow"] == (
        "ENTREGADA"
    )


def test_con_una_reparacion_en_curso_la_interrumpe(cliente, tmp_path):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)
    ejecucion_id = iniciar(cliente, orden_id)
    assert len(_reservas(cliente)) == 1
    stock_antes = stock(tmp_path)

    orden = ok(_liberar(cliente, orden_id))

    (ejecucion,) = orden["ejecuciones"]
    assert ejecucion["id"] == ejecucion_id
    assert ejecucion["estado"] == "INTERRUMPIDO"
    assert ejecucion["motivo_interrupcion"] == (
        f"Liberada por {TECNICO_B} (titular {TECNICO}): {MOTIVO}"
    )
    assert orden["reparaciones_detail"][0]["estado"] == "DEFINIDO"
    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["toma_activa"] is None
    # Lo reservado y no usado vuelve; nada se consumio.
    assert _reservas(cliente) == []
    assert stock(tmp_path) == stock_antes
    # El titular anterior ya no puede cerrar esa ejecucion.
    conflicto(
        cerrar_ejecucion(cliente, orden_id, ejecucion_id, tecnico=TECNICO)
    )
    # Otro tecnico la retoma y la termina.
    tomar(cliente, orden_id, TECNICO_B)
    _ejecutar_como(cliente, orden_id, TECNICO_B)
    assert stock(tmp_path) == stock_antes - Decimal("1")


def test_lo_ya_usado_se_consume(cliente, tmp_path):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)
    iniciar(cliente, orden_id)
    stock_antes = stock(tmp_path)

    ok(
        _liberar(
            cliente,
            orden_id,
            usuario=COORDINADOR,
            insumos_utilizados=[
                {"insumo_id": INSUMO_BATERIA, "cantidad": "1"}
            ],
        )
    )

    assert stock(tmp_path) == stock_antes - Decimal("1")
    assert _reservas(cliente) == []


def test_el_titular_libera_como_siempre(cliente):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)

    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/release", json={"usuario_id": TECNICO}
        )
    )

    (toma,) = orden["tomas"]
    assert toma["liberada_por"] is None
    assert orden["estado_workflow"] == "EN_COLA"


def test_el_titular_con_una_reparacion_en_curso_sigue_bloqueado(cliente):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)
    iniciar(cliente, orden_id)

    conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/release", json={"usuario_id": TECNICO}
        )
    )


def test_no_en_una_orden_entregada(cliente, tmp_path):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)
    ejecutar(cliente, orden_id)
    ok(aprobar(cliente, orden_id, "DET-001"))
    notificar_pagar_entregar(cliente, orden_id)
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    assert not [c for c, _ in complementarias(orden)]
    antes = archivo(tmp_path, orden_id)

    respuesta = _liberar(cliente, orden_id)

    assert respuesta.status_code == 409, respuesta.text
    assert archivo(tmp_path, orden_id) == antes


def test_dos_liberaciones_simultaneas_solo_una_ocurre(cliente, tmp_path):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)
    iniciar(cliente, orden_id)
    contexto = construir_contexto(Settings(data_dir=tmp_path))
    resultados: list[str] = []

    def liberar(usuario):
        try:
            liberar_orden(
                contexto,
                orden_id=orden_id,
                usuario_id=usuario,
                motivo=MOTIVO,
                confirmado=True,
            )
            resultados.append("ok")
        except Exception as error:
            resultados.append(type(error).__name__)

    hilos = [
        threading.Thread(target=liberar, args=(usuario,))
        for usuario in (TECNICO_B, COORDINADOR, TECNICO_B)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert resultados.count("ok") == 1, resultados
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    assert ids(orden).count("PROC-REP-213") == 1
    assert [e["estado"] for e in orden["ejecuciones"]] == ["INTERRUMPIDO"]
    assert _reservas(cliente) == []


# --- Con una reparacion en curso: aviso, trazabilidad e inventario ----------


def _movimientos(cliente, orden_id) -> list[tuple[str, str]]:
    detalle = ok(cliente.get(f"/api/inventory/{INSUMO_BATERIA}"))
    return [
        (m["tipo"], m["cantidad"])
        for m in detalle["movimientos"]
        if m["orden_id"] == orden_id
    ]


def test_el_aviso_dice_que_pasa_con_la_reparacion_y_los_insumos(cliente):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)
    iniciar(cliente, orden_id)

    mensaje = conflicto(
        _liberar(cliente, orden_id, confirmado=False), "CONFIRMACION_REQUERIDA"
    )

    assert TECNICO in mensaje
    assert "interrumpe la reparacion en curso" in mensaje
    assert "utilizados se consumen" in mensaje
    assert "reservados sin usar se liberan" in mensaje


def test_conserva_la_traza_de_los_dos_tecnicos(cliente):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)
    ejecucion_id = iniciar(cliente, orden_id)

    orden = ok(_liberar(cliente, orden_id))

    (ejecucion,) = orden["ejecuciones"]
    # La Ejecucion es del titular; la interrupcion, de quien libero.
    assert ejecucion["usuario_id"] == TECNICO
    assert ejecucion["fin"] is not None
    assert TECNICO_B in ejecucion["motivo_interrupcion"]
    (toma,) = orden["tomas"]
    assert (toma["usuario_id"], toma["liberada_por"]) == (TECNICO, TECNICO_B)
    pasos = [
        (p["referencia_id"], p["usuario_id"], p["ejecucion_id"])
        for p in orden["historial"]
    ]
    assert ("PROC-REP-200", TECNICO_B, ejecucion_id) in pasos
    assert ("PROC-REP-213", TECNICO_B, None) in pasos
    assert [p for p, _, _ in pasos][-2:] == ["PROC-REP-213", "PROC-REP-170"]


@pytest.mark.parametrize(
    ("usado", "esperado"),
    [
        ("", [("RESERVA", "1"), ("LIBERACION_RESERVA", "1")]),
        ("1", [("RESERVA", "1"), ("CONSUMO", "1")]),
    ],
)
def test_reservas_y_consumos(cliente, tmp_path, usado, esperado):
    orden_id = ingresada(cliente)
    tomar(cliente, orden_id, TECNICO)
    iniciar(cliente, orden_id)
    stock_antes = stock(tmp_path)
    utilizados = (
        [{"insumo_id": INSUMO_BATERIA, "cantidad": usado}] if usado else []
    )

    ok(_liberar(cliente, orden_id, insumos_utilizados=utilizados))

    assert _movimientos(cliente, orden_id) == esperado
    assert _reservas(cliente) == []
    consumido = Decimal(usado or "0")
    assert stock(tmp_path) == stock_antes - consumido
