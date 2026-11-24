"""Importacion masiva de precios por modelo sobre PostgreSQL (DEC-AJ-13).

Migracion ``20261124000400_importacion_precios.sql``:

- aditiva: tabla ``importacion_precio`` (inmutable) y
  ``cambio_configuracion.importacion_id``, solo en los cambios de
  PRECIO_MODELO; ``historial_precio`` suma la columna al final;
- aplicar: todo o nada en una transaccion, con la importacion registrada y
  cada cambio de la auditoria con su identificador; con un error no se
  escribe nada; la validacion se repite en el servidor con los precios
  del momento; la clave de idempotencia evita aplicarla dos veces;
- la plantilla descargada se vuelve a importar sin cambios.
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
OTRO = "TR-901"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    for codigo, nombre in ((TIPO, "Cambio de modulo"), (OTRO, "Bateria")):
        f.ok(
            cliente.post(
                "/api/admin/repair-types",
                json={
                    "usuario_id": f.ADMINISTRADOR,
                    "codigo": codigo,
                    "nombre": nombre,
                    "precio": "1",
                    "puntaje": 5,
                    "precio_por_modelo": True,
                },
            )
        )
    f.ok(
        cliente.put(
            f"/api/admin/repair-types/{TIPO}/model-prices",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "precios": [{"modelo_equipo_id": "MOD-0001", "precio": "100"}],
            },
        )
    )
    return cliente


def _enviar(cliente, ruta, texto, *, usuario=f.ADMINISTRADOR, clave=None):
    cabeceras = {"Content-Type": "text/csv"}
    if clave:
        cabeceras["Idempotency-Key"] = clave
    return cliente.post(
        f"/api/admin/model-prices/{ruta}",
        params={"usuario_id": usuario, "nombre": "lista.csv"},
        content=texto.encode(),
        headers=cabeceras,
    )


def _previa(cliente, texto, **datos):
    return _enviar(cliente, "import/preview", texto, **datos)


def _aplicar(cliente, texto, **datos):
    return _enviar(cliente, "import", texto, **datos)


def _precios(base):
    return _sql(
        base,
        """
        select t.codigo, m.codigo, p.precio from rma.precio_tipo_modelo p
          join rma.tipo_reparacion t on t.id = p.tipo_reparacion_id
          join rma.modelo_equipo m on m.id = p.modelo_equipo_id
         where p.activo and t.codigo in ('TR-900', 'TR-901')
         order by 1, 2
        """,
    )


LISTA = (
    f"Modelo;Nombre del modelo;{TIPO} · Cambio de modulo;{OTRO}\n"
    "MOD-0001;iPhone 8;250.000;80.000,50\n"
    "MOD-0002;iPhone 8 Plus;;90000\n"
    "MOD-0003;iPhone 11;300000;\n"
)


def test_la_migracion_es_aditiva(base):
    assert _sql(
        base,
        """
        select is_nullable from information_schema.columns
         where table_schema = 'rma' and table_name = 'cambio_configuracion'
           and column_name = 'importacion_id'
        """,
    ) == [("YES",)]
    assert _sql(
        base,
        "select count(*) from rma.cambio_configuracion "
        "where importacion_id is not null",
    ) == [(0,)]
    columnas = [
        c
        for (c,) in _sql(
            base,
            """
            select column_name from information_schema.columns
             where table_schema = 'rma' and table_name = 'historial_precio'
             order by ordinal_position
            """,
        )
    ]
    assert columnas == [
        "secuencia",
        "tipo_reparacion",
        "precio_anterior",
        "precio_nuevo",
        "usuario_id",
        "registrado_en",
        "modelo_equipo",
        "importacion_id",
    ]
    assert _sql(
        base,
        """
        select has_table_privilege('rma_backend', 'rma.importacion_precio',
                                   'INSERT'),
               has_table_privilege('rma_backend', 'rma.importacion_precio',
                                   'UPDATE'),
               has_table_privilege('rma_backend', 'rma.importacion_precio',
                                   'DELETE')
        """,
    ) == [(True, False, False)]
    # Solo los cambios de precio por modelo llevan importacion.
    with pytest.raises(psycopg.errors.CheckViolation):
        _ejecutar(
            base,
            """
            insert into rma.importacion_precio (id, usuario_id,
                registrado_en, formato, precios_nuevos,
                precios_actualizados, precios_sin_cambio)
            select '00000000-0000-0000-0000-000000000001', u.id, now(),
                   'CSV', 1, 0, 0
              from rma.usuario u where u.codigo = 'ADMIN-001';
            insert into rma.cambio_configuracion (entidad, clave, campo,
                valor_nuevo, usuario_id, registrado_en, importacion_id)
            select 'TIPO_REPARACION', 'TR-001', 'precio', '1', u.id, now(),
                   '00000000-0000-0000-0000-000000000001'
              from rma.usuario u where u.codigo = 'ADMIN-001'
            """,
        )


def test_aplica_todo_con_la_auditoria_agrupada(admin, base):
    vista = f.ok(_previa(admin, LISTA))
    assert vista["editable"] is True
    assert vista["errores"] == []
    assert vista["resumen"]["nuevos"] == 3
    assert vista["resumen"]["actualizados"] == 1
    assert [a["celda"] for a in vista["avisos"]] == ["C2"]
    # La vista previa no escribe nada.
    assert _precios(base) == [(TIPO, "MOD-0001", Decimal("100.00"))]

    resultado = f.ok(_aplicar(admin, LISTA))
    importacion = resultado["importacion"]
    assert resultado["cambios_registrados"] == 4
    assert (importacion["nuevos"], importacion["actualizados"]) == (3, 1)
    assert importacion["formato"] == "CSV"
    assert importacion["nombre_archivo"] == "lista.csv"
    assert _precios(base) == [
        (TIPO, "MOD-0001", Decimal("250000.00")),
        (TIPO, "MOD-0003", Decimal("300000.00")),
        (OTRO, "MOD-0001", Decimal("80000.50")),
        (OTRO, "MOD-0002", Decimal("90000.00")),
    ]
    assert _sql(
        base,
        """
        select i.id::text, u.codigo, i.formato, i.nombre_archivo,
               i.precios_nuevos, i.precios_actualizados,
               i.precios_sin_cambio
          from rma.importacion_precio i join rma.usuario u
            on u.id = i.usuario_id
        """,
    ) == [(importacion["id"], f.ADMINISTRADOR, "CSV", "lista.csv", 3, 1, 0)]
    # Un identificador comun en la auditoria y en el historial de precios.
    assert _sql(
        base,
        """
        select clave, valor_anterior, valor_nuevo
          from rma.cambio_configuracion
         where importacion_id = %s order by secuencia
        """,
        (importacion["id"],),
    ) == [
        (f"{TIPO}/MOD-0001", "100.00", "250000.00"),
        (f"{OTRO}/MOD-0001", None, "80000.50"),
        (f"{OTRO}/MOD-0002", None, "90000.00"),
        (f"{TIPO}/MOD-0003", None, "300000.00"),
    ]
    historial = _sql(
        base,
        """
        select modelo_equipo, precio_nuevo, importacion_id::text
          from rma.historial_precio where tipo_reparacion = %s
         order by secuencia
        """,
        (TIPO,),
    )
    assert historial[-2:] == [
        ("MOD-0001", "250000.00", importacion["id"]),
        ("MOD-0003", "300000.00", importacion["id"]),
    ]
    # La edicion individual no lleva importacion.
    assert historial[1] == ("MOD-0001", "100.00", None)
    cambios = f.ok(
        admin.get(
            "/api/admin/config-changes", params={"entidad": "PRECIO_MODELO"}
        )
    )
    assert {c["importacion_id"] for c in cambios} == {None, importacion["id"]}

    # Repetirla no cambia nada: se rechaza y no registra otra importacion.
    assert "no hay cambios" in f.conflicto(_aplicar(admin, LISTA))
    assert _sql(base, "select count(*) from rma.importacion_precio") == [(1,)]


def test_con_un_error_no_se_aplica_nada(admin, base):
    antes = _sql(base, "select count(*) from rma.cambio_configuracion")
    con_error = LISTA + "MOD-0004;iPhone 11 Pro;80,000;\n"
    vista = f.ok(_previa(admin, con_error))
    assert [e["celda"] for e in vista["errores"]] == ["C5"]
    assert vista["aplicable"] is False
    mensaje = f.conflicto(_aplicar(admin, con_error))
    assert "1 error(es)" in mensaje and "C5" in mensaje
    assert _precios(base) == [(TIPO, "MOD-0001", Decimal("100.00"))]
    assert _sql(base, "select count(*) from rma.cambio_configuracion") == antes
    assert _sql(base, "select count(*) from rma.importacion_precio") == [(0,)]


def test_otra_marca_es_un_error_de_la_fila(admin, base):
    f.ok(
        admin.post(
            "/api/admin/device-models",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "marca": "Samsung",
                "modelo": "Galaxy S24",
            },
        )
    )
    vista = f.ok(_previa(admin, f"Modelo;{TIPO}\nMOD-0037;1000\n"))
    assert [e["celda"] for e in vista["errores"]] == ["A2"]
    assert "marca Apple" in vista["errores"][0]["mensaje"]
    # La plantilla trae solo los modelos Apple.
    plantilla_csv = admin.get(
        "/api/admin/model-prices/template", params={"formato": "csv"}
    )
    assert b"MOD-0037" not in plantilla_csv.content


def test_el_servidor_vuelve_a_validar_con_los_precios_del_momento(admin):
    texto = f"Modelo;{OTRO}\nMOD-0005;70000\n"
    vista = f.ok(_previa(admin, texto))
    assert vista["cambios"][0]["estado"] == "NUEVO"
    # Entre la vista previa y aplicar, alguien carga el mismo precio.
    f.ok(
        admin.put(
            f"/api/admin/repair-types/{OTRO}/model-prices",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "precios": [
                    {"modelo_equipo_id": "MOD-0005", "precio": "70000"}
                ],
            },
        )
    )
    assert "no hay cambios" in f.conflicto(_aplicar(admin, texto))


def test_permiso_y_clave_de_idempotencia(admin, base):
    respuesta = _aplicar(admin, LISTA, usuario=f.COORDINADOR)
    assert "requiere" in f.conflicto(respuesta)
    primera = f.ok(_aplicar(admin, LISTA, clave="imp-1"))
    repetida = f.ok(_aplicar(admin, LISTA, clave="imp-1"))
    assert repetida == primera
    assert _sql(base, "select count(*) from rma.importacion_precio") == [(1,)]


def test_la_plantilla_se_vuelve_a_importar_sin_cambios(admin):
    for formato, tipo in (("xlsx", XLSX), ("csv", "text/csv")):
        archivo = admin.get(
            "/api/admin/model-prices/template", params={"formato": formato}
        )
        assert archivo.status_code == 200, archivo.text
        vista = f.ok(
            admin.post(
                "/api/admin/model-prices/import/preview",
                params={"usuario_id": f.ADMINISTRADOR},
                content=archivo.content,
                headers={"Content-Type": tipo},
            )
        )
        assert vista["errores"] == [], formato
        assert vista["cambios"] == []
        assert vista["resumen"]["sin_cambio"] == 1
        assert vista["resumen"]["tipos"] == 2
        assert vista["resumen"]["modelos"] == 36
