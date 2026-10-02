"""VAR-REP-001 / VAR-REP-002 componiendo services (sin HTTP).

La Orden pasa por EN_REVISION con CERO Detalles; el comprobante depende
solo de ``PoliticaOrigen``; la revision (PROC-REP-065) deja quien, cuando
y el resultado en el historial; y los Detalles se definen luego con
PROC-REP-068 (una vez) y PROC-REP-075 (por Detalle).
"""

import json

import pytest

from app.application import acciones_disponibles, progreso
from app.domain.models import EstadoWorkflow, OrdenReparacion, OrigenOrden
from app.services import (
    PrecondicionInvalidaError,
    crear_orden_garantia_rma,
    definir_reparacion_detail,
    definir_reparacion_detail_luego_revision,
    generar_comprobante_recepcion,
    habilitar_orden,
    marcar_orden_en_revision,
    registrar_revision_tecnica,
    validar_factibilidad_detalles,
)
from app.storage import JsonOrdenReparacionRepository
from tests.fixtures import flujo_mvp
from tests.fixtures import flujo_mvp_rt as flujo_rt
from tests.fixtures.catalogos_mvp import (
    ADMINISTRADOR,
    INSUMOS,
    INSUMOS_PREVISTOS,
    RECEPCION,
    TECNICO,
    TIPO_BATERIA,
    t,
)


def _en_revision(orden: OrdenReparacion) -> OrdenReparacion:
    orden = marcar_orden_en_revision(orden, usuario=RECEPCION, fecha=t(1))
    return generar_comprobante_recepcion(orden, fecha=t(2))


def _revisada(orden: OrdenReparacion) -> OrdenReparacion:
    return registrar_revision_tecnica(
        _en_revision(orden),
        usuario=TECNICO,
        resultado="Placa danada.",
        fecha=t(3),
    )


def _garantia() -> OrdenReparacion:
    return crear_orden_garantia_rma(
        orden_id="OR-002",
        orden_origen=flujo_mvp.orden_entregada(),
        detalle_origen_ids=["DET-001"],
        usuario=RECEPCION,
        fecha=t(300),
    )


def _definir(orden, detalle_id="DET-001", **extra):
    return definir_reparacion_detail_luego_revision(
        orden,
        detalle_id=detalle_id,
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(4),
        **extra,
    )


def _codigos(orden) -> list[str]:
    return [a.codigo for a in acciones_disponibles(orden)]


# --- PROC-REP-045 No -> 055 ---------------------------------------------


def test_enviar_a_revision_deja_la_orden_en_revision_sin_detalles():
    orden = marcar_orden_en_revision(
        flujo_mvp.orden_creada(), usuario=RECEPCION, fecha=t(1)
    )

    assert orden.estado_workflow is EstadoWorkflow.EN_REVISION
    assert orden.reparaciones_detail == []
    assert [
        (p.referencia_id, p.observacion, p.usuario_id)
        for p in orden.historial[-2:]
    ] == [
        ("PROC-REP-045", "No", RECEPCION.id),
        ("PROC-REP-055", None, None),
    ]


def test_el_comprobante_depende_solo_de_la_politica_del_origen():
    con = _en_revision(flujo_mvp.orden_creada())
    assert con.documentos.comprobante_recepcion.generado is True
    assert [p.referencia_id for p in con.historial[-2:]] == [
        "PROC-REP-050",
        "PROC-REP-060",
    ]

    sin = _en_revision(flujo_rt.orden_rt_creada())
    assert sin.documentos.comprobante_recepcion.generado is False
    assert [p.referencia_id for p in sin.historial[-1:]] == ["PROC-REP-050"]
    assert "PROC-REP-060" not in [p.referencia_id for p in sin.historial]

    garantia = _en_revision(_garantia())
    assert garantia.documentos.comprobante_recepcion.generado is True


def test_enviar_a_revision_rechaza_actor_estado_y_detalles():
    with pytest.raises(PrecondicionInvalidaError):
        marcar_orden_en_revision(
            flujo_mvp.orden_creada(), usuario=TECNICO, fecha=t(1)
        )
    with pytest.raises(PrecondicionInvalidaError):
        marcar_orden_en_revision(
            flujo_mvp.orden_con_detalle(), usuario=RECEPCION, fecha=t(1)
        )
    with pytest.raises(PrecondicionInvalidaError):
        marcar_orden_en_revision(
            _en_revision(flujo_mvp.orden_creada()),
            usuario=RECEPCION,
            fecha=t(1),
        )


# --- PROC-REP-065 ----------------------------------------------------------


def test_revision_tecnica_registra_tecnico_fecha_y_resultado():
    orden = _revisada(flujo_mvp.orden_creada())

    paso = orden.historial[-1]
    assert paso.referencia_id == "PROC-REP-065"
    assert paso.usuario_id == TECNICO.id
    assert paso.fecha == t(3)
    assert paso.observacion == "Placa danada."
    assert orden.estado_workflow is EstadoWorkflow.EN_REVISION
    assert orden.reparaciones_detail == []


def test_revision_tecnica_guards():
    en_revision = _en_revision(flujo_mvp.orden_creada())
    with pytest.raises(PrecondicionInvalidaError):
        registrar_revision_tecnica(
            en_revision, usuario=RECEPCION, resultado="x", fecha=t(3)
        )
    with pytest.raises(PrecondicionInvalidaError):
        registrar_revision_tecnica(
            en_revision, usuario=TECNICO, resultado="  ", fecha=t(3)
        )
    with pytest.raises(PrecondicionInvalidaError):
        registrar_revision_tecnica(
            flujo_mvp.orden_creada(),
            usuario=TECNICO,
            resultado="x",
            fecha=t(3),
        )
    with pytest.raises(PrecondicionInvalidaError):
        registrar_revision_tecnica(
            _revisada(flujo_mvp.orden_creada()),
            usuario=TECNICO,
            resultado="otra",
            fecha=t(4),
        )


# --- PROC-REP-068 / 075 ----------------------------------------------------


def test_068_una_sola_vez_y_075_por_detalle():
    orden = _definir(_revisada(flujo_mvp.orden_creada()))
    orden = _definir(orden, detalle_id="DET-002")

    ids = [p.referencia_id for p in orden.historial]
    assert ids.count("PROC-REP-068") == 1
    assert ids.count("PROC-REP-075") == 2
    assert "PROC-REP-070" not in ids
    assert ids.count("PROC-REP-045") == 1  # solo el "No"
    assert [d.id for d in orden.reparaciones_detail] == ["DET-001", "DET-002"]
    assert orden.estado_workflow is EstadoWorkflow.EN_REVISION  # hasta 140


def test_definir_luego_de_revision_comparte_el_snapshot_de_070():
    por_070 = definir_reparacion_detail(
        flujo_mvp.orden_creada(),
        detalle_id="DET-001",
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(5),
    )
    por_075 = _definir(_revisada(flujo_mvp.orden_creada()))

    assert por_075.reparaciones_detail == por_070.reparaciones_detail


def test_definir_luego_de_revision_guards():
    with pytest.raises(PrecondicionInvalidaError):  # antes de 065
        _definir(_en_revision(flujo_mvp.orden_creada()))
    with pytest.raises(PrecondicionInvalidaError):  # fuera de EN_REVISION
        _definir(flujo_mvp.orden_creada())
    with pytest.raises(PrecondicionInvalidaError):  # actor
        definir_reparacion_detail_luego_revision(
            _revisada(flujo_mvp.orden_creada()),
            detalle_id="DET-001",
            tipo_reparacion=TIPO_BATERIA,
            usuario=ADMINISTRADOR,
            fecha=t(4),
        )
    with pytest.raises(PrecondicionInvalidaError):  # Tipo inactivo
        definir_reparacion_detail_luego_revision(
            _revisada(flujo_mvp.orden_creada()),
            detalle_id="DET-001",
            tipo_reparacion=TIPO_BATERIA.model_copy(update={"activo": False}),
            usuario=RECEPCION,
            fecha=t(4),
        )


def test_definir_luego_de_revision_no_confunde_detalles_con_el_historial():
    """La procedencia sale de ``detalles_origen_ids``, nunca del historial."""
    garantia = _revisada(_garantia())
    assert garantia.detalles_origen_ids == ["DET-001"]

    # Aunque la observacion de PROC-REP-035 cambie, el origen es el mismo.
    garantia.historial[0].observacion = "texto sin ids"
    orden = _definir(garantia)
    assert orden.reparaciones_detail[0].detalle_origen_id == "DET-001"


def test_con_varios_detalles_origen_hay_que_elegir_explicitamente():
    garantia = _revisada(_garantia()).model_copy(
        update={"detalles_origen_ids": ["DET-001", "DET-002"]}
    )

    with pytest.raises(PrecondicionInvalidaError, match="indicar"):
        _definir(garantia)
    with pytest.raises(PrecondicionInvalidaError):
        _definir(garantia, detalle_origen_id="DET-999")

    orden = _definir(garantia, detalle_origen_id="DET-002")
    assert orden.reparaciones_detail[0].detalle_origen_id == "DET-002"


def test_un_origen_que_no_es_garantia_no_admite_detalle_origen():
    with pytest.raises(PrecondicionInvalidaError):
        _definir(
            _revisada(flujo_mvp.orden_creada()), detalle_origen_id="DET-001"
        )


# --- Acciones ----------------------------------------------------------------


def test_acciones_a_lo_largo_de_la_revision():
    orden = flujo_mvp.orden_creada()
    assert _codigos(orden) == ["AGREGAR_DETALLE", "ENVIAR_A_REVISION"]

    orden = _en_revision(orden)
    assert _codigos(orden) == ["REALIZAR_REVISION"]
    assert acciones_disponibles(orden)[0].roles == (TECNICO.rol,)

    # Sin Detalles: agregar uno o concluir SIN_REPARACION (068 No -> 069).
    orden = _revisada(flujo_mvp.orden_creada())
    assert _codigos(orden) == [
        "AGREGAR_DETALLE_DESDE_REVISION",
        "FINALIZAR_SIN_REPARACION",
    ]
    assert {a.roles for a in acciones_disponibles(orden)} == {(RECEPCION.rol,)}

    # Con al menos un Detalle: agregar otro o finalizar la definicion.
    orden = _definir(orden)
    assert _codigos(orden) == [
        "AGREGAR_DETALLE_DESDE_REVISION",
        "FINALIZAR_DEFINICION",
        "REGISTRAR_PAGO",
    ]


def test_enviar_a_revision_no_se_ofrece_con_detalles_ya_definidos():
    orden = definir_reparacion_detail(
        flujo_mvp.orden_creada(),
        detalle_id="DET-001",
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(5),
    )
    assert orden.estado_workflow is EstadoWorkflow.REQUERIMIENTO
    assert "ENVIAR_A_REVISION" not in _codigos(orden)


def test_rt_en_revision_ofrece_las_mismas_acciones_sin_garantia():
    orden = flujo_rt.orden_rt_creada()
    assert _codigos(orden) == ["AGREGAR_DETALLE", "ENVIAR_A_REVISION"]

    orden = _en_revision(orden)
    assert _codigos(orden) == ["REALIZAR_REVISION"]
    assert "INICIAR_GARANTIA_RMA" not in _codigos(flujo_rt.orden_rt_devuelta())


def test_orden_entregada_publica_solo_iniciar_garantia():
    # Ya no hay una garantia "directa" y otra "para revision": la revision
    # es obligatoria (BR-REP-019) y hay una sola accion de Orden.
    assert _codigos(flujo_mvp.orden_entregada()) == ["INICIAR_GARANTIA_RMA"]


# --- Progreso -------------------------------------------------------------


@pytest.mark.parametrize(
    ("orden", "origen", "inicio", "tiene_020", "tiene_060"),
    [
        (
            flujo_mvp.orden_creada,
            OrigenOrden.CLIENTE_EXTERNO,
            "PROC-REP-010",
            False,
            True,
        ),
        (
            flujo_rt.orden_rt_creada,
            OrigenOrden.RT_INTERNO,
            "PROC-REP-010",
            True,
            False,
        ),
        (
            _garantia,
            OrigenOrden.RMA_GARANTIA_REPARACION,
            "PROC-REP-035",
            False,
            True,
        ),
    ],
)
def test_progreso_de_revision_por_origen(
    orden, origen, inicio, tiene_020, tiene_060
):
    en_revision = _en_revision(orden())
    assert en_revision.origen is origen
    ruta = [p.process_id for p in progreso(en_revision)]

    assert ruta[0] == inicio
    assert ("PROC-REP-020" in ruta) is tiene_020
    assert ("PROC-REP-060" in ruta) is tiene_060
    assert "PROC-REP-070" not in ruta
    i = ruta.index("PROC-REP-045")
    assert ruta[i + 1] == "PROC-REP-055"
    j = ruta.index("PROC-REP-080")
    assert ruta[j - 3 : j] == ["PROC-REP-065", "PROC-REP-068", "PROC-REP-075"]
    assert ruta[-1] == "EVT-REP-999"


def test_progreso_happy_path_no_cambia_sin_055():
    ruta = [p.process_id for p in progreso(flujo_mvp.orden_creada())]
    assert "PROC-REP-055" not in ruta
    assert "PROC-REP-070" in ruta


# --- Persistencia ------------------------------------------------------------


@pytest.fixture
def repo(tmp_path) -> JsonOrdenReparacionRepository:
    return JsonOrdenReparacionRepository(tmp_path / "ordenes")


def test_json_previo_sin_detalles_origen_ids_carga_con_default_vacio(repo):
    repo.guardar(flujo_mvp.orden_entregada())
    ruta = repo.directorio / "OR-001.json"
    crudo = json.loads(ruta.read_text(encoding="utf-8"))
    crudo.pop("detalles_origen_ids", None)
    ruta.write_text(json.dumps(crudo), encoding="utf-8")

    assert repo.obtener("OR-001").detalles_origen_ids == []


def test_detalles_origen_ids_hace_round_trip(repo):
    garantia = _revisada(_garantia())
    repo.guardar(garantia)

    recuperada = repo.obtener(garantia.id)
    assert recuperada.detalles_origen_ids == ["DET-001"]
    assert recuperada.estado_workflow is EstadoWorkflow.EN_REVISION
    assert recuperada.model_dump() == garantia.model_dump()
    crudo = json.loads(
        (repo.directorio / f"{garantia.id}.json").read_text("utf-8")
    )
    assert crudo["detalles_origen_ids"] == ["DET-001"]
    assert "total" not in crudo and "saldo" not in crudo


def test_los_origenes_que_no_son_garantia_tienen_lista_vacia():
    assert flujo_mvp.orden_creada().detalles_origen_ids == []
    assert flujo_rt.orden_rt_creada().detalles_origen_ids == []


# --- Gate de PROC-REP-140 desde revision ----------------------------------


def test_habilitar_no_permite_saltear_080_090_desde_revision():
    orden = _definir(_revisada(flujo_mvp.orden_creada()))
    assert orden.estado_workflow is EstadoWorkflow.EN_REVISION
    assert orden.current_process == "PROC-REP-075"

    with pytest.raises(PrecondicionInvalidaError, match="factibilidad"):
        habilitar_orden(orden, fecha=t(10))
    assert "PROC-REP-140" not in [p.referencia_id for p in orden.historial]


def test_habilitar_funciona_desde_revision_tras_080_090_si():
    orden = _definir(_revisada(flujo_mvp.orden_creada()))
    orden, factible = validar_factibilidad_detalles(
        orden,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(8),
    )
    assert factible is True

    habilitada = habilitar_orden(orden, fecha=t(10))

    assert habilitada.estado_workflow is EstadoWorkflow.HABILITADA
    assert [p.referencia_id for p in habilitada.historial[-4:]] == [
        "PROC-REP-075",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]
