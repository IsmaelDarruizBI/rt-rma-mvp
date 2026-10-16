"""Interrumpir la reparacion exige un motivo (VAR-REP-003).

Vacio, solo espacios o ausente se rechaza antes de tocar nada: la Orden,
su historial, la reserva y el inventario quedan como estaban. Con motivo,
la interrupcion funciona igual que siempre y el motivo queda en la
Ejecucion, aparte de las observaciones.
"""

from pathlib import Path

import pytest

from app.domain.models import EstadoEjecucion, EstadoReparacionDetail
from app.services import (
    PrecondicionInvalidaError,
    registrar_ejecucion_interrumpida,
)
from tests.fixtures.api_salidas import (
    TECNICO,
    archivo,
    conflicto,
    definida,
    iniciar,
    ok,
    repo_ordenes,
    stock,
    tomada,
)
from tests.test_inventario_operativo import _cliente
from tests.test_var_rep_003 import TECNICO as TECNICO_SERVICIO
from tests.test_var_rep_003 import _iniciada, flujo_mvp, t


def _interrumpir(cliente, orden_id, ejecucion_id, **cuerpo):
    return cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/interrupt",
        json={"usuario_id": TECNICO, "insumos_utilizados": [], **cuerpo},
    )


def _en_reparacion(cliente) -> tuple[str, str]:
    orden_id = definida(cliente)
    tomada(cliente, orden_id)
    return orden_id, iniciar(cliente, orden_id)


def _estado(directorio: Path, orden_id: str) -> dict:
    """Todo lo que una interrupcion podria tocar."""
    catalogos = directorio / "catalogs"
    return {
        "orden": archivo(directorio, orden_id),
        "catalogos": {
            ruta.name: ruta.read_bytes()
            for ruta in sorted(catalogos.glob("*.json"))
        },
    }


# --- Servicio ----------------------------------------------------------------


@pytest.mark.parametrize("motivo", ["", "   ", "\n\t "])
def test_servicio_rechaza_un_motivo_vacio_sin_cambiar_la_orden(motivo):
    orden = _iniciada(flujo_mvp.orden_tomada())
    antes = orden.model_dump()

    with pytest.raises(PrecondicionInvalidaError, match="exige un motivo"):
        registrar_ejecucion_interrumpida(
            orden,
            ejecucion_id=orden.ejecuciones[0].id,
            insumos_utilizados=[],
            usuario=TECNICO_SERVICIO,
            fecha=t(100),
            motivo=motivo,
        )

    assert orden.model_dump() == antes
    assert orden.ejecuciones[0].estado is EstadoEjecucion.EN_PROGRESO


def test_servicio_guarda_el_motivo_aparte_de_las_observaciones():
    orden = _iniciada(flujo_mvp.orden_tomada())

    orden = registrar_ejecucion_interrumpida(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        insumos_utilizados=[],
        usuario=TECNICO_SERVICIO,
        fecha=t(100),
        motivo="  Falta un repuesto menor.  ",
        observaciones="Sigue mañana.",
    )

    (ejecucion,) = orden.ejecuciones
    assert ejecucion.estado is EstadoEjecucion.INTERRUMPIDO
    assert ejecucion.motivo_interrupcion == "Falta un repuesto menor."
    assert ejecucion.observaciones == "Sigue mañana."
    assert ejecucion.motivo_redefinicion is None
    assert orden.reparaciones_detail[0].estado is (
        EstadoReparacionDetail.DEFINIDO
    )
    assert orden.historial[-1].observacion == "Interrumpido"


# --- API ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cuerpo", "status", "codigo"),
    [
        ({}, 422, "REQUEST_INVALIDO"),
        ({"motivo": ""}, 422, "REQUEST_INVALIDO"),
        ({"motivo": "   "}, 409, "PRECONDICION_INVALIDA"),
        ({"motivo": " \t\n"}, 409, "PRECONDICION_INVALIDA"),
        ({"motivo": None}, 422, "REQUEST_INVALIDO"),
    ],
)
def test_api_rechaza_sin_motivo_y_sin_efectos(
    tmp_path, cuerpo, status, codigo
):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id, ejecucion_id = _en_reparacion(cliente)
        antes = _estado(tmp_path, orden_id)

        respuesta = _interrumpir(
            cliente, orden_id, ejecucion_id, observaciones="Algo", **cuerpo
        )

        assert respuesta.status_code == status, respuesta.text
        assert respuesta.json()["error"]["codigo"] == codigo
        # Ni la Orden (historial, ejecucion, reserva) ni el inventario.
        assert _estado(tmp_path, orden_id) == antes
        orden = ok(cliente.get(f"/api/orders/{orden_id}"))
        assert [e["estado"] for e in orden["ejecuciones"]] == ["EN_PROGRESO"]
        assert any(
            a["codigo"] == "INTERRUMPIR_EJECUCION"
            for a in orden["acciones_disponibles"]
        )


def test_api_motivo_solo_espacios_explica_que_falta(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id, ejecucion_id = _en_reparacion(cliente)

        mensaje = conflicto(
            _interrumpir(cliente, orden_id, ejecucion_id, motivo="   ")
        )

        assert "exige un motivo" in mensaje


def test_api_con_motivo_interrumpe_igual_que_siempre(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id, ejecucion_id = _en_reparacion(cliente)
        stock_antes = stock(tmp_path)
        historial_antes = len(
            ok(cliente.get(f"/api/orders/{orden_id}"))["historial"]
        )

        orden = ok(
            _interrumpir(
                cliente,
                orden_id,
                ejecucion_id,
                motivo=" Falta pegamento. ",
                observaciones="Se retoma mañana.",
            )
        )

        (ejecucion,) = orden["ejecuciones"]
        assert ejecucion["estado"] == "INTERRUMPIDO"
        assert ejecucion["motivo_interrupcion"] == "Falta pegamento."
        assert ejecucion["observaciones"] == "Se retoma mañana."
        assert orden["reparaciones_detail"][0]["estado"] == "DEFINIDO"
        assert [t["estado"] for t in orden["tomas"]] == ["ACTIVA"]
        # PROC-REP-190 -> 200 (Interrumpido) -> 210 -> 211, como antes.
        nuevos = [p["referencia_id"] for p in orden["historial"]][
            historial_antes:
        ]
        assert nuevos[:4] == [
            "PROC-REP-190",
            "PROC-REP-200",
            "PROC-REP-210",
            "PROC-REP-211",
        ]
        assert orden["historial"][historial_antes + 1]["observacion"] == (
            "Interrumpido"
        )
        # Nada usado: la reserva se libera y el stock fisico no cambia.
        movimientos = (
            repo_ordenes(tmp_path).obtener(orden_id).movimientos_insumo
        )
        assert [m.tipo.value for m in movimientos] == [
            "RESERVA",
            "LIBERACION_RESERVA",
        ]
        assert stock(tmp_path) == stock_antes
        # Se puede retomar con una Ejecucion nueva.
        nueva = iniciar(cliente, orden_id)
        assert nueva != ejecucion_id
