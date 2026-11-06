"""Integracion del Bloque A (E4 + E5, slice A8) contra PostgreSQL local.

Los recorridos reales del corpus (``corpus_ordenes.py``) corren por HTTP,
con la API de la aplicacion apuntando a PostgreSQL solo en la prueba: el
contexto de la app se reemplaza por uno con los repositories PostgreSQL.
La aplicacion no se activa (``RMA_PERSISTENCIA`` sigue en JSON).

Cubren alta, recepcion y documentos, definicion y reserva, ejecucion y
consumo, control, pagos, descuentos y devoluciones de dinero, entrega,
devolucion del equipo y garantia RMA. Los mismos recorridos corren en JSON
y se comparan Orden por Orden (los identificadores aleatorios aparte), con
el saldo de ``v_orden_saldo``, el stock del libro y
``verificar_integridad()``.

Ademas: inventario por la API (ingreso, ajuste y H-1), dos altas con el
mismo DNI nuevo (A5-3), comandos simultaneos sobre el mismo cliente
(A6-3).

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (seccion 19).
"""

import threading
from dataclasses import replace
from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

from fastapi.testclient import TestClient  # noqa: E402

from app.application import crear_orden  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.domain.models import Cliente, Equipo  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repositories.exceptions import ConflictoDeEscrituraError  # noqa: E402
from app.storage.json.catalogos import JsonCatalogosRepository  # noqa: E402
from app.storage.json.ordenes import (  # noqa: E402
    JsonOrdenReparacionRepository,
)
from app.storage.postgres.catalogos import (  # noqa: E402
    PostgresCatalogosRepository,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.corpus_ordenes import (  # noqa: E402
    _flujos,
    _flujos_de_salida,
    _flujos_financieros,
)
from tests.postgres.test_ordenes_postgres import _contexto, _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla


def _recorridos(cliente):
    _flujos(cliente)
    _flujos_de_salida(cliente)
    _flujos_financieros(cliente)
    # Inventario por la API: ingreso, ajuste confirmado y H-1.
    f.ok(
        cliente.post(
            f"/api/inventory/{f.INSUMO_BATERIA}/receipts",
            json={
                "usuario_id": f.COORDINADOR,
                "cantidad": "4",
                "motivo": "Compra al proveedor",
                "referencia": "FC-100",
            },
        )
    )
    f.ok(
        cliente.post(
            f"/api/inventory/{f.INSUMO_BATERIA}/adjustments",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "diferencia": "-1",
                "motivo": "Rotura en deposito",
                "confirmado": True,
            },
        )
    )


def _resumen(orden):
    """Lo que tiene que dar igual en JSON y PostgreSQL, sin los
    identificadores aleatorios (pagos, movimientos) ni las fechas."""
    return {
        "estado": (orden.estado_workflow.value, orden.current_process),
        "prioridad": orden.prioridad,
        "detalles": [
            (d.id, d.estado.value, d.control_estado.value, d.precio)
            for d in orden.reparaciones_detail
        ],
        "movimientos": [
            (m.tipo.value, m.insumo_id, m.cantidad)
            for m in orden.movimientos_insumo
        ],
        "pagos": [
            (p.tipo_pago.value, p.monto, p.metodo, p.anulacion is not None)
            for p in orden.resumen_pago.pagos
        ],
        "devoluciones": [
            (d.monto, d.medio) for d in orden.resumen_pago.devoluciones
        ],
        "descuentos": [(d.tipo, d.valor) for d in orden.descuentos],
        "cuenta": (orden.total, orden.saldo, orden.estado_pago.value),
        "historial": [(h.referencia_id, h.accion) for h in orden.historial],
        "documentos": [
            (d.tipo.value, d.version) for d in orden.documentos.emitidos
        ],
        "fotos": len(orden.fotos),
        "salida": (orden.entrega or orden.devolucion or None)
        and (orden.entrega or orden.devolucion).tipo.value,
        "recepcion": orden.recepcion
        and (
            orden.recepcion.registro.value,
            orden.recepcion.datos.checkin,
            len(orden.recepcion.notas),
        ),
    }


@pytest.fixture
def en_json(tmp_path_factory):
    directorio = tmp_path_factory.mktemp("bloque_a_json")
    f.sembrar(directorio)
    configuracion = Settings(
        data_dir=directorio, fotos_dir=directorio / "fotos"
    )
    with TestClient(create_app(configuracion)) as cliente:
        _recorridos(cliente)
    ordenes_json = JsonOrdenReparacionRepository(directorio / "ordenes")
    catalogos = JsonCatalogosRepository(configuracion.catalogos_dir)
    return ordenes_json.listar(), catalogos.listar_insumos()


def test_a8_los_recorridos_reales_sobre_postgres(
    armar, base, tmp_path, en_json
):
    f.sembrar(tmp_path)
    configuracion = Settings(data_dir=tmp_path, fotos_dir=tmp_path / "fotos")
    app = create_app(configuracion)
    repo, unidad = armar(pool_max=4)
    catalogos = PostgresCatalogosRepository(unidad)
    app.state.contexto = replace(
        app.state.contexto,
        ordenes=repo,
        catalogos=catalogos,
        unidad_de_trabajo=unidad,
    )
    with TestClient(app) as cliente:
        _recorridos(cliente)
        # H-1 por la API: lo reservado no se ajusta (sin reservas vigentes
        # en este punto, se reserva una unidad para probarlo).
        orden_id = f.definida(cliente, f.BATERIA)
        f.tomada(cliente, orden_id)
        f.iniciar(cliente, orden_id)
        fisico = catalogos.obtener_insumo(f.INSUMO_BATERIA).stock_fisico
        rechazo = cliente.post(
            f"/api/inventory/{f.INSUMO_BATERIA}/adjustments",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "diferencia": str(-fisico),
                "motivo": "Conteo",
                "confirmado": True,
            },
        )
        assert orden_id in f.conflicto(rechazo, "PRECONDICION_INVALIDA")

    de_json, insumos_json = en_json
    de_postgres = [o for o in repo.listar() if o.id != orden_id]
    assert [o.id for o in de_postgres] == [o.id for o in de_json]
    for pg, js in zip(de_postgres, de_json):
        assert _resumen(pg) == _resumen(js), pg.id
    # Saldos: la vista de la base coincide con el dominio en cada Orden.
    for orden in de_postgres:
        fila = _sql(
            base,
            "select s.total, s.saldo, s.estado_pago from rma.v_orden_saldo s "
            "join rma.orden o on o.id = s.orden_id where o.codigo = %s",
            (orden.id,),
        )[0]
        assert fila == (orden.total, orden.saldo, orden.estado_pago.value)
    # Stock: el libro llega al mismo fisico que JSON, sin la reserva final.
    fisico_pg = {
        clave: fisico
        for clave, fisico in _sql(
            base, "select clave, stock_fisico from rma.insumo"
        )
    }
    for insumo in insumos_json:
        assert fisico_pg[insumo.id] == insumo.stock_fisico, insumo.id
    assert _sql(
        base,
        "select stock_reservado from rma.insumo where clave = %s",
        (f.INSUMO_BATERIA,),
    ) == [(Decimal("1.000"),)]
    assert _sql(base, "select * from rma.verificar_integridad()") == []
    # Historial y trazabilidad: cada paso con su evento y su accion.
    assert _sql(
        base,
        "select count(*) from rma.evento_negocio "
        "where historial_referencia_id is not null and accion_id is null",
    ) == [(0,)]


# --- A5-3: dos altas con el mismo DNI nuevo ---------------------------------


def test_a8_dos_altas_con_el_mismo_dni_nuevo(armar, base, corpus):
    """Decision A5-3: una se guarda y la otra recibe 409, con rollback
    completo. Nunca dos clientes con el mismo DNI."""
    repo, unidad = armar(pool_max=4)
    contexto = _contexto(repo, unidad, corpus)
    barrera = threading.Barrier(2)
    resultados, errores = [], []

    def alta(sufijo):
        barrera.wait(10)
        try:
            resultados.append(
                crear_orden(
                    contexto,
                    usuario_id=f.RECEPCION,
                    cliente=Cliente(
                        id=f"CLI-DNI-{sufijo}",
                        dni="40111222",
                        nombre_apellido="Ana",
                        telefono="341",
                    ),
                    equipo=Equipo(
                        id=f"EQP-DNI-{sufijo}",
                        marca="Apple",
                        modelo="iPhone 13",
                        falla_reportada="No enciende.",
                    ),
                )
            )
        except Exception as error:  # noqa: BLE001
            errores.append(error)

    hilos = [threading.Thread(target=alta, args=(n,)) for n in "AB"]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert len(resultados) + len(errores) == 2
    assert all(isinstance(e, ConflictoDeEscrituraError) for e in errores)
    assert _sql(
        base,
        "select count(*) from rma.documento_cliente "
        "where numero_normalizado = '40111222' and vigente_hasta is null",
    ) == [(1,)]
    assert _sql(
        base,
        "select count(*) from rma.orden "
        "where cliente_documento_numero = '40111222'",
    ) == [(len(resultados),)]


# --- A6-3: comandos simultaneos sobre el mismo cliente ----------------------


def test_a8_comandos_sobre_el_mismo_cliente_no_se_bloquean(
    armar, base, corpus
):
    """Dos Ordenes del mismo cliente cambian su copia a la vez y un alta lo
    reutiliza: se serializan en el cliente, sin deadlock ni errores."""
    repo, unidad = armar(pool_max=6, lock_timeout_ms=5000)
    contexto = _contexto(repo, unidad, corpus)
    cliente = Cliente(
        id="CLI-COMPARTIDO", nombre_apellido="Ana", telefono="341-0"
    )

    def equipo(n):
        return Equipo(
            id=f"EQP-C{n}",
            marca="Apple",
            modelo="iPhone 13",
            falla_reportada="No enciende.",
        )

    a = crear_orden(
        contexto, usuario_id=f.RECEPCION, cliente=cliente, equipo=equipo(1)
    )
    b = crear_orden(
        contexto, usuario_id=f.RECEPCION, cliente=cliente, equipo=equipo(2)
    )
    barrera = threading.Barrier(3)
    errores = []

    def cambiar(codigo, telefono):
        barrera.wait(10)
        try:
            with unidad.transaccion():
                orden = repo.obtener_para_modificar(codigo)
                orden.cliente = orden.cliente.model_copy(
                    update={"telefono": telefono}
                )
                repo.guardar(orden)
        except Exception as error:  # noqa: BLE001
            errores.append(error)

    def reutilizar():
        barrera.wait(10)
        try:
            crear_orden(
                contexto,
                usuario_id=f.RECEPCION,
                cliente=cliente.model_copy(update={"telefono": "341-9"}),
                equipo=equipo(3),
                cliente_reutilizado=True,
            )
        except Exception as error:  # noqa: BLE001
            errores.append(error)

    hilos = [
        threading.Thread(target=cambiar, args=(a.id, "341-1")),
        threading.Thread(target=cambiar, args=(b.id, "341-2")),
        threading.Thread(target=reutilizar),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert errores == []
    assert _sql(
        base,
        "select count(*) from rma.cliente where codigo = 'CLI-COMPARTIDO'",
    ) == [(1,)]
    assert _sql(
        base,
        "select count(*) from rma.orden o join rma.cliente c "
        "on c.id = o.cliente_id where c.codigo = 'CLI-COMPARTIDO'",
    ) == [(3,)]
