"""Persistencia JSON: contratos, round-trip y fallos de infraestructura.

Cada test usa su propio ``tmp_path``: nunca se escribe sobre
``app/backend/data/``.
"""

from decimal import Decimal

import pytest

from app.domain.models import (
    EstacionTrabajo,
    EstadoPago,
    Insumo,
    OrdenReparacion,
    ResumenPago,
    RolUsuario,
    TipoReparacion,
    TipoReparacionEstacion,
    TipoReparacionInsumos,
    Usuario,
)
from app.repositories import (
    CatalogosRepository,
    EntidadPersistidaNoEncontradaError,
    OrdenReparacionRepository,
    PersistenciaError,
)
from app.storage import JsonCatalogosRepository, JsonOrdenReparacionRepository
from app.storage.json.base import escribir_json_atomico
from tests.fixtures import flujo_mvp
from tests.fixtures.catalogos_mvp import (
    COMPATIBILIDADES,
    ESTACION,
    INSUMO_BATERIA,
    INSUMOS_PREVISTOS,
    TIPO_BATERIA,
)


@pytest.fixture
def repo_ordenes(tmp_path) -> JsonOrdenReparacionRepository:
    return JsonOrdenReparacionRepository(tmp_path / "ordenes")


@pytest.fixture
def repo_catalogos(tmp_path) -> JsonCatalogosRepository:
    return JsonCatalogosRepository(tmp_path / "catalogs")


# --- Conformidad con los contratos ---


def test_las_implementaciones_cumplen_los_contratos(
    repo_ordenes,
    repo_catalogos,
):
    assert isinstance(repo_ordenes, OrdenReparacionRepository)
    assert isinstance(repo_catalogos, CatalogosRepository)


# 1) 2) 3) Guardar, cargar y round-trip exacto.


def test_guardar_y_cargar_una_orden(repo_ordenes):
    orden = flujo_mvp.orden_creada()

    repo_ordenes.guardar(orden)

    assert (repo_ordenes.directorio / f"{orden.id}.json").is_file()


def test_el_round_trip_es_exacto(repo_ordenes):
    orden = flujo_mvp.orden_entregada()

    repo_ordenes.guardar(orden)
    recuperada = repo_ordenes.obtener(orden.id)

    assert recuperada == orden
    assert recuperada.model_dump(mode="json") == orden.model_dump(mode="json")


def test_el_round_trip_conserva_tipos_y_trazabilidad(repo_ordenes):
    orden = flujo_mvp.orden_entregada()

    repo_ordenes.guardar(orden)
    recuperada = repo_ordenes.obtener(orden.id)

    assert isinstance(recuperada.total, Decimal)
    assert recuperada.total == Decimal("80000")
    assert recuperada.created_at == orden.created_at
    assert [p.process_id for p in recuperada.historial] == [
        p.process_id for p in orden.historial
    ]
    assert recuperada.current_process == "EVT-REP-999"


# 4) Actualizar reemplaza el archivo, no duplica.


def test_guardar_dos_veces_reemplaza_la_orden(repo_ordenes):
    orden = flujo_mvp.orden_creada()
    repo_ordenes.guardar(orden)

    avanzada = flujo_mvp.orden_con_detalle()
    repo_ordenes.guardar(avanzada)

    archivos = list(repo_ordenes.directorio.glob("*.json"))
    assert len(archivos) == 1

    recuperada = repo_ordenes.obtener(orden.id)
    assert len(recuperada.reparaciones_detail) == 1
    assert recuperada.total == Decimal("80000")


# 5) Listar.


def test_listar_devuelve_todas_las_ordenes(repo_ordenes):
    assert repo_ordenes.listar() == []

    primera = flujo_mvp.orden_creada()
    segunda = primera.model_copy(deep=True, update={"id": "OR-002"})
    repo_ordenes.guardar(primera)
    repo_ordenes.guardar(segunda)

    listadas = repo_ordenes.listar()

    assert [orden.id for orden in listadas] == ["OR-001", "OR-002"]


# 6) Orden inexistente.


def test_orden_inexistente_lanza_no_encontrada(repo_ordenes):
    with pytest.raises(EntidadPersistidaNoEncontradaError):
        repo_ordenes.obtener("OR-INEXISTENTE")


# 7) Catalogos: guardar y cargar cada uno.


def _sembrar_catalogos(repo: JsonCatalogosRepository) -> None:
    """Escribe los seis catalogos con los datos de prueba."""
    datos = {
        "tipos_reparacion.json": [TIPO_BATERIA],
        "insumos.json": [INSUMO_BATERIA],
        "tipo_reparacion_insumos.json": INSUMOS_PREVISTOS,
        "estaciones.json": [ESTACION],
        "tipo_reparacion_estaciones.json": COMPATIBILIDADES,
        "usuarios.json": [
            Usuario(id="TECH-001", nombre="Tecnico", rol=RolUsuario.TECNICO)
        ],
    }
    for archivo, entidades in datos.items():
        escribir_json_atomico(
            repo.directorio / archivo,
            [entidad.model_dump(mode="json") for entidad in entidades],
        )


def test_guardar_y_cargar_cada_catalogo(repo_catalogos):
    _sembrar_catalogos(repo_catalogos)

    assert repo_catalogos.obtener_tipo_reparacion("TREP-001") == TIPO_BATERIA
    assert repo_catalogos.obtener_insumo("INS-001") == INSUMO_BATERIA
    assert repo_catalogos.obtener_estacion("EST-001") == ESTACION
    assert repo_catalogos.obtener_usuario("TECH-001").rol is RolUsuario.TECNICO

    assert len(repo_catalogos.listar_tipos_reparacion()) == 1
    assert len(repo_catalogos.listar_insumos()) == 1
    assert len(repo_catalogos.listar_tipo_reparacion_insumos()) == 1
    assert len(repo_catalogos.listar_estaciones()) == 1
    assert len(repo_catalogos.listar_tipo_reparacion_estaciones()) == 1
    assert len(repo_catalogos.listar_usuarios()) == 1


def test_un_catalogo_ausente_esta_vacio(repo_catalogos):
    assert repo_catalogos.listar_insumos() == []
    assert repo_catalogos.listar_usuarios() == []


def test_los_tipos_decimal_sobreviven_al_catalogo(repo_catalogos):
    _sembrar_catalogos(repo_catalogos)

    insumo = repo_catalogos.obtener_insumo("INS-001")
    tipo = repo_catalogos.obtener_tipo_reparacion("TREP-001")

    assert isinstance(insumo.stock_fisico, Decimal)
    assert insumo.stock_fisico == Decimal("2")
    assert tipo.precio == Decimal("80000")


def test_actualizar_stock_persiste_el_nuevo_valor(repo_catalogos):
    _sembrar_catalogos(repo_catalogos)

    actualizado = repo_catalogos.actualizar_stock_insumo(
        "INS-001", Decimal("1")
    )

    assert actualizado.stock_fisico == Decimal("1")
    assert repo_catalogos.obtener_insumo("INS-001").stock_fisico == Decimal(
        "1"
    )
    # No se duplican filas.
    assert len(repo_catalogos.listar_insumos()) == 1


def test_actualizar_stock_conserva_el_resto_del_insumo(repo_catalogos):
    _sembrar_catalogos(repo_catalogos)

    repo_catalogos.actualizar_stock_insumo("INS-001", Decimal("0"))
    insumo = repo_catalogos.obtener_insumo("INS-001")

    assert insumo.codigo == "BAT-IP14"
    assert insumo.nombre == "Bateria iPhone 14"
    assert insumo.activo is True


# 8) Entidad de catalogo inexistente.


@pytest.mark.parametrize(
    ("metodo", "identificador"),
    [
        ("obtener_tipo_reparacion", "TREP-INEXISTENTE"),
        ("obtener_insumo", "INS-INEXISTENTE"),
        ("obtener_estacion", "EST-INEXISTENTE"),
        ("obtener_usuario", "USR-INEXISTENTE"),
    ],
)
def test_entidad_de_catalogo_inexistente(
    repo_catalogos,
    metodo,
    identificador,
):
    _sembrar_catalogos(repo_catalogos)

    with pytest.raises(EntidadPersistidaNoEncontradaError):
        getattr(repo_catalogos, metodo)(identificador)


def test_actualizar_stock_de_un_insumo_inexistente(repo_catalogos):
    _sembrar_catalogos(repo_catalogos)

    with pytest.raises(EntidadPersistidaNoEncontradaError):
        repo_catalogos.actualizar_stock_insumo("INS-X", Decimal("1"))


# 9) JSON invalido.


def test_una_orden_con_json_invalido_lanza_persistencia(repo_ordenes):
    ruta = repo_ordenes.directorio / "OR-ROTA.json"
    ruta.write_text("{ esto no es json", encoding="utf-8")

    with pytest.raises(PersistenciaError):
        repo_ordenes.obtener("OR-ROTA")


def test_una_orden_que_no_respeta_el_modelo_lanza_persistencia(repo_ordenes):
    ruta = repo_ordenes.directorio / "OR-RARA.json"
    ruta.write_text('{"id": "OR-RARA"}', encoding="utf-8")

    with pytest.raises(PersistenciaError):
        repo_ordenes.obtener("OR-RARA")


def test_listar_propaga_el_error_de_una_orden_corrupta(repo_ordenes):
    repo_ordenes.guardar(flujo_mvp.orden_creada())
    (repo_ordenes.directorio / "OR-ROTA.json").write_text(
        "no json", encoding="utf-8"
    )

    with pytest.raises(PersistenciaError):
        repo_ordenes.listar()


def test_un_catalogo_con_json_invalido_lanza_persistencia(repo_catalogos):
    (repo_catalogos.directorio / "insumos.json").write_text(
        "[[[", encoding="utf-8"
    )

    with pytest.raises(PersistenciaError):
        repo_catalogos.listar_insumos()


def test_un_catalogo_que_no_es_array_lanza_persistencia(repo_catalogos):
    (repo_catalogos.directorio / "insumos.json").write_text(
        '{"id": "INS-001"}', encoding="utf-8"
    )

    with pytest.raises(PersistenciaError):
        repo_catalogos.listar_insumos()


def test_un_catalogo_con_filas_invalidas_lanza_persistencia(repo_catalogos):
    (repo_catalogos.directorio / "insumos.json").write_text(
        '[{"id": "INS-001"}]', encoding="utf-8"
    )

    with pytest.raises(PersistenciaError):
        repo_catalogos.listar_insumos()


# 10) La escritura atomica no deja temporales.


def test_la_escritura_atomica_no_deja_temporales(repo_ordenes):
    repo_ordenes.guardar(flujo_mvp.orden_entregada())

    archivos = sorted(p.name for p in repo_ordenes.directorio.iterdir())

    assert archivos == ["OR-001.json"]
    assert not list(repo_ordenes.directorio.glob("*.tmp"))
    assert not list(repo_ordenes.directorio.glob(".*"))


def test_reescribir_muchas_veces_no_acumula_archivos(repo_ordenes):
    for _ in range(5):
        repo_ordenes.guardar(flujo_mvp.orden_creada())

    assert len(list(repo_ordenes.directorio.iterdir())) == 1


def test_la_escritura_atomica_crea_el_directorio(tmp_path):
    destino = tmp_path / "nueva" / "carpeta" / "datos.json"

    escribir_json_atomico(destino, {"ok": True})

    assert destino.is_file()


# Los catalogos DEMO versionados siguen siendo legibles.


def test_los_catalogos_demo_del_repositorio_son_validos():
    from pathlib import Path

    directorio = Path(__file__).parent.parent / "data" / "catalogs"
    repo = JsonCatalogosRepository(directorio)

    assert repo.obtener_tipo_reparacion("TR-001").precio == Decimal("80000")
    assert repo.obtener_insumo("INS-001").stock_fisico == Decimal("6")
    assert {u.id for u in repo.listar_usuarios()} == {
        "RECEP-001",
        "COORD-001",
        "TECH-001",
        "ADMIN-001",
    }
    assert repo.listar_tipo_reparacion_insumos()[0].cantidad == Decimal("1")
    assert repo.listar_tipo_reparacion_estaciones()[0].estacion_id == "EST-001"


def test_los_catalogos_demo_no_se_modifican_al_leerlos():
    """Leer nunca escribe: los archivos versionados quedan intactos."""
    from pathlib import Path

    directorio = Path(__file__).parent.parent / "data" / "catalogs"
    antes = {p.name: p.read_bytes() for p in directorio.glob("*.json")}

    repo = JsonCatalogosRepository(directorio)
    repo.listar_insumos()
    repo.listar_usuarios()

    despues = {p.name: p.read_bytes() for p in directorio.glob("*.json")}
    assert despues == antes


# Tipos del catalogo no cubiertos arriba.


def test_los_modelos_de_catalogo_se_reconstruyen_completos(repo_catalogos):
    _sembrar_catalogos(repo_catalogos)

    assert isinstance(
        repo_catalogos.listar_tipo_reparacion_insumos()[0],
        TipoReparacionInsumos,
    )
    assert isinstance(
        repo_catalogos.listar_tipo_reparacion_estaciones()[0],
        TipoReparacionEstacion,
    )
    assert isinstance(repo_catalogos.listar_estaciones()[0], EstacionTrabajo)
    assert isinstance(repo_catalogos.listar_insumos()[0], Insumo)
    assert isinstance(
        repo_catalogos.listar_tipos_reparacion()[0], TipoReparacion
    )
    assert isinstance(repo_catalogos.listar_usuarios()[0], Usuario)


def test_una_orden_guardada_es_json_legible_a_mano(repo_ordenes):
    """El archivo debe poder inspeccionarse sin herramientas."""
    import json

    orden = flujo_mvp.orden_entregada()
    repo_ordenes.guardar(orden)

    crudo = json.loads(
        (repo_ordenes.directorio / "OR-001.json").read_text(encoding="utf-8")
    )

    assert crudo["estado_workflow"] == "ENTREGADA"
    assert crudo["current_process"] == "EVT-REP-999"
    assert crudo["cliente"]["id"] == "CLI-001"
    assert OrdenReparacion.model_validate(crudo) == orden


# --- Los campos derivados no se persisten ---------------------------


def _json_crudo(repo: JsonOrdenReparacionRepository, orden_id: str) -> dict:
    """Contenido del archivo, sin pasar por el modelo."""
    import json

    ruta = repo.directorio / f"{orden_id}.json"
    return json.loads(ruta.read_text(encoding="utf-8"))


DERIVADOS_DE_LA_ORDEN = ("total", "saldo", "estado_pago", "puntaje_total")


@pytest.mark.parametrize("derivado", DERIVADOS_DE_LA_ORDEN)
def test_el_json_no_guarda_los_derivados_de_la_orden(repo_ordenes, derivado):
    repo_ordenes.guardar(flujo_mvp.orden_entregada())

    crudo = _json_crudo(repo_ordenes, "OR-001")

    assert derivado not in crudo


def test_el_json_no_guarda_el_pagado_del_resumen(repo_ordenes):
    repo_ordenes.guardar(flujo_mvp.orden_entregada())

    crudo = _json_crudo(repo_ordenes, "OR-001")

    assert "pagado" not in crudo["resumen_pago"]
    # Los pagos, que si son fuente de verdad, estan.
    assert len(crudo["resumen_pago"]["pagos"]) == 1
    assert crudo["resumen_pago"]["pagos"][0]["monto"] == "80000"


def test_los_derivados_se_recalculan_al_cargar(repo_ordenes):
    orden = flujo_mvp.orden_entregada()
    repo_ordenes.guardar(orden)

    recuperada = repo_ordenes.obtener("OR-001")

    assert recuperada.total == Decimal("80000")
    assert recuperada.saldo == Decimal("0")
    assert recuperada.estado_pago is EstadoPago.PAGADO
    assert recuperada.puntaje_total == 10
    assert recuperada.resumen_pago.pagado == Decimal("80000")


def test_el_json_conserva_los_campos_almacenados(repo_ordenes):
    """Excluir derivados no debe llevarse nada que si sea fuente de verdad."""
    orden = flujo_mvp.orden_entregada()
    repo_ordenes.guardar(orden)

    crudo = _json_crudo(repo_ordenes, "OR-001")

    for campo in OrdenReparacion.model_fields:
        assert campo in crudo, campo


def test_ningun_computado_del_modelo_llega_al_json(repo_ordenes):
    """Guarda contra que un computed_field nuevo se cuele sin querer."""
    repo_ordenes.guardar(flujo_mvp.orden_entregada())

    crudo = _json_crudo(repo_ordenes, "OR-001")

    for computado in OrdenReparacion.model_computed_fields:
        assert computado not in crudo, computado
    for computado in ResumenPago.model_computed_fields:
        assert computado not in crudo["resumen_pago"], computado


def test_una_orden_a_medio_flujo_tampoco_guarda_derivados(repo_ordenes):
    repo_ordenes.guardar(flujo_mvp.orden_reparacion_lista())

    crudo = _json_crudo(repo_ordenes, "OR-001")
    recuperada = repo_ordenes.obtener("OR-001")

    assert "saldo" not in crudo
    assert recuperada.saldo == Decimal("80000")
    assert recuperada.estado_pago is EstadoPago.PENDIENTE


# --- Compatibilidad con JSON anterior a Slice 2 (RT_INTERNO) ------------


def test_una_orden_hp1_anterior_a_referencia_rt_sigue_cargando(repo_ordenes):
    """``referencia_rt`` es aditivo: un JSON de antes de Slice 2 no lo tiene.

    ``cliente`` tampoco cambio para CLIENTE_EXTERNO -sigue viniendo
    poblado-, asi que una Orden HP1 persistida antes de que ``cliente``
    se volviera opcional debe seguir cargando identica.
    """
    import json

    orden = flujo_mvp.orden_entregada()
    repo_ordenes.guardar(orden)

    crudo = _json_crudo(repo_ordenes, "OR-001")
    del crudo["referencia_rt"]
    (repo_ordenes.directorio / "OR-001.json").write_text(
        json.dumps(crudo), encoding="utf-8"
    )

    recuperada = repo_ordenes.obtener("OR-001")

    assert recuperada.referencia_rt is None
    assert recuperada.cliente is not None
    assert recuperada.cliente.id == "CLI-001"
    assert recuperada == orden
