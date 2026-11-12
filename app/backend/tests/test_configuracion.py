"""Administracion de catalogos con auditoria (DC23, DC23AUD, BR-REP-040).

Reglas del service y comportamiento sin PostgreSQL: en el modo JSON los
catalogos son de solo lectura y la API lo dice. El recorrido completo (alta,
edicion, auditoria, historial de precios, snapshot intacto) esta en
``tests/postgres/test_configuracion_postgres.py``.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.models import RolUsuario, TipoReparacion, Usuario
from app.services.configuracion import (
    cambio_de_tipos_habilitados,
    cambios_de_tipo,
)
from app.services.exceptions import DomainError, PrecondicionInvalidaError
from tests.fixtures import api_salidas as f

FECHA = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
ADMIN = Usuario(id="ADMIN-001", nombre="Admin", rol=RolUsuario.ADMINISTRADOR)
RECEPCION = Usuario(id="RECEP-001", nombre="Recep", rol=RolUsuario.RECEPCION)
BATERIA = TipoReparacion(
    id="TR-001",
    nombre="Cambio de bateria",
    precio=Decimal("80000"),
    puntaje=10,
    garantia_dias=90,
)


def test_un_alta_audita_cada_campo():
    cambios = cambios_de_tipo(None, BATERIA, usuario=ADMIN, fecha=FECHA)
    assert [(c.campo, c.valor_anterior, c.valor_nuevo) for c in cambios] == [
        ("nombre", None, "Cambio de bateria"),
        ("precio", None, "80000.00"),
        ("puntaje", None, "10"),
        ("garantia_dias", None, "90"),
        ("activo", None, "true"),
    ]
    assert {c.usuario_id for c in cambios} == {"ADMIN-001"}


def test_una_edicion_audita_solo_lo_que_cambia():
    nuevo = BATERIA.model_copy(update={"precio": Decimal("95000")})
    (cambio,) = cambios_de_tipo(BATERIA, nuevo, usuario=ADMIN, fecha=FECHA)
    assert (cambio.campo, cambio.valor_anterior, cambio.valor_nuevo) == (
        "precio",
        "80000.00",
        "95000.00",
    )
    with pytest.raises(PrecondicionInvalidaError, match="no hay cambios"):
        cambios_de_tipo(BATERIA, BATERIA, usuario=ADMIN, fecha=FECHA)


def test_solo_administracion_y_otros_reservado():
    with pytest.raises(DomainError):
        cambios_de_tipo(None, BATERIA, usuario=RECEPCION, fecha=FECHA)
    otros = BATERIA.model_copy(update={"id": "TR-OTROS"})
    with pytest.raises(PrecondicionInvalidaError, match="reservado"):
        cambios_de_tipo(None, otros, usuario=ADMIN, fecha=FECHA)


def test_tipos_habilitados_de_una_mesa():
    cambio = cambio_de_tipos_habilitados(
        "EST-001",
        ["TR-001", "TR-002"],
        ["TR-001"],
        tipos_existentes=[BATERIA],
        usuario=ADMIN,
        fecha=FECHA,
    )
    assert (cambio.valor_anterior, cambio.valor_nuevo) == (
        "TR-001, TR-002",
        "TR-001",
    )
    with pytest.raises(PrecondicionInvalidaError, match="No existen"):
        cambio_de_tipos_habilitados(
            "EST-001",
            [],
            ["TR-999"],
            tipos_existentes=[BATERIA],
            usuario=ADMIN,
            fecha=FECHA,
        )


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path) as test_client:
        yield test_client


def test_en_json_el_catalogo_es_de_solo_lectura(cliente):
    catalogo = f.ok(cliente.get("/api/admin/catalog"))
    assert catalogo["editable"] is False
    assert {t["id"] for t in catalogo["tipos"]} >= {f.BATERIA, f.PANTALLA}
    assert catalogo["mesas"][0]["tipos"]

    mensaje = f.conflicto(
        cliente.put(
            f"/api/admin/repair-types/{f.BATERIA}",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Cambio de bateria",
                "precio": "1",
                "puntaje": 1,
                "garantia_dias": 1,
            },
        )
    )
    assert "PostgreSQL" in mensaje
    assert f.ok(cliente.get("/api/admin/config-changes")) == []
