"""Roles y permisos sobre PostgreSQL (DC27A, DC08; DEC-MI-12).

Con la migracion ``20261113000100_roles_permisos.sql``: los roles quedan en
``rma.usuario_rol``, los permisos configurados en ``rma.permiso`` y cada
cambio en ``rma.cambio_configuracion``; el rol con que se actuo en
``rma.evento_negocio.rol_codigo``. Un permiso configurado rige desde el
pedido siguiente.
"""

import pytest

pytest.importorskip("psycopg_pool")

from tests.fixtures import api_salidas as f  # noqa: E402
from tests.postgres import test_configuracion_postgres as config  # noqa: E402
from tests.postgres import test_idempotencia_postgres as idem  # noqa: E402
from tests.postgres import test_ordenes_postgres as ordenes  # noqa: E402
from tests.postgres.test_ordenes_postgres import _sql  # noqa: E402

armar = ordenes.armar
base = ordenes.base
corpus = ordenes.corpus
plantilla = ordenes.plantilla
api = idem.api
admin = config.admin


def _roles(base, codigo):
    return [
        r
        for (r,) in _sql(
            base,
            """
            select r.codigo from rma.usuario_rol ur
            join rma.usuario u on u.id = ur.usuario_id
            join rma.rol r on r.id = ur.rol_id
            where u.codigo = %s order by ur.otorgado_en, r.codigo
            """,
            (codigo,),
        )
    ]


def _crear(cliente, usuario):
    return cliente.post(
        "/api/orders",
        json={
            "usuario_id": usuario,
            "cliente": {"nombre_apellido": "Cli", "telefono": "341-9"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "No carga.",
            },
        },
    )


def test_asignar_un_segundo_rol_y_actuar_con_el(admin, base):
    usuario = f.ok(
        admin.put(
            f"/api/admin/users/{f.TECNICO}/roles",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "roles": ["RECEPCION", "TECNICO"],
            },
        )
    )
    assert usuario["roles"] == ["TECNICO", "RECEPCION"]
    assert _roles(base, f.TECNICO) == ["TECNICO", "RECEPCION"]
    usuarios = {u["id"]: u for u in f.ok(admin.get("/api/admin/users"))}
    assert usuarios[f.TECNICO]["rol"] == "TECNICO"
    assert "ORDEN_CREAR" in usuarios[f.TECNICO]["permisos"]
    assert _sql(
        base,
        """
        select clave, campo, valor_anterior, valor_nuevo
        from rma.cambio_configuracion where entidad = 'USUARIO'
        """,
    ) == [(f.TECNICO, "roles", "TECNICO", "RECEPCION, TECNICO")]

    orden_id = f.ok(_crear(admin, f.TECNICO))["id"]
    assert _sql(
        base,
        """
        select u.codigo, e.rol_codigo from rma.evento_negocio e
        join rma.orden o on o.id = e.orden_id
        join rma.usuario u on u.id = e.usuario_id
        where o.codigo = %s order by e.secuencia limit 1
        """,
        (orden_id,),
    ) == [(f.TECNICO, "RECEPCION")]
    alta = f.ok(admin.get(f"/api/orders/{orden_id}"))["historial"][0]
    assert alta["rol"] == "RECEPCION"


def test_nunca_sin_administrador(admin, base):
    mensaje = f.conflicto(
        admin.put(
            f"/api/admin/users/{f.ADMINISTRADOR}/roles",
            json={"usuario_id": f.ADMINISTRADOR, "roles": ["RECEPCION"]},
        )
    )
    assert "sin un Administrador" in mensaje
    assert _roles(base, f.ADMINISTRADOR) == ["ADMINISTRADOR"]


def test_un_permiso_configurado_rige_en_el_pedido_siguiente(admin, base):
    assert f.ok(_crear(admin, f.RECEPCION))["id"]
    vista = f.ok(
        admin.put(
            "/api/admin/permissions/ORDEN_CREAR",
            json={"usuario_id": f.ADMINISTRADOR, "roles": ["ADMINISTRADOR"]},
        )
    )
    assert vista["vigentes"] == ["ADMINISTRADOR"]
    assert _sql(base, "select codigo, roles from rma.permiso") == [
        ("ORDEN_CREAR", ["ADMINISTRADOR"])
    ]

    assert "ADMINISTRADOR" in f.conflicto(_crear(admin, f.RECEPCION))
    assert f.ok(_crear(admin, f.ADMINISTRADOR))["id"]
    catalogo = {
        p["codigo"]: p for p in f.ok(admin.get("/api/admin/permissions"))
    }
    assert catalogo["ORDEN_CREAR"]["vigentes"] == ["ADMINISTRADOR"]
    assert catalogo["ORDEN_CREAR"]["predeterminados"] == ["RECEPCION"]

    # Los permisos de administracion no se configuran.
    assert "no se configura" in f.conflicto(
        admin.put(
            "/api/admin/permissions/ROLES_ADMINISTRAR",
            json={"usuario_id": f.ADMINISTRADOR, "roles": ["TECNICO"]},
        )
    )
    cambios = f.ok(
        admin.get("/api/admin/config-changes", params={"entidad": "PERMISO"})
    )
    assert [
        (c["clave"], c["valor_anterior"], c["valor_nuevo"]) for c in cambios
    ] == [("ORDEN_CREAR", "RECEPCION", "ADMINISTRADOR")]
