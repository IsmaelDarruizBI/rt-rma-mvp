"""Busqueda de clientes por DNI (UAT-010).

Primero nuestras Ordenes; solo si el cliente no esta y hay una fuente
externa AUTORIZADA configurada, esa fuente, con limite de consultas. Hoy
no hay ninguna: CUIT Online protege los nombres (contenido de pago
codificado) y no se implementa un extractor que eluda esa proteccion. Por
eso la fuente externa se prueba con una fuente simulada que cumple el
contrato (``app.integraciones.FuentePersonas``), no con HTML.

La busqueda no guarda nada: Recepcion revisa, corrige y recien al crear la
Orden se guardan el DNI y los datos.
"""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.integraciones import (
    EstadoFuente,
    LimitadorConsultas,
    PersonaExterna,
    ResultadoFuente,
)
from app.main import create_app
from app.services import PrecondicionInvalidaError, normalizar_dni
from tests.fixtures.api_salidas import (
    RECEPCION,
    TECNICO,
    conflicto,
    ok,
    repo_ordenes,
    sembrar,
)

DNI = "30123456"


class FuenteSimulada:
    """Fuente externa autorizada simulada: cuenta las consultas."""

    nombre = "fuente-simulada"

    def __init__(self, resultado=None, error=None):
        self.resultado = resultado
        self.error = error
        self.consultas = []

    def consultar(self, dni):
        self.consultas.append(dni)
        if self.error:
            raise self.error
        return self.resultado


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def armar(tmp_path):
    """Un cliente HTTP con la fuente externa (o ninguna) que se pida."""
    sembrar(tmp_path)
    clientes = []

    def _armar(fuente=None, limitador=None):
        app = create_app(Settings(data_dir=tmp_path))
        app.state.contexto = replace(
            app.state.contexto,
            fuente_personas=fuente,
            limitador_personas=limitador
            or LimitadorConsultas(intervalo_minimo=0, maximo_por_minuto=100),
        )
        cliente = TestClient(app)
        clientes.append(cliente)
        return cliente

    yield _armar
    for cliente in clientes:
        cliente.close()


def _buscar(cliente, dni=DNI, usuario=RECEPCION):
    return cliente.get(
        "/api/clients/lookup", params={"dni": dni, "usuario_id": usuario}
    )


def _crear(cliente, nombre="Ana Gomez", dni=DNI, cliente_id=None):
    datos = {"nombre_apellido": nombre, "telefono": "341-555", "dni": dni}
    if cliente_id:
        datos["id"] = cliente_id
    return ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": RECEPCION,
                "cliente": datos,
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 14",
                    "falla_reportada": "No carga.",
                },
            },
        )
    )


def _archivos(tmp_path):
    return sorted(p.name for p in (tmp_path / "ordenes").glob("*.json"))


# --- DNI -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "dni"),
    [
        ("30123456", "30123456"),
        ("30.123.456", "30123456"),
        (" 7 123 456 ", "7123456"),
        ("07.123.456", "7123456"),
    ],
)
def test_normaliza_el_dni(texto, dni):
    assert normalizar_dni(texto) == dni


@pytest.mark.parametrize("texto", ["", "123456", "123456789", "30A23456"])
def test_rechaza_un_dni_invalido(texto):
    with pytest.raises(PrecondicionInvalidaError):
        normalizar_dni(texto)


def test_un_dni_invalido_no_se_consulta(armar):
    fuente = FuenteSimulada()
    cliente = armar(fuente)

    assert "7 u 8 digitos" in conflicto(_buscar(cliente, dni="12A45678"))
    assert fuente.consultas == []


def test_solo_recepcion_o_administracion_buscan(armar):
    cliente = armar()

    conflicto(_buscar(cliente, usuario=TECNICO))


# --- Nuestra base primero --------------------------------------------------


def test_cliente_existente_en_nuestra_base(armar, tmp_path):
    fuente = FuenteSimulada()
    cliente = armar(fuente)
    creada = _crear(cliente)
    antes = _archivos(tmp_path)

    busqueda = ok(_buscar(cliente, dni="30.123.456"))

    assert busqueda["estado"] == "ENCONTRADO"
    assert busqueda["origen"] == "BASE"
    (conocido,) = busqueda["conocidos"]
    assert conocido["cliente_id"] == creada["cliente"]["id"]
    assert conocido["nombre_apellido"] == "Ana Gomez"
    assert conocido["ultima_orden_id"] == creada["id"]
    # No se consulta afuera ni se guarda nada.
    assert fuente.consultas == []
    assert _archivos(tmp_path) == antes


def test_dos_clientes_con_el_mismo_dni_es_ambiguo(armar, tmp_path):
    """Datos anteriores: dos clientes con el mismo DNI (hoy el alta ya no
    lo permite). La busqueda los muestra a los dos para elegir."""
    cliente = armar()
    primera = _crear(cliente, nombre="Ana Gomez")
    otra = _crear(cliente, nombre="Ana M. Gomez", dni=None)
    repo = repo_ordenes(tmp_path)
    anterior = repo.obtener(otra["id"])
    anterior.cliente.dni = DNI
    repo.guardar(anterior)
    assert otra["cliente"]["id"] != primera["cliente"]["id"]

    busqueda = ok(_buscar(cliente))

    assert busqueda["estado"] == "AMBIGUO"
    assert busqueda["origen"] == "BASE"
    assert len(busqueda["conocidos"]) == 2


def test_la_correccion_manual_queda_y_reutiliza_el_cliente(armar):
    """Recepcion usa el cliente conocido, corrige el nombre y crea la
    Orden: queda el dato corregido, con el mismo cliente."""
    cliente = armar()
    primera = _crear(cliente, nombre="ana gomes")
    cliente_id = primera["cliente"]["id"]

    segunda = _crear(
        cliente, nombre="Ana Gómez", dni="30.123.456", cliente_id=cliente_id
    )

    assert segunda["cliente"] == {
        "id": cliente_id,
        "dni": DNI,
        "nombre_apellido": "Ana Gómez",
        "telefono": "341-555",
        "email": None,
    }
    (conocido,) = ok(_buscar(cliente))["conocidos"]
    assert (conocido["nombre_apellido"], conocido["ordenes"]) == (
        "Ana Gómez",
        2,
    )


def test_el_alta_sin_dni_sigue_valiendo_y_uno_invalido_se_rechaza(armar):
    cliente = armar()

    sin_dni = _crear(cliente, dni=None)
    assert sin_dni["cliente"]["dni"] is None
    respuesta = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre_apellido": "X", "telefono": "1", "dni": "12"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "No carga.",
            },
        },
    )
    assert "7 u 8 digitos" in conflicto(respuesta)


# --- Fuente externa --------------------------------------------------------


def test_sin_fuente_autorizada_se_carga_a_mano(armar):
    cliente = armar(fuente=None)

    busqueda = ok(_buscar(cliente))

    assert busqueda["estado"] == "NO_HABILITADA"
    assert busqueda["conocidos"] == [] and busqueda["externos"] == []
    assert "cargá el nombre y apellido a mano" in busqueda["mensaje"]


def test_dni_encontrado_por_la_fuente_se_propone_tal_cual(armar, tmp_path):
    """El nombre completo, sin separar: Recepcion lo revisa y confirma."""
    persona = PersonaExterna(nombre_apellido="GOMEZ ANA MARIA")
    fuente = FuenteSimulada(
        ResultadoFuente(EstadoFuente.ENCONTRADO, (persona,))
    )
    cliente = armar(fuente)
    antes = _archivos(tmp_path)

    busqueda = ok(_buscar(cliente, dni="30.123.456"))

    assert busqueda["estado"] == "ENCONTRADO"
    assert busqueda["origen"] == "EXTERNO"
    assert busqueda["fuente"] == "fuente-simulada"
    assert busqueda["externos"] == [{"nombre_apellido": "GOMEZ ANA MARIA"}]
    assert fuente.consultas == [DNI]
    # Nada se guarda hasta que Recepcion confirma y crea la Orden.
    assert _archivos(tmp_path) == antes
    orden = _crear(cliente, nombre="GOMEZ ANA MARIA")
    assert orden["cliente"]["nombre_apellido"] == "GOMEZ ANA MARIA"


def test_la_comprobacion_previa_al_alta_no_consulta_afuera(armar):
    fuente = FuenteSimulada(
        ResultadoFuente(
            EstadoFuente.ENCONTRADO,
            (PersonaExterna(nombre_apellido="GOMEZ ANA"),),
        )
    )
    cliente = armar(fuente)

    busqueda = ok(
        cliente.get(
            "/api/clients/lookup",
            params={"dni": DNI, "usuario_id": RECEPCION, "externa": "false"},
        )
    )

    assert busqueda["estado"] == "SIN_RESULTADOS"
    assert busqueda["externos"] == []
    assert fuente.consultas == []


def test_dni_sin_resultados(armar):
    cliente = armar(
        FuenteSimulada(ResultadoFuente(EstadoFuente.SIN_RESULTADOS))
    )

    busqueda = ok(_buscar(cliente))

    assert busqueda["estado"] == "SIN_RESULTADOS"
    assert busqueda["externos"] == []


def test_resultados_multiples_son_ambiguos(armar):
    personas = (
        PersonaExterna(nombre_apellido="GOMEZ ANA"),
        PersonaExterna(nombre_apellido="GOMEZ ANA MARIA"),
    )
    cliente = armar(
        FuenteSimulada(ResultadoFuente(EstadoFuente.AMBIGUO, personas))
    )

    busqueda = ok(_buscar(cliente))

    assert busqueda["estado"] == "AMBIGUO"
    assert busqueda["origen"] == "EXTERNO"
    assert len(busqueda["externos"]) == 2


@pytest.mark.parametrize(
    "fuente",
    [
        FuenteSimulada(error=TimeoutError("sin respuesta")),
        FuenteSimulada(error=ValueError("formato desconocido")),
        FuenteSimulada(ResultadoFuente(EstadoFuente.NO_DISPONIBLE)),
    ],
    ids=["caida", "formato-modificado", "rechazada"],
)
def test_fuente_indisponible_no_rompe_el_alta(armar, fuente):
    cliente = armar(fuente)

    busqueda = ok(_buscar(cliente))

    assert busqueda["estado"] == "NO_DISPONIBLE"
    assert "cargá el nombre y apellido a mano" in busqueda["mensaje"]
    # La busqueda nunca bloquea el alta: se carga a mano y se crea.
    orden = _crear(cliente, nombre="Ana Gomez (a mano)")
    assert orden["cliente"]["nombre_apellido"] == "Ana Gomez (a mano)"


def test_limite_de_consultas(armar):
    reloj = Reloj()
    fuente = FuenteSimulada(ResultadoFuente(EstadoFuente.SIN_RESULTADOS))
    cliente = armar(
        fuente,
        LimitadorConsultas(
            intervalo_minimo=2, maximo_por_minuto=2, reloj=reloj
        ),
    )

    assert ok(_buscar(cliente))["estado"] == "SIN_RESULTADOS"
    assert ok(_buscar(cliente))["estado"] == "LIMITE"  # antes de 2 s
    reloj.t += 3
    assert ok(_buscar(cliente))["estado"] == "SIN_RESULTADOS"
    reloj.t += 3
    assert ok(_buscar(cliente))["estado"] == "LIMITE"  # 2 por minuto
    reloj.t += 60
    assert ok(_buscar(cliente))["estado"] == "SIN_RESULTADOS"
    assert len(fuente.consultas) == 3
