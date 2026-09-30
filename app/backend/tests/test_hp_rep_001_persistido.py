"""HP-REP-001 atravesando la persistencia real.

Complementa -no reemplaza- al E2E en memoria de
``test_hp_rep_001_services.py``. Aqui cada tramo del flujo hace el ciclo
completo:

    cargar desde JSON -> ejecutar service -> guardar en JSON

de modo que la Orden se reconstruye desde disco varias veces durante el
escenario. Si la serializacion perdiera algo -un Decimal, una fecha, el
historial-, el flujo se rompe antes de terminar.

Los catalogos tambien salen del repository, no de constantes en memoria.
"""

from decimal import Decimal

import pytest

from app.domain.models import (
    EstadoControl,
    EstadoPago,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    InsumoUtilizado,
    OrdenReparacion,
)
from app.services import (
    ResultadoEvaluacionOrden,
    aplicar_movimientos_inventario,
    aprobar_control_tecnico,
    calcular_puntaje,
    cargar_reservas_externas,
    crear_orden_cliente_externo,
    definir_prioridad,
    definir_reparacion_detail,
    ejecucion_activa,
    ejecutar_detalle,
    entregar_equipo,
    evaluar_situacion_orden,
    generar_comprobante_final,
    generar_comprobante_recepcion,
    habilitar_orden,
    hay_reservas_activas,
    ingresar_a_cola,
    marcar_reparacion_lista,
    notificar_cliente,
    registrar_ejecucion_completada,
    registrar_pago,
    registrar_saldo_pendiente,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
    toma_activa,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_condicion_entrega,
    validar_estacion_trabajo,
    validar_factibilidad_detalles,
)
from app.storage import JsonCatalogosRepository, JsonOrdenReparacionRepository
from app.storage.json.base import escribir_json_atomico
from tests.fixtures.catalogos_mvp import (
    ADMINISTRADOR as ADMIN_DEMO,
)
from tests.fixtures.catalogos_mvp import (
    CLIENTE,
    COMPATIBILIDADES,
    EQUIPO,
    ESTACION,
    ESTACIONES,
    INSUMO_BATERIA,
    INSUMOS_PREVISTOS,
    TIPO_BATERIA,
    t,
)
from tests.fixtures.catalogos_mvp import (
    COORDINADOR as COORD_DEMO,
)
from tests.fixtures.catalogos_mvp import (
    RECEPCION as RECEP_DEMO,
)
from tests.fixtures.catalogos_mvp import (
    TECNICO as TECH_DEMO,
)

ORDEN_ID = "OR-000001"
DETALLE_ID = "DET-001"


@pytest.fixture
def repos(tmp_path):
    """Repositories aislados, con los catalogos ya sembrados."""
    ordenes_repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    catalogos_repo = JsonCatalogosRepository(tmp_path / "catalogs")

    catalogos = {
        "tipos_reparacion.json": [TIPO_BATERIA],
        "insumos.json": [INSUMO_BATERIA],
        "tipo_reparacion_insumos.json": INSUMOS_PREVISTOS,
        "estaciones.json": ESTACIONES,
        "tipo_reparacion_estaciones.json": COMPATIBILIDADES,
        "usuarios.json": [RECEP_DEMO, COORD_DEMO, TECH_DEMO, ADMIN_DEMO],
    }
    for archivo, entidades in catalogos.items():
        escribir_json_atomico(
            catalogos_repo.directorio / archivo,
            [entidad.model_dump(mode="json") for entidad in entidades],
        )

    return ordenes_repo, catalogos_repo


def test_hp_rep_001_persistido_end_to_end(repos):
    """Recorre HP-REP-001 recargando la Orden desde JSON en cada tramo."""
    ordenes_repo, catalogos_repo = repos

    # Los actores salen del catalogo persistido.
    recepcion = catalogos_repo.obtener_usuario("RECEP-001")
    coordinador = catalogos_repo.obtener_usuario("COORD-001")
    tecnico = catalogos_repo.obtener_usuario("TECH-001")
    administrador = catalogos_repo.obtener_usuario("ADMIN-001")

    # --- Tramo 1: ingreso (010/030/040) -> guardar
    orden = crear_orden_cliente_externo(
        orden_id=ORDEN_ID,
        cliente=CLIENTE,
        equipo=EQUIPO,
        usuario=recepcion,
        fecha=t(0),
    )
    ordenes_repo.guardar(orden)

    # --- Tramo 2: cargar -> Detalle y comprobante (045/070, 050/060)
    orden = ordenes_repo.obtener(ORDEN_ID)
    assert orden.estado_workflow is EstadoWorkflow.REQUERIMIENTO
    assert orden.reparaciones_detail == []

    tipo = catalogos_repo.obtener_tipo_reparacion("TREP-001")
    orden = definir_reparacion_detail(
        orden,
        detalle_id=DETALLE_ID,
        tipo_reparacion=tipo,
        usuario=recepcion,
        fecha=t(5),
    )
    orden = generar_comprobante_recepcion(orden, fecha=t(10))
    ordenes_repo.guardar(orden)

    # --- Tramo 3: cargar -> factibilidad, habilitacion y cola
    orden = ordenes_repo.obtener(ORDEN_ID)
    assert orden.total == Decimal("80000")
    assert orden.documentos.comprobante_recepcion.generado is True

    orden, factible = validar_factibilidad_detalles(
        orden,
        insumos=catalogos_repo.listar_insumos(),
        insumos_previstos=catalogos_repo.listar_tipo_reparacion_insumos(),
        fecha=t(15),
        reservas_externas=cargar_reservas_externas(ORDEN_ID, ordenes_repo),
    )
    assert factible is True
    # La factibilidad no reservo nada.
    assert orden.movimientos_insumo == []
    assert catalogos_repo.obtener_insumo("INS-001").stock_fisico == Decimal(
        "2"
    )

    orden = habilitar_orden(orden, fecha=t(20))
    orden = definir_prioridad(
        orden, prioridad=1, usuario=coordinador, fecha=t(25)
    )
    orden = ingresar_a_cola(orden, fecha=t(30))
    ordenes_repo.guardar(orden)

    # --- Tramo 4: cargar -> toma y seleccion (172/180/181/174)
    orden = ordenes_repo.obtener(ORDEN_ID)
    assert orden.estado_workflow is EstadoWorkflow.EN_COLA

    orden, estacion_valida = validar_estacion_trabajo(
        orden,
        usuario=tecnico,
        estacion_id=ESTACION.id,
        estaciones=catalogos_repo.listar_estaciones(),
        compatibilidades=catalogos_repo.listar_tipo_reparacion_estaciones(),
        fecha=t(58),
    )
    assert estacion_valida is True

    orden = tomar_orden(
        orden, usuario=tecnico, estacion_id=ESTACION.id, fecha=t(60)
    )
    orden = seleccionar_detalle(
        orden, detalle_id=DETALLE_ID, usuario=tecnico, fecha=t(62)
    )
    orden, compatible = validar_compatibilidad_detalle(
        orden,
        detalle_id=DETALLE_ID,
        compatibilidades=catalogos_repo.listar_tipo_reparacion_estaciones(),
        fecha=t(63),
    )
    assert compatible is True
    ordenes_repo.guardar(orden)

    # --- Tramo 5: cargar -> reserva y ejecucion (185/190)
    orden = ordenes_repo.obtener(ORDEN_ID)
    assert toma_activa(orden) is not None

    orden = reservar_insumos_e_iniciar_ejecucion(
        orden,
        detalle_id=DETALLE_ID,
        usuario=tecnico,
        insumos=catalogos_repo.listar_insumos(),
        insumos_previstos=catalogos_repo.listar_tipo_reparacion_insumos(),
        fecha=t(65),
        reservas_externas=cargar_reservas_externas(ORDEN_ID, ordenes_repo),
    )
    orden = ejecutar_detalle(
        orden, detalle_id=DETALLE_ID, usuario=tecnico, fecha=t(70)
    )
    ordenes_repo.guardar(orden)

    # La RESERVA no toco el stock fisico.
    assert catalogos_repo.obtener_insumo("INS-001").stock_fisico == Decimal(
        "2"
    )

    # --- Tramo 6: cargar -> ejecucion real (200) e inventario (210)
    orden = ordenes_repo.obtener(ORDEN_ID)
    ejecucion = ejecucion_activa(orden)
    assert ejecucion is not None
    assert orden.estado_workflow is EstadoWorkflow.EN_REPARACION

    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=ejecucion.id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
        ],
        usuario=tecnico,
        fecha=t(145),
        observaciones="Bateria reemplazada sin novedades.",
    )
    orden = aplicar_movimientos_inventario(
        orden,
        ejecucion_id=ejecucion.id,
        fecha=t(146),
        ordenes_repo=ordenes_repo,
        catalogos_repo=catalogos_repo,
    )

    # El CONSUMO si bajo el stock fisico: 2 - 1 = 1.
    assert catalogos_repo.obtener_insumo("INS-001").stock_fisico == Decimal(
        "1"
    )

    # --- Tramo 7: cargar -> evaluacion (211) y control (220/230/245/240)
    orden = ordenes_repo.obtener(ORDEN_ID)
    assert hay_reservas_activas(orden.movimientos_insumo) is False

    orden, resultado = evaluar_situacion_orden(orden, fecha=t(150))
    assert resultado is ResultadoEvaluacionOrden.COMPLETA

    orden = aprobar_control_tecnico(
        orden,
        usuario=recepcion,
        fecha=t(160),
        observaciones="Equipo enciende y carga correctamente.",
    )
    orden = calcular_puntaje(orden, fecha=t(165))
    orden = marcar_reparacion_lista(orden, fecha=t(170))
    ordenes_repo.guardar(orden)

    # --- Tramo 8: cargar -> notificacion y cobro (250/260/265/266)
    orden = ordenes_repo.obtener(ORDEN_ID)
    assert orden.estado_workflow is EstadoWorkflow.REPARACION_LISTA
    assert orden.puntaje_total == 10

    orden = notificar_cliente(orden, usuario=recepcion, fecha=t(175))
    orden, puede_entregar = validar_condicion_entrega(orden, fecha=t(180))
    assert puede_entregar is False
    assert orden.saldo == Decimal("80000")

    orden = registrar_saldo_pendiente(orden, fecha=t(181))
    ordenes_repo.guardar(orden)

    # --- Tramo 9: cargar -> pago, revalidacion y documentacion (280)
    orden = ordenes_repo.obtener(ORDEN_ID)
    assert orden.estado_pago is EstadoPago.PENDIENTE

    orden = registrar_pago(
        orden,
        monto=Decimal("80000"),
        metodo="EFECTIVO",
        usuario=administrador,
        fecha=t(185),
    )
    orden, puede_entregar = validar_condicion_entrega(orden, fecha=t(186))
    assert puede_entregar is True

    orden = generar_comprobante_final(orden, fecha=t(190))
    ordenes_repo.guardar(orden)

    # --- Tramo 10: cargar -> entrega (270 -> EVT-REP-999)
    orden = ordenes_repo.obtener(ORDEN_ID)
    assert orden.saldo == Decimal("0")

    orden = entregar_equipo(orden, usuario=administrador, fecha=t(195))
    ordenes_repo.guardar(orden)

    # --- expected de HP-REP-001, releido desde JSON ---------------------
    final = ordenes_repo.obtener(ORDEN_ID)

    assert resultado is ResultadoEvaluacionOrden.COMPLETA
    assert final.estado_workflow is EstadoWorkflow.ENTREGADA
    assert ejecucion_activa(final) is None
    assert toma_activa(final) is None
    assert hay_reservas_activas(final.movimientos_insumo) is False
    assert final.saldo == Decimal("0")
    assert final.documentos.comprobante_final.generado is True
    assert final.documentos.garantia_reparacion.generado is True

    assert final.current_process == "EVT-REP-999"
    assert final.reparaciones_detail[0].estado is (
        EstadoReparacionDetail.COMPLETO
    )
    assert final.reparaciones_detail[0].control_estado is (
        EstadoControl.APROBADO
    )
    assert final.tomas[0].estado is EstadoTomaOrden.CERRADA
    assert final.puntaje_total == 10
    assert final.estado_pago is EstadoPago.PAGADO

    # El estado final se puede volver a cargar desde el archivo.
    assert final == orden
    assert ordenes_repo.obtener(ORDEN_ID) == final
    assert len(ordenes_repo.listar()) == 1


def test_la_orden_persistida_recorre_los_nodos_del_scenario(repos):
    """El historial sobrevive intacto a todos los ciclos de guardado."""
    ordenes_repo, _ = repos
    test_hp_rep_001_persistido_end_to_end(repos)

    final = ordenes_repo.obtener(ORDEN_ID)
    recorridos = [paso.process_id for paso in final.historial]

    for process_id in [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
        "PROC-REP-150",
        "PROC-REP-170",
        "PROC-REP-172",
        "PROC-REP-180",
        "PROC-REP-181",
        "PROC-REP-174",
        "PROC-REP-185",
        "PROC-REP-190",
        "PROC-REP-200",
        "PROC-REP-210",
        "PROC-REP-211",
        "PROC-REP-220",
        "PROC-REP-230",
        "PROC-REP-245",
        "PROC-REP-240",
        "PROC-REP-250",
        "PROC-REP-260",
        "PROC-REP-265",
        "PROC-REP-266",
        "PROC-REP-280",
        "PROC-REP-270",
    ]:
        assert process_id in recorridos, f"falta {process_id}"

    assert recorridos.count("PROC-REP-265") == 2
    assert all(paso.process_id != "EVT-REP-999" for paso in final.historial)


def test_el_archivo_final_es_una_orden_valida(repos, tmp_path):
    """El JSON en disco se valida contra el modelo sin intermediarios."""
    import json

    ordenes_repo, _ = repos
    test_hp_rep_001_persistido_end_to_end(repos)

    ruta = ordenes_repo.directorio / f"{ORDEN_ID}.json"
    crudo = json.loads(ruta.read_text(encoding="utf-8"))

    reconstruida = OrdenReparacion.model_validate(crudo)

    assert reconstruida == ordenes_repo.obtener(ORDEN_ID)
    assert crudo["estado_workflow"] == "ENTREGADA"
    assert crudo["current_process"] == "EVT-REP-999"

    # Los derivados no se persisten: renacen al reconstruir el modelo.
    for derivado in ("total", "saldo", "estado_pago", "puntaje_total"):
        assert derivado not in crudo
    assert "pagado" not in crudo["resumen_pago"]

    assert reconstruida.saldo == Decimal("0")
    assert reconstruida.puntaje_total == 10


def test_un_json_anterior_a_slice_0_sigue_cargando(repos, tmp_path):
    """Compatibilidad JSON: ``condicion`` es nueva, con default.

    Simula un archivo escrito ANTES de Slice 0 -sin el campo
    ``condicion`` en cada Detalle, que no existia todavia- y confirma
    que ``OrdenReparacion.model_validate`` lo sigue cargando sin
    tocarlo, con ``condicion`` resuelta a su default (``SIN_BLOQUEO``).
    """
    import json

    from app.domain.models import CondicionReparacionDetail

    ordenes_repo, _ = repos
    test_hp_rep_001_persistido_end_to_end(repos)

    ruta = ordenes_repo.directorio / f"{ORDEN_ID}.json"
    crudo_v2 = json.loads(ruta.read_text(encoding="utf-8"))

    # El JSON real (post Slice 0) SI tiene "condicion": lo confirma antes
    # de quitarlo, para no simular una forma que nunca existio.
    assert "condicion" in crudo_v2["reparaciones_detail"][0]

    crudo_v1 = json.loads(json.dumps(crudo_v2))
    for detalle in crudo_v1["reparaciones_detail"]:
        del detalle["condicion"]

    reconstruida = OrdenReparacion.model_validate(crudo_v1)

    assert reconstruida.reparaciones_detail[0].condicion is (
        CondicionReparacionDetail.SIN_BLOQUEO
    )
    # El flujo de HP-REP-001 nunca produce otra condicion: el default
    # que Pydantic resuelve para el JSON "v1" (sin el campo) coincide
    # exactamente con lo que el JSON real (post Slice 0) ya tenia, asi
    # que la Orden reconstruida es identica a la persistida de verdad.
    assert reconstruida == ordenes_repo.obtener(ORDEN_ID)
