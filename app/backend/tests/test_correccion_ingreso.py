"""Correccion de los datos del ingreso (DEC-MI-07, cierra ABI-25).

Completar un dato vacio es registrarlo; cambiar uno ya registrado es una
correccion: la hacen Recepcion, Coordinacion RMA o Administracion, con
motivo, y cada dato queda con su valor anterior y el nuevo. Hasta cuando se
corrige no cambia (antes de confirmar la recepcion; ABI-41).
"""

import pytest

from tests.fixtures import api_salidas as f


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path) as test_client:
        yield test_client


def _ingreso(cliente, orden_id, usuario=f.RECEPCION, motivo=None, **datos):
    return cliente.put(
        f"/api/orders/{orden_id}/reception",
        json={"usuario_id": usuario, "motivo": motivo, **datos},
    )


def test_registrar_no_pide_motivo_y_corregir_si(cliente):
    orden_id = f.crear(cliente)
    f.ok(_ingreso(cliente, orden_id, estado_fisico="Sin golpes."))

    assert "exige un motivo" in f.conflicto(
        _ingreso(cliente, orden_id, estado_fisico="Pantalla rota.")
    )
    f.conflicto(
        _ingreso(
            cliente,
            orden_id,
            usuario=f.TECNICO,
            motivo="Error de carga.",
            estado_fisico="Pantalla rota.",
        )
    )

    orden = f.ok(
        _ingreso(
            cliente,
            orden_id,
            usuario=f.COORDINADOR,
            motivo="Error de carga.",
            estado_fisico="Pantalla rota.",
            accesorios=["Cargador"],
        )
    )
    version = orden["recepcion"]["versiones_anteriores"][-1]
    assert version["motivo"] == "Error de carga."
    assert version["cambios"] == [
        {
            "campo": "estado_fisico",
            "anterior": "Sin golpes.",
            "nuevo": "Pantalla rota.",
        },
        {"campo": "accesorios", "anterior": None, "nuevo": "Cargador"},
    ]
    paso = orden["historial"][-1]
    assert paso["usuario_id"] == f.COORDINADOR
    assert paso["rol"] == "COORDINADOR_RMA"
    assert "Motivo: Error de carga." in paso["observacion"]
    assert orden["recepcion"]["datos"]["estado_fisico"] == "Pantalla rota."
