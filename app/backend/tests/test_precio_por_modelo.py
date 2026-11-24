"""DEC-AJ-12 (BF-01): precio por modelo, precio manual autorizado, precio
pendiente, copia del trabajo y cambio de modelo.

Modo JSON (la administracion del catalogo es de PostgreSQL: ver
``tests/postgres/test_precio_por_modelo_postgres.py``). Catalogo propio:
``TR-001`` de precio unico y ``TR-010`` con precio por modelo, con precio
solo para ``MOD-0001`` (iPhone 8) y un precio unico «de respaldo» que nunca
debe usarse.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.models import (
    DefinicionAnteriorDetalle,
    EvaluacionTecnica,
    OrigenPrecio,
    ReparacionDetail,
    ResultadoEvaluacionTecnica,
    RolUsuario,
    TipoReparacion,
    Usuario,
)
from app.services import nombre_del_trabajo, tipo_reparacion_otros
from app.services.evaluacion_tecnica import evaluacion_vigente
from app.services.exceptions import PrecondicionInvalidaError
from app.services.precio_trabajo import (
    PrecioManual,
    precio_de_otro_modelo,
    redeterminar_por_cambio_de_modelo,
    resolver_precio,
)
from app.services.redefinicion import aplicar_redefinicion
from tests.fixtures import api_salidas as f

POR_MODELO = "TR-010"
CON_PRECIO = "MOD-0001"  # Apple iPhone 8
SIN_PRECIO = "MOD-0003"  # Apple iPhone 11
FECHA = datetime(2026, 11, 24, 12, tzinfo=UTC)
TIPO = TipoReparacion(
    id=POR_MODELO,
    nombre="Cambio de modulo",
    precio=Decimal("999"),
    puntaje=8,
    garantia_dias=90,
    precio_por_modelo=True,
    precios_modelo={CON_PRECIO: Decimal("60000")},
)


def _usuario(rol: RolUsuario) -> Usuario:
    return Usuario(id=f"U-{rol.value}", nombre=rol.value, rol=rol)


RECEP = _usuario(RolUsuario.RECEPCION)
COORD = _usuario(RolUsuario.COORDINADOR_RMA)
TECH = _usuario(RolUsuario.TECNICO)


def _escribir_tipos(directorio, precios: dict[str, str]) -> None:
    ruta = directorio / "catalogs" / "tipos_reparacion.json"
    tipos = [
        t for t in json.loads(ruta.read_text("utf-8")) if t["id"] != POR_MODELO
    ]
    tipos.append(
        TIPO.model_copy(
            update={
                "precios_modelo": {k: Decimal(v) for k, v in precios.items()}
            }
        ).model_dump(mode="json")
    )
    ruta.write_text(json.dumps(tipos), encoding="utf-8")


@pytest.fixture
def directorio(tmp_path):
    f.sembrar(tmp_path, "10")
    _escribir_tipos(tmp_path, {CON_PRECIO: "60000"})
    return tmp_path


@pytest.fixture
def cliente(directorio):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(data_dir=directorio))) as http:
        yield http


def _crear(cliente, modelo: str | None, **extra) -> dict:
    equipo = (
        {"modelo_tecnico_id": modelo, "falla_reportada": "No enciende."}
        if modelo
        else {
            "marca": "Apple",
            "modelo": "iPhone 14",
            "falla_reportada": "No enciende.",
        }
    )
    return cliente.post(
        "/api/orders",
        json={
            "usuario_id": f.RECEPCION,
            "cliente": {"nombre_apellido": "Ana", "telefono": "341-1"},
            "equipo": equipo,
            "recepcion": {
                "estado_fisico": "Sin golpes.",
                "funcionalidades_verificadas": True,
            },
            **extra,
        },
    )


def _agregar(cliente, orden_id, usuario=f.RECEPCION, **extra):
    return cliente.post(
        f"/api/orders/{orden_id}/details",
        json={
            "usuario_id": usuario,
            "tipo_reparacion_id": POR_MODELO,
            **extra,
        },
    )


def _precio(
    cliente, orden_id, detalle="DET-001", usuario=f.RECEPCION, **extra
):
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle}/price",
        json={"usuario_id": usuario, **extra},
    )


def _avisos(orden) -> list[str]:
    return [a["codigo"] for a in orden["situacion"]["avisos"]]


def _ingreso(cliente, orden_id):
    return cliente.post(
        f"/api/orders/{orden_id}/documents/intake-receipt",
        json={"usuario_id": f.RECEPCION},
    )


# --- Resolucion (una sola regla para todos los caminos) ----------------------


def test_cada_origen_del_precio():
    unico = TipoReparacion(
        id="TR-001",
        nombre="Bateria",
        precio=Decimal("80000"),
        puntaje=1,
        garantia_dias=90,
    )
    otros = tipo_reparacion_otros(Decimal("1500"))

    def resolver(tipo, modelo, usuario=RECEP, manual=None):
        return resolver_precio(
            tipo,
            modelo_equipo_id=modelo,
            usuario=usuario,
            fecha=FECHA,
            manual=manual,
        )

    assert (resolver(unico, None).precio, resolver(unico, None).origen) == (
        Decimal("80000"),
        OrigenPrecio.CATALOGO,
    )
    con = resolver(TIPO, CON_PRECIO)
    assert (con.precio, con.origen, con.modelo_equipo_id) == (
        Decimal("60000"),
        OrigenPrecio.CATALOGO_MODELO,
        CON_PRECIO,
    )
    assert resolver(otros, None).origen is OrigenPrecio.OTROS
    # Sin precio para el modelo, o sin modelo tecnico: nunca el precio unico
    # (999) como respaldo silencioso.
    for modelo in (SIN_PRECIO, None):
        pendiente = resolver(TIPO, modelo)
        assert pendiente.origen is OrigenPrecio.PENDIENTE
        assert pendiente.precio == Decimal("0")
    manual = resolver(
        TIPO,
        SIN_PRECIO,
        COORD,
        PrecioManual(Decimal("70000.50"), " Cotizado "),
    )
    assert (manual.precio, manual.origen, manual.motivo) == (
        Decimal("70000.50"),
        OrigenPrecio.MANUAL,
        "Cotizado",
    )
    assert (manual.definido_por, manual.definido_en) == (COORD.id, FECHA)


@pytest.mark.parametrize(
    ("tipo", "modelo", "usuario", "manual", "texto"),
    [
        # Hay precio de catalogo: para bajarlo esta el ajuste comercial.
        (TIPO, CON_PRECIO, COORD, PrecioManual(Decimal("1"), "x"), "ajuste"),
        (
            TipoReparacion(
                id="TR-001",
                nombre="Bateria",
                precio=Decimal("1"),
                puntaje=1,
                garantia_dias=90,
            ),
            None,
            COORD,
            PrecioManual(Decimal("1"), "x"),
            "precio unico",
        ),
        (
            tipo_reparacion_otros(Decimal("1")),
            None,
            COORD,
            PrecioManual(Decimal("1"), "x"),
            "Otros",
        ),
        # Sin PRECIO_MANUAL (Recepcion y Tecnico, por defecto).
        (TIPO, SIN_PRECIO, RECEP, PrecioManual(Decimal("1"), "x"), "permiso"),
        (TIPO, SIN_PRECIO, TECH, PrecioManual(Decimal("1"), "x"), "permiso"),
        (TIPO, SIN_PRECIO, COORD, PrecioManual(Decimal("1"), "  "), "motivo"),
        (
            TIPO,
            SIN_PRECIO,
            COORD,
            PrecioManual(Decimal("1.001"), "x"),
            "decimales",
        ),
    ],
)
def test_el_precio_manual_se_rechaza_cuando_no_corresponde(
    tipo, modelo, usuario, manual, texto
):
    with pytest.raises(PrecondicionInvalidaError, match=texto):
        resolver_precio(
            tipo,
            modelo_equipo_id=modelo,
            usuario=usuario,
            fecha=FECHA,
            manual=manual,
        )


# --- Caminos de alta del trabajo ---------------------------------------------


def test_070_toma_el_precio_del_modelo_y_guarda_la_copia(cliente):
    orden_id = f.ok(_crear(cliente, CON_PRECIO))["id"]
    orden = f.ok(_agregar(cliente, orden_id))

    detalle = f.detalle(orden, "DET-001")
    assert detalle["precio"] == "60000"
    assert detalle["origen_precio"] == "CATALOGO_MODELO"
    assert detalle["modelo_equipo_id"] == CON_PRECIO
    assert detalle["nombre_trabajo"] == "Cambio de modulo"
    assert detalle["precio_pendiente"] is False
    # El de precio unico, como siempre.
    orden = f.ok(_agregar(cliente, orden_id, tipo_reparacion_id=f.BATERIA))
    unico = f.detalle(orden, "DET-002")
    assert (unico["precio"], unico["origen_precio"]) == ("80000", "CATALOGO")
    f.ok(_ingreso(cliente, orden_id))


def test_sin_precio_queda_pendiente_y_bloquea_el_comprobante(cliente):
    orden_id = f.ok(_crear(cliente, SIN_PRECIO))["id"]
    orden = f.ok(_agregar(cliente, orden_id))

    detalle = f.detalle(orden, "DET-001")
    assert detalle["origen_precio"] == "PENDIENTE"
    assert detalle["precio_pendiente"] is True
    assert detalle["precio"] == "0"
    assert "PRECIO_PENDIENTE" in _avisos(orden)
    acciones = orden["acciones_complementarias"]
    assert ("DEFINIR_PRECIO", "DET-001") in [
        (a["codigo"], a["detalle_id"]) for a in acciones
    ]
    assert "precio pendiente" in f.conflicto(_ingreso(cliente, orden_id))


def test_recepcion_no_fija_precios_al_agregar(cliente):
    orden_id = f.ok(_crear(cliente, SIN_PRECIO))["id"]
    # Recepcion no tiene PRECIO_MANUAL por defecto: el trabajo se carga sin
    # precio (pendiente) y lo define quien tiene el permiso.
    assert "permiso" in f.conflicto(
        _agregar(cliente, orden_id, precio="70000", precio_motivo="Cotizado")
    )
    assert "motivo" in f.conflicto(
        _agregar(cliente, orden_id, precio_motivo="Cotizado")
    )


def test_el_trabajo_inicial_usa_el_modelo_del_alta(cliente):
    con = f.ok(_crear(cliente, CON_PRECIO, trabajo_inicial=POR_MODELO))
    assert f.detalle(con, "DET-001")["precio"] == "60000"

    sin = f.ok(_crear(cliente, SIN_PRECIO, trabajo_inicial=POR_MODELO))
    assert f.detalle(sin, "DET-001")["origen_precio"] == "PENDIENTE"

    # Recepcion no puede fijar un precio manual: el alta no crea nada.
    respuesta = _crear(
        cliente,
        SIN_PRECIO,
        trabajo_inicial=POR_MODELO,
        trabajo_inicial_precio="70000",
        trabajo_inicial_motivo="Cotizado",
    )
    assert "permiso" in f.conflicto(respuesta)


def test_equipo_sin_modelo_tecnico_queda_pendiente(cliente):
    orden_id = f.ok(_crear(cliente, None))["id"]
    orden = f.ok(_agregar(cliente, orden_id))
    assert f.detalle(orden, "DET-001")["origen_precio"] == "PENDIENTE"


# --- Definir precio ----------------------------------------------------------


def test_definir_precio_manual_y_despues_el_comprobante(cliente):
    orden_id = f.ok(_crear(cliente, SIN_PRECIO))["id"]
    f.ok(_agregar(cliente, orden_id))

    assert "COORDINADOR_RMA" in f.conflicto(
        _precio(cliente, orden_id, precio="70000", motivo="Cotizado")
    )
    assert "motivo" in f.conflicto(
        _precio(cliente, orden_id, usuario=f.COORDINADOR, precio="70000")
    )
    orden = f.ok(
        _precio(
            cliente,
            orden_id,
            usuario=f.COORDINADOR,
            precio="70000",
            motivo="Cotizado con el proveedor",
        )
    )
    detalle = f.detalle(orden, "DET-001")
    assert detalle["precio"] == "70000"
    assert detalle["origen_precio"] == "MANUAL"
    assert detalle["precio_motivo"] == "Cotizado con el proveedor"
    assert detalle["precio_definido_por"] == f.COORDINADOR
    assert detalle["solo_precio"] is True
    assert detalle["version_definicion"] == 2
    # La definicion pendiente queda en el historial del trabajo.
    (anterior,) = detalle["definiciones_anteriores"]
    assert anterior["origen_precio"] == "PENDIENTE"
    assert "PRECIO_PENDIENTE" not in _avisos(orden)
    paso = orden["historial"][-1]
    assert (paso["referencia_id"], paso["accion"]) == (
        "ACC-REP-083",
        "DEFINIR_PRECIO_TRABAJO",
    )
    # Un precio ya definido no se vuelve a definir por aca.
    f.conflicto(
        _precio(
            cliente, orden_id, usuario=f.COORDINADOR, precio="1", motivo="x"
        )
    )
    orden = f.ok(_ingreso(cliente, orden_id))
    assert f.detalle(orden, "DET-001")["estado_autorizacion"] == "AUTORIZADO"


def test_tomar_el_precio_de_catalogo_cuando_se_carga(cliente, directorio):
    orden_id = f.ok(_crear(cliente, SIN_PRECIO))["id"]
    f.ok(_agregar(cliente, orden_id))

    assert "todavia no tiene precio" in f.conflicto(_precio(cliente, orden_id))

    _escribir_tipos(directorio, {CON_PRECIO: "60000", SIN_PRECIO: "65000"})
    orden = f.ok(_precio(cliente, orden_id))
    detalle = f.detalle(orden, "DET-001")
    assert (detalle["precio"], detalle["origen_precio"]) == (
        "65000",
        "CATALOGO_MODELO",
    )
    # Con precio de catalogo, un precio manual se rechaza.
    orden_id = f.ok(_crear(cliente, SIN_PRECIO))["id"]
    assert "ajuste" in f.conflicto(
        _agregar(cliente, orden_id, precio="1", precio_motivo="x")
    )


# --- Autorizacion del cliente y origenes no cobrables ------------------------


def _por_revision_con_pendiente(cliente) -> str:
    """Revision (075) del tecnico con un trabajo sin precio para el modelo:
    queda esperando la decision del cliente (129)."""
    from tests.fixtures import custodia

    orden_id = f.ok(_crear(cliente, SIN_PRECIO))["id"]
    f.ok(custodia.enviar_a_revision(cliente, orden_id))
    custodia.confirmar_recepcion(cliente, orden_id)
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Modulo roto."},
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/review/details",
            json={"usuario_id": f.TECNICO, "tipo_reparacion_id": POR_MODELO},
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/definition/finalize",
            json={"usuario_id": f.TECNICO},
        )
    )
    return orden_id


def test_el_precio_pendiente_bloquea_la_autorizacion(cliente):
    orden_id = _por_revision_con_pendiente(cliente)

    respuesta = f.decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"})
    assert "precio" in f.conflicto(respuesta, "PRECIO_PENDIENTE")

    f.ok(
        _precio(
            cliente,
            orden_id,
            usuario=f.COORDINADOR,
            precio="50000",
            motivo="Cotizado",
        )
    )
    orden = f.ok(f.decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
    assert f.detalle(orden, "DET-001")["estado_autorizacion"] == "AUTORIZADO"


def test_rt_interno_no_bloquea_y_conserva_el_precio_con_aviso(cliente):
    orden = f.ok(
        cliente.post(
            "/api/orders/rt-interno",
            json={
                "usuario_id": f.RECEPCION,
                "referencia_rt": "RT-1",
                "equipo": {
                    "modelo_tecnico_id": SIN_PRECIO,
                    "falla_reportada": "No enciende.",
                },
                "trabajo_inicial": POR_MODELO,
            },
        )
    )
    orden_id = orden["id"]
    assert f.detalle(orden, "DET-001")["origen_precio"] == "PENDIENTE"
    aviso = next(
        a
        for a in orden["situacion"]["avisos"]
        if a["codigo"] == "PRECIO_PENDIENTE"
    )
    assert "comprobante" not in aviso["titulo"]
    # Finalizar la definicion no exige precio en un origen no cobrable.
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/definition/finalize",
            json={"usuario_id": f.RECEPCION},
        )
    )
    # Con precio definido, un cambio de modelo no lo recalcula: avisa.
    f.ok(
        _precio(
            cliente,
            orden_id,
            usuario=f.COORDINADOR,
            precio="1000",
            motivo="Costo interno",
        )
    )
    orden = f.ok(
        cliente.put(
            f"/api/orders/{orden_id}/reception",
            json={
                "usuario_id": f.RECEPCION,
                "motivo": "Era otro modelo.",
                "equipo": {
                    "modelo_tecnico_id": CON_PRECIO,
                    "falla_reportada": "No enciende.",
                },
            },
        )
    )
    detalle = f.detalle(orden, "DET-001")
    assert (detalle["precio"], detalle["origen_precio"]) == ("1000", "MANUAL")
    assert detalle["precio_de_otro_modelo"] is True
    assert "PRECIO_OTRO_MODELO" in _avisos(orden)


# --- Cambio de modelo antes de autorizar (D-12.6) ----------------------------


def _cambiar_modelo(cliente, orden_id, modelo):
    return f.ok(
        cliente.put(
            f"/api/orders/{orden_id}/reception",
            json={
                "usuario_id": f.RECEPCION,
                "motivo": "Se cargo otro modelo.",
                "estado_fisico": "Sin golpes.",
                "funcionalidades_verificadas": True,
                "equipo": {
                    "modelo_tecnico_id": modelo,
                    "falla_reportada": "No enciende.",
                },
            },
        )
    )


def test_cambio_de_modelo_antes_de_autorizar_vuelve_a_determinar(cliente):
    orden_id = f.ok(_crear(cliente, CON_PRECIO))["id"]
    f.ok(_agregar(cliente, orden_id))
    f.ok(_agregar(cliente, orden_id, tipo_reparacion_id=f.BATERIA))

    orden = _cambiar_modelo(cliente, orden_id, SIN_PRECIO)
    detalle = f.detalle(orden, "DET-001")
    assert detalle["origen_precio"] == "PENDIENTE"
    assert detalle["modelo_equipo_id"] == SIN_PRECIO
    assert detalle["solo_precio"] is True
    # El de precio unico no depende del modelo.
    assert f.detalle(orden, "DET-002")["version_definicion"] == 1

    # Un precio manual no se traslada a otro modelo: toma el de catalogo.
    f.ok(
        _precio(
            cliente,
            orden_id,
            usuario=f.COORDINADOR,
            precio="70000",
            motivo="Cotizado",
        )
    )
    orden = _cambiar_modelo(cliente, orden_id, CON_PRECIO)
    detalle = f.detalle(orden, "DET-001")
    assert (detalle["precio"], detalle["origen_precio"]) == (
        "60000",
        "CATALOGO_MODELO",
    )
    assert detalle["version_definicion"] == 4
    assert orden["historial"][-1]["accion"] == (
        "REDETERMINAR_PRECIO_POR_CAMBIO_DE_MODELO"
    )


def test_despues_de_autorizar_se_conserva_el_precio(directorio):
    orden_id = None
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(data_dir=directorio))) as http:
        orden_id = f.ok(_crear(http, CON_PRECIO))["id"]
        f.ok(_agregar(http, orden_id))
        f.ok(_ingreso(http, orden_id))
    orden = f.repo_ordenes(directorio).obtener(orden_id)
    orden.equipo.modelo_tecnico_id = SIN_PRECIO

    misma = redeterminar_por_cambio_de_modelo(
        orden, tipos={POR_MODELO: TIPO}, usuario=RECEP, fecha=FECHA
    )
    (detalle,) = misma.reparaciones_detail
    assert (detalle.precio, detalle.origen_precio) == (
        Decimal("60000"),
        OrigenPrecio.CATALOGO_MODELO,
    )
    assert precio_de_otro_modelo(misma, detalle)


# --- Redefinicion, adicional y evaluacion ------------------------------------


def test_la_redefinicion_usa_la_misma_regla(directorio):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(data_dir=directorio))) as http:
        orden_id = f.ok(_crear(http, SIN_PRECIO))["id"]
        f.ok(_agregar(http, orden_id, tipo_reparacion_id=f.BATERIA))
    orden = f.repo_ordenes(directorio).obtener(orden_id)

    redefinida = aplicar_redefinicion(
        orden,
        detalle_id="DET-001",
        tipo_reparacion=TIPO,
        usuario=TECH,
        fecha=FECHA,
    )
    (detalle,) = redefinida.reparaciones_detail
    assert detalle.origen_precio is OrigenPrecio.PENDIENTE
    assert detalle.solo_precio is False
    (anterior,) = detalle.definiciones_anteriores
    assert anterior.origen_precio is OrigenPrecio.CATALOGO
    # El tecnico no fija precios sin PRECIO_MANUAL.
    with pytest.raises(PrecondicionInvalidaError, match="permiso"):
        aplicar_redefinicion(
            orden,
            detalle_id="DET-001",
            tipo_reparacion=TIPO,
            usuario=TECH,
            fecha=FECHA,
            precio_manual=PrecioManual(Decimal("1"), "x"),
        )


def test_el_adicional_del_tecnico_queda_pendiente(cliente):
    orden_id = f.definida(cliente)
    f.tomada(cliente, orden_id)
    f.iniciar(cliente, orden_id)
    adicional = {"usuario_id": f.TECNICO, "tipo_reparacion_id": POR_MODELO}
    assert "permiso" in f.conflicto(
        cliente.post(
            f"/api/orders/{orden_id}/details/additional",
            json={**adicional, "precio": "1000", "precio_motivo": "x"},
        )
    )
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/additional", json=adicional
        )
    )
    assert f.detalle(orden, "DET-002")["origen_precio"] == "PENDIENTE"
    assert "PRECIO_PENDIENTE" in _avisos(orden)
    respuesta = f.decidir(cliente, orden_id, {"DET-002": "AUTORIZADO"})
    f.conflicto(respuesta, "PRECIO_PENDIENTE")


def test_la_evaluacion_sigue_valiendo_tras_definir_solo_el_precio():
    base = dict(
        tipo_reparacion_id=POR_MODELO,
        puntaje=1,
        garantia_dias=90,
        reemplazada_en=FECHA,
        usuario_id=COORD.id,
    )
    detalle = ReparacionDetail(
        id="DET-001",
        tipo_reparacion_id=POR_MODELO,
        precio=Decimal("70000"),
        puntaje=1,
        garantia_dias=90,
        origen_precio=OrigenPrecio.MANUAL,
        solo_precio=True,
        definiciones_anteriores=[
            DefinicionAnteriorDetalle(
                **base,
                precio=Decimal("0"),
                origen_precio=OrigenPrecio.PENDIENTE,
            )
        ],
        evaluaciones=[
            EvaluacionTecnica(
                version_definicion=1,
                resultado=ResultadoEvaluacionTecnica.CONFIRMADO,
                usuario_id=TECH.id,
                fecha=FECHA,
            )
        ],
    )
    assert evaluacion_vigente(detalle) is not None
    # Una redefinicion tecnica posterior si la deja sin efecto.
    redefinido = detalle.model_copy(
        update={
            "solo_precio": False,
            "definiciones_anteriores": [
                *detalle.definiciones_anteriores,
                DefinicionAnteriorDetalle(
                    **base, precio=Decimal("70000"), solo_precio=True
                ),
            ],
        }
    )
    assert evaluacion_vigente(redefinido) is None


# --- Copia del nombre --------------------------------------------------------


def test_el_nombre_es_la_copia_y_el_anterior_lee_el_catalogo(
    cliente, directorio
):
    orden_id = f.ok(_crear(cliente, CON_PRECIO))["id"]
    f.ok(_agregar(cliente, orden_id))
    ruta = directorio / "catalogs" / "tipos_reparacion.json"
    tipos = json.loads(ruta.read_text("utf-8"))
    for tipo in tipos:
        if tipo["id"] == POR_MODELO:
            tipo["nombre"] = "Modulo (renombrado)"
    ruta.write_text(json.dumps(tipos), encoding="utf-8")

    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert f.detalle(orden, "DET-001")["tipo_reparacion_nombre"] == (
        "Cambio de modulo"
    )
    anterior = ReparacionDetail(
        id="DET-009",
        tipo_reparacion_id=POR_MODELO,
        precio=Decimal("1"),
        puntaje=1,
        garantia_dias=1,
    )
    assert nombre_del_trabajo(anterior, {POR_MODELO: "Del catalogo"}) == (
        "Del catalogo"
    )


def test_la_administracion_de_precios_y_modelos_es_de_postgresql(cliente):
    respuesta = cliente.put(
        f"/api/admin/repair-types/{POR_MODELO}/model-prices",
        json={
            "usuario_id": f.ADMINISTRADOR,
            "precios": [{"modelo_equipo_id": SIN_PRECIO, "precio": "1"}],
        },
    )
    assert "PostgreSQL" in f.conflicto(respuesta)
    respuesta = cliente.post(
        "/api/admin/device-models",
        json={
            "usuario_id": f.ADMINISTRADOR,
            "marca": "Apple",
            "modelo": "iPhone 18",
        },
    )
    assert "PostgreSQL" in f.conflicto(respuesta)
    modelos = f.ok(cliente.get("/api/admin/device-models"))
    assert modelos["editable"] is False
    assert CON_PRECIO in [m["id"] for m in modelos["modelos"]]
