"""Varios roles por usuario y permisos configurables (DC27A, DC08, DC27B;
DEC-MI-12).

- Un usuario con varios roles suma sus permisos; el rol con el que actuo
  queda en el historial.
- Los permisos predeterminados son los que el producto ya validaba; una
  politica configurada los cambia y los de administracion no se tocan.
- Asignar roles y configurar permisos: solo Administracion, con auditoria,
  sin dejar el sistema sin Administrador.
- Consultas configurables (reportes y antecedentes) con sesion real.

El recorrido sobre PostgreSQL (persistencia, auditoria y ``rol_codigo``)
esta en ``tests/postgres/test_roles_permisos_postgres.py``.
"""

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.domain.models import EntidadConfiguracion, RolUsuario, Usuario
from app.services import permisos
from app.services.autorizacion import validar_alguno_de
from app.services.exceptions import PrecondicionInvalidaError
from app.services.roles import (
    cambio_de_permiso,
    cambio_de_roles,
    permisos_de,
)
from tests import test_autenticacion as auth
from tests.fixtures import api_salidas as f

FECHA = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
app_supabase = auth.app_supabase
ADMIN = Usuario(id="ADMIN-001", nombre="A", rol=RolUsuario.ADMINISTRADOR)
RECEP = Usuario(id="RECEP-001", nombre="R", rol=RolUsuario.RECEPCION)
TECH = Usuario(id="TECH-001", nombre="T", rol=RolUsuario.TECNICO)
TECH_RECEP = Usuario(
    id="TECH-009",
    nombre="TR",
    rol=RolUsuario.TECNICO,
    roles=(RolUsuario.TECNICO, RolUsuario.RECEPCION),
)


# --- Modelo ---


def test_un_usuario_anterior_tiene_su_unico_rol():
    usuario = Usuario.model_validate(
        {"id": "X", "nombre": "X", "rol": "RECEPCION"}
    )
    assert usuario.roles == (RolUsuario.RECEPCION,)
    desde_roles = Usuario.model_validate(
        {"id": "X", "nombre": "X", "roles": ["TECNICO", "RECEPCION"]}
    )
    assert desde_roles.rol is RolUsuario.TECNICO
    assert desde_roles.roles == (RolUsuario.TECNICO, RolUsuario.RECEPCION)


def test_varios_roles_suman_permisos_y_anotan_el_rol_habilitante():
    assert validar_alguno_de(TECH_RECEP, permisos.ORDEN_CREAR) is (
        RolUsuario.RECEPCION
    )
    assert validar_alguno_de(TECH_RECEP, permisos.EJECUCION) is (
        RolUsuario.TECNICO
    )
    assert permisos.rol_habilitante("TECH-009") is RolUsuario.TECNICO
    assert permisos.rol_habilitante("OTRO") is None
    propios = set(permisos_de(TECH_RECEP))
    assert {"ORDEN_CREAR", "EJECUCION", "CONTROL_TECNICO"} <= propios
    assert "PAGO_ANULAR" not in propios
    with pytest.raises(PrecondicionInvalidaError, match="TECNICO, RECEPCION"):
        validar_alguno_de(TECH_RECEP, permisos.PAGO_ANULAR)


# --- Politica configurable ---


def test_sin_politica_rigen_los_predeterminados():
    assert permisos.PAGO_REGISTRAR == (
        RolUsuario.ADMINISTRADOR,
        RolUsuario.RECEPCION,
        RolUsuario.COORDINADOR_RMA,
    )
    assert RolUsuario.TECNICO not in permisos.PAGO_REGISTRAR


def test_una_politica_configurada_cambia_quien_puede():
    politica = {
        "PAGO_REGISTRAR": (RolUsuario.TECNICO,),
        "CONFIGURACION_ADMINISTRAR": (RolUsuario.TECNICO,),
    }
    with permisos.politica_vigente(lambda: politica):
        validar_alguno_de(TECH, permisos.PAGO_REGISTRAR)
        with pytest.raises(PrecondicionInvalidaError):
            validar_alguno_de(RECEP, permisos.PAGO_REGISTRAR)
        # Los de administracion no se configuran.
        assert permisos.CONFIGURACION_ADMINISTRAR == (
            RolUsuario.ADMINISTRADOR,
        )
    validar_alguno_de(RECEP, permisos.PAGO_REGISTRAR)


def test_todo_permiso_tiene_un_predeterminado():
    assert len(permisos.REGISTRO) >= 35
    for permiso in permisos.REGISTRO.values():
        assert permiso.predeterminados, permiso.codigo
        assert permiso.descripcion and permiso.grupo


# --- Asignacion de roles y permisos ---


def test_asignar_roles_audita_y_conserva_el_principal():
    nuevos, cambio = cambio_de_roles(
        TECH,
        [RolUsuario.RECEPCION, RolUsuario.TECNICO],
        usuarios=[ADMIN, RECEP, TECH],
        usuario=ADMIN,
        fecha=FECHA,
    )
    assert nuevos == (RolUsuario.TECNICO, RolUsuario.RECEPCION)
    assert (cambio.entidad, cambio.clave, cambio.campo) == (
        EntidadConfiguracion.USUARIO,
        "TECH-001",
        "roles",
    )
    assert (cambio.valor_anterior, cambio.valor_nuevo) == (
        "TECNICO",
        "RECEPCION, TECNICO",
    )


@pytest.mark.parametrize(
    ("destino", "roles", "actor", "mensaje"),
    [
        (ADMIN, [RolUsuario.RECEPCION], ADMIN, "sin un Administrador"),
        (TECH, [], ADMIN, "al menos un rol"),
        (TECH, [RolUsuario.TECNICO], ADMIN, "no hay cambios"),
        (TECH, [RolUsuario.RECEPCION], RECEP, "ADMINISTRADOR"),
    ],
)
def test_reglas_de_la_asignacion(destino, roles, actor, mensaje):
    with pytest.raises(PrecondicionInvalidaError, match=mensaje):
        cambio_de_roles(
            destino,
            roles,
            usuarios=[ADMIN, RECEP, TECH],
            usuario=actor,
            fecha=FECHA,
        )


def test_otro_administrador_permite_quitar_el_rol():
    otro = Usuario(id="ADMIN-002", nombre="B", rol=RolUsuario.ADMINISTRADOR)
    nuevos, _ = cambio_de_roles(
        ADMIN,
        [RolUsuario.RECEPCION],
        usuarios=[ADMIN, otro],
        usuario=otro,
        fecha=FECHA,
    )
    assert nuevos == (RolUsuario.RECEPCION,)
    inactivo = otro.model_copy(update={"activo": False})
    with pytest.raises(PrecondicionInvalidaError, match="sin un Admin"):
        cambio_de_roles(
            ADMIN,
            [RolUsuario.RECEPCION],
            usuarios=[ADMIN, inactivo],
            usuario=ADMIN,
            fecha=FECHA,
        )


def test_configurar_un_permiso():
    nuevos, cambio = cambio_de_permiso(
        permisos.DESCUENTO, [], usuario=ADMIN, fecha=FECHA
    )
    assert nuevos == ()
    assert (cambio.valor_anterior, cambio.valor_nuevo) == (
        "ADMINISTRADOR, RECEPCION",
        "(ninguno)",
    )
    with pytest.raises(PrecondicionInvalidaError, match="no se configura"):
        cambio_de_permiso(
            permisos.ROLES_ADMINISTRAR, [], usuario=ADMIN, fecha=FECHA
        )
    with pytest.raises(PrecondicionInvalidaError):
        cambio_de_permiso(
            permisos.DESCUENTO,
            [RolUsuario.TECNICO],
            usuario=RECEP,
            fecha=FECHA,
        )


# --- HTTP (modo JSON) ---


def _con_usuario_doble(directorio) -> None:
    """TECH-001 es tambien Recepcion."""
    ruta = directorio / "catalogs" / "usuarios.json"
    usuarios = json.loads(ruta.read_text("utf-8"))
    for usuario in usuarios:
        if usuario["id"] == f.TECNICO:
            usuario["roles"] = ["TECNICO", "RECEPCION"]
    ruta.write_text(json.dumps(usuarios), "utf-8")


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def test_un_usuario_con_dos_roles_trabaja_con_los_dos(tmp_path):
    f.sembrar(tmp_path, "10")
    _con_usuario_doble(tmp_path)
    from app.core.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(data_dir=tmp_path))) as cliente:
        usuarios = {
            u["id"]: u for u in f.ok(cliente.get("/api/catalogs/users"))
        }
        doble = usuarios[f.TECNICO]
        assert doble["roles"] == ["TECNICO", "RECEPCION"]
        assert {"ORDEN_CREAR", "EJECUCION"} <= set(doble["permisos"])

        orden_id = f.ok(
            cliente.post(
                "/api/orders",
                json={
                    "usuario_id": f.TECNICO,
                    "cliente": {"nombre_apellido": "Cli", "telefono": "1"},
                    "equipo": {
                        "marca": "Apple",
                        "modelo": "iPhone 14",
                        "falla_reportada": "No carga.",
                    },
                },
            )
        )["id"]
        orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
        alta = orden["historial"][0]
        assert (alta["usuario_id"], alta["rol"]) == (f.TECNICO, "RECEPCION")

        bandejas = f.ok(cliente.get(f"/api/work/inbox?usuario_id={f.TECNICO}"))
        assert bandejas["roles"] == ["TECNICO", "RECEPCION"]
        codigos = [b["codigo"] for b in bandejas["bandejas"]]
        assert len(codigos) == len(set(codigos))


def test_la_administracion_de_roles_exige_postgres(cliente):
    usuarios = f.ok(cliente.get("/api/admin/users"))
    assert {u["id"] for u in usuarios} >= {f.ADMINISTRADOR, f.TECNICO}
    catalogo = f.ok(cliente.get("/api/admin/permissions"))
    pago = next(p for p in catalogo if p["codigo"] == "PAGO_REGISTRAR")
    assert pago["vigentes"] == pago["predeterminados"]
    assert pago["configurable"] is True
    mensaje = f.conflicto(
        cliente.put(
            f"/api/admin/users/{f.TECNICO}/roles",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "roles": ["TECNICO", "RECEPCION"],
            },
        )
    )
    assert "PostgreSQL" in mensaje


# --- Consultas configurables con sesion real ---


class _ConfiguracionDePrueba:
    def __init__(self, politica):
        self._politica = politica

    def leer_permisos(self):
        return self._politica


def test_las_consultas_respetan_el_permiso_configurado(app_supabase):
    auth_app = app_supabase
    contexto = auth_app.state.contexto
    auth_app.state.contexto = replace(
        contexto,
        configuracion=_ConfiguracionDePrueba(
            {"REPORTES_CONSULTAR": (RolUsuario.ADMINISTRADOR,)}
        ),
    )
    cliente = TestClient(auth_app)
    ruta = "/api/reports/operational"
    auth._error(
        cliente.get(ruta, headers=auth.sesion(f.TECNICO)),
        403,
        "ROL_NO_AUTORIZADO",
    )
    assert (
        cliente.get(ruta, headers=auth.sesion(f.ADMINISTRADOR)).status_code
        == 200
    )
    # Antecedentes sigue con su predeterminado (todos los roles).
    assert (
        cliente.get(
            "/api/equipment/history?imei=1",
            headers=auth.sesion(f.TECNICO),
        ).status_code
        == 200
    )
    yo = f.ok(cliente.get("/api/me", headers=auth.sesion(f.TECNICO)))
    assert "REPORTES_CONSULTAR" not in yo["permisos"]
    assert yo["roles"] == ["TECNICO"]
