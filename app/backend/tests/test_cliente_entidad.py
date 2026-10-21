"""Entidad Cliente: id, dni, nombre_apellido, telefono y email (UAT-010).

El ``id`` interno es la identidad (nunca el DNI). ``nombre_apellido`` es el
nombre completo tal como lo carga Recepcion o lo devuelve una fuente
autorizada: no se separa. Compatibilidad: las Ordenes y documentos
anteriores guardaron el nombre en ``nombre`` y se leen tal cual; la API
sigue aceptando ``nombre`` al crear. Con DNI, un cliente que ya existe se
reutiliza (por su ``id``) y nunca se duplica.
"""

import json
import threading

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import Cliente
from app.main import create_app
from tests.fixtures.api_salidas import (
    BATERIA,
    RECEPCION,
    agregar,
    conflicto,
    generar_ingreso,
    ok,
    repo_ordenes,
    sembrar,
)

DNI = "30123456"
EQUIPO = {"marca": "Apple", "modelo": "iPhone 14", "falla_reportada": "X."}


@pytest.fixture
def cliente(tmp_path):
    sembrar(tmp_path)
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def _alta(cliente, **datos):
    """``POST /api/orders`` (la respuesta, sin validar)."""
    datos = {"telefono": "341-555", **datos}
    return cliente.post(
        "/api/orders",
        json={"usuario_id": RECEPCION, "cliente": datos, "equipo": EQUIPO},
    )


def _buscar(cliente, dni=DNI):
    return ok(
        cliente.get(
            "/api/clients/lookup",
            params={"dni": dni, "usuario_id": RECEPCION},
        )
    )


def _cantidad(tmp_path) -> int:
    return len(list((tmp_path / "ordenes").glob("*.json")))


# --- Cliente nuevo ----------------------------------------------------------


def test_cliente_nuevo_con_nombre_apellido_y_dni(cliente, tmp_path):
    orden = ok(
        _alta(cliente, nombre_apellido=" GOMEZ Ana María ", dni="30.123.456")
    )

    assert orden["cliente"] == {
        "id": orden["cliente"]["id"],
        "dni": DNI,
        "nombre_apellido": "GOMEZ Ana María",
        "telefono": "341-555",
        "email": None,
    }
    assert orden["cliente"]["id"].startswith("CLI-")
    # Se guarda una sola representacion del nombre.
    guardado = json.loads(
        (tmp_path / "ordenes" / f"{orden['id']}.json").read_text(
            encoding="utf-8"
        )
    )["cliente"]
    assert set(guardado) == {
        "id",
        "dni",
        "nombre_apellido",
        "telefono",
        "email",
    }
    # El listado, el comprobante y su PDF muestran el nombre tal cual.
    (fila,) = ok(cliente.get("/api/orders"))
    assert fila["cliente_nombre"] == "GOMEZ Ana María"
    agregar(cliente, orden["id"], BATERIA)
    generar_ingreso(cliente, orden["id"])
    (ingreso,) = ok(cliente.get(f"/api/orders/{orden['id']}/documents"))[
        "emitidos"
    ]
    assert ingreso["contenido"]["cliente"]["nombre_apellido"] == (
        "GOMEZ Ana María"
    )
    pdf = cliente.get(
        f"/api/orders/{orden['id']}/documents/{ingreso['id']}/pdf"
    )
    assert pdf.status_code == 200
    assert b"GOMEZ Ana" in pdf.content


def test_la_api_acepta_la_clave_anterior_nombre(cliente):
    """Compatibilidad de escritura con un consumidor anterior."""
    orden = ok(_alta(cliente, nombre="Ana Gomez"))

    assert orden["cliente"]["nombre_apellido"] == "Ana Gomez"
    assert "nombre" not in orden["cliente"]
    # Si vienen las dos, manda la nueva.
    ambas = ok(_alta(cliente, nombre_apellido="Ana Gómez", nombre="viejo"))
    assert ambas["cliente"]["nombre_apellido"] == "Ana Gómez"


@pytest.mark.parametrize(
    ("datos", "status", "texto"),
    [
        ({"nombre_apellido": "   "}, 409, "Falta el nombre y apellido"),
        ({"nombre_apellido": "x" * 201}, 422, "nombre_apellido"),
        ({"telefono": "1"}, 422, "nombre_apellido"),
        ({"nombre_apellido": "Ana", "dni": "12A"}, 409, "7 u 8"),
    ],
)
def test_alta_valida_los_datos(cliente, tmp_path, datos, status, texto):
    respuesta = _alta(cliente, **datos)

    assert respuesta.status_code == status
    assert texto in respuesta.json()["error"]["mensaje"]
    assert _cantidad(tmp_path) == 0


# --- Compatibilidad historica ----------------------------------------------


def test_ordenes_y_documentos_anteriores_siguen_cargando(cliente, tmp_path):
    """JSON anterior: el cliente con ``nombre`` (Orden y documento)."""
    orden = ok(_alta(cliente, nombre_apellido="Ana Gomez"))
    agregar(cliente, orden["id"], BATERIA)
    generar_ingreso(cliente, orden["id"])
    ruta = tmp_path / "ordenes" / f"{orden['id']}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    anterior = {"id": "CLI-ANTERIOR", "nombre": "Ana Gomez", "telefono": "1"}
    datos["cliente"] = dict(anterior)
    for documento in datos["documentos"]["emitidos"]:
        documento["contenido"]["cliente"] = dict(anterior)
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    leida = ok(cliente.get(f"/api/orders/{orden['id']}"))
    (fila,) = ok(cliente.get("/api/orders"))
    (documento,) = ok(cliente.get(f"/api/orders/{orden['id']}/documents"))[
        "emitidos"
    ]

    assert leida["cliente"] == {
        "id": "CLI-ANTERIOR",
        "dni": None,
        "nombre_apellido": "Ana Gomez",
        "telefono": "1",
        "email": None,
    }
    assert fila["cliente_nombre"] == "Ana Gomez"
    # El documento emitido conserva su dato: el mismo nombre.
    assert documento["contenido"]["cliente"]["nombre_apellido"] == "Ana Gomez"
    assert documento["contenido"]["cliente"]["id"] == "CLI-ANTERIOR"


def test_la_lectura_anterior_no_pisa_el_campo_nuevo():
    anterior = Cliente.model_validate(
        {"id": "C", "nombre": "Ana Gomez", "telefono": "1"}
    )
    nuevo = Cliente.model_validate(
        {
            "id": "C",
            "nombre_apellido": "Ana Gómez",
            "nombre": "x",
            "telefono": "1",
        }
    )

    assert anterior.nombre_apellido == "Ana Gomez"
    assert nuevo.nombre_apellido == "Ana Gómez"
    assert "nombre" not in anterior.model_dump()


# --- Busqueda ----------------------------------------------------------------


def test_cliente_existente_se_encuentra_con_su_nombre(cliente):
    ok(_alta(cliente, nombre_apellido="Ana Gomez", dni=DNI))

    (conocido,) = _buscar(cliente)["conocidos"]

    assert conocido["nombre_apellido"] == "Ana Gomez"


def test_un_cliente_anterior_se_encuentra_por_dni(cliente, tmp_path):
    orden = ok(_alta(cliente, nombre="Ana Gomez"))
    repo = repo_ordenes(tmp_path)
    anterior = repo.obtener(orden["id"])
    anterior.cliente.dni = DNI
    repo.guardar(anterior)

    (conocido,) = _buscar(cliente)["conocidos"]

    assert conocido["nombre_apellido"] == "Ana Gomez"


# --- Reutilizacion y correccion --------------------------------------------


def test_reutilizar_y_corregir_el_nombre_completo(cliente):
    primera = ok(_alta(cliente, nombre_apellido="ana gomes", dni=DNI))
    cliente_id = primera["cliente"]["id"]

    segunda = ok(
        _alta(
            cliente,
            id=cliente_id,
            nombre_apellido="Ana Gómez",
            telefono="341-999",
            email="ana@example.com",
            dni=DNI,
        )
    )

    assert segunda["cliente"]["id"] == cliente_id
    assert segunda["cliente"]["nombre_apellido"] == "Ana Gómez"
    # La Orden anterior conserva lo que se registro entonces.
    vieja = ok(cliente.get(f"/api/orders/{primera['id']}"))
    assert vieja["cliente"]["nombre_apellido"] == "ana gomes"
    # La busqueda devuelve el dato mas reciente, con las dos Ordenes.
    (conocido,) = _buscar(cliente)["conocidos"]
    assert (conocido["nombre_apellido"], conocido["telefono"]) == (
        "Ana Gómez",
        "341-999",
    )
    assert (conocido["email"], conocido["ordenes"]) == ("ana@example.com", 2)


def test_corregir_el_dni_de_un_cliente(cliente):
    """Reutilizado con otro DNI que nadie tiene: es una correccion."""
    primera = ok(_alta(cliente, nombre_apellido="Ana Gomez", dni=DNI))
    cliente_id = primera["cliente"]["id"]

    segunda = ok(
        _alta(
            cliente,
            id=cliente_id,
            nombre_apellido="Ana Gomez",
            dni="30123457",
        )
    )

    assert segunda["cliente"]["id"] == cliente_id
    (conocido,) = _buscar(cliente, "30123457")["conocidos"]
    assert conocido["cliente_id"] == cliente_id


# --- Prevencion de duplicados ----------------------------------------------


def test_un_dni_existente_no_crea_otro_cliente(cliente, tmp_path):
    ok(_alta(cliente, nombre_apellido="Ana Gomez", dni=DNI))

    respuesta = _alta(cliente, nombre_apellido="Ana María Gomez", dni=DNI)

    mensaje = conflicto(respuesta, "CLIENTE_EXISTENTE")
    assert "Ana Gomez" in mensaje and "Buscar datos" in mensaje
    assert _cantidad(tmp_path) == 1


def test_no_se_reutiliza_otro_cliente_con_un_dni_ajeno(cliente, tmp_path):
    ok(_alta(cliente, nombre_apellido="Ana Gomez", dni=DNI))
    otra = ok(_alta(cliente, nombre_apellido="Luis Perez", dni="30999888"))

    respuesta = _alta(
        cliente,
        id=otra["cliente"]["id"],
        nombre_apellido="Luis Perez",
        dni=DNI,
    )

    conflicto(respuesta, "CLIENTE_EXISTENTE")
    assert _cantidad(tmp_path) == 2


def test_sin_dni_no_hay_como_reconocerlo(cliente):
    """Sin DNI se crea un cliente nuevo (no se compara por nombre)."""
    primero = ok(_alta(cliente, nombre_apellido="Ana Gomez"))
    segundo = ok(_alta(cliente, nombre_apellido="Ana Gomez"))

    assert primero["cliente"]["id"] != segundo["cliente"]["id"]


def test_duplicados_anteriores_se_pueden_seguir_usando(cliente, tmp_path):
    """Dos clientes anteriores con el mismo DNI: cualquiera se reutiliza."""
    uno = ok(_alta(cliente, nombre_apellido="Ana Gomez", dni=DNI))
    otro = ok(_alta(cliente, nombre_apellido="Ana M. Gomez"))
    repo = repo_ordenes(tmp_path)
    anterior = repo.obtener(otro["id"])
    anterior.cliente.dni = DNI
    repo.guardar(anterior)

    for elegido in (uno, otro):
        nueva = ok(
            _alta(
                cliente,
                id=elegido["cliente"]["id"],
                nombre_apellido="Ana Gomez",
                dni=DNI,
            )
        )
        assert nueva["cliente"]["id"] == elegido["cliente"]["id"]


def test_dos_altas_simultaneas_con_el_mismo_dni(tmp_path):
    """La comprobacion ocurre en la seccion critica del alta: una sola."""
    sembrar(tmp_path)
    app = create_app(Settings(data_dir=tmp_path))
    resultados = []
    largada = threading.Barrier(4)

    with TestClient(app) as cliente:

        def alta(numero):
            largada.wait()
            resultados.append(
                _alta(
                    cliente, nombre_apellido=f"Ana Gomez {numero}", dni=DNI
                ).status_code
            )

        hilos = [
            threading.Thread(target=alta, args=(numero,))
            for numero in range(4)
        ]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=60)

    assert sorted(resultados) == [201, 409, 409, 409]
    assert _cantidad(tmp_path) == 1
