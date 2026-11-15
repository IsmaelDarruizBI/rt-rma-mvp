"""Checklist de recepcion por tipo de equipo sobre PostgreSQL (DC12), con
``20261113001100_checklist_recepcion.sql`` y
``20261115000100_tipo_equipo_catalogo_ventas.sql``.

Decision aprobada de DC12: el Tipo de Equipo viene del catalogo de Ventas
de Gestion RT. RMA copia los tipos con el origen de solo lectura que ya
existe (aca, el adaptador CSV con un catalogo FICTICIO); Administracion no
los crea ni los edita, configura sus preguntas; Recepcion elige un tipo
vigente y responde lo que quiera; la Orden guarda la copia del tipo y de
las preguntas, y un cambio posterior del catalogo no la altera.

Que columna de Ventas es el tipo no esta decidido: estas pruebas fijan
``tp_gp`` solo para ejercitar el mecanismo (no es una eleccion funcional).
"""

from dataclasses import replace

import pytest

pytest.importorskip("psycopg_pool")

import psycopg  # noqa: E402

from app.integraciones.catalogo import ProveedorCatalogoArchivo  # noqa: E402
from app.storage.postgres.operativa import (  # noqa: E402
    PostgresConfiguracionOperativa,
)
from tests.fixtures import api_salidas as f  # noqa: E402
from tests.fixtures import catalogo_ventas as ventas  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _ejecutar, _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api

# Dos grupos ficticios dentro del filtro (IPHONE USADOS), mas los casos
# reales: generadores (no son equipos), eliminados y otra subcategoria.
GRUPO_A = "apple_usados"
GRUPO_B = "grupo_ficticio_b"


def _filas(*grupos: str) -> list[list]:
    filas = [ventas.GENERADOR, ventas.GENERADOR_CON_ID_CORTO]
    for numero, grupo in enumerate(grupos, start=12):
        filas.append(
            ventas.fila(str(numero), "Nada", "128gb", "black", grupo=grupo)
        )
    filas.append(
        ventas.fila(
            "8", "Plus", "64gb", "gold", grupo="eliminado_x", eliminado=True
        )
    )
    filas.append(
        ventas.fila(
            "12",
            "Nada",
            "128gb",
            "black",
            subcat="IPHONE NUEVOS",
            grupo="nuevos_x",
        )
    )
    return filas


@pytest.fixture
def entorno(api, tmp_path):
    """El cliente con la operativa sobre PostgreSQL y un catalogo de Ventas
    ficticio en CSV. ``fijar`` cambia el contexto (columna, origen)."""
    app, cliente = api
    original = app.state.contexto
    csv = tmp_path / "raw_TipoProducto.csv"
    ventas.escribir_csv(csv, _filas(GRUPO_A, GRUPO_B))

    def fijar(*, campo="tp_gp", ruta=csv):
        app.state.contexto = replace(
            original,
            operativa=PostgresConfiguracionOperativa(
                original.unidad_de_trabajo
            ),
            proveedor_catalogo=ProveedorCatalogoArchivo(
                ruta, marcas={"IPHONE": "Apple"}
            ),
            campo_tipo_equipo=campo,
        )

    fijar()
    return cliente, csv, fijar


def _admin(cliente, metodo, ruta, **cuerpo):
    return f.ok(
        getattr(cliente, metodo)(
            ruta, json={"usuario_id": f.ADMINISTRADOR, **cuerpo}
        )
    )


def _no_encontrado(respuesta) -> None:
    assert respuesta.status_code == 404, respuesta.text


def _sincronizar(cliente, usuario=f.ADMINISTRADOR):
    return cliente.post(
        "/api/admin/equipment-types/sync", json={"usuario_id": usuario}
    )


def test_sin_columna_definida_no_hay_tipos_ni_se_pide_checklist(entorno, base):
    cliente, _, fijar = entorno
    fijar(campo=None)
    assert "decisión de negocio pendiente" in f.conflicto(
        _sincronizar(cliente)
    )
    admin = f.ok(cliente.get("/api/admin/checklist"))
    assert admin["tipos"] == []
    assert admin["origen"]["definido"] is False
    assert admin["origen"]["sincronizable"] is False
    assert "RMA_TIPO_EQUIPO_CAMPO" in admin["origen"]["aviso"]
    # RMA no crea tipos propios: no hay alta ni edicion.
    assert cliente.post(
        "/api/admin/equipment-types",
        json={"usuario_id": f.ADMINISTRADOR, "nombre": "Celular"},
    ).status_code in (404, 405)
    orden = f.ok(cliente.get(f"/api/orders/{f.crear(cliente)}"))
    assert "Checklist de recepcion" not in orden["informacion_faltante"]
    assert orden["tipo_equipo"] is None


def test_tipos_desde_ventas_preguntas_y_checklist_con_copia(entorno, base):
    cliente, csv, _ = entorno
    # Solo Administracion actualiza la copia.
    f.conflicto(_sincronizar(cliente, f.RECEPCION))
    resultado = f.ok(_sincronizar(cliente))
    assert (resultado["nuevos"], resultado["vigentes"]) == (2, 2)
    assert resultado["campo"] == "tp_gp"
    admin = f.ok(cliente.get("/api/admin/checklist"))
    # Los identificadores son los de Ventas, tal cual; sin generadores,
    # eliminados ni otras subcategorias.
    assert [t["id"] for t in admin["tipos"]] == [GRUPO_A, GRUPO_B]
    assert all(t["campo_origen"] == "tp_gp" for t in admin["tipos"])
    assert admin["origen"]["ultima_sincronizacion"] is not None
    assert (GRUPO_A, "activo", None, "true") in _sql(
        base,
        """
        select clave, campo, valor_anterior, valor_nuevo
          from rma.cambio_configuracion where entidad = 'CHECKLIST'
        """,
    )
    # Repetir la sincronizacion no duplica ni audita de nuevo.
    repetida = f.ok(_sincronizar(cliente))
    assert (repetida["nuevos"], repetida["sin_cambios"]) == (0, 2)
    assert _sql(base, "select count(*) from rma.tipo_equipo") == [(2,)]

    # Preguntas por tipo externo, con orden de presentacion.
    f.conflicto(
        cliente.post(
            "/api/admin/checklist-questions",
            json={
                "usuario_id": f.RECEPCION,
                "tipo_equipo_id": GRUPO_A,
                "texto": "Carga",
                "opciones": ["Carga", "No carga"],
            },
        )
    )
    _no_encontrado(
        cliente.post(
            "/api/admin/checklist-questions",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "tipo_equipo_id": "INVENTADO",
                "texto": "Carga",
                "opciones": ["Carga", "No carga"],
            },
        )
    )
    carga = _admin(
        cliente,
        "post",
        "/api/admin/checklist-questions",
        tipo_equipo_id=GRUPO_A,
        texto="Carga",
        opciones=["Carga", "No carga"],
        orden=2,
    )
    _admin(
        cliente,
        "post",
        "/api/admin/checklist-questions",
        tipo_equipo_id=GRUPO_A,
        texto="Camara",
        opciones=["Funciona", "Falla"],
        orden=1,
    )
    catalogo = f.ok(cliente.get("/api/catalogs/checklist"))
    assert [p["texto"] for p in catalogo["preguntas"]] == ["Camara", "Carga"]

    orden_id = f.crear(cliente)
    ruta = f"/api/orders/{orden_id}/checklist"
    assert (
        "Checklist de recepcion"
        in f.ok(cliente.get(f"/api/orders/{orden_id}"))["informacion_faltante"]
    )
    # El backend valida el identificador recibido.
    _no_encontrado(
        cliente.post(
            ruta,
            json={"usuario_id": f.RECEPCION, "tipo_equipo_id": "INVENTADO"},
        )
    )
    assert "no es una opcion" in f.conflicto(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.RECEPCION,
                "tipo_equipo_id": GRUPO_A,
                "respuestas": [
                    {"pregunta_id": carga["id"], "respuesta": "Tal vez"}
                ],
            },
        )
    )
    orden = f.ok(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.RECEPCION,
                "tipo_equipo_id": GRUPO_A,
                "respuestas": [
                    {"pregunta_id": carga["id"], "no_realizada": True}
                ],
            },
        )
    )
    (registro,) = orden["checklists_recepcion"]
    assert registro["sin_registrar"] == ["Camara"]
    assert registro["respuestas"][0]["no_realizada"] is True
    assert orden["tipo_equipo"] == {"id": GRUPO_A, "descripcion": GRUPO_A}
    assert (
        "Verificaciones del checklist sin registrar (1)"
        in orden["informacion_faltante"]
    )

    # Corregir exige motivo y agrega una version.
    assert "motivo" in f.conflicto(
        cliente.post(
            ruta, json={"usuario_id": f.RECEPCION, "tipo_equipo_id": GRUPO_A}
        )
    )
    orden = f.ok(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.RECEPCION,
                "tipo_equipo_id": GRUPO_A,
                "respuestas": [
                    {"pregunta_id": carga["id"], "respuesta": "No carga"}
                ],
                "motivo": "Se pudo probar el cargador.",
            },
        )
    )
    assert len(orden["checklists_recepcion"]) == 2

    # Cambiar una pregunta (y su orden) queda auditado y no altera lo
    # registrado.
    _admin(
        cliente,
        "put",
        f"/api/admin/checklist-questions/{carga['id']}",
        tipo_equipo_id=GRUPO_A,
        texto="Carga por USB",
        opciones=["Si", "No"],
        orden=3,
    )
    auditoria = _sql(
        base,
        """
        select clave, campo, valor_anterior, valor_nuevo
          from rma.cambio_configuracion where entidad = 'CHECKLIST'
        """,
    )
    assert (
        f"{GRUPO_A}/{carga['id']}",
        "texto",
        "Carga",
        "Carga por USB",
    ) in auditoria
    assert (f"{GRUPO_A}/{carga['id']}", "orden", "2", "3") in auditoria

    # El catalogo de Ventas cambia: el tipo deja de venir. No se borra ni
    # cambia lo registrado; no se ofrece para checklists nuevos.
    ventas.escribir_csv(csv, _filas(GRUPO_B))
    baja = f.ok(_sincronizar(cliente))
    assert baja["dados_de_baja"] == 1
    releida = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert releida["checklists_recepcion"] == orden["checklists_recepcion"]
    assert (
        releida["checklists_recepcion"][1]["respuestas"][0]["texto"] == "Carga"
    )
    assert releida["tipo_equipo"] == {"id": GRUPO_A, "descripcion": GRUPO_A}
    assert [
        t["id"] for t in f.ok(cliente.get("/api/catalogs/checklist"))["tipos"]
    ] == [GRUPO_B]
    assert "no esta vigente" in f.conflicto(
        cliente.post(
            ruta,
            json={
                "usuario_id": f.RECEPCION,
                "tipo_equipo_id": GRUPO_A,
                "motivo": "Otra vez",
            },
        )
    )
    # Vuelve a venir: se reactiva el mismo, con sus preguntas.
    ventas.escribir_csv(csv, _filas(GRUPO_A, GRUPO_B))
    assert f.ok(_sincronizar(cliente))["reactivados"] == 1
    assert _sql(
        base,
        "select count(*) from rma.checklist_pregunta p join rma.tipo_equipo t "
        f"on t.id = p.tipo_equipo_id where t.codigo = '{GRUPO_A}'",
    ) == [(2,)]

    with pytest.raises(psycopg.Error):
        _ejecutar(base, "update rma.checklist_registro set motivo = 'x'")
    with pytest.raises(psycopg.Error):
        _ejecutar(
            base, f"delete from rma.tipo_equipo where codigo = '{GRUPO_B}'"
        )
    assert _sql(base, "select count(*) from rma.verificar_integridad()") == [
        (0,)
    ]


def test_origen_caido_o_ambiguo_no_cambia_la_copia(entorno, base, tmp_path):
    cliente, csv, fijar = entorno
    f.ok(_sincronizar(cliente))
    orden_id = f.crear(cliente)

    # El origen no responde: 503 y la copia queda como estaba; las Ordenes
    # se siguen consultando.
    fijar(ruta=tmp_path / "no_existe.csv")
    respuesta = _sincronizar(cliente)
    assert respuesta.status_code == 503
    assert len(f.ok(cliente.get("/api/admin/checklist"))["tipos"]) == 2
    f.ok(cliente.get(f"/api/orders/{orden_id}"))

    # Dos valores que solo difieren en mayusculas: no se adivina.
    ambiguo = tmp_path / "ambiguo.csv"
    ventas.escribir_csv(ambiguo, _filas(GRUPO_A, GRUPO_A.upper()))
    fijar(ruta=ambiguo)
    assert "mismo tipo" in f.conflicto(_sincronizar(cliente))

    # Una lectura sin ningun valor no da de baja todo.
    vacio = tmp_path / "vacio.csv"
    ventas.escribir_csv(vacio, [ventas.GENERADOR])
    fijar(ruta=vacio)
    assert "ningun valor" in f.conflicto(_sincronizar(cliente))
    tipos = f.ok(cliente.get("/api/admin/checklist"))["tipos"]
    assert [t["activo"] for t in tipos] == [True, True]


def test_codigos_anteriores_de_la_migracion_siguen_siendo_validos(base):
    """La restriccion del codigo se amplio: un ``TEQ-...`` sigue entrando
    y un codigo vacio o con espacios al borde no."""
    _ejecutar(
        base,
        "insert into rma.tipo_equipo (codigo, nombre) "
        "values ('TEQ-0001', 'x')",
    )
    with pytest.raises(psycopg.Error):
        _ejecutar(
            base,
            "insert into rma.tipo_equipo (codigo, nombre) values (' a', 'x')",
        )
    with pytest.raises(psycopg.Error):
        _ejecutar(
            base,
            "insert into rma.tipo_equipo (codigo, nombre, campo_origen) "
            "values ('b', 'x', 'tp_modelo')",
        )
