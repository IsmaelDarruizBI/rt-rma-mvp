"""Catalogo de equipos de Ventas por HTTP: sincronizacion, alta y Ordenes.

El origen es el adaptador de archivo (un CSV con la estructura real de
``raw_TipoProducto`` y valores ficticios) o un proveedor simulado; ningun
test consulta Google Sheets.
"""

import json
import threading
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.application import sincronizar_catalogo_equipos
from app.application.documentos import pdf_documento_de_orden
from app.core.config import Settings
from app.domain.models import Equipo, MotivoBaja, ProductoInformado
from app.integraciones.catalogo import (
    CatalogoOrigenNoDisponibleError,
    LecturaCatalogo,
)
from app.main import create_app
from app.services import SincronizacionEnCursoError
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    COORDINADOR,
    RECEPCION,
    TECNICO,
    agregar,
    aprobar,
    conflicto,
    crear,
    ejecutar,
    finalizar,
    notificar_pagar_entregar,
    ok,
    sembrar,
    tomar,
)
from tests.fixtures.catalogo_ventas import (
    ID_12_MINI_GENERICO,
    ID_12_NEGRO,
    ID_12_PRO_MAX_VIOLETA,
    ID_SE_ROJO,
    escribir_csv,
    fila,
    filas_base,
)

IMEI = "356000000000017"  # ficticio


@pytest.fixture
def entorno(tmp_path):
    sembrar(tmp_path, "10")
    csv = escribir_csv(tmp_path / "tipo_producto.csv")
    app = create_app(
        Settings(
            data_dir=tmp_path,
            catalogo_origen="archivo",
            catalogo_archivo=csv,
        )
    )
    with TestClient(app) as cliente:
        yield cliente, app, csv


def _sincronizar(cliente, usuario=ADMINISTRADOR):
    return cliente.post(
        "/api/catalogs/equipment/sync", params={"usuario_id": usuario}
    )


def _catalogo(cliente) -> dict:
    return ok(cliente.get("/api/catalogs/equipment"))


def _ids_ofrecidos(catalogo: dict) -> set[str]:
    return {
        color["tipo_producto_id"]
        for modelo in catalogo["modelos"]
        for variante in modelo["variantes"]
        for capacidad in variante["capacidades"]
        for color in capacidad["colores"]
    }


def _alta(cliente, equipo: dict):
    return cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre_apellido": "Cliente", "telefono": "341-1"},
            "equipo": {"falla_reportada": "No carga.", **equipo},
        },
    )


def _alta_catalogo(cliente, tipo_id=ID_12_PRO_MAX_VIOLETA) -> dict:
    return ok(_alta(cliente, {"tipo_producto_id": tipo_id, "imei": IMEI}))


def _copia(app):
    return app.state.contexto.catalogo_equipos


class ProveedorSimulado:
    descripcion = "Proveedor simulado"

    def __init__(self, resultado=None, error=None, bloqueo=None):
        self.resultado = resultado
        self.error = error
        self.bloqueo = bloqueo
        self.llamadas = 0

    def leer(self, filtro):
        self.llamadas += 1
        if self.bloqueo:
            self.bloqueo.wait(5)
        if self.error:
            raise self.error
        return self.resultado


def _con_proveedor(app, proveedor):
    app.state.contexto = replace(
        app.state.contexto, proveedor_catalogo=proveedor
    )


# --- Sin sincronizar ---------------------------------------------------------


def test_sin_sincronizar_el_selector_esta_vacio_y_se_carga_a_mano(entorno):
    cliente, _, _ = entorno
    catalogo = _catalogo(cliente)
    assert catalogo["modelos"] == []
    estado = catalogo["estado"]
    assert estado["habilitado"] and estado["sincronizable"]
    assert estado["ultima"] is None and estado["elegibles"] == 0
    assert estado["origen"] == "Archivo CSV (tipo_producto.csv)"
    assert estado["filtro"] == "subcategoría: IPHONE USADOS"

    orden = ok(cliente.get(f"/api/orders/{crear(cliente)}"))
    assert orden["equipo"]["tipo_producto_id"] is None
    assert orden["equipo"]["marca"] == "Apple"


# --- Sincronizacion manual ---------------------------------------------------


def test_sincronizacion_manual_registra_fecha_y_resultado(entorno):
    cliente, app, _ = entorno
    resultado = ok(_sincronizar(cliente))
    assert resultado["resultado"] == "EXITOSA"
    assert resultado["usuario_id"] == ADMINISTRADOR
    assert resultado["iniciada_en"] and resultado["finalizada_en"]
    assert {
        clave: resultado[clave]
        for clave in (
            "leidos", "filtrados", "nuevos", "vigentes", "elegibles",
        )
    } == {
        "leidos": 14, "filtrados": 12, "nuevos": 12, "vigentes": 12,
        "elegibles": 10,
    }  # fmt: skip

    catalogo = _catalogo(cliente)
    assert catalogo["estado"]["ultima"]["id"] == resultado["id"]
    assert catalogo["estado"]["ultima_exitosa"]["id"] == resultado["id"]
    assert len(_ids_ofrecidos(catalogo)) == 10
    assert "iphone_usados" not in _ids_ofrecidos(catalogo)
    assert len(_copia(app).listar_productos()) == 12


def test_repetir_la_sincronizacion_no_duplica(entorno):
    cliente, app, _ = entorno
    ok(_sincronizar(cliente))
    segunda = ok(_sincronizar(cliente, COORDINADOR))
    assert (segunda["nuevos"], segunda["sin_cambios"]) == (0, 12)
    ids = [p.tipo_producto_id for p in _copia(app).listar_productos()]
    assert len(ids) == len(set(ids)) == 12
    assert len(_copia(app).listar_sincronizaciones()) == 2


@pytest.mark.parametrize("usuario", [RECEPCION, TECNICO])
def test_solo_administracion_o_coordinacion_sincronizan(entorno, usuario):
    cliente, app, _ = entorno
    conflicto(_sincronizar(cliente, usuario))
    assert _copia(app).listar_sincronizaciones() == []


def test_si_el_origen_falla_se_conserva_el_ultimo_catalogo(entorno):
    cliente, app, _ = entorno
    exitosa = ok(_sincronizar(cliente))
    antes = _copia(app).listar_productos()
    _con_proveedor(
        app,
        ProveedorSimulado(
            error=CatalogoOrigenNoDisponibleError(
                "No se pudo conectar con Google Sheets."
            )
        ),
    )

    respuesta = _sincronizar(cliente)
    assert respuesta.status_code == 503
    error = respuesta.json()["error"]
    assert error["codigo"] == "CATALOGO_ORIGEN_NO_DISPONIBLE"
    assert "Se conserva el catálogo anterior" in error["mensaje"]

    assert _copia(app).listar_productos() == antes
    estado = _catalogo(cliente)["estado"]
    assert estado["ultima"]["resultado"] == "FALLIDA"
    assert estado["ultima"]["mensaje"] == (
        "No se pudo conectar con Google Sheets."
    )
    assert estado["ultima_exitosa"]["id"] == exitosa["id"]
    # El alta sigue usando la copia.
    assert _alta_catalogo(cliente)["equipo"]["capacidad"] == "256 GB"


def test_datos_no_confiables_se_rechazan_sin_tocar_la_copia(entorno):
    cliente, app, csv = entorno
    ok(_sincronizar(cliente))
    antes = _copia(app).listar_productos()

    repetido = fila("12", "Nada", "128gb", "black")
    escribir_csv(csv, [*filas_base(), repetido])
    mensaje = conflicto(_sincronizar(cliente), "CATALOGO_ORIGEN_INVALIDO")
    assert ID_12_NEGRO in mensaje

    csv.write_text("tp_id,tp_modelo\nx,y\n", encoding="utf-8")
    assert "faltan columnas" in conflicto(
        _sincronizar(cliente), "CATALOGO_ORIGEN_INVALIDO"
    )

    escribir_csv(csv, [fila("12", "Nada", "128gb", "black", subcat="OTRA")])
    assert "ningún producto" in conflicto(
        _sincronizar(cliente), "CATALOGO_ORIGEN_INVALIDO"
    )

    assert _copia(app).listar_productos() == antes
    resultados = [
        s.resultado.value for s in _copia(app).listar_sincronizaciones()
    ]
    assert resultados == ["EXITOSA", "RECHAZADA", "RECHAZADA", "RECHAZADA"]


def test_sin_origen_configurado_no_se_sincroniza(entorno):
    cliente, app, _ = entorno
    _con_proveedor(app, None)
    assert "No hay un origen" in conflicto(_sincronizar(cliente))
    assert _catalogo(cliente)["estado"]["sincronizable"] is False


def test_una_sincronizacion_por_vez(entorno):
    _, app, _ = entorno
    bloqueo = threading.Event()
    lento = ProveedorSimulado(
        resultado=LecturaCatalogo(
            productos=(
                ProductoInformado(
                    tipo_producto_id="A",
                    descripcion="A",
                    marca="Apple",
                    modelo="iPhone 12",
                    capacidad="128 GB",
                    color="Black",
                ),
            ),
            leidos=1,
            filtrados=1,
        ),
        bloqueo=bloqueo,
    )
    _con_proveedor(app, lento)
    contexto = app.state.contexto
    hilo = threading.Thread(
        target=sincronizar_catalogo_equipos,
        args=(contexto,),
        kwargs={"usuario_id": ADMINISTRADOR},
    )
    hilo.start()
    while lento.llamadas == 0:
        pass
    with pytest.raises(SincronizacionEnCursoError):
        sincronizar_catalogo_equipos(contexto, usuario_id=ADMINISTRADOR)
    bloqueo.set()
    hilo.join(5)
    assert [p.tipo_producto_id for p in _copia(app).listar_productos()] == [
        "A"
    ]


# --- Alta con el catalogo ----------------------------------------------------


def test_alta_con_un_producto_del_catalogo(entorno, tmp_path):
    cliente, _, _ = entorno
    ok(_sincronizar(cliente))
    orden = ok(
        _alta(
            cliente,
            {
                "tipo_producto_id": ID_12_PRO_MAX_VIOLETA,
                # Lo que mande la pantalla no pisa al catalogo.
                "marca": "Otra",
                "modelo": "Otro",
                "imei": IMEI,
            },
        )
    )
    equipo = orden["equipo"]
    assert {
        clave: equipo[clave]
        for clave in (
            "tipo_producto_id", "marca", "modelo", "variante", "capacidad",
            "color", "imei", "numero_serie",
        )
    } == {
        "tipo_producto_id": ID_12_PRO_MAX_VIOLETA,
        "marca": "Apple",
        "modelo": "iPhone 12",
        "variante": "Pro Max",
        "capacidad": "256 GB",
        "color": "Deep Purple",
        "imei": IMEI,
        "numero_serie": None,
    }  # fmt: skip
    # El ID fisico es de RMA, no el tp_id.
    assert equipo["id"].startswith("EQP-")

    guardada = json.loads(
        (tmp_path / "ordenes" / f"{orden['id']}.json").read_text("utf-8")
    )
    assert guardada["equipo"]["tipo_producto_id"] == ID_12_PRO_MAX_VIOLETA
    (resumen,) = ok(cliente.get("/api/orders"))
    assert resumen["equipo"] == "Apple iPhone 12 Pro Max 256 GB Deep Purple"


def test_el_alta_nunca_consulta_el_origen(entorno):
    cliente, app, _ = entorno
    ok(_sincronizar(cliente))
    espia = ProveedorSimulado(error=AssertionError("no debe leer"))
    _con_proveedor(app, espia)
    _alta_catalogo(cliente)
    _catalogo(cliente)
    assert espia.llamadas == 0


def test_el_color_generico_queda_sin_color(entorno):
    cliente, _, _ = entorno
    ok(_sincronizar(cliente))
    equipo = _alta_catalogo(cliente, ID_12_MINI_GENERICO)["equipo"]
    assert (equipo["variante"], equipo["capacidad"], equipo["color"]) == (
        "Mini",
        "128 GB",
        None,
    )
    assert equipo["tipo_producto_id"] == ID_12_MINI_GENERICO


@pytest.mark.parametrize("tipo_id", ["no-existe", "iphone_usados"])
def test_un_producto_inexistente_o_no_elegible_se_rechaza(entorno, tipo_id):
    cliente, _, _ = entorno
    ok(_sincronizar(cliente))
    conflicto(
        _alta(cliente, {"tipo_producto_id": tipo_id}),
        "PRODUCTO_CATALOGO_NO_DISPONIBLE",
    )
    assert ok(cliente.get("/api/orders")) == []


def test_sin_producto_ni_marca_y_modelo_el_pedido_es_invalido(entorno):
    cliente, _, _ = entorno
    respuesta = _alta(cliente, {"marca": "Apple"})
    assert respuesta.status_code == 422
    assert "elegilo del catálogo" in respuesta.json()["error"]["mensaje"]


def test_rt_interno_tambien_puede_usar_el_catalogo(entorno):
    cliente, _, _ = entorno
    ok(_sincronizar(cliente))
    orden = ok(
        cliente.post(
            "/api/orders/rt-interno",
            json={
                "usuario_id": RECEPCION,
                "referencia_rt": "RT-FICTICIA-1",
                "equipo": {
                    "tipo_producto_id": ID_SE_ROJO,
                    "falla_reportada": "Pantalla rota.",
                },
            },
        )
    )
    assert orden["equipo"]["modelo"] == "iPhone SE 2020"
    assert orden["equipo"]["variante"] is None


# --- Historia y compatibilidad -----------------------------------------------


def test_un_producto_referenciado_que_ventas_borra_no_se_elimina(entorno):
    cliente, app, csv = entorno
    ok(_sincronizar(cliente))
    orden_id = _alta_catalogo(cliente, ID_12_NEGRO)["id"]

    escribir_csv(csv, [f for f in filas_base() if f and f[0] != ID_12_NEGRO])
    resultado = ok(_sincronizar(cliente))
    assert resultado["dados_de_baja"] == 1

    producto = _copia(app).obtener_producto(ID_12_NEGRO)
    assert producto is not None and not producto.vigente
    assert producto.motivo_baja == MotivoBaja.NO_INFORMADO
    assert ID_12_NEGRO not in _ids_ofrecidos(_catalogo(cliente))
    equipo = ok(cliente.get(f"/api/orders/{orden_id}"))["equipo"]
    assert (equipo["tipo_producto_id"], equipo["capacidad"]) == (
        ID_12_NEGRO,
        "128 GB",
    )
    conflicto(
        _alta(cliente, {"tipo_producto_id": ID_12_NEGRO}),
        "PRODUCTO_CATALOGO_NO_DISPONIBLE",
    )


def test_las_ordenes_anteriores_al_catalogo_siguen_cargando(entorno, tmp_path):
    cliente, _, _ = entorno
    orden_id = crear(cliente)
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    datos = json.loads(ruta.read_text("utf-8"))
    for campo in ("tipo_producto_id", "variante", "capacidad", "color"):
        datos["equipo"].pop(campo)
        for version in datos.get("recepcion", {}).get(
            "versiones_anteriores", []
        ):
            version["equipo"].pop(campo, None)
    ruta.write_text(json.dumps(datos), "utf-8")

    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    assert orden["equipo"]["marca"] == "Apple"
    assert orden["equipo"]["modelo"] == "iPhone 14"
    assert orden["equipo"]["tipo_producto_id"] is None
    (resumen,) = ok(cliente.get("/api/orders"))
    assert resumen["equipo"] == "Apple iPhone 14"
    anterior = Equipo(
        id="EQ-1", marca="Samsung", modelo="A54", falla_reportada="x"
    )
    assert anterior.nombre == anterior.descripcion == "Samsung A54"


def _corregir(cliente, orden_id, equipo):
    return cliente.put(
        f"/api/orders/{orden_id}/reception",
        json={
            "usuario_id": RECEPCION,
            "estado_fisico": "Sin golpes.",
            "equipo": {"falla_reportada": "No carga.", **equipo},
        },
    )


def test_corregir_los_datos_del_ingreso(entorno, tmp_path):
    cliente, app, _ = entorno
    ok(_sincronizar(cliente))
    orden_id = _alta_catalogo(cliente)["id"]

    # Otro producto del catalogo.
    equipo = ok(
        _corregir(cliente, orden_id, {"tipo_producto_id": ID_SE_ROJO})
    )["equipo"]
    assert (equipo["tipo_producto_id"], equipo["modelo"]) == (
        ID_SE_ROJO,
        "iPhone SE 2020",
    )

    # Sin la copia (por ejemplo, despues de un redespliegue del UAT), el
    # mismo producto conserva sus datos: corregir el IMEI no depende del
    # catalogo.
    _copia(app).ruta.unlink()
    orden = ok(
        _corregir(
            cliente,
            orden_id,
            {"tipo_producto_id": ID_SE_ROJO, "imei": "356000000000025"},
        )
    )
    assert orden["equipo"]["imei"] == "356000000000025"
    assert orden["equipo"]["color"] == "Red"

    # A mano: deja de estar vinculado al catalogo.
    orden = ok(
        _corregir(cliente, orden_id, {"marca": "Apple", "modelo": "iPhone X"})
    )
    assert orden["equipo"]["tipo_producto_id"] is None
    assert orden["equipo"]["capacidad"] is None
    versiones = orden["recepcion"]["versiones_anteriores"]
    assert [v["equipo"]["tipo_producto_id"] for v in versiones] == [
        ID_12_PRO_MAX_VIOLETA,
        ID_SE_ROJO,
        ID_SE_ROJO,
    ]


# --- Happy Paths con un equipo del catalogo ----------------------------------


def test_hp_rep_001_y_003_con_un_equipo_del_catalogo(entorno):
    cliente, _, _ = entorno
    ok(_sincronizar(cliente))
    orden_id = _alta_catalogo(cliente)["id"]
    agregar(cliente, orden_id, BATERIA)
    finalizar(cliente, orden_id)
    tomar(cliente, orden_id, TECNICO)
    ejecutar(cliente, orden_id, "DET-001", BATERIA)
    ok(aprobar(cliente, orden_id, "DET-001"))
    entregada = notificar_pagar_entregar(cliente, orden_id)
    assert entregada["estado_workflow"] == "ENTREGADA"
    assert entregada["equipo"]["tipo_producto_id"] == ID_12_PRO_MAX_VIOLETA

    # Cada documento guarda su copia del equipo, con el producto.
    documentos = ok(cliente.get(f"/api/orders/{orden_id}/documents"))
    equipos = [
        d["contenido"]["equipo"]
        for d in documentos["emitidos"]
        if "equipo" in d["contenido"]
    ]
    assert equipos and all(
        e["tipo_producto_id"] == ID_12_PRO_MAX_VIOLETA
        and e["capacidad"] == "256 GB"
        for e in equipos
    )

    # HP-REP-003: la garantia es el mismo equipo fisico y el mismo producto.
    garantia = ok(
        cliente.post(
            f"/api/orders/{orden_id}/warranty-rma",
            json={"usuario_id": RECEPCION, "detalle_origen_ids": ["DET-001"]},
        )
    )
    assert garantia["equipo"] == entregada["equipo"]


def test_el_pdf_muestra_modelo_variante_capacidad_y_color(entorno):
    cliente, app, _ = entorno
    ok(_sincronizar(cliente))
    orden_id = _alta_catalogo(cliente)["id"]
    agregar(cliente, orden_id, BATERIA)
    finalizar(cliente, orden_id)
    orden = app.state.contexto.ordenes.obtener(orden_id)
    (documento, *_) = orden.documentos.emitidos
    _, pdf = pdf_documento_de_orden(app.state.contexto, orden_id, documento.id)
    texto = pdf.decode("cp1252")
    assert "(Apple iPhone 12 Pro Max) Tj" in texto
    assert "(256 GB) Tj" in texto and "(Deep Purple) Tj" in texto
    assert f"({IMEI}) Tj" in texto
