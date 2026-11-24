"""Requisitos de insumo y pieza elegida sobre PostgreSQL (DEC-AJ-14, D-14.4).

Migracion ``20261124000600_requisitos_pieza.sql``:

- aditiva: ``tipo_reparacion_requisito`` (uno por categoria, sin borrado,
  tipo y categoria fijos) y ``detalle_pieza`` (append-only e inmutable, con
  la cadena lineal de reemplazos, la categoria del requisito y la pieza
  vigente); ningun tipo queda con requisitos ni ningun Detalle con piezas;
- ``rma_backend`` edita los previstos concretos (cantidad y quitar) y los
  requisitos (cantidad, posicion y vigencia), y solo inserta piezas;
- Configuracion: «Insumos necesarios» de un tipo con auditoria;
- la pieza elegida se reserva con el motor de siempre; la sustitucion de
  una pieza reservada es una LIBERACION_RESERVA y una RESERVA en la misma
  transaccion, con los saldos del insumo y ``v_conciliacion_inventario``
  conciliados; dos sustituciones a la vez no toman la misma unidad;
- Compras: la demanda por faltante es de la pieza elegida; un requisito sin
  pieza se informa aparte.
"""

import threading
import time
from dataclasses import replace
from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.application import piezas as app_piezas  # noqa: E402
from app.services.exceptions import RecursoNoDisponibleError  # noqa: E402
from app.storage.postgres.catalogos import (  # noqa: E402
    PostgresCatalogosRepository,
)
from app.storage.postgres.compras import (  # noqa: E402
    PostgresComprasRepository,
)
from app.storage.postgres.configuracion import (  # noqa: E402
    PostgresConfiguracionRepository,
)
from app.storage.postgres.modelos_equipo import (  # noqa: E402
    PostgresModelosEquipoRepository,
)
from app.storage.postgres.operativa import (  # noqa: E402
    PostgresConfiguracionOperativa,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.sembrado import fijar_stock  # noqa: E402
from tests.postgres.test_ordenes_postgres import _ejecutar, _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api

IPHONE_8 = "MOD-0001"
IPHONE_11 = "MOD-0003"


@pytest.fixture
def admin(api):
    app, cliente = api
    contexto = app.state.contexto
    unidad = contexto.unidad_de_trabajo
    app.state.contexto = replace(
        contexto,
        catalogos=PostgresCatalogosRepository(unidad),
        operativa=PostgresConfiguracionOperativa(unidad),
        configuracion=PostgresConfiguracionRepository(unidad),
        modelos_equipo=PostgresModelosEquipoRepository(unidad),
        compras=PostgresComprasRepository(unidad),
    )
    return app, cliente


def _alta(cliente, ruta, **cuerpo):
    return f.ok(
        cliente.post(ruta, json={"usuario_id": f.ADMINISTRADOR, **cuerpo})
    )


def _stock(base, clave, cantidad) -> None:
    with psycopg.connect(base, autocommit=True) as conexion:
        fijar_stock(conexion, clave, cantidad)


def _saldos(base, clave):
    return _sql(
        base,
        "select stock_fisico, stock_reservado from rma.insumo "
        "where clave = %s",
        (clave,),
    )[0]


def _concilia(base) -> bool:
    return _sql(
        base,
        "select bool_and(concilia) from rma.v_conciliacion_inventario",
    ) == [(True,)] and (
        _sql(base, "select * from rma.verificar_integridad()") == []
    )


def _necesarios(cliente, tipo, insumos, requisitos, usuario=f.ADMINISTRADOR):
    return cliente.put(
        f"/api/admin/repair-types/{tipo}/supplies",
        json={
            "usuario_id": usuario,
            "insumos": [{"insumo_id": i, "cantidad": c} for i, c in insumos],
            "requisitos": [
                {"categoria_id": c, "cantidad": q} for c, q in requisitos
            ],
        },
    )


@pytest.fixture
def catalogo(admin, base):
    """Baterias (CAT-001) con dos piezas para el iPhone 8 y una para el
    iPhone 11; TR-001 pide INS-001 x 1 (como antes) y una bateria."""
    app, cliente = admin
    _alta(cliente, "/api/admin/supply-categories", nombre="Baterías")
    piezas = {}
    for nombre, modelos, stock in (
        ("Batería iPhone 8 Acme", [IPHONE_8], 2),
        ("Batería iPhone 8 Beta", [IPHONE_8], 1),
        ("Batería iPhone 11", [IPHONE_11], 1),
    ):
        insumo = _alta(
            cliente,
            "/api/admin/supplies",
            nombre=nombre,
            categoria_id="CAT-001",
            modelos_compatibles=modelos,
        )
        piezas[nombre] = insumo["id"]
        _stock(base, insumo["id"], stock)
    _stock(base, f.INSUMO_BATERIA, 5)
    f.ok(
        _necesarios(
            cliente, f.BATERIA, [(f.INSUMO_BATERIA, "1")], [("CAT-001", "1")]
        )
    )
    acme, beta, once = piezas.values()
    return app, cliente, acme, beta, once


def _orden(cliente, modelo=IPHONE_8) -> str:
    orden_id = f.ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": f.RECEPCION,
                "cliente": {"nombre_apellido": "Ana", "telefono": "341-1"},
                "equipo": {
                    "modelo_tecnico_id": modelo,
                    "falla_reportada": "No carga.",
                },
                "recepcion": {
                    "estado_fisico": "Sin golpes.",
                    "funcionalidades_verificadas": True,
                },
            },
        )
    )["id"]
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details",
            json={"usuario_id": f.RECEPCION, "tipo_reparacion_id": f.BATERIA},
        )
    )
    f.finalizar(cliente, orden_id)
    return orden_id


def _elegir(cliente, orden_id, insumo, motivo=None, usuario=f.TECNICO):
    requisito = _requisito(cliente, orden_id)["requisito_id"]
    return cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/pieces",
        json={
            "usuario_id": usuario,
            "requisito_id": requisito,
            "insumo_id": insumo,
            "motivo": motivo,
        },
    )


def _requisito(cliente, orden_id) -> dict:
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    (requisito,) = f.detalle(orden, "DET-001")["requisitos_insumo"]
    return requisito


def _iniciar(cliente, orden_id, tecnico=f.TECNICO) -> str:
    f.tomada(cliente, orden_id, tecnico)
    f.evaluar_si_hace_falta(cliente, orden_id, "DET-001", tecnico)
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": tecnico},
        )
    )
    (activa,) = [
        e["id"] for e in orden["ejecuciones"] if e["estado"] == "EN_PROGRESO"
    ]
    return activa


def _libro(base, orden_id):
    return _sql(
        base,
        """
        select m.tipo, i.clave, m.cantidad, o2.codigo, x.codigo,
               u.codigo, m.stock_reservado_resultante
          from rma.movimiento_inventario m
          join rma.orden o on o.id = m.orden_id
          join rma.insumo i on i.id = m.insumo_id
          left join rma.movimiento_inventario o2
                 on o2.id = m.movimiento_origen_id
          left join rma.ejecucion x on x.id = m.ejecucion_id
          left join rma.usuario u on u.id = m.usuario_id
         where o.codigo = %s
         order by m.posicion
        """,
        (orden_id,),
    )


# --- Migracion ---------------------------------------------------------------


def test_la_migracion_es_aditiva_y_con_sus_privilegios(base):
    assert _sql(
        base, "select count(*) from rma.tipo_reparacion_requisito"
    ) == [(0,)]
    assert _sql(base, "select count(*) from rma.detalle_pieza") == [(0,)]
    privilegios = dict(
        _sql(
            base,
            """
            select t || ':' || p, has_table_privilege('rma_backend', t, p)
              from unnest(array['rma.detalle_pieza',
                                'rma.tipo_reparacion_requisito',
                                'rma.tipo_reparacion_insumo']) t,
                   unnest(array['SELECT', 'INSERT', 'UPDATE', 'DELETE']) p
            """,
        )
    )
    assert privilegios == {
        "rma.detalle_pieza:SELECT": True,
        "rma.detalle_pieza:INSERT": True,
        "rma.detalle_pieza:UPDATE": False,
        "rma.detalle_pieza:DELETE": False,
        "rma.tipo_reparacion_requisito:SELECT": True,
        "rma.tipo_reparacion_requisito:INSERT": True,
        "rma.tipo_reparacion_requisito:UPDATE": False,
        "rma.tipo_reparacion_requisito:DELETE": False,
        "rma.tipo_reparacion_insumo:SELECT": True,
        "rma.tipo_reparacion_insumo:INSERT": True,
        "rma.tipo_reparacion_insumo:UPDATE": False,
        "rma.tipo_reparacion_insumo:DELETE": True,
    }
    columnas = _sql(
        base,
        """
        select table_name, column_name
          from information_schema.column_privileges
         where grantee = 'rma_backend' and privilege_type = 'UPDATE'
           and table_name in ('tipo_reparacion_requisito',
                              'tipo_reparacion_insumo', 'detalle_pieza')
         order by 1, 2
        """,
    )
    assert columnas == [
        ("tipo_reparacion_insumo", "cantidad"),
        ("tipo_reparacion_requisito", "activo"),
        ("tipo_reparacion_requisito", "cantidad"),
        ("tipo_reparacion_requisito", "posicion"),
    ]
    assert _sql(
        base,
        """
        select e.accion, t.codigo from rma.equivalencia_historial e
          join rma.tipo_evento t on t.id = e.tipo_evento_id
         where e.referencia_id = 'ACC-REP-084' order by e.accion nulls first
        """,
    ) == [(None, "EV-REP-010"), ("SUSTITUIR_PIEZA_RESERVADA", "EV-REP-024")]


# --- Insumos necesarios ------------------------------------------------------


def test_insumos_necesarios_se_auditan_y_conservan_el_requisito(
    catalogo, base
):
    _, cliente, acme, *_ = catalogo
    (inicial,) = _sql(
        base,
        "select id, cantidad, activo from rma.tipo_reparacion_requisito",
    )
    assert (inicial[1], inicial[2]) == (Decimal("1.000"), True)
    lectura = f.ok(cliente.get("/api/admin/repair-types/supplies"))
    assert lectura["editable"] is True
    assert [
        (r["tipo_reparacion_id"], r["categoria_id"], r["cantidad"])
        for r in lectura["requisitos"]
    ] == [(f.BATERIA, "CAT-001", "1")]
    # Cambia la cantidad: el mismo requisito (las piezas lo referencian).
    cuerpo = f.ok(
        _necesarios(
            cliente, f.BATERIA, [(f.INSUMO_BATERIA, "2")], [("CAT-001", "2")]
        )
    )
    assert cuerpo["requisitos"][0]["id"] == str(inicial[0])
    # Se quita: queda inactivo, no se borra; vuelve: se reactiva.
    f.ok(_necesarios(cliente, f.BATERIA, [], []))
    assert _sql(
        base,
        "select activo from rma.tipo_reparacion_requisito",
    ) == [(False,)]
    assert _sql(
        base,
        "select count(*) from rma.tipo_reparacion_insumo ti "
        "join rma.tipo_reparacion t on t.id = ti.tipo_reparacion_id "
        "where t.codigo = %s",
        (f.BATERIA,),
    ) == [(0,)]
    f.ok(_necesarios(cliente, f.BATERIA, [], [("CAT-001", "1")]))
    assert _sql(
        base, "select id, activo from rma.tipo_reparacion_requisito"
    ) == [(inicial[0], True)]
    auditoria = _sql(
        base,
        """
        select campo, valor_anterior, valor_nuevo
          from rma.cambio_configuracion
         where entidad = 'TIPO_REPARACION' and clave = %s
           and campo in ('insumos_previstos', 'requisitos')
         order by secuencia
        """,
        (f.BATERIA,),
    )
    assert auditoria == [
        ("requisitos", None, "CAT-001 x 1"),
        ("insumos_previstos", "INS-001 x 1", "INS-001 x 2"),
        ("requisitos", "CAT-001 x 1", "CAT-001 x 2"),
        ("insumos_previstos", "INS-001 x 2", None),
        ("requisitos", "CAT-001 x 2", None),
        ("requisitos", None, "CAT-001 x 1"),
    ]
    # Una pieza que depende del modelo no es un previsto concreto.
    assert "requisito por categoria" in f.conflicto(
        _necesarios(cliente, f.BATERIA, [(acme, "1")], [("CAT-001", "1")])
    )
    # Sin el permiso (Recepcion), 409 desde el caso de uso.
    f.conflicto(
        _necesarios(
            cliente,
            f.BATERIA,
            [],
            [("CAT-001", "3")],
            usuario=f.RECEPCION,
        )
    )


def test_la_base_protege_requisitos_y_piezas(catalogo, base):
    _, cliente, acme, beta, _ = catalogo
    orden_id = _orden(cliente)
    f.ok(_elegir(cliente, orden_id, acme))
    f.ok(_elegir(cliente, orden_id, beta, motivo="Cambio."))
    filas = _sql(
        base,
        "select codigo, reemplaza_a is null from rma.detalle_pieza "
        "order by posicion",
    )
    assert [nulo for _, nulo in filas] == [True, False]
    for sentencia in (
        "update rma.detalle_pieza set motivo = 'x'",
        "delete from rma.detalle_pieza",
        "delete from rma.tipo_reparacion_requisito",
        "update rma.tipo_reparacion_requisito "
        "set categoria_id = (select id from rma.categoria_insumo limit 1), "
        "tipo_reparacion_id = (select id from rma.tipo_reparacion "
        "where codigo = 'TR-002')",
    ):
        with pytest.raises(psycopg.Error):
            _ejecutar(base, sentencia)
    # Una eleccion nueva tiene que reemplazar a la ultima del requisito.
    with pytest.raises(psycopg.Error, match="reemplazar a la última"):
        _ejecutar(
            base,
            """
            insert into rma.detalle_pieza
                (codigo, detalle_id, posicion, requisito_id,
                 tipo_reparacion_id, categoria_id, cantidad, insumo_id, causa,
                 elegida_por, elegida_en)
            select 'PZA-X', p.detalle_id, 9, p.requisito_id,
                   p.tipo_reparacion_id, p.categoria_id, 1, p.insumo_id,
                   'ELECCION', p.elegida_por, now()
              from rma.detalle_pieza p where p.posicion = 1
            """,
        )
    # Sustituir sin motivo o sin pieza (salvo una anulacion) no se guarda.
    with pytest.raises(psycopg.Error, match="detalle_pieza_"):
        _ejecutar(
            base,
            """
            insert into rma.detalle_pieza
                (codigo, detalle_id, posicion, requisito_id,
                 tipo_reparacion_id, categoria_id, cantidad, insumo_id, causa,
                 elegida_por, elegida_en, reemplaza_a)
            select 'PZA-Y', p.detalle_id, 9, p.requisito_id,
                   p.tipo_reparacion_id, p.categoria_id, 1, null,
                   'SUSTITUCION', p.elegida_por, now(), p.id
              from rma.detalle_pieza p where p.posicion = 2
            """,
        )


# --- Eleccion, reserva y sustitucion ----------------------------------------


def test_elegir_reservar_sustituir_y_consumir_concilia_el_libro(
    catalogo, base, armar
):
    _, cliente, acme, beta, _ = catalogo
    orden_id = _orden(cliente)
    assert _requisito(cliente, orden_id)["estado"] == "PENDIENTE"
    f.ok(_elegir(cliente, orden_id, acme))
    ejecucion = _iniciar(cliente, orden_id)
    assert [(t, c, q) for t, c, q, *_ in _libro(base, orden_id)] == [
        ("RESERVA", f.INSUMO_BATERIA, Decimal("1.000")),
        ("RESERVA", acme, Decimal("1.000")),
    ]
    assert _saldos(base, acme) == (Decimal("2.000"), Decimal("1.000"))
    assert _concilia(base)

    orden = f.ok(_elegir(cliente, orden_id, beta, motivo="Vino fallada."))
    reserva_acme = _sql(
        base,
        "select m.codigo from rma.movimiento_inventario m "
        "join rma.insumo i on i.id = m.insumo_id "
        "where m.tipo = 'RESERVA' and i.clave = %s",
        (acme,),
    )[0][0]
    libro = _libro(base, orden_id)
    assert [fila[:6] for fila in libro[2:]] == [
        (
            "LIBERACION_RESERVA",
            acme,
            Decimal("1.000"),
            reserva_acme,
            ejecucion,
            f.TECNICO,
        ),
        ("RESERVA", beta, Decimal("1.000"), None, ejecucion, f.TECNICO),
    ]
    assert _saldos(base, acme) == (Decimal("2.000"), Decimal("0.000"))
    assert _saldos(base, beta) == (Decimal("1.000"), Decimal("1.000"))
    assert _concilia(base)
    # El historial: la sustitucion de la pieza reservada es EV-REP-024.
    assert _sql(
        base,
        """
        select t.codigo from rma.evento_negocio e
          join rma.tipo_evento t on t.id = e.tipo_evento_id
          join rma.orden o on o.id = e.orden_id
         where o.codigo = %s and e.historial_referencia_id = 'ACC-REP-084'
         order by e.secuencia
        """,
        (orden_id,),
    ) == [("EV-REP-010",), ("EV-REP-024",)]
    # Lo guardado vuelve igual.
    repo, _ = armar()
    leida = repo.obtener(orden_id)
    assert [
        (p.causa.value, p.insumo_id, p.motivo)
        for p in leida.reparaciones_detail[0].piezas
    ] == [("ELECCION", acme, None), ("SUSTITUCION", beta, "Vino fallada.")]
    assert f.detalle(orden, "DET-001")["piezas"] == [
        p.model_dump(mode="json") for p in leida.reparaciones_detail[0].piezas
    ]

    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion}/complete",
            json={
                "usuario_id": f.TECNICO,
                "insumos_utilizados": [
                    {"insumo_id": beta, "cantidad": "1"},
                    {"insumo_id": f.INSUMO_BATERIA, "cantidad": "1"},
                ],
            },
        )
    )
    assert _saldos(base, beta) == (Decimal("0.000"), Decimal("0.000"))
    assert _saldos(base, acme) == (Decimal("2.000"), Decimal("0.000"))
    assert _concilia(base)
    # Ya consumida, la pieza no se sustituye (el trabajo tambien termino).
    f.conflicto(_elegir(cliente, orden_id, acme, motivo="Otra."))


def test_sin_pieza_elegida_no_se_inicia(catalogo, base):
    _, cliente, *_ = catalogo
    orden_id = _orden(cliente)
    f.tomada(cliente, orden_id)
    f.evaluar_si_hace_falta(cliente, orden_id, "DET-001")
    f.conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": f.TECNICO},
        ),
        "PIEZA_SIN_ELEGIR",
    )
    assert _libro(base, orden_id) == []


def test_dos_sustituciones_a_la_vez_no_toman_la_misma_unidad(
    catalogo, base, monkeypatch
):
    """La ultima unidad de la pieza nueva: una sustitucion reserva y la otra
    se rechaza sin cambiar nada (bloqueo de insumos por clave, DI-2; el
    trigger del libro es la ultima defensa)."""
    app, cliente, acme, beta, _ = catalogo
    primera = _orden(cliente)
    segunda = _orden(cliente)
    for orden_id, tecnico in ((primera, f.TECNICO), (segunda, f.TECNICO_B)):
        f.ok(_elegir(cliente, orden_id, acme, usuario=tecnico))
        _iniciar(cliente, orden_id, tecnico)
    assert _saldos(base, beta) == (Decimal("1.000"), Decimal("0.000"))
    requisito = _requisito(cliente, primera)["requisito_id"]

    original = app_piezas.cargar_reservas_externas

    def lenta(*argumentos, **nombrados):
        reservas = original(*argumentos, **nombrados)
        time.sleep(0.3)
        return reservas

    monkeypatch.setattr(app_piezas, "cargar_reservas_externas", lenta)
    contexto = app.state.contexto
    barrera = threading.Barrier(2)
    resultados, errores = {}, []

    def sustituir(orden_id, tecnico):
        barrera.wait(10)
        try:
            resultados[orden_id] = app_piezas.elegir_pieza(
                contexto,
                orden_id=orden_id,
                detalle_id="DET-001",
                requisito_id=requisito,
                insumo_id=beta,
                usuario_id=tecnico,
                motivo="La Acme vino fallada.",
            )
        except Exception as error:  # noqa: BLE001
            errores.append(error)

    hilos = [
        threading.Thread(target=sustituir, args=par)
        for par in ((primera, f.TECNICO), (segunda, f.TECNICO_B))
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert len(resultados) == 1
    assert [type(e) for e in errores] == [RecursoNoDisponibleError]
    assert _saldos(base, beta) == (Decimal("1.000"), Decimal("1.000"))
    assert _saldos(base, acme) == (Decimal("2.000"), Decimal("1.000"))
    assert _concilia(base)


# --- Compras -----------------------------------------------------------------


def test_compras_pide_la_pieza_elegida_y_avisa_las_pendientes(catalogo, base):
    _, cliente, acme, beta, _ = catalogo
    _stock(base, acme, 0)
    _stock(base, beta, 0)
    pendiente = _orden(cliente)  # sin piezas: bloqueada, sin SKU
    elegida = _orden(cliente)
    f.ok(_elegir(cliente, elegida, acme))
    # Las dos quedaron bloqueadas por recursos al definirlas; la consulta
    # de Compras evalua la pieza elegida (falta la Acme) y no pide la Beta.
    for orden_id in (pendiente, elegida):
        orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
        assert (
            f.detalle(orden, "DET-001")["condicion"]
            == "BLOQUEADO_POR_RECURSOS"
        )
    sugerencias = {
        s["insumo_id"]: s
        for s in f.ok(cliente.get("/api/purchases/suggestions"))
    }
    assert sugerencias[acme]["por_faltante"] == "1"
    assert sugerencias[acme]["ordenes"] == [elegida]
    assert beta not in sugerencias
    sin_pieza = f.ok(cliente.get("/api/purchases/suggestions/pending-pieces"))
    assert [
        (s["orden_id"], s["categoria_id"], s["cantidad"]) for s in sin_pieza
    ] == [(pendiente, "CAT-001", "1")]
