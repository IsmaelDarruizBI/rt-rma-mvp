"""Trabajo "Otros — Reparacion no tipificada" (iteracion 1 del UAT).

Un tipo reservado del sistema (``TR-OTROS``), no una fila del catalogo:
cada trabajo lleva su descripcion y su precio manual. Recorre el ciclo de
vida de cualquier Detalle, no inventa insumos y se distingue en las
lecturas y los documentos ("Otros: <descripcion>").
"""

import pytest

from tests.fixtures.api_salidas import (
    BATERIA,
    RECEPCION,
    TECNICO,
    agregar,
    aprobar,
    archivo,
    cerrar_ejecucion,
    cliente_http,
    conflicto,
    detalle,
    iniciar,
    notificar_pagar_entregar,
    ok,
    stock,
    tomar,
)
from tests.fixtures.ingreso_inicial import (
    agregar_otros,
    crear_con_recepcion,
    del_tipo,
    generar_ingreso,
)

DESCRIPCION = "Limpieza de puerto de carga"


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def test_otros_con_descripcion_y_precio_manual(cliente):
    orden_id = crear_con_recepcion(cliente)

    orden = ok(agregar_otros(cliente, orden_id, DESCRIPCION, "15000"))

    otros = detalle(orden, "DET-001")
    assert otros["tipo_reparacion_id"] == "TR-OTROS"
    assert otros["descripcion"] == DESCRIPCION
    assert otros["tipo_reparacion_nombre"] == f"Otros: {DESCRIPCION}"
    assert otros["precio"] == "15000"
    assert otros["puntaje"] == 0
    # No inventa insumos.
    assert otros["insumos_previstos"] == []
    assert orden["resumen"]["total"] == "15000"


def test_conviven_con_los_tipos_del_catalogo(cliente):
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id, BATERIA)
    ok(agregar_otros(cliente, orden_id, "Cambio de tornillos", "3000"))
    orden = ok(agregar_otros(cliente, orden_id, DESCRIPCION, "15000"))

    assert [
        d["tipo_reparacion_nombre"] for d in orden["reparaciones_detail"]
    ] == [
        "Cambio de bateria",
        "Otros: Cambio de tornillos",
        f"Otros: {DESCRIPCION}",
    ]
    assert orden["resumen"]["total"] == "98000"
    # El catalogo no cambia: "Otros" no es una fila.
    tipos = ok(cliente.get("/api/catalogs/repair-types"))
    assert "TR-OTROS" not in [tipo["id"] for tipo in tipos]


@pytest.mark.parametrize(
    ("cuerpo", "texto"),
    [
        ({"tipo_reparacion_id": "TR-OTROS", "descripcion": "x"}, "precio"),
        (
            {"tipo_reparacion_id": "TR-OTROS", "precio": "1000"},
            "descripcion",
        ),
        ({"tipo_reparacion_id": BATERIA, "precio": "1000"}, "catalogo"),
        ({"tipo_reparacion_id": BATERIA, "descripcion": "x"}, "Otros"),
    ],
)
def test_reglas_de_descripcion_y_precio(cliente, tmp_path, cuerpo, texto):
    orden_id = crear_con_recepcion(cliente)
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/details",
            json={"usuario_id": RECEPCION, **cuerpo},
        )
    )

    assert texto.lower() in mensaje.lower()
    assert archivo(tmp_path, orden_id) == antes


def test_precio_negativo_o_con_mas_de_dos_decimales(cliente):
    orden_id = crear_con_recepcion(cliente)

    for precio in ("-1", "10.555"):
        respuesta = agregar_otros(cliente, orden_id, DESCRIPCION, precio)
        assert respuesta.status_code == 422, respuesta.text


def test_ciclo_de_vida_completo_sin_insumos(cliente, tmp_path):
    orden_id = crear_con_recepcion(cliente)
    ok(agregar_otros(cliente, orden_id, DESCRIPCION, "15000"))
    ingreso = ok(generar_ingreso(cliente, orden_id))
    assert ingreso["estado_workflow"] == "EN_COLA"
    stock_antes = stock(tmp_path)

    tomar(cliente, orden_id, TECNICO)
    ejecucion_id = iniciar(cliente, orden_id)
    ok(
        cerrar_ejecucion(
            cliente, orden_id, ejecucion_id, tecnico=TECNICO, cantidad=None
        )
    )
    ok(aprobar(cliente, orden_id, "DET-001"))
    entregada = notificar_pagar_entregar(cliente, orden_id)

    assert entregada["estado_workflow"] == "ENTREGADA"
    assert stock(tmp_path) == stock_antes
    # Se distingue en los documentos.
    (comprobante,) = del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")
    assert comprobante["contenido"]["trabajos"][0]["nombre"] == (
        f"Otros: {DESCRIPCION}"
    )
    (garantia,) = del_tipo(cliente, orden_id, "GARANTIA")
    (cobertura,) = garantia["contenido"]["coberturas"]
    assert cobertura["tipo_reparacion_id"] == "TR-OTROS"
    assert cobertura["nombre"] == f"Otros: {DESCRIPCION}"


def test_se_distingue_en_las_bandejas(cliente):
    orden_id = crear_con_recepcion(cliente)
    ok(agregar_otros(cliente, orden_id, DESCRIPCION, "15000"))
    ok(generar_ingreso(cliente, orden_id))

    bandejas = ok(
        cliente.get("/api/work/workshop", params={"usuario_id": TECNICO})
    )

    (item,) = [
        item
        for bandeja in bandejas["bandejas"]
        for item in bandeja["ordenes"]
        if item["orden"]["id"] == orden_id
    ][:1]
    assert item["trabajos"][0]["nombre"] == f"Otros: {DESCRIPCION}"
