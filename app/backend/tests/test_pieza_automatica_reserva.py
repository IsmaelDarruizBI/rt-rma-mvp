"""La eleccion automatica de la pieza nunca inicia una Ejecucion sin la
reserva de esa pieza concreta (DEC-AJ-14, D-14.4).

Cubre la eleccion automatica en sus dos momentos:
- al definir el trabajo (una sola pieza compatible);
- al iniciar (la pieza quedo como unica compatible despues de definir).

En los dos casos, iniciar reserva la pieza elegida con el mismo motor, todo
o nada: sin disponible no hay Ejecucion ni reserva (EXC-REP-003). La unica
excepcion es el override de factibilidad vigente (EXC-REP-002, P-06), que ya
existia y queda anotado en el paso 185; se prueba en
``test_requisitos_pieza.py``.
"""

import json
from decimal import Decimal

from app.storage.json.base import escribir_json_atomico
from tests.fixtures import api_salidas as f
from tests.test_requisitos_pieza import (
    ADHESIVO,
    BATERIA_A,
    BATERIA_B,
    FLEX,
    REQ_BATERIA,
    REQ_FLEX,
    TIPO_FLEX,
    _cliente,
    _en_cola,
    _iniciar,
    _movimientos,
    _requisitos,
    _sembrar,
)


def _dar_de_baja(directorio, insumo_id) -> None:
    archivo = directorio / "catalogs" / "insumos.json"
    filas = json.loads(archivo.read_text(encoding="utf-8"))
    for fila in filas:
        if fila["id"] == insumo_id:
            fila["activo"] = False
    escribir_json_atomico(archivo, filas)


def _reservas(directorio, orden_id) -> list[tuple[str, str]]:
    return sorted(
        (m.insumo_id, str(m.cantidad))
        for m in _movimientos(directorio, orden_id)
        if m.tipo.value == "RESERVA"
    )


def test_la_elegida_al_definir_se_reserva_al_iniciar(tmp_path):
    _sembrar(tmp_path)
    with _cliente(tmp_path) as cliente:
        orden_id = _en_cola(cliente, tipo=TIPO_FLEX)
        orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
        assert _requisitos(orden)[REQ_FLEX]["causa"] == "AUTOMATICA"
        f.tomada(cliente, orden_id)

        orden = f.ok(_iniciar(cliente, orden_id))

    assert [e["estado"] for e in orden["ejecuciones"]] == ["EN_PROGRESO"]
    assert _reservas(tmp_path, orden_id) == [(ADHESIVO, "2"), (FLEX, "1")]


def test_la_elegida_al_iniciar_se_reserva_en_la_misma_operacion(tmp_path):
    _sembrar(tmp_path)
    with _cliente(tmp_path) as cliente:
        orden_id = _en_cola(cliente)  # dos baterias: queda pendiente
        orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
        assert _requisitos(orden)[REQ_BATERIA]["estado"] != "ELEGIDA"
    # Despues de definir, una de las dos deja de estar vigente.
    _dar_de_baja(tmp_path, BATERIA_B)
    with _cliente(tmp_path) as cliente:
        f.tomada(cliente, orden_id)

        orden = f.ok(_iniciar(cliente, orden_id))

    requisito = _requisitos(orden)[REQ_BATERIA]
    assert (requisito["estado"], requisito["causa"]) == (
        "ELEGIDA",
        "AUTOMATICA",
    )
    assert requisito["insumo_id"] == BATERIA_A
    assert [e["estado"] for e in orden["ejecuciones"]] == ["EN_PROGRESO"]
    assert _reservas(tmp_path, orden_id) == [(BATERIA_A, "1"), (ADHESIVO, "1")]


def test_la_elegida_al_iniciar_sin_disponible_no_inicia_ni_reserva(tmp_path):
    _sembrar(tmp_path, bateria_a="0")
    with _cliente(tmp_path) as cliente:
        orden_id = _en_cola(cliente)  # factible: hay de la otra bateria
    _dar_de_baja(tmp_path, BATERIA_B)
    with _cliente(tmp_path) as cliente:
        f.tomada(cliente, orden_id)

        orden = f.ok(_iniciar(cliente, orden_id))

    assert orden["ejecuciones"] == []
    assert f.detalle(orden, "DET-001")["condicion"] == "BLOQUEADO_POR_RECURSOS"
    assert _reservas(tmp_path, orden_id) == []


def test_sin_pieza_elegible_no_inicia_ni_reserva(tmp_path):
    _sembrar(tmp_path)
    with _cliente(tmp_path) as cliente:
        orden_id = _en_cola(cliente)
    _dar_de_baja(tmp_path, BATERIA_A)
    _dar_de_baja(tmp_path, BATERIA_B)
    with _cliente(tmp_path) as cliente:
        f.tomada(cliente, orden_id)

        respuesta = _iniciar(cliente, orden_id)

        f.conflicto(respuesta, "PIEZA_SIN_ELEGIR")
        orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert orden["ejecuciones"] == []
    assert _reservas(tmp_path, orden_id) == []
    assert Decimal(0) == sum(
        (m.cantidad for m in _movimientos(tmp_path, orden_id)), Decimal(0)
    )
