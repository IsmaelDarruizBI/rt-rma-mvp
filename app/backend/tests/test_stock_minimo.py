"""Stock minimo por insumo (DEC-AJ-11, BF-15), sin base de datos.

- El estado de reposicion se calcula contra el DISPONIBLE (fisico menos
  reservado pendiente), con lo que esta en camino para distinguir «bajo
  minimo» de «bajo minimo con reposicion solicitada».
- No es un faltante: «Solo faltantes» y la bandeja de insumos negativos no
  cambian.
- Inventario lo muestra y lo filtra; Inicio avisa a Coordinacion y
  Administracion; Compras sugiere reponer hasta el minimo sin duplicar lo
  pedido. La edicion del minimo (PostgreSQL) se prueba en
  ``tests/postgres/test_stock_minimo_postgres.py``.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.models import Insumo, RolUsuario, Usuario
from app.domain.models.compras import OrigenSolicitud
from app.services import (
    EstadoReposicion,
    PrecondicionInvalidaError,
    SituacionInsumo,
    cantidad_a_reponer,
    estado_reposicion,
)
from app.services.compras import sugerencias
from app.services.operativa import cambios_de_insumo
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    COORDINADOR,
    INSUMO_BATERIA,
    INSUMO_PANTALLA,
    RECEPCION,
    TECNICO,
    cliente_http,
    definida,
    iniciar,
    ok,
    tomada,
)

D = Decimal
FECHA = datetime(2026, 11, 24, tzinfo=timezone.utc)
ADMIN = Usuario(id="ADMIN-001", nombre="A", rol=RolUsuario.ADMINISTRADOR)
RECEP = Usuario(id="RECEP-001", nombre="R", rol=RolUsuario.RECEPCION)
E = EstadoReposicion


# --- Estado de reposicion (funcion pura) -------------------------------------


@pytest.mark.parametrize(
    ("minimo", "disponible", "camino", "esperado"),
    [
        (None, "0", "0", E.SIN_MINIMO),
        (None, "-3", "10", E.SIN_MINIMO),
        ("5", "5", "0", E.SUFICIENTE),
        ("5", "9", "0", E.SUFICIENTE),
        ("0", "0", "0", E.SUFICIENTE),
        ("5", "4", "0", E.BAJO_MINIMO),
        ("5", "2", "2", E.BAJO_MINIMO),
        ("5", "2", "3", E.BAJO_MINIMO_REPOSICION_SOLICITADA),
        ("5", "0", "8", E.BAJO_MINIMO_REPOSICION_SOLICITADA),
        ("2.5", "2.4", "0", E.BAJO_MINIMO),
    ],
)
def test_estado_de_reposicion(minimo, disponible, camino, esperado):
    assert (
        estado_reposicion(
            stock_minimo=None if minimo is None else D(minimo),
            disponible=D(disponible),
            en_camino=D(camino),
        )
        is esperado
    )


def _insumo(minimo=None, fisico="5", activo=True, id="INS-001"):
    return Insumo(
        id=id,
        codigo=id,
        nombre=id,
        stock_fisico=D(fisico),
        activo=activo,
        stock_minimo=None if minimo is None else D(minimo),
    )


def test_la_situacion_compara_con_el_disponible_y_no_es_un_faltante():
    from app.services import ReservaVigente

    reserva = ReservaVigente(
        orden_id="OR-1",
        detalle_id="RD-1",
        movimiento_id="MOV-1",
        ejecucion_id=None,
        cantidad=D("2"),
        fecha=FECHA,
    )
    # Fisico 5 cubre el minimo 4, pero el disponible (5 - 2 = 3) no.
    situacion = SituacionInsumo(insumo=_insumo("4"), reservas=(reserva,))
    assert situacion.disponible == D("3")
    assert situacion.estado_reposicion is E.BAJO_MINIMO
    assert situacion.bajo_minimo is True
    assert situacion.faltante is False
    con_pedido = SituacionInsumo(
        insumo=_insumo("4"), reservas=(reserva,), en_camino=D("1")
    )
    assert con_pedido.estado_reposicion is E.BAJO_MINIMO_REPOSICION_SOLICITADA
    assert con_pedido.bajo_minimo is True
    # Un insumo inactivo informa su estado pero no alerta.
    inactivo = SituacionInsumo(insumo=_insumo("4", activo=False), reservas=())
    assert inactivo.estado_reposicion is E.SUFICIENTE
    inactivo = SituacionInsumo(insumo=_insumo("9", activo=False), reservas=())
    assert inactivo.estado_reposicion is E.BAJO_MINIMO
    assert inactivo.bajo_minimo is False
    # Sin minimo: nunca alerta.
    assert not SituacionInsumo(insumo=_insumo(), reservas=()).bajo_minimo


# --- Cantidad sugerida -------------------------------------------------------


def test_cantidad_a_reponer_sin_minimo_es_la_formula_de_siempre():
    assert cantidad_a_reponer(
        stock_minimo=None, demanda=D("4"), disponible=D("1"), en_camino=D("1")
    ) == (D("2"), D("0"))
    assert cantidad_a_reponer(
        stock_minimo=None, demanda=D("1"), disponible=D("3"), en_camino=D("0")
    ) == (D("0"), D("0"))


def _reponer(minimo, demanda, disponible, camino):
    return cantidad_a_reponer(
        stock_minimo=D(minimo),
        demanda=D(demanda),
        disponible=D(disponible),
        en_camino=D(camino),
    )


def test_cantidad_a_reponer_con_minimo_separa_faltante_y_minimo():
    # demanda + minimo - disponible - en camino = 4 + 5 - 1 - 1 = 7
    assert _reponer("5", "4", "1", "1") == (D("2"), D("5"))
    # Solo el minimo: 0 + 5 - 2 - 0 = 3
    assert _reponer("5", "0", "2", "0") == (D("0"), D("3"))
    # Lo en camino ya lo cubre: nada.
    assert _reponer("5", "0", "2", "3") == (D("0"), D("0"))


def test_sugerencias_con_minimo_motivo_y_sin_duplicar_lo_pedido():
    resultado = sugerencias(
        disponibles={
            "A": D("1"),
            "B": D("2"),
            "C": D("2"),
            "E": D("10"),
            "F": D("0"),
        },
        demanda={"A": (D("4"), ["OR-1"]), "F": (D("2"), ["OR-2"])},
        en_camino={"A": D("1"), "C": D("3")},
        minimos={"A": D("5"), "B": D("5"), "C": D("5"), "E": D("5")},
    )
    por_insumo = {s.insumo_id: s for s in resultado}
    # A: faltante y minimo -> STOCK_MINIMO, con las Ordenes del faltante.
    a = por_insumo["A"]
    assert (a.sugerido, a.por_faltante, a.por_minimo) == (D(7), D(2), D(5))
    assert a.motivo is OrigenSolicitud.STOCK_MINIMO
    assert a.ordenes == ["OR-1"]
    assert a.stock_minimo == D("5")
    # B: solo el minimo.
    b = por_insumo["B"]
    assert (b.sugerido, b.por_faltante, b.por_minimo) == (D(3), D(0), D(3))
    assert b.motivo is OrigenSolicitud.STOCK_MINIMO
    assert b.ordenes == []
    # C: bajo minimo, pero lo pedido lo cubre: no se sugiere de nuevo.
    assert "C" not in por_insumo
    # E: sobre el minimo y sin demanda: nada.
    assert "E" not in por_insumo
    # F: sin minimo, solo faltante (como siempre).
    f = por_insumo["F"]
    assert (f.sugerido, f.por_minimo, f.motivo) == (
        D(2),
        D(0),
        OrigenSolicitud.FALTANTE,
    )
    assert f.stock_minimo is None


# --- Configuracion: auditoria y validacion -----------------------------------


def test_el_minimo_se_audita_y_se_valida():
    anterior = _insumo()
    cambios = cambios_de_insumo(
        anterior, _insumo("2.5"), usuario=ADMIN, fecha=FECHA
    )
    assert [(c.campo, c.valor_anterior, c.valor_nuevo) for c in cambios] == [
        ("stock_minimo", None, "2.5")
    ]
    # Tres decimales: no se pierde un cambio por redondeo.
    cambios = cambios_de_insumo(
        _insumo("1.001"), _insumo("1.002"), usuario=ADMIN, fecha=FECHA
    )
    assert [(c.valor_anterior, c.valor_nuevo) for c in cambios] == [
        ("1.001", "1.002")
    ]
    # Quitarlo tambien queda auditado.
    cambios = cambios_de_insumo(
        _insumo("3"), _insumo(), usuario=ADMIN, fecha=FECHA
    )
    assert [(c.valor_anterior, c.valor_nuevo) for c in cambios] == [
        ("3", None)
    ]
    with pytest.raises(PrecondicionInvalidaError, match="tres decimales"):
        cambios_de_insumo(
            anterior, _insumo("1.0005"), usuario=ADMIN, fecha=FECHA
        )
    with pytest.raises(PrecondicionInvalidaError):
        cambios_de_insumo(anterior, _insumo("3"), usuario=RECEP, fecha=FECHA)
    with pytest.raises(ValueError):
        _insumo("-1")


# --- Inventario e Inicio (API, modo JSON) ------------------------------------


def _con_minimos(tmp_path, minimos: dict[str, str | None]) -> None:
    archivo = tmp_path / "catalogs" / "insumos.json"
    insumos = json.loads(archivo.read_text("utf-8"))
    for insumo in insumos:
        if insumo["id"] in minimos:
            insumo["stock_minimo"] = minimos[insumo["id"]]
    archivo.write_text(json.dumps(insumos), "utf-8")


def _inventario(cliente, **parametros) -> dict[str, dict]:
    filas = ok(cliente.get("/api/inventory", params=parametros))
    return {fila["id"]: fila for fila in filas}


def _bandejas(cliente, usuario) -> dict[str, dict]:
    datos = ok(cliente.get("/api/work/inbox", params={"usuario_id": usuario}))
    return {bandeja["codigo"]: bandeja for bandeja in datos["bandejas"]}


def test_inventario_muestra_el_estado_y_filtra_bajo_minimo(tmp_path):
    with cliente_http(tmp_path, "5") as cliente:
        # Sin minimos: todo igual que antes.
        inventario = _inventario(cliente)
        assert {
            (f["stock_minimo"], f["estado_reposicion"], f["bajo_minimo"])
            for f in inventario.values()
        } == {(None, "SIN_MINIMO", False)}
        assert _inventario(cliente, bajo_minimo=True) == {}

        orden = definida(cliente)
        tomada(cliente, orden)
        iniciar(cliente, orden)  # reserva una bateria: disponible 4
        _con_minimos(tmp_path, {INSUMO_BATERIA: "5", INSUMO_PANTALLA: "5"})

        inventario = _inventario(cliente)
        bateria = inventario[INSUMO_BATERIA]
        # El fisico (5) alcanza el minimo; el disponible (4), no.
        assert (bateria["stock_fisico"], bateria["disponible"]) == ("5", "4")
        assert bateria["stock_minimo"] == "5"
        assert bateria["en_camino"] == "0"  # JSON: sin Compras
        assert bateria["estado_reposicion"] == "BAJO_MINIMO"
        assert bateria["bajo_minimo"] is True
        assert bateria["faltante"] is False
        assert inventario[INSUMO_PANTALLA]["estado_reposicion"] == "SUFICIENTE"

        assert list(_inventario(cliente, bajo_minimo=True)) == [INSUMO_BATERIA]
        # No es un faltante: «Solo faltantes» sigue vacio.
        assert _inventario(cliente, solo_faltantes=True) == {}
        assert list(_inventario(cliente, bajo_minimo=True, buscar="BAT")) == [
            INSUMO_BATERIA
        ]
        detalle = ok(cliente.get(f"/api/inventory/{INSUMO_BATERIA}"))
        assert detalle["insumo"]["estado_reposicion"] == "BAJO_MINIMO"


def test_inicio_avisa_a_coordinacion_y_administracion(tmp_path):
    with cliente_http(tmp_path, "3") as cliente:
        vacia = _bandejas(cliente, COORDINADOR)["STOCK_BAJO_MINIMO"]
        assert (vacia["cantidad"], vacia["insumos"]) == (0, [])
        assert vacia["destino"] == "INVENTARIO"
        assert vacia["tipo"] == "SEGUIMIENTO"

        _con_minimos(tmp_path, {INSUMO_BATERIA: "4", INSUMO_PANTALLA: "3"})
        for usuario in (COORDINADOR, ADMINISTRADOR):
            bandejas = _bandejas(cliente, usuario)
            bandeja = bandejas["STOCK_BAJO_MINIMO"]
            assert bandeja["titulo"] == "Insumos a reponer"
            assert bandeja["cantidad"] == 1
            (insumo,) = bandeja["insumos"]
            assert insumo["id"] == INSUMO_BATERIA
            assert insumo["estado_reposicion"] == "BAJO_MINIMO"
            # La bandeja de negativos no cambia.
            assert bandejas["INSUMOS_NEGATIVOS"]["insumos"] == []
        for usuario in (RECEPCION, TECNICO):
            assert "STOCK_BAJO_MINIMO" not in _bandejas(cliente, usuario)

        # Un insumo inactivo no avisa.
        archivo = tmp_path / "catalogs" / "insumos.json"
        insumos = json.loads(archivo.read_text("utf-8"))
        for insumo in insumos:
            insumo["activo"] = insumo["id"] != INSUMO_BATERIA
        archivo.write_text(json.dumps(insumos), "utf-8")
        assert (
            _bandejas(cliente, COORDINADOR)["STOCK_BAJO_MINIMO"]["cantidad"]
            == 0
        )
