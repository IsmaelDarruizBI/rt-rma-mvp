"""Reservas de insumos en PostgreSQL (E5, slice A6).

Contra la base local descartable. Las Ordenes se arman por la API en JSON
hasta tener la toma y se copian a PostgreSQL; la reserva (185) corre como
comando real sobre PostgreSQL, con sus catalogos y su stock (el del
catalogo JSON, ingresado en el libro). Semantica que se verifica:

- La ultima unidad: dos tecnicos reservan a la vez; uno reserva y el otro
  recibe la reserva fallida funcional (186), nunca un error. Sin el
  bloqueo de insumos, el trigger del libro igual impide la sobreasignacion.
- Stock insuficiente: reserva fallida, sin movimientos.
- Las reservas se guardan en el libro y vuelven igual; el trigger mueve
  ``stock_reservado`` y ``verificar_integridad()`` queda vacia.
- Bloqueos: los insumos van despues de la Orden y por ``clave``; un
  ``KEY SHARE`` sobre el insumo no frena la reserva (QA-A2-M4).
- Todo o nada; un movimiento repetido no se duplica.
- Dos lineas del mismo insumo en una Ejecucion (QA-A2-M1).
- ``listar_con_reservas`` y ``listar_con_movimientos`` con reservas reales
  (A5-2).

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (seccion 17).
"""

import threading
import time
from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.application import iniciar_detalle  # noqa: E402
from app.application import taller as taller_app  # noqa: E402
from app.application.contexto import ApplicationContext  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.domain.models import (  # noqa: E402
    HistorialWorkflow,
    InsumoUtilizado,
    MovimientoInsumo,
    TipoMovimientoInsumo,
)
from app.main import create_app  # noqa: E402
from app.repositories.exceptions import (  # noqa: E402
    ConflictoDeEscrituraError,
    PersistenciaError,
    RestriccionDeIntegridadError,
)
from app.storage.json.ordenes import (  # noqa: E402
    JsonOrdenReparacionRepository,
)
from app.storage.postgres.catalogos import (  # noqa: E402
    PostgresCatalogosRepository,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.sembrado import fijar_stock  # noqa: E402
from tests.postgres.test_ordenes_postgres import (  # noqa: E402
    _consultas_de,
    _sql,
    _version,
)

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla

RESERVA = TipoMovimientoInsumo.RESERVA
INSUMO = f.INSUMO_BATERIA


@pytest.fixture
def taller(armar, base, tmp_path):
    """Dos Ordenes de BATERIA tomadas (una por tecnico), en PostgreSQL.

    Devuelve el repository, la unidad, el contexto PostgreSQL y las dos
    Ordenes con su tecnico.
    """
    f.sembrar(tmp_path)
    configuracion = Settings(data_dir=tmp_path, fotos_dir=tmp_path / "fotos")
    tomadas = []
    with TestClient(create_app(configuracion)) as cliente:
        for tecnico in (f.TECNICO, f.TECNICO_B):
            orden = f.definida(cliente, f.BATERIA)
            f.tomada(cliente, orden, tecnico)
            tomadas.append((orden, tecnico))
    # La plantilla tiene el stock que dejo el corpus: aca, 5 de cada uno.
    for clave in (f.INSUMO_BATERIA, f.INSUMO_PANTALLA):
        _fijar(base, 5, clave)
    repo, unidad = armar(pool_max=4, lock_timeout_ms=3000)
    for orden in JsonOrdenReparacionRepository(tmp_path / "ordenes").listar():
        assert not orden.movimientos_insumo
        repo.guardar(orden)
    contexto = ApplicationContext(
        ordenes=repo,
        catalogos=PostgresCatalogosRepository(unidad),
        unidad_de_trabajo=unidad,
    )
    return repo, unidad, contexto, tomadas


def _stock(base, clave=INSUMO):
    return _sql(
        base,
        "select stock_fisico, stock_reservado from rma.insumo "
        "where clave = %s",
        (clave,),
    )[0]


def _integridad(base):
    return _sql(base, "select * from rma.verificar_integridad()")


def _fijar(base, cantidad, clave=INSUMO):
    with psycopg.connect(base, autocommit=True) as conexion:
        fijar_stock(conexion, clave, cantidad)


def _reservo(orden) -> bool:
    return any(m.tipo is RESERVA for m in orden.movimientos_insumo)


def _fallo(orden) -> bool:
    return any(p.referencia_id == "PROC-REP-186" for p in orden.historial)


def _iniciar(contexto, orden_id, tecnico):
    return iniciar_detalle(
        contexto, orden_id=orden_id, detalle_id="DET-001", usuario_id=tecnico
    )


def _a_la_vez(contexto, tomadas):
    """Las dos reservas a la vez. Entre leer el stock y guardar, cada una
    espera: sin bloqueo, las dos leerian lo mismo."""
    barrera = threading.Barrier(len(tomadas))
    resultados, errores = {}, []

    def reservar(orden_id, tecnico):
        barrera.wait(10)
        try:
            resultados[orden_id] = _iniciar(contexto, orden_id, tecnico)
        except Exception as error:  # noqa: BLE001
            errores.append(error)

    hilos = [threading.Thread(target=reservar, args=t) for t in tomadas]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    return resultados, errores


@pytest.fixture
def lectura_lenta(monkeypatch):
    """Despues de leer las reservas de las demas Ordenes, cada comando
    espera antes de decidir y guardar: sin bloqueo, el otro lee lo mismo."""
    original = taller_app.cargar_reservas_externas

    def lenta(*argumentos, **nombrados):
        reservas = original(*argumentos, **nombrados)
        time.sleep(0.3)
        return reservas

    monkeypatch.setattr(taller_app, "cargar_reservas_externas", lenta)


# --- Reserva ----------------------------------------------------------------


def test_a6_la_reserva_real_se_guarda_en_el_libro(taller, base):
    repo, _, contexto, tomadas = taller
    orden_id, tecnico = tomadas[0]
    reservada = _iniciar(contexto, orden_id, tecnico)
    assert _reservo(reservada) and not _fallo(reservada)
    assert repo.obtener(orden_id) == reservada
    assert _stock(base) == (Decimal("5"), Decimal("1"))
    assert _integridad(base) == []


def test_a6_la_ultima_unidad_la_reserva_uno_solo(taller, base, lectura_lenta):
    """Escenario 1 de §5.2: uno reserva y el otro recibe 186."""
    repo, _, contexto, tomadas = taller
    _fijar(base, 1)
    resultados, errores = _a_la_vez(contexto, tomadas)
    assert errores == []
    assert sorted(_reservo(o) for o in resultados.values()) == [False, True]
    perdedora = next(o for o in resultados.values() if not _reservo(o))
    assert _fallo(perdedora)
    for orden_id, orden in resultados.items():
        assert repo.obtener(orden_id) == orden
    assert _stock(base) == (Decimal("1"), Decimal("1"))
    assert _integridad(base) == []


def test_a6_sin_el_bloqueo_el_libro_igual_impide_la_sobreasignacion(
    taller, base, lectura_lenta, monkeypatch
):
    """Red por debajo de DI-2: sin bloquear los insumos, las dos leen la
    misma unidad libre; el trigger rechaza la segunda y no queda nada de
    ella. Es el error tecnico que el bloqueo evita."""
    _, _, contexto, tomadas = taller
    monkeypatch.setattr(
        PostgresCatalogosRepository, "bloquear_insumos", lambda *a: None
    )
    _fijar(base, 1)
    resultados, errores = _a_la_vez(contexto, tomadas)
    assert len(resultados) == 1 and _reservo(*resultados.values())
    assert [type(e) for e in errores] == [RestriccionDeIntegridadError]
    assert _stock(base) == (Decimal("1"), Decimal("1"))
    assert _integridad(base) == []


def test_a6_sin_stock_la_reserva_falla_sin_movimientos(taller, base):
    repo, _, contexto, tomadas = taller
    _fijar(base, 0)
    orden_id, tecnico = tomadas[0]
    version = _version(base, orden_id)
    fallida = _iniciar(contexto, orden_id, tecnico)
    assert _fallo(fallida) and not _reservo(fallida)
    assert repo.obtener(orden_id) == fallida
    assert _version(base, orden_id) == version + 1
    assert _sql(
        base,
        "select count(*) from rma.movimiento_inventario "
        "where tipo = 'RESERVA'",
    ) == [(0,)]


def test_a6_dos_reservas_con_stock_suficiente_conviven(taller, base):
    _, _, contexto, tomadas = taller
    resultados, errores = _a_la_vez(contexto, tomadas)
    assert errores == [] and all(_reservo(o) for o in resultados.values())
    assert _stock(base) == (Decimal("5"), Decimal("2"))
    assert _integridad(base) == []


# --- Bloqueos ---------------------------------------------------------------


def _reserva(codigo, insumo, fecha):
    return MovimientoInsumo(
        id=codigo,
        tipo=RESERVA,
        insumo_id=insumo,
        reparacion_detail_id="DET-001",
        cantidad=Decimal("1"),
        fecha=fecha,
    )


def test_a6_los_insumos_se_bloquean_por_clave_antes_de_reservar(taller):
    """Despues de la Orden y antes del primer movimiento, aunque el
    dominio los traiga en otro orden. La lista vuelve en su orden."""
    repo, unidad, _, tomadas = taller
    orden_id = tomadas[0][0]
    nombres = _consultas_de(unidad)
    with unidad.transaccion():
        orden = repo.obtener_para_modificar(orden_id)
        orden.movimientos_insumo += [
            _reserva("MOV-B", f.INSUMO_PANTALLA, orden.updated_at),
            _reserva("MOV-A", f.INSUMO_BATERIA, orden.updated_at),
        ]
        repo.guardar(orden)
    assert nombres.index("ordenes.bloquear") < nombres.index(
        "catalogos.bloquear_insumos"
    )
    assert nombres.index("catalogos.bloquear_insumos") < nombres.index(
        "ordenes.insertar_movimiento"
    )
    assert [m.id for m in repo.obtener(orden_id).movimientos_insumo] == [
        "MOV-B",
        "MOV-A",
    ]


def test_a6_un_key_share_sobre_el_insumo_no_frena_la_reserva(
    armar, base, tmp_path
):
    """QA-A2-M4: otra transaccion referencia el insumo (KEY SHARE, como una
    clave foranea). Con FOR UPDATE la reserva esperaba hasta agotar el
    bloqueo; con FOR NO KEY UPDATE, sigue."""
    f.sembrar(tmp_path)
    with TestClient(
        create_app(Settings(data_dir=tmp_path, fotos_dir=tmp_path / "f"))
    ) as cliente:
        orden_id = f.definida(cliente, f.BATERIA)
        f.tomada(cliente, orden_id)
    _fijar(base, 5)
    repo, unidad = armar(lock_timeout_ms=1000)
    repo.guardar(
        JsonOrdenReparacionRepository(tmp_path / "ordenes").listar()[0]
    )
    contexto = ApplicationContext(
        ordenes=repo,
        catalogos=PostgresCatalogosRepository(unidad),
        unidad_de_trabajo=unidad,
    )
    with psycopg.connect(base) as otra:
        otra.execute(
            "select 1 from rma.insumo where clave = %s for key share",
            (INSUMO,),
        )
        reservada = _iniciar(contexto, orden_id, f.TECNICO)
        otra.rollback()
    assert _reservo(reservada)


# --- Atomicidad y duplicados ------------------------------------------------


def test_a6_un_error_despues_de_reservar_no_deja_nada(taller, base):
    repo, unidad, _, tomadas = taller
    orden_id = tomadas[0][0]
    antes, version = _stock(base), _version(base, orden_id)
    with pytest.raises(PersistenciaError, match="no tiene equivalencia"):
        with unidad.transaccion():
            orden = repo.obtener_para_modificar(orden_id)
            orden.movimientos_insumo.append(
                _reserva("MOV-X", INSUMO, orden.updated_at)
            )
            orden.historial.append(
                HistorialWorkflow(
                    referencia_id="ACC-REP-999",
                    accion="SIN_EQUIVALENCIA",
                    fecha=orden.updated_at,
                )
            )
            repo.guardar(orden)
    assert _stock(base) == antes
    assert _version(base, orden_id) == version
    assert _sql(
        base,
        "select count(*) from rma.movimiento_inventario "
        "where tipo = 'RESERVA'",
    ) == [(0,)]


def test_a6_un_movimiento_repetido_no_se_duplica(taller, base):
    repo, unidad, contexto, tomadas = taller
    (primera, tecnico), (segunda, _) = tomadas
    reservada = _iniciar(contexto, primera, tecnico)
    repetido = reservada.movimientos_insumo[0]
    antes = _stock(base)
    with pytest.raises(ConflictoDeEscrituraError):
        with unidad.transaccion():
            orden = repo.obtener_para_modificar(segunda)
            orden.movimientos_insumo.append(repetido)
            repo.guardar(orden)
    assert _stock(base) == antes
    assert not repo.obtener(segunda).movimientos_insumo


def test_a6_alterar_una_reserva_guardada_se_rechaza(taller, base):
    repo, unidad, contexto, tomadas = taller
    orden_id, tecnico = tomadas[0]
    _iniciar(contexto, orden_id, tecnico)
    antes = _stock(base)
    with pytest.raises(PersistenciaError, match="movimientos de insumo"):
        with unidad.transaccion():
            orden = repo.obtener_para_modificar(orden_id)
            orden.movimientos_insumo[0] = orden.movimientos_insumo[
                0
            ].model_copy(update={"cantidad": Decimal("2")})
            repo.guardar(orden)
    assert _stock(base) == antes


# --- QA-A2-M1 ---------------------------------------------------------------


def test_m1_dos_lineas_del_mismo_insumo(taller, base):
    repo, unidad, contexto, tomadas = taller
    orden_id, tecnico = tomadas[0]
    _iniciar(contexto, orden_id, tecnico)
    with unidad.transaccion():
        orden = repo.obtener_para_modificar(orden_id)
        orden.ejecuciones[0] = orden.ejecuciones[0].model_copy(
            update={
                "insumos_utilizados": [
                    InsumoUtilizado(insumo_id=INSUMO, cantidad=Decimal("0.5")),
                    InsumoUtilizado(insumo_id=INSUMO, cantidad=Decimal("0.5")),
                ]
            }
        )
        repo.guardar(orden)
    assert repo.obtener(orden_id) == orden
    assert _sql(
        base,
        "select utilizada_declarada from rma.v_ejecucion_insumo_consumo",
    ) == [(Decimal("1.000"),)]


# --- A5-2: consultas con reservas reales ------------------------------------


@pytest.mark.parametrize("en_comando", [False, True])
def test_a5_2_las_consultas_ven_las_reservas(taller, en_comando):
    repo, unidad, contexto, tomadas = taller
    (con_reserva, tecnico), (sin_reserva, _) = tomadas
    _iniciar(contexto, con_reserva, tecnico)

    def ids(ordenes):
        return [o.id for o in ordenes]

    def consultar():
        assert ids(repo.listar_con_reservas()) == [con_reserva]
        assert ids(repo.listar_con_reservas([INSUMO])) == [con_reserva]
        assert repo.listar_con_reservas([f.INSUMO_PANTALLA]) == []
        assert ids(repo.listar_con_movimientos()) == [con_reserva]
        assert ids(repo.listar_con_movimientos(INSUMO)) == [con_reserva]
        assert repo.listar_con_movimientos("INS-0") == []
        assert sin_reserva not in ids(repo.listar_con_reservas())

    if en_comando:
        with unidad.transaccion():
            consultar()
    else:
        consultar()


def test_a6_el_contexto_json_no_cambia(tmp_path):
    """JSON: ``bloquear_insumos`` no hace nada y la reserva es la de
    siempre."""
    f.sembrar(tmp_path)
    configuracion = Settings(data_dir=tmp_path, fotos_dir=tmp_path / "f")
    with TestClient(create_app(configuracion)) as cliente:
        orden_id = f.definida(cliente, f.BATERIA)
        f.tomada(cliente, orden_id)
    from app.application import construir_contexto

    contexto = construir_contexto(configuracion)
    contexto.catalogos.bloquear_insumos([INSUMO])
    reservada = _iniciar(contexto, orden_id, f.TECNICO)
    assert _reservo(reservada)
