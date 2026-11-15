"""Checklist de recepcion (DC12) y advertencia por informacion faltante
(BR-REP-025) en JSON, y las reglas de la copia de los Tipos de Equipo del
catalogo de Ventas.

La advertencia nunca bloquea: la Orden informa que falta y Recepcion
puede continuar igualmente, lo que queda registrado. Sin ningun tipo de
equipo vigente (en JSON no hay copia; en PostgreSQL, mientras negocio no
defina la columna de Ventas) no se pide un checklist que no se puede
completar. El recorrido completo, sobre PostgreSQL:
tests/postgres/test_checklist_postgres.py.
"""

from datetime import UTC, datetime

import pytest

from app.domain.models import ProductoInformado, RolUsuario, Usuario
from app.domain.models.checklist import TipoEquipo
from app.services import PrecondicionInvalidaError
from app.services.checklist import fusionar_tipos_equipo, tipos_informados
from tests.fixtures import api_salidas as f

FECHA = datetime(2026, 11, 15, 12, tzinfo=UTC)
ADMIN = Usuario(
    id="ADMIN-001", nombre="Admin", rol=RolUsuario.ADMINISTRADOR, activo=True
)
RECEPCION = Usuario(
    id="RECEP-001", nombre="Recep", rol=RolUsuario.RECEPCION, activo=True
)


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def test_advertencia_no_bloquea_y_la_confirmacion_queda(cliente):
    orden_id = f.crear(cliente)
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    # DC12: en JSON no hay tipos de equipo; el checklist no se pide.
    assert orden["informacion_faltante"] == [
        "Fotografias",
        "Observaciones del equipo",
    ]
    assert orden["tipo_equipo"] is None
    # No bloquea: se puede seguir con los trabajos sin confirmar.
    f.agregar(cliente, orden_id)

    f.conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/missing-info-ack",
            json={"usuario_id": f.TECNICO},
        )
    )
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/missing-info-ack",
            json={"usuario_id": f.RECEPCION},
        )
    )
    assert orden["informacion_faltante"] == []
    catalogo = f.ok(cliente.get("/api/catalogs/checklist"))
    assert (
        catalogo["editable"],
        catalogo["tipos"],
        catalogo["preguntas"],
    ) == (
        False,
        [],
        [],
    )
    assert catalogo["origen"]["definido"] is False
    assert (
        cliente.post(
            f"/api/orders/{orden_id}/checklist",
            json={"usuario_id": f.RECEPCION, "tipo_equipo_id": "IPHONE"},
        ).status_code
        == 404
    )
    # En JSON la copia no se actualiza (se administra sobre PostgreSQL).
    f.conflicto(
        cliente.post(
            "/api/admin/equipment-types/sync",
            json={"usuario_id": f.ADMINISTRADOR},
        )
    )


def _producto(id_, *, grupo, categoria="IPHONE", **otros) -> ProductoInformado:
    return ProductoInformado(
        tipo_producto_id=id_,
        descripcion=id_,
        categoria=categoria,
        subcategoria="IPHONE USADOS",
        grupo=grupo,
        **otros,
    )


def test_tipos_informados_son_los_valores_distintos_de_equipos_vigentes():
    productos = [
        _producto("a", grupo="apple_usados"),
        _producto("b", grupo=" apple_usados "),
        _producto("c", grupo="otro"),
        _producto("g", grupo="generador", generador=True),
        _producto("e", grupo="eliminado", eliminado=True),
        _producto("v", grupo=None),
    ]
    assert tipos_informados(productos, "tp_gp") == ["apple_usados", "otro"]
    assert tipos_informados(productos, "tp_categoria") == ["IPHONE"]
    with pytest.raises(PrecondicionInvalidaError, match="no es una columna"):
        tipos_informados(productos, "tp_modelo")
    with pytest.raises(PrecondicionInvalidaError, match="mismo tipo"):
        tipos_informados(
            [_producto("a", grupo="x"), _producto("b", grupo="X")], "tp_gp"
        )
    with pytest.raises(PrecondicionInvalidaError, match="ningun valor"):
        tipos_informados([_producto("g", grupo="x", generador=True)], "tp_gp")


def test_fusion_da_de_alta_reactiva_y_da_de_baja_sin_borrar():
    existentes = [
        TipoEquipo(id="sigue", nombre="sigue", campo_origen="tp_gp"),
        TipoEquipo(id="vuelve", nombre="vuelve", activo=False),
        TipoEquipo(id="se_va", nombre="se_va", campo_origen="tp_gp"),
        TipoEquipo(id="ya_no", nombre="ya_no", activo=False),
    ]
    fusion = fusionar_tipos_equipo(
        existentes,
        ["nuevo", "sigue", "vuelve"],
        campo="tp_gp",
        usuario=ADMIN,
        fecha=FECHA,
    )
    por_id = {t.id: t for t in fusion.tipos}
    assert set(por_id) == {"nuevo", "sigue", "vuelve", "se_va"}
    assert por_id["se_va"].activo is False
    assert all(por_id[i].activo for i in ("nuevo", "sigue", "vuelve"))
    assert por_id["sigue"].sincronizado_en == FECHA
    assert (fusion.nuevos, fusion.reactivados, fusion.dados_de_baja) == (
        1,
        1,
        1,
    )
    assert fusion.sin_cambios == 1
    claves = {(c.clave, c.campo) for c in fusion.cambios}
    assert ("sigue", "activo") not in claves
    assert ("se_va", "activo") in claves
    assert ("vuelve", "activo") in claves
    # Solo Administracion.
    with pytest.raises(PrecondicionInvalidaError):
        fusionar_tipos_equipo(
            existentes, ["x"], campo="tp_gp", usuario=RECEPCION, fecha=FECHA
        )


def test_cambiar_la_columna_de_origen_queda_auditado():
    anterior = TipoEquipo(id="IPHONE", nombre="IPHONE", campo_origen="tp_gp")
    fusion = fusionar_tipos_equipo(
        [anterior],
        ["IPHONE"],
        campo="tp_categoria",
        usuario=ADMIN,
        fecha=FECHA,
    )
    assert [
        (c.campo, c.valor_anterior, c.valor_nuevo) for c in fusion.cambios
    ] == [("campo_origen", "tp_gp", "tp_categoria")]
