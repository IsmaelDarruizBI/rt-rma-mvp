"""Catalogo tecnico de modelos de equipo (propio de RMA) por HTTP.

    GET /api/catalogs/device-models   los modelos activos
    POST /api/orders (equipo)         modelo del catalogo o carga manual
    PUT  /api/orders/{id}/reception   correccion del equipo

El modelo identifica QUE equipo es (marca, modelo, variante): la Orden
guarda su ID y una copia. Capacidad y color no lo identifican; el color
es opcional y se carga aparte. La carga manual conserva la variante.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import MODELOS_EQUIPO_POR_DEFECTO, Settings
from app.main import create_app
from app.repositories import PersistenciaError
from app.storage import JsonModelosEquipoRepository
from tests.fixtures.api_salidas import RECEPCION, conflicto, ok, sembrar

MODELOS = [
    {"id": "MOD-0001", "marca": "Apple", "modelo": "iPhone 15"},
    {
        "id": "MOD-0002",
        "marca": "Apple",
        "modelo": "iPhone 15",
        "variante": "Pro Max",
        "numeros_modelo": ["A2849"],
    },
    {
        "id": "MOD-0003",
        "marca": "Apple",
        "modelo": "iPhone 8",
        "activo": False,
    },
]


def _escribir(ruta, modelos) -> None:
    ruta.write_text(json.dumps(modelos), encoding="utf-8")


@pytest.fixture
def entorno(tmp_path):
    sembrar(tmp_path)
    archivo = tmp_path / "modelos_equipo.json"
    _escribir(archivo, MODELOS)
    settings = Settings(data_dir=tmp_path, modelos_equipo_archivo=archivo)
    with TestClient(create_app(settings)) as cliente:
        yield cliente, archivo


def _alta(cliente, equipo: dict):
    return cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre_apellido": "Ana Gomez", "telefono": "341"},
            "equipo": {"falla_reportada": "No enciende.", **equipo},
        },
    )


def _corregir(cliente, orden_id: str, equipo: dict):
    return cliente.put(
        f"/api/orders/{orden_id}/reception",
        json={
            "usuario_id": RECEPCION,
            "equipo": {"falla_reportada": "No enciende.", **equipo},
        },
    )


def _equipo(cliente, orden_id: str) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))["equipo"]


# --- Lectura -------------------------------------------------------------------


def test_solo_se_ofrecen_los_modelos_activos(entorno):
    cliente, _ = entorno
    modelos = ok(cliente.get("/api/catalogs/device-models"))
    assert [modelo["id"] for modelo in modelos] == ["MOD-0001", "MOD-0002"]
    assert modelos[1] == {
        "id": "MOD-0002",
        "marca": "Apple",
        "modelo": "iPhone 15",
        "variante": "Pro Max",
        "numeros_modelo": ["A2849"],
        "nombre": "Apple iPhone 15 Pro Max",
    }
    assert modelos[0]["variante"] is None
    assert modelos[0]["numeros_modelo"] == []


def test_sin_archivo_el_catalogo_esta_vacio(tmp_path):
    repositorio = JsonModelosEquipoRepository(tmp_path / "no-existe.json")
    assert repositorio.listar_modelos() == []
    assert repositorio.obtener_modelo("MOD-0001") is None


def test_ids_repetidos_se_rechazan(tmp_path):
    archivo = tmp_path / "modelos.json"
    _escribir(archivo, [MODELOS[0], MODELOS[0]])
    with pytest.raises(PersistenciaError):
        JsonModelosEquipoRepository(archivo).listar_modelos()


def test_el_catalogo_versionado_es_valido():
    modelos = JsonModelosEquipoRepository(
        MODELOS_EQUIPO_POR_DEFECTO
    ).listar_modelos()
    assert len({modelo.id for modelo in modelos}) == len(modelos)
    claves = {(m.marca, m.modelo, m.variante) for m in modelos}
    assert len(claves) == len(modelos)


# --- Alta ------------------------------------------------------------------------


def test_alta_con_un_modelo_copia_marca_modelo_y_variante(entorno):
    cliente, _ = entorno
    orden = ok(
        _alta(
            cliente,
            {
                "modelo_tecnico_id": "MOD-0002",
                # Lo que mande la pantalla no pisa al catalogo.
                "marca": "Otra",
                "modelo": "Otro",
                "color": "Negro",
                "imei": "356789012345678",
            },
        )
    )
    equipo = orden["equipo"]
    assert equipo["modelo_tecnico_id"] == "MOD-0002"
    assert (equipo["marca"], equipo["modelo"], equipo["variante"]) == (
        "Apple",
        "iPhone 15",
        "Pro Max",
    )
    # Capacidad y color no identifican el tipo de equipo.
    assert equipo["capacidad"] is None
    assert equipo["color"] == "Negro"
    assert equipo["tipo_producto_id"] is None
    assert equipo["imei"] == "356789012345678"


def test_el_color_es_opcional(entorno):
    cliente, _ = entorno
    equipo = ok(_alta(cliente, {"modelo_tecnico_id": "MOD-0001"}))["equipo"]
    assert equipo["color"] is None
    assert equipo["variante"] is None


@pytest.mark.parametrize("modelo_id", ["MOD-9999", "MOD-0003"])
def test_un_modelo_inexistente_o_inactivo_se_rechaza(entorno, modelo_id):
    cliente, _ = entorno
    antes = ok(cliente.get("/api/orders"))
    conflicto(
        _alta(cliente, {"modelo_tecnico_id": modelo_id}),
        "MODELO_EQUIPO_NO_DISPONIBLE",
    )
    assert ok(cliente.get("/api/orders")) == antes


def test_la_carga_manual_conserva_variante_y_color(entorno):
    cliente, _ = entorno
    equipo = ok(
        _alta(
            cliente,
            {
                "marca": "Samsung",
                "modelo": "Galaxy S23",
                "variante": "Ultra",
                "color": "Verde",
            },
        )
    )["equipo"]
    assert (equipo["marca"], equipo["modelo"], equipo["variante"]) == (
        "Samsung",
        "Galaxy S23",
        "Ultra",
    )
    assert equipo["color"] == "Verde"
    assert equipo["modelo_tecnico_id"] is None
    assert equipo["tipo_producto_id"] is None


def test_sin_modelo_ni_marca_y_modelo_el_pedido_es_invalido(entorno):
    cliente, _ = entorno
    respuesta = _alta(cliente, {"variante": "Pro"})
    assert respuesta.status_code == 422, respuesta.text


# --- Correccion ------------------------------------------------------------


def test_corregir_conserva_la_copia_del_mismo_modelo(entorno):
    cliente, archivo = entorno
    orden_id = ok(_alta(cliente, {"modelo_tecnico_id": "MOD-0002"}))["id"]

    # El modelo deja de ofrecerse y cambia su nombre en el catalogo.
    modelos = [dict(m) for m in MODELOS]
    modelos[1].update(activo=False, variante="Pro Max (2023)")
    _escribir(archivo, modelos)

    ok(
        _corregir(
            cliente,
            orden_id,
            {
                "modelo_tecnico_id": "MOD-0002",
                "imei": "111",
                "color": "Azul",
            },
        )
    )
    equipo = _equipo(cliente, orden_id)
    assert equipo["variante"] == "Pro Max"
    assert equipo["imei"] == "111"
    assert equipo["color"] == "Azul"


def test_corregir_a_otro_modelo_o_a_mano(entorno):
    cliente, _ = entorno
    orden_id = ok(_alta(cliente, {"modelo_tecnico_id": "MOD-0002"}))["id"]

    ok(_corregir(cliente, orden_id, {"modelo_tecnico_id": "MOD-0001"}))
    equipo = _equipo(cliente, orden_id)
    assert (equipo["modelo_tecnico_id"], equipo["variante"]) == (
        "MOD-0001",
        None,
    )

    ok(
        _corregir(
            cliente,
            orden_id,
            {"marca": "Motorola", "modelo": "Moto G13"},
        )
    )
    equipo = _equipo(cliente, orden_id)
    assert equipo["modelo_tecnico_id"] is None
    assert (equipo["marca"], equipo["modelo"]) == ("Motorola", "Moto G13")


def test_el_comprobante_nombra_marca_modelo_y_variante(entorno):
    cliente, _ = entorno
    orden_id = ok(
        _alta(cliente, {"modelo_tecnico_id": "MOD-0002", "color": "Negro"})
    )["id"]
    previa = ok(
        cliente.get(
            f"/api/orders/{orden_id}/documents/preview/COMPROBANTE_RECEPCION"
        )
    )
    equipo = previa["contenido"]["equipo"]
    assert (equipo["marca"], equipo["modelo"], equipo["variante"]) == (
        "Apple",
        "iPhone 15",
        "Pro Max",
    )
    assert equipo["color"] == "Negro"
