"""Disponibilidad de stock mirando TODAS las Ordenes.

Semantica acordada:

    RESERVA             -> compromete, NO toca stock_fisico
    CONSUMO             -> reduce stock_fisico, cierra la reserva
    LIBERACION_RESERVA  -> NO toca stock_fisico, cierra la reserva

Los insumos que una Orden solo PREVE usar no comprometen nada: el stock
recien se compromete en PROC-REP-185.
"""

from decimal import Decimal

import pytest

from app.domain.models import InsumoUtilizado
from app.services import (
    RecursoNoDisponibleError,
    aplicar_movimientos_inventario,
    cantidad_reservada_global,
    cargar_reservas_externas,
    generar_movimientos_inventario,
    inventario_aplicado,
    registrar_ejecucion_completada,
    reservar_insumos_e_iniciar_ejecucion,
    reservas_activas_globales,
    reservas_externas_a,
    stock_disponible_global,
    stock_disponible_por_insumo,
    validar_factibilidad_detalles,
)
from app.storage import JsonCatalogosRepository, JsonOrdenReparacionRepository
from app.storage.json.base import escribir_json_atomico
from tests.fixtures import flujo_mvp
from tests.fixtures.catalogos_mvp import (
    INSUMO_BATERIA,
    INSUMOS_PREVISTOS,
    TECNICO,
    t,
)

DETALLE_ID = flujo_mvp.DETALLE_ID
UNA_UNIDAD = INSUMO_BATERIA.model_copy(update={"stock_fisico": Decimal("1")})


def _segunda_orden_tomada():
    """Otra Orden, en el mismo punto del flujo, con otro ID."""
    return flujo_mvp.orden_tomada().model_copy(
        deep=True, update={"id": "OR-002"}
    )


@pytest.fixture
def repos(tmp_path):
    """Repositories JSON aislados, con el insumo en una unidad."""
    ordenes = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    catalogos = JsonCatalogosRepository(tmp_path / "catalogs")
    escribir_json_atomico(
        catalogos.directorio / "insumos.json",
        [UNA_UNIDAD.model_dump(mode="json")],
    )
    return ordenes, catalogos


# --- Caso A: prever no reserva --------------------------------------


def test_caso_a_dos_ordenes_factibles_no_reservan_nada():
    """stock 1, dos Ordenes que lo necesitan, ninguna inicio Ejecucion."""
    or_001 = flujo_mvp.orden_con_detalle()
    or_002 = or_001.model_copy(deep=True, update={"id": "OR-002"})
    ordenes = [or_001, or_002]

    or_001, factible_1 = validar_factibilidad_detalles(
        or_001,
        insumos=[UNA_UNIDAD],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(15),
        reservas_externas=reservas_externas_a("OR-001", ordenes),
    )
    or_002, factible_2 = validar_factibilidad_detalles(
        or_002,
        insumos=[UNA_UNIDAD],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(15),
        reservas_externas=reservas_externas_a("OR-002", ordenes),
    )

    # Las dos son factibles: la demanda futura no compromete stock.
    assert factible_1 is True
    assert factible_2 is True

    assert reservas_activas_globales(ordenes) == {}
    assert cantidad_reservada_global("INS-001", ordenes) == Decimal("0")
    assert stock_disponible_global(UNA_UNIDAD, ordenes) == Decimal("1")


# --- Caso B: la reserva real si compromete --------------------------


def test_caso_b_una_reserva_deja_el_stock_en_cero():
    or_001 = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=[UNA_UNIDAD],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )
    or_002 = _segunda_orden_tomada()
    ordenes = [or_001, or_002]

    assert cantidad_reservada_global("INS-001", ordenes) == Decimal("1")
    assert stock_disponible_global(UNA_UNIDAD, ordenes) == Decimal("0")
    # El stock fisico no se movio: la unidad sigue en el deposito.
    assert UNA_UNIDAD.stock_fisico == Decimal("1")


def test_caso_b_la_segunda_orden_no_puede_reservar():
    or_001 = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=[UNA_UNIDAD],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )
    or_002 = _segunda_orden_tomada()
    ordenes = [or_001, or_002]

    with pytest.raises(RecursoNoDisponibleError):
        reservar_insumos_e_iniciar_ejecucion(
            or_002,
            detalle_id=DETALLE_ID,
            usuario=TECNICO,
            insumos=[UNA_UNIDAD],
            insumos_previstos=INSUMOS_PREVISTOS,
            fecha=t(66),
            reservas_externas=reservas_externas_a("OR-002", ordenes),
        )

    # Sin reserva parcial ni Ejecucion abierta.
    assert or_002.movimientos_insumo == []
    assert or_002.ejecuciones == []


def test_caso_b_la_factibilidad_ajena_ya_refleja_el_faltante():
    or_001 = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=[UNA_UNIDAD],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )
    or_002 = flujo_mvp.orden_con_detalle().model_copy(
        deep=True, update={"id": "OR-002"}
    )
    ordenes = [or_001, or_002]

    _, factible = validar_factibilidad_detalles(
        or_002,
        insumos=[UNA_UNIDAD],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(70),
        reservas_externas=reservas_externas_a("OR-002", ordenes),
    )

    assert factible is False


def test_una_orden_no_se_cuenta_sus_propias_reservas_como_ajenas():
    or_001 = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=[UNA_UNIDAD],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )

    assert reservas_externas_a("OR-001", [or_001]) == {}
    assert cantidad_reservada_global("INS-001", [or_001]) == Decimal("1")


# --- Caso C: el consumo baja el stock fisico ------------------------


def test_caso_c_tras_el_consumo_todo_queda_en_cero(repos):
    ordenes_repo, catalogos_repo = repos

    orden = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=[UNA_UNIDAD],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
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
    ordenes_repo.guardar(orden)

    orden = aplicar_movimientos_inventario(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        fecha=t(146),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )

    insumo = catalogos_repo.obtener_insumo("INS-001")
    ordenes = ordenes_repo.listar()

    assert insumo.stock_fisico == Decimal("0")
    assert cantidad_reservada_global("INS-001", ordenes) == Decimal("0")
    assert stock_disponible_global(insumo, ordenes) == Decimal("0")


# --- Caso D: consumo parcial mas liberacion -------------------------


def test_caso_d_consumo_parcial_y_liberacion(tmp_path):
    ordenes_repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    catalogos_repo = JsonCatalogosRepository(tmp_path / "catalogs")

    dos_unidades = INSUMO_BATERIA.model_copy(
        update={"stock_fisico": Decimal("2")}
    )
    escribir_json_atomico(
        catalogos_repo.directorio / "insumos.json",
        [dos_unidades.model_dump(mode="json")],
    )
    previstos_dos = [
        INSUMOS_PREVISTOS[0].model_copy(update={"cantidad": Decimal("2")})
    ]

    orden = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=[dos_unidades],
        insumos_previstos=previstos_dos,
        fecha=t(65),
    )
    assert orden.movimientos_insumo[0].cantidad == Decimal("2")

    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
        ],
        usuario=TECNICO,
        fecha=t(145),
    )
    orden = aplicar_movimientos_inventario(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        fecha=t(146),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )

    tipos = [m.tipo.value for m in orden.movimientos_insumo]
    assert tipos == ["RESERVA", "CONSUMO", "LIBERACION_RESERVA"]

    insumo = catalogos_repo.obtener_insumo("INS-001")
    ordenes = ordenes_repo.listar()

    # Solo el CONSUMO bajo el stock fisico: 2 - 1 = 1.
    assert insumo.stock_fisico == Decimal("1")
    assert cantidad_reservada_global("INS-001", ordenes) == Decimal("0")
    assert stock_disponible_global(insumo, ordenes) == Decimal("1")


# --- Coordinador de PROC-REP-210 ------------------------------------


def test_aplicar_movimientos_guarda_orden_y_catalogo(repos):
    ordenes_repo, catalogos_repo = repos

    orden = flujo_mvp.orden_con_ejecucion_completada()
    ordenes_repo.guardar(orden)

    aplicada = aplicar_movimientos_inventario(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        fecha=t(146),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )

    # La Orden persistida ya tiene el consumo.
    persistida = ordenes_repo.obtener(orden.id)
    assert persistida == aplicada
    assert len(persistida.movimientos_insumo) == 2
    assert catalogos_repo.obtener_insumo("INS-001").stock_fisico == Decimal(
        "0"
    )


def test_aplicar_movimientos_no_muta_la_orden_recibida(repos):
    ordenes_repo, catalogos_repo = repos
    original = flujo_mvp.orden_con_ejecucion_completada()
    antes = original.model_dump(mode="json")

    aplicar_movimientos_inventario(
        original,
        ejecucion_id=original.ejecuciones[0].id,
        fecha=t(146),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )

    assert original.model_dump(mode="json") == antes
    assert len(original.movimientos_insumo) == 1


def test_aplicar_movimientos_registra_el_faltante_si_el_stock_no_alcanza(
    tmp_path,
):
    """Decision E3: el consumo de una reserva propia no se bloquea.

    Antes, con el stock fisico en 0, PROC-REP-210 se rechazaba y no
    escribia nada: la Orden quedaba con la Ejecucion y la reserva
    abiertas. Ahora el CONSUMO se registra, el stock queda negativo y el
    faltante fisico queda trazado en el paso 210.
    """
    ordenes_repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    catalogos_repo = JsonCatalogosRepository(tmp_path / "catalogs")
    sin_stock = INSUMO_BATERIA.model_copy(
        update={"stock_fisico": Decimal("0")}
    )
    escribir_json_atomico(
        catalogos_repo.directorio / "insumos.json",
        [sin_stock.model_dump(mode="json")],
    )

    orden = flujo_mvp.orden_con_ejecucion_completada()

    aplicada = aplicar_movimientos_inventario(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        fecha=t(146),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )

    assert ordenes_repo.obtener(orden.id) == aplicada
    assert catalogos_repo.obtener_insumo("INS-001").stock_fisico == Decimal(
        "-1"
    )
    assert "Faltante fisico" in aplicada.historial[-1].observacion


# --- Consultas auxiliares -------------------------------------------


def test_cargar_reservas_externas_lee_del_repository(repos):
    ordenes_repo, _ = repos

    or_001 = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=[UNA_UNIDAD],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )
    ordenes_repo.guardar(or_001)

    assert cargar_reservas_externas("OR-002", ordenes_repo) == {
        "INS-001": Decimal("1")
    }
    assert cargar_reservas_externas("OR-001", ordenes_repo) == {}


def test_stock_disponible_por_insumo_resume_el_catalogo():
    or_001 = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=[UNA_UNIDAD],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )

    resumen = stock_disponible_por_insumo([UNA_UNIDAD], [or_001])

    assert resumen == {"INS-001": Decimal("0")}


def test_sin_ordenes_el_disponible_es_el_stock_fisico():
    assert stock_disponible_global(UNA_UNIDAD, []) == Decimal("1")
    assert reservas_activas_globales([]) == {}


def test_las_reservas_de_varias_ordenes_se_suman():
    dos_unidades = INSUMO_BATERIA.model_copy(
        update={"stock_fisico": Decimal("2")}
    )

    or_001 = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=[dos_unidades],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )
    or_002 = reservar_insumos_e_iniciar_ejecucion(
        _segunda_orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=[dos_unidades],
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(66),
        reservas_externas={"INS-001": Decimal("1")},
    )
    ordenes = [or_001, or_002]

    assert cantidad_reservada_global("INS-001", ordenes) == Decimal("2")
    assert stock_disponible_global(dos_unidades, ordenes) == Decimal("0")


# --- Idempotencia de PROC-REP-210 -----------------------------------


def test_reaplicar_210_no_duplica_el_consumo(repos):
    """stock 2, se usa 1: reintentar no vuelve a descontar."""
    ordenes_repo, catalogos_repo = repos
    dos_unidades = INSUMO_BATERIA.model_copy(
        update={"stock_fisico": Decimal("2")}
    )
    escribir_json_atomico(
        catalogos_repo.directorio / "insumos.json",
        [dos_unidades.model_dump(mode="json")],
    )

    orden = flujo_mvp.orden_con_ejecucion_completada()
    ejecucion_id = orden.ejecuciones[0].id

    primera = aplicar_movimientos_inventario(
        orden,
        ejecucion_id=ejecucion_id,
        fecha=t(146),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )

    assert catalogos_repo.obtener_insumo("INS-001").stock_fisico == Decimal(
        "1"
    )
    assert _tipos(primera) == ["RESERVA", "CONSUMO"]

    segunda = aplicar_movimientos_inventario(
        primera,
        ejecucion_id=ejecucion_id,
        fecha=t(200),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )

    # Ni stock ni movimientos se movieron.
    assert catalogos_repo.obtener_insumo("INS-001").stock_fisico == Decimal(
        "1"
    )
    assert _tipos(segunda) == ["RESERVA", "CONSUMO"]
    assert segunda == primera


def test_reaplicar_210_no_duplica_consumo_ni_liberacion(repos):
    """RESERVA 2 -> CONSUMO 1 + LIBERACION 1: reintentar no agrega nada."""
    ordenes_repo, catalogos_repo = repos
    dos_unidades = INSUMO_BATERIA.model_copy(
        update={"stock_fisico": Decimal("2")}
    )
    escribir_json_atomico(
        catalogos_repo.directorio / "insumos.json",
        [dos_unidades.model_dump(mode="json")],
    )
    previstos_dos = [
        INSUMOS_PREVISTOS[0].model_copy(update={"cantidad": Decimal("2")})
    ]

    orden = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=[dos_unidades],
        insumos_previstos=previstos_dos,
        fecha=t(65),
    )
    ejecucion_id = orden.ejecuciones[0].id
    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=ejecucion_id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
        ],
        usuario=TECNICO,
        fecha=t(145),
    )

    primera = aplicar_movimientos_inventario(
        orden,
        ejecucion_id=ejecucion_id,
        fecha=t(146),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )

    assert _tipos(primera) == ["RESERVA", "CONSUMO", "LIBERACION_RESERVA"]
    assert catalogos_repo.obtener_insumo("INS-001").stock_fisico == Decimal(
        "1"
    )

    segunda = aplicar_movimientos_inventario(
        primera,
        ejecucion_id=ejecucion_id,
        fecha=t(200),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )

    assert _tipos(segunda) == ["RESERVA", "CONSUMO", "LIBERACION_RESERVA"]
    assert catalogos_repo.obtener_insumo("INS-001").stock_fisico == Decimal(
        "1"
    )
    assert segunda == primera


def test_el_service_210_por_si_solo_es_idempotente():
    """Sin repositories: tampoco duplica movimientos ni historial."""
    orden = flujo_mvp.orden_con_inventario_conciliado()
    ejecucion_id = orden.ejecuciones[0].id

    repetida = generar_movimientos_inventario(
        orden, ejecucion_id=ejecucion_id, fecha=t(200)
    )

    assert _tipos(repetida) == ["RESERVA", "CONSUMO"]
    assert len(repetida.historial) == len(orden.historial)
    assert repetida == orden
    # Sigue devolviendo una Orden nueva, como el resto de los services.
    assert repetida is not orden


def test_inventario_aplicado_reconoce_el_estado_del_ledger():
    sin_aplicar = flujo_mvp.orden_con_ejecucion_completada()
    aplicada = flujo_mvp.orden_con_inventario_conciliado()
    ejecucion_id = sin_aplicar.ejecuciones[0].id

    assert inventario_aplicado(sin_aplicar, ejecucion_id) is False
    assert (
        inventario_aplicado(aplicada, aplicada.ejecuciones[0].id) is True
    )
    # Otra Ejecucion cualquiera no esta aplicada.
    assert inventario_aplicado(aplicada, "EJE-INEXISTENTE") is False


def test_reaplicar_210_no_reescribe_la_orden_persistida(repos):
    """El reintento no toca el disco."""
    ordenes_repo, catalogos_repo = repos

    completada = flujo_mvp.orden_con_ejecucion_completada()
    orden = aplicar_movimientos_inventario(
        completada,
        ejecucion_id=completada.ejecuciones[0].id,
        fecha=t(146),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )
    ruta = ordenes_repo.directorio / f"{orden.id}.json"
    antes = ruta.read_bytes()

    aplicar_movimientos_inventario(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        fecha=t(300),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )

    assert ruta.read_bytes() == antes


def _tipos(orden) -> list[str]:
    return [m.tipo.value for m in orden.movimientos_insumo]
