"""Consultas dedicadas de E2 en PostgreSQL y lecturas consistentes (A5).

Contra la base local descartable. El contrato de cada consulta esta en
``tests/test_contrato_ordenes.py`` (JSON y PostgreSQL). Aca:

- QA-A2-M2: dentro de un comando (READ COMMITTED) una carga son varias
  consultas. Una escritura que confirma entre ellas no produce una Orden
  mezclada: la carga se repite. Y una Orden que el comando no bloqueo se
  ve en una sola version durante todo el comando (QA-E2-1).
- Los casos de uso que dependen de las consultas dan lo mismo en JSON y
  en PostgreSQL, desde el mismo estado y con el reloj fijo: bandejas,
  pendientes de autorizacion, busqueda de cliente por DNI y el
  comprobante de ingreso (A4-2, que necesita ``listar_con_reservas``).

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (seccion 16).
"""

import threading
from dataclasses import replace
from datetime import datetime, timezone

import pytest

pytest.importorskip("psycopg_pool")

from fastapi.testclient import TestClient  # noqa: E402

from app.application import (  # noqa: E402
    bandejas_de_inicio,
    bandejas_de_taller,
    buscar_cliente_por_dni,
    construir_contexto,
    generar_comprobante_ingreso,
    pendientes_de_autorizacion,
)
from app.application.contexto import ApplicationContext  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.domain.models.recepcion import NotaRecepcion  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repositories.exceptions import (  # noqa: E402
    ConflictoDeEscrituraError,
    EntidadPersistidaNoEncontradaError,
)
from app.storage.json.catalogos import JsonCatalogosRepository  # noqa: E402
from app.storage.json.ordenes import (  # noqa: E402
    JsonOrdenReparacionRepository,
)
from app.storage.postgres import ordenes_lectura  # noqa: E402
from app.storage.postgres.ordenes_lectura import cargar_ordenes  # noqa: E402
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.fixtures import custodia  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.corpus_ordenes import DNI, _crear_con_dni  # noqa: E402
from tests.postgres.test_ordenes_postgres import (  # noqa: E402
    _guardar_paso,
    _ultimos,
)

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla

AHORA = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)


def _cargar(repo, unidad, pasos):
    vistos = set()
    for paso in pasos:
        _guardar_paso(repo, unidad, paso, paso.id in vistos)
        vistos.add(paso.id)


def _abierta_con_recepcion(repo, unidad, corpus):
    """Una Orden abierta con recepcion, cargada con todos sus pasos."""
    orden = next(
        o
        for o in _ultimos(corpus).values()
        if not o.esta_cerrada and o.recepcion and not o.movimientos_insumo
    )
    _cargar(repo, unidad, [o for o in corpus[1] if o.id == orden.id])
    return orden


def _escribir(repo, unidad, codigo, prioridad, texto):
    """Otro comando, en otro hilo: cambia la raiz y agrega una hija."""

    def comando():
        with unidad.transaccion():
            orden = repo.obtener_para_modificar(codigo)
            orden.prioridad = prioridad
            orden.recepcion.notas.append(
                NotaRecepcion(
                    usuario_id=f.RECEPCION,
                    fecha=orden.updated_at,
                    texto=texto,
                )
            )
            repo.guardar(orden)

    hilo = threading.Thread(target=comando)
    hilo.start()
    hilo.join(30)


def _nota(orden, texto):
    return any(n.texto == texto for n in orden.recepcion.notas)


def _escritura_entre_consultas(monkeypatch, repo, unidad, codigo, veces):
    """La escritura confirma despues de leer la raiz y antes de las hijas,
    en las primeras ``veces`` cargas."""
    original = ordenes_lectura._agrupar_hijas
    cargas = []
    lector_principal = threading.get_ident()

    def agrupar(lector, ids):
        # Solo las del hilo que lee: el comando que escribe tambien carga.
        if threading.get_ident() != lector_principal:
            return original(lector, ids)
        cargas.append(1)
        if len(cargas) <= veces:
            _escribir(
                repo, unidad, codigo, len(cargas) % 5 + 1, f"n{len(cargas)}"
            )
        return original(lector, ids)

    monkeypatch.setattr(ordenes_lectura, "_agrupar_hijas", agrupar)
    return cargas


# --- QA-A2-M2 ---------------------------------------------------------------


def test_m2_sin_validar_una_carga_mezcla_dos_instantes(
    armar, corpus, monkeypatch
):
    """Lo que pasaba: la raiz de antes con la nota de despues. Muestra que
    la escritura de la prueba si se mete entre las consultas."""
    repo, unidad = armar(pool_max=4)
    orden = _abierta_con_recepcion(repo, unidad, corpus)
    assert orden.prioridad != 2  # la que pone la escritura
    _escritura_entre_consultas(monkeypatch, repo, unidad, orden.id, 1)
    with unidad.transaccion():
        cargada = cargar_ordenes(unidad.ejecutor(), [orden.id])[0].orden
    assert cargada.prioridad == orden.prioridad
    assert _nota(cargada, "n1")


@pytest.mark.parametrize(
    "consulta",
    ["obtener", "listar", "listar_abiertas"],
)
def test_m2_dentro_de_un_comando_la_carga_no_mezcla(
    armar, corpus, monkeypatch, consulta
):
    repo, unidad = armar(pool_max=4)
    orden = _abierta_con_recepcion(repo, unidad, corpus)
    cargas = _escritura_entre_consultas(monkeypatch, repo, unidad, orden.id, 1)
    with unidad.transaccion():
        if consulta == "obtener":
            leida = repo.obtener(orden.id)
        else:
            leida = next(
                o for o in getattr(repo, consulta)() if o.id == orden.id
            )
    assert len(cargas) == 2  # la primera se descarto
    assert leida.prioridad == 2 and _nota(leida, "n1")
    monkeypatch.undo()
    assert leida == repo.obtener(orden.id)


def test_m2_si_la_orden_no_para_de_cambiar_es_un_conflicto_reintentable(
    armar, corpus, monkeypatch
):
    repo, unidad = armar(pool_max=4)
    orden = _abierta_con_recepcion(repo, unidad, corpus)
    _escritura_entre_consultas(monkeypatch, repo, unidad, orden.id, 99)
    with pytest.raises(ConflictoDeEscrituraError) as capturado:
        with unidad.transaccion():
            repo.listar_abiertas()
    assert capturado.value.reintentable


def test_m2_una_sola_version_por_comando(armar, corpus):
    """QA-E2-1: entre dos consultas del mismo comando, otro confirma un
    cambio. La segunda ve la Orden como la primera; despues, como quedo."""
    repo, unidad = armar(pool_max=4)
    orden = _abierta_con_recepcion(repo, unidad, corpus)
    with unidad.transaccion():
        primera = next(o for o in repo.listar_abiertas() if o.id == orden.id)
        _escribir(repo, unidad, orden.id, 1, "despues")
        segunda = next(o for o in repo.listar() if o.id == orden.id)
        tercera = repo.obtener(orden.id)
    assert primera == segunda == tercera == orden
    ahora = repo.obtener(orden.id)
    assert ahora.prioridad == 1 and _nota(ahora, "despues")


def test_m2_lo_que_el_comando_bloquea_o_escribe_se_lee_como_esta(
    armar, corpus
):
    repo, unidad = armar(pool_max=4)
    orden = _abierta_con_recepcion(repo, unidad, corpus)
    with unidad.transaccion():
        repo.listar_abiertas()
        cargada = repo.obtener_para_modificar(orden.id)
        cargada.prioridad = 5
        repo.guardar(cargada)
        assert repo.obtener(orden.id).prioridad == 5
        assert next(o for o in repo.listar() if o.id == orden.id) == cargada


def test_m2_fuera_de_un_comando_no_queda_nada_fijo(armar, corpus):
    repo, unidad = armar(pool_max=4)
    orden = _abierta_con_recepcion(repo, unidad, corpus)
    assert repo.obtener(orden.id) == orden
    _escribir(repo, unidad, orden.id, 1, "otra")
    assert _nota(repo.obtener(orden.id), "otra")


# --- Casos de uso: JSON y PostgreSQL desde el mismo estado -------------------


@pytest.fixture
def mismo_estado(armar, tmp_path, corpus):
    """Ordenes armadas por la API en JSON y copiadas a PostgreSQL, sin
    movimientos de insumo (A6). Devuelve los dos contextos, con el mismo
    reloj."""
    f.sembrar(tmp_path)
    configuracion = Settings(data_dir=tmp_path, fotos_dir=tmp_path / "fotos")
    with TestClient(create_app(configuracion)) as cliente:
        # Para el comprobante de ingreso: un trabajo y el estado fisico.
        ingreso = f.crear(cliente)
        f.agregar(cliente, ingreso)
        custodia.preparar_ingreso(cliente, ingreso)
        # Para la autorizacion pendiente y la busqueda por DNI.
        f.por_revision(cliente, f.BATERIA)
        primera = _crear_con_dni(cliente)
        _crear_con_dni(cliente, primera["cliente"]["id"])
        f.ok(f.cancelar_orden(cliente, f.definida(cliente)))
    json_repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    todas = json_repo.listar()
    assert all(not o.movimientos_insumo for o in todas)
    repo, unidad = armar(pool_max=4)
    for orden in todas:
        repo.guardar(orden)
    catalogos = JsonCatalogosRepository(
        Settings(_env_file=None, data_dir=tmp_path).catalogos_dir
    )
    en_json = replace(construir_contexto(configuracion), ahora=lambda: AHORA)
    en_postgres = ApplicationContext(
        ordenes=repo,
        catalogos=catalogos,
        unidad_de_trabajo=unidad,
        ahora=lambda: AHORA,
    )
    return en_json, en_postgres, ingreso


USUARIOS = (f.RECEPCION, f.COORDINADOR, f.TECNICO, f.ADMINISTRADOR)


def test_a5_las_lecturas_de_los_casos_de_uso_coinciden(mismo_estado):
    en_json, en_postgres, _ = mismo_estado
    for usuario in USUARIOS:
        assert bandejas_de_inicio(
            en_postgres, usuario_id=usuario
        ) == bandejas_de_inicio(en_json, usuario_id=usuario)
        assert bandejas_de_taller(
            en_postgres, usuario_id=usuario
        ) == bandejas_de_taller(en_json, usuario_id=usuario)
    assert pendientes_de_autorizacion(en_postgres) == (
        pendientes_de_autorizacion(en_json)
    )
    for dni in (DNI, "99999999"):
        assert buscar_cliente_por_dni(
            en_postgres,
            dni=dni,
            usuario_id=f.RECEPCION,
            incluir_externa=False,
        ) == buscar_cliente_por_dni(
            en_json, dni=dni, usuario_id=f.RECEPCION, incluir_externa=False
        )


def test_a5_el_comprobante_de_ingreso_corre_sobre_postgres(mismo_estado):
    """A4-2: necesita ``listar_con_reservas``. Mismo resultado que JSON."""
    en_json, en_postgres, ingreso = mismo_estado
    en_pg = generar_comprobante_ingreso(
        en_postgres, orden_id=ingreso, usuario_id=f.RECEPCION
    )
    en_js = generar_comprobante_ingreso(
        en_json, orden_id=ingreso, usuario_id=f.RECEPCION
    )
    assert en_pg.model_dump(mode="json") == en_js.model_dump(mode="json")
    assert en_postgres.ordenes.obtener(ingreso) == en_pg


# --- Menos viajes a la base -------------------------------------------------


def test_precargar_no_cambia_lo_que_devuelve_cada_consulta(armar, corpus):
    repo, unidad = armar()
    _cargar(repo, unidad, corpus[1])
    clave = "INS-001"
    sin = (
        repo.listar(),
        repo.listar_abiertas(),
        repo.listar_con_reservas(),
        repo.listar_con_reservas([clave]),
        repo.listar_con_movimientos(clave),
    )
    with unidad.lectura_consistente():
        repo.precargar(
            todas=True, abiertas=True, con_reservas=True, insumo_id=clave
        )
        con = (
            repo.listar(),
            repo.listar_abiertas(),
            repo.listar_con_reservas(),
            repo.listar_con_reservas([clave]),
            repo.listar_con_movimientos(clave),
        )
    assert con == sin


def test_lo_precargado_se_entrega_en_copias(armar, corpus):
    repo, unidad = armar()
    orden = _abierta_con_recepcion(repo, unidad, corpus)
    with unidad.lectura_consistente():
        repo.precargar(abiertas=True)
        primera = repo.obtener(orden.id)
        primera.prioridad = 1
        primera.recepcion.notas.clear()
        segunda = repo.obtener(orden.id)
    assert segunda == repo.obtener(orden.id)
    assert segunda != primera


def test_precargar_no_hace_nada_dentro_de_un_comando(armar, corpus):
    """Un comando lee en READ COMMITTED: sigue validando por version."""
    repo, unidad = armar()
    orden = _abierta_con_recepcion(repo, unidad, corpus)
    with unidad.transaccion():
        repo.precargar(abiertas=True)
        assert orden.id in {o.id for o in repo.listar_abiertas()}
    repo.precargar(abiertas=True)  # sin transaccion, tampoco


def test_cargar_para_modificar_lee_despues_de_obtener_el_bloqueo(
    armar, corpus
):
    """El bloqueo y la carga van en un envio: lo que sigue al bloqueo corre
    cuando lo obtiene y ve lo que el otro comando confirmo."""
    repo, unidad = armar(pool_max=4)
    orden = _abierta_con_recepcion(repo, unidad, corpus)
    bloqueada = threading.Event()
    seguir = threading.Event()
    leidas = []

    def primero():
        with unidad.transaccion():
            propia = repo.obtener_para_modificar(orden.id)
            propia.prioridad = 2
            propia.recepcion.notas.append(
                NotaRecepcion(
                    usuario_id=f.RECEPCION,
                    fecha=propia.updated_at,
                    texto="del primero",
                )
            )
            repo.guardar(propia)
            bloqueada.set()
            seguir.wait(10)

    def segundo():
        bloqueada.wait(10)
        with unidad.transaccion():
            leidas.append(repo.obtener_para_modificar(orden.id))

    hilos = [
        threading.Thread(target=primero),
        threading.Thread(target=segundo),
    ]
    for hilo in hilos:
        hilo.start()
    bloqueada.wait(10)
    hilos[1].join(0.4)
    assert hilos[1].is_alive()  # espera el bloqueo
    seguir.set()
    for hilo in hilos:
        hilo.join(30)
    assert leidas[0].prioridad == 2
    assert _nota(leidas[0], "del primero")


def test_una_orden_inexistente_no_se_puede_modificar(armar, corpus):
    repo, unidad = armar()
    with unidad.transaccion():
        with pytest.raises(EntidadPersistidaNoEncontradaError):
            repo.obtener_para_modificar("OR-999999")
