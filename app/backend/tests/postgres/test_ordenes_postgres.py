"""Orden de Reparacion en PostgreSQL: alta, lectura y guardado incremental
(E4, slices A1 y A2).

Contra la base local descartable. Cada prueba usa una base propia,
clonada de una plantilla con las migraciones, la carga de referencia y los
catalogos del corpus (``corpus_ordenes.py``).

Semantica que se verifica:

- ``obtener(guardar(o)) == o`` en cada paso de flujos reales (DA-5).
- ``guardar`` sin cambios no escribe ni cambia la version; cada
  ``guardar`` con cambios sube la version en 1, tambien si el cambio no
  deja historial (DA-2).
- Los comandos sobre la misma Orden se serializan (``FOR NO KEY UPDATE``):
  el segundo lee lo que confirmo el primero, sin perder cambios.
- Una version obsoleta da ``ConflictoDeEscrituraError`` y no escribe nada;
  una entrada inmutable alterada dentro del comando da ``PersistenciaError``.
- Una Orden existente que no viene de ``obtener_para_modificar`` en esta
  transaccion se rechaza sin escribir (QA-A2-H1).
- Todo o nada: un error a mitad de ``guardar`` revierte la Orden, sus
  hijas y la accion del comando.

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (secciones 3, 4 y 8).
"""

import copy
import threading
import time
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.application import (  # noqa: E402
    cambiar_prioridad_de_orden,
    cancelar_detalle,
    crear_orden,
    crear_orden_rt,
    definir_reparacion,
)
from app.application.contexto import ApplicationContext  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.domain.models import (  # noqa: E402
    Cliente,
    Equipo,
    EstadoWorkflow,
    HistorialWorkflow,
    MovimientoInsumo,
    OrdenReparacion,
)
from app.main import create_app  # noqa: E402
from app.repositories.exceptions import (  # noqa: E402
    ConflictoDeEscrituraError,
    DatosInvalidosError,
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
    RestriccionDeIntegridadError,
    TransaccionInvalidadaError,
)
from app.storage.json.catalogos import JsonCatalogosRepository  # noqa: E402
from app.storage.json.ordenes import (
    JsonOrdenReparacionRepository,  # noqa: E402
)
from app.storage.postgres import (  # noqa: E402
    AjustesPostgres,
    configuracion_postgres,
)
from app.storage.postgres.ordenes import (  # noqa: E402
    _INSTANTANEAS,
    PostgresOrdenReparacionRepository,
    _marca_de,
    _marcar,
)
from app.storage.postgres.transaccion import (  # noqa: E402
    UnidadDeTrabajoPostgres,
    abrir_pool,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres.base_local import (  # noqa: E402
    archivos_sql,
    borrar_base,
    clonar_base,
    crear_base,
    url_admin_local,
)
from tests.postgres.corpus_ordenes import (  # noqa: E402
    _flujos,
    _flujos_de_salida,
    armar_corpus,
)
from tests.postgres.sembrado import sembrar_catalogos  # noqa: E402

TABLAS = (
    "orden",
    "cliente",
    "equipo",
    "recepcion",
    "detalle",
    "detalle_version",
    "decision_cliente",
    "toma",
    "ejecucion",
    "evento_negocio",
    "accion_usuario",
)


# --- Bases y repositories --------------------------------------------------


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    directorio = tmp_path_factory.mktemp("corpus_e4")
    return directorio, armar_corpus(directorio)


@pytest.fixture(scope="module")
def plantilla(postgres_descartable, corpus):
    url = urlsplit(postgres_descartable)
    admin = url_admin_local(url._replace(path="/postgres").geturl())
    base = crear_base(
        admin, [a for a in archivos_sql() if a.parent.name != "desarrollo"]
    )
    with psycopg.connect(base, autocommit=True) as conexion:
        sembrar_catalogos(conexion, corpus[0])
    nombre = urlsplit(base).path.lstrip("/")
    yield admin, nombre
    borrar_base(admin, nombre)


@pytest.fixture
def base(plantilla):
    admin, nombre = plantilla
    url = clonar_base(admin, nombre)
    yield url
    borrar_base(admin, urlsplit(url).path.lstrip("/"))


@pytest.fixture
def armar(base):
    pools = []

    def _armar(**valores):
        configuracion = configuracion_postgres(
            Settings(
                _env_file=None, persistencia="postgres", database_url=base
            )
        )
        ajustes = AjustesPostgres(**{"pool_max": 3, **valores})
        pool = abrir_pool(configuracion, ajustes)
        pool.wait(10)
        pools.append(pool)
        unidad = UnidadDeTrabajoPostgres(pool, ajustes)
        return PostgresOrdenReparacionRepository(unidad), unidad

    yield _armar
    for pool in pools:
        pool.close()


def _sql(url, texto, parametros=()):
    with psycopg.connect(url, autocommit=True) as conexion:
        return conexion.execute(texto, parametros).fetchall()


def _ejecutar(url, texto, parametros=()) -> None:
    with psycopg.connect(url, autocommit=True) as conexion:
        conexion.execute(texto, parametros)


def _cuentas(url) -> dict[str, int]:
    return {
        tabla: _sql(url, f"select count(*) from rma.{tabla}")[0][0]
        for tabla in TABLAS
    }


def _version(url, codigo) -> int:
    return _sql(
        url, "select version from rma.orden where codigo = %s", (codigo,)
    )[0][0]


def _ultimos(corpus):
    """La ultima version de cada Orden del corpus."""
    ultimas = {}
    for orden in corpus[1]:
        ultimas[orden.id] = orden
    return ultimas


def _con_ejecuciones(corpus):
    return next(o for o in _ultimos(corpus).values() if o.ejecuciones)


def _aplicar(orden, paso):
    """Lo que hace un comando: cambia la Orden que recibio."""
    for campo in type(paso).model_fields:
        setattr(orden, campo, getattr(paso, campo))
    return orden


def _como_comando(repo, paso):
    """La Orden de ``obtener_para_modificar`` con el paso del corpus."""
    return _aplicar(repo.obtener_para_modificar(paso.id), paso)


def _guardar_paso(repo, unidad, orden, existe):
    with unidad.transaccion():
        repo.guardar(_como_comando(repo, orden) if existe else orden)


# --- A1: alta y lectura ----------------------------------------------------


def test_cada_paso_de_los_flujos_vuelve_identico(armar, base, corpus):
    """El corpus completo, paso a paso: cada Orden guardada se relee igual,
    tambien en su forma JSON; la version sube 1 por paso con cambios."""
    repo, unidad = armar()
    guardadas: dict = {}
    for orden in corpus[1]:
        anterior = guardadas.get(orden.id)
        _guardar_paso(repo, unidad, orden, anterior is not None)
        leida = repo.obtener(orden.id)
        assert leida == orden
        assert leida.model_dump(mode="json") == orden.model_dump(mode="json")
        version_esperada = (
            1
            if anterior is None
            else anterior[1] + (0 if anterior[0] == orden else 1)
        )
        assert _version(base, orden.id) == version_esperada
        guardadas[orden.id] = (orden, version_esperada)
    # Y la lectura de todas juntas devuelve lo mismo, en el mismo orden.
    assert repo.listar() == sorted(
        (o for o, _ in guardadas.values()), key=lambda o: o.id
    )


def test_el_cliente_compartido_y_su_documento(armar, base, corpus):
    repo, unidad = armar()
    con_dni = [
        o for o in _ultimos(corpus).values() if o.cliente and o.cliente.dni
    ]
    assert len(con_dni) == 2 and con_dni[0].cliente.id == con_dni[1].cliente.id
    for orden in con_dni:
        repo.guardar(orden)
    assert _sql(
        base,
        "select count(*), count(distinct o.cliente_id) from rma.orden o "
        "where o.cliente_documento_numero = %s",
        (con_dni[0].cliente.dni,),
    ) == [(2, 1)]
    assert _sql(
        base,
        "select numero_normalizado from rma.documento_cliente "
        "where vigente_hasta is null",
    ) == [(con_dni[0].cliente.dni,)]


def test_guardar_fuera_de_una_transaccion_abre_la_suya(armar, corpus):
    repo, unidad = armar()
    orden = corpus[1][0]
    repo.guardar(orden)
    assert not unidad.en_curso()
    assert repo.obtener(orden.id) == orden


def test_un_alta_que_falla_no_deja_nada(armar, base, corpus):
    """El error llega despues de insertar la Orden, el cliente, el equipo
    y la recepcion: no queda ninguna fila, ni la accion del comando."""
    repo, _ = armar()
    orden = _con_ejecuciones(corpus).model_copy(deep=True)
    orden.historial.append(
        HistorialWorkflow(
            referencia_id="ACC-REP-999",
            accion="SIN_EQUIVALENCIA",
            fecha=orden.updated_at,
        )
    )
    antes = _cuentas(base)
    with pytest.raises(PersistenciaError, match="no tiene equivalencia"):
        repo.guardar(orden)
    assert _cuentas(base) == antes


def test_lo_que_todavia_no_se_guarda_se_rechaza_sin_escribir(
    armar, base, corpus
):
    repo, _ = armar()
    orden = corpus[1][0].model_copy(deep=True)
    orden.movimientos_insumo.append(
        MovimientoInsumo(
            id="MOV-1",
            tipo="DEVOLUCION",
            insumo_id="INS-001",
            reparacion_detail_id="DET-001",
            cantidad=Decimal("1"),
            movimiento_origen_id="MOV-0",
            fecha=orden.updated_at,
        )
    )
    antes = _cuentas(base)
    with pytest.raises(PersistenciaError, match="DI-5"):
        repo.guardar(orden)
    assert _cuentas(base) == antes


def test_un_codigo_inexistente_en_la_base_es_un_error(armar, base, corpus):
    repo, _ = armar()
    orden = _con_ejecuciones(corpus).model_copy(deep=True)
    orden.tomas[0].usuario_id = "NADIE-001"
    with pytest.raises(PersistenciaError, match="NADIE-001"):
        repo.guardar(orden)
    assert _cuentas(base)["orden"] == 0


def test_un_precio_con_mas_decimales_que_la_columna_se_rechaza(armar, corpus):
    repo, _ = armar()
    orden = _con_ejecuciones(corpus).model_copy(deep=True)
    orden.reparaciones_detail[0].precio = Decimal("80000.555")
    with pytest.raises(PersistenciaError, match="decimales"):
        repo.guardar(orden)


def test_numeracion_concurrente_unica_y_sin_truncar(armar, base, corpus):
    """Ocho comandos reservan y guardan a la vez: numeros distintos. Por
    encima de 999999 no se trunca (QA-E2-5)."""
    repo, unidad = armar(pool_max=8)
    plantilla_ = corpus[1][0]
    reservados, errores = [], []
    barrera = threading.Barrier(8, timeout=20)

    def alta():
        try:
            barrera.wait()
            with unidad.transaccion():
                codigo = repo.reservar_codigo()
                repo.guardar(
                    plantilla_.model_copy(update={"id": codigo}, deep=True)
                )
            reservados.append(codigo)
        except Exception as error:  # noqa: BLE001
            errores.append(error)

    hilos = [threading.Thread(target=alta) for _ in range(8)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert errores == [] and len(set(reservados)) == 8
    _sql(base, "select setval('rma.orden_numero_seq', 999998)")
    with unidad.transaccion():
        grandes = [repo.reservar_codigo() for _ in range(3)]
    assert grandes == ["OR-999999", "OR-1000000", "OR-1000001"]


def test_reservar_codigo_no_devuelve_uno_ya_guardado(armar, corpus):
    repo, unidad = armar()
    repo.guardar(corpus[1][0])  # OR-000001, con numero explicito
    with unidad.transaccion():
        assert repo.reservar_codigo() == "OR-000002"
    with pytest.raises(PersistenciaError, match="transaccion en curso"):
        repo.reservar_codigo()


# --- A2: guardado incremental, versiones y conflictos ------------------------


def test_obtener_para_modificar_exige_transaccion_y_existencia(armar, corpus):
    repo, unidad = armar()
    with pytest.raises(PersistenciaError, match="transaccion en curso"):
        repo.obtener_para_modificar("OR-000001")
    with unidad.transaccion():
        with pytest.raises(EntidadPersistidaNoEncontradaError):
            repo.obtener_para_modificar("OR-999999")


def test_guardar_lo_mismo_no_escribe_nada(armar, base, corpus):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    antes = _cuentas(base), _version(base, orden.id)
    with unidad.transaccion():
        repo.guardar(repo.obtener_para_modificar(orden.id))
    assert (_cuentas(base), _version(base, orden.id)) == antes


def test_un_cambio_sin_historial_tambien_sube_la_version(armar, base, corpus):
    """La version representa todo cambio durable, aunque no deje evento."""
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    eventos = _cuentas(base)["evento_negocio"]
    with unidad.transaccion():
        modificada = repo.obtener_para_modificar(orden.id)
        modificada.prioridad += 1
        repo.guardar(modificada)
    assert _version(base, orden.id) == 2
    assert _cuentas(base)["evento_negocio"] == eventos
    assert repo.obtener(orden.id).prioridad == orden.prioridad + 1


def _dos_comandos(repo, unidad, codigo, primero, segundo):
    """``primero`` toma la Orden y espera; ``segundo`` queda bloqueado
    hasta que el primero confirma, y entonces lee su resultado."""
    tomada, soltar, leidas, errores = (
        threading.Event(),
        threading.Event(),
        [],
        [],
    )

    def comando_a():
        try:
            with unidad.transaccion():
                orden = repo.obtener_para_modificar(codigo)
                tomada.set()
                soltar.wait(10)
                repo.guardar(primero(orden))
        except Exception as error:  # noqa: BLE001
            errores.append(error)

    def comando_b():
        try:
            tomada.wait(10)
            with unidad.transaccion():
                orden = repo.obtener_para_modificar(codigo)  # espera a A
                leidas.append(orden.model_copy(deep=True))
                repo.guardar(segundo(orden))
        except Exception as error:  # noqa: BLE001
            errores.append(error)

    hilo_a = threading.Thread(target=comando_a)
    hilo_b = threading.Thread(target=comando_b)
    hilo_a.start()
    hilo_b.start()
    time.sleep(0.3)
    assert not leidas  # B sigue esperando el bloqueo de A
    soltar.set()
    hilo_a.join(15)
    hilo_b.join(15)
    assert errores == []
    return leidas[0]


def test_dos_comandos_sobre_campos_distintos_conservan_los_dos(
    armar, base, corpus
):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)

    def subir_prioridad(o):
        o.prioridad = 4
        return o

    def anotar_referencia(o):
        o.referencia_rt = "RT-99"
        return o

    leida_por_b = _dos_comandos(
        repo, unidad, orden.id, subir_prioridad, anotar_referencia
    )
    assert leida_por_b.prioridad == 4
    final = repo.obtener(orden.id)
    assert (final.prioridad, final.referencia_rt) == (4, "RT-99")
    assert _version(base, orden.id) == 3


def test_dos_comandos_sobre_el_mismo_campo_no_pierden_el_primero(
    armar, base, corpus
):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)

    def a_tres(o):
        o.prioridad = 3
        return o

    def sumar_uno(o):
        o.prioridad += 1  # parte del valor que confirmo A
        return o

    leida_por_b = _dos_comandos(repo, unidad, orden.id, a_tres, sumar_uno)
    assert leida_por_b.prioridad == 3
    assert repo.obtener(orden.id).prioridad == 4


def test_guardar_una_lectura_vieja_se_rechaza(armar, base, corpus):
    """Sin instantanea (leida en otra transaccion) y con historial ajeno:
    se rechaza y no escribe nada."""
    repo, unidad = armar()
    pasos = [o for o in corpus[1] if o.id == _con_ejecuciones(corpus).id]
    repo.guardar(pasos[0])
    vieja = repo.obtener(pasos[0].id)
    with unidad.transaccion():
        repo.guardar(_como_comando(repo, pasos[1]))
    antes = _cuentas(base), _version(base, vieja.id)
    vieja.prioridad = 4
    vieja.historial.append(
        HistorialWorkflow(
            referencia_id="PROC-REP-170",
            accion="ENCOLAR",
            fecha=vieja.updated_at,
            usuario_id="COORD-001",
        )
    )
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        repo.guardar(vieja)
    assert (_cuentas(base), _version(base, vieja.id)) == antes


def test_una_version_obsoleta_es_conflicto_y_no_escribe(armar, base, corpus):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    antes = _cuentas(base), _version(base, orden.id)
    with pytest.raises(ConflictoDeEscrituraError, match="version 0"):
        with unidad.transaccion():
            modificada = repo.obtener_para_modificar(orden.id)
            unidad.datos_de_transaccion()[_INSTANTANEAS][orden.id].version = 0
            modificada.prioridad = 4
            repo.guardar(modificada)
    assert (_cuentas(base), _version(base, orden.id)) == antes


@pytest.mark.parametrize(
    "alterar",
    [
        lambda o: setattr(o.historial[0], "observacion", "otra cosa"),
        lambda o: o.historial.pop(),
        lambda o: o.reparaciones_detail.pop(),
        lambda o: o.reparaciones_detail[0].autorizaciones.clear(),
        lambda o: setattr(o.ejecuciones[0], "observaciones", "cambiada"),
        lambda o: setattr(o, "created_at", o.created_at + timedelta(days=1)),
        lambda o: setattr(o.reparaciones_detail[0], "precio", Decimal("1")),
    ],
    ids=[
        "paso del historial",
        "historial que se achica",
        "Detalle quitado",
        "decisiones borradas",
        "Ejecucion terminada",
        "fecha de alta",
        "definicion vigente sin version",
    ],
)
def test_alterar_lo_inmutable_es_un_error_y_no_escribe(
    armar, base, corpus, alterar
):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    antes = _cuentas(base), _version(base, orden.id)
    with pytest.raises(PersistenciaError, match="inmutable"):
        with unidad.transaccion():
            modificada = repo.obtener_para_modificar(orden.id)
            alterar(modificada)
            repo.guardar(modificada)
    assert (_cuentas(base), _version(base, orden.id)) == antes
    assert repo.obtener(orden.id) == orden


def test_un_error_a_mitad_del_guardado_revierte_todo(armar, base, corpus):
    """El Detalle nuevo y la accion ya se insertaron cuando falla el paso
    sin equivalencia: no queda nada de ese comando."""
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    antes = _cuentas(base), _version(base, orden.id)
    with pytest.raises(PersistenciaError, match="equivalencia"):
        with unidad.transaccion():
            modificada = repo.obtener_para_modificar(orden.id)
            nuevo = modificada.reparaciones_detail[0].model_copy(deep=True)
            nuevo.id = "DET-009"
            nuevo.autorizaciones = []
            nuevo.controles = []
            modificada.reparaciones_detail.append(nuevo)
            modificada.historial.append(
                HistorialWorkflow(
                    referencia_id="PROC-REP-070",
                    accion="AGREGAR_DETALLE",
                    fecha=modificada.updated_at,
                    usuario_id="RECEP-001",
                )
            )
            modificada.historial.append(
                HistorialWorkflow(
                    referencia_id="ACC-REP-999",
                    accion="SIN_EQUIVALENCIA",
                    fecha=modificada.updated_at,
                )
            )
            repo.guardar(modificada)
    assert (_cuentas(base), _version(base, orden.id)) == antes


def test_el_bloqueo_se_retiene_y_se_libera_al_revertir(armar, corpus):
    """Mientras un comando tiene la Orden, otro espera; con lock_timeout
    agotado recibe 409 reintentable, sin reintento automatico. Al revertir
    el primero, el otro la toma."""
    repo, unidad = armar(lock_timeout_ms=300)
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    tomada, soltar = threading.Event(), threading.Event()

    def comando_que_falla():
        try:
            with unidad.transaccion():
                repo.obtener_para_modificar(orden.id)
                tomada.set()
                soltar.wait(10)
                raise RuntimeError("falla el comando")
        except RuntimeError:
            pass

    hilo = threading.Thread(target=comando_que_falla)
    hilo.start()
    assert tomada.wait(10)
    with pytest.raises(ConflictoDeEscrituraError) as capturado:
        with unidad.transaccion():
            repo.obtener_para_modificar(orden.id)
    assert capturado.value.reintentable
    soltar.set()
    hilo.join(10)
    with unidad.transaccion():
        assert repo.obtener_para_modificar(orden.id) == orden


def test_una_orden_cerrada_no_se_modifica(armar, base, corpus):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    with unidad.transaccion():
        cerrada = repo.obtener_para_modificar(orden.id)
        cerrada.current_process = "EVT-REP-999"
        repo.guardar(cerrada)
    assert _sql(
        base,
        "select cerrada_en is not null from rma.orden where codigo = %s",
        (orden.id,),
    ) == [(True,)]
    with pytest.raises(ConflictoDeEscrituraError, match="cerrada"):
        with unidad.transaccion():
            otra = repo.obtener_para_modificar(orden.id)
            otra.prioridad = 4
            repo.guardar(otra)
    # La base lo respalda: entregada sin fecha de cierre no se admite (F-06).
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(
            base,
            "insert into rma.orden (origen, estado_workflow, "
            "posicion_proceso, "
            "equipo_id, equipo_marca, equipo_modelo, falla_reportada) "
            "select 'RT_INTERNO', 'ENTREGADA', 'PROC-REP-300', id, "
            "'x', 'y', "
            "'z' from rma.equipo limit 1",
        )


def test_dos_guardar_en_el_mismo_comando(armar, base, corpus):
    """Como el 210 y el 211 (DI-7): el segundo compara contra el primero."""
    repo, unidad = armar()
    pasos = [o for o in corpus[1] if o.id == _con_ejecuciones(corpus).id]
    repo.guardar(pasos[0])
    acciones = _cuentas(base)["accion_usuario"]
    with unidad.transaccion():
        orden = _como_comando(repo, pasos[1])
        repo.guardar(orden)
        repo.guardar(_aplicar(orden, pasos[2]))
    assert repo.obtener(pasos[0].id) == pasos[2]
    assert _version(base, pasos[0].id) == 3
    # Un comando, una accion: el segundo guardar reusa la del primero.
    assert _cuentas(base)["accion_usuario"] == acciones + 1


def test_una_sola_accion_por_comando_y_ninguna_si_se_revierte(
    armar, base, corpus
):
    repo, unidad = armar()
    pasos = [o for o in corpus[1] if o.id == _con_ejecuciones(corpus).id]
    repo.guardar(pasos[0])
    acciones = _cuentas(base)["accion_usuario"]
    with unidad.transaccion():
        repo.guardar(_como_comando(repo, pasos[1]))
    assert _cuentas(base)["accion_usuario"] == acciones + 1
    # Todos los eventos de ese comando apuntan a esa accion, CONFIRMADA.
    assert _sql(
        base,
        "select count(distinct e.accion_id), min(a.resultado) "
        "from rma.evento_negocio e join rma.accion_usuario a "
        "on a.id = e.accion_id where a.id = (select id from "
        "rma.accion_usuario order by registrada_en desc, id limit 1)",
    ) == [(1, "CONFIRMADA")]
    with pytest.raises(RuntimeError):
        with unidad.transaccion():
            repo.guardar(_como_comando(repo, pasos[2]))
            raise RuntimeError("se revierte")
    assert _cuentas(base)["accion_usuario"] == acciones + 1


# --- A0: migracion aditiva ---------------------------------------------------


def test_la_migracion_de_e4_es_aditiva_sobre_datos_existentes(plantilla):
    """Sobre una base con datos anteriores a E4: agrega columnas y la
    funcion de numeracion sin tocar lo cargado; los medios de pago que ya
    estaban no cambian (idempotente)."""
    admin, _ = plantilla
    migracion = next(
        a for a in archivos_sql() if a.name.endswith("_e4_agregado.sql")
    )
    url = crear_base(
        admin,
        [
            a
            for a in archivos_sql()
            if a.parent.name == "migrations" and a.name < migracion.name
        ],
    )
    try:
        _ejecutar(
            url,
            "insert into rma.medio_pago (codigo, nombre, orden) "
            "values ('EFECTIVO', 'Caja', 9)",
        )
        _ejecutar(url, migracion.read_text(encoding="utf-8"))
        assert _sql(
            url,
            "select nombre, orden from rma.medio_pago "
            "where codigo = 'EFECTIVO'",
        ) == [("Caja", 9)]
        assert _sql(url, "select count(*) from rma.medio_pago") == [(5,)]
        assert _sql(url, "select rma.formatear_numero_orden(1234567)") == [
            ("OR-1234567",)
        ]
    finally:
        borrar_base(admin, urlsplit(url).path.lstrip("/"))


# --- QA-A2-H1: guardar exige la instantanea de esta transaccion ------------
#
# Una Orden existente solo se guarda si viene de obtener_para_modificar en
# la misma transaccion. Cualquier otra cosa se rechaza sin escribir: es lo
# que evita pisar en silencio un campo mutable que cambio otro comando.


def _estado(base, codigo):
    return (
        _cuentas(base),
        _sql(
            base,
            "select version, prioridad, referencia_rt, actualizado_en "
            "from rma.orden where codigo = %s",
            (codigo,),
        ),
    )


def _rechazado(repo, base, orden):
    """``guardar`` rechaza ``orden`` y no escribe nada."""
    antes = _estado(base, orden.id)
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        repo.guardar(orden)
    assert _estado(base, orden.id) == antes


def _prioridad_a_cuatro(repo, unidad, codigo):
    """Otro comando cambia un campo mutable que no deja historial."""
    with unidad.transaccion():
        otra = repo.obtener_para_modificar(codigo)
        otra.prioridad = 4
        repo.guardar(otra)


def test_h1_una_lectura_vieja_no_pierde_la_prioridad(armar, base, corpus):
    """La reproduccion de la QA: antes, la prioridad volvia a su valor
    viejo sin conflicto y la version subia."""
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    vieja = repo.obtener(orden.id)
    _prioridad_a_cuatro(repo, unidad, orden.id)
    vieja.referencia_rt = "RT-A"
    _rechazado(repo, base, vieja)
    final = repo.obtener(orden.id)
    assert (final.prioridad, final.referencia_rt) == (4, orden.referencia_rt)


def test_h1_una_copia_vieja_sin_cambios_no_revierte(armar, base, corpus):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    vieja = repo.obtener(orden.id)
    _prioridad_a_cuatro(repo, unidad, orden.id)
    _rechazado(repo, base, vieja)
    assert repo.obtener(orden.id).prioridad == 4


def test_h1_una_orden_de_obtener_se_rechaza_sin_comando(armar, base, corpus):
    repo, _ = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    leida = repo.obtener(orden.id)
    leida.prioridad = 2
    _rechazado(repo, base, leida)


def test_h1_una_lectura_previa_se_rechaza_aunque_haya_instantanea(
    armar, base, corpus
):
    """Hay instantanea de esa Orden, pero lo que llega no viene de ella: el
    contenido no alcanza para distinguirlo de un cambio legitimo."""
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    vieja = repo.obtener(orden.id)
    _prioridad_a_cuatro(repo, unidad, orden.id)
    antes = _estado(base, orden.id)
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        with unidad.transaccion():
            repo.obtener_para_modificar(orden.id)
            repo.guardar(vieja)
    assert _estado(base, orden.id) == antes
    assert repo.obtener(orden.id).prioridad == 4


def test_h1_obtener_dentro_del_comando_tampoco_vale(armar, base, corpus):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    antes = _estado(base, orden.id)
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        with unidad.transaccion():
            repo.obtener_para_modificar(orden.id)
            leida = repo.obtener(orden.id)
            leida.prioridad = 2
            repo.guardar(leida)
    assert _estado(base, orden.id) == antes


def test_h1_la_instantanea_de_otra_orden_no_vale(armar, base, corpus):
    repo, unidad = armar()
    uno, otro = list(_ultimos(corpus).values())[:2]
    repo.guardar(uno)
    repo.guardar(otro)
    leida = repo.obtener(uno.id)
    antes = _estado(base, uno.id)
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        with unidad.transaccion():
            repo.obtener_para_modificar(otro.id)
            repo.guardar(leida)
    assert _estado(base, uno.id) == antes


def test_h1_una_orden_con_la_identidad_cambiada_no_vale(armar, base, corpus):
    """Las dos instantaneas existen, pero la Orden salio de la otra."""
    repo, unidad = armar()
    uno, otro = list(_ultimos(corpus).values())[:2]
    repo.guardar(uno)
    repo.guardar(otro)
    antes = _estado(base, uno.id)
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        with unidad.transaccion():
            repo.obtener_para_modificar(uno.id)
            ajena = repo.obtener_para_modificar(otro.id)
            repo.guardar(ajena.model_copy(update={"id": uno.id}))
    assert _estado(base, uno.id) == antes


def test_h1_una_orden_con_otro_codigo_no_se_vuelve_un_alta(
    armar, base, corpus
):
    """Sin fila ni instantanea con ese codigo, pero salio de otra Orden."""
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    antes = _cuentas(base)
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        with unidad.transaccion():
            cargada = repo.obtener_para_modificar(orden.id)
            repo.guardar(cargada.model_copy(update={"id": "OR-999999"}))
    assert _cuentas(base) == antes


def test_h1_la_instantanea_de_una_transaccion_terminada_no_vale(
    armar, base, corpus
):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    with unidad.transaccion():
        vieja = repo.obtener_para_modificar(orden.id)
    _prioridad_a_cuatro(repo, unidad, orden.id)
    _rechazado(repo, base, vieja)
    antes = _estado(base, orden.id)
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        with unidad.transaccion():
            repo.obtener_para_modificar(orden.id)  # otra instantanea
            repo.guardar(vieja)
    assert _estado(base, orden.id) == antes


def test_h1_la_instantanea_de_otra_transaccion_en_curso_no_vale(
    armar, base, corpus
):
    """Otro hilo, mientras la duena sigue abierta: no espera el bloqueo ni
    usa la instantanea ajena."""
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    tomada, soltar, capturados = threading.Event(), threading.Event(), []
    orden_de_a = []

    def comando_a():
        with unidad.transaccion():
            orden_de_a.append(repo.obtener_para_modificar(orden.id))
            tomada.set()
            soltar.wait(10)

    hilo = threading.Thread(target=comando_a)
    hilo.start()
    assert tomada.wait(10)
    try:
        repo.guardar(orden_de_a[0])
    except PersistenciaError as error:
        capturados.append(error)
    finally:
        soltar.set()
        hilo.join(10)
    assert len(capturados) == 1
    assert "obtener_para_modificar" in str(capturados[0])
    assert _version(base, orden.id) == 1


def test_h1_lo_que_deriva_de_la_instantanea_se_guarda(armar, base, corpus):
    """Los services devuelven copias: siguen siendo la Orden del comando."""
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    with unidad.transaccion():
        cargada = repo.obtener_para_modificar(orden.id)
        copia = cargada.model_copy(deep=True)
        copia.prioridad = 1
        repo.guardar(copia)
        segunda = copia.model_copy(update={"referencia_rt": "RT-9"})
        repo.guardar(segunda)
    final = repo.obtener(orden.id)
    assert (final.prioridad, final.referencia_rt) == (1, "RT-9")
    assert _version(base, orden.id) == 3


def test_h1_despues_de_guardar_se_sigue_exigiendo_la_procedencia(
    armar, base, corpus
):
    """El segundo guardar del comando no abre la puerta a una lectura."""
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    vieja = repo.obtener(orden.id)
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        with unidad.transaccion():
            cargada = repo.obtener_para_modificar(orden.id)
            cargada.prioridad = 1
            repo.guardar(cargada)
            repo.guardar(vieja)
    assert repo.obtener(orden.id).prioridad == orden.prioridad
    assert _version(base, orden.id) == 1


def test_h1_releer_en_el_comando_no_invalida_lo_ya_cargado(
    armar, base, corpus
):
    """Un comando anidado vuelve a pedir la Orden en la misma transaccion."""
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    with unidad.transaccion():
        primera = repo.obtener_para_modificar(orden.id)
        repo.obtener_para_modificar(orden.id)
        primera.prioridad = 1
        repo.guardar(primera)
    assert repo.obtener(orden.id).prioridad == 1


def test_h1_el_alta_no_necesita_instantanea(armar, base, corpus):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    with unidad.transaccion():
        repo.guardar(orden)
        # La fila es de esta transaccion: nadie mas pudo escribirla.
        orden.prioridad = 2
        repo.guardar(orden)
    assert repo.obtener(orden.id).prioridad == 2
    assert _version(base, orden.id) == 2


def test_h1_un_alta_repetida_no_se_vuelve_una_actualizacion(
    armar, base, corpus
):
    repo, _ = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    repetida = orden.model_copy(deep=True)
    repetida.prioridad = 2
    _rechazado(repo, base, repetida)
    assert repo.obtener(orden.id).prioridad == orden.prioridad


def test_h1_dos_altas_simultaneas_del_mismo_codigo(armar, base, corpus):
    """La segunda no ve la fila sin confirmar: la frena la unicidad, no se
    convierte en una actualizacion."""
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    insertada, soltar, resultados = threading.Event(), threading.Event(), []

    def primera():
        with unidad.transaccion():
            repo.guardar(orden)
            insertada.set()
            soltar.wait(10)

    def segunda():
        insertada.wait(10)
        otra = orden.model_copy(deep=True)
        otra.prioridad = 2
        try:
            repo.guardar(otra)
            resultados.append("guardada")
        except ConflictoDeEscrituraError as error:
            resultados.append(error.sqlstate)

    hilos = [threading.Thread(target=f) for f in (primera, segunda)]
    for hilo in hilos:
        hilo.start()
    assert insertada.wait(10)
    time.sleep(0.3)
    soltar.set()
    for hilo in hilos:
        hilo.join(15)
    assert resultados == ["23505"]
    assert repo.obtener(orden.id).prioridad == orden.prioridad
    assert _version(base, orden.id) == 1


def test_h1_un_rechazo_revierte_todo_el_comando(armar, base, corpus):
    repo, unidad = armar()
    uno, otro = list(_ultimos(corpus).values())[:2]
    repo.guardar(uno)
    repo.guardar(otro)
    leida = repo.obtener(otro.id)
    antes = _cuentas(base), _version(base, uno.id), _version(base, otro.id)
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        with unidad.transaccion():
            modificada = repo.obtener_para_modificar(uno.id)
            modificada.prioridad = 2
            repo.guardar(modificada)
            repo.guardar(leida)
    assert antes == (
        _cuentas(base),
        _version(base, uno.id),
        _version(base, otro.id),
    )
    assert repo.obtener(uno.id).prioridad == uno.prioridad


def test_h1_atrapar_el_rechazo_no_salva_el_comando(armar, base, corpus):
    """El comando quedo invalidado: nada de lo anterior se confirma."""
    repo, unidad = armar()
    uno, otro = list(_ultimos(corpus).values())[:2]
    repo.guardar(uno)
    repo.guardar(otro)
    leida = repo.obtener(otro.id)
    with pytest.raises(TransaccionInvalidadaError):
        with unidad.transaccion():
            modificada = repo.obtener_para_modificar(uno.id)
            modificada.prioridad = 2
            repo.guardar(modificada)
            try:
                repo.guardar(leida)
            except PersistenciaError:
                pass
    assert repo.obtener(uno.id).prioridad == uno.prioridad
    assert _version(base, uno.id) == 1


def test_h1_el_bloqueo_se_libera_despues_de_un_rechazo(armar, corpus):
    repo, unidad = armar(lock_timeout_ms=300)
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    vieja = repo.obtener(orden.id)
    with pytest.raises(PersistenciaError):
        with unidad.transaccion():
            repo.obtener_para_modificar(orden.id)
            repo.guardar(vieja)
    with unidad.transaccion():
        repo.guardar(repo.obtener_para_modificar(orden.id))


def test_h1_la_marca_no_es_parte_de_la_orden(armar, corpus):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    leida = repo.obtener(orden.id)
    with unidad.transaccion():
        entregada = repo.obtener_para_modificar(orden.id)
    assert entregada == leida
    assert entregada.model_dump(mode="json") == leida.model_dump(mode="json")
    assert entregada.model_dump_json() == leida.model_dump_json()
    # Reconstruida desde sus datos deja de ser la Orden del comando.
    assert _marca_de(entregada) is not None
    assert (
        _marca_de(OrdenReparacion.model_validate(entregada.model_dump()))
        is None
    )


@pytest.mark.parametrize(
    "copiar",
    [
        lambda o: o.model_copy(),
        lambda o: o.model_copy(deep=True),
        lambda o: o.model_copy(update={"prioridad": 2}),
        lambda o: o.model_copy(update={"prioridad": 2}, deep=True),
        copy.copy,
        copy.deepcopy,
    ],
    ids=["copia", "profunda", "update", "update-profunda", "copy", "deepcopy"],
)
def test_h1_la_marca_se_conserva_en_las_copias(armar, corpus, copiar):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    with unidad.transaccion():
        copia = copiar(repo.obtener_para_modificar(orden.id))
        copia.prioridad = 3
        repo.guardar(copia)
    assert repo.obtener(orden.id).prioridad == 3


@pytest.mark.parametrize(
    "reconstruir",
    [
        lambda o: OrdenReparacion.model_validate(o.model_dump()),
        lambda o: OrdenReparacion.model_validate_json(o.model_dump_json()),
        lambda o: OrdenReparacion(**o.model_dump()),
    ],
    ids=["model_validate", "json", "constructor"],
)
def test_h1_una_orden_reconstruida_se_rechaza(
    armar, base, corpus, reconstruir
):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    antes = _estado(base, orden.id)
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        with unidad.transaccion():
            repo.guardar(reconstruir(repo.obtener_para_modificar(orden.id)))
    assert _estado(base, orden.id) == antes


def test_h1_la_marca_llega_por_los_comandos_reales(tmp_path):
    """Los flujos reales por la API, en JSON: toda Orden existente que los
    casos de uso guardan salio de ``obtener_para_modificar``. Si un service
    la reconstruyera, en PostgreSQL ese comando se rechazaria."""
    f.sembrar(tmp_path)
    con_marca, sin_marca, altas = [], [], []
    obtener = JsonOrdenReparacionRepository.obtener_para_modificar
    guardar = JsonOrdenReparacionRepository.guardar

    def marcar(self, orden_id):
        orden = obtener(self, orden_id)
        _marcar(orden, "marca")
        return orden

    def registrar(self, orden):
        if _marca_de(orden) == "marca":
            con_marca.append(orden.id)
        elif self._ruta_de(orden.id).is_file():
            sin_marca.append(orden.id)
        else:
            altas.append(orden.id)
        guardar(self, orden)

    with pytest.MonkeyPatch.context() as parche:
        parche.setattr(
            JsonOrdenReparacionRepository, "obtener_para_modificar", marcar
        )
        parche.setattr(JsonOrdenReparacionRepository, "guardar", registrar)
        configuracion = Settings(
            data_dir=tmp_path, fotos_dir=tmp_path / "fotos"
        )
        with TestClient(create_app(configuracion)) as cliente:
            _flujos(cliente)
            _flujos_de_salida(cliente)
    assert sin_marca == []
    assert len(con_marca) > 40 and altas


def _contexto(repo, unidad, corpus):
    return ApplicationContext(
        ordenes=repo,
        catalogos=JsonCatalogosRepository(
            Settings(_env_file=None, data_dir=corpus[0]).catalogos_dir
        ),
        unidad_de_trabajo=unidad,
    )


def test_h1_los_comandos_reales_funcionan_sobre_postgres(armar, base, corpus):
    """Casos de uso reales, sin simular nada, con lo que A1 y A2 guardan."""
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    equipo = Equipo(
        id="EQP-H1",
        marca="Apple",
        modelo="iPhone 13",
        falla_reportada="No enciende.",
    )
    cliente = Cliente(id="CLI-H1", nombre_apellido="Ana", telefono="341-9")

    creada = crear_orden(
        contexto, usuario_id=f.RECEPCION, cliente=cliente, equipo=equipo
    )
    assert repo.obtener(creada.id) == creada

    definida = definir_reparacion(
        contexto,
        orden_id=creada.id,
        usuario_id=f.RECEPCION,
        tipo_reparacion_id=f.BATERIA,
    )
    assert repo.obtener(creada.id) == definida
    assert _version(base, creada.id) == 2

    cancelada = cancelar_detalle(
        contexto,
        orden_id=creada.id,
        detalle_id=definida.reparaciones_detail[0].id,
        usuario_id=f.RECEPCION,
        motivo="El cliente desiste.",
    )
    assert repo.obtener(creada.id) == cancelada
    assert _version(base, creada.id) == 3

    rt = crear_orden_rt(
        contexto,
        usuario_id=f.RECEPCION,
        equipo=equipo.model_copy(update={"id": "EQP-H2"}),
        referencia_rt="RT-1",
    )
    assert repo.obtener(rt.id) == rt


def test_h1_un_comando_real_ve_lo_que_confirmo_otro(armar, base, corpus):
    """Dos comandos reales seguidos sobre la Orden: nada se pierde."""
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden = next(
        o
        for o in _ultimos(corpus).values()
        if o.ejecuciones and not o.esta_cerrada
    )
    repo.guardar(orden)
    for prioridad in (1, 2):
        cambiada = cambiar_prioridad_de_orden(
            contexto,
            orden_id=orden.id,
            usuario_id=f.COORDINADOR,
            prioridad=prioridad,
            motivo="Cambia el orden de atencion.",
        )
        assert repo.obtener(orden.id) == cambiada
    assert repo.obtener(orden.id).prioridad == 2
    assert _version(base, orden.id) == 3


# --- A2-3: orden de bloqueo -------------------------------------------------


def _consultas_de(unidad):
    """Registra el nombre de cada consulta que ejecuta el comando."""
    nombres = []
    original = unidad.ejecutor

    def ejecutor():
        real = original()

        class Espia:
            def __getattr__(self, metodo):
                llamada = getattr(real, metodo)

                def registrar(consulta_, *argumentos):
                    nombres.append(consulta_.nombre)
                    return llamada(consulta_, *argumentos)

                return registrar

        return Espia()

    unidad.ejecutor = ejecutor
    return nombres


def _posiciones(nombres, *buscados):
    return [nombres.index(nombre) for nombre in buscados]


def test_a2_3_al_modificar_orden_cliente_documento_equipo(armar, corpus):
    repo, unidad = armar()
    orden = next(
        o
        for o in _ultimos(corpus).values()
        if o.ejecuciones and o.cliente is not None
    )
    repo.guardar(orden)
    nombres = _consultas_de(unidad)
    with unidad.transaccion():
        cargada = repo.obtener_para_modificar(orden.id)
        cargada.cliente.telefono = "341-9"
        cargada.cliente.dni = "40111222"
        cargada.equipo.color = "Azul"
        repo.guardar(cargada)
    posiciones = _posiciones(
        nombres,
        "ordenes.bloquear",
        "ordenes.cliente",
        "ordenes.documento_vigente",
        "ordenes.equipo",
    )
    assert posiciones == sorted(posiciones)
    assert nombres.count("ordenes.bloquear") == 1


def test_a2_3_un_alta_bloquea_cliente_documento_y_equipo(armar, corpus):
    """Su Orden todavia no la ve nadie: se inserta despues."""
    repo, unidad = armar()
    orden = next(
        o
        for o in _ultimos(corpus).values()
        if o.ejecuciones and o.cliente is not None
    )
    nombres = _consultas_de(unidad)
    repo.guardar(orden)
    posiciones = _posiciones(
        nombres,
        "ordenes.cliente",
        "ordenes.documento_vigente",
        "ordenes.equipo",
        "ordenes.insertar",
    )
    assert posiciones == sorted(posiciones)
    assert "ordenes.bloquear" not in nombres


# --- L-3: una restriccion violada no es un conflicto de concurrencia --------


def test_l3_un_check_del_esquema_no_se_presenta_como_conflicto(armar, corpus):
    """Hoy lo dispara M-3 (alta de una Orden ya cerrada, pendiente de E8)."""
    repo, _ = armar()
    cerrada = _con_ejecuciones(corpus).model_copy(
        update={"estado_workflow": EstadoWorkflow.ENTREGADA}
    )
    with pytest.raises(RestriccionDeIntegridadError) as capturado:
        repo.guardar(cerrada)
    assert capturado.value.sqlstate == "23514"
    assert not capturado.value.reintentable
    assert "orden_cerrada_con_fecha" in str(capturado.value)
    assert "cambiaron" not in str(capturado.value)


def test_l3_una_clave_primaria_no_se_presenta_como_conflicto(
    armar, base, corpus
):
    """Un Detalle de origen repetido en el alta de una garantia viola la
    clave primaria de ``orden_detalle_origen``. (Antes la disparaba M-1,
    un insumo repetido, que A6 resolvio.)"""
    repo, unidad = armar()
    garantia = next(o for o in corpus[1] if o.orden_origen_id)
    vistos = set()
    for paso in corpus[1]:
        if paso.id == garantia.orden_origen_id:
            _guardar_paso(repo, unidad, paso, paso.id in vistos)
            vistos.add(paso.id)
    alta = garantia.model_copy(
        update={"detalles_origen_ids": garantia.detalles_origen_ids * 2},
        deep=True,
    )
    antes = _cuentas(base)
    with pytest.raises(RestriccionDeIntegridadError) as capturado:
        repo.guardar(alta)
    # Una clave primaria repetida no es una carrera: ni 409 ni reintento.
    assert not isinstance(capturado.value, ConflictoDeEscrituraError)
    assert not capturado.value.reintentable
    assert capturado.value.sqlstate == "23505"
    assert capturado.value.restriccion == "orden_detalle_origen_pkey"
    assert _cuentas(base) == antes


def test_l3_un_valor_fuera_de_rango_es_un_dato_invalido(armar, base, corpus):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    with pytest.raises(DatosInvalidosError) as capturado:
        with unidad.transaccion():
            modificada = repo.obtener_para_modificar(orden.id)
            modificada.prioridad = 100000  # la columna es smallint
            repo.guardar(modificada)
    assert capturado.value.sqlstate == "22003"
    assert _version(base, orden.id) == 1


def test_l3_un_bloqueo_agotado_no_dice_que_los_datos_cambiaron(armar, corpus):
    repo, unidad = armar(lock_timeout_ms=200)
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    tomada, soltar = threading.Event(), threading.Event()

    def comando():
        with unidad.transaccion():
            repo.obtener_para_modificar(orden.id)
            tomada.set()
            soltar.wait(10)

    hilo = threading.Thread(target=comando)
    hilo.start()
    assert tomada.wait(10)
    try:
        with pytest.raises(ConflictoDeEscrituraError) as capturado:
            with unidad.transaccion():
                repo.obtener_para_modificar(orden.id)
    finally:
        soltar.set()
        hilo.join(10)
    assert capturado.value.reintentable
    assert capturado.value.sqlstate == "55P03"
    assert "Otra operacion esta usando" in str(capturado.value)
