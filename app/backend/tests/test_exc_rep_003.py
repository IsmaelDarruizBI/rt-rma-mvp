"""EXC-REP-003 (reserva de insumos fallida al iniciar la Ejecucion): services.

PROC-REP-185 "Reserva fallida" -> 186 -> 211. La factibilidad (080) fue
correcta, pero al intentar la reserva real faltan insumos y el Detalle NO
tiene override propio (EXC-REP-002). No se crea Ejecucion ni reservas, el
stock no se toca, y el Detalle queda DEFINIDO (la representacion tecnica de
PENDIENTE) + BLOQUEADO_POR_RECURSOS.
"""

from decimal import Decimal

import pytest

from app.application import (
    acciones_disponibles,
    iniciar_detalle,
    progreso,
)
from app.application.contexto import ApplicationContext, construir_contexto
from app.core.config import Settings
from app.domain.models import (
    CondicionReparacionDetail,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    OrdenReparacion,
)
from app.services import (
    PrecondicionInvalidaError,
    RecursoNoDisponibleError,
    ResultadoEvaluacionOrden,
    definir_prioridad,
    evaluar_situacion_orden,
    faltantes_del_detalle,
    habilitar_orden,
    ingresar_a_cola,
    intentar_reserva_e_inicio,
    registrar_accion_funcional,
    registrar_espera_recursos,
    registrar_reserva_fallida,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_estacion_trabajo,
)
from app.services.recursos import ACCION_AUTORIZAR_OVERRIDE
from tests.fixtures.catalogos_mvp import (
    COMPATIBILIDADES,
    COORDINADOR,
    ESTACION,
    ESTACIONES,
    TECNICO,
    TIPO_BATERIA,
    t,
)
from tests.fixtures.override import override_en_100
from tests.test_api_exc_rep_001 import _cliente
from tests.test_api_exc_rep_002 import _tomar
from tests.test_api_exc_rep_003 import _definir
from tests.test_api_var_rep_001_002 import _crear_orden as _crear_orden_cliente
from tests.test_exc_rep_001 import (
    PREVISTOS,
    TIPO_PANTALLA,
    _con_detalles,
    _ids,
    _insumos,
    _validar,
)


def _en_toma(*tipos, base_stock="1") -> OrdenReparacion:
    """Factible (090 Si), habilitada, encolada y tomada por el tecnico."""
    orden, factible = _validar(
        _con_detalles(*(tipos or (TIPO_BATERIA,))),
        _insumos(a=base_stock, b=base_stock, c=base_stock),
    )
    assert factible is True
    orden = habilitar_orden(orden, fecha=t(20))
    orden = ingresar_a_cola(
        definir_prioridad(
            orden, prioridad=1, usuario=COORDINADOR, fecha=t(25)
        ),
        fecha=t(30),
    )
    orden, _ = validar_estacion_trabajo(
        orden,
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )
    return tomar_orden(
        orden, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )


def _seleccionar(orden, detalle_id="DET-001"):
    orden = seleccionar_detalle(
        orden, detalle_id=detalle_id, usuario=TECNICO, fecha=t(62)
    )
    orden, _ = validar_compatibilidad_detalle(
        orden,
        detalle_id=detalle_id,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(63),
    )
    return orden


def _intentar(
    orden, insumos, detalle_id="DET-001", externas=None, previstos=PREVISTOS
):
    return intentar_reserva_e_inicio(
        orden,
        detalle_id=detalle_id,
        usuario=TECNICO,
        insumos=insumos,
        insumos_previstos=previstos,
        fecha=t(65),
        reservas_externas=externas,
    )


# --- Helper de disponibilidad compartido ---


def test_faltantes_del_detalle_ordenados_y_con_reservas_ajenas():
    orden = _con_detalles(TIPO_PANTALLA)
    previstos = [p for p in PREVISTOS if p.tipo_reparacion_id == "TREP-002"]

    # INS-003 y INS-002 faltan: devueltos en orden deterministico.
    assert faltantes_del_detalle(
        "TREP-002",
        orden.movimientos_insumo,
        _insumos(a="1", b="0", c="0"),
        previstos,
    ) == ["INS-002", "INS-003"]
    # Sin faltantes: lista vacia.
    assert (
        faltantes_del_detalle(
            "TREP-002",
            orden.movimientos_insumo,
            _insumos(),
            previstos,
        )
        == []
    )
    # Una reserva ajena deja a INS-002 sin disponibilidad.
    assert faltantes_del_detalle(
        "TREP-002",
        orden.movimientos_insumo,
        _insumos(),
        previstos,
        {"INS-002": Decimal("1")},
    ) == ["INS-002"]


# --- Caso A: queda otro Detalle trabajable ---


def test_caso_a_det_a_falla_y_det_b_sigue_trabajable():
    orden = _en_toma(TIPO_BATERIA, TIPO_PANTALLA)
    antes = _seleccionar(orden)

    orden, exitosa = _intentar(antes, _insumos(a="0", b="1", c="1"))
    assert exitosa is False
    orden, resultado = evaluar_situacion_orden(orden, fecha=t(66))

    assert _ids(orden)[-5:] == [
        "PROC-REP-181",
        "PROC-REP-174",
        "PROC-REP-185",
        "PROC-REP-186",
        "PROC-REP-211",
    ]
    paso_185, paso_186, paso_211 = orden.historial[-3:]
    assert paso_185.observacion == "Reserva fallida"
    assert paso_185.usuario_id == TECNICO.id
    assert paso_185.reparacion_detail_id == "DET-001"
    assert paso_185.ejecucion_id is None
    assert paso_186.usuario_id is None
    assert paso_186.reparacion_detail_id == "DET-001"
    assert paso_186.observacion == "Faltantes: INS-001"
    assert resultado is ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE
    assert paso_211.observacion == "ABIERTA_TRABAJABLE"

    det_a, det_b = orden.reparaciones_detail
    assert det_a.estado is EstadoReparacionDetail.DEFINIDO
    assert det_a.condicion is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    assert det_b.estado is EstadoReparacionDetail.DEFINIDO
    assert det_b.condicion is CondicionReparacionDetail.SIN_BLOQUEO

    assert orden.ejecuciones == []
    assert orden.movimientos_insumo == []
    assert [toma.estado for toma in orden.tomas] == [EstadoTomaOrden.ACTIVA]
    assert orden.estado_workflow is EstadoWorkflow.EN_COLA
    assert orden.current_process == "PROC-REP-211"
    codigos = [
        (a.codigo, a.detalle_id)
        for a in acciones_disponibles(orden)
        if a.codigo != "REGISTRAR_PAGO"
    ]
    assert codigos == [
        ("INICIAR_DETALLE", "DET-002"),
        ("LIBERAR_ORDEN", None),
        # Transversal (BR-REP-003): el bloqueado puede autorizarse.
        ("OVERRIDE_RECURSOS", "DET-001"),
    ]


def test_la_orden_original_no_se_modifica():
    antes = _seleccionar(_en_toma())
    foto = antes.model_copy(deep=True)

    _intentar(antes, _insumos(a="0"))

    assert antes == foto


# --- Caso B: no queda ningun Detalle trabajable ---


def test_caso_b_unico_detalle_211_cierra_la_toma_y_va_a_120():
    orden, exitosa = _intentar(_seleccionar(_en_toma()), _insumos(a="0"))
    assert exitosa is False
    orden, resultado = evaluar_situacion_orden(orden, fecha=t(66))

    assert resultado is ResultadoEvaluacionOrden.PENDIENTE_RECURSOS
    assert _ids(orden)[-2:] == ["PROC-REP-211", "PROC-REP-120"]
    assert "PROC-REP-100" not in _ids(orden)
    assert "PROC-REP-110" not in _ids(orden)
    assert orden.current_process == "PROC-REP-120"
    (toma,) = orden.tomas
    assert toma.estado is EstadoTomaOrden.CERRADA and toma.fin == t(66)
    # El workflow conserva el ultimo hito (EN_COLA: nada empezo).
    assert orden.estado_workflow is EstadoWorkflow.EN_COLA
    assert [
        a.codigo
        for a in acciones_disponibles(orden)
        if a.codigo != "REGISTRAR_PAGO"
    ] == ["REVALIDAR_RECURSOS", "OVERRIDE_RECURSOS"]


def test_primer_intento_en_cola_y_con_trabajo_previo_en_reparacion():
    en_cola, _ = _intentar(_seleccionar(_en_toma()), _insumos(a="0"))
    assert en_cola.estado_workflow is EstadoWorkflow.EN_COLA

    con_trabajo = _seleccionar(_en_toma()).model_copy(
        update={"estado_workflow": EstadoWorkflow.EN_REPARACION}
    )
    fallida, _ = _intentar(con_trabajo, _insumos(a="0"))
    assert fallida.estado_workflow is EstadoWorkflow.EN_REPARACION


# --- Atomicidad y faltantes ---


def test_la_reserva_fallida_no_deja_reservas_ejecuciones_ni_movimientos():
    orden = _seleccionar(_en_toma(TIPO_PANTALLA))
    insumos = _insumos(a="1", b="1", c="0")  # solo INS-003 falta

    nueva, exitosa = _intentar(orden, insumos)

    assert exitosa is False
    assert nueva.movimientos_insumo == []  # ni siquiera INS-002 (parcial)
    assert nueva.ejecuciones == []
    assert [i.stock_fisico for i in insumos] == [Decimal("1")] * 2 + [
        Decimal("0")
    ]
    assert nueva.reparaciones_detail[0].estado is (
        EstadoReparacionDetail.DEFINIDO
    )


def test_varios_faltantes_se_registran_todos_y_ordenados():
    orden = _seleccionar(_en_toma(TIPO_PANTALLA))

    nueva, _ = _intentar(orden, _insumos(a="1", b="0", c="0"))

    assert nueva.historial[-1].observacion == "Faltantes: INS-002, INS-003"


def test_concurrencia_entre_ordenes_la_segunda_ve_la_reserva_de_la_primera():
    """OR-001 ya reservo la ultima unidad; OR-002 habia pasado 080."""
    primera, _ = _intentar(_seleccionar(_en_toma()), _insumos())
    assert primera.movimientos_insumo  # reservo
    segunda = _seleccionar(_en_toma())

    nueva, exitosa = _intentar(
        segunda, _insumos(), externas={"INS-001": Decimal("1")}
    )

    assert exitosa is False
    assert nueva.historial[-2].observacion == "Reserva fallida"
    assert nueva.historial[-1].observacion == "Faltantes: INS-001"
    assert nueva.movimientos_insumo == []


def test_con_stock_suficiente_se_delega_en_la_reserva_exitosa():
    orden = _seleccionar(_en_toma())

    nueva, exitosa = _intentar(orden, _insumos())

    assert exitosa is True
    assert "PROC-REP-186" not in _ids(nueva)
    assert nueva.historial[-1].referencia_id == "PROC-REP-185"
    assert nueva.historial[-1].observacion is None
    assert len(nueva.ejecuciones) == 1 and len(nueva.movimientos_insumo) == 1
    assert nueva.estado_workflow is EstadoWorkflow.EN_REPARACION


# --- Override: solo el del MISMO Detalle ---


def test_con_override_del_mismo_detalle_reserva_sin_reserva_fallida():
    orden, _ = _validar(_con_detalles(TIPO_BATERIA), _insumos(a="0"))
    orden = override_en_100(
        orden,
        detalle_id="DET-001",
        usuario=COORDINADOR,
        motivo="urgente",
        fecha=t(20),
    )
    orden = habilitar_orden(orden, fecha=t(21))
    orden = _seleccionar(_encolar_y_tomar(orden))

    nueva, exitosa = _intentar(orden, _insumos(a="0"))

    assert exitosa is True
    assert "PROC-REP-186" not in _ids(nueva)
    assert len(nueva.ejecuciones) == 1


def _encolar_y_tomar(orden):
    orden = ingresar_a_cola(
        definir_prioridad(
            orden, prioridad=1, usuario=COORDINADOR, fecha=t(25)
        ),
        fecha=t(30),
    )
    orden, _ = validar_estacion_trabajo(
        orden,
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )
    return tomar_orden(
        orden, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )


def test_el_override_de_otro_detalle_no_cuenta():
    orden = _seleccionar(_en_toma(TIPO_BATERIA, TIPO_PANTALLA))
    # Autorizacion registrada solo para DET-002 (el historial es la fuente).
    orden = registrar_accion_funcional(
        orden,
        accion_id=ACCION_AUTORIZAR_OVERRIDE,
        accion="AUTORIZAR_OVERRIDE_RECURSOS",
        fecha=t(64),
        usuario_id=COORDINADOR.id,
        reparacion_detail_id="DET-002",
        observacion="Motivo",
    )

    # DET-001 no tiene override propio: falta stock -> 186.
    nueva, exitosa = _intentar(orden, _insumos(a="0"))
    assert exitosa is False
    assert nueva.historial[-1].observacion == "Faltantes: INS-001"

    # DET-002 si lo tiene: reserva aunque falte stock.
    propia = _seleccionar(orden, "DET-002")
    reservada, exitosa = _intentar(
        propia, _insumos(b="0", c="0"), detalle_id="DET-002"
    )
    assert exitosa is True and "PROC-REP-186" not in _ids(reservada)


# --- Precondiciones: error, no reserva fallida ---


def test_sin_toma_es_una_precondicion_no_una_reserva_fallida():
    orden, _ = _validar(_con_detalles(TIPO_BATERIA), _insumos())
    orden = habilitar_orden(orden, fecha=t(20))

    with pytest.raises(PrecondicionInvalidaError):
        _intentar(orden, _insumos(a="0"))
    assert "PROC-REP-186" not in _ids(orden)


def test_con_ejecucion_activa_es_una_precondicion():
    orden, _ = _intentar(
        _seleccionar(_en_toma(TIPO_BATERIA, TIPO_PANTALLA)), _insumos()
    )
    # DET-001 en ejecucion: iniciar DET-002 es BR-REP-007, no una falla.
    with pytest.raises(PrecondicionInvalidaError, match="Ejecucion activa"):
        _intentar(orden, _insumos(b="0", c="0"), detalle_id="DET-002")


def test_un_detalle_bloqueado_es_una_precondicion():
    orden = _seleccionar(_en_toma())
    orden.reparaciones_detail[
        0
    ].condicion = CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS

    with pytest.raises(PrecondicionInvalidaError, match="condicion"):
        _intentar(orden, _insumos(a="0"))


def test_la_funcion_exitosa_sigue_lanzando_el_error_defensivo():
    orden = _seleccionar(_en_toma())

    with pytest.raises(RecursoNoDisponibleError, match="INS-001"):
        reservar_insumos_e_iniciar_ejecucion(
            orden,
            detalle_id="DET-001",
            usuario=TECNICO,
            insumos=_insumos(a="0"),
            insumos_previstos=PREVISTOS,
            fecha=t(65),
        )
    assert orden.movimientos_insumo == [] and orden.ejecuciones == []


# --- PROC-REP-186 ---


def test_186_exige_una_reserva_fallida_previa_y_faltantes():
    orden = _seleccionar(_en_toma())

    with pytest.raises(PrecondicionInvalidaError, match="reserva fallida"):
        registrar_reserva_fallida(
            orden, detalle_id="DET-001", faltantes=["INS-001"], fecha=t(66)
        )


def test_186_no_toca_otros_detalles_ni_el_stock():
    orden = _seleccionar(_en_toma(TIPO_BATERIA, TIPO_PANTALLA))

    nueva, _ = _intentar(orden, _insumos(a="0"))

    assert nueva.reparaciones_detail[1].condicion is (
        CondicionReparacionDetail.SIN_BLOQUEO
    )
    assert nueva.movimientos_insumo == [] and nueva.ejecuciones == []


# --- Habilitar desde EN_COLA (I-1) ---


def _a_120_en_cola() -> OrdenReparacion:
    orden, _ = _intentar(_seleccionar(_en_toma()), _insumos(a="0"))
    orden, _ = evaluar_situacion_orden(orden, fecha=t(66))
    assert orden.estado_workflow is EstadoWorkflow.EN_COLA
    assert orden.current_process == "PROC-REP-120"
    return orden


def test_revalidar_desde_120_en_cola_permite_habilitar():
    orden, factible = _validar(_a_120_en_cola(), _insumos(), minuto=70)
    assert factible is True

    habilitada = habilitar_orden(orden, fecha=t(71))

    assert habilitada.estado_workflow is EstadoWorkflow.HABILITADA
    assert _ids(habilitada)[-3:] == [
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]


def test_en_cola_sin_090_si_ni_130_valido_sigue_rechazada():
    # 120, 100, 110 y una Orden EN_COLA arbitraria no habilitan.
    for nodo in ("PROC-REP-120", "PROC-REP-100", "PROC-REP-110"):
        orden = _a_120_en_cola().model_copy(update={"current_process": nodo})
        with pytest.raises(PrecondicionInvalidaError, match="factibilidad"):
            habilitar_orden(orden, fecha=t(71))

    arbitraria = _en_toma().model_copy(deep=True)
    with pytest.raises(PrecondicionInvalidaError):
        habilitar_orden(arbitraria, fecha=t(71))


def test_090_ninguno_en_cola_no_habilita():
    orden, factible = _validar(_a_120_en_cola(), _insumos(a="0"), minuto=70)
    assert factible is False
    with pytest.raises(PrecondicionInvalidaError):
        habilitar_orden(orden, fecha=t(71))


def test_003_120_revalida_100_override_130_140_en_cola():
    orden, factible = _validar(_a_120_en_cola(), _insumos(a="0"), minuto=70)
    assert factible is False and orden.current_process == "PROC-REP-100"

    orden = override_en_100(
        orden,
        detalle_id="DET-001",
        usuario=COORDINADOR,
        motivo="urgente",
        fecha=t(72),
    )
    habilitada = habilitar_orden(orden, fecha=t(73))

    assert habilitada.estado_workflow is EstadoWorkflow.HABILITADA
    assert _ids(habilitada)[-3:] == [
        "PROC-REP-110",
        "PROC-REP-130",
        "PROC-REP-140",
    ]


# --- Progreso ---


def test_progreso_incluye_186_y_120_solo_con_evidencia():
    orden, _ = _intentar(_seleccionar(_en_toma()), _insumos(a="0"))
    orden, _ = evaluar_situacion_orden(orden, fecha=t(66))
    pasos = progreso(orden)
    ruta = [p.process_id for p in pasos]

    assert ruta.index("PROC-REP-186") == ruta.index("PROC-REP-185") + 1
    assert ruta.index("PROC-REP-120") == ruta.index("PROC-REP-211") + 1
    assert {p.process_id for p in pasos if p.alcanzado} >= {
        "PROC-REP-186",
        "PROC-REP-120",
    }

    sin_fallo = [p.process_id for p in progreso(_seleccionar(_en_toma()))]
    assert "PROC-REP-186" not in sin_fallo
    assert "PROC-REP-120" not in sin_fallo


def test_progreso_no_duplica_120_si_ya_hubo_100():
    orden = _a_120_en_cola()
    orden, _ = _validar(orden, _insumos(a="0"), minuto=70)  # 100
    orden = registrar_espera_recursos(orden, fecha=t(75))
    ruta = [p.process_id for p in progreso(orden)]

    assert ruta.count("PROC-REP-120") == 1


# --- Una sola escritura (application) ---


class _RepoEspia:
    """Cuenta los ``guardar`` y delega en el repository real."""

    def __init__(self, real) -> None:
        self._real = real
        self.guardados: list[OrdenReparacion] = []

    def guardar(self, orden):
        self.guardados.append(orden.model_copy(deep=True))
        return self._real.guardar(orden)

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)


def _con_espia(tmp_path, stock="1"):
    cliente = _cliente(tmp_path, stock=stock)
    orden_id = _crear_orden_cliente(cliente)
    _definir(cliente, orden_id)
    _tomar(cliente, orden_id)
    real = construir_contexto(Settings(data_dir=tmp_path))
    espia = _RepoEspia(real.ordenes)
    return (
        cliente,
        orden_id,
        ApplicationContext(ordenes=espia, catalogos=real.catalogos),
        espia,
    )


def test_la_orden_se_guarda_una_sola_vez_ante_reserva_fallida(tmp_path):
    from tests.test_api_exc_rep_001 import _fijar_stock

    cliente, orden_id, contexto, espia = _con_espia(tmp_path)
    with cliente:
        _fijar_stock(tmp_path, **{"INS-001": 0, "INS-002": 0})
        espia.guardados.clear()

        orden = iniciar_detalle(
            contexto,
            orden_id=orden_id,
            detalle_id="DET-001",
            usuario_id="TECH-001",
        )

        assert len(espia.guardados) == 1
        (guardada,) = espia.guardados
        assert _ids(guardada)[-6:] == [
            "PROC-REP-181",
            "PROC-REP-174",
            "PROC-REP-185",
            "PROC-REP-186",
            "PROC-REP-211",
            "PROC-REP-120",
        ]
        assert guardada == orden
        assert guardada.ejecuciones == [] and guardada.movimientos_insumo == []


def test_la_orden_se_guarda_una_sola_vez_ante_reserva_exitosa(tmp_path):
    cliente, orden_id, contexto, espia = _con_espia(tmp_path)
    with cliente:
        espia.guardados.clear()

        iniciar_detalle(
            contexto,
            orden_id=orden_id,
            detalle_id="DET-001",
            usuario_id="TECH-001",
        )

        assert len(espia.guardados) == 1
        assert len(espia.guardados[0].ejecuciones) == 1
