"""DEC-AJ-14 (D-14.4, parte B del bloque 8): requisitos de insumo por Tipo,
pieza concreta elegida antes de reservar, sustitucion controlada,
factibilidad y reserva sobre la pieza elegida.

Modo JSON: la administracion de los requisitos es de PostgreSQL (ver
``tests/postgres/test_requisitos_pieza_postgres.py``); aca se cargan en el
archivo opcional ``tipo_reparacion_requisitos.json``. Sin categorias en el
modo JSON, cada requisito apunta a la categoria exacta de sus piezas.

Catalogo propio (sobre ``api_salidas.sembrar``):

- ``TR-003`` «Cambio de bateria (por modelo)»: previsto concreto
  ``INS-020`` (adhesivo universal) x 1 y requisito ``CAT-001`` (baterias)
  x 1. Para el iPhone 8 (``MOD-0001``) hay dos baterias compatibles
  (``INS-010`` e ``INS-011``): la elige una persona.
- ``TR-004`` «Cambio de flex»: requisitos ``CAT-003`` (flex) x 1 (para el
  iPhone 8 solo ``INS-030``) y ``CAT-002`` (adhesivos) x 2 (solo
  ``INS-020``, universal): las dos se eligen solas.
- ``INS-012``: bateria del iPhone 11 (``MOD-0003``), la unica compatible
  con ese modelo.
"""

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.application import construir_contexto
from app.application.piezas import piezas_de, requisitos_de_insumo
from app.core.config import Settings
from app.domain.models import (
    CategoriaInsumo,
    Insumo,
    RolUsuario,
    TipoMovimientoInsumo,
    TipoReparacion,
    TipoReparacionInsumos,
    TipoReparacionRequisito,
    Usuario,
)
from app.main import create_app
from app.services.configuracion import insumos_necesarios
from app.services.exceptions import PrecondicionInvalidaError
from app.services.inventario_global import reservas_activas_globales
from app.services.piezas import conciliar_piezas
from app.storage.json.base import escribir_json_atomico
from tests.fixtures import api_salidas as f

IPHONE_8 = "MOD-0001"
IPHONE_11 = "MOD-0003"
TIPO_BATERIA = "TR-003"
TIPO_FLEX = "TR-004"
REQ_BATERIA = "REQ-BAT"
REQ_FLEX = "REQ-FLEX"
REQ_ADHESIVO = "REQ-ADH"
BATERIA_A = "INS-010"
BATERIA_B = "INS-011"
BATERIA_11 = "INS-012"
ADHESIVO = "INS-020"
FLEX = "INS-030"


def _insumo(id_, nombre, stock, categoria, modelos=()):
    return Insumo(
        id=id_,
        codigo=id_.replace("INS", "P"),
        nombre=nombre,
        stock_fisico=Decimal(stock),
        categoria_id=categoria,
        modelos_compatibles=tuple(modelos),
    )


def _sembrar(directorio, **stocks) -> None:
    f.sembrar(directorio, "5")
    catalogos = directorio / "catalogs"

    def leer(nombre):
        return json.loads((catalogos / nombre).read_text(encoding="utf-8"))

    def escribir(nombre, filas):
        escribir_json_atomico(catalogos / nombre, filas)

    tipos = leer("tipos_reparacion.json")
    tipos += [
        TipoReparacion(
            id=TIPO_BATERIA,
            nombre="Cambio de bateria (por modelo)",
            precio=Decimal("70000"),
            puntaje=8,
            garantia_dias=90,
        ).model_dump(mode="json"),
        TipoReparacion(
            id=TIPO_FLEX,
            nombre="Cambio de flex",
            precio=Decimal("40000"),
            puntaje=6,
            garantia_dias=90,
        ).model_dump(mode="json"),
    ]
    escribir("tipos_reparacion.json", tipos)
    insumos = leer("insumos.json")
    insumos += [
        i.model_dump(mode="json")
        for i in (
            _insumo(
                BATERIA_A,
                "Bateria iPhone 8 Acme",
                stocks.get("bateria_a", "2"),
                "CAT-001",
                [IPHONE_8],
            ),
            _insumo(
                BATERIA_B,
                "Bateria iPhone 8 Beta",
                stocks.get("bateria_b", "2"),
                "CAT-001",
                [IPHONE_8],
            ),
            _insumo(
                BATERIA_11,
                "Bateria iPhone 11",
                stocks.get("bateria_11", "1"),
                "CAT-001",
                [IPHONE_11],
            ),
            _insumo(
                ADHESIVO, "Adhesivo", stocks.get("adhesivo", "9"), "CAT-002"
            ),
            _insumo(
                FLEX,
                "Flex de carga iPhone 8",
                stocks.get("flex", "1"),
                "CAT-003",
                [IPHONE_8],
            ),
        )
    ]
    escribir("insumos.json", insumos)
    previstos = leer("tipo_reparacion_insumos.json")
    previstos.append(
        TipoReparacionInsumos(
            tipo_reparacion_id=TIPO_BATERIA,
            insumo_id=ADHESIVO,
            cantidad=Decimal("1"),
        ).model_dump(mode="json")
    )
    escribir("tipo_reparacion_insumos.json", previstos)
    estaciones = leer("tipo_reparacion_estaciones.json")
    estaciones += [
        {"tipo_reparacion_id": tipo, "estacion_id": f.ESTACION}
        for tipo in (TIPO_BATERIA, TIPO_FLEX)
    ]
    escribir("tipo_reparacion_estaciones.json", estaciones)
    escribir(
        "tipo_reparacion_requisitos.json",
        [
            TipoReparacionRequisito(
                id=REQ_BATERIA,
                tipo_reparacion_id=TIPO_BATERIA,
                categoria_id="CAT-001",
                cantidad=Decimal("1"),
            ).model_dump(mode="json"),
            TipoReparacionRequisito(
                id=REQ_FLEX,
                tipo_reparacion_id=TIPO_FLEX,
                categoria_id="CAT-003",
                cantidad=Decimal("1"),
            ).model_dump(mode="json"),
            TipoReparacionRequisito(
                id=REQ_ADHESIVO,
                tipo_reparacion_id=TIPO_FLEX,
                categoria_id="CAT-002",
                cantidad=Decimal("2"),
                posicion=2,
            ).model_dump(mode="json"),
        ],
    )


@pytest.fixture
def directorio(tmp_path):
    _sembrar(tmp_path)
    return tmp_path


def _cliente(directorio) -> TestClient:
    return TestClient(create_app(Settings(data_dir=directorio)))


@pytest.fixture
def cliente(directorio):
    with _cliente(directorio) as http:
        yield http


def _orden(cliente, tipo=TIPO_BATERIA, modelo: str | None = IPHONE_8) -> str:
    """CLIENTE_EXTERNO con un trabajo ``tipo``, autorizado y en la cola."""
    equipo = (
        {"modelo_tecnico_id": modelo, "falla_reportada": "No carga."}
        if modelo
        else {
            "marca": "Apple",
            "modelo": "iPhone generico",
            "falla_reportada": "No carga.",
        }
    )
    orden_id = f.ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": f.RECEPCION,
                "cliente": {"nombre_apellido": "Ana", "telefono": "341-1"},
                "equipo": equipo,
                "recepcion": {
                    "estado_fisico": "Sin golpes.",
                    "funcionalidades_verificadas": True,
                },
            },
        )
    )["id"]
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details",
            json={"usuario_id": f.RECEPCION, "tipo_reparacion_id": tipo},
        )
    )
    return orden_id


def _en_cola(cliente, **extra) -> str:
    orden_id = _orden(cliente, **extra)
    f.finalizar(cliente, orden_id)
    return orden_id


def _elegir(
    cliente,
    orden_id,
    insumo,
    *,
    requisito=REQ_BATERIA,
    usuario=f.TECNICO,
    motivo=None,
    detalle="DET-001",
):
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle}/pieces",
        json={
            "usuario_id": usuario,
            "requisito_id": requisito,
            "insumo_id": insumo,
            "motivo": motivo,
        },
    )


def _requisitos(orden, detalle="DET-001") -> dict[str, dict]:
    return {
        r["requisito_id"]: r
        for r in f.detalle(orden, detalle)["requisitos_insumo"]
    }


def _movimientos(directorio, orden_id) -> list:
    return f.repo_ordenes(directorio).obtener(orden_id).movimientos_insumo


def _reservado(directorio) -> dict[str, Decimal]:
    return reservas_activas_globales(f.repo_ordenes(directorio).listar())


def _iniciar(cliente, orden_id, detalle="DET-001"):
    f.evaluar_si_hace_falta(cliente, orden_id, detalle)
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle}/start",
        json={"usuario_id": f.TECNICO},
    )


def _ejecucion_activa(orden) -> str:
    (activa,) = [
        e for e in orden["ejecuciones"] if e["estado"] == "EN_PROGRESO"
    ]
    return activa["id"]


# --- Sin requisitos: como antes ----------------------------------------------


def test_un_tipo_sin_requisitos_funciona_como_antes(cliente, directorio):
    orden_id = f.definida(cliente, f.BATERIA)
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    detalle = f.detalle(orden, "DET-001")
    assert detalle["requisitos_insumo"] == []
    assert detalle["piezas"] == []
    assert [
        (p["insumo_id"], p["cantidad_prevista"], p["pieza"])
        for p in detalle["insumos_previstos"]
    ] == [(f.INSUMO_BATERIA, "1", False)]
    f.tomada(cliente, orden_id)
    ejecucion = f.iniciar(cliente, orden_id)
    assert [
        (m.tipo, m.insumo_id) for m in _movimientos(directorio, orden_id)
    ] == [(TipoMovimientoInsumo.RESERVA, f.INSUMO_BATERIA)]
    f.ok(f.cerrar_ejecucion(cliente, orden_id, ejecucion))
    assert f.stock(directorio) == Decimal("4")


def test_sin_el_archivo_de_requisitos_no_hay_requisitos(tmp_path):
    with f.cliente_http(tmp_path) as cliente:
        orden_id = f.definida(cliente, f.BATERIA)
        orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
        assert f.detalle(orden, "DET-001")["requisitos_insumo"] == []


# --- Eleccion automatica -----------------------------------------------------


def test_una_sola_pieza_compatible_se_elige_sola_al_definir(cliente):
    orden_id = _orden(cliente, tipo=TIPO_FLEX)
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    requisitos = _requisitos(orden)
    assert [
        r["requisito_id"]
        for r in orden["reparaciones_detail"][0]["requisitos_insumo"]
    ] == [REQ_FLEX, REQ_ADHESIVO]
    assert requisitos[REQ_FLEX]["estado"] == "ELEGIDA"
    assert requisitos[REQ_FLEX]["insumo_id"] == FLEX
    assert requisitos[REQ_FLEX]["causa"] == "AUTOMATICA"
    assert requisitos[REQ_ADHESIVO]["insumo_id"] == ADHESIVO
    assert requisitos[REQ_ADHESIVO]["cantidad"] == "2"
    # Quien definio el trabajo queda como quien eligio.
    assert {
        p["usuario_id"] for p in f.detalle(orden, "DET-001")["piezas"]
    } == {f.RECEPCION}
    pasos = [
        (p["referencia_id"], p["accion"])
        for p in orden["historial"]
        if p["referencia_id"] == "ACC-REP-084"
    ]
    assert pasos == [("ACC-REP-084", "ELEGIR_PIEZA_AUTOMATICA")] * 2
    # Lo previsto del trabajo (formulario de consumo) incluye las piezas.
    assert [
        (p["insumo_id"], p["cantidad_prevista"], p["pieza"])
        for p in f.detalle(orden, "DET-001")["insumos_previstos"]
    ] == [(FLEX, "1", True), (ADHESIVO, "2", True)]


def test_con_varias_compatibles_queda_pendiente_de_elegir(cliente):
    orden_id = _orden(cliente)
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    requisito = _requisitos(orden)[REQ_BATERIA]
    assert requisito["estado"] == "PENDIENTE"
    assert requisito["insumo_id"] is None
    assert f.detalle(orden, "DET-001")["piezas"] == []


def test_las_opciones_son_las_compatibles_con_su_disponible(cliente):
    orden_id = _orden(cliente)
    opciones = f.ok(
        cliente.get(
            f"/api/orders/{orden_id}/details/DET-001/pieces/options",
            params={"requisito_id": REQ_BATERIA},
        )
    )
    assert opciones["modelo_equipo_id"] == IPHONE_8
    assert opciones["compatibilidad_no_verificada"] is False
    assert [(o["id"], o["disponible"]) for o in opciones["opciones"]] == [
        (BATERIA_A, "2"),
        (BATERIA_B, "2"),
    ]


# --- Factibilidad y reserva --------------------------------------------------


def test_pendiente_con_alguna_compatible_disponible_es_factible(cliente):
    orden_id = _en_cola(cliente)
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert orden["estado_workflow"] == "EN_COLA"
    assert f.detalle(orden, "DET-001")["condicion"] == "SIN_BLOQUEO"


def test_pendiente_sin_ninguna_compatible_disponible_bloquea(tmp_path):
    _sembrar(tmp_path, bateria_a="0", bateria_b="0")
    with _cliente(tmp_path) as cliente:
        orden_id = _en_cola(cliente)
        orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
        assert (
            f.detalle(orden, "DET-001")["condicion"]
            == "BLOQUEADO_POR_RECURSOS"
        )
        observaciones = " ".join(
            p["observacion"] or "" for p in orden["historial"]
        )
        assert "Sin pieza elegida: CAT-001" in observaciones


def test_no_se_inicia_con_un_requisito_sin_pieza(cliente, directorio):
    orden_id = _en_cola(cliente)
    f.tomada(cliente, orden_id)
    antes = f.archivo(directorio, orden_id)
    mensaje = f.conflicto(_iniciar(cliente, orden_id), "PIEZA_SIN_ELEGIR")
    assert "CAT-001" in mensaje
    assert f.archivo(directorio, orden_id) == antes
    assert _movimientos(directorio, orden_id) == []


def test_iniciar_reserva_los_previstos_y_la_pieza_elegida(cliente, directorio):
    orden_id = _en_cola(cliente)
    orden = f.ok(_elegir(cliente, orden_id, BATERIA_A))
    requisito = _requisitos(orden)[REQ_BATERIA]
    assert (requisito["estado"], requisito["causa"]) == ("ELEGIDA", "ELECCION")
    assert requisito["elegida_por"] == f.TECNICO
    f.tomada(cliente, orden_id)
    f.ok(_iniciar(cliente, orden_id))
    assert sorted(
        (m.tipo.value, m.insumo_id, str(m.cantidad))
        for m in _movimientos(directorio, orden_id)
    ) == [("RESERVA", BATERIA_A, "1"), ("RESERVA", ADHESIVO, "1")]
    reservado = _reservado(directorio)
    assert reservado[BATERIA_A] == Decimal("1")
    assert BATERIA_B not in reservado


def test_la_pieza_elegida_sin_disponible_bloquea_y_no_reserva(tmp_path):
    _sembrar(tmp_path, bateria_a="0")
    with _cliente(tmp_path) as cliente:
        orden_id = _en_cola(cliente)  # factible: hay de la otra
        f.ok(_elegir(cliente, orden_id, BATERIA_A))
        f.tomada(cliente, orden_id)
        orden = f.ok(_iniciar(cliente, orden_id))
        # Reserva fallida (EXC-REP-003): todo o nada, sin Ejecucion.
        assert (
            f.detalle(orden, "DET-001")["condicion"]
            == "BLOQUEADO_POR_RECURSOS"
        )
        assert orden["ejecuciones"] == []
        assert _movimientos(tmp_path, orden_id) == []
        assert any(
            p["referencia_id"] == "PROC-REP-186"
            and p["observacion"] == f"Faltantes: {BATERIA_A}"
            for p in orden["historial"]
        )


def test_el_override_reserva_solo_lo_disponible_de_la_pieza(tmp_path):
    """El override sigue igual (P-06): la pieza sin stock no se reserva."""
    _sembrar(tmp_path, bateria_a="0", bateria_b="0")
    with _cliente(tmp_path) as cliente:
        orden_id = _orden(cliente)
        f.ok(_elegir(cliente, orden_id, BATERIA_A))
        f.finalizar(cliente, orden_id)
        orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
        assert orden["current_process"] == "PROC-REP-100"
        f.ok(
            cliente.post(
                f"/api/orders/{orden_id}/details/DET-001/resources/override",
                json={
                    "usuario_id": f.COORDINADOR,
                    "motivo": "Llega la bateria mañana.",
                    "confirmado": True,
                },
            )
        )
        f.tomada(cliente, orden_id)
        orden = f.ok(_iniciar(cliente, orden_id))
        assert [
            (m.tipo.value, m.insumo_id)
            for m in _movimientos(tmp_path, orden_id)
        ] == [("RESERVA", ADHESIVO)]
        paso = next(
            p
            for p in orden["historial"]
            if p["referencia_id"] == "PROC-REP-185"
        )
        assert f"{BATERIA_A} reservado 0 de 1" in paso["observacion"]


# --- Eleccion manual ---------------------------------------------------------


def test_recepcion_no_elige_piezas_por_defecto(cliente, directorio):
    orden_id = _orden(cliente)
    antes = f.archivo(directorio, orden_id)
    mensaje = f.conflicto(
        _elegir(cliente, orden_id, BATERIA_A, usuario=f.RECEPCION)
    )
    assert "requiere el rol" in mensaje
    assert f.archivo(directorio, orden_id) == antes


@pytest.mark.parametrize(
    "usuario", [f.TECNICO, f.COORDINADOR, f.ADMINISTRADOR]
)
def test_tecnico_coordinacion_y_administracion_eligen(cliente, usuario):
    orden_id = _orden(cliente)
    orden = f.ok(_elegir(cliente, orden_id, BATERIA_B, usuario=usuario))
    assert _requisitos(orden)[REQ_BATERIA]["insumo_id"] == BATERIA_B


def test_solo_se_elige_una_pieza_compatible_de_la_categoria(cliente):
    orden_id = _orden(cliente)
    assert "compatible con el modelo" in f.conflicto(
        _elegir(cliente, orden_id, BATERIA_11)
    )
    # Un insumo de otra categoria tampoco.
    f.conflicto(_elegir(cliente, orden_id, FLEX))
    assert _elegir(cliente, orden_id, "INS-999").status_code == 404


def test_sustituir_antes_de_reservar_exige_motivo(cliente, directorio):
    orden_id = _orden(cliente)
    f.ok(_elegir(cliente, orden_id, BATERIA_A))
    assert "motivo" in f.conflicto(_elegir(cliente, orden_id, BATERIA_B))
    assert "no hay cambios" in f.conflicto(
        _elegir(cliente, orden_id, BATERIA_A, motivo="Otra")
    )
    orden = f.ok(
        _elegir(cliente, orden_id, BATERIA_B, motivo="Mejor proveedor.")
    )
    primera, segunda = f.detalle(orden, "DET-001")["piezas"]
    assert (segunda["causa"], segunda["reemplaza_a"]) == (
        "SUSTITUCION",
        primera["id"],
    )
    assert segunda["motivo"] == "Mejor proveedor."
    assert _requisitos(orden)[REQ_BATERIA]["insumo_id"] == BATERIA_B
    assert orden["historial"][-1]["accion"] == "SUSTITUIR_PIEZA"
    assert _movimientos(directorio, orden_id) == []


# --- Equipo sin modelo tecnico -----------------------------------------------


def test_sin_modelo_las_universales_se_eligen_solas(cliente):
    orden_id = _orden(cliente, tipo=TIPO_FLEX, modelo=None)
    requisitos = _requisitos(f.ok(cliente.get(f"/api/orders/{orden_id}")))
    assert requisitos[REQ_ADHESIVO]["insumo_id"] == ADHESIVO
    # El flex no es universal: sin modelo no hay eleccion automatica.
    assert requisitos[REQ_FLEX]["estado"] == "PENDIENTE"


def test_sin_modelo_ni_universales_se_elige_con_motivo_sin_verificar(cliente):
    orden_id = _orden(cliente, modelo=None)
    opciones = f.ok(
        cliente.get(
            f"/api/orders/{orden_id}/details/DET-001/pieces/options",
            params={"requisito_id": REQ_BATERIA},
        )
    )
    assert opciones["compatibilidad_no_verificada"] is True
    assert {o["id"] for o in opciones["opciones"]} == {
        BATERIA_A,
        BATERIA_B,
        BATERIA_11,
    }
    assert "compatibilidad no verificada" in f.conflicto(
        _elegir(cliente, orden_id, BATERIA_11)
    )
    orden = f.ok(
        _elegir(
            cliente, orden_id, BATERIA_11, motivo="El cliente dice iPhone 11."
        )
    )
    requisito = _requisitos(orden)[REQ_BATERIA]
    assert requisito["compatibilidad_no_verificada"] is True
    assert requisito["compatible_con_modelo"] is True
    assert (
        "compatibilidad no verificada" in orden["historial"][-1]["observacion"]
    )


# --- Sustitucion despues de reservar -----------------------------------------


def _reservada(cliente, directorio) -> tuple[str, str]:
    orden_id = _en_cola(cliente)
    f.ok(_elegir(cliente, orden_id, BATERIA_A))
    f.tomada(cliente, orden_id)
    orden = f.ok(_iniciar(cliente, orden_id))
    return orden_id, _ejecucion_activa(orden)


def test_sustituir_reservada_libera_y_reserva_en_una_operacion(
    cliente, directorio
):
    orden_id, ejecucion = _reservada(cliente, directorio)
    antes = len(_movimientos(directorio, orden_id))
    orden = f.ok(
        _elegir(cliente, orden_id, BATERIA_B, motivo="La Acme vino fallada.")
    )
    nuevos = _movimientos(directorio, orden_id)[antes:]
    reserva_a = next(
        m
        for m in _movimientos(directorio, orden_id)
        if m.tipo is TipoMovimientoInsumo.RESERVA and m.insumo_id == BATERIA_A
    )
    liberacion, reserva = nuevos
    assert (
        liberacion.tipo,
        liberacion.insumo_id,
        liberacion.cantidad,
        liberacion.movimiento_origen_id,
        liberacion.ejecucion_id,
        liberacion.usuario_id,
    ) == (
        TipoMovimientoInsumo.LIBERACION_RESERVA,
        BATERIA_A,
        Decimal("1"),
        reserva_a.id,
        ejecucion,
        f.TECNICO,
    )
    assert (
        reserva.tipo,
        reserva.insumo_id,
        reserva.cantidad,
        reserva.ejecucion_id,
    ) == (TipoMovimientoInsumo.RESERVA, BATERIA_B, Decimal("1"), ejecucion)
    reservado = _reservado(directorio)
    assert BATERIA_A not in reservado
    assert reservado[BATERIA_B] == Decimal("1")
    assert orden["historial"][-1]["accion"] == "SUSTITUIR_PIEZA_RESERVADA"
    requisito = _requisitos(orden)[REQ_BATERIA]
    assert (requisito["insumo_id"], requisito["reservada"]) == (
        BATERIA_B,
        True,
    )
    # La Ejecucion sigue en curso y, al completarla, se consume la nueva.
    assert [
        p["insumo_id"]
        for p in f.detalle(orden, "DET-001")["insumos_previstos"]
    ] == [ADHESIVO, BATERIA_B]
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion}/complete",
            json={
                "usuario_id": f.TECNICO,
                "insumos_utilizados": [
                    {"insumo_id": BATERIA_B, "cantidad": "1"},
                    {"insumo_id": ADHESIVO, "cantidad": "1"},
                ],
            },
        )
    )
    consumos = sorted(
        m.insumo_id
        for m in _movimientos(directorio, orden_id)
        if m.tipo is TipoMovimientoInsumo.CONSUMO
    )
    assert consumos == [BATERIA_B, ADHESIVO]
    assert f.stock(directorio, BATERIA_B) == Decimal("1")
    assert f.stock(directorio, BATERIA_A) == Decimal("2")
    assert _reservado(directorio) == {}


def test_sustituir_reservada_sin_disponible_no_cambia_nada(tmp_path):
    _sembrar(tmp_path, bateria_b="0")
    with _cliente(tmp_path) as cliente:
        orden_id, _ = _reservada(cliente, tmp_path)
        antes = f.archivo(tmp_path, orden_id)
        f.conflicto(
            _elegir(cliente, orden_id, BATERIA_B, motivo="Cambio."),
            "RECURSO_NO_DISPONIBLE",
        )
        assert f.archivo(tmp_path, orden_id) == antes
        assert _reservado(tmp_path)[BATERIA_A] == Decimal("1")


def test_sustituir_reservada_no_toma_la_reserva_de_otra_orden(tmp_path):
    """Una sola reserva por disponibilidad: la de otra Orden cuenta."""
    _sembrar(tmp_path, bateria_b="1")
    with _cliente(tmp_path) as cliente:
        otra = _en_cola(cliente)
        f.ok(_elegir(cliente, otra, BATERIA_B))
        f.tomada(cliente, otra, tecnico=f.TECNICO_B)
        f.evaluar_si_hace_falta(cliente, otra, "DET-001", f.TECNICO_B)
        f.ok(
            cliente.post(
                f"/api/orders/{otra}/details/DET-001/start",
                json={"usuario_id": f.TECNICO_B},
            )
        )
        orden_id, _ = _reservada(cliente, tmp_path)
        antes = f.archivo(tmp_path, orden_id)
        f.conflicto(
            _elegir(cliente, orden_id, BATERIA_B, motivo="Cambio."),
            "RECURSO_NO_DISPONIBLE",
        )
        assert f.archivo(tmp_path, orden_id) == antes
        assert _reservado(tmp_path)[BATERIA_B] == Decimal("1")


def test_no_se_elige_por_primera_vez_con_la_ejecucion_en_curso(
    cliente, directorio
):
    """Un requisito agregado al Tipo con la Ejecucion ya en curso no se
    elige ahora (la reserva ya se hizo): rige para la proxima."""
    orden_id, _ = _reservada(cliente, directorio)
    ruta = directorio / "catalogs" / "tipo_reparacion_requisitos.json"
    requisitos = json.loads(ruta.read_text(encoding="utf-8"))
    requisitos.append(
        TipoReparacionRequisito(
            id="REQ-NUEVO",
            tipo_reparacion_id=TIPO_BATERIA,
            categoria_id="CAT-002",
            cantidad=Decimal("1"),
            posicion=2,
        ).model_dump(mode="json")
    )
    escribir_json_atomico(ruta, requisitos)
    assert "antes de iniciar" in f.conflicto(
        _elegir(cliente, orden_id, ADHESIVO, requisito="REQ-NUEVO")
    )


def test_no_se_sustituye_una_pieza_ya_consumida(cliente, directorio):
    orden_id, ejecucion = _reservada(cliente, directorio)
    # Se interrumpe habiendo usado la bateria: queda consumida.
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion}/interrupt",
            json={
                "usuario_id": f.TECNICO,
                "motivo": "Falta una herramienta.",
                "insumos_utilizados": [
                    {"insumo_id": BATERIA_A, "cantidad": "1"}
                ],
            },
        )
    )
    orden = f.ok(cliente.get(f"/api/orders/{orden_id}"))
    assert f.detalle(orden, "DET-001")["estado"] == "DEFINIDO"
    assert _requisitos(orden)[REQ_BATERIA]["consumida"] is True
    antes = f.archivo(directorio, orden_id)
    assert "ya se consumio" in f.conflicto(
        _elegir(cliente, orden_id, BATERIA_B, motivo="Otra.")
    )
    assert f.archivo(directorio, orden_id) == antes


def test_un_trabajo_terminado_no_cambia_de_pieza(cliente, directorio):
    orden_id, ejecucion = _reservada(cliente, directorio)
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion}/complete",
            json={
                "usuario_id": f.TECNICO,
                "insumos_utilizados": [
                    {"insumo_id": BATERIA_A, "cantidad": "1"},
                    {"insumo_id": ADHESIVO, "cantidad": "1"},
                ],
            },
        )
    )
    assert "COMPLETO" in f.conflicto(
        _elegir(cliente, orden_id, BATERIA_B, motivo="Otra.")
    )


# --- Cambio de modelo y redefinicion -----------------------------------------


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
                    "falla_reportada": "No carga.",
                },
            },
        )
    )


def test_cambio_de_modelo_reemplaza_por_la_unica_compatible(cliente):
    orden_id = _orden(cliente)
    f.ok(_elegir(cliente, orden_id, BATERIA_A))
    orden = _cambiar_modelo(cliente, orden_id, IPHONE_11)
    piezas = f.detalle(orden, "DET-001")["piezas"]
    assert [(p["causa"], p["insumo_id"]) for p in piezas] == [
        ("ELECCION", BATERIA_A),
        ("CAMBIO_MODELO", BATERIA_11),
    ]
    assert piezas[1]["reemplaza_a"] == piezas[0]["id"]
    assert piezas[1]["modelo_equipo_id"] == IPHONE_11
    assert orden["historial"][-1]["accion"] == "REVISAR_PIEZA"


def test_cambio_de_modelo_sin_compatible_vuelve_a_pendiente(cliente):
    orden_id = _orden(cliente)
    f.ok(_elegir(cliente, orden_id, BATERIA_A))
    orden = _cambiar_modelo(cliente, orden_id, "MOD-0002")
    requisito = _requisitos(orden)[REQ_BATERIA]
    assert requisito["estado"] == "PENDIENTE"
    ultima = f.detalle(orden, "DET-001")["piezas"][-1]
    assert (ultima["causa"], ultima["insumo_id"]) == ("CAMBIO_MODELO", None)


def test_cambio_de_modelo_no_toca_una_pieza_reservada(cliente, directorio):
    """La API no cambia el modelo despues de confirmar la recepcion (y sin
    recepcion confirmada no se reserva): la regla se prueba en el
    service. Una pieza reservada se conserva con su reserva; la pantalla
    avisa que ya no es compatible y se sustituye a mano."""
    orden_id, _ = _reservada(cliente, directorio)
    orden = f.repo_ordenes(directorio).obtener(orden_id)
    orden.equipo.modelo_tecnico_id = IPHONE_11
    contexto = construir_contexto(Settings(data_dir=directorio))
    requisitos = requisitos_de_insumo(contexto)
    revisada = conciliar_piezas(
        orden,
        requisitos=requisitos,
        insumos=contexto.catalogos.listar_insumos(),
        usuario_id=f.RECEPCION,
        fecha=orden.updated_at,
    )
    assert revisada is orden
    (fila,) = piezas_de(
        orden,
        requisitos=requisitos,
        insumos=contexto.catalogos.listar_insumos(),
    )["DET-001"]
    assert (fila.insumo_id, fila.compatible_con_modelo, fila.reservada) == (
        BATERIA_A,
        False,
        True,
    )


def test_redefinir_a_otro_tipo_anula_las_piezas_del_anterior(
    cliente, directorio
):
    orden_id, ejecucion = _reservada(cliente, directorio)
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion}"
            "/requires-redefinition",
            json={
                "usuario_id": f.TECNICO,
                "motivo": "Es el flex, no la bateria.",
                "insumos_utilizados": [],
            },
        )
    )
    # La reserva de la pieza se libero con la Ejecucion (PROC-REP-210).
    assert _reservado(directorio) == {}
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Falla el flex."},
        )
    )
    orden = f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/redefine",
            json={"usuario_id": f.TECNICO, "tipo_reparacion_id": TIPO_FLEX},
        )
    )
    detalle = f.detalle(orden, "DET-001")
    assert detalle["tipo_reparacion_id"] == TIPO_FLEX
    causas = [(p["causa"], p["insumo_id"]) for p in detalle["piezas"]]
    assert causas[:2] == [("ELECCION", BATERIA_A), ("REDEFINICION", None)]
    # Las del Tipo nuevo con una sola compatible se eligen solas.
    assert sorted(causas[2:]) == [
        ("AUTOMATICA", ADHESIVO),
        ("AUTOMATICA", FLEX),
    ]
    assert set(_requisitos(orden)) == {REQ_FLEX, REQ_ADHESIVO}
    assert [
        (p["insumo_id"], p["cantidad_prevista"])
        for p in detalle["insumos_previstos"]
    ] == [(FLEX, "1"), (ADHESIVO, "2")]


# --- Administracion (PostgreSQL) y reglas puras ------------------------------


def test_la_administracion_de_insumos_necesarios_es_de_postgres(cliente):
    respuesta = cliente.put(
        f"/api/admin/repair-types/{TIPO_BATERIA}/supplies",
        json={"usuario_id": f.ADMINISTRADOR, "insumos": [], "requisitos": []},
    )
    assert "PostgreSQL" in f.conflicto(respuesta)
    lectura = f.ok(cliente.get("/api/admin/repair-types/supplies"))
    assert lectura["editable"] is False
    assert {r["id"] for r in lectura["requisitos"]} == {
        REQ_BATERIA,
        REQ_FLEX,
        REQ_ADHESIVO,
    }


ADMIN = Usuario(id="ADMIN-001", nombre="Admin", rol=RolUsuario.ADMINISTRADOR)
TIPO = TipoReparacion(
    id="TR-009",
    nombre="Cambio de modulo",
    precio=1,
    puntaje=1,
    garantia_dias=1,
)
CATEGORIAS = {
    "CAT-001": CategoriaInsumo(id="CAT-001", nombre="Modulos"),
    "CAT-002": CategoriaInsumo(
        id="CAT-002", nombre="OLED", padre_id="CAT-001"
    ),
    "CAT-003": CategoriaInsumo(id="CAT-003", nombre="Viejos", activo=False),
    "CAT-004": CategoriaInsumo(id="CAT-004", nombre="Sub", padre_id="CAT-003"),
}
INSUMOS = {
    "INS-1": Insumo(id="INS-1", codigo="A", nombre="A", stock_fisico=1),
    "INS-2": Insumo(
        id="INS-2",
        codigo="B",
        nombre="B",
        stock_fisico=1,
        modelos_compatibles=("MOD-0001",),
    ),
    "INS-3": Insumo(
        id="INS-3", codigo="C", nombre="C", stock_fisico=1, activo=False
    ),
}


def _necesarios(previstos=(), requisitos=(), *, actuales=(), req_actuales=()):
    contador = iter(range(1, 100))
    return insumos_necesarios(
        TIPO,
        previstos_actuales=list(actuales),
        requisitos_actuales=list(req_actuales),
        previstos=[(i, Decimal(c)) for i, c in previstos],
        requisitos=[(c, Decimal(q)) for c, q in requisitos],
        insumos=INSUMOS,
        categorias=CATEGORIAS,
        usuario=ADMIN,
        fecha="2026-11-24T12:00:00+00:00",
        nuevo_id=lambda: f"REQ-{next(contador)}",
    )


def test_insumos_necesarios_audita_previstos_y_requisitos():
    efectivos, requisitos, cambios = _necesarios(
        [("INS-1", "2")], [("CAT-002", "1"), ("CAT-001", "1.5")]
    )
    assert [(p.insumo_id, p.cantidad) for p in efectivos] == [
        ("INS-1", Decimal("2"))
    ]
    assert [(r.id, r.categoria_id, r.posicion) for r in requisitos] == [
        ("REQ-1", "CAT-002", 1),
        ("REQ-2", "CAT-001", 2),
    ]
    assert [(c.campo, c.valor_anterior, c.valor_nuevo) for c in cambios] == [
        ("insumos_previstos", None, "INS-1 x 2"),
        ("requisitos", None, "CAT-002 x 1; CAT-001 x 1.5"),
    ]
    assert {c.entidad.value for c in cambios} == {"TIPO_REPARACION"}


def test_insumos_necesarios_conserva_el_id_y_desactiva_lo_que_se_quita():
    actual = TipoReparacionRequisito(
        id="REQ-A",
        tipo_reparacion_id=TIPO.id,
        categoria_id="CAT-001",
        cantidad=Decimal("1"),
    )
    otro = actual.model_copy(update={"id": "REQ-B", "categoria_id": "CAT-002"})
    _, requisitos, cambios = _necesarios(
        requisitos=[("CAT-001", "3")], req_actuales=[actual, otro]
    )
    por_id = {r.id: r for r in requisitos}
    assert (por_id["REQ-A"].cantidad, por_id["REQ-A"].activo) == (
        Decimal("3"),
        True,
    )
    assert por_id["REQ-B"].activo is False
    (cambio,) = cambios
    assert (cambio.valor_anterior, cambio.valor_nuevo) == (
        "CAT-001 x 1; CAT-002 x 1",
        "CAT-001 x 3",
    )


@pytest.mark.parametrize(
    ("previstos", "requisitos", "mensaje"),
    [
        ([("INS-2", "1")], [], "solo sirve para algunos modelos"),
        ([("INS-3", "1")], [], "dado de baja"),
        ([("INS-9", "1")], [], "No existe el insumo"),
        ([("INS-1", "1"), ("INS-1", "2")], [], "repetido"),
        ([("INS-1", "0.0001")], [], "tres decimales"),
        ([], [("CAT-003", "1")], "dada de baja"),
        ([], [("CAT-004", "1")], "dada de baja"),
        ([], [("CAT-009", "1")], "No existe la categoria"),
        ([], [("CAT-001", "1"), ("CAT-001", "1")], "repetida"),
        ([], [], "no hay cambios"),
    ],
)
def test_insumos_necesarios_rechaza(previstos, requisitos, mensaje):
    with pytest.raises(PrecondicionInvalidaError, match=mensaje):
        _necesarios(previstos, requisitos)


def test_insumos_necesarios_conserva_lo_que_ya_estaba_aunque_no_se_admita():
    actual = TipoReparacionInsumos(
        tipo_reparacion_id=TIPO.id, insumo_id="INS-2", cantidad=Decimal("1")
    )
    efectivos, _, cambios = _necesarios([("INS-2", "2")], actuales=[actual])
    assert efectivos[0].cantidad == Decimal("2")
    assert cambios[0].valor_nuevo == "INS-2 x 2"


def test_insumos_necesarios_exige_el_permiso():
    with pytest.raises(PrecondicionInvalidaError, match="requiere el rol"):
        insumos_necesarios(
            TIPO,
            previstos_actuales=[],
            requisitos_actuales=[],
            previstos=[("INS-1", Decimal("1"))],
            requisitos=[],
            insumos=INSUMOS,
            categorias=CATEGORIAS,
            usuario=Usuario(id="T", nombre="T", rol=RolUsuario.TECNICO),
            fecha="2026-11-24T12:00:00+00:00",
            nuevo_id=lambda: "X",
        )
