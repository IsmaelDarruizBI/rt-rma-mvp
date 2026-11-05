"""Contrato de ``OrdenReparacionRepository``: consultas dedicadas (E2).

Las pruebas de este modulo valen para cualquier implementacion: hoy
JSON. E4 y E5 agregan PostgreSQL a ``IMPLEMENTACIONES`` sin reescribirlas.
Cada una arma un repository vacio y la transaccion de su unidad de
trabajo. Las que dependen de como JSON numera estan al final, aparte.

Diseno: ``docs/postgresql/e2-consultas-dedicadas.md`` (seccion C).
"""

import re
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.application import ApplicationContext
from app.application.concurrencia import UnidadDeTrabajoJson
from app.domain.models import (
    Cliente,
    EstadoWorkflow,
    FotoOrden,
    MovimientoInsumo,
    OrdenReparacion,
    TipoMovimientoInsumo,
)
from app.repositories import (
    ConflictoDeEscrituraError,
    EntidadPersistidaNoEncontradaError,
    OrdenReparacionRepository,
    PersistenciaError,
)
from app.services.inventario import cantidad_pendiente
from app.services.inventario_global import (
    reservas_activas_globales,
    reservas_externas_a,
)
from app.services.inventario_operativo import reservas_vigentes_por_insumo
from app.storage import JsonOrdenReparacionRepository
from tests.fixtures.hp_rep_001 import construir_orden_hp_rep_001

FECHA = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
DNI = "30111222"


@dataclass(frozen=True)
class Implementacion:
    repo: OrdenReparacionRepository
    transaccion: Callable[[], AbstractContextManager[None]]


def _json(tmp_path) -> Implementacion:
    unidad = UnidadDeTrabajoJson()
    repo = JsonOrdenReparacionRepository(
        tmp_path / "ordenes", en_transaccion=unidad.en_curso
    )
    return Implementacion(repo=repo, transaccion=unidad.transaccion)


IMPLEMENTACIONES = {"json": _json}


@pytest.fixture(params=sorted(IMPLEMENTACIONES))
def impl(request, tmp_path) -> Implementacion:
    return IMPLEMENTACIONES[request.param](tmp_path)


# --- Ordenes de prueba ------------------------------------------------------

_BASE = construir_orden_hp_rep_001()


def _orden(orden_id: str, **cambios) -> OrdenReparacion:
    """Una Orden ABIERTA, sin movimientos ni fotos, salvo ``cambios``."""
    datos = {
        "id": orden_id,
        "estado_workflow": EstadoWorkflow.REQUERIMIENTO,
        "current_process": "PROC-REP-040",
        "movimientos_insumo": [],
        "fotos": [],
        **cambios,
    }
    return _BASE.model_copy(update=datos, deep=True)


def _cliente(cliente_id: str, dni: str | None) -> Cliente:
    return Cliente(
        id=cliente_id, dni=dni, nombre_apellido="Ana", telefono="341-1"
    )


def _mov(
    mov_id: str,
    tipo: TipoMovimientoInsumo,
    insumo_id: str = "INS-001",
    origen: str | None = None,
    cantidad: str = "1",
) -> MovimientoInsumo:
    return MovimientoInsumo(
        id=mov_id,
        tipo=tipo,
        insumo_id=insumo_id,
        reparacion_detail_id="DET-001",
        cantidad=Decimal(cantidad),
        movimiento_origen_id=origen,
        fecha=FECHA,
    )


def _foto(foto_id: str, objeto: str) -> FotoOrden:
    return FotoOrden(
        id=foto_id,
        objeto=objeto,
        tipo_contenido="image/jpeg",
        tamano_bytes=10,
        usuario_id="RECEP-001",
        fecha=FECHA,
    )


RESERVA = TipoMovimientoInsumo.RESERVA
CONSUMO = TipoMovimientoInsumo.CONSUMO
LIBERACION = TipoMovimientoInsumo.LIBERACION_RESERVA
CERRADA = {"estado_workflow": EstadoWorkflow.ENTREGADA}
# RT_INTERNO devuelto a Gestion RT: cerrada sin pasar por ENTREGADA.
CERRADA_RT = {
    "estado_workflow": EstadoWorkflow.REPARACION_LISTA,
    "current_process": "EVT-REP-999",
}
CANCELADA = {"estado_workflow": EstadoWorkflow.CANCELADA}


def _guardar(impl: Implementacion, *ordenes: OrdenReparacion) -> None:
    with impl.transaccion():
        for orden in ordenes:
            impl.repo.guardar(orden)


def _ids(ordenes) -> list[str]:
    return [orden.id for orden in ordenes]


# --- Conjuntos vacios -------------------------------------------------------


def test_sin_ordenes_todas_las_consultas_vuelven_vacias(impl):
    repo = impl.repo
    assert repo.listar() == []
    assert repo.listar_abiertas() == []
    assert repo.listar_por_dni_cliente(DNI) == []
    assert repo.listar_con_reservas() == []
    assert repo.listar_con_reservas(["INS-001"]) == []
    assert repo.listar_con_movimientos() == []
    assert repo.listar_con_movimientos("INS-001") == []
    assert repo.claves_de_fotos() == frozenset()
    with impl.transaccion():
        assert re.fullmatch(r"OR-\d{6,}", repo.reservar_codigo())


# --- Orden y cardinalidad ---------------------------------------------------


def test_toda_lista_va_por_numero_de_orden(impl):
    """Se guardan desordenadas; todas vuelven por numero ascendente."""

    def _con(n):
        return _orden(
            f"OR-00000{n}",
            cliente=_cliente("CLI-1", DNI),
            movimientos_insumo=[_mov(f"M-{n}", RESERVA)],
            fotos=[_foto(f"F-{n}", f"ordenes/{n}.jpg")],
        )

    _guardar(impl, _con(3), _con(1), _con(2))
    esperado = ["OR-000001", "OR-000002", "OR-000003"]
    repo = impl.repo
    assert _ids(repo.listar()) == esperado
    assert _ids(repo.listar_abiertas()) == esperado
    assert _ids(repo.listar_por_dni_cliente(DNI)) == esperado
    assert _ids(repo.listar_con_reservas()) == esperado
    assert _ids(repo.listar_con_movimientos()) == esperado
    assert repo.claves_de_fotos() == {
        "ordenes/1.jpg",
        "ordenes/2.jpg",
        "ordenes/3.jpg",
    }


def test_un_unico_resultado_entre_otras_ordenes(impl):
    _guardar(
        impl,
        _orden("OR-000001"),
        _orden(
            "OR-000002",
            cliente=_cliente("CLI-2", DNI),
            movimientos_insumo=[_mov("M-1", RESERVA, "INS-002")],
        ),
        _orden("OR-000003", **CERRADA),
    )
    repo = impl.repo
    assert _ids(repo.listar_por_dni_cliente(DNI)) == ["OR-000002"]
    assert _ids(repo.listar_con_reservas(["INS-002"])) == ["OR-000002"]
    assert _ids(repo.listar_con_movimientos("INS-002")) == ["OR-000002"]


# --- Abiertas: estados ------------------------------------------------------


def test_abiertas_incluye_canceladas_y_excluye_las_cerradas(impl):
    _guardar(
        impl,
        _orden("OR-000001"),
        _orden("OR-000002", **CANCELADA),
        _orden("OR-000003", **CERRADA),
        _orden("OR-000004", **CERRADA_RT),
        _orden("OR-000005", estado_workflow=EstadoWorkflow.EN_REVISION),
    )
    repo = impl.repo
    abiertas = repo.listar_abiertas()
    assert _ids(abiertas) == ["OR-000001", "OR-000002", "OR-000005"]
    # La misma semantica que ``esta_cerrada`` sobre todas.
    assert abiertas == [o for o in repo.listar() if not o.esta_cerrada]


# --- DNI: nulos y clientes distintos ----------------------------------------


def test_dni_exacto_sin_nulos_ni_ordenes_sin_cliente(impl):
    _guardar(
        impl,
        _orden("OR-000001", cliente=_cliente("CLI-1", DNI)),
        # Otro cliente con el mismo DNI (ambiguo): tambien vuelve.
        _orden("OR-000002", cliente=_cliente("CLI-2", DNI), **CERRADA),
        _orden("OR-000003", cliente=_cliente("CLI-3", None)),
        _orden("OR-000004", cliente=_cliente("CLI-4", "30111223")),
        _orden("OR-000005", cliente=None),
        _orden("OR-000006", cliente=_cliente("CLI-6", "3011122")),
    )
    repo = impl.repo
    assert _ids(repo.listar_por_dni_cliente(DNI)) == [
        "OR-000001",
        "OR-000002",
    ]
    assert repo.listar_por_dni_cliente("99999999") == []
    assert repo.listar_por_dni_cliente(DNI) == [
        o
        for o in repo.listar()
        if o.cliente is not None and o.cliente.dni == DNI
    ]


# --- Reservas y movimientos -------------------------------------------------


def _ordenes_con_movimientos() -> list[OrdenReparacion]:
    return [
        _orden("OR-000001", movimientos_insumo=[_mov("M-1", RESERVA)]),
        # Reserva ya consumida: puede volver o no (QA-E2-2).
        _orden(
            "OR-000002",
            movimientos_insumo=[
                _mov("M-2", RESERVA, "INS-002"),
                _mov("M-3", CONSUMO, "INS-002", origen="M-2"),
            ],
        ),
        # Consumo sin reserva (override): movimiento, pero no RESERVA.
        _orden("OR-000003", movimientos_insumo=[_mov("M-4", CONSUMO)]),
        _orden("OR-000004"),
        # Cerrada con una reserva pendiente: tiene que volver.
        _orden(
            "OR-000005",
            movimientos_insumo=[_mov("M-5", RESERVA, "INS-10")],
            **CERRADA,
        ),
    ]


def _ordenes_con_reservas() -> list[OrdenReparacion]:
    return [
        *_ordenes_con_movimientos(),
        # Reserva liberada en parte: sigue pendiente lo que queda.
        _orden(
            "OR-000006",
            movimientos_insumo=[
                _mov("M-6", RESERVA, "INS-001", cantidad="2"),
                _mov("M-7", LIBERACION, "INS-001", origen="M-6"),
            ],
        ),
        # Reserva liberada del todo: puede volver o no.
        _orden(
            "OR-000007",
            movimientos_insumo=[
                _mov("M-8", RESERVA, "INS-002"),
                _mov("M-9", LIBERACION, "INS-002", origen="M-8"),
            ],
        ),
    ]


def _reservas_de(orden, insumo_ids, solo_pendientes):
    movimientos = orden.movimientos_insumo
    return any(
        movimiento.tipo is RESERVA
        and (insumo_ids is None or movimiento.insumo_id in insumo_ids)
        and (
            not solo_pendientes
            or cantidad_pendiente(movimiento, movimientos) > 0
        )
        for movimiento in movimientos
    )


FILTROS_DE_INSUMOS = [
    None,
    ["INS-001"],
    ["INS-002"],
    ["INS-001", "INS-002"],
    ["INS-10"],
    [],
    ["INS-999"],
]


@pytest.mark.parametrize("insumo_ids", FILTROS_DE_INSUMOS)
def test_con_reservas_es_un_conjunto_candidato(impl, insumo_ids):
    """Las dos garantias minimas (QA-E2-2): toda Orden con una reserva
    pendiente, ninguna sin RESERVA. Las de reservas cerradas, a eleccion
    de la implementacion."""
    _guardar(impl, *_ordenes_con_reservas())
    todas = impl.repo.listar()
    ids = _ids(impl.repo.listar_con_reservas(insumo_ids))
    assert ids == sorted(set(ids))  # por numero, sin repetidos
    pendientes = {o.id for o in todas if _reservas_de(o, insumo_ids, True)}
    con_reserva = {o.id for o in todas if _reservas_de(o, insumo_ids, False)}
    assert pendientes <= set(ids) <= con_reserva


@pytest.mark.parametrize("insumo_ids", FILTROS_DE_INSUMOS)
def test_con_reservas_alcanza_para_los_calculos_de_reservas(impl, insumo_ids):
    """Los services calculan sobre las candidatas lo mismo que sobre
    todas las Ordenes (para los insumos pedidos)."""
    _guardar(impl, *_ordenes_con_reservas())
    todas = impl.repo.listar()
    candidatas = impl.repo.listar_con_reservas(insumo_ids)

    def de_los_pedidos(por_insumo):
        return {
            insumo: valor
            for insumo, valor in por_insumo.items()
            if insumo_ids is None or insumo in insumo_ids
        }

    assert de_los_pedidos(reservas_activas_globales(candidatas)) == (
        de_los_pedidos(reservas_activas_globales(todas))
    )
    assert de_los_pedidos(reservas_vigentes_por_insumo(candidatas)) == (
        de_los_pedidos(reservas_vigentes_por_insumo(todas))
    )
    for orden in todas:
        assert de_los_pedidos(
            reservas_externas_a(orden.id, candidatas)
        ) == de_los_pedidos(reservas_externas_a(orden.id, todas))


# --- Parametros invalidos (QA-E2-3) -----------------------------------------


def test_un_insumo_suelto_como_str_se_rechaza(impl):
    """Un str tambien es Collection[str]: se tomaria letra por letra."""
    _guardar(impl, *_ordenes_con_movimientos())
    with pytest.raises(ValueError, match="no un str"):
        impl.repo.listar_con_reservas("INS-001")


def test_buscar_por_dni_none_se_rechaza(impl):
    """Con None, JSON compararia contra los clientes sin DNI y SQL no
    devolveria nada: se rechaza en las dos."""
    _guardar(impl, _orden("OR-000001", cliente=_cliente("CLI-1", None)))
    with pytest.raises(ValueError, match="None"):
        impl.repo.listar_por_dni_cliente(None)


def test_con_movimientos_compara_el_insumo_exacto(impl):
    _guardar(impl, *_ordenes_con_movimientos())
    repo = impl.repo
    assert _ids(repo.listar_con_movimientos()) == [
        "OR-000001",
        "OR-000002",
        "OR-000003",
        "OR-000005",
    ]
    assert _ids(repo.listar_con_movimientos("INS-001")) == [
        "OR-000001",
        "OR-000003",
    ]
    # "INS-1" no coincide con "INS-10": igualdad, no subcadena.
    assert repo.listar_con_movimientos("INS-1") == []
    assert _ids(repo.listar_con_movimientos("INS-10")) == ["OR-000005"]


# --- Fotos ------------------------------------------------------------------


def test_claves_de_fotos_de_abiertas_y_cerradas(impl):
    _guardar(
        impl,
        _orden(
            "OR-000001",
            fotos=[_foto("F-1", "ordenes/a.jpg"), _foto("F-2", "ordenes/b")],
        ),
        _orden("OR-000002", fotos=[_foto("F-3", "ordenes/c.png")], **CERRADA),
        _orden("OR-000003"),
    )
    claves = impl.repo.claves_de_fotos()
    assert isinstance(claves, frozenset)
    assert claves == {"ordenes/a.jpg", "ordenes/b", "ordenes/c.png"}


# --- Numeracion -------------------------------------------------------------


def test_reservar_codigo_nunca_repite_un_numero_guardado(impl):
    _guardar(
        impl,
        _orden("OR-000001"),
        _orden("OR-000007"),
        _orden("RT-77"),
        _orden("OR-ABC"),
    )
    with impl.transaccion():
        codigo = impl.repo.reservar_codigo()
    assert re.fullmatch(r"OR-\d{6,}", codigo)
    assert codigo not in _ids(impl.repo.listar())


# --- Precondiciones transaccionales -----------------------------------------


def test_fuera_de_una_transaccion_no_se_lee_para_modificar(impl):
    _guardar(impl, _orden("OR-000001"))
    with pytest.raises(PersistenciaError, match="transaccion"):
        impl.repo.obtener_para_modificar("OR-000001")
    with pytest.raises(PersistenciaError, match="transaccion"):
        impl.repo.reservar_codigo()


def test_dentro_de_la_transaccion_se_lee_para_modificar(impl):
    _guardar(impl, _orden("OR-000001"))
    with impl.transaccion():
        orden = impl.repo.obtener_para_modificar("OR-000001")
        with pytest.raises(EntidadPersistidaNoEncontradaError):
            impl.repo.obtener_para_modificar("OR-999999")
    assert orden == impl.repo.obtener("OR-000001")


def test_la_transaccion_de_otro_hilo_no_cuenta(impl):
    _guardar(impl, _orden("OR-000001"))
    adentro, soltar = threading.Event(), threading.Event()
    errores = []

    def otro_hilo():
        with impl.transaccion():
            adentro.set()
            soltar.wait(10)

    hilo = threading.Thread(target=otro_hilo)
    hilo.start()
    assert adentro.wait(10)
    try:
        impl.repo.obtener_para_modificar("OR-000001")
    except PersistenciaError as error:
        errores.append(error)
    finally:
        soltar.set()
        hilo.join(10)
    assert len(errores) == 1


# --- Concurrencia -----------------------------------------------------------


def test_altas_simultaneas_reciben_numeros_distintos(impl):
    hilos, codigos, errores = 8, [], []
    barrera = threading.Barrier(hilos, timeout=10)

    def alta():
        barrera.wait()
        try:
            with impl.transaccion():
                codigo = impl.repo.reservar_codigo()
                time.sleep(0.005)  # deja lugar a que otro se meta
                impl.repo.guardar(_orden(codigo))
                codigos.append(codigo)
        except Exception as error:  # noqa: BLE001 (se informa abajo)
            errores.append(error)

    trabajos = [threading.Thread(target=alta) for _ in range(hilos)]
    for trabajo in trabajos:
        trabajo.start()
    for trabajo in trabajos:
        trabajo.join(30)
    assert errores == []
    assert len(set(codigos)) == hilos
    assert sorted(codigos) == _ids(impl.repo.listar())


def test_lecturas_para_modificar_simultaneas_no_se_pisan(impl):
    """Cada hilo lee, agrega un paso al historial y guarda. Sin exclusion
    mutua, dos leerian la misma version y uno chocaria al guardar."""
    _guardar(impl, _orden("OR-000001"))
    hilos, errores = 6, []
    barrera = threading.Barrier(hilos, timeout=10)

    def modificar(n):
        barrera.wait()
        try:
            with impl.transaccion():
                orden = impl.repo.obtener_para_modificar("OR-000001")
                paso = orden.historial[-1].model_copy(
                    update={"observacion": f"hilo {n}"}
                )
                time.sleep(0.005)
                impl.repo.guardar(
                    orden.model_copy(
                        update={"historial": [*orden.historial, paso]}
                    )
                )
        except ConflictoDeEscrituraError as error:
            errores.append(error)

    trabajos = [
        threading.Thread(target=modificar, args=(n,)) for n in range(hilos)
    ]
    for trabajo in trabajos:
        trabajo.start()
    for trabajo in trabajos:
        trabajo.join(30)
    assert errores == []
    final = impl.repo.obtener("OR-000001")
    observaciones = {paso.observacion for paso in final.historial}
    assert {f"hilo {n}" for n in range(hilos)} <= observaciones
    assert len(final.historial) == len(_BASE.historial) + hilos


# --- Propio de JSON ---------------------------------------------------------


def test_json_devuelve_toda_orden_con_alguna_reserva(tmp_path):
    """JSON elige el conjunto candidato mas amplio que admite el
    contrato: toda Orden con alguna RESERVA, pendiente o no (el mismo
    resultado que antes de QA-E2-2)."""
    impl = _json(tmp_path)
    _guardar(impl, *_ordenes_con_reservas())
    repo = impl.repo
    assert _ids(repo.listar_con_reservas()) == [
        "OR-000001",
        "OR-000002",
        "OR-000005",
        "OR-000006",
        "OR-000007",
    ]
    assert _ids(repo.listar_con_reservas(["INS-001"])) == [
        "OR-000001",
        "OR-000006",
    ]
    assert _ids(repo.listar_con_reservas(["INS-002"])) == [
        "OR-000002",
        "OR-000007",
    ]
    assert repo.listar_con_reservas([]) == []
    assert repo.listar_con_reservas(["INS-999"]) == []


def test_json_numera_como_antes_maximo_mas_uno(tmp_path):
    """La numeracion JSON es la de siempre (identificadores.py): maximo
    persistido con el patron ``OR-\\d+`` mas uno, a seis digitos."""
    impl = _json(tmp_path)
    with impl.transaccion():
        assert impl.repo.reservar_codigo() == "OR-000001"
    _guardar(
        impl,
        _orden("OR-000001"),
        _orden("OR-12"),
        _orden("RT-77"),
        _orden("OR-ABC"),
        _orden("XOR-000099"),
    )
    with impl.transaccion():
        assert impl.repo.reservar_codigo() == "OR-000013"


def test_json_sin_unidad_de_trabajo_vinculada_falla_cerrado(tmp_path):
    repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    repo.guardar(_orden("OR-000001"))
    with UnidadDeTrabajoJson().transaccion():
        with pytest.raises(PersistenciaError, match="transaccion"):
            repo.obtener_para_modificar("OR-000001")
        with pytest.raises(PersistenciaError, match="transaccion"):
            repo.reservar_codigo()


def test_el_contexto_vincula_su_unidad_de_trabajo(tmp_path):
    unidad = UnidadDeTrabajoJson()
    repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    repo.guardar(_orden("OR-000001"))
    contexto = ApplicationContext(
        ordenes=repo, catalogos=object(), unidad_de_trabajo=unidad
    )
    with pytest.raises(PersistenciaError, match="transaccion"):
        repo.obtener_para_modificar("OR-000001")
    with contexto.transaccion():
        assert repo.obtener_para_modificar("OR-000001").id == "OR-000001"
    # La transaccion de OTRA unidad no habilita a esta.
    with UnidadDeTrabajoJson().transaccion():
        with pytest.raises(PersistenciaError, match="transaccion"):
            repo.obtener_para_modificar("OR-000001")
