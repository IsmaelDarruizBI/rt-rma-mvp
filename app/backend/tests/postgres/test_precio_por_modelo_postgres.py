"""Precio por modelo y modelos administrables sobre PostgreSQL (DEC-AJ-12).

Migracion ``20261124000300_precio_por_modelo.sql``:

- aditiva: ``tipo_reparacion.precio_por_modelo`` (falso en los existentes),
  tabla ``precio_tipo_modelo`` (unica por par, sin borrado), la copia del
  trabajo en ``detalle_version`` y la secuencia del codigo MOD, que sigue
  al mayor existente;
- Configuracion: alta y edicion de modelos (MODELO_EQUIPO_GESTIONAR) y
  precios por modelo en bloque (PRECIOS_GESTIONAR), auditados, con el
  historial de precios por modelo;
- la copia del trabajo (nombre, modelo, origen, motivo y quien) se guarda
  y se relee igual, y un cambio del catalogo no toca las Ordenes.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.storage.postgres.configuracion import (  # noqa: E402
    PostgresConfiguracionRepository,
)
from app.storage.postgres.modelos_equipo import (  # noqa: E402
    PostgresModelosEquipoRepository,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _ejecutar, _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api

TIPO = "TR-900"
CON_PRECIO = "MOD-0001"
SIN_PRECIO = "MOD-0003"


@pytest.fixture
def admin(api):
    app, cliente = api
    contexto = app.state.contexto
    unidad = contexto.unidad_de_trabajo
    app.state.contexto = replace(
        contexto,
        configuracion=PostgresConfiguracionRepository(unidad),
        modelos_equipo=PostgresModelosEquipoRepository(unidad),
    )
    return cliente


# --- Migracion ---------------------------------------------------------------


def test_la_migracion_es_aditiva(base):
    assert _sql(
        base,
        "select count(*) from rma.tipo_reparacion where precio_por_modelo",
    ) == [(0,)]
    columnas = dict(
        _sql(
            base,
            """
            select column_name, is_nullable from information_schema.columns
             where table_schema = 'rma' and table_name = 'detalle_version'
               and column_name in ('nombre_trabajo', 'modelo_equipo_id',
                   'origen_precio', 'precio_motivo', 'precio_definido_por',
                   'precio_definido_en', 'solo_precio')
            """,
        )
    )
    assert columnas == {
        "nombre_trabajo": "YES",
        "modelo_equipo_id": "YES",
        "origen_precio": "YES",
        "precio_motivo": "YES",
        "precio_definido_por": "YES",
        "precio_definido_en": "YES",
        "solo_precio": "NO",
    }
    (definicion,) = _sql(
        base,
        """
        select pg_get_constraintdef(oid) from pg_constraint
         where conname = 'detalle_version_origen_precio'
        """,
    )[0]
    for origen in (
        "CATALOGO",
        "CATALOGO_MODELO",
        "MANUAL",
        "OTROS",
        "PENDIENTE",
    ):
        assert f"'{origen}'" in definicion
    # El codigo MOD sigue al mayor existente (36 modelos de la carga
    # inicial).
    assert _sql(base, "select count(*) from rma.modelo_equipo") == [(36,)]
    assert _sql(base, "select rma.siguiente_codigo('MOD')") == [("MOD-0037",)]
    privilegios = _sql(
        base,
        """
        select has_table_privilege('rma_backend', 'rma.precio_tipo_modelo',
                                   'INSERT'),
               has_column_privilege('rma_backend', 'rma.precio_tipo_modelo',
                                    'precio', 'UPDATE'),
               has_table_privilege('rma_backend', 'rma.precio_tipo_modelo',
                                   'DELETE'),
               has_column_privilege('rma_backend', 'rma.modelo_equipo',
                                    'marca', 'UPDATE')
        """,
    )
    assert privilegios == [(True, True, False, True)]
    # Unica por par y sin borrado.
    _ejecutar(
        base,
        """
        insert into rma.precio_tipo_modelo (tipo_reparacion_id,
            modelo_equipo_id, precio)
        select t.id, m.id, 100 from rma.tipo_reparacion t, rma.modelo_equipo m
         where t.codigo = 'TR-001' and m.codigo = 'MOD-0001'
        """,
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        _ejecutar(
            base,
            """
            insert into rma.precio_tipo_modelo (tipo_reparacion_id,
                modelo_equipo_id, precio)
            select t.id, m.id, 200
              from rma.tipo_reparacion t, rma.modelo_equipo m
             where t.codigo = 'TR-001' and m.codigo = 'MOD-0001'
            """,
        )
    with pytest.raises(psycopg.errors.RestrictViolation):
        _ejecutar(base, "delete from rma.precio_tipo_modelo")
    with pytest.raises(psycopg.errors.Error):
        _ejecutar(
            base,
            "update rma.modelo_equipo set codigo = 'MOD-9999' "
            "where codigo = 'MOD-0001'",
        )


# --- Modelos de equipo -------------------------------------------------------


def _modelo(**datos):
    return {
        "usuario_id": f.ADMINISTRADOR,
        "marca": "Apple",
        "modelo": "iPhone 18",
        **datos,
    }


def test_alta_y_edicion_de_modelos_con_auditoria(admin, base):
    alta = f.ok(admin.post("/api/admin/device-models", json=_modelo()))
    assert alta["id"] == "MOD-0037"
    assert alta["nombre"] == "Apple iPhone 18"
    seleccion = f.ok(admin.get("/api/catalogs/device-models"))
    assert "MOD-0037" in [m["id"] for m in seleccion]

    # Sin duplicados, tampoco con otras mayusculas o espacios.
    assert "Ya existe el modelo MOD-0037" in f.conflicto(
        admin.post(
            "/api/admin/device-models",
            json=_modelo(marca="apple", modelo=" iPhone  18 "),
        )
    )
    # Solo con MODELO_EQUIPO_GESTIONAR (Administracion por defecto).
    respuesta = admin.post(
        "/api/admin/device-models",
        json=_modelo(usuario_id=f.COORDINADOR, modelo="iPhone 19"),
    )
    assert respuesta.status_code in (403, 409), respuesta.text

    f.ok(
        admin.put(
            "/api/admin/device-models/MOD-0037",
            json=_modelo(variante="Pro", numeros_modelo=["A3001"]),
        )
    )
    f.ok(
        admin.put(
            "/api/admin/device-models/MOD-0037",
            json=_modelo(
                variante="Pro", numeros_modelo=["A3001"], activo=False
            ),
        )
    )
    seleccion = f.ok(admin.get("/api/catalogs/device-models"))
    assert "MOD-0037" not in [m["id"] for m in seleccion]
    todos = f.ok(admin.get("/api/admin/device-models"))
    assert todos["editable"] is True
    assert "MOD-0037" in [m["id"] for m in todos["modelos"]]

    cambios = f.ok(
        admin.get(
            "/api/admin/config-changes",
            params={"entidad": "MODELO_EQUIPO", "clave": "MOD-0037"},
        )
    )
    assert [
        (c["campo"], c["valor_anterior"], c["valor_nuevo"]) for c in cambios
    ] == [
        ("marca", None, "Apple"),
        ("modelo", None, "iPhone 18"),
        ("activo", None, "true"),
        ("variante", None, "Pro"),
        ("numeros_modelo", None, "A3001"),
        ("activo", "true", "false"),
    ]
    assert _sql(
        base,
        "select variante, numeros_modelo, activo from rma.modelo_equipo "
        "where codigo = 'MOD-0037'",
    ) == [("Pro", ["A3001"], False)]


# --- Precios por modelo ------------------------------------------------------


def _tipo_por_modelo(admin):
    return f.ok(
        admin.post(
            "/api/admin/repair-types",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "codigo": TIPO,
                "nombre": "Cambio de modulo",
                "precio": "1",
                "puntaje": 5,
                "precio_por_modelo": True,
            },
        )
    )


def _precios(admin, *pares, usuario=f.ADMINISTRADOR, tipo=TIPO):
    return admin.put(
        f"/api/admin/repair-types/{tipo}/model-prices",
        json={
            "usuario_id": usuario,
            "precios": [
                {"modelo_equipo_id": modelo, "precio": precio}
                for modelo, precio in pares
            ],
        },
    )


def test_precios_por_modelo_auditados_y_su_historial(admin, base):
    alta = _tipo_por_modelo(admin)
    assert alta["precio_por_modelo"] is True

    resultado = f.ok(
        _precios(admin, (CON_PRECIO, "50000"), (SIN_PRECIO, "60000.50"))
    )
    assert resultado["tipo"]["precios_modelo"] == {
        CON_PRECIO: "50000",
        SIN_PRECIO: "60000.5",
    }
    f.ok(_precios(admin, (CON_PRECIO, "55000"), (SIN_PRECIO, None)))
    (tipo,) = [
        t
        for t in f.ok(admin.get("/api/catalogs/repair-types"))
        if t["id"] == TIPO
    ]
    assert tipo["precios_modelo"] == {CON_PRECIO: "55000"}
    # El precio retirado queda inactivo, no se borra.
    assert _sql(
        base,
        """
        select m.codigo, p.precio, p.activo from rma.precio_tipo_modelo p
          join rma.modelo_equipo m on m.id = p.modelo_equipo_id
          join rma.tipo_reparacion t on t.id = p.tipo_reparacion_id
         where t.codigo = %s order by m.codigo
        """,
        (TIPO,),
    ) == [
        (CON_PRECIO, Decimal("55000"), True),
        (SIN_PRECIO, Decimal("60000.50"), False),
    ]
    assert _sql(
        base,
        """
        select modelo_equipo, precio_anterior, precio_nuevo
          from rma.historial_precio where tipo_reparacion = %s
         order by secuencia
        """,
        (TIPO,),
    ) == [
        (None, None, "1.00"),
        (CON_PRECIO, None, "50000.00"),
        (SIN_PRECIO, None, "60000.50"),
        (CON_PRECIO, "50000.00", "55000.00"),
        (SIN_PRECIO, "60000.50", None),
    ]
    cambios = f.ok(
        admin.get(
            "/api/admin/config-changes",
            params={
                "entidad": "PRECIO_MODELO",
                "clave": f"{TIPO}/{CON_PRECIO}",
            },
        )
    )
    assert [c["valor_nuevo"] for c in cambios] == ["50000.00", "55000.00"]

    # Sin cambios, repetidos, Otros o sin PRECIOS_GESTIONAR: nada se guarda.
    assert "no hay cambios" in f.conflicto(
        _precios(admin, (CON_PRECIO, "55000"))
    )
    assert "repetida" in f.conflicto(
        _precios(admin, (CON_PRECIO, "1"), (CON_PRECIO, "2"))
    )
    assert "Otros" in f.conflicto(
        _precios(admin, (CON_PRECIO, "1"), tipo="TR-OTROS")
    )
    assert "MOD-9999" in f.conflicto(
        _precios(admin, (CON_PRECIO, "1"), ("MOD-9999", "2"))
    )
    respuesta = _precios(admin, (CON_PRECIO, "1"), usuario=f.COORDINADOR)
    assert respuesta.status_code in (403, 409), respuesta.text
    assert _sql(
        base,
        "select count(*) from rma.cambio_configuracion "
        "where entidad = 'PRECIO_MODELO'",
    ) == [(4,)]


def _crear(admin, modelo):
    return f.ok(
        admin.post(
            "/api/orders",
            json={
                "usuario_id": f.RECEPCION,
                "cliente": {"nombre_apellido": "Ana", "telefono": "341-1"},
                "equipo": {
                    "modelo_tecnico_id": modelo,
                    "falla_reportada": "No enciende.",
                },
                "recepcion": {
                    "estado_fisico": "Sin golpes.",
                    "funcionalidades_verificadas": True,
                },
            },
        )
    )["id"]


def test_la_copia_del_trabajo_se_guarda_y_se_relee(admin, base):
    _tipo_por_modelo(admin)
    f.ok(_precios(admin, (CON_PRECIO, "50000")))
    orden_id = _crear(admin, SIN_PRECIO)
    orden = f.ok(
        admin.post(
            f"/api/orders/{orden_id}/details",
            json={"usuario_id": f.RECEPCION, "tipo_reparacion_id": TIPO},
        )
    )
    assert f.detalle(orden, "DET-001")["origen_precio"] == "PENDIENTE"
    f.conflicto(
        admin.post(
            f"/api/orders/{orden_id}/documents/intake-receipt",
            json={"usuario_id": f.RECEPCION},
        )
    )
    f.ok(
        admin.post(
            f"/api/orders/{orden_id}/details/DET-001/price",
            json={
                "usuario_id": f.COORDINADOR,
                "precio": "70000",
                "motivo": "Cotizado con el proveedor",
            },
        )
    )
    # Un cambio posterior del catalogo no toca la Orden.
    f.ok(_precios(admin, (SIN_PRECIO, "90000")))
    orden = f.ok(admin.get(f"/api/orders/{orden_id}"))
    detalle = f.detalle(orden, "DET-001")
    assert detalle["precio"] == "70000"
    assert detalle["origen_precio"] == "MANUAL"
    assert detalle["precio_motivo"] == "Cotizado con el proveedor"
    assert detalle["precio_definido_por"] == f.COORDINADOR
    assert detalle["modelo_equipo_id"] == SIN_PRECIO
    assert detalle["nombre_trabajo"] == "Cambio de modulo"
    assert detalle["solo_precio"] is True
    (anterior,) = detalle["definiciones_anteriores"]
    assert (anterior["origen_precio"], anterior["precio"]) == (
        "PENDIENTE",
        "0",
    )
    assert _sql(
        base,
        """
        select v.numero, v.origen_precio, v.precio, v.solo_precio,
               m.codigo, v.nombre_trabajo, u.codigo
          from rma.detalle_version v
          join rma.detalle d on d.id = v.detalle_id
          join rma.orden o on o.id = d.orden_id
          left join rma.modelo_equipo m on m.id = v.modelo_equipo_id
          left join rma.usuario u on u.id = v.precio_definido_por
         where o.codigo = %s order by v.numero
        """,
        (orden_id,),
    ) == [
        (
            1,
            "PENDIENTE",
            Decimal("0"),
            False,
            SIN_PRECIO,
            "Cambio de modulo",
            f.RECEPCION,
        ),
        (
            2,
            "MANUAL",
            Decimal("70000"),
            True,
            SIN_PRECIO,
            "Cambio de modulo",
            f.COORDINADOR,
        ),
    ]
    orden = f.ok(
        admin.post(
            f"/api/orders/{orden_id}/documents/intake-receipt",
            json={"usuario_id": f.RECEPCION},
        )
    )
    assert f.detalle(orden, "DET-001")["estado_autorizacion"] == "AUTORIZADO"
    # Un precio pendiente con importe no entra en la base.
    with pytest.raises(psycopg.errors.CheckViolation):
        _ejecutar(
            base,
            """
            insert into rma.detalle_version (detalle_id, numero,
                tipo_reparacion_id, precio, puntaje, garantia_dias,
                origen_precio, reemplaza_a)
            select v.detalle_id, 9, v.tipo_reparacion_id, 1, 1, 1,
                   'PENDIENTE', v.id
              from rma.detalle_version v where v.numero = 2 limit 1
            """,
        )
