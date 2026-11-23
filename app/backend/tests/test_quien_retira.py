"""DEC-AJ-09, parte P-05 (BF-19): quien retira el equipo.

El formulario de entrega pregunta «¿Retira otra persona?»:

- No: retira el titular y no se pide ningun otro dato.
- Si: nombre, apellido y telefono obligatorios.

No se piden el vinculo, el DNI ni otra identificacion, ni una autorizacion
formal. Que retire otra persona no modifica ni anula la garantia. Quien
retiro queda en la Orden y en el comprobante.
"""

import pytest

from tests.fixtures import api_salidas as f
from tests.fixtures import iteracion1 as it
from tests.fixtures.custodia import checkin_si_falta

TERCERO = {
    "retira_otra_persona": True,
    "retira_nombre": " Ana ",
    "retira_apellido": "Lopez",
    "retira_telefono": "341-555-0199",
}


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _lista_y_pagada(cliente) -> str:
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    it.pagar(cliente, orden_id, "80000")
    checkin_si_falta(cliente, orden_id)
    return orden_id


def _entregar(cliente, orden_id, **cuerpo):
    return cliente.post(
        f"/api/orders/{orden_id}/deliver",
        json={"usuario_id": f.RECEPCION, **cuerpo},
    )


def _comprobante(cliente, orden_id) -> dict:
    (documento,) = [
        d
        for d in f.ok(cliente.get(f"/api/orders/{orden_id}/documents"))[
            "emitidos"
        ]
        if d["tipo"] == "COMPROBANTE_ENTREGA"
    ]
    return documento["contenido"]


def test_retira_el_titular_sin_otro_dato(cliente):
    orden_id = _lista_y_pagada(cliente)
    titular = f.ok(cliente.get(f"/api/orders/{orden_id}"))["cliente"][
        "nombre_apellido"
    ]

    orden = f.ok(_entregar(cliente, orden_id))

    entrega = orden["entrega"]
    assert entrega["recibido_por"] == titular
    assert entrega["retira_otra_persona"] is False
    assert entrega["telefono_receptor"] is None
    assert entrega["identificacion_receptor"] is None
    assert orden["historial"][-1]["observacion"] == (
        f"Retira el titular: {titular}"
    )
    comprobante = _comprobante(cliente, orden_id)
    assert comprobante["recibido_por"] == titular
    assert comprobante["retira_otra_persona"] is False


@pytest.mark.parametrize(
    ("faltan", "mensaje"),
    [
        (("retira_nombre",), "indica el nombre de quien retira"),
        (("retira_apellido",), "indica el apellido de quien retira"),
        (("retira_telefono",), "indica el telefono de quien retira"),
        (
            ("retira_nombre", "retira_telefono"),
            "indica el nombre y el telefono de quien retira",
        ),
    ],
)
def test_otra_persona_exige_nombre_apellido_y_telefono(
    cliente, tmp_path, faltan, mensaje
):
    orden_id = _lista_y_pagada(cliente)
    antes = f.archivo(tmp_path, orden_id)
    cuerpo = {**TERCERO, **{campo: "  " for campo in faltan}}

    assert mensaje in f.conflicto(_entregar(cliente, orden_id, **cuerpo))

    assert f.archivo(tmp_path, orden_id) == antes


def test_retira_otra_persona_sin_vinculo_ni_dni(cliente):
    orden_id = _lista_y_pagada(cliente)

    # Una identificacion que llegue igual no se pide ni se guarda.
    orden = f.ok(
        _entregar(
            cliente,
            orden_id,
            **TERCERO,
            identificacion_receptor="DNI 1",
            recibido_por="Otro nombre",
        )
    )

    entrega = orden["entrega"]
    assert entrega["recibido_por"] == "Ana Lopez"
    assert entrega["retira_otra_persona"] is True
    assert entrega["telefono_receptor"] == "341-555-0199"
    assert entrega["identificacion_receptor"] is None
    assert orden["historial"][-1]["observacion"] == (
        "Retira otra persona: Ana Lopez, tel. 341-555-0199"
    )
    comprobante = _comprobante(cliente, orden_id)
    assert (
        comprobante["recibido_por"],
        comprobante["retira_otra_persona"],
        comprobante["telefono_receptor"],
    ) == ("Ana Lopez", True, "341-555-0199")
    custodia = f.ok(cliente.get(f"/api/orders/{orden_id}/custody"))
    assert custodia["custodia"]["salida"]["retira_otra_persona"] is True


def test_que_retire_otra_persona_no_cambia_la_garantia(cliente):
    titular_id = _lista_y_pagada(cliente)
    tercero_id = _lista_y_pagada(cliente)

    f.ok(_entregar(cliente, titular_id))
    f.ok(_entregar(cliente, tercero_id, **TERCERO))

    def garantias(orden_id):
        return [
            (t["garantia_dias"], t["garantia_vence"])
            for t in _comprobante(cliente, orden_id)["trabajos_realizados"]
        ]

    assert garantias(tercero_id) == garantias(titular_id)
    assert garantias(tercero_id)[0][0] == 90
    # La garantia del trabajo sigue vigente para un reclamo RMA.
    rma = f.ok(it.iniciar_garantia(cliente, tercero_id))
    assert rma["orden_origen_id"] == tercero_id
