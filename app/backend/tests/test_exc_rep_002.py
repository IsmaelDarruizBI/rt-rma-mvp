"""EXC-REP-002 (recursos insuficientes, resuelto por override) en services.

PROC-REP-090 "Ninguno trabajable" -> 100 -> 110 "Si" -> 130 -> 140. Un
Coordinador RMA fuerza UN Detalle bloqueado (BR-REP-003); el override solo
REGISTRA la autorizacion en el historial: no reserva ni descuenta stock. Con
override valido de ESE Detalle, PROC-REP-185 reserva aunque no alcance y
PROC-REP-210 puede dejar el stock fisico negativo; sin override se conserva
el comportamiento anterior.
"""

from decimal import Decimal

import pytest

from app.application import acciones_disponibles, progreso
from app.domain.models import (
    CondicionReparacionDetail,
    EstadoEjecucion,
    EstadoWorkflow,
    InsumoUtilizado,
    OrdenReparacion,
    RolUsuario,
    TipoMovimientoInsumo,
    TipoReparacionInsumos,
    Usuario,
)
from app.services import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    RecursoNoDisponibleError,
    aplicar_movimientos_inventario,
    definir_prioridad,
    ejecutar_detalle,
    habilitar_orden,
    ingresar_a_cola,
    registrar_ejecucion_completada,
    registrar_espera_recursos,
    registrar_override_recursos,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
    stock_disponible,
    tiene_override_factibilidad,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_estacion_trabajo,
)
from app.storage import JsonCatalogosRepository, JsonOrdenReparacionRepository
from app.storage.json.base import escribir_json_atomico
from tests.fixtures import flujo_mvp
from tests.fixtures.catalogos_mvp import (
    ADMINISTRADOR,
    COMPATIBILIDADES,
    COORDINADOR,
    ESTACION,
    ESTACIONES,
    RECEPCION,
    TECNICO,
    TIPO_BATERIA,
    t,
)
from tests.test_exc_rep_001 import (
    PREVISTOS,
    TIPO_PANTALLA,
    _con_detalles,
    _ids,
    _insumos,
    _validar,
)

MOTIVO = "Cliente urgente; el repuesto llega manana."


def _bloqueada(a="0", b="1", *tipos) -> OrdenReparacion:
    """Ningun Detalle trabajable: detenida en PROC-REP-100."""
    orden, factible = _validar(
        _con_detalles(*(tipos or (TIPO_BATERIA,))),
        _insumos(a=a, b=b, c=b),
    )
    assert factible is False and orden.current_process == "PROC-REP-100"
    return orden


def _forzar(orden, detalle_id="DET-001", usuario=COORDINADOR, minuto=20):
    return registrar_override_recursos(
        orden,
        detalle_id=detalle_id,
        usuario=usuario,
        motivo=MOTIVO,
        fecha=t(minuto),
    )


def _habilitada_por_override(**kw) -> OrdenReparacion:
    return habilitar_orden(_forzar(_bloqueada(**kw)), fecha=t(21))


# --- Flujo 090 Ninguno -> 100 -> 110 Si -> 130 -> 140 ---


def test_override_completo_090_ninguno_100_110_si_130_140():
    orden = _habilitada_por_override()

    assert _ids(orden)[-6:] == [
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-100",
        "PROC-REP-110",
        "PROC-REP-130",
        "PROC-REP-140",
    ]
    assert orden.estado_workflow is EstadoWorkflow.HABILITADA
    assert orden.current_process == "PROC-REP-140"
    # No se fabrica un 090 "Si": el unico 090 es "Ninguno trabajable".
    observaciones_090 = [
        p.observacion
        for p in orden.historial
        if p.referencia_id == "PROC-REP-090"
    ]
    assert observaciones_090 == ["Ninguno trabajable"]
    assert (
        orden.reparaciones_detail[0].condicion
        is CondicionReparacionDetail.SIN_BLOQUEO
    )


def test_el_override_queda_trazado_con_usuario_fecha_detalle_y_motivo():
    orden = _forzar(_bloqueada(), minuto=22)

    paso_110, paso_130 = orden.historial[-2:]
    assert (paso_110.referencia_id, paso_110.observacion) == (
        "PROC-REP-110",
        "Si",
    )
    assert paso_110.usuario_id == COORDINADOR.id
    assert paso_130.referencia_id == "PROC-REP-130"
    assert paso_130.usuario_id == COORDINADOR.id
    assert paso_130.fecha == t(22)
    assert paso_130.reparacion_detail_id == "DET-001"
    assert MOTIVO in paso_130.observacion
    assert "Validacion ignorada" in paso_130.observacion
    assert "PROC-REP-080/090" in paso_130.observacion
    assert tiene_override_factibilidad(orden, "DET-001") is True
    assert tiene_override_factibilidad(orden, "DET-002") is False


@pytest.mark.parametrize(
    "usuario",
    [
        RECEPCION,
        TECNICO,
        ADMINISTRADOR,
        Usuario(
            id="COORD-OFF",
            nombre="Coordinador inactivo",
            rol=RolUsuario.COORDINADOR_RMA,
            activo=False,
        ),
    ],
    ids=["recepcion", "tecnico", "administrador", "coordinador_inactivo"],
)
def test_solo_un_coordinador_activo_puede_hacer_el_override(usuario):
    orden = _bloqueada()
    with pytest.raises(PrecondicionInvalidaError):
        _forzar(orden, usuario=usuario)
    assert tiene_override_factibilidad(orden, "DET-001") is False


@pytest.mark.parametrize("motivo", ["", "   ", "\n\t"])
def test_el_motivo_es_obligatorio(motivo):
    with pytest.raises(PrecondicionInvalidaError, match="motivo"):
        registrar_override_recursos(
            _bloqueada(),
            detalle_id="DET-001",
            usuario=COORDINADOR,
            motivo=motivo,
            fecha=t(20),
        )


def test_el_override_solo_vale_desde_100_y_sobre_un_detalle_bloqueado():
    with pytest.raises(PrecondicionInvalidaError, match="PROC-REP-100"):
        _forzar(flujo_mvp.orden_con_factibilidad())
    with pytest.raises(PrecondicionInvalidaError, match="PROC-REP-100"):
        _forzar(registrar_espera_recursos(_bloqueada(), fecha=t(20)))  # 120
    with pytest.raises(EntidadNoEncontradaError):
        _forzar(_bloqueada(), detalle_id="DET-999")

    parcial, _ = _validar(
        _con_detalles(TIPO_BATERIA, TIPO_PANTALLA), _insumos(a="1", b="0")
    )
    assert parcial.current_process == "PROC-REP-090"  # hay uno trabajable
    with pytest.raises(PrecondicionInvalidaError):
        _forzar(parcial)


# --- Solo el Detalle objetivo; Multi-Detalle ---


def test_solo_el_detalle_forzado_pasa_a_sin_bloqueo():
    orden = _bloqueada("0", "0", TIPO_BATERIA, TIPO_PANTALLA)
    assert [d.condicion for d in orden.reparaciones_detail] == [
        CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    ] * 2

    habilitada = habilitar_orden(_forzar(orden, "DET-001"), fecha=t(21))

    a, b = habilitada.reparaciones_detail
    assert a.condicion is CondicionReparacionDetail.SIN_BLOQUEO
    assert b.condicion is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    assert habilitada.estado_workflow is EstadoWorkflow.HABILITADA
    assert tiene_override_factibilidad(habilitada, "DET-002") is False


def test_override_de_a_deja_a_iniciable_y_b_no_iniciable():
    habilitada = habilitar_orden(
        _forzar(_bloqueada("0", "0", TIPO_BATERIA, TIPO_PANTALLA)),
        fecha=t(21),
    )
    en_cola = ingresar_a_cola(
        definir_prioridad(
            habilitada, prioridad=1, usuario=COORDINADOR, fecha=t(25)
        ),
        fecha=t(30),
    )
    orden, _ = validar_estacion_trabajo(
        en_cola,
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )
    orden = tomar_orden(
        orden, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )

    iniciables = [
        a.detalle_id
        for a in acciones_disponibles(orden)
        if a.codigo == "INICIAR_DETALLE"
    ]
    assert iniciables == ["DET-001"]
    with pytest.raises(PrecondicionInvalidaError):
        seleccionar_detalle(
            orden, detalle_id="DET-002", usuario=TECNICO, fecha=t(62)
        )


# --- Gate de PROC-REP-140 ---


def test_no_se_habilita_directo_desde_100_ni_desde_110():
    en_100 = _bloqueada()
    with pytest.raises(PrecondicionInvalidaError, match="factibilidad"):
        habilitar_orden(en_100, fecha=t(21))

    en_110 = en_100.model_copy(update={"current_process": "PROC-REP-110"})
    with pytest.raises(PrecondicionInvalidaError, match="factibilidad"):
        habilitar_orden(en_110, fecha=t(21))

    # Aun en 130, sin un override valido registrado, no habilita.
    en_130 = en_100.model_copy(update={"current_process": "PROC-REP-130"})
    with pytest.raises(PrecondicionInvalidaError):
        habilitar_orden(en_130, fecha=t(21))
    assert "PROC-REP-140" not in _ids(en_100)


def test_el_gate_de_090_si_sigue_vigente():
    orden = habilitar_orden(flujo_mvp.orden_con_factibilidad(), fecha=t(20))
    assert orden.estado_workflow is EstadoWorkflow.HABILITADA


def test_la_rama_110_no_hacia_120_no_tiene_regresion():
    orden = registrar_espera_recursos(_bloqueada(), fecha=t(20))
    assert _ids(orden)[-2:] == ["PROC-REP-110", "PROC-REP-120"]
    assert orden.historial[-2].observacion == "No"
    assert orden.historial[-2].usuario_id is None


# --- 130 no toca el stock ---


def test_el_override_no_reserva_ni_modifica_stock():
    insumos = _insumos(a="0")
    orden, _ = _validar(_con_detalles(TIPO_BATERIA), insumos)

    orden = _forzar(orden)

    assert orden.movimientos_insumo == []
    assert insumos[0].stock_fisico == Decimal("0")
    habilitada = habilitar_orden(orden, fecha=t(21))
    assert habilitada.movimientos_insumo == []


# --- 185 y 210 con y sin override ---


def _en_toma(orden: OrdenReparacion) -> OrdenReparacion:
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


def _seleccionar(orden, detalle_id):
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


def _reservar(orden, insumos, previstos=PREVISTOS, detalle_id="DET-001"):
    return reservar_insumos_e_iniciar_ejecucion(
        orden,
        detalle_id=detalle_id,
        usuario=TECNICO,
        insumos=insumos,
        insumos_previstos=previstos,
        fecha=t(65),
    )


def test_con_override_185_reserva_y_deja_el_disponible_negativo():
    insumos = _insumos(a="0")
    orden = _seleccionar(_en_toma(_habilitada_por_override()), "DET-001")

    orden = _reservar(orden, insumos)

    (reserva,) = orden.movimientos_insumo
    assert reserva.tipo is TipoMovimientoInsumo.RESERVA
    assert reserva.cantidad == Decimal("1")
    (ejecucion,) = orden.ejecuciones
    assert ejecucion.estado is EstadoEjecucion.EN_PROGRESO
    # La RESERVA no toca el stock fisico: solo el disponible queda negativo.
    assert insumos[0].stock_fisico == Decimal("0")
    assert stock_disponible(insumos[0], orden.movimientos_insumo) == Decimal(
        "-1"
    )


def test_sin_override_185_con_stock_insuficiente_sigue_fallando():
    orden = _seleccionar(
        _en_toma(
            habilitar_orden(flujo_mvp.orden_con_factibilidad(), fecha=t(20))
        ),
        "DET-001",
    )

    with pytest.raises(RecursoNoDisponibleError):
        _reservar(orden, _insumos(a="0"))
    assert orden.movimientos_insumo == [] and orden.ejecuciones == []


def test_185_con_override_es_atomico_reserva_todo_o_nada():
    """Con override se generan TODAS las reservas previstas (nunca parcial)."""
    previstos = [
        TipoReparacionInsumos(
            tipo_reparacion_id="TREP-001",
            insumo_id="INS-001",
            cantidad=Decimal("1"),
        ),
        TipoReparacionInsumos(
            tipo_reparacion_id="TREP-001",
            insumo_id="INS-002",
            cantidad=Decimal("2"),
        ),
    ]
    orden = _seleccionar(_en_toma(_habilitada_por_override()), "DET-001")

    orden = _reservar(orden, _insumos(a="0", b="0"), previstos=previstos)

    assert sorted(
        (m.insumo_id, m.cantidad) for m in orden.movimientos_insumo
    ) == [
        ("INS-001", Decimal("1")),
        ("INS-002", Decimal("2")),
    ]


def _con_repos(tmp_path, insumos):
    escribir_json_atomico(
        tmp_path / "catalogs" / "insumos.json",
        [i.model_dump(mode="json") for i in insumos],
    )
    return (
        JsonOrdenReparacionRepository(tmp_path / "ordenes"),
        JsonCatalogosRepository(tmp_path / "catalogs"),
    )


def _consumir(orden, repos, utilizado, previstos=PREVISTOS, insumos=None):
    ordenes_repo, catalogos_repo = repos
    orden = _reservar(orden, insumos, previstos=previstos)
    orden = ejecutar_detalle(
        orden, detalle_id="DET-001", usuario=TECNICO, fecha=t(70)
    )
    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal(utilizado))
        ],
        usuario=TECNICO,
        fecha=t(145),
    )
    return aplicar_movimientos_inventario(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        fecha=t(146),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )


def test_al_consumir_con_override_el_stock_fisico_pasa_a_negativo(tmp_path):
    insumos = _insumos(a="0")
    repos = _con_repos(tmp_path, insumos)
    orden = _seleccionar(_en_toma(_habilitada_por_override()), "DET-001")

    _consumir(orden, repos, "1", insumos=insumos)

    assert repos[1].obtener_insumo("INS-001").stock_fisico == Decimal("-1")


def test_la_liberacion_de_reserva_no_descuenta_stock(tmp_path):
    previstos = [
        TipoReparacionInsumos(
            tipo_reparacion_id="TREP-001",
            insumo_id="INS-001",
            cantidad=Decimal("2"),
        )
    ]
    insumos = _insumos(a="0")
    repos = _con_repos(tmp_path, insumos)
    orden = _seleccionar(_en_toma(_habilitada_por_override()), "DET-001")

    orden = _consumir(orden, repos, "1", previstos=previstos, insumos=insumos)

    tipos = sorted(
        (m.tipo.value, m.cantidad)
        for m in orden.movimientos_insumo
        if m.tipo is not TipoMovimientoInsumo.RESERVA
    )
    assert tipos == [
        ("CONSUMO", Decimal("1")),
        ("LIBERACION_RESERVA", Decimal("1")),
    ]
    # Reservado 2, usado 1: solo el CONSUMO baja el stock fisico (-1, no -2).
    assert repos[1].obtener_insumo("INS-001").stock_fisico == Decimal("-1")


def test_sin_override_el_consumo_no_puede_dejar_stock_negativo(tmp_path):
    """El stock se agota por otra via antes de 210: sin override se rechaza."""
    insumos = _insumos(a="1")
    repos = _con_repos(tmp_path, insumos)
    orden = _seleccionar(
        _en_toma(
            habilitar_orden(flujo_mvp.orden_con_factibilidad(), fecha=t(20))
        ),
        "DET-001",
    )
    orden = _reservar(orden, insumos)
    orden = ejecutar_detalle(
        orden, detalle_id="DET-001", usuario=TECNICO, fecha=t(70)
    )
    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
        ],
        usuario=TECNICO,
        fecha=t(145),
    )
    repos[1].actualizar_stock_insumo("INS-001", Decimal("0"))  # se agoto

    with pytest.raises(PrecondicionInvalidaError, match="stock"):
        aplicar_movimientos_inventario(
            orden,
            ejecucion_id=orden.ejecuciones[0].id,
            fecha=t(146),
            ordenes_repo=repos[0],
            catalogos_repo=repos[1],
        )
    assert repos[1].obtener_insumo("INS-001").stock_fisico == Decimal("0")


def test_el_override_de_un_detalle_no_habilita_negativo_para_otro(tmp_path):
    """DET-A con override; DET-B (sin override) no puede ir a negativo."""
    insumos = _insumos(a="0", b="1")
    orden, _ = _validar(
        _con_detalles(TIPO_BATERIA, TIPO_PANTALLA), insumos
    )  # A bloqueado, B trabajable
    assert orden.current_process == "PROC-REP-090"
    assert tiene_override_factibilidad(orden, "DET-001") is False

    en_100 = _bloqueada("0", "0", TIPO_BATERIA, TIPO_PANTALLA)
    con_override = _forzar(en_100, "DET-001")
    assert tiene_override_factibilidad(con_override, "DET-001") is True
    assert tiene_override_factibilidad(con_override, "DET-002") is False

    # 185 de B (sin override) con stock insuficiente: error aunque A tenga.
    con_b_sin_stock = habilitar_orden(con_override, fecha=t(21))
    b = con_b_sin_stock.reparaciones_detail[1]
    assert b.condicion is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    forzado_b = con_b_sin_stock.model_copy(deep=True)
    forzado_b.reparaciones_detail[
        1
    ].condicion = (
        CondicionReparacionDetail.SIN_BLOQUEO
    )  # (aislar la politica de stock del guard de condicion)
    seleccion = _seleccionar(_en_toma(forzado_b), "DET-002")
    with pytest.raises(RecursoNoDisponibleError):
        _reservar(
            seleccion, _insumos(a="0", b="0", c="0"), detalle_id="DET-002"
        )


# --- Acciones y progreso ---


def test_en_100_se_publican_esperar_y_un_override_por_detalle_bloqueado():
    orden = _bloqueada("0", "0", TIPO_BATERIA, TIPO_PANTALLA)

    acciones = acciones_disponibles(orden)

    esperar = acciones[0]
    assert (esperar.codigo, esperar.roles, esperar.requiere_actor) == (
        "ESPERAR_RECURSOS",
        (),
        False,
    )
    overrides = [a for a in acciones if a.codigo == "OVERRIDE_RECURSOS"]
    assert [(a.detalle_id, a.roles) for a in overrides] == [
        ("DET-001", (RolUsuario.COORDINADOR_RMA,)),
        ("DET-002", (RolUsuario.COORDINADOR_RMA,)),
    ]
    for ausente in (
        "DEFINIR_REPARACION",
        "ENCOLAR",
        "TOMAR",
        "INICIAR_DETALLE",
    ):
        assert ausente not in [a.codigo for a in acciones]


def test_en_120_no_se_publica_el_override():
    en_120 = registrar_espera_recursos(_bloqueada(), fecha=t(20))
    codigos = [a.codigo for a in acciones_disponibles(en_120)]
    assert "REVALIDAR_RECURSOS" in codigos
    assert "OVERRIDE_RECURSOS" not in codigos


def test_el_progreso_muestra_130_solo_con_evidencia_de_override():
    sin = [p.process_id for p in progreso(_bloqueada())]
    assert "PROC-REP-130" not in sin and "PROC-REP-100" in sin

    con = progreso(habilitar_orden(_forzar(_bloqueada()), fecha=t(21)))
    ids = [p.process_id for p in con]
    i = ids.index("PROC-REP-090")
    assert ids[i : i + 5] == [
        "PROC-REP-090",
        "PROC-REP-100",
        "PROC-REP-110",
        "PROC-REP-120",
        "PROC-REP-130",
    ]
    alcanzados = {p.process_id for p in con if p.alcanzado}
    assert {"PROC-REP-110", "PROC-REP-130", "PROC-REP-140"} <= alcanzados
    assert "PROC-REP-120" not in alcanzados
