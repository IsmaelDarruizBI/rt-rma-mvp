"""Prioridad de la Orden: 1 Urgente, 2 Alta, 3 Media, 4 Normal.

Cuanto menor el numero, mayor la prioridad (``app.domain.prioridad``). La
predeterminada (4) se propone al priorizar y se registra solo al
confirmar; PROC-REP-150 ocurre una sola vez y no repite PROC-REP-140. Los
valores historicos fuera de 1-4 se conservan sin migrarlos.
"""

import json
from datetime import timedelta
from itertools import permutations

import pytest

from app.domain.models import EstadoWorkflow
from app.domain.prioridad import (
    FUERA_DE_ESCALA,
    PRIORIDAD_PREDETERMINADA,
    clave_de_prioridad,
    nombre_de_prioridad,
    prioridad_vigente,
    texto_de_prioridad,
)
from app.services import (
    PrecondicionInvalidaError,
    definir_prioridad,
    fue_priorizada,
)
from tests.fixtures import flujo_mvp
from tests.fixtures.api_salidas import (
    COORDINADOR,
    RECEPCION,
    aprobar,
    archivo,
    cerrar_ejecucion,
    conflicto,
    definida,
    ids,
    iniciar,
    ok,
    tomada,
    tomar,
)
from tests.fixtures.catalogos_mvp import COORDINADOR as COORDINADOR_DOMINIO
from tests.fixtures.catalogos_mvp import t
from tests.fixtures.custodia import entregar
from tests.test_inventario_operativo import _cliente

# --- Convencion -----------------------------------------------------------


def test_la_convencion_de_prioridades():
    assert [nombre_de_prioridad(valor) for valor in (1, 2, 3, 4)] == [
        "Urgente",
        "Alta",
        "Media",
        "Normal",
    ]
    assert PRIORIDAD_PREDETERMINADA == 4
    assert texto_de_prioridad(1) == "Prioridad 1 · Urgente"
    # 0 es "todavia sin prioridad", no una prioridad.
    assert nombre_de_prioridad(0) is None and texto_de_prioridad(0) is None
    # Un valor historico fuera de 1-4 se nombra, sin reinterpretarlo.
    assert texto_de_prioridad(9) == f"Prioridad 9 · {FUERA_DE_ESCALA}"


def _en_cola(numero: int, prioridad: int, minutos: int = 0, **cambios):
    """Una Orden en cola con esa prioridad, ingresada ``minutos`` despues."""
    base = flujo_mvp.orden_en_cola()
    return base.model_copy(
        update={
            "id": f"OR-{numero:06d}",
            "prioridad": prioridad,
            "created_at": base.created_at + timedelta(minutes=minutos),
            **cambios,
        }
    )


def _orden_por_prioridad(ordenes) -> list[str]:
    return [orden.id for orden in sorted(ordenes, key=clave_de_prioridad)]


def test_primero_1_despues_2_3_y_4():
    ordenes = [_en_cola(n, p, n) for n, p in enumerate((4, 2, 1, 3), 1)]

    assert _orden_por_prioridad(ordenes) == [
        "OR-000003",  # 1 Urgente
        "OR-000002",  # 2 Alta
        "OR-000004",  # 3 Media
        "OR-000001",  # 4 Normal
    ]


def test_sin_prioridad_cerradas_y_canceladas_van_al_final():
    normal = _en_cola(1, 4, 50)
    historica = _en_cola(2, 9, 60)
    sin_prioridad = _en_cola(3, 0, 10)
    entregada = _en_cola(4, 1, 0, estado_workflow=EstadoWorkflow.ENTREGADA)
    cancelada = _en_cola(5, 1, 20, estado_workflow=EstadoWorkflow.CANCELADA)

    assert [
        prioridad_vigente(orden)
        for orden in (normal, historica, sin_prioridad, entregada, cancelada)
    ] == [4, 9, None, None, None]
    # El valor historico va despues de 4; sin prioridad vigente, al final
    # y por fecha de ingreso.
    assert _orden_por_prioridad(
        [cancelada, sin_prioridad, entregada, historica, normal]
    ) == ["OR-000001", "OR-000002", "OR-000004", "OR-000003", "OR-000005"]


def test_con_la_misma_prioridad_el_orden_es_estable():
    primera = _en_cola(7, 2, 0)
    misma_hora_menor_numero = _en_cola(8, 2, 5)
    misma_hora_mayor_numero = _en_cola(9, 2, 5)
    ultima = _en_cola(6, 2, 30)
    esperado = ["OR-000007", "OR-000008", "OR-000009", "OR-000006"]

    for orden in permutations(
        [ultima, misma_hora_mayor_numero, primera, misma_hora_menor_numero]
    ):
        assert _orden_por_prioridad(orden) == esperado


def test_ordenar_no_modifica_las_ordenes():
    ordenes = [_en_cola(1, 3), _en_cola(2, 0), _en_cola(3, 9)]
    antes = [orden.model_dump() for orden in ordenes]

    _orden_por_prioridad(ordenes)

    assert [orden.model_dump() for orden in ordenes] == antes


# --- PROC-REP-150 (service) -----------------------------------------------


@pytest.mark.parametrize("prioridad", [1, 2, 3, 4])
def test_se_registra_la_prioridad_elegida(prioridad):
    orden = flujo_mvp.orden_habilitada()
    assert not fue_priorizada(orden)

    priorizada = definir_prioridad(
        orden, prioridad=prioridad, usuario=COORDINADOR_DOMINIO, fecha=t(25)
    )

    assert priorizada.prioridad == prioridad
    assert priorizada.historial[-1].observacion == str(prioridad)
    assert fue_priorizada(priorizada)


@pytest.mark.parametrize("prioridad", [-1, 0, 5, 10])
def test_fuera_de_1_a_4_no_se_asigna(prioridad):
    orden = flujo_mvp.orden_habilitada()

    with pytest.raises(PrecondicionInvalidaError, match="Valores admitidos"):
        definir_prioridad(
            orden,
            prioridad=prioridad,
            usuario=COORDINADOR_DOMINIO,
            fecha=t(25),
        )


def test_la_priorizacion_no_se_repite_aunque_vuelva_a_estar_habilitada():
    # Un dato inconsistente (habilitada con PROC-REP-150 ya registrado) no
    # habilita una segunda priorizacion.
    orden = flujo_mvp.orden_en_cola().model_copy(
        update={"estado_workflow": EstadoWorkflow.HABILITADA}
    )

    with pytest.raises(PrecondicionInvalidaError, match="no se repite"):
        definir_prioridad(
            orden, prioridad=2, usuario=COORDINADOR_DOMINIO, fecha=t(40)
        )


# --- API -------------------------------------------------------------------


def _encolar(cliente, orden_id, **cuerpo):
    return cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, **cuerpo},
    )


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _filas(cliente) -> dict[str, dict]:
    return {fila["id"]: fila for fila in ok(cliente.get("/api/orders"))}


def test_el_catalogo_propone_4_normal(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        catalogo = ok(cliente.get("/api/catalogs/priorities"))

    assert catalogo == [
        {"valor": 1, "nombre": "Urgente", "predeterminada": False},
        {"valor": 2, "nombre": "Alta", "predeterminada": False},
        {"valor": 3, "nombre": "Media", "predeterminada": False},
        {"valor": 4, "nombre": "Normal", "predeterminada": True},
    ]


def test_habilitada_todavia_no_tiene_prioridad(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente)

        orden = _orden(cliente, orden_id)
        fila = _filas(cliente)[orden_id]

    assert orden["estado_workflow"] == "HABILITADA"
    assert orden["prioridad"] == 0 and orden["prioridad_texto"] is None
    assert "PROC-REP-150" not in ids(orden)
    assert orden["situacion"]["codigo"] == "PENDIENTE_PRIORIDAD"
    assert fila["prioridad_texto"] is None


def test_confirmar_sin_elegir_registra_4(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente)

        orden = ok(_encolar(cliente, orden_id))

    assert orden["prioridad"] == 4
    assert orden["prioridad_texto"] == "Prioridad 4 · Normal"
    assert orden["situacion"]["titulo"] == "En cola (prioridad 4 · Normal)"
    paso = next(
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-150"
    )
    assert paso["observacion"] == "4"


@pytest.mark.parametrize(
    ("prioridad", "texto"),
    [
        (1, "Prioridad 1 · Urgente"),
        (2, "Prioridad 2 · Alta"),
        (3, "Prioridad 3 · Media"),
    ],
)
def test_se_puede_elegir_1_2_o_3(tmp_path, prioridad, texto):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente)

        orden = ok(_encolar(cliente, orden_id, prioridad=prioridad))
        fila = _filas(cliente)[orden_id]

    assert (orden["prioridad"], orden["estado_workflow"]) == (
        prioridad,
        "EN_COLA",
    )
    assert orden["prioridad_texto"] == fila["prioridad_texto"] == texto


@pytest.mark.parametrize("prioridad", [0, 5, -1])
def test_la_api_rechaza_valores_fuera_de_1_a_4(tmp_path, prioridad):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente)
        antes = archivo(tmp_path, orden_id)

        respuesta = _encolar(cliente, orden_id, prioridad=prioridad)

        assert respuesta.status_code == 422
        assert archivo(tmp_path, orden_id) == antes


def test_no_repite_140_ni_la_priorizacion(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente)
        ok(_encolar(cliente, orden_id, prioridad=2))
        antes = archivo(tmp_path, orden_id)

        conflicto(_encolar(cliente, orden_id, prioridad=1))

        assert archivo(tmp_path, orden_id) == antes
        orden = _orden(cliente, orden_id)
        assert ids(orden).count("PROC-REP-140") == 1
        assert ids(orden).count("PROC-REP-150") == 1
        assert orden["prioridad"] == 2
        assert "ENCOLAR" not in [
            a["codigo"] for a in orden["acciones_disponibles"]
        ]

        # Tomarla y trabajarla tampoco la vuelve a priorizar.
        tomar(cliente, orden_id)
        orden = _orden(cliente, orden_id)
        assert ids(orden).count("PROC-REP-150") == 1
        assert orden["prioridad"] == 2


def _con_prioridad_historica(tmp_path, cliente, valor: int) -> str:
    """Una Orden en cola cuyo JSON guarda un valor anterior a la escala."""
    orden_id = definida(cliente)
    ok(_encolar(cliente, orden_id, prioridad=3))
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    datos = json.loads(ruta.read_text("utf-8"))
    datos["prioridad"] = valor
    ruta.write_text(json.dumps(datos), "utf-8")
    return orden_id


def test_las_prioridades_historicas_se_conservan(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _con_prioridad_historica(tmp_path, cliente, 9)
        antes = archivo(tmp_path, orden_id)

        orden = _orden(cliente, orden_id)
        fila = _filas(cliente)[orden_id]

        # Leer y listar no la migran ni la invierten.
        assert archivo(tmp_path, orden_id) == antes
        assert orden["prioridad"] == fila["prioridad"] == 9
        assert fila["prioridad_texto"] == f"Prioridad 9 · {FUERA_DE_ESCALA}"

        # Se sigue trabajando con su valor.
        tomar(cliente, orden_id)
        assert _orden(cliente, orden_id)["prioridad"] == 9


def test_el_listado_trae_el_orden_por_prioridad(tmp_path):
    with _cliente(tmp_path, stock_bateria="9") as cliente:
        normal = definida(cliente)
        ok(_encolar(cliente, normal))  # 4 Normal
        urgente = definida(cliente)
        ok(_encolar(cliente, urgente, prioridad=1))
        sin_prioridad = definida(cliente)  # habilitada, todavia sin cola
        alta = definida(cliente)
        ok(_encolar(cliente, alta, prioridad=2))
        historica = _con_prioridad_historica(tmp_path, cliente, 7)
        urgente_despues = definida(cliente)
        ok(_encolar(cliente, urgente_despues, prioridad=1))
        entregada = definida(cliente)
        tomada(cliente, entregada)  # 3 Media, hasta que se entrega
        ok(cerrar_ejecucion(cliente, entregada, iniciar(cliente, entregada)))
        ok(aprobar(cliente, entregada, "DET-001"))
        saldo = ok(
            cliente.post(
                f"/api/orders/{entregada}/notify",
                json={"usuario_id": RECEPCION},
            )
        )["resumen"]["saldo"]
        ok(
            cliente.post(
                f"/api/orders/{entregada}/payments",
                json={
                    "usuario_id": RECEPCION,
                    "monto": saldo,
                    "metodo": "EFECTIVO",
                },
            )
        )
        ok(entregar(cliente, entregada))

        filas = _filas(cliente)

    por_prioridad = sorted(
        filas, key=lambda i: filas[i]["posicion_por_prioridad"]
    )
    assert por_prioridad == [
        urgente,
        urgente_despues,  # misma prioridad: ingreso posterior
        alta,
        normal,
        historica,
        sin_prioridad,
        entregada,
    ]
    assert sorted(f["posicion_por_prioridad"] for f in filas.values()) == list(
        range(7)
    )
    assert filas[entregada]["prioridad"] == 3
    assert filas[entregada]["prioridad_texto"] is None
