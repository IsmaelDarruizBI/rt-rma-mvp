# ruff: noqa: E501  (SQL)
"""Configuracion v2, CFG-01: codigos automaticos generados por la base.

Migracion ``20261120000100_codigos_automaticos.sql``: una secuencia por
prefijo y ``rma.siguiente_codigo(prefijo)``. Se prueba:

* los formatos de cada prefijo, sin truncar (``PRV-9999`` -> ``PRV-10000``);
* concurrencia: dos transacciones abiertas reciben codigos distintos, sin
  esperarse; una reversion deja un hueco y no repite el codigo;
* los codigos cargados por fuera (a mano, por un backend anterior) se
  saltean, sin distinguir mayusculas;
* la inicializacion desde los codigos existentes, ignorando los que no
  siguen el patron (``TR-OTROS``, ``TR-OFF``), y que la migracion aborta
  si hay codigos que solo difieren en mayusculas;
* el codigo de un catalogo no cambia (trigger) y es unico sin distinguir
  mayusculas;
* la API: altas sin codigo (generado), con codigo informado (respetado,
  compatibilidad con clientes anteriores) y duplicados como 409, nunca 500.
"""

from dataclasses import replace
from urllib.parse import urlsplit

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.storage.postgres.catalogos import (  # noqa: E402
    PostgresCatalogosRepository,
)
from app.storage.postgres.compras import PostgresComprasRepository  # noqa: E402
from app.storage.postgres.configuracion import (  # noqa: E402
    PostgresConfiguracionRepository,
)
from app.storage.postgres.operativa import (  # noqa: E402
    PostgresConfiguracionOperativa,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.base_local import (  # noqa: E402
    VARIABLE,
    archivos_sql,
    borrar_base,
    crear_base,
    url_admin_local,
)
from tests.postgres.test_movimientos_postgres import _en_paralelo  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

pytestmark = pytest.mark.postgres

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api

MIGRACION = "20261120000100_codigos_automaticos.sql"


def _siguiente(conexion, prefijo: str) -> str:
    return conexion.execute(
        "select rma.siguiente_codigo(%s)", (prefijo,)
    ).fetchone()[0]


# --- La funcion de la base ----------------------------------------------------


def test_cada_prefijo_tiene_su_formato_y_no_trunca(base):
    with psycopg.connect(base, autocommit=True) as conexion:
        codigos = {
            p: _siguiente(conexion, p)
            for p in ("TR", "CANC", "INT", "INS", "PRV", "CHK", "SC", "OC", "RGA")
        }
        # El seed tiene TR-001, TR-002 y TR-OTROS; INS-001 (BAT-IP14).
        assert codigos["TR"] == "TR-003"
        # INS continua despues del mayor INS-NNN existente (clave o codigo).
        mayor = conexion.execute(
            "select max(substring(clave from '^INS-([0-9]+)$')::int) from rma.insumo"
        ).fetchone()[0]
        assert codigos["INS"] == f"INS-{mayor + 1:03d}"
        assert codigos["CANC"] == "CANC-001"
        assert codigos["INT"] == "INT-001"
        assert codigos["PRV"] == "PRV-0001"
        assert codigos["CHK"] == "CHK-0001"
        assert codigos["SC"] == "SC-000001"
        assert codigos["OC"] == "OC-000001"
        assert codigos["RGA"] == "RGA-000001"
        conexion.execute("select setval('rma.codigo_prv_seq', 9998)")
        assert [_siguiente(conexion, "PRV") for _ in range(2)] == [
            "PRV-9999",
            "PRV-10000",
        ]
        conexion.execute("select setval('rma.codigo_oc_seq', 999999)")
        assert _siguiente(conexion, "OC") == "OC-1000000"
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            _siguiente(conexion, "XYZ")


def test_dos_transacciones_abiertas_reciben_codigos_distintos_sin_esperarse(base):
    with (
        psycopg.connect(base) as primera,
        psycopg.connect(base) as segunda,
    ):
        segunda.execute("set lock_timeout = '2s'")
        a = _siguiente(primera, "TR")  # transaccion abierta, sin confirmar
        b = _siguiente(segunda, "TR")  # no espera a la primera
        assert a != b
        primera.rollback()  # el numero de la primera queda como hueco
        segunda.commit()
    with psycopg.connect(base, autocommit=True) as conexion:
        c = _siguiente(conexion, "TR")
    assert len({a, b, c}) == 3
    assert c > b > a


def test_altas_concurrentes_por_la_base_no_repiten(base):
    def alta():
        with psycopg.connect(base) as conexion:
            codigo = _siguiente(conexion, "INS")
            conexion.execute(
                "insert into rma.insumo (clave, codigo, nombre) values (%s, %s, 'x')",
                (codigo, codigo),
            )
            conexion.commit()
            return codigo

    resultados, errores = _en_paralelo(*[alta] * 6)
    assert errores == []
    assert len(set(resultados)) == 6


def test_saltea_codigos_cargados_por_fuera_sin_distinguir_mayusculas(base):
    with psycopg.connect(base, autocommit=True) as conexion:
        # Un backend anterior (max+1) o una carga a mano usan los siguientes.
        conexion.execute(
            "insert into rma.tipo_reparacion (codigo, nombre, precio, puntaje, garantia_dias)"
            " values ('TR-003', 'a', 1, 1, 1), ('tr-004', 'b', 1, 1, 1)"
        )
        conexion.execute(
            "insert into rma.insumo (clave, codigo, nombre) values ('X-1', 'ins-002', 'y')"
        )
        assert _siguiente(conexion, "TR") == "TR-005"
        # INS mira la clave y el codigo: INS-002 ya es un codigo.
        assert _siguiente(conexion, "INS") == "INS-003"


def test_el_codigo_de_un_catalogo_no_cambia(base):
    tablas = {
        "tipo_reparacion": "TR-001",
        "mesa_trabajo": "EST-001",
        "motivo_operativo": "CANC-OTRO",
        "plantilla_mensaje": "INGRESO",
    }
    with psycopg.connect(base, autocommit=True) as conexion:
        for tabla, codigo in tablas.items():
            with pytest.raises(psycopg.errors.RestrictViolation):
                conexion.execute(
                    f"update rma.{tabla} set codigo = codigo || 'X' where codigo = %s",
                    (codigo,),
                )
        # Los demas campos se siguen editando.
        conexion.execute(
            "update rma.tipo_reparacion set nombre = 'Otro nombre' where codigo = 'TR-001'"
        )


def test_unicidad_sin_distinguir_mayusculas(base):
    with psycopg.connect(base, autocommit=True) as conexion:
        with pytest.raises(psycopg.errors.UniqueViolation):
            conexion.execute(
                "insert into rma.tipo_reparacion (codigo, nombre, precio, puntaje, garantia_dias)"
                " values ('tr-001', 'x', 1, 1, 1)"
            )
        conexion.execute(
            "insert into rma.insumo (clave, codigo, nombre) values ('INS-778', 'COD-X', 'x')"
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conexion.execute(
                "insert into rma.insumo (clave, codigo, nombre) values ('ins-778', 'OTRO', 'x')"
            )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conexion.execute(
                "insert into rma.insumo (clave, codigo, nombre) values ('INS-779', 'cod-x', 'x')"
            )


def test_solo_el_backend_genera_codigos(base):
    with psycopg.connect(base, autocommit=True) as conexion:
        for rol in ("anon", "authenticated", "service_role"):
            puede = conexion.execute(
                "select has_function_privilege(%s, 'rma.siguiente_codigo(text)', 'execute')",
                (rol,),
            ).fetchone()[0]
            assert puede is False, rol
        assert conexion.execute(
            "select has_function_privilege('rma_backend', 'rma.siguiente_codigo(text)', 'execute')"
            " and has_sequence_privilege('rma_backend', 'rma.codigo_tr_seq', 'usage')"
        ).fetchone()[0]


# --- La migracion sobre datos anteriores --------------------------------------


def _admin_url() -> str:
    import os

    url = os.environ.get(VARIABLE)
    if not url:
        pytest.skip(f"{VARIABLE} no esta definida: sin PostgreSQL local.")
    return url_admin_local(url)


def _base_anterior(admin: str) -> str:
    anteriores = [
        a for a in archivos_sql() if "migrations" in a.parts and a.name < MIGRACION
    ]
    return crear_base(admin, anteriores)


def _migracion():
    return next(a for a in archivos_sql() if a.name == MIGRACION)


def test_la_migracion_continua_los_codigos_existentes_e_ignora_los_otros():
    admin = _admin_url()
    url = _base_anterior(admin)
    try:
        with psycopg.connect(url, autocommit=True) as conexion:
            conexion.execute(
                "insert into rma.tipo_reparacion (codigo, nombre, precio, puntaje, garantia_dias) values"
                " ('TR-OTROS', 'Otros', 0, 0, 0), ('TR-OFF', 'a', 1, 1, 1),"
                " ('TR-041', 'b', 1, 1, 1), ('TR-9', 'c', 1, 1, 1)"
            )
            conexion.execute(
                "insert into rma.insumo (clave, codigo, nombre) values"
                " ('INS-S', 'INS-012', 'a'), ('INS-007', 'BAT-X', 'b')"
            )
            conexion.execute(
                "insert into rma.motivo_operativo (codigo, tipo, nombre, orden)"
                " values ('CANC-PRECIO', 'CANCELACION', 'p', 9)"
            )
            conexion.execute(_migracion().read_text(encoding="utf-8"))
            assert _siguiente(conexion, "TR") == "TR-042"
            assert _siguiente(conexion, "INS") == "INS-013"
            assert _siguiente(conexion, "CANC") == "CANC-001"
            # Ningun codigo existente cambio.
            assert {
                r[0] for r in conexion.execute("select codigo from rma.tipo_reparacion")
            } == {"TR-OTROS", "TR-OFF", "TR-041", "TR-9"}
            # Repetir la migracion no retrocede las secuencias.
            conexion.execute(_migracion().read_text(encoding="utf-8"))
            assert _siguiente(conexion, "TR") == "TR-043"
    finally:
        borrar_base(admin, urlsplit(url).path.lstrip("/"))


def test_la_migracion_se_detiene_si_hay_codigos_que_solo_difieren_en_mayusculas():
    admin = _admin_url()
    url = _base_anterior(admin)
    try:
        with psycopg.connect(url, autocommit=True) as conexion:
            conexion.execute(
                "insert into rma.tipo_reparacion (codigo, nombre, precio, puntaje, garantia_dias) values"
                " ('TR-050', 'a', 1, 1, 1), ('tr-050', 'b', 1, 1, 1)"
            )
            with pytest.raises(psycopg.errors.UniqueViolation) as error:
                conexion.execute(_migracion().read_text(encoding="utf-8"))
            assert "TR-050, tr-050" in str(error.value)
            # No corrigio nada por su cuenta.
            assert conexion.execute(
                "select count(*) from rma.tipo_reparacion where upper(codigo) = 'TR-050'"
            ).fetchone()[0] == 2
    finally:
        borrar_base(admin, urlsplit(url).path.lstrip("/"))


# --- La API -------------------------------------------------------------------


@pytest.fixture
def cliente(api):
    app, cliente = api
    contexto = app.state.contexto
    unidad = contexto.unidad_de_trabajo
    app.state.contexto = replace(
        contexto,
        configuracion=PostgresConfiguracionRepository(unidad),
        catalogos=PostgresCatalogosRepository(unidad),
        operativa=PostgresConfiguracionOperativa(unidad),
        compras=PostgresComprasRepository(unidad),
    )
    return cliente


def _tipo(**cambios):
    return {
        "usuario_id": f.ADMINISTRADOR,
        "nombre": "Cambio de pantalla",
        "precio": "50000",
        "puntaje": 5,
        "garantia_dias": 90,
        **cambios,
    }


def test_alta_de_tipo_sin_codigo_lo_genera_y_el_informado_se_respeta(cliente, base):
    generado = f.ok(cliente.post("/api/admin/repair-types", json=_tipo()))
    assert generado["id"] == "TR-003"
    # Un cliente anterior que manda el codigo: se respeta.
    informado = f.ok(
        cliente.post("/api/admin/repair-types", json=_tipo(codigo="TR-MANUAL"))
    )
    assert informado["id"] == "TR-MANUAL"
    # Duplicado sin distinguir mayusculas: 409, como antes de CFG-01.
    assert "Ya existe" in f.conflicto(
        cliente.post("/api/admin/repair-types", json=_tipo(codigo="tr-manual"))
    )
    assert "reservado" in f.conflicto(
        cliente.post("/api/admin/repair-types", json=_tipo(codigo="tr-otros"))
    )
    # La auditoria usa el codigo generado.
    assert ("TR-003", "nombre") in {
        (r[0], r[1])
        for r in _sql(
            base,
            "select clave, campo from rma.cambio_configuracion where entidad = 'TIPO_REPARACION'",
        )
    }


def test_un_rechazo_por_permiso_no_consume_codigos(cliente):
    # El servicio valida el permiso antes de reservar el codigo.
    f.conflicto(
        cliente.post(
            "/api/admin/repair-types", json=_tipo(usuario_id=f.RECEPCION)
        )
    )
    assert f.ok(cliente.post("/api/admin/repair-types", json=_tipo()))["id"] == "TR-003"


def test_alta_de_motivos_e_insumos_sin_codigo(cliente):
    motivo = f.ok(
        cliente.post(
            "/api/admin/reasons",
            json={"usuario_id": f.ADMINISTRADOR, "tipo": "CANCELACION", "nombre": "Sin repuesto"},
        )
    )
    assert motivo["codigo"] == "CANC-001"
    interrupcion = f.ok(
        cliente.post(
            "/api/admin/reasons",
            json={"usuario_id": f.ADMINISTRADOR, "tipo": "INTERRUPCION", "nombre": "Falta luz"},
        )
    )
    assert interrupcion["codigo"] == "INT-001"
    # Codigo informado (cliente anterior): en mayusculas, y el duplicado es 409.
    informado = f.ok(
        cliente.post(
            "/api/admin/reasons",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "tipo": "CANCELACION",
                "nombre": "Precio",
                "codigo": "canc-precio",
            },
        )
    )
    assert informado["codigo"] == "CANC-PRECIO"
    assert "Ya existe" in f.conflicto(
        cliente.post(
            "/api/admin/reasons",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "tipo": "CANCELACION",
                "nombre": "Precio",
                "codigo": "CANC-PRECIO",
            },
        )
    )
    assert "no es valido" in f.conflicto(
        cliente.post(
            "/api/admin/reasons",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "tipo": "CANCELACION",
                "nombre": "Precio",
                "codigo": "con espacios",
            },
        )
    )

    # QA A, M3: un nombre en blanco se informa como tal, no como codigo.
    assert "nombre" in f.conflicto(
        cliente.post(
            "/api/admin/reasons",
            json={"usuario_id": f.ADMINISTRADOR, "tipo": "CANCELACION", "nombre": "   "},
        )
    )

    insumo = f.ok(
        cliente.post(
            "/api/admin/supplies",
            json={"usuario_id": f.ADMINISTRADOR, "nombre": "Pantalla A54", "unidad": "unidad"},
        )
    )
    assert insumo["id"].startswith("INS-") and insumo["codigo"] == insumo["id"]
    clave = insumo["id"]
    # La edicion no necesita el codigo (D4) y no lo cambia.
    editado = f.ok(
        cliente.put(
            f"/api/admin/supplies/{clave}",
            json={"usuario_id": f.ADMINISTRADOR, "nombre": "Pantalla Samsung A54", "unidad": "unidad"},
        )
    )
    assert editado["codigo"] == clave
    # Cliente anterior: clave y codigo informados; duplicados sin distinguir
    # mayusculas, 409.
    f.ok(
        cliente.post(
            "/api/admin/supplies",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "clave": "INS-500",
                "codigo": "FLEX-A54",
                "nombre": "Flex",
            },
        )
    )
    assert "Ya existe" in f.conflicto(
        cliente.post(
            "/api/admin/supplies",
            json={"usuario_id": f.ADMINISTRADOR, "clave": "ins-500", "nombre": "Otro"},
        )
    )
    assert "codigo" in f.conflicto(
        cliente.post(
            "/api/admin/supplies",
            json={"usuario_id": f.ADMINISTRADOR, "codigo": "flex-a54", "nombre": "Otro"},
        )
    )


def test_altas_concurrentes_por_la_api_reciben_codigos_distintos(cliente):
    def alta():
        respuesta = cliente.post("/api/admin/repair-types", json=_tipo())
        assert respuesta.status_code == 200, respuesta.text
        return respuesta.json()["id"]

    resultados, errores = _en_paralelo(*[alta] * 4)
    assert errores == []
    assert len(set(resultados)) == 4


def test_choque_en_la_base_es_un_conflicto_no_un_fallo(cliente, armar):
    # Otro proceso confirma el mismo codigo despues del control del caso de
    # uso: la base rechaza el alta (ON CONFLICT) y el repositorio lo informa
    # como CodigoExistenteError, que la API responde 409 (antes, 500).
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.domain.models import TipoReparacion
    from app.repositories import CodigoExistenteError

    _, unidad = armar()
    repositorio = PostgresConfiguracionRepository(unidad)
    tipo = TipoReparacion(
        id="tr-001", nombre="x", precio=Decimal(1), puntaje=1, garantia_dias=1
    )
    with pytest.raises(CodigoExistenteError):
        with unidad.transaccion():
            repositorio.guardar_tipo_reparacion(tipo, nuevo=True, cambios=[])
    assert datetime.now(UTC)  # la transaccion se revirtio sin dejar nada

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.errores import registrar_manejadores_de_error

    app = FastAPI()
    registrar_manejadores_de_error(app)

    @app.get("/choque")
    def _choque():
        raise CodigoExistenteError("Ya existe un Tipo de Reparacion TR-001.")

    respuesta = TestClient(app).get("/choque")
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["codigo"] == "PRECONDICION_INVALIDA"


def test_proveedor_y_pregunta_usan_el_generador(cliente, base):
    proveedor = f.ok(
        cliente.post(
            "/api/admin/suppliers",
            json={"usuario_id": f.ADMINISTRADOR, "nombre": "Repuestos SA"},
        )
    )
    assert proveedor["id"] == "PRV-0001"
    _sql(
        base,
        "insert into rma.proveedor (codigo, nombre) values ('PRV-0002', 'cargado por fuera')"
        " returning id",
    )
    otro = f.ok(
        cliente.post(
            "/api/admin/suppliers",
            json={"usuario_id": f.ADMINISTRADOR, "nombre": "Otro SA"},
        )
    )
    assert otro["id"] == "PRV-0003"
