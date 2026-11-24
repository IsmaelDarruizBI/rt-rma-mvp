"""Stock minimo sobre PostgreSQL (DEC-AJ-11).

Migracion ``20261124000200_stock_minimo.sql``.

- La migracion es aditiva: ``insumo.stock_minimo`` opcional y >= 0, que
  ``rma_backend`` puede actualizar, y el origen STOCK_MINIMO de las
  solicitudes de compra.
- Configuracion -> Insumos lo edita con ``INSUMO_GESTIONAR`` y auditoria;
  la relectura devuelve lo guardado.
- Compras sugiere reponer hasta el minimo y descuenta lo que ya esta en
  camino (solicitudes pendientes y ordenes de compra abiertas): no se
  duplica. Inventario e Inicio muestran el mismo estado.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.application import bandejas_de_inicio, compras  # noqa: E402
from app.application.inventario import consultar_inventario  # noqa: E402
from app.application.operativa import guardar_insumo  # noqa: E402
from app.domain.models.compras import (  # noqa: E402
    ItemOrdenCompra,
    LineaRecepcion,
    OrigenSolicitud,
)
from app.services import EstadoReposicion  # noqa: E402
from app.storage.postgres.compras import (  # noqa: E402
    PostgresComprasRepository,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_insumos_admin_postgres as admin  # noqa: E402
from tests.postgres import test_reservas_postgres as reservas  # noqa: E402
from tests.postgres.test_lotes_postgres import lotes as _lotes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402
from tests.postgres.test_reservas_postgres import INSUMO, _fijar  # noqa: E402

armar = reservas.armar
base = reservas.base
corpus = reservas.corpus
plantilla = reservas.plantilla
taller = reservas.taller
lotes = _lotes
api = admin.api
cliente_insumos = admin.cliente_insumos
D = Decimal
E = EstadoReposicion


# --- Migracion ---------------------------------------------------------------


def test_la_migracion_es_aditiva(base):
    assert _sql(
        base,
        """
        select data_type, numeric_precision, numeric_scale, is_nullable
          from information_schema.columns
         where table_schema = 'rma' and table_name = 'insumo'
           and column_name = 'stock_minimo'
        """,
    ) == [("numeric", 12, 3, "YES")]
    # Ningun insumo existente queda con minimo.
    assert _sql(
        base, "select count(*) from rma.insumo where stock_minimo is not null"
    ) == [(0,)]
    assert _sql(
        base,
        "select has_column_privilege('rma_backend', 'rma.insumo', "
        "'stock_minimo', 'UPDATE')",
    ) == [(True,)]
    # rma_backend sigue sin poder escribir los saldos.
    assert _sql(
        base,
        "select has_column_privilege('rma_backend', 'rma.insumo', "
        "'stock_fisico', 'UPDATE')",
    ) == [(False,)]
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(
            base,
            "update rma.insumo set stock_minimo = -1 where clave = %s",
            (INSUMO,),
        )
    (definicion,) = _sql(
        base,
        """
        select pg_get_constraintdef(oid) from pg_constraint
         where conname = 'solicitud_compra_origen_check'
        """,
    )[0]
    for origen in ("MANUAL", "FALTANTE", "STOCK_MINIMO"):
        assert f"'{origen}'" in definicion


# --- Configuracion -> Insumos ------------------------------------------------


def _editar(cliente, usuario=f.ADMINISTRADOR, **campos):
    return cliente.put(
        "/api/admin/supplies/INS-910",
        json={
            "usuario_id": usuario,
            "codigo": "MOD-A10",
            "nombre": "Modulo A10",
            "unidad": "unidad",
            **campos,
        },
    )


def _minimo_guardado(base):
    return _sql(
        base, "select stock_minimo from rma.insumo where clave = 'INS-910'"
    )[0][0]


def test_el_minimo_se_edita_con_permiso_y_auditoria(cliente_insumos, base):
    cliente = cliente_insumos
    alta = f.ok(
        cliente.post(
            "/api/admin/supplies",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "clave": "INS-910",
                "codigo": "MOD-A10",
                "nombre": "Modulo A10",
                "unidad": "unidad",
                "stock_minimo": "3",
            },
        )
    )
    assert alta["stock_minimo"] == "3"
    assert _minimo_guardado(base) == D("3")
    # Sin INSUMO_GESTIONAR (Recepcion, Coordinacion) no se edita.
    for usuario in (f.RECEPCION, f.COORDINADOR):
        respuesta = _editar(cliente, usuario, stock_minimo="9")
        assert respuesta.status_code in (403, 409), respuesta.text
    assert _minimo_guardado(base) == D("3")
    # Hasta tres decimales; negativo, no.
    f.ok(_editar(cliente, stock_minimo="2.125"))
    assert _minimo_guardado(base) == D("2.125")
    assert "tres decimales" in f.conflicto(
        _editar(cliente, stock_minimo="2.1255")
    )
    assert _editar(cliente, stock_minimo="-1").status_code == 422
    # Sin informarlo se conserva (un cliente anterior no lo borra) ...
    f.ok(_editar(cliente, nombre="Modulo Samsung A10"))
    assert _minimo_guardado(base) == D("2.125")
    # ... y con null se quita.
    f.ok(_editar(cliente, stock_minimo=None))
    assert _minimo_guardado(base) is None
    (releido,) = [
        i
        for i in f.ok(cliente.get("/api/admin/supplies"))["insumos"]
        if i["id"] == "INS-910"
    ]
    assert releido["stock_minimo"] is None

    auditoria = _sql(
        base,
        """
        select valor_anterior, valor_nuevo, u.codigo
          from rma.cambio_configuracion c
          join rma.usuario u on u.id = c.usuario_id
         where entidad = 'INSUMO' and clave = 'INS-910'
           and campo = 'stock_minimo'
        """,
    )
    assert sorted(auditoria, key=str) == sorted(
        [
            (None, "3", f.ADMINISTRADOR),
            ("3", "2.125", f.ADMINISTRADOR),
            ("2.125", None, f.ADMINISTRADOR),
        ],
        key=str,
    )


# --- Compras, Inventario e Inicio --------------------------------------------


@pytest.fixture
def contexto_compras(lotes):
    contexto, _ = lotes
    return replace(
        contexto,
        compras=PostgresComprasRepository(contexto.unidad_de_trabajo),
    )


def _fijar_minimo(contexto, minimo):
    insumo = contexto.catalogos.obtener_insumo(INSUMO)
    return guardar_insumo(
        contexto,
        usuario_id=f.ADMINISTRADOR,
        clave=INSUMO,
        codigo=insumo.codigo,
        nombre=insumo.nombre,
        unidad=insumo.unidad,
        activo=insumo.activo,
        nuevo=False,
        control=insumo.control,
        precio=insumo.precio,
        stock_minimo=minimo,
    )


def _situacion(contexto):
    return next(
        s for s in consultar_inventario(contexto) if s.insumo.id == INSUMO
    )


def _sugerencia(contexto):
    return next(
        (
            s
            for s in compras.sugerencias_de_compra(contexto)
            if s.insumo_id == INSUMO
        ),
        None,
    )


def _a_reponer(contexto, usuario=f.COORDINADOR):
    vista = bandejas_de_inicio(contexto, usuario_id=usuario)
    (bandeja,) = [b for b in vista.bandejas if b.codigo == "STOCK_BAJO_MINIMO"]
    return [(s.insumo.id, s.estado_reposicion) for s in bandeja.insumos]


def test_reponer_hasta_el_minimo_sin_duplicar(contexto_compras, base):
    contexto = contexto_compras
    _fijar(base, 1)
    assert _situacion(contexto).estado_reposicion is E.SIN_MINIMO
    assert _sugerencia(contexto) is None
    assert _a_reponer(contexto) == []

    assert _fijar_minimo(contexto, D("4")).stock_minimo == D("4")
    situacion = _situacion(contexto)
    assert (situacion.disponible, situacion.en_camino) == (D("1"), D("0"))
    assert situacion.estado_reposicion is E.BAJO_MINIMO
    assert not situacion.faltante
    assert _a_reponer(contexto) == [(INSUMO, E.BAJO_MINIMO)]
    assert _a_reponer(contexto, f.ADMINISTRADOR) == [(INSUMO, E.BAJO_MINIMO)]

    sugerencia = _sugerencia(contexto)
    assert sugerencia.motivo is OrigenSolicitud.STOCK_MINIMO
    assert (sugerencia.por_faltante, sugerencia.por_minimo) == (D(0), D(3))
    assert sugerencia.sugerido == D("3")
    assert sugerencia.stock_minimo == D("4")

    # Se confirma una parte: la sugerencia baja y el estado sigue bajo.
    compras.crear_solicitud(
        contexto,
        usuario_id=f.RECEPCION,
        insumo_id=INSUMO,
        cantidad=D("1"),
        motivo="Reponer hasta el minimo.",
        origen=OrigenSolicitud.STOCK_MINIMO,
    )
    assert _sugerencia(contexto).sugerido == D("2")
    assert _situacion(contexto).estado_reposicion is E.BAJO_MINIMO

    # El resto: ya no se sugiere y queda «reposicion solicitada».
    segunda = compras.crear_solicitud(
        contexto,
        usuario_id=f.RECEPCION,
        insumo_id=INSUMO,
        cantidad=D("2"),
        motivo="Reponer hasta el minimo.",
        origen=OrigenSolicitud.STOCK_MINIMO,
    )
    assert segunda.origen is OrigenSolicitud.STOCK_MINIMO
    assert _sql(
        base,
        "select origen from rma.solicitud_compra where codigo = %s",
        (segunda.id,),
    ) == [("STOCK_MINIMO",)]
    assert _sugerencia(contexto) is None
    situacion = _situacion(contexto)
    assert situacion.en_camino == D("3")
    assert situacion.estado_reposicion is E.BAJO_MINIMO_REPOSICION_SOLICITADA
    assert _a_reponer(contexto) == [
        (INSUMO, E.BAJO_MINIMO_REPOSICION_SOLICITADA)
    ]

    # Las solicitudes pasan a una orden de compra: sigue en camino, sin
    # contarse dos veces.
    solicitudes = [s.id for s in compras.listar_solicitudes(contexto)]
    orden = compras.crear_orden_compra(
        contexto,
        usuario_id=f.RECEPCION,
        proveedor_id=compras.guardar_proveedor(
            contexto,
            usuario_id=f.ADMINISTRADOR,
            datos={"nombre": "Repuestos SA"},
            codigo=None,
        ).id,
        items=[
            ItemOrdenCompra(
                insumo_id=INSUMO, cantidad=D("3"), costo_unitario=D("100")
            )
        ],
        solicitudes=solicitudes,
    )
    assert _situacion(contexto).en_camino == D("3")
    assert _sugerencia(contexto) is None
    orden = compras.confirmar(
        contexto, usuario_id=f.COORDINADOR, orden_id=orden.id
    )
    assert _situacion(contexto).estado_reposicion is (
        E.BAJO_MINIMO_REPOSICION_SOLICITADA
    )

    # Llega: disponible 4, alcanza el minimo y deja de avisar.
    compras.recibir(
        contexto,
        usuario_id=f.RECEPCION,
        orden_id=orden.id,
        lineas=[
            LineaRecepcion(
                insumo_id=INSUMO, cantidad=D("3"), costo_unitario=D("100")
            )
        ],
    )
    situacion = _situacion(contexto)
    assert (situacion.disponible, situacion.en_camino) == (D("4"), D("0"))
    assert situacion.estado_reposicion is E.SUFICIENTE
    assert _a_reponer(contexto) == []
    assert _sugerencia(contexto) is None
