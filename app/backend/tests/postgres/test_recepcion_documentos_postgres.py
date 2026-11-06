"""Recepcion, documentos, fotos y salida en PostgreSQL (E4, slice A4).

Contra la base local descartable, con el corpus de flujos reales
(``corpus_ordenes.py``). Semantica que se verifica:

- Cada paso de los flujos reales vuelve igual que su ida y vuelta por JSON.
- Las versiones, notas y check-in de la recepcion, las fotos y los documentos
  solo crecen: alterar o quitar una entrada se rechaza sin escribir.
- El check-in posterior a la custodia va a ``rma.checkin``: ``rma.recepcion``
  no se toca.
- ``entrega`` y ``devolucion`` son la unica fila de ``rma.salida``, y el
  estado de la Orden dice cual es.
- El limite de 10 fotos se respeta con altas simultaneas, y el trigger no
  choca con las claves foraneas hacia la Orden.
- Todo o nada, con una sola accion por comando.

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (seccion 14).
"""

import json
import threading
import time
from datetime import timedelta
from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.application import (  # noqa: E402
    agregar_foto,
    agregar_observacion_recepcion,
    cancelar_orden,
    confirmar_recepcion,
    crear_orden,
    definir_reparacion,
    emitir_comprobante_recepcion,
    entregar,
    enviar_a_revision,
    registrar_checkin,
    registrar_devolucion,
    registrar_no_recepcion,
    registrar_recepcion,
)
from app.application.contexto import ApplicationContext  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.domain.models import (  # noqa: E402
    Cliente,
    Equipo,
    EstadoWorkflow,
    HistorialWorkflow,
    OrdenReparacion,
)
from app.domain.models.enums import (  # noqa: E402
    TipoDocumento,
    TipoEntrega,
)
from app.domain.models.equipos import EntregaEquipo  # noqa: E402
from app.domain.models.fotos import FotoOrden  # noqa: E402
from app.domain.models.recepcion import (  # noqa: E402
    DatosRecepcion,
    NotaRecepcion,
    RegistroCheckin,
)
from app.repositories.exceptions import (  # noqa: E402
    ConflictoDeEscrituraError,
    PersistenciaError,
    RestriccionDeIntegridadError,
)
from app.services import PrecondicionInvalidaError  # noqa: E402
from app.storage.fotos import AlmacenFotosMemoria  # noqa: E402
from app.storage.json.catalogos import JsonCatalogosRepository  # noqa: E402
from app.storage.postgres.ordenes_lectura import (  # noqa: E402
    cargar_ordenes,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.base_local import archivos_sql  # noqa: E402
from tests.postgres.corpus_ordenes import JPEG  # noqa: E402
from tests.postgres.test_ordenes_postgres import (  # noqa: E402
    _con_ejecuciones,
    _ejecutar,
    _guardar_paso,
    _sql,
    _ultimos,
    _version,
)

# Las bases y el corpus son los de las pruebas de A1 y A2.
armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla

TABLAS_A4 = (
    "recepcion_version",
    "recepcion_nota",
    "checkin",
    "foto",
    "documento_emitido",
    "salida",
    "evento_negocio",
    "accion_usuario",
)
TABLAS_POSICION = TABLAS_A4[:5]


def _filas(url):
    return {
        tabla: _sql(url, f"select count(*) from rma.{tabla}")[0][0]
        for tabla in TABLAS_A4
    }


def _pasos(corpus, codigo):
    return [o for o in corpus[1] if o.id == codigo]


def _completa(corpus):
    """La Orden con versiones, notas, check-in, fotos y documentos."""
    return next(
        o
        for o in _ultimos(corpus).values()
        if o.fotos and o.recepcion.registros_checkin
    )


def _cargar(repo, unidad, pasos):
    vistos = set()
    for paso in pasos:
        _guardar_paso(repo, unidad, paso, paso.id in vistos)
        vistos.add(paso.id)


def _hasta_antes_del_cierre(repo, unidad, corpus):
    """La Orden completa, cargada hasta el ultimo paso abierto."""
    pasos = [
        o for o in _pasos(corpus, _completa(corpus).id) if not o.esta_cerrada
    ]
    _cargar(repo, unidad, pasos)
    return pasos[-1]


def _modificar(repo, unidad, codigo, cambio):
    with unidad.transaccion():
        orden = repo.obtener_para_modificar(codigo)
        cambio(orden)
        repo.guardar(orden)


def _foto(numero, fecha, usuario):
    return FotoOrden(
        id=f"FOT-{numero}",
        objeto=f"ordenes/x/{numero}.jpg",
        tipo_contenido="image/jpeg",
        tamano_bytes=10,
        usuario_id=usuario,
        fecha=fecha,
    )


def _fila_orden(url, codigo):
    return _sql(url, "select id from rma.orden where codigo = %s", (codigo,))[
        0
    ][0]


# --- Equivalencia ----------------------------------------------------------


def test_a4_cada_paso_real_es_igual_a_su_ida_y_vuelta_por_json(
    armar, base, corpus
):
    repo, unidad = armar()
    vistos = set()
    for paso in corpus[1]:
        _guardar_paso(repo, unidad, paso, paso.id in vistos)
        vistos.add(paso.id)
        por_json = OrdenReparacion.model_validate(
            json.loads(
                paso.model_dump_json(exclude_computed_fields=True),
            )
        )
        leida = repo.obtener(paso.id)
        assert leida == por_json
        assert leida.model_dump(mode="json") == por_json.model_dump(
            mode="json"
        )
    assert _sql(base, "select * from rma.verificar_integridad()") == []
    finales = list(_ultimos(corpus).values())
    assert repo.listar() == sorted(finales, key=lambda o: o.id)


def test_a4_el_corpus_cubre_lo_que_a4_guarda(corpus):
    """Si un flujo deja de producir estas partes, la prueba de arriba dejaria
    de decir algo."""
    finales = list(_ultimos(corpus).values())
    recepciones = [o.recepcion for o in finales if o.recepcion]
    documentos = [d for o in finales for d in o.documentos.emitidos]
    assert any(len(r.versiones_anteriores) >= 2 for r in recepciones)
    assert any(n.interna for r in recepciones for n in r.notas)
    assert any(len(r.registros_checkin) >= 2 for r in recepciones)
    assert any(r.no_recibido for r in recepciones)
    assert any(len(o.fotos) >= 2 for o in finales)
    assert any(d.reemplaza_a for d in documentos)
    assert {d.tipo.value for d in documentos} == {
        "COMPROBANTE_INGRESO",
        "COMPROBANTE_RECEPCION",
        "COMPROBANTE_AUTORIZACION",
        "COMPROBANTE_ENTREGA",
        "GARANTIA",
    }
    assert {o.entrega.tipo for o in finales if o.entrega} == set(TipoEntrega)
    assert any(o.devolucion for o in finales)
    assert any(o.orden_origen_id and o.esta_cerrada for o in finales)
    assert any(o.referencia_rt and o.esta_cerrada for o in finales)


def test_a4_cargar_no_hace_una_consulta_por_orden(armar, corpus):
    repo, unidad = armar()
    _cargar(repo, unidad, corpus[1])
    consultas = []

    class Espia:
        def __init__(self, real):
            self._real = real

        def filas(self, *argumentos):
            consultas.append(argumentos[0].nombre)
            return self._real.filas(*argumentos)

        def filas_en_lote(self, pedidos):
            consultas.extend(consulta.nombre for consulta, _ in pedidos)
            return self._real.filas_en_lote(pedidos)

    codigos = list(_ultimos(corpus))
    with unidad.lectura() as lector:
        cargar_ordenes(Espia(lector), codigos[:1])
        una = len(consultas)
        consultas.clear()
        cargar_ordenes(Espia(lector), codigos)
    assert len(consultas) == una


# --- Recepcion -------------------------------------------------------------


def test_a4_una_version_guarda_su_equipo_en_el_jsonb(armar, base, corpus):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    filas = _sql(
        base,
        "select posicion, datos->'equipo'->>'marca', datos ? 'datos' "
        "from rma.recepcion_version where orden_id = %s order by posicion",
        (_fila_orden(base, orden.id),),
    )
    versiones = orden.recepcion.versiones_anteriores
    assert filas == [
        (numero, version.equipo.marca, True)
        for numero, version in enumerate(versiones, 1)
    ]
    assert repo.obtener(orden.id).recepcion.versiones_anteriores == versiones


def test_a4_una_recepcion_decidida_no_se_corrige(armar, base, corpus):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    assert orden.recepcion.decidida
    antes = _filas(base), _version(base, orden.id)

    def corregir(cargada):
        cargada.recepcion.datos.estado_fisico = "Otro estado."

    with pytest.raises(PersistenciaError, match="inmutable"):
        _modificar(repo, unidad, orden.id, corregir)
    assert (_filas(base), _version(base, orden.id)) == antes


def test_a4_una_nota_se_agrega_despues_de_la_custodia(armar, base, corpus):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    fecha = orden.updated_at
    textos = ["z primera", "a segunda", "m tercera"]

    def anotar(cargada):
        cargada.recepcion.notas.extend(
            NotaRecepcion(usuario_id=f.RECEPCION, fecha=fecha, texto=texto)
            for texto in textos
        )

    previas = len(orden.recepcion.notas)
    _modificar(repo, unidad, orden.id, anotar)
    # Con la misma fecha, el orden es el de la lista, no el alfabetico.
    leidas = repo.obtener(orden.id).recepcion.notas
    assert [n.texto for n in leidas[previas:]] == textos


@pytest.mark.parametrize(
    "alterar",
    [
        lambda o: setattr(
            o.recepcion.versiones_anteriores[0].datos, "estado_fisico", "x"
        ),
        lambda o: o.recepcion.versiones_anteriores.pop(0),
        lambda o: setattr(o.recepcion.notas[0], "texto", "x"),
        lambda o: o.recepcion.notas.pop(0),
        lambda o: setattr(
            o.recepcion.registros_checkin[0],
            "realizado",
            not o.recepcion.registros_checkin[0].realizado,
        ),
        lambda o: o.recepcion.registros_checkin.pop(0),
        lambda o: setattr(o.fotos[0], "objeto", "ordenes/otra.jpg"),
        lambda o: o.fotos.pop(0),
        lambda o: o.fotos.reverse(),
        lambda o: setattr(o.documentos.emitidos[0], "motivo", "x"),
        lambda o: o.documentos.emitidos.pop(0),
        lambda o: o.documentos.emitidos.reverse(),
    ],
    ids=[
        "version-alterada",
        "version-quitada",
        "nota-alterada",
        "nota-quitada",
        "checkin-alterado",
        "checkin-quitado",
        "foto-alterada",
        "foto-quitada",
        "fotos-reordenadas",
        "documento-alterado",
        "documento-quitado",
        "documentos-reordenados",
    ],
)
def test_a4_lo_que_solo_crece_no_se_altera(armar, base, corpus, alterar):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    antes = _filas(base), _version(base, orden.id)
    with pytest.raises(PersistenciaError, match="inmutable"):
        _modificar(repo, unidad, orden.id, alterar)
    assert (_filas(base), _version(base, orden.id)) == antes
    assert repo.obtener(orden.id) == orden


# --- Check-in --------------------------------------------------------------


def _sin_checkin(corpus):
    return next(
        o
        for o in _pasos(corpus, _completa(corpus).id)
        if o.recepcion.decidida and o.ejecuciones
    )


def test_a4_el_checkin_posterior_a_la_custodia_no_toca_la_recepcion(
    armar, base, corpus
):
    repo, unidad = armar()
    pasos = _pasos(corpus, _completa(corpus).id)
    _cargar(repo, unidad, pasos[: pasos.index(_sin_checkin(corpus)) + 1])
    orden = _sin_checkin(corpus)
    fila = _fila_orden(base, orden.id)
    recepcion = "select to_jsonb(r) from rma.recepcion r where orden_id = %s"
    antes = _sql(base, recepcion, (fila,))
    fecha = orden.updated_at + timedelta(minutes=1)

    def registrar(realizado):
        def cambio(cargada):
            cargada.recepcion.datos.checkin = realizado
            cargada.recepcion.registros_checkin.append(
                RegistroCheckin(
                    realizado=realizado, usuario_id=f.RECEPCION, fecha=fecha
                )
            )

        return cambio

    _modificar(repo, unidad, orden.id, registrar(False))
    _modificar(repo, unidad, orden.id, registrar(True))
    assert _sql(base, recepcion, (fila,)) == antes
    assert _sql(
        base,
        "select posicion, realizado from rma.checkin where orden_id = %s "
        "order by posicion",
        (fila,),
    ) == [(1, False), (2, True)]
    leida = repo.obtener(orden.id).recepcion
    assert leida.datos.checkin is True
    assert [r.realizado for r in leida.registros_checkin] == [False, True]


def test_a4_sin_registros_vale_el_checkin_del_ingreso(armar, corpus):
    repo, _ = armar()
    orden = _con_ejecuciones(corpus).model_copy(deep=True)
    orden.recepcion.datos.checkin = True
    repo.guardar(orden)
    assert repo.obtener(orden.id).recepcion.datos.checkin is True


def test_a4_un_checkin_que_no_es_el_ultimo_registro_se_rechaza(
    armar, base, corpus
):
    """Se perderia en silencio al releer."""
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    antes = _filas(base), _version(base, orden.id)

    def contradecir(cargada):
        cargada.recepcion.datos.checkin = not cargada.recepcion.datos.checkin

    with pytest.raises(PersistenciaError, match="check-in vigente"):
        _modificar(repo, unidad, orden.id, contradecir)
    assert (_filas(base), _version(base, orden.id)) == antes


# --- Fotos -----------------------------------------------------------------


def _con_fotos(repo, unidad, corpus, cantidad):
    orden = _con_ejecuciones(corpus).model_copy(deep=True)
    orden.fotos = [
        _foto(numero, orden.updated_at, f.RECEPCION)
        for numero in range(cantidad)
    ]
    repo.guardar(orden)
    return orden


def test_a4_las_fotos_conservan_su_orden_y_sus_datos(armar, base, corpus):
    repo, unidad = armar()
    orden = _con_fotos(repo, unidad, corpus, 3)
    assert repo.obtener(orden.id).fotos == orden.fotos
    assert _sql(
        base,
        "select posicion from rma.foto where orden_id = %s order by posicion",
        (_fila_orden(base, orden.id),),
    ) == [(1,), (2,), (3,)]


def test_a4_la_undecima_foto_se_rechaza_y_revierte_el_comando(
    armar, base, corpus
):
    repo, unidad = armar()
    orden = _con_fotos(repo, unidad, corpus, 10)
    antes = _filas(base), _version(base, orden.id)

    def agregar(cargada):
        cargada.prioridad = 2
        cargada.fotos.append(_foto(99, orden.updated_at, f.RECEPCION))

    with pytest.raises(RestriccionDeIntegridadError) as capturado:
        _modificar(repo, unidad, orden.id, agregar)
    assert capturado.value.sqlstate == "23514"
    assert (_filas(base), _version(base, orden.id)) == antes
    assert repo.obtener(orden.id).prioridad == orden.prioridad


def test_a4_comandos_simultaneos_no_superan_las_diez_fotos(
    armar, base, corpus
):
    repo, unidad = armar(pool_max=5)
    orden = _con_fotos(repo, unidad, corpus, 9)
    barrera = threading.Barrier(4)
    resultados = []

    def comando(numero):
        barrera.wait(10)
        try:

            def agregar(cargada):
                cargada.fotos.append(
                    _foto(100 + numero, orden.updated_at, f.TECNICO)
                )

            _modificar(repo, unidad, orden.id, agregar)
            resultados.append("guardada")
        except RestriccionDeIntegridadError as error:
            resultados.append(error.sqlstate)

    hilos = [
        threading.Thread(target=comando, args=(numero,)) for numero in range(4)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert sorted(resultados) == ["23514", "23514", "23514", "guardada"]
    assert len(repo.obtener(orden.id).fotos) == 10
    assert _version(base, orden.id) == 2


FOTO_SQL = (
    "insert into rma.foto (codigo, orden_id, objeto_clave, tipo_contenido, "
    "tamano_bytes, usuario_id) values (%s, %s, %s, 'image/jpeg', 1, %s)"
)


def test_a4_el_limite_tambien_vale_sin_el_bloqueo_del_comando(
    armar, base, corpus
):
    """Lo sostiene el trigger, con altas directas y simultaneas."""
    repo, unidad = armar()
    orden = _con_fotos(repo, unidad, corpus, 9)
    fila = _fila_orden(base, orden.id)
    usuario = _sql(base, "select id from rma.usuario limit 1")[0][0]
    barrera = threading.Barrier(4)
    resultados = []

    def alta(numero):
        with psycopg.connect(base) as conexion:
            barrera.wait(10)
            try:
                conexion.execute(
                    FOTO_SQL,
                    (f"G-{numero}", fila, f"directa/{numero}", usuario),
                )
                time.sleep(0.1)
                conexion.commit()
                resultados.append("ok")
            except psycopg.errors.CheckViolation:
                conexion.rollback()
                resultados.append("limite")

    hilos = [
        threading.Thread(target=alta, args=(numero,)) for numero in range(4)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert sorted(resultados) == ["limite", "limite", "limite", "ok"]
    assert _sql(
        base, "select count(*) from rma.foto where orden_id = %s", (fila,)
    ) == [(10,)]


def _referenciar_la_orden(conexion, fila):
    """``KEY SHARE`` sobre la Orden, por la clave foranea de la accion."""
    conexion.execute(
        "insert into rma.accion_usuario "
        "(proceso, operacion, resultado, orden_id) "
        "values ('SISTEMA', 'prueba', 'CONFIRMADA', %s)",
        (fila,),
    )


def test_a4_una_foto_no_choca_con_las_claves_foraneas_hacia_la_orden(
    armar, base, corpus
):
    """El deadlock que se reprodujo con ``FOR UPDATE``: un comando ya tiene
    la Orden y otra transaccion la referencia antes de pedirla."""
    repo, _ = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    fila = _fila_orden(base, orden.id)
    usuario = _sql(base, "select id from rma.usuario limit 1")[0][0]
    bloqueo = "select 1 from rma.orden where id = %s for no key update"
    comando = psycopg.connect(base)
    otra = psycopg.connect(base)
    tercera = psycopg.connect(base)
    resultado = {}
    try:
        for conexion in (comando, otra, tercera):
            conexion.execute("set lock_timeout = '4s'")
        comando.execute(bloqueo, (fila,))
        _referenciar_la_orden(otra, fila)
        _referenciar_la_orden(tercera, fila)

        def foto():
            inicio = time.monotonic()
            comando.execute(FOTO_SQL, ("F-1", fila, "fk/1", usuario))
            resultado["espera"] = time.monotonic() - inicio
            comando.commit()

        hilo = threading.Thread(target=foto)
        hilo.start()
        time.sleep(0.3)
        otra.execute(bloqueo, (fila,))
        otra.commit()
        tercera.commit()
        hilo.join(10)
    finally:
        for conexion in (comando, otra, tercera):
            conexion.close()
    # Ni deadlock ni espera: el KEY SHARE ajeno no la frena.
    assert resultado["espera"] < 1
    assert _sql(
        base, "select count(*) from rma.foto where orden_id = %s", (fila,)
    ) == [(1,)]


def test_a4_el_trigger_de_fotos_no_usa_for_update(base):
    definicion = _sql(
        base,
        "select pg_get_functiondef("
        "'rma.foto_limite_por_orden()'::regprocedure)",
    )[0][0]
    assert "for no key update" in definicion
    assert "for update" not in definicion


# --- Documentos ------------------------------------------------------------


def test_a4_reemplaza_a_es_un_uuid_y_vuelve_como_identificador(
    armar, base, corpus
):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    reemplazos = [
        d for d in orden.documentos.emitidos if d.reemplaza_a is not None
    ]
    assert len(reemplazos) >= 2
    filas = _sql(
        base,
        "select d.codigo, r.codigo, r.tipo = d.tipo, r.version + 1 = d.version"
        " from rma.documento_emitido d "
        "join rma.documento_emitido r on r.id = d.reemplaza_a "
        "where d.orden_id = %s order by d.posicion",
        (_fila_orden(base, orden.id),),
    )
    assert filas == [(d.id, d.reemplaza_a, True, True) for d in reemplazos]
    assert repo.obtener(orden.id).documentos.emitidos == (
        orden.documentos.emitidos
    )


def _version_nueva(orden, reemplaza_a):
    ultimo = orden.documentos.emitidos[-1]
    return ultimo.model_copy(
        update={
            "id": "DOC-NUEVO",
            "version": ultimo.version + 1,
            "motivo": "Se corrigio.",
            "reemplaza_a": reemplaza_a,
        }
    )


def test_a4_un_documento_reemplaza_a_uno_del_mismo_comando(armar, corpus):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)

    def emitir(cargada):
        primero = _version_nueva(cargada, cargada.documentos.emitidos[-1].id)
        cargada.documentos.emitidos.append(primero)
        cargada.documentos.emitidos.append(
            primero.model_copy(
                update={
                    "id": "DOC-OTRO",
                    "version": primero.version + 1,
                    "reemplaza_a": primero.id,
                }
            )
        )

    _modificar(repo, unidad, orden.id, emitir)
    ultimos = repo.obtener(orden.id).documentos.emitidos[-2:]
    assert [d.id for d in ultimos] == ["DOC-NUEVO", "DOC-OTRO"]
    assert ultimos[1].reemplaza_a == "DOC-NUEVO"


def test_a4_un_reemplazo_desconocido_se_rechaza(armar, base, corpus):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    antes = _filas(base)

    def emitir(cargada):
        cargada.documentos.emitidos.append(
            _version_nueva(cargada, "DOC-INEXISTENTE")
        )

    with pytest.raises(PersistenciaError, match="DOC-INEXISTENTE"):
        _modificar(repo, unidad, orden.id, emitir)
    assert _filas(base) == antes


def test_a4_un_documento_de_otra_orden_se_rechaza(armar, base, corpus):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    antes = _filas(base)

    def emitir(cargada):
        ajeno = _version_nueva(cargada, cargada.documentos.emitidos[-1].id)
        cargada.documentos.emitidos.append(
            ajeno.model_copy(update={"orden_id": "OR-000001"})
        )

    with pytest.raises(PersistenciaError, match="no de"):
        _modificar(repo, unidad, orden.id, emitir)
    assert _filas(base) == antes


@pytest.mark.parametrize(
    "importe",
    ["1234.50", "0.10", "80000", "12345678901234567890.123456789"],
)
def test_a4_los_importes_no_pierden_precision(armar, base, corpus, importe):
    repo, _ = armar()
    orden = _con_ejecuciones(corpus).model_copy(deep=True)
    documento = orden.documentos.emitidos[0]
    documento.contenido.total = Decimal(importe)
    repo.guardar(orden)
    assert _sql(
        base,
        "select contenido->>'total', jsonb_typeof(contenido->'total') "
        "from rma.documento_emitido where codigo = %s",
        (documento.id,),
    ) == [(importe, "string")]
    leido = repo.obtener(orden.id).documentos.emitidos[0]
    assert str(leido.contenido.total) == importe
    assert leido == documento


def test_a4_documentos_de_distinto_tipo_con_la_misma_fecha(armar, corpus):
    """El orden de la lista no sale ni de la fecha ni del tipo."""
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    fecha = orden.updated_at

    def emitir(cargada):
        for numero, tipo in enumerate(
            (TipoDocumento.GARANTIA, TipoDocumento.COMPROBANTE_ENTREGA)
        ):
            cargada.documentos.emitidos.append(
                cargada.documentos.emitidos[0].model_copy(
                    update={
                        "id": f"DOC-{numero}",
                        "tipo": tipo,
                        "version": 1,
                        "fecha_emision": fecha,
                        "motivo": None,
                        "reemplaza_a": None,
                    }
                )
            )

    _modificar(repo, unidad, orden.id, emitir)
    leidos = repo.obtener(orden.id).documentos.emitidos
    assert [d.id for d in leidos[-2:]] == ["DOC-0", "DOC-1"]


def test_a4_plantilla_version_vacia_sin_inventarla(armar, base, corpus):
    repo, _ = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    assert _sql(
        base,
        "select distinct plantilla_version from rma.documento_emitido",
    ) == [(None,)]


def test_a4_una_plantilla_real_se_conserva_y_no_admite_texto_vacio(
    armar, base, corpus
):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    insertar = (
        "insert into rma.documento_emitido (codigo, orden_id, tipo, version, "
        "contenido, plantilla_version, posicion) "
        "select %s, orden_id, 'GARANTIA', 1, contenido, %s, 2 "
        "from rma.documento_emitido where codigo = %s"
    )
    primero = orden.documentos.emitidos[0].id
    _ejecutar(base, insertar, ("DOC-REAL", "v3", primero))

    def cambiar(cargada):
        cargada.prioridad = 2

    _modificar(repo, unidad, orden.id, cambiar)
    assert _sql(
        base,
        "select plantilla_version from rma.documento_emitido "
        "where codigo = 'DOC-REAL'",
    ) == [("v3",)]
    with pytest.raises(psycopg.errors.CheckViolation):
        _ejecutar(
            base,
            insertar.replace("'GARANTIA'", "'COMPROBANTE_ENTREGA'"),
            ("DOC-VACIO", "  ", primero),
        )


# --- Salida ----------------------------------------------------------------


def test_a4_el_estado_dice_si_la_salida_es_entrega_o_devolucion(
    armar, base, corpus
):
    repo, unidad = armar()
    _cargar(repo, unidad, corpus[1])
    finales = _ultimos(corpus).values()
    sin_reparacion = next(
        o
        for o in finales
        if o.entrega
        and o.entrega.tipo is TipoEntrega.DEVOLUCION_SIN_REPARACION
    )
    cancelada = next(o for o in finales if o.devolucion)
    leida = repo.obtener(sin_reparacion.id)
    assert leida.entrega == sin_reparacion.entrega
    assert leida.devolucion is None
    leida = repo.obtener(cancelada.id)
    assert leida.devolucion == cancelada.devolucion
    assert leida.entrega is None
    assert _sql(
        base,
        "select s.tipo, s.retira_nombre, s.retira_vinculo, s.retira_telefono "
        "from rma.salida s join rma.orden o on o.id = s.orden_id "
        "where o.codigo = %s",
        (cancelada.id,),
    ) == [
        (
            cancelada.devolucion.tipo.value,
            cancelada.devolucion.recibido_por,
            None,
            None,
        )
    ]


def _salida(orden):
    return EntregaEquipo(
        entregado_por=f.RECEPCION,
        recibido_por="Titular",
        fecha=orden.updated_at,
    )


@pytest.mark.parametrize("campo", ["entrega", "devolucion"])
def test_a4_una_salida_que_no_corresponde_al_estado_se_rechaza(
    armar, base, corpus, campo
):
    """Se releeria en el otro campo."""
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    antes = _filas(base)

    def salir(cargada):
        setattr(cargada, campo, _salida(cargada))
        if campo == "devolucion":
            cargada.estado_workflow = EstadoWorkflow.ENTREGADA

    with pytest.raises(PersistenciaError, match="no corresponde al estado"):
        _modificar(repo, unidad, orden.id, salir)
    assert _filas(base) == antes


def test_a4_una_salida_guardada_no_cambia(armar, base, corpus):
    repo, unidad = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)

    def devolver(cargada):
        cargada.devolucion = _salida(cargada)

    _modificar(repo, unidad, orden.id, devolver)

    def corregir(cargada):
        cargada.devolucion.recibido_por = "Otra persona"

    with pytest.raises(PersistenciaError, match="inmutable"):
        _modificar(repo, unidad, orden.id, corregir)
    assert repo.obtener(orden.id).devolucion.recibido_por == "Titular"


def test_a4_la_entrega_cierra_la_orden_con_sus_documentos(armar, base, corpus):
    """La salida y los documentos entran antes del cierre (regla 9)."""
    repo, unidad = armar()
    pasos = _pasos(corpus, _completa(corpus).id)
    _cargar(repo, unidad, pasos)
    final = pasos[-1]
    assert final.esta_cerrada and final.entrega
    assert _sql(
        base,
        "select o.cerrada_en is not null, s.tipo, "
        "(select count(*) from rma.documento_emitido d "
        "where d.orden_id = o.id) "
        "from rma.orden o join rma.salida s on s.orden_id = o.id "
        "where o.codigo = %s",
        (final.id,),
    ) == [(True, final.entrega.tipo.value, len(final.documentos.emitidos))]
    assert repo.obtener(final.id) == final


# --- Transaccion -----------------------------------------------------------


def _agregar_de_todo(cargada):
    fecha = cargada.updated_at
    cargada.recepcion.notas.append(
        NotaRecepcion(usuario_id=f.RECEPCION, fecha=fecha, texto="Nota.")
    )
    cargada.fotos.append(_foto(50, fecha, f.RECEPCION))
    cargada.documentos.emitidos.append(
        _version_nueva(cargada, cargada.documentos.emitidos[-1].id)
    )


def test_a4_un_error_a_mitad_del_guardado_revierte_todo(armar, base, corpus):
    """Falla al final, con notas, fotos y documentos ya insertados."""
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    antes = _filas(base), _version(base, orden.id)

    def romper(cargada):
        _agregar_de_todo(cargada)
        cargada.historial.append(
            HistorialWorkflow(
                referencia_id="ACC-REP-999",
                accion="SIN_EQUIVALENCIA",
                fecha=cargada.updated_at,
            )
        )

    with pytest.raises(PersistenciaError, match="no tiene equivalencia"):
        _modificar(repo, unidad, orden.id, romper)
    assert (_filas(base), _version(base, orden.id)) == antes
    assert repo.obtener(orden.id) == orden


def test_a4_una_clave_de_foto_repetida_revierte_todo(armar, base, corpus):
    """La unicidad de negocio llega desde la base, a mitad del guardado."""
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    antes = _filas(base), _version(base, orden.id)

    def repetir(cargada):
        _agregar_de_todo(cargada)
        cargada.fotos[-1].objeto = cargada.fotos[0].objeto

    with pytest.raises(ConflictoDeEscrituraError) as capturado:
        _modificar(repo, unidad, orden.id, repetir)
    assert capturado.value.sqlstate == "23505"
    assert (_filas(base), _version(base, orden.id)) == antes


def test_a4_un_comando_es_una_accion_y_una_version(armar, base, corpus):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    antes, version = _filas(base), _version(base, orden.id)

    def comando(cargada):
        _agregar_de_todo(cargada)
        cargada.historial.append(
            HistorialWorkflow(
                referencia_id="PROC-REP-170",
                accion="ENCOLAR",
                fecha=cargada.updated_at,
                usuario_id=f.RECEPCION,
            )
        )

    _modificar(repo, unidad, orden.id, comando)
    despues = _filas(base)
    assert despues["accion_usuario"] == antes["accion_usuario"] + 1
    assert despues["evento_negocio"] == antes["evento_negocio"] + 1
    assert despues["foto"] == antes["foto"] + 1
    assert despues["recepcion_nota"] == antes["recepcion_nota"] + 1
    assert despues["documento_emitido"] == antes["documento_emitido"] + 1
    assert _version(base, orden.id) == version + 1


def test_a4_un_cambio_sin_historial_sube_la_version(armar, base, corpus):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    version = _version(base, orden.id)

    def anotar(cargada):
        cargada.recepcion.notas.append(
            NotaRecepcion(
                usuario_id=f.RECEPCION, fecha=orden.updated_at, texto="Nota."
            )
        )

    _modificar(repo, unidad, orden.id, anotar)
    assert _version(base, orden.id) == version + 1


def test_a4_guardar_otra_vez_no_duplica_nada(armar, base, corpus):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    antes = _filas(base), _version(base, orden.id)
    with unidad.transaccion():
        cargada = repo.obtener_para_modificar(orden.id)
        repo.guardar(cargada)
        repo.guardar(cargada.model_copy(deep=True))
    assert (_filas(base), _version(base, orden.id)) == antes


def test_a4_dos_guardar_del_comando_no_repiten_filas(armar, base, corpus):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    antes = _filas(base)
    with unidad.transaccion():
        cargada = repo.obtener_para_modificar(orden.id)
        _agregar_de_todo(cargada)
        repo.guardar(cargada)
        cargada.prioridad = 2
        repo.guardar(cargada)
    despues = _filas(base)
    assert despues["foto"] == antes["foto"] + 1
    assert despues["recepcion_nota"] == antes["recepcion_nota"] + 1
    assert despues["documento_emitido"] == antes["documento_emitido"] + 1


def test_a4_una_lectura_vieja_sigue_rechazada(armar, base, corpus):
    """La precondicion de QA-A2-H1 con las partes nuevas."""
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    vieja = repo.obtener(orden.id)

    def anotar(cargada):
        cargada.recepcion.notas.append(
            NotaRecepcion(
                usuario_id=f.RECEPCION, fecha=orden.updated_at, texto="Nueva."
            )
        )

    _modificar(repo, unidad, orden.id, anotar)
    with pytest.raises(PersistenciaError, match="obtener_para_modificar"):
        repo.guardar(vieja)
    assert repo.obtener(orden.id).recepcion.notas[-1].texto == "Nueva."


# --- Migracion -------------------------------------------------------------


def _con_replica(url, *sentencias):
    """Sin triggers: lo que hace una base anterior, no un comando."""
    with psycopg.connect(url, autocommit=True) as conexion:
        conexion.execute("set session_replication_role = replica")
        for sentencia in sentencias:
            conexion.execute(sentencia)


def test_a4_las_filas_sin_posicion_se_leen_primero(armar, base, corpus):
    """Las anteriores a la migracion quedan como estaban, y las nuevas se
    numeran a continuacion."""
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    _con_replica(
        base,
        *(
            f"update rma.{tabla} set posicion = null"
            for tabla in TABLAS_POSICION
        ),
    )
    assert repo.obtener(orden.id) == orden

    def anotar(cargada):
        cargada.recepcion.notas.append(
            NotaRecepcion(
                usuario_id=f.RECEPCION,
                # Mas vieja que las otras: decide la posicion, no la fecha.
                fecha=orden.created_at - timedelta(days=1),
                texto="La ultima.",
            )
        )

    _modificar(repo, unidad, orden.id, anotar)
    notas = repo.obtener(orden.id).recepcion.notas
    assert notas[-1].texto == "La ultima."
    assert notas[:-1] == orden.recepcion.notas


def test_a4_sin_posicion_las_versiones_empatadas_siguen_su_cadena(
    armar, base, corpus
):
    """Dos correcciones en el mismo tic del reloj comparten
    ``reemplazado_en``: desempata ``registrado_en``, no el ``uuid``. Las fechas
    y los ids se fijan, con los ids al reves, para que el azar no decida."""
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    versiones = orden.recepcion.versiones_anteriores
    assert len(versiones) == 2
    fila = _fila_orden(base, orden.id)
    cambio = (
        "update rma.recepcion_version set posicion = null, id = '{id}', "
        "registrado_en = '{registrado}', "
        "reemplazado_en = '2026-01-03T00:00:00+00:00' "
        f"where orden_id = '{fila}' and posicion = {{posicion}}"
    )
    _con_replica(
        base,
        cambio.format(
            id="ffffffff-ffff-4fff-bfff-ffffffffffff",
            registrado="2026-01-01T00:00:00+00:00",
            posicion=1,
        ),
        cambio.format(
            id="00000000-0000-4000-8000-000000000000",
            registrado="2026-01-02T00:00:00+00:00",
            posicion=2,
        ),
    )
    leidas = repo.obtener(orden.id).recepcion.versiones_anteriores
    assert [v.datos for v in leidas] == [v.datos for v in versiones]


def test_a4_dos_filas_no_comparten_posicion(armar, base, corpus):
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    fila = _fila_orden(base, orden.id)
    usuario = _sql(base, "select id from rma.usuario limit 1")[0][0]
    with pytest.raises(psycopg.errors.UniqueViolation):
        _ejecutar(
            base,
            "insert into rma.recepcion_nota "
            "(orden_id, texto, usuario_id, posicion) values (%s, 'x', %s, 1)",
            (fila, usuario),
        )


def test_a4_la_migracion_es_aditiva_sobre_datos_existentes(
    armar, base, corpus
):
    """Se vuelve el esquema atras sobre una base con datos y se aplica la
    migracion real: ninguna fila cambia."""
    repo, unidad = armar()
    orden = _hasta_antes_del_cierre(repo, unidad, corpus)
    migracion = next(
        a
        for a in archivos_sql()
        if a.name.endswith("_e4_recepcion_documentos.sql")
    )
    _con_replica(
        base,
        "update rma.documento_emitido set plantilla_version = 'v1'",
        "alter table rma.documento_emitido "
        "alter column plantilla_version set not null",
        *(
            f"alter table rma.{tabla} drop column posicion"
            for tabla in TABLAS_POSICION
        ),
    )
    contenido = [
        f"select to_jsonb(t) from rma.{tabla} t order by id"
        for tabla in TABLAS_POSICION
    ]
    antes = [_sql(base, consulta_) for consulta_ in contenido]
    assert all(antes)
    _ejecutar(base, migracion.read_text(encoding="utf-8"))
    despues = [
        [
            ({k: v for k, v in fila[0].items() if k != "posicion"},)
            for fila in _sql(base, consulta_)
        ]
        for consulta_ in contenido
    ]
    assert despues == antes
    assert _sql(
        base, "select distinct plantilla_version from rma.documento_emitido"
    ) == [("v1",)]
    assert _sql(base, "select count(posicion) from rma.documento_emitido") == [
        (0,)
    ]
    assert repo.obtener(orden.id) == orden


def test_a4_el_rol_del_backend_escribe_y_no_altera_la_historia(base):
    for tabla in TABLAS_A4[:6]:
        assert _sql(
            base,
            "select has_table_privilege('rma_backend', %s, 'INSERT'), "
            "has_table_privilege('rma_backend', %s, 'UPDATE'), "
            "has_table_privilege('rma_backend', %s, 'DELETE')",
            (f"rma.{tabla}", f"rma.{tabla}", f"rma.{tabla}"),
        ) == [(True, False, False)]


def test_a4_el_trigger_de_fotos_funciona_con_el_rol_del_backend(
    armar, base, corpus
):
    """``FOR NO KEY UPDATE`` exige el permiso de actualizar la Orden."""
    repo, _ = armar()
    orden = _con_ejecuciones(corpus)
    repo.guardar(orden)
    fila = _fila_orden(base, orden.id)
    usuario = _sql(base, "select id from rma.usuario limit 1")[0][0]
    with psycopg.connect(base) as conexion:
        conexion.execute("set local role rma_backend")
        conexion.execute(FOTO_SQL, ("ROL-1", fila, "rol/1", usuario))
        conexion.rollback()


# --- Comandos reales -------------------------------------------------------


def _contexto(repo, unidad, corpus):
    return ApplicationContext(
        ordenes=repo,
        catalogos=JsonCatalogosRepository(
            Settings(_env_file=None, data_dir=corpus[0]).catalogos_dir
        ),
        fotos=AlmacenFotosMemoria(),
        unidad_de_trabajo=unidad,
    )


def test_a4_los_comandos_de_recepcion_funcionan_sobre_postgres(
    armar, base, corpus
):
    """Casos de uso reales, sin simular nada: cada uno deja lo mismo que
    devuelve."""
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden = crear_orden(
        contexto,
        usuario_id=f.RECEPCION,
        cliente=Cliente(id="CLI-A4", nombre_apellido="Ana", telefono="341-9"),
        equipo=Equipo(
            id="EQP-A4",
            marca="Apple",
            modelo="iPhone 13",
            falla_reportada="No enciende.",
        ),
    )
    codigo = orden.id
    version = _version(base, codigo)

    def comprobar(resultado):
        nonlocal version
        assert repo.obtener(codigo) == resultado
        assert _version(base, codigo) == version + 1
        version += 1
        return resultado

    for estado in ("Con rayones.", "Con rayones y un golpe."):
        comprobar(
            registrar_recepcion(
                contexto,
                orden_id=codigo,
                usuario_id=f.RECEPCION,
                datos=DatosRecepcion(estado_fisico=estado),
            )
        )
    comprobar(
        agregar_observacion_recepcion(
            contexto,
            orden_id=codigo,
            usuario_id=f.RECEPCION,
            texto="Llamar antes.",
        )
    )
    comprobar(
        agregar_foto(
            contexto, orden_id=codigo, usuario_id=f.RECEPCION, contenido=JPEG
        )
    )
    comprobar(
        definir_reparacion(
            contexto,
            orden_id=codigo,
            usuario_id=f.RECEPCION,
            tipo_reparacion_id=f.BATERIA,
        )
    )
    final = repo.obtener(codigo)
    assert len(final.recepcion.versiones_anteriores) >= 1
    assert final.fotos and final.recepcion.notas
    # El comprobante de ingreso necesita listar_con_reservas (A5): la
    # custodia se decide por el camino de revision.


def _recibida_por_revision(contexto, repo, codigo):
    orden = enviar_a_revision(
        contexto, orden_id=codigo, usuario_id=f.RECEPCION
    )
    assert repo.obtener(codigo) == orden
    orden = registrar_recepcion(
        contexto,
        orden_id=codigo,
        usuario_id=f.RECEPCION,
        datos=DatosRecepcion(estado_fisico="Sano."),
    )
    assert repo.obtener(codigo) == orden
    orden = confirmar_recepcion(
        contexto, orden_id=codigo, usuario_id=f.RECEPCION
    )
    assert repo.obtener(codigo) == orden
    assert orden.recepcion.decidida
    return orden


def _orden_nueva(contexto, sufijo):
    return crear_orden(
        contexto,
        usuario_id=f.RECEPCION,
        cliente=Cliente(
            id=f"CLI-{sufijo}", nombre_apellido="Ana", telefono="341-9"
        ),
        equipo=Equipo(
            id=f"EQP-{sufijo}",
            marca="Apple",
            modelo="iPhone 13",
            falla_reportada="No enciende.",
        ),
    )


def test_a4_comandos_reales_de_custodia_documentos_y_devolucion(armar, corpus):
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    codigo = _orden_nueva(contexto, "DEV").id
    _recibida_por_revision(contexto, repo, codigo)
    # El proceso ya emitio la primera version: esta la reemplaza.
    agregar_observacion_recepcion(
        contexto, orden_id=codigo, usuario_id=f.RECEPCION, texto="Visible."
    )
    reemplazo = emitir_comprobante_recepcion(
        contexto,
        orden_id=codigo,
        usuario_id=f.RECEPCION,
        motivo="Se agrego una nota.",
    )
    assert repo.obtener(codigo) == reemplazo
    documentos = reemplazo.documentos.emitidos
    assert documentos[-1].reemplaza_a == documentos[-2].id
    cancelada = cancelar_orden(
        contexto,
        orden_id=codigo,
        usuario_id=f.RECEPCION,
        motivo="El cliente desiste.",
    )
    assert repo.obtener(codigo) == cancelada
    devuelta = registrar_devolucion(
        contexto,
        orden_id=codigo,
        usuario_id=f.RECEPCION,
        recibido_por="Titular",
    )
    assert repo.obtener(codigo) == devuelta
    assert devuelta.devolucion is not None


def test_a4_comando_real_de_equipo_no_recibido(armar, corpus):
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    codigo = _orden_nueva(contexto, "NOR").id
    cancelar_orden(
        contexto,
        orden_id=codigo,
        usuario_id=f.RECEPCION,
        motivo="El cliente desiste.",
    )
    orden = registrar_no_recepcion(
        contexto,
        orden_id=codigo,
        usuario_id=f.RECEPCION,
        motivo="Nunca trajo el equipo.",
    )
    assert repo.obtener(codigo) == orden
    assert orden.recepcion.no_recibido is not None


def test_a4_subidas_reales_simultaneas_dan_el_error_funcional(
    armar, base, corpus
):
    """El 409 de siempre, no el 500 del trigger: el service vuelve a mirar
    el limite con la Orden ya bloqueada."""
    repo, unidad = armar(pool_max=5)
    orden = _con_fotos(repo, unidad, corpus, 9)
    contexto = _contexto(repo, unidad, corpus)
    barrera = threading.Barrier(4)
    resultados = []

    def subir():
        barrera.wait(10)
        try:
            agregar_foto(
                contexto,
                orden_id=orden.id,
                usuario_id=f.RECEPCION,
                contenido=JPEG,
            )
            resultados.append("guardada")
        except PrecondicionInvalidaError as error:
            resultados.append(str(error))

    hilos = [threading.Thread(target=subir) for _ in range(4)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    limite = "La Orden ya tiene 10 fotos, el maximo."
    assert sorted(resultados) == sorted(["guardada"] + [limite] * 3)
    assert len(repo.obtener(orden.id).fotos) == 10
    assert _version(base, orden.id) == 2


def test_a4_la_entrega_real_cierra_una_garantia(armar, corpus):
    """Una garantia no se cobra: su cierre real no necesita A3. El origen se
    carga completo y la garantia, hasta antes de entregar."""
    repo, unidad = armar()
    final = next(
        o
        for o in _ultimos(corpus).values()
        if o.orden_origen_id and o.esta_cerrada
    )
    _cargar(repo, unidad, _pasos(corpus, final.orden_origen_id))
    abiertos = [o for o in _pasos(corpus, final.id) if not o.esta_cerrada]
    _cargar(repo, unidad, abiertos)
    entregada = entregar(
        _contexto(repo, unidad, corpus),
        orden_id=final.id,
        usuario_id=f.ADMINISTRADOR,
        recibido_por="Titular",
    )
    assert entregada.esta_cerrada
    assert repo.obtener(final.id) == entregada
    # Cerrada, nada mas se escribe.
    with pytest.raises(ConflictoDeEscrituraError, match="cerrada"):
        with unidad.transaccion():
            cargada = repo.obtener_para_modificar(final.id)
            cargada.prioridad = 2
            repo.guardar(cargada)


def test_a4_el_checkin_real_sobre_postgres(armar, base, corpus):
    repo, unidad = armar()
    pasos = _pasos(corpus, _completa(corpus).id)
    orden = next(
        o
        for o in pasos
        if all(d.control_estado is not None for d in o.reparaciones_detail)
        and o.reparaciones_detail
        and not o.recepcion.registros_checkin
        and any(
            d.control_estado.value == "APROBADO" for d in o.reparaciones_detail
        )
    )
    _cargar(repo, unidad, pasos[: pasos.index(orden) + 1])
    contexto = _contexto(repo, unidad, corpus)
    for realizado in (False, True):
        resultado = registrar_checkin(
            contexto,
            orden_id=orden.id,
            usuario_id=f.RECEPCION,
            realizado=realizado,
        )
        assert repo.obtener(orden.id) == resultado
    leida = repo.obtener(orden.id).recepcion
    assert leida.datos.checkin is True
    assert len(leida.registros_checkin) == 2
