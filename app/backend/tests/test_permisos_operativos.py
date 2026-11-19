# ruff: noqa: E501
"""Configuracion v2, CFG-03: permisos operativos (reglas puras y API JSON).

- Catalogos con permisos propios y configurables, al inicio solo de
  Administracion (D2); el precio aparte (D3): un alta de Tipo fija precio y
  exige los dos; un insumo puede darse de alta sin precio.
- Compras dividida por accion (D5), heredando los roles de
  ``COMPRAS_GESTIONAR`` (DF-4); cancelar una OC confirmada exige
  ``OC_CANCELAR`` y quien crea OC descarta su propio borrador (DF-5).
- Dependencias: un rol no queda con una accion sin su consulta.
- ``ENVIAR_A_REVISION`` y ``GARANTIA_RMA_CREAR`` reemplazan los roles fijos
  (brechas 1 y 2): configurables, con el mismo predeterminado.
- Alias ``COMPRAS_GESTIONAR`` para el frontend publicado.

Con sesion real y PostgreSQL: ``tests/postgres/test_permisos_operativos_postgres.py``.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.models import Insumo, RolUsuario, TipoReparacion, Usuario
from app.domain.models.compras import ItemOrdenCompra, OrdenCompra
from app.services import permisos
from app.services.compras import (
    cancelar_orden_compra,
    confirmar_orden_compra,
)
from app.services.configuracion import cambios_de_tipo
from app.services.exceptions import PrecondicionInvalidaError
from app.services.operativa import cambios_de_insumo
from app.services.roles import cambio_de_permiso, permisos_de
from tests.fixtures import api_salidas as f

FECHA = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
ADMIN = Usuario(id="ADMIN-001", nombre="A", rol=RolUsuario.ADMINISTRADOR)
RECEP = Usuario(id="RECEP-001", nombre="R", rol=RolUsuario.RECEPCION)
COORD = Usuario(id="COORD-001", nombre="C", rol=RolUsuario.COORDINADOR_RMA)
TECH = Usuario(id="TECH-001", nombre="T", rol=RolUsuario.TECNICO)


def _politica(**roles):
    return permisos.politica_vigente(
        lambda: {codigo: tuple(valor) for codigo, valor in roles.items()}
    )


# --- Catalogo de permisos ---------------------------------------------------


NUEVOS_DE_CATALOGO = (
    "TIPO_REPARACION_GESTIONAR",
    "PRECIOS_GESTIONAR",
    "MESA_TIPOS_GESTIONAR",
    "MOTIVO_GESTIONAR",
    "INSUMO_GESTIONAR",
    "PLANTILLA_GESTIONAR",
    "CHECKLIST_GESTIONAR",
    "PROVEEDOR_GESTIONAR",
)
DE_COMPRAS = (
    "COMPRA_SOLICITAR",
    "OC_CREAR",
    "OC_CONFIRMAR",
    "OC_CANCELAR",
    "COMPRA_RECIBIR",
)


def test_los_permisos_de_catalogos_empiezan_solo_con_administracion():
    # D2: nadie gana acceso sin que Administracion lo decida.
    for codigo in NUEVOS_DE_CATALOGO:
        permiso = permisos.REGISTRO[codigo]
        assert permiso.predeterminados == (RolUsuario.ADMINISTRADOR,), codigo
        assert permiso.configurable, codigo


def test_compras_hereda_los_roles_de_compras_gestionar():
    # DF-4: los predeterminados de COMPRAS_GESTIONAR (DEC-MI-09).
    for codigo in DE_COMPRAS:
        assert set(permisos.REGISTRO[codigo].predeterminados) == {
            RolUsuario.RECEPCION,
            RolUsuario.COORDINADOR_RMA,
            RolUsuario.ADMINISTRADOR,
        }, codigo
        assert permisos.REGISTRO[codigo].requiere == ("COMPRAS_CONSULTAR",)
    assert "COMPRAS_GESTIONAR" not in permisos.REGISTRO


def test_lo_sensible_sigue_siendo_de_administracion_y_fijo():
    for permiso in (
        permisos.ROLES_ADMINISTRAR,
        permisos.CONFIGURACION_ADMINISTRAR,
    ):
        assert permiso.predeterminados == (RolUsuario.ADMINISTRADOR,)
        assert not permiso.configurable


def test_el_alias_de_compras_para_el_frontend_publicado():
    assert "COMPRAS_GESTIONAR" in permisos_de(RECEP)
    assert "COMPRAS_GESTIONAR" not in permisos_de(TECH)
    with _politica(OC_CREAR=[RolUsuario.ADMINISTRADOR]):
        assert "COMPRAS_GESTIONAR" not in permisos_de(RECEP)


# --- Tipos de reparacion y precio (D3) --------------------------------------


def _tipo(**cambios) -> TipoReparacion:
    return TipoReparacion(
        **{
            "id": "TR-010",
            "nombre": "Pantalla",
            "precio": Decimal("1000"),
            "puntaje": 1,
            "garantia_dias": 90,
            **cambios,
        }
    )


def test_el_tipo_y_su_precio_tienen_permisos_separados():
    anterior = _tipo()
    with _politica(TIPO_REPARACION_GESTIONAR=[RolUsuario.COORDINADOR_RMA]):
        # Sin PRECIOS_GESTIONAR: edita el nombre, no el precio ni el alta.
        assert cambios_de_tipo(
            anterior, _tipo(nombre="Pantalla OLED"), usuario=COORD, fecha=FECHA
        )
        with pytest.raises(PrecondicionInvalidaError):
            cambios_de_tipo(
                anterior,
                _tipo(precio=Decimal("900")),
                usuario=COORD,
                fecha=FECHA,
            )
        with pytest.raises(PrecondicionInvalidaError):
            cambios_de_tipo(None, _tipo(), usuario=COORD, fecha=FECHA)
    with _politica(
        TIPO_REPARACION_GESTIONAR=[RolUsuario.COORDINADOR_RMA],
        PRECIOS_GESTIONAR=[RolUsuario.COORDINADOR_RMA],
    ):
        assert cambios_de_tipo(None, _tipo(), usuario=COORD, fecha=FECHA)
    # Solo el precio no alcanza para el Tipo.
    with (
        _politica(PRECIOS_GESTIONAR=[RolUsuario.COORDINADOR_RMA]),
        pytest.raises(PrecondicionInvalidaError),
    ):
        cambios_de_tipo(
            anterior, _tipo(precio=Decimal("900")), usuario=COORD, fecha=FECHA
        )
    # Por defecto, Recepcion no administra Tipos (D2).
    with pytest.raises(PrecondicionInvalidaError):
        cambios_de_tipo(
            anterior, _tipo(nombre="x"), usuario=RECEP, fecha=FECHA
        )


def _insumo(**cambios) -> Insumo:
    return Insumo(
        **{
            "id": "INS-010",
            "codigo": "INS-010",
            "nombre": "Bateria",
            "stock_fisico": 0,
            **cambios,
        }
    )


def test_un_insumo_sin_precio_no_exige_el_permiso_de_precios():
    with _politica(INSUMO_GESTIONAR=[RolUsuario.RECEPCION]):
        assert cambios_de_insumo(None, _insumo(), usuario=RECEP, fecha=FECHA)
        with pytest.raises(PrecondicionInvalidaError):
            cambios_de_insumo(
                None,
                _insumo(precio=Decimal("10")),
                usuario=RECEP,
                fecha=FECHA,
            )
        anterior = _insumo(precio=Decimal("10"))
        # Editar sin tocar el precio: alcanza INSUMO_GESTIONAR.
        assert cambios_de_insumo(
            anterior,
            _insumo(precio=Decimal("10"), nombre="Bateria A54"),
            usuario=RECEP,
            fecha=FECHA,
        )
        with pytest.raises(PrecondicionInvalidaError):
            cambios_de_insumo(
                anterior,
                _insumo(precio=Decimal("12")),
                usuario=RECEP,
                fecha=FECHA,
            )


def test_un_precio_con_mas_de_dos_decimales_se_rechaza():
    # QA B, M1: la base redondearia el precio sin pasar por
    # PRECIOS_GESTIONAR ni dejar auditoria.
    with _politica(INSUMO_GESTIONAR=[RolUsuario.RECEPCION]):
        with pytest.raises(PrecondicionInvalidaError, match="dos decimales"):
            cambios_de_insumo(
                _insumo(precio=Decimal("10.50")),
                _insumo(precio=Decimal("10.505")),
                usuario=RECEP,
                fecha=FECHA,
            )
    with pytest.raises(PrecondicionInvalidaError, match="dos decimales"):
        cambios_de_tipo(
            _tipo(),
            _tipo(precio=Decimal("1000.005")),
            usuario=ADMIN,
            fecha=FECHA,
        )
    # Mismo valor con otra escritura: no es un cambio de precio.
    with _politica(INSUMO_GESTIONAR=[RolUsuario.RECEPCION]):
        assert cambios_de_insumo(
            _insumo(precio=Decimal("10.5")),
            _insumo(precio=Decimal("10.500"), nombre="Otro"),
            usuario=RECEP,
            fecha=FECHA,
        )


# --- Compras (D5, DF-5) -------------------------------------------------------


def _oc(*, creada_por="RECEP-001", confirmada=False) -> OrdenCompra:
    return OrdenCompra(
        id="OC-000001",
        proveedor_id="PRV-0001",
        items=[
            ItemOrdenCompra(
                insumo_id="INS-001",
                cantidad=Decimal(1),
                costo_unitario=Decimal(1),
            )
        ],
        creada_por=creada_por,
        creada_en=FECHA,
        confirmada_por="ADMIN-001" if confirmada else None,
        confirmada_en=FECHA if confirmada else None,
    )


def test_cancelar_una_oc_segun_su_estado_y_quien_la_creo():
    # Recepcion puede crear pero no cancelar OC (configurado).
    with _politica(OC_CANCELAR=[RolUsuario.ADMINISTRADOR]):
        # Su propio borrador: lo descarta con OC_CREAR.
        assert cancelar_orden_compra(
            _oc(), motivo="error", usuario=RECEP, fecha=FECHA
        ).cancelada_en
        # El borrador de otro o una OC confirmada: OC_CANCELAR.
        with pytest.raises(PrecondicionInvalidaError):
            cancelar_orden_compra(
                _oc(creada_por="COORD-001"),
                motivo="error",
                usuario=RECEP,
                fecha=FECHA,
            )
        with pytest.raises(PrecondicionInvalidaError):
            cancelar_orden_compra(
                _oc(confirmada=True),
                motivo="error",
                usuario=RECEP,
                fecha=FECHA,
            )
        assert cancelar_orden_compra(
            _oc(confirmada=True), motivo="error", usuario=ADMIN, fecha=FECHA
        ).cancelada_en
    # Sin OC_CREAR ni OC_CANCELAR, ni su propio borrador.
    with (
        _politica(
            OC_CREAR=[RolUsuario.ADMINISTRADOR],
            OC_CANCELAR=[RolUsuario.ADMINISTRADOR],
        ),
        pytest.raises(PrecondicionInvalidaError),
    ):
        cancelar_orden_compra(_oc(), motivo="x", usuario=RECEP, fecha=FECHA)


def test_confirmar_exige_su_propio_permiso():
    with _politica(OC_CONFIRMAR=[RolUsuario.ADMINISTRADOR]):
        with pytest.raises(PrecondicionInvalidaError):
            confirmar_orden_compra(_oc(), usuario=RECEP, fecha=FECHA)
        assert confirmar_orden_compra(_oc(), usuario=ADMIN, fecha=FECHA)


# --- Dependencias ---------------------------------------------------------------


def test_una_accion_no_queda_sin_su_consulta():
    # El Tecnico no consulta Compras: no puede crear OC.
    with pytest.raises(PrecondicionInvalidaError, match="COMPRAS_CONSULTAR"):
        cambio_de_permiso(
            permisos.OC_CREAR,
            [RolUsuario.ADMINISTRADOR, RolUsuario.TECNICO],
            usuario=ADMIN,
            fecha=FECHA,
        )
    # Quitarle la consulta a Recepcion, que crea OC: primero la accion.
    with pytest.raises(PrecondicionInvalidaError, match="quitaselo"):
        cambio_de_permiso(
            permisos.COMPRAS_CONSULTAR,
            [RolUsuario.ADMINISTRADOR, RolUsuario.COORDINADOR_RMA],
            usuario=ADMIN,
            fecha=FECHA,
        )
    with _politica(
        COMPRA_SOLICITAR=[RolUsuario.ADMINISTRADOR],
        OC_CREAR=[RolUsuario.ADMINISTRADOR],
        OC_CONFIRMAR=[RolUsuario.ADMINISTRADOR],
        OC_CANCELAR=[RolUsuario.ADMINISTRADOR],
        COMPRA_RECIBIR=[RolUsuario.ADMINISTRADOR],
        PROVEEDOR_GESTIONAR=[RolUsuario.ADMINISTRADOR],
    ):
        nuevos, _ = cambio_de_permiso(
            permisos.COMPRAS_CONSULTAR,
            [RolUsuario.ADMINISTRADOR],
            usuario=ADMIN,
            fecha=FECHA,
        )
        assert nuevos == (RolUsuario.ADMINISTRADOR,)
    # Insumos: Recepcion ya consulta el inventario.
    nuevos, _ = cambio_de_permiso(
        permisos.INSUMO_GESTIONAR,
        [RolUsuario.ADMINISTRADOR, RolUsuario.RECEPCION],
        usuario=ADMIN,
        fecha=FECHA,
    )
    assert RolUsuario.RECEPCION in nuevos


# --- Roles fijos reemplazados por permisos (brechas 1 y 2) ------------------


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path) as test_client:
        yield test_client


def test_enviar_a_revision_sigue_el_permiso_configurado(cliente, monkeypatch):
    orden = f.crear(cliente)
    # Predeterminado: Recepcion (antes, rol fijo). Configurado para
    # Coordinacion RMA, Recepcion ya no puede y Coordinacion si.
    monkeypatch.setattr(
        permisos.ENVIAR_A_REVISION,
        "predeterminados",
        (RolUsuario.COORDINADOR_RMA,),
    )
    f.conflicto(
        cliente.post(
            f"/api/orders/{orden}/send-to-review",
            json={"usuario_id": f.RECEPCION},
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{orden}/send-to-review",
            json={"usuario_id": f.COORDINADOR},
        )
    )
