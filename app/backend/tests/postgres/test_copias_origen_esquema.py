# ruff: noqa: E501  (SQL)
"""Bloque C, entrega 1: esquema de las copias de origenes externos.

``rma.sincronizacion_origen`` (registro de intentos y reserva) y
``rma.catalogo_producto`` (copia del catalogo de Ventas), migracion
``20261117000100_copias_origen_externo.sql``. Diseño en
``docs/persistencia-catalogos.md``.

Una base propia por modulo (las filas de estas tablas no se borran) y un rol
de login miembro de ``rma_backend``, como el de Supabase.
"""

import os
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest

psycopg = pytest.importorskip("psycopg")

from tests.postgres.base_local import (  # noqa: E402
    VARIABLE,
    archivos_sql,
    borrar_base,
    crear_base,
    url_admin_local,
)

pytestmark = pytest.mark.postgres

MIGRACION = "20261117000100_copias_origen_externo.sql"
ROL = "rma_api_prueba"
COPIA = "CATALOGO_VENTAS"


def _admin() -> str:
    url = os.environ.get(VARIABLE)
    if not url:
        pytest.skip(f"{VARIABLE} no esta definida: sin PostgreSQL local.")
    return url_admin_local(url)


def _como_rol(url: str) -> str:
    partes = urlsplit(url)
    return urlunsplit(
        partes._replace(netloc=f"{ROL}@{partes.hostname}:{partes.port}")
    )


@pytest.fixture(scope="module")
def base():
    url_admin = _admin()
    url = crear_base(url_admin)
    with psycopg.connect(url, autocommit=True) as admin:
        if not admin.execute(
            "select 1 from pg_roles where rolname = %s", (ROL,)
        ).fetchone():
            admin.execute(
                f"create role {ROL} login inherit in role rma_backend"
            )
    try:
        yield url
    finally:
        borrar_base(url_admin, urlsplit(url).path.lstrip("/"))


@pytest.fixture
def backend(base):
    """Conexion como el usuario de la API (miembro de rma_backend)."""
    with psycopg.connect(_como_rol(base), autocommit=True) as conexion:
        yield conexion


@pytest.fixture
def admin(base):
    with psycopg.connect(base, autocommit=True) as conexion:
        yield conexion


@pytest.fixture
def usuario(admin) -> uuid.UUID:
    return admin.execute(
        "select id from rma.usuario order by codigo limit 1"
    ).fetchone()[0]


def _sinc_id() -> str:
    return f"SINC-{uuid.uuid4().hex[:12]}"


def _cerrar_en_curso(admin) -> None:
    """Deja la copia sin reserva vigente (cada prueba empieza limpia)."""
    admin.execute(
        "update rma.sincronizacion_origen set resultado = 'FALLIDA',"
        " mensaje = 'cierre de la prueba' where resultado = 'EN_CURSO'"
    )


@pytest.fixture(autouse=True)
def _sin_reservas(admin):
    _cerrar_en_curso(admin)
    yield
    _cerrar_en_curso(admin)


def _reservar(conexion, usuario, *, duracion="10 minutes", copia=COPIA):
    return conexion.execute(
        "select id, resultado, iniciada_en, vence_en from rma.reservar_sincronizacion"
        "(%s, %s, %s, %s, %s, %s::interval)",
        (_sinc_id(), copia, usuario, "archivo de prueba", "", duracion),
    ).fetchone()


def _producto(conexion, tp_id: str, sinc_id: str, **cambios) -> None:
    datos = {
        "descripcion": f"iPhone de prueba {tp_id}",
        "seleccionable": True,
        "motivo_no_seleccionable": None,
        "vigente": True,
        "motivo_baja": None,
    } | cambios
    conexion.execute(
        """
        insert into rma.catalogo_producto (tipo_producto_id, descripcion,
          seleccionable, motivo_no_seleccionable, vigente, motivo_baja,
          valores_origen, primera_sincronizacion, ultima_sincronizacion,
          sincronizacion_id)
        values (%(tp)s, %(descripcion)s, %(seleccionable)s,
          %(motivo_no_seleccionable)s, %(vigente)s, %(motivo_baja)s,
          '{"tp_gb": "128gb"}', now(), now(), %(sinc)s)
        on conflict (tipo_producto_id) do update set
          descripcion = excluded.descripcion,
          vigente = excluded.vigente,
          motivo_baja = excluded.motivo_baja,
          ultima_sincronizacion = excluded.ultima_sincronizacion,
          sincronizacion_id = excluded.sincronizacion_id
        """,
        datos | {"tp": tp_id, "sinc": sinc_id},
    )


# --- Estructura y permisos -------------------------------------------------


def test_tablas_indices_y_funcion(admin):
    tablas = {
        t
        for (t,) in admin.execute(
            "select table_name from information_schema.tables"
            " where table_schema = 'rma' and table_name in"
            " ('sincronizacion_origen', 'catalogo_producto')"
        )
    }
    assert tablas == {"sincronizacion_origen", "catalogo_producto"}
    indice = admin.execute(
        "select indexdef from pg_indexes where schemaname = 'rma'"
        " and indexname = 'sincronizacion_origen_en_curso'"
    ).fetchone()[0]
    assert "UNIQUE" in indice and "(copia)" in indice
    assert "WHERE (resultado = 'EN_CURSO'::text)" in indice


def test_permisos_minimos(admin):
    def priv(tabla, tipo):
        return admin.execute(
            "select has_table_privilege('rma_backend', %s, %s)", (tabla, tipo)
        ).fetchone()[0]

    def priv_col(tabla, columna):
        return admin.execute(
            "select has_column_privilege('rma_backend', %s, %s, 'UPDATE')",
            (tabla, columna),
        ).fetchone()[0]

    for tabla in ("rma.sincronizacion_origen", "rma.catalogo_producto"):
        assert priv(tabla, "SELECT") and priv(tabla, "INSERT")
        assert not priv(tabla, "DELETE")
        assert not priv(tabla, "TRUNCATE")
        for rol in ("anon", "authenticated", "service_role"):
            assert not admin.execute(
                "select has_table_privilege(%s, %s, 'SELECT')", (rol, tabla)
            ).fetchone()[0]
    # Del intento, solo su final; la reserva no se extiende ni se reescribe.
    for columna in ("resultado", "finalizada_en", "mensaje", "contadores"):
        assert priv_col("rma.sincronizacion_origen", columna)
    for columna in (
        "id",
        "copia",
        "usuario_id",
        "origen",
        "iniciada_en",
        "vence_en",
    ):
        assert not priv_col("rma.sincronizacion_origen", columna)
    # De la copia, todo menos su identidad y su primera sincronizacion.
    for columna in ("tipo_producto_id", "primera_sincronizacion", "creado_en"):
        assert not priv_col("rma.catalogo_producto", columna)
    assert priv_col("rma.catalogo_producto", "vigente")
    funcion = (
        "rma.reservar_sincronizacion(text, text, uuid, text, text, interval)"
    )
    assert admin.execute(
        "select has_function_privilege('rma_backend', %s, 'EXECUTE')",
        (funcion,),
    ).fetchone()[0]
    for rol in ("anon", "authenticated"):
        assert not admin.execute(
            "select has_function_privilege(%s, %s, 'EXECUTE')", (rol, funcion)
        ).fetchone()[0]


def test_el_backend_no_borra_ni_trunca(backend, usuario):
    sinc = _reservar(backend, usuario)[0]
    _producto(backend, "TP-NOBORRA", sinc)
    for sentencia in (
        "delete from rma.catalogo_producto",
        "delete from rma.sincronizacion_origen",
        "truncate rma.catalogo_producto",
        "update rma.sincronizacion_origen set vence_en = now() + interval '1 day'",
        "update rma.catalogo_producto set primera_sincronizacion = now()",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            backend.execute(sentencia)


def test_ni_el_dueno_borra(admin, usuario):
    sinc = _reservar(admin, usuario)[0]
    _producto(admin, "TP-DUENO", sinc)
    for tabla in ("catalogo_producto", "sincronizacion_origen"):
        with pytest.raises(psycopg.errors.RestrictViolation):
            admin.execute(f"delete from rma.{tabla}")


# --- Reserva ---------------------------------------------------------------


def test_reserva_con_la_hora_de_la_base(backend, usuario):
    sinc, resultado, iniciada, vence = _reservar(backend, usuario)
    assert resultado == "EN_CURSO"
    ahora = backend.execute("select now()").fetchone()[0]
    assert abs((iniciada - ahora).total_seconds()) < 5
    assert round((vence - iniciada).total_seconds()) == 600


def test_una_sola_sincronizacion_en_curso_por_copia(backend, usuario):
    _reservar(backend, usuario)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _reservar(backend, usuario)


def test_dos_instancias_a_la_vez(base, usuario):
    """Dos conexiones reservan en paralelo: una gana, la otra espera el
    indice unico y falla cuando la primera confirma."""
    resultados: dict[str, object] = {}
    listo = threading.Event()

    with psycopg.connect(_como_rol(base)) as a:
        _reservar(a, usuario)  # dentro de una transaccion abierta

        def segunda():
            with psycopg.connect(_como_rol(base), autocommit=True) as b:
                listo.set()
                try:
                    _reservar(b, usuario)
                    resultados["b"] = "reservo"
                except psycopg.errors.UniqueViolation:
                    resultados["b"] = "rechazada"

        hilo = threading.Thread(target=segunda)
        hilo.start()
        listo.wait(5)
        time.sleep(0.5)
        assert hilo.is_alive()  # espera a que la primera confirme
        a.commit()
        hilo.join(10)
    assert resultados == {"b": "rechazada"}


def test_la_reserva_vencida_se_interrumpe_y_deja_lugar(
    admin, backend, usuario
):
    vencida = _sinc_id()
    admin.execute(
        "insert into rma.sincronizacion_origen (id, copia, usuario_id, origen,"
        " iniciada_en, vence_en) values (%s, %s, %s, 'instancia caida',"
        " now() - interval '1 hour', now() - interval '50 minutes')",
        (vencida, COPIA, usuario),
    )
    nueva, resultado, *_ = _reservar(backend, usuario)
    assert resultado == "EN_CURSO"
    anterior = admin.execute(
        "select resultado, finalizada_en is not null, mensaje"
        " from rma.sincronizacion_origen where id = %s",
        (vencida,),
    ).fetchone()
    assert anterior[0] == "INTERRUMPIDA" and anterior[1]
    assert "venció" in anterior[2]


def test_una_reserva_vigente_no_se_interrumpe(backend, usuario):
    sinc = _reservar(backend, usuario)[0]
    with pytest.raises(psycopg.errors.RestrictViolation):
        backend.execute(
            "update rma.sincronizacion_origen set resultado = 'INTERRUMPIDA'"
            " where id = %s",
            (sinc,),
        )


def test_duracion_de_la_reserva_acotada(backend, usuario):
    for duracion in ("0 seconds", "-1 minute", "2 hours"):
        with pytest.raises(psycopg.errors.CheckViolation):
            _reservar(backend, usuario, duracion=duracion)


def test_copia_desconocida_rechazada(backend, usuario):
    with pytest.raises(psycopg.errors.CheckViolation):
        _reservar(backend, usuario, copia="PRODUCTOS_RT")


# --- Ciclo del intento -----------------------------------------------------


def test_un_intento_nace_en_curso(backend, usuario):
    with pytest.raises(psycopg.errors.CheckViolation):
        backend.execute(
            "insert into rma.sincronizacion_origen (id, copia, usuario_id,"
            " origen, vence_en, resultado, finalizada_en) values"
            " (%s, %s, %s, 'x', now() + interval '1 minute', 'EXITOSA', now())",
            (_sinc_id(), COPIA, usuario),
        )


def test_finaliza_una_sola_vez(backend, usuario):
    sinc = _reservar(backend, usuario)[0]
    backend.execute(
        "update rma.sincronizacion_origen set resultado = 'EXITOSA',"
        " contadores = '{\"nuevos\": 3}' where id = %s",
        (sinc,),
    )
    fila = backend.execute(
        "select resultado, finalizada_en is not null, contadores"
        " from rma.sincronizacion_origen where id = %s",
        (sinc,),
    ).fetchone()
    assert fila == ("EXITOSA", True, {"nuevos": 3})
    for cambio in ("resultado = 'FALLIDA'", "mensaje = 'otro'"):
        with pytest.raises(psycopg.errors.RestrictViolation):
            backend.execute(
                f"update rma.sincronizacion_origen set {cambio} where id = %s",
                (sinc,),
            )


def test_contadores_y_formato(backend, usuario):
    with pytest.raises(psycopg.errors.CheckViolation):
        backend.execute(
            "select rma.reservar_sincronizacion(%s, %s, %s, 'x', '', '1 minute')",
            ("SINC-NOHEX", COPIA, usuario),
        )
    sinc = _reservar(backend, usuario)[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        backend.execute(
            "update rma.sincronizacion_origen set resultado = 'FALLIDA',"
            " contadores = '[1]' where id = %s",
            (sinc,),
        )


# --- Copia del catalogo ----------------------------------------------------


def test_la_copia_se_escribe_dentro_de_la_reserva(backend, usuario):
    sinc = _reservar(backend, usuario)[0]
    _producto(backend, "TP-1", sinc)
    _producto(backend, "TP-1", sinc, vigente=False, motivo_baja="NO_INFORMADO")
    fila = backend.execute(
        "select vigente, motivo_baja, sincronizacion_id"
        " from rma.catalogo_producto where tipo_producto_id = 'TP-1'"
    ).fetchone()
    assert fila == (False, "NO_INFORMADO", sinc)


def test_la_copia_no_se_escribe_fuera_de_una_reserva(backend, usuario):
    sinc = _reservar(backend, usuario)[0]
    backend.execute(
        "update rma.sincronizacion_origen set resultado = 'EXITOSA' where id = %s",
        (sinc,),
    )
    with pytest.raises(psycopg.errors.RestrictViolation):
        _producto(backend, "TP-FUERA", sinc)
    with pytest.raises(psycopg.errors.RestrictViolation):
        _producto(backend, "TP-FUERA", "SINC-000000000000")


def test_una_reserva_interrumpida_ya_no_aplica(admin, backend, usuario):
    """Instancia lenta: su reserva vencio y otra la interrumpio; su
    aplicacion tardia se rechaza."""
    lenta = _sinc_id()
    admin.execute(
        "insert into rma.sincronizacion_origen (id, copia, usuario_id, origen,"
        " iniciada_en, vence_en) values (%s, %s, %s, 'lenta',"
        " now() - interval '20 minutes', now() - interval '10 minutes')",
        (lenta, COPIA, usuario),
    )
    _reservar(backend, usuario)
    with pytest.raises(psycopg.errors.RestrictViolation):
        _producto(backend, "TP-TARDIO", lenta)


def test_aplicar_y_tomar_la_reserva_en_paralelo(admin, base, usuario):
    """La aplicacion de A (reserva vencida pero todavia aplicando) y la
    toma de B no se pisan: B espera, y como A termina EXITOSA, B no la
    interrumpe y reserva despues."""
    a_id = _sinc_id()
    admin.execute(
        "insert into rma.sincronizacion_origen (id, copia, usuario_id, origen,"
        " iniciada_en, vence_en) values (%s, %s, %s, 'a',"
        " now() - interval '20 minutes', now() - interval '1 second')",
        (a_id, COPIA, usuario),
    )
    resultados: dict[str, object] = {}
    with psycopg.connect(_como_rol(base)) as a:
        _producto(a, "TP-PARALELO", a_id)  # toma FOR SHARE del intento

        def toma():
            with psycopg.connect(_como_rol(base), autocommit=True) as b:
                resultados["b"] = _reservar(b, usuario)[1]

        hilo = threading.Thread(target=toma)
        hilo.start()
        time.sleep(0.5)
        assert hilo.is_alive()
        a.execute(
            "update rma.sincronizacion_origen set resultado = 'EXITOSA' where id = %s",
            (a_id,),
        )
        a.commit()
        hilo.join(10)
    assert resultados == {"b": "EN_CURSO"}
    assert admin.execute(
        "select resultado from rma.sincronizacion_origen where id = %s",
        (a_id,),
    ).fetchone() == ("EXITOSA",)


def test_identidad_y_primera_sincronizacion_no_cambian(
    admin, backend, usuario
):
    sinc = _reservar(backend, usuario)[0]
    _producto(backend, "TP-ID", sinc)
    with pytest.raises(psycopg.errors.RestrictViolation):
        admin.execute(
            "update rma.catalogo_producto set tipo_producto_id = 'TP-OTRO'"
            " where tipo_producto_id = 'TP-ID'"
        )


def test_coherencia_de_vigencia_y_seleccion(backend, usuario):
    sinc = _reservar(backend, usuario)[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        _producto(backend, "TP-V", sinc, vigente=False, motivo_baja=None)
    with pytest.raises(psycopg.errors.CheckViolation):
        _producto(backend, "TP-S", sinc, seleccionable=False)
    with pytest.raises(psycopg.errors.CheckViolation):
        _producto(backend, " TP-ESPACIO", sinc)


# --- Respaldo y restauracion ------------------------------------------------


def test_la_restauracion_en_modo_replica_carga_lo_finalizado(admin, usuario):
    """restaurar.sh carga los datos con session_replication_role = replica
    (sin triggers): intentos finalizados y su copia entran tal cual."""
    sinc = _sinc_id()
    with admin.transaction():
        admin.execute("set local session_replication_role = replica")
        admin.execute(
            "insert into rma.sincronizacion_origen (id, copia, usuario_id,"
            " origen, iniciada_en, vence_en, finalizada_en, resultado)"
            " values (%s, %s, %s, 'respaldo', now() - interval '2 days',"
            " now() - interval '2 days' + interval '10 minutes',"
            " now() - interval '2 days' + interval '1 minute', 'EXITOSA')",
            (sinc, COPIA, usuario),
        )
        _producto(admin, "TP-RESTAURADO", sinc)
    assert admin.execute(
        "select sincronizacion_id from rma.catalogo_producto"
        " where tipo_producto_id = 'TP-RESTAURADO'"
    ).fetchone() == (sinc,)
    # Ya restaurado, vuelve a ser inmutable.
    with pytest.raises(psycopg.errors.RestrictViolation):
        admin.execute(
            "update rma.sincronizacion_origen set mensaje = 'x' where id = %s",
            (sinc,),
        )


# --- La migracion sobre una base con datos ---------------------------------


def test_la_migracion_no_cambia_los_datos_existentes():
    """Base con las 37 migraciones anteriores y las cargas; la migracion
    nueva (dos veces) no cambia ninguna fila ni secuencia existente."""
    url_admin = _admin()
    todos = archivos_sql()
    nueva = next(a for a in todos if a.name == MIGRACION)
    url = crear_base(url_admin, [a for a in todos if a != nueva])
    huella = """
        select c.relname, md5(coalesce((xpath('/row/h/text()', query_to_xml(format(
          'select string_agg(t::text, ''|'' order by t::text) as h from rma.%I t', c.relname),
          false, true, '')))[1]::text, ''))
          from pg_class c join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'rma' and c.relkind = 'r' order by 1
    """
    secuencias = "select sequencename, last_value from pg_sequences where schemaname = 'rma' order by 1"
    try:
        with psycopg.connect(url, autocommit=True) as conexion:
            antes = conexion.execute(huella).fetchall()
            sec_antes = conexion.execute(secuencias).fetchall()
            assert len(antes) == 69
            for _ in range(2):  # idempotente
                conexion.execute(nueva.read_text(encoding="utf-8"))
            despues = dict(conexion.execute(huella).fetchall())
            assert {t: h for t, h in antes} == {
                t: despues[t] for t, _ in antes
            }
            assert set(despues) - {t for t, _ in antes} == {
                "sincronizacion_origen",
                "catalogo_producto",
            }
            assert conexion.execute(secuencias).fetchall() == sec_antes
            assert conexion.execute(
                "select count(*) from rma.verificar_integridad()"
            ).fetchone() == (0,)
    finally:
        borrar_base(url_admin, urlsplit(url).path.lstrip("/"))
