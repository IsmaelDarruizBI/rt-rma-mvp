"""E2, QA-E2-1: una respuesta no mezcla versiones de una misma Orden.

Las bandejas y el detalle de un insumo leen el repository mas de una vez.
Cada prueba lanza una escritura en OTRO hilo justo despues de la primera
lectura: completar la ejecucion en curso, que consume la reserva. Esa
escritura tiene que esperar a que terminen las lecturas de la respuesta
(con JSON, el lock de la unidad de trabajo), y la respuesta tiene que
ser coherente: la Orden en una sola version, ninguna reserva vigente
junto al consumo que la cierra.
"""

import threading
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.application import construir_contexto, detalle_de_insumo
from app.application.bandejas import _Lectura
from app.core.config import Settings
from app.domain.models import TipoMovimientoInsumo
from app.main import create_app
from tests.fixtures.api_salidas import (
    COORDINADOR,
    INSUMO_BATERIA,
    TECNICO,
    definida,
    iniciar,
    sembrar,
    tomada,
)

# Lo que se le da a la escritura para colarse entre las lecturas.
ESPERA_S = 0.5


@pytest.fixture
def con_ejecucion_en_curso(tmp_path):
    """Una Orden con la ejecucion iniciada y su reserva vigente."""
    sembrar(tmp_path, "5")
    settings = Settings(data_dir=tmp_path)
    app = create_app(settings)
    with TestClient(app) as cliente:
        orden_id = definida(cliente)
        tomada(cliente, orden_id)
        ejecucion_id = iniciar(cliente, orden_id)
    return app, settings, orden_id, ejecucion_id


class _EscrituraEnElMedio:
    """Repository que, al responder ``metodo`` la primera vez, lanza la
    escritura en otro hilo y le da ``ESPERA_S`` para terminar."""

    def __init__(self, repo, metodo, escribir):
        self._repo = repo
        self._metodo = metodo
        self._escribir = escribir
        self.hilo: threading.Thread | None = None

    def __getattr__(self, nombre):
        original = getattr(self._repo, nombre)
        if nombre != self._metodo:
            return original

        def envuelto(*args, **kwargs):
            resultado = original(*args, **kwargs)
            if self.hilo is None:
                self.hilo = threading.Thread(target=self._escribir)
                self.hilo.start()
                self.hilo.join(ESPERA_S)
            return resultado

        return envuelto


def _completar(app, orden_id, ejecucion_id, respuestas):
    def escribir():
        with TestClient(app) as cliente:
            respuestas.append(
                cliente.post(
                    f"/api/orders/{orden_id}/executions/{ejecucion_id}/"
                    "complete",
                    json={
                        "usuario_id": TECNICO,
                        "insumos_utilizados": [
                            {"insumo_id": INSUMO_BATERIA, "cantidad": "1"}
                        ],
                    },
                )
            )

    return escribir


def _esperar_escritura(repo, respuestas):
    """La escritura termino (despues de la respuesta) y salio bien."""
    repo.hilo.join(10)
    assert not repo.hilo.is_alive()
    assert [r.status_code for r in respuestas] == [200]


def test_el_detalle_de_un_insumo_no_mezcla_reservas_y_movimientos(
    con_ejecucion_en_curso,
):
    app, settings, orden_id, ejecucion_id = con_ejecucion_en_curso
    contexto = construir_contexto(settings)
    respuestas = []
    repo = _EscrituraEnElMedio(
        contexto.ordenes,
        "listar_con_reservas",
        _completar(app, orden_id, ejecucion_id, respuestas),
    )

    detalle = detalle_de_insumo(
        replace(contexto, ordenes=repo), INSUMO_BATERIA
    )
    _esperar_escritura(repo, respuestas)

    vigentes = {r.movimiento_id for r in detalle.situacion.reservas}
    cerradas = {
        movimiento.movimiento_origen_id
        for movimiento in detalle.movimientos
        if movimiento.tipo is TipoMovimientoInsumo.CONSUMO
    }
    assert vigentes  # la respuesta es de antes del consumo
    assert vigentes.isdisjoint(cerradas)
    # Y leida de nuevo, ya ve el consumo.
    despues = detalle_de_insumo(contexto, INSUMO_BATERIA)
    assert not despues.situacion.reservas


def test_una_bandeja_ve_cada_orden_en_una_sola_version(
    con_ejecucion_en_curso,
):
    app, settings, orden_id, ejecucion_id = con_ejecucion_en_curso
    contexto = construir_contexto(settings)
    respuestas = []
    repo = _EscrituraEnElMedio(
        contexto.ordenes,
        "listar_abiertas",
        _completar(app, orden_id, ejecucion_id, respuestas),
    )

    lectura = _Lectura(
        replace(contexto, ordenes=repo),
        contexto.catalogos.obtener_usuario(COORDINADOR),
    )
    _esperar_escritura(repo, respuestas)

    (en_filas,) = [o for o in lectura.ordenes if o.id == orden_id]
    (en_reservas,) = [o for o in lectura.con_reservas if o.id == orden_id]
    assert en_filas == en_reservas
