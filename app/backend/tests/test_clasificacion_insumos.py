"""Clasificacion de insumos y compatibilidad con modelos (DEC-AJ-14, parte A
del bloque 8), sin base de datos.

- Compatibilidad: sin modelos, universal; con modelos, solo esos; equipo
  sin modelo tecnico, solo los universales.
- Categorias de dos niveles, fabricantes y su auditoria
  (``INSUMO_GESTIONAR``).
- La clasificacion de un insumo: lo nuevo tiene que existir y estar
  vigente; lo que ya tenia se conserva aunque se haya dado de baja.
- Modo JSON: los insumos se leen sin clasificar y universales, y la
  administracion es de solo lectura.

La escritura atomica (insumo, compatibilidad y auditoria) se prueba sobre
PostgreSQL en ``tests/postgres/test_clasificacion_insumos_postgres.py``.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.models import (
    CategoriaInsumo,
    EntidadConfiguracion,
    FabricanteRepuesto,
    Insumo,
    ModeloEquipo,
    RolUsuario,
    Usuario,
)
from app.services import PrecondicionInvalidaError
from app.services.clasificacion_insumos import (
    cambios_de_categoria,
    cambios_de_fabricante,
    categoria_padre,
    categorias_por_id,
    compatible,
    en_categoria,
    es_universal,
    insumos_compatibles,
    normalizar_modelos,
    validar_clasificacion,
)
from app.services.operativa import cambios_de_insumo
from tests.fixtures import api_salidas as f

FECHA = datetime(2026, 11, 24, tzinfo=timezone.utc)
ADMIN = Usuario(id="ADMIN-001", nombre="A", rol=RolUsuario.ADMINISTRADOR)
RECEP = Usuario(id="RECEP-001", nombre="R", rol=RolUsuario.RECEPCION)

BATERIAS = CategoriaInsumo(id="CAT-001", nombre="Baterías")
MODULOS = CategoriaInsumo(id="CAT-002", nombre="Módulos")
OLED = CategoriaInsumo(id="CAT-003", nombre="OLED", padre_id="CAT-002")
INCELL = CategoriaInsumo(
    id="CAT-004", nombre="Incell", padre_id="CAT-002", activo=False
)
VIEJA = CategoriaInsumo(id="CAT-005", nombre="Vieja", activo=False)
HUERFANA = CategoriaInsumo(id="CAT-006", nombre="Sub", padre_id="CAT-005")
CATEGORIAS = [BATERIAS, MODULOS, OLED, INCELL, VIEJA, HUERFANA]

ACME = FabricanteRepuesto(id="FAB-001", nombre="Acme")
BAJA = FabricanteRepuesto(id="FAB-002", nombre="Baja", activo=False)
FABRICANTES = [ACME, BAJA]

MOD_14 = ModeloEquipo(id="MOD-0014", marca="Apple", modelo="iPhone 14")
MOD_15 = ModeloEquipo(id="MOD-0015", marca="Apple", modelo="iPhone 15")
MOD_VIEJO = ModeloEquipo(
    id="MOD-0003", marca="Apple", modelo="iPhone 8", activo=False
)
MODELOS = [MOD_14, MOD_15, MOD_VIEJO]


def insumo(id_="INS-001", **campos) -> Insumo:
    return Insumo(
        id=id_,
        codigo=id_,
        nombre=campos.pop("nombre", "Pieza"),
        stock_fisico=Decimal("0"),
        **campos,
    )


# --- Compatibilidad (funciones puras para la parte B) -----------------------


def test_sin_modelos_es_universal_y_sirve_para_todo():
    adhesivo = insumo()
    assert es_universal(adhesivo)
    assert compatible(adhesivo, "MOD-0014")
    assert compatible(adhesivo, "MOD-9999")
    # Un equipo sin modelo tecnico admite los universales.
    assert compatible(adhesivo, None)


def test_con_modelos_solo_sirve_para_esos():
    bateria = insumo(modelos_compatibles=("MOD-0014", "MOD-0015"))
    assert not es_universal(bateria)
    assert compatible(bateria, "MOD-0014")
    assert not compatible(bateria, "MOD-0003")
    # Sin modelo tecnico, solo los universales: la excepcion «compatibilidad
    # no verificada» es de la parte B, no de esta regla.
    assert not compatible(bateria, None)


def test_una_categoria_incluye_sus_subcategorias():
    por_id = categorias_por_id(CATEGORIAS)
    oled = insumo(categoria_id="CAT-003")
    assert categoria_padre("CAT-003", por_id) == "CAT-002"
    assert categoria_padre("CAT-001", por_id) == "CAT-001"
    assert categoria_padre(None, por_id) is None
    assert en_categoria(oled, "CAT-003", por_id)
    assert en_categoria(oled, "CAT-002", por_id)
    assert not en_categoria(oled, "CAT-001", por_id)
    modulo_sin_sub = insumo(categoria_id="CAT-002")
    assert en_categoria(modulo_sin_sub, "CAT-002", por_id)
    assert not en_categoria(modulo_sin_sub, "CAT-003", por_id)
    assert not en_categoria(insumo(), "CAT-002", por_id)


def test_insumos_compatibles_por_modelo_y_categoria():
    universal = insumo("INS-001", categoria_id="CAT-001")
    bat_14 = insumo(
        "INS-002", categoria_id="CAT-001", modelos_compatibles=("MOD-0014",)
    )
    bat_15 = insumo(
        "INS-003", categoria_id="CAT-001", modelos_compatibles=("MOD-0015",)
    )
    oled_14 = insumo(
        "INS-004", categoria_id="CAT-003", modelos_compatibles=("MOD-0014",)
    )
    inactiva = insumo(
        "INS-005",
        categoria_id="CAT-001",
        modelos_compatibles=("MOD-0014",),
        activo=False,
    )
    sin_clasificar = insumo("INS-006")
    todos = [universal, bat_14, bat_15, oled_14, inactiva, sin_clasificar]

    def ids(lista):
        return [i.id for i in lista]

    assert ids(
        insumos_compatibles(
            todos, "MOD-0014", "CAT-001", categorias=CATEGORIAS
        )
    ) == ["INS-001", "INS-002"]
    assert ids(
        insumos_compatibles(
            todos,
            "MOD-0014",
            "CAT-001",
            categorias=CATEGORIAS,
            solo_activos=False,
        )
    ) == ["INS-001", "INS-002", "INS-005"]
    # La categoria de primer nivel incluye la subcategoria.
    assert ids(
        insumos_compatibles(
            todos, "MOD-0014", "CAT-002", categorias=CATEGORIAS
        )
    ) == ["INS-004"]
    # Sin categoria: todo lo compatible con el modelo.
    assert ids(insumos_compatibles(todos, "MOD-0015")) == [
        "INS-001",
        "INS-003",
        "INS-006",
    ]
    # Sin modelo tecnico: solo los universales.
    assert ids(
        insumos_compatibles(todos, None, "CAT-001", categorias=CATEGORIAS)
    ) == ["INS-001"]


def test_normalizar_modelos():
    assert normalizar_modelos([" mod-0015", "MOD-0014", "MOD-0015", ""]) == (
        "MOD-0014",
        "MOD-0015",
    )


# --- Categorias y fabricantes ------------------------------------------------


def test_alta_de_categoria_y_subcategoria_auditadas():
    nueva = CategoriaInsumo(id="CAT-010", nombre="Flex")
    cambios = cambios_de_categoria(
        None, nueva, existentes=CATEGORIAS, usuario=ADMIN, fecha=FECHA
    )
    assert {(c.entidad, c.clave, c.campo, c.valor_nuevo) for c in cambios} == {
        (EntidadConfiguracion.CATEGORIA_INSUMO, "CAT-010", "nombre", "Flex"),
        (EntidadConfiguracion.CATEGORIA_INSUMO, "CAT-010", "activo", "true"),
    }
    sub = CategoriaInsumo(id="CAT-011", nombre="Original", padre_id="CAT-002")
    cambios = cambios_de_categoria(
        None, sub, existentes=CATEGORIAS, usuario=ADMIN, fecha=FECHA
    )
    assert ("padre_id", "CAT-002") in {
        (c.campo, c.valor_nuevo) for c in cambios
    }


@pytest.mark.parametrize(
    ("padre", "mensaje"),
    [
        ("CAT-003", "dos niveles"),
        ("CAT-999", "No existe"),
        ("CAT-005", "dada de baja"),
    ],
)
def test_subcategoria_invalida(padre, mensaje):
    sub = CategoriaInsumo(id="CAT-020", nombre="X", padre_id=padre)
    with pytest.raises(PrecondicionInvalidaError, match=mensaje):
        cambios_de_categoria(
            None, sub, existentes=CATEGORIAS, usuario=ADMIN, fecha=FECHA
        )


def test_nombre_repetido_entre_pares_sin_distinguir_mayusculas():
    with pytest.raises(PrecondicionInvalidaError, match="Ya existe CAT-001"):
        cambios_de_categoria(
            None,
            CategoriaInsumo(id="CAT-030", nombre="  baterías "),
            existentes=CATEGORIAS,
            usuario=ADMIN,
            fecha=FECHA,
        )
    with pytest.raises(PrecondicionInvalidaError, match="en Módulos"):
        cambios_de_categoria(
            None,
            CategoriaInsumo(id="CAT-031", nombre="oled", padre_id="CAT-002"),
            existentes=CATEGORIAS,
            usuario=ADMIN,
            fecha=FECHA,
        )
    # El mismo nombre en otro nivel o en otra categoria si se admite.
    cambios_de_categoria(
        None,
        CategoriaInsumo(id="CAT-032", nombre="OLED"),
        existentes=CATEGORIAS,
        usuario=ADMIN,
        fecha=FECHA,
    )


def test_edicion_de_categoria_sin_cambiar_de_nivel():
    renombrada = OLED.model_copy(update={"nombre": "OLED premium"})
    (cambio,) = cambios_de_categoria(
        OLED, renombrada, existentes=CATEGORIAS, usuario=ADMIN, fecha=FECHA
    )
    assert (cambio.campo, cambio.valor_anterior, cambio.valor_nuevo) == (
        "nombre",
        "OLED",
        "OLED premium",
    )
    with pytest.raises(PrecondicionInvalidaError, match="no cambia de nivel"):
        cambios_de_categoria(
            OLED,
            OLED.model_copy(update={"padre_id": None}),
            existentes=CATEGORIAS,
            usuario=ADMIN,
            fecha=FECHA,
        )
    with pytest.raises(PrecondicionInvalidaError, match="no hay cambios"):
        cambios_de_categoria(
            OLED, OLED, existentes=CATEGORIAS, usuario=ADMIN, fecha=FECHA
        )
    (baja,) = cambios_de_categoria(
        BATERIAS,
        BATERIAS.model_copy(update={"activo": False}),
        existentes=CATEGORIAS,
        usuario=ADMIN,
        fecha=FECHA,
    )
    assert (baja.campo, baja.valor_nuevo) == ("activo", "false")


def test_fabricantes_unicos_y_auditados():
    nuevo = FabricanteRepuesto(id="FAB-003", nombre="Ampsentrix")
    cambios = cambios_de_fabricante(
        None, nuevo, existentes=FABRICANTES, usuario=ADMIN, fecha=FECHA
    )
    assert {c.entidad for c in cambios} == {
        EntidadConfiguracion.FABRICANTE_REPUESTO
    }
    with pytest.raises(PrecondicionInvalidaError, match="FAB-001"):
        cambios_de_fabricante(
            None,
            FabricanteRepuesto(id="FAB-004", nombre="ACME"),
            existentes=FABRICANTES,
            usuario=ADMIN,
            fecha=FECHA,
        )


def test_sin_permiso_de_insumos_no_se_administra():
    with pytest.raises(PrecondicionInvalidaError):
        cambios_de_categoria(
            None,
            CategoriaInsumo(id="CAT-040", nombre="Z"),
            existentes=[],
            usuario=RECEP,
            fecha=FECHA,
        )
    with pytest.raises(PrecondicionInvalidaError):
        cambios_de_fabricante(
            None,
            FabricanteRepuesto(id="FAB-040", nombre="Z"),
            existentes=[],
            usuario=RECEP,
            fecha=FECHA,
        )


# --- Clasificacion de un insumo ----------------------------------------------


def validar(anterior, nuevo):
    validar_clasificacion(
        anterior,
        nuevo,
        categorias=CATEGORIAS,
        fabricantes=FABRICANTES,
        modelos=MODELOS,
    )


def test_clasificacion_valida_y_auditada():
    anterior = insumo(nombre="Batería iPhone 14")
    nuevo = anterior.model_copy(
        update={
            "categoria_id": "CAT-003",
            "fabricante_id": "FAB-001",
            "variante": "con marco",
            "codigo_fabricante": "APN-661",
            "modelos_compatibles": ("MOD-0014", "MOD-0015"),
        }
    )
    validar(anterior, nuevo)
    cambios = cambios_de_insumo(anterior, nuevo, usuario=ADMIN, fecha=FECHA)
    assert {
        (c.entidad, c.campo, c.valor_anterior, c.valor_nuevo) for c in cambios
    } == {
        (EntidadConfiguracion.INSUMO, "categoria", None, "CAT-003"),
        (EntidadConfiguracion.INSUMO, "fabricante", None, "FAB-001"),
        (EntidadConfiguracion.INSUMO, "variante", None, "con marco"),
        (EntidadConfiguracion.INSUMO, "codigo_fabricante", None, "APN-661"),
        (
            EntidadConfiguracion.INSUMO,
            "compatibilidad",
            None,
            "MOD-0014, MOD-0015",
        ),
    }
    # Volver a universal se audita con la lista anterior.
    (cambio,) = cambios_de_insumo(
        nuevo,
        nuevo.model_copy(update={"modelos_compatibles": ()}),
        usuario=ADMIN,
        fecha=FECHA,
    )
    assert (cambio.campo, cambio.valor_anterior, cambio.valor_nuevo) == (
        "compatibilidad",
        "MOD-0014, MOD-0015",
        None,
    )


def test_alta_sin_clasificar_no_audita_campos_vacios():
    cambios = cambios_de_insumo(None, insumo(), usuario=ADMIN, fecha=FECHA)
    assert not {
        "categoria",
        "fabricante",
        "variante",
        "codigo_fabricante",
        "compatibilidad",
    } & {c.campo for c in cambios}


@pytest.mark.parametrize(
    ("campos", "mensaje"),
    [
        ({"categoria_id": "CAT-999"}, "No existe la categoria"),
        ({"categoria_id": "CAT-005"}, "dada de baja"),
        # Subcategoria vigente de una categoria dada de baja.
        ({"categoria_id": "CAT-006"}, "dada de baja"),
        ({"categoria_id": "CAT-004"}, "dada de baja"),
        ({"fabricante_id": "FAB-999"}, "No existe el fabricante"),
        ({"fabricante_id": "FAB-002"}, "dado de baja"),
        ({"modelos_compatibles": ("MOD-9999",)}, "No existen los modelos"),
        ({"modelos_compatibles": ("MOD-0003",)}, "dados de baja"),
    ],
)
def test_lo_nuevo_tiene_que_existir_y_estar_vigente(campos, mensaje):
    with pytest.raises(PrecondicionInvalidaError, match=mensaje):
        validar(insumo(), insumo(**campos))


def test_lo_que_ya_tenia_se_conserva_aunque_este_dado_de_baja():
    anterior = insumo(
        categoria_id="CAT-005",
        fabricante_id="FAB-002",
        modelos_compatibles=("MOD-0003",),
    )
    # Agregar un modelo vigente sin quitar el dado de baja.
    validar(
        anterior,
        anterior.model_copy(
            update={"modelos_compatibles": ("MOD-0003", "MOD-0014")}
        ),
    )
    # Pero un alta no puede usarlos.
    with pytest.raises(PrecondicionInvalidaError):
        validar(None, anterior)


# --- Modo JSON: lectura con valores por defecto ------------------------------


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def test_json_lee_los_insumos_sin_clasificar_y_universales(cliente):
    datos = f.ok(cliente.get("/api/admin/supplies"))
    (bateria,) = [i for i in datos["insumos"] if i["id"] == f.INSUMO_BATERIA]
    assert bateria["categoria_id"] is None
    assert bateria["fabricante_id"] is None
    assert bateria["variante"] is None
    assert bateria["codigo_fabricante"] is None
    assert bateria["modelos_compatibles"] == []
    inventario = f.ok(cliente.get("/api/inventory"))
    (situacion,) = [i for i in inventario if i["id"] == f.INSUMO_BATERIA]
    assert situacion["modelos_compatibles"] == []
    assert situacion["categoria_id"] is None


def test_json_clasificacion_vacia_y_de_solo_lectura(cliente):
    catalogo = f.ok(cliente.get("/api/catalogs/supply-classification"))
    assert catalogo["categorias"] == []
    assert catalogo["fabricantes"] == []
    assert len(catalogo["modelos"]) >= 36
    assert {"id", "marca", "nombre", "activo"} <= set(catalogo["modelos"][0])
    admin = f.ok(cliente.get("/api/admin/supply-classification"))
    assert admin["editable"] is False
    for ruta, cuerpo in (
        ("/api/admin/supply-categories", {"nombre": "Baterías"}),
        ("/api/admin/supply-manufacturers", {"nombre": "Acme"}),
    ):
        assert "PostgreSQL" in f.conflicto(
            cliente.post(ruta, json={"usuario_id": f.ADMINISTRADOR, **cuerpo})
        )
    assert "PostgreSQL" in f.conflicto(
        cliente.put(
            f"/api/admin/supplies/{f.INSUMO_BATERIA}",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "nombre": "Batería",
                "categoria_id": "CAT-001",
            },
        )
    )


def test_listar_insumos_compatibles_en_json(cliente):
    """La base de la eleccion de piezas (parte B): en JSON todo es universal
    y sin clasificar."""
    from app.application.clasificacion_insumos import (
        listar_insumos_compatibles,
    )

    contexto = cliente.app.state.contexto
    activos = {i.id for i in contexto.catalogos.listar_insumos() if i.activo}
    assert {
        i.id
        for i in listar_insumos_compatibles(
            contexto, modelo_equipo_id="MOD-0001"
        )
    } == activos
    assert {
        i.id
        for i in listar_insumos_compatibles(contexto, modelo_equipo_id=None)
    } == activos
    assert (
        listar_insumos_compatibles(
            contexto, modelo_equipo_id="MOD-0001", categoria_id="CAT-001"
        )
        == []
    )
