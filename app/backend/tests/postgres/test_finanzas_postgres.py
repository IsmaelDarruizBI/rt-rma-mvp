"""Pagos, devoluciones de dinero y descuentos en PostgreSQL (E4, slice A3).

Contra la base local descartable, con el corpus de flujos reales
(``corpus_ordenes.py``, que ya incluye anticipos, pago parcial y final,
anulacion, descuentos y devoluciones). Semantica que se verifica:

- En cada paso financiero del corpus, el saldo, el total, lo pagado, lo
  devuelto y el estado de pago del dominio son los de ``v_orden_saldo``.
- Los comandos reales de finanzas corren sobre PostgreSQL y dejan lo que
  devuelven; cada uno sube la version en 1.
- Pagos, devoluciones y descuentos solo crecen; de un Pago solo cambia su
  anulacion, una vez. Alterar otra cosa se rechaza sin escribir.
- Sin pagos duplicados: el mismo ``operacion_id`` en dos comandos
  simultaneos registra uno solo, y la base tampoco admite dos en la Orden.
- Todo o nada: un error a mitad del guardado no deja el pago.
- La devolucion no choca con las claves foraneas que referencian su pago.

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (seccion 15).
"""

import threading
from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.application import (  # noqa: E402
    anular_pago_de_orden,
    aplicar_descuento_de_orden,
    cancelar_detalle,
    crear_orden,
    definir_reparacion,
    registrar_devolucion_de_dinero,
    registrar_pago_de_orden,
)
from app.domain.models import (  # noqa: E402
    Cliente,
    Equipo,
    HistorialWorkflow,
    Pago,
)
from app.domain.models.descuentos import RegistroDescuento  # noqa: E402
from app.domain.models.enums import TipoDescuento  # noqa: E402
from app.domain.models.pagos import (  # noqa: E402
    AnulacionPago,
    DevolucionDinero,
)
from app.repositories.exceptions import (  # noqa: E402
    ConflictoDeEscrituraError,
    PersistenciaError,
)
from app.services import PrecondicionInvalidaError  # noqa: E402
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import (  # noqa: E402
    _contexto,
    _guardar_paso,
    _sql,
    _version,
)

# Las bases y el corpus son los de las pruebas de A1 y A2.
armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla

TABLAS_A3 = (
    "pago",
    "devolucion_dinero",
    "descuento",
    "evento_negocio",
    "accion_usuario",
)


def _filas(url):
    return {
        tabla: _sql(url, f"select count(*) from rma.{tabla}")[0][0]
        for tabla in TABLAS_A3
    }


def _saldo_sql(url, codigo):
    return _sql(
        url,
        "select s.subtotal, s.descuento_aplicado, s.total, s.pagado, "
        "s.devuelto, s.saldo, s.estado_pago from rma.v_orden_saldo s "
        "join rma.orden o on o.id = s.orden_id where o.codigo = %s",
        (codigo,),
    )[0]


def _saldo_dominio(orden):
    return (
        orden.subtotal,
        orden.descuento_aplicado,
        orden.total,
        orden.resumen_pago.pagado,
        orden.resumen_pago.devuelto,
        orden.saldo,
        orden.estado_pago.value,
    )


def _con_finanzas(corpus):
    return {
        o.id
        for o in corpus[1]
        if o.resumen_pago.pagos or o.descuentos or o.resumen_pago.devoluciones
    }


def _cargar(repo, unidad, pasos):
    vistos = set()
    for paso in pasos:
        _guardar_paso(repo, unidad, paso, paso.id in vistos)
        vistos.add(paso.id)


def _nueva(contexto, sufijo="1"):
    """Una Orden de cliente externo con un trabajo definido: cobrable."""
    creada = crear_orden(
        contexto,
        usuario_id=f.RECEPCION,
        cliente=Cliente(
            id=f"CLI-A3-{sufijo}", nombre_apellido="Ana", telefono="341"
        ),
        equipo=Equipo(
            id=f"EQP-A3-{sufijo}",
            marca="Apple",
            modelo="iPhone 13",
            falla_reportada="No enciende.",
        ),
    )
    return definir_reparacion(
        contexto,
        orden_id=creada.id,
        usuario_id=f.RECEPCION,
        tipo_reparacion_id=f.BATERIA,
    )


def _pagar(contexto, orden_id, monto, **extra):
    orden, _ = registrar_pago_de_orden(
        contexto,
        orden_id=orden_id,
        usuario_id=f.RECEPCION,
        monto=Decimal(monto),
        metodo=extra.pop("metodo", "EFECTIVO"),
        **extra,
    )
    return orden


# --- Equivalencia con el dominio ------------------------------------------


def test_a3_el_corpus_cubre_las_finanzas(corpus):
    ultimas = {o.id: o for o in corpus[1] if o.id in _con_finanzas(corpus)}
    pagos = [p for o in ultimas.values() for p in o.resumen_pago.pagos]
    assert {p.tipo_pago.value for p in pagos} >= {
        "ANTICIPO",
        "PARCIAL",
        "FINAL",
    }
    assert any(p.anulacion for p in pagos)
    assert any(p.operacion_id for p in pagos)
    assert any(o.resumen_pago.devoluciones for o in ultimas.values())
    descuentos = [d for o in ultimas.values() for d in o.descuentos]
    assert {d.tipo for d in descuentos} == {
        TipoDescuento.PORCENTAJE,
        TipoDescuento.IMPORTE,
        None,
    }
    assert any(p.pago_id for o in ultimas.values() for p in o.historial)


def test_a3_el_saldo_de_cada_paso_es_el_de_la_vista(armar, base, corpus):
    """Cada paso de las Ordenes con finanzas: la Orden vuelve igual, y el
    saldo y el estado de pago del dominio son los de ``v_orden_saldo``."""
    repo, unidad = armar()
    codigos = _con_finanzas(corpus)
    vistos = set()
    for paso in corpus[1]:
        if paso.id not in codigos:
            continue
        _guardar_paso(repo, unidad, paso, paso.id in vistos)
        vistos.add(paso.id)
        leida = repo.obtener(paso.id)
        assert leida == paso
        assert leida.model_dump(mode="json") == paso.model_dump(mode="json")
        assert _saldo_sql(base, paso.id) == _saldo_dominio(paso)
    # Los pasos del historial con pago lo referencian por clave foranea.
    assert _sql(
        base,
        "select count(*) from rma.evento_negocio e "
        "join rma.pago p on p.id = e.pago_id and p.orden_id = e.orden_id",
    )[0][0] == sum(
        1
        for o in {p.id: p for p in corpus[1] if p.id in codigos}.values()
        for h in o.historial
        if h.pago_id
    )


def test_a3_un_importe_con_ceros_vuelve_sin_ellos(armar, base, corpus):
    """DE3-3: el valor es el mismo; la representacion pierde los ceros."""
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden = _pagar(contexto, _nueva(contexto).id, "100.50")
    leido = repo.obtener(orden.id).resumen_pago.pagos[0].monto
    assert leido == Decimal("100.50")
    assert str(leido) == "100.5"


# --- Comandos reales -------------------------------------------------------


def test_a3_los_comandos_reales_de_finanzas(armar, base, corpus):
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden = _nueva(contexto)
    version = _version(base, orden.id)

    def comprobar(resultado):
        nonlocal version
        version += 1
        assert repo.obtener(resultado.id) == resultado
        assert _version(base, resultado.id) == version
        assert _saldo_sql(base, resultado.id) == _saldo_dominio(resultado)

    seña = _pagar(contexto, orden.id, "10000", operacion_id="op-1")
    comprobar(seña)
    segundo = _pagar(
        contexto, orden.id, "5000", metodo="TRANSFERENCIA", referencia="T-9"
    )
    comprobar(segundo)
    anulado, _ = anular_pago_de_orden(
        contexto,
        orden_id=orden.id,
        pago_id=segundo.resumen_pago.pagos[-1].id,
        usuario_id=f.ADMINISTRADOR,
        motivo="Mal cargado.",
    )
    comprobar(anulado)
    for tipo, valor in (
        (TipoDescuento.PORCENTAJE, Decimal("12.5")),
        (None, None),
        (TipoDescuento.IMPORTE, Decimal("700.25")),
    ):
        descontada, _ = aplicar_descuento_de_orden(
            contexto,
            orden_id=orden.id,
            usuario_id=f.RECEPCION,
            tipo=tipo,
            valor=valor,
            motivo="Acuerdo comercial.",
        )
        comprobar(descontada)
    # Un trabajo cancelado deja credito a favor; se devuelve desde la sena.
    cancelada = cancelar_detalle(
        contexto,
        orden_id=orden.id,
        detalle_id="DET-001",
        usuario_id=f.RECEPCION,
        motivo="El cliente desiste.",
    )
    comprobar(cancelada)
    assert cancelada.saldo == Decimal("-10000")
    devuelta, _ = registrar_devolucion_de_dinero(
        contexto,
        orden_id=orden.id,
        pago_id=seña.resumen_pago.pagos[0].id,
        usuario_id=f.ADMINISTRADOR,
        monto=Decimal("10000"),
        medio="EFECTIVO",
        motivo="Se cancelo el trabajo.",
        operacion_id="dev-1",
    )
    comprobar(devuelta)
    assert devuelta.saldo == 0
    assert _sql(
        base,
        "select count(*) from rma.pago where operacion_id = 'op-1'",
    ) == [(1,)]


def test_a3_un_reintento_no_duplica_el_pago_ni_escribe(armar, base, corpus):
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden = _pagar(contexto, _nueva(contexto).id, "1000", operacion_id="x")
    antes, version = _filas(base), _version(base, orden.id)
    with pytest.raises(PrecondicionInvalidaError, match="no se duplica"):
        _pagar(contexto, orden.id, "1000", operacion_id="x")
    assert _filas(base) == antes
    assert _version(base, orden.id) == version


def test_a3_dos_envios_simultaneos_registran_un_solo_pago(armar, base, corpus):
    """El mismo envio dos veces a la vez: el bloqueo de la Orden los
    serializa y el segundo ve el primero. Un solo Pago."""
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden = _nueva(contexto)
    barrera = threading.Barrier(2)
    resultados = []

    def enviar():
        barrera.wait(10)
        try:
            _pagar(contexto, orden.id, "2500", operacion_id="doble")
            resultados.append("registrado")
        except PrecondicionInvalidaError:
            resultados.append("duplicado")

    hilos = [threading.Thread(target=enviar) for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert sorted(resultados) == ["duplicado", "registrado"]
    assert len(repo.obtener(orden.id).resumen_pago.pagos) == 1
    assert _sql(base, "select count(*) from rma.pago") == [(1,)]


def test_a3_pagos_simultaneos_distintos_se_conservan(armar, base, corpus):
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden = _nueva(contexto)
    version = _version(base, orden.id)
    barrera = threading.Barrier(3)
    errores = []

    def enviar(numero):
        barrera.wait(10)
        try:
            _pagar(contexto, orden.id, "1000", operacion_id=f"op-{numero}")
        except Exception as error:  # noqa: BLE001
            errores.append(error)

    hilos = [threading.Thread(target=enviar, args=(n,)) for n in range(3)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert errores == []
    leida = repo.obtener(orden.id)
    assert leida.resumen_pago.pagado == Decimal("3000")
    assert _version(base, orden.id) == version + 3
    assert _saldo_sql(base, orden.id) == _saldo_dominio(leida)


def test_a3_la_base_no_admite_dos_pagos_con_la_misma_operacion(
    armar, base, corpus
):
    """Red por debajo del service: el indice unico da el 409 de L-3."""
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden = _pagar(contexto, _nueva(contexto).id, "1000", operacion_id="u")
    antes = _filas(base)
    with pytest.raises(ConflictoDeEscrituraError) as capturado:
        with unidad.transaccion():
            cargada = repo.obtener_para_modificar(orden.id)
            copia = cargada.resumen_pago.pagos[0].model_copy(
                update={"id": "PAG-OTRO"}
            )
            cargada.resumen_pago.pagos.append(copia)
            repo.guardar(cargada)
    assert capturado.value.restriccion == "pago_operacion"
    assert _filas(base) == antes


# --- Inmutabilidad y atomicidad -------------------------------------------


def _pagada(repo, unidad, contexto, base):
    orden = _pagar(contexto, _nueva(contexto).id, "1000")
    return orden, _filas(base), _version(base, orden.id)


def _anular(pago, fecha):
    pago.anulacion = AnulacionPago(
        usuario_id=f.ADMINISTRADOR, fecha=fecha, motivo="Error."
    )


@pytest.mark.parametrize(
    ("alterar", "mensaje"),
    [
        (
            lambda o: setattr(o.resumen_pago.pagos[0], "monto", Decimal(9)),
            "el pago",
        ),
        (
            lambda o: setattr(o.resumen_pago.pagos[0], "metodo", "OTRO"),
            "el pago",
        ),
        (lambda o: o.resumen_pago.pagos.pop(), "los pagos"),
        (
            lambda o: o.resumen_pago.pagos.insert(
                0, o.resumen_pago.pagos[0].model_copy(update={"id": "P-0"})
            ),
            "los pagos",
        ),
    ],
    ids=["monto", "medio", "quitar", "insertar-antes"],
)
def test_a3_alterar_un_pago_guardado_se_rechaza(
    armar, base, corpus, alterar, mensaje
):
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden, antes, version = _pagada(repo, unidad, contexto, base)
    with pytest.raises(PersistenciaError, match=mensaje):
        with unidad.transaccion():
            cargada = repo.obtener_para_modificar(orden.id)
            alterar(cargada)
            repo.guardar(cargada)
    assert _filas(base) == antes
    assert _version(base, orden.id) == version


def test_a3_la_anulacion_se_completa_una_sola_vez(armar, base, corpus):
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden, _, _ = _pagada(repo, unidad, contexto, base)
    with unidad.transaccion():
        cargada = repo.obtener_para_modificar(orden.id)
        _anular(cargada.resumen_pago.pagos[0], cargada.updated_at)
        repo.guardar(cargada)
    assert repo.obtener(orden.id) == cargada
    antes, version = _filas(base), _version(base, orden.id)
    with pytest.raises(PersistenciaError, match="el pago"):
        with unidad.transaccion():
            otra = repo.obtener_para_modificar(orden.id)
            otra.resumen_pago.pagos[0].anulacion.motivo = "Otro motivo."
            repo.guardar(otra)
    assert _filas(base) == antes
    assert _version(base, orden.id) == version


@pytest.mark.parametrize(
    ("alterar", "mensaje"),
    [
        (lambda o: o.descuentos.pop(), "los descuentos"),
        (
            lambda o: setattr(o.descuentos[0], "valor", Decimal("5")),
            "los descuentos",
        ),
        (
            lambda o: setattr(o.resumen_pago.pagos[0], "metodo", "BITCOIN"),
            "BITCOIN",
        ),
    ],
    ids=["quitar-descuento", "cambiar-descuento", "medio-inexistente"],
)
def test_a3_descuentos_y_medios(armar, base, corpus, alterar, mensaje):
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden = _nueva(contexto)
    aplicar_descuento_de_orden(
        contexto,
        orden_id=orden.id,
        usuario_id=f.RECEPCION,
        tipo=TipoDescuento.PORCENTAJE,
        valor=Decimal("10"),
        motivo="Promocion.",
    )
    antes, version = _filas(base), _version(base, orden.id)
    with pytest.raises(PersistenciaError, match=mensaje):
        with unidad.transaccion():
            cargada = repo.obtener_para_modificar(orden.id)
            if mensaje == "BITCOIN":
                cargada.resumen_pago.pagos.append(
                    Pago(
                        id="PAG-B",
                        monto=Decimal("1"),
                        tipo_pago="ANTICIPO",
                        metodo="EFECTIVO",
                        usuario_id=f.RECEPCION,
                        fecha=cargada.updated_at,
                    )
                )
            alterar(cargada)
            repo.guardar(cargada)
    assert _filas(base) == antes
    assert _version(base, orden.id) == version


def test_a3_una_devolucion_de_un_pago_ajeno_se_rechaza(armar, base, corpus):
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden, antes, version = _pagada(repo, unidad, contexto, base)
    with pytest.raises(PersistenciaError, match="PAG-NO-EXISTE"):
        with unidad.transaccion():
            cargada = repo.obtener_para_modificar(orden.id)
            cargada.resumen_pago.devoluciones.append(
                DevolucionDinero(
                    id="DEV-X",
                    pago_id="PAG-NO-EXISTE",
                    monto=Decimal("1"),
                    medio="EFECTIVO",
                    usuario_id=f.RECEPCION,
                    fecha=cargada.updated_at,
                    motivo="Prueba.",
                )
            )
            repo.guardar(cargada)
    assert _filas(base) == antes
    assert _version(base, orden.id) == version


def test_a3_un_error_despues_del_pago_no_deja_el_pago(armar, base, corpus):
    """El pago se inserta antes que el historial; un paso sin equivalencia
    revierte todo, tambien la accion del comando."""
    repo, unidad = armar()
    contexto = _contexto(repo, unidad, corpus)
    orden, antes, version = _pagada(repo, unidad, contexto, base)
    with pytest.raises(PersistenciaError, match="no tiene equivalencia"):
        with unidad.transaccion():
            cargada = repo.obtener_para_modificar(orden.id)
            nuevo = cargada.resumen_pago.pagos[0].model_copy(
                update={"id": "PAG-2", "operacion_id": None}
            )
            cargada.resumen_pago.pagos.append(nuevo)
            cargada.descuentos.append(
                RegistroDescuento(
                    tipo=TipoDescuento.IMPORTE,
                    valor=Decimal("1"),
                    motivo="Prueba.",
                    usuario_id=f.RECEPCION,
                    fecha=cargada.updated_at,
                )
            )
            cargada.historial.append(
                HistorialWorkflow(
                    referencia_id="ACC-REP-999",
                    accion="SIN_EQUIVALENCIA",
                    fecha=cargada.updated_at,
                    pago_id="PAG-2",
                )
            )
            repo.guardar(cargada)
    assert _filas(base) == antes
    assert _version(base, orden.id) == version


def test_a3_la_devolucion_no_choca_con_las_claves_foraneas(
    armar, base, corpus
):
    """QA-A2-M4: otra transaccion con KEY SHARE sobre el pago (una clave
    foranea que lo referencia) no frena la devolucion. Con FOR UPDATE el
    trigger esperaba hasta agotar el bloqueo."""
    repo, unidad = armar(lock_timeout_ms=1000)
    contexto = _contexto(repo, unidad, corpus)
    orden = _pagar(contexto, _nueva(contexto).id, "3000")
    orden = cancelar_detalle(
        contexto,
        orden_id=orden.id,
        detalle_id="DET-001",
        usuario_id=f.RECEPCION,
        motivo="El cliente desiste.",
    )
    pago = orden.resumen_pago.pagos[0].id
    with psycopg.connect(base) as otra:
        otra.execute(
            "select 1 from rma.pago where codigo = %s for key share", (pago,)
        )
        devuelta, _ = registrar_devolucion_de_dinero(
            contexto,
            orden_id=orden.id,
            pago_id=pago,
            usuario_id=f.ADMINISTRADOR,
            monto=Decimal("3000"),
            medio="EFECTIVO",
            motivo="Se cancelo el trabajo.",
        )
        otra.rollback()
    assert repo.obtener(orden.id) == devuelta
    assert devuelta.saldo == 0


def test_a3_la_migracion_es_aditiva(base):
    """Las columnas nuevas son nulas; la vista conserva sus columnas."""
    columnas = _sql(
        base,
        "select table_name, column_name, is_nullable "
        "from information_schema.columns where table_schema = 'rma' "
        "and column_name in ('operacion_id', 'posicion') "
        "and table_name in ('pago', 'devolucion_dinero', 'descuento') "
        "order by 1, 2",
    )
    assert columnas == [
        ("descuento", "posicion", "YES"),
        ("devolucion_dinero", "operacion_id", "YES"),
        ("devolucion_dinero", "posicion", "YES"),
        ("pago", "operacion_id", "YES"),
        ("pago", "posicion", "YES"),
    ]
    assert [
        fila[0]
        for fila in _sql(
            base,
            "select column_name from information_schema.columns "
            "where table_schema = 'rma' and table_name = 'v_orden_saldo' "
            "order by ordinal_position",
        )
    ] == [
        "orden_id",
        "subtotal",
        "descuento_aplicado",
        "total",
        "pagado",
        "devuelto",
        "saldo",
        "estado_pago",
    ]
