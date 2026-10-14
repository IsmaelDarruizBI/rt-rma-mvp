"""E3: el override de stock nunca toca reservas de otras Ordenes.

Decision de negocio aprobada (auditoria funcional MVP v2, E3): un override
autorizado permite continuar una reparacion sin stock disponible
suficiente, pero nunca elimina, consume, libera ni reasigna reservas de
otras Ordenes. Antes de aplicarlo se informa el impacto (stock fisico,
reservado, disponible, requerido) y se exige confirmacion explicita.

    disponible = stock fisico - stock reservado

Ejemplo obligatorio de la decision:

    stock fisico 5; OR-A reserva 4 -> disponible 1
    OR-B consume 3 con override    -> fisico 2, reservado OR-A 4,
                                      disponible -2
    OR-A consume sus 4 reservadas  -> NO se bloquea; fisico -2 con el
                                      faltante fisico trazado

Antes de la correccion, el ultimo paso respondia 409 ("dejaria el stock
fisico en -2") y OR-A quedaba con la Ejecucion y la reserva abiertas.

    HTTP -> router -> application -> services -> repositories -> JSON
"""

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.application import construir_contexto
from app.core.config import Settings
from app.domain.models import (
    EstacionTrabajo,
    Insumo,
    RolUsuario,
    TipoReparacion,
    TipoReparacionEstacion,
    TipoReparacionInsumos,
    Usuario,
)
from app.main import create_app
from app.services import stock_disponible_global
from app.storage.json.base import escribir_json_atomico
from tests.fixtures.api_definicion import definir_y_finalizar

RECEPCION = "RECEP-001"
COORDINADOR = "COORD-001"
TECNICO_A = "TECH-001"
TECNICO_B = "TECH-002"
ESTACION = "EST-001"
INSUMO = "INS-001"
TIPO_CUATRO = "TR-CUATRO"  # consume 4 unidades
TIPO_TRES = "TR-TRES"  # consume 3 unidades
TIPO_UNA = "TR-UNA"  # consume 1 unidad
MOTIVO = "Cliente prioritario: el repuesto ya esta en camino."
CODIGO_CONFIRMACION = "CONFIRMACION_REQUERIDA"


def _sembrar(directorio, stock: str) -> None:
    tipos = {TIPO_CUATRO: "4", TIPO_TRES: "3", TIPO_UNA: "1"}
    catalogos = {
        "tipos_reparacion.json": [
            TipoReparacion(
                id=tipo,
                nombre=f"Reparacion con {cantidad} unidades",
                precio=Decimal("1000"),
                puntaje=1,
                garantia_dias=30,
            )
            for tipo, cantidad in tipos.items()
        ],
        "insumos.json": [
            Insumo(
                id=INSUMO,
                codigo="BAT",
                nombre="Bateria",
                stock_fisico=Decimal(stock),
            )
        ],
        "tipo_reparacion_insumos.json": [
            TipoReparacionInsumos(
                tipo_reparacion_id=tipo,
                insumo_id=INSUMO,
                cantidad=Decimal(cantidad),
            )
            for tipo, cantidad in tipos.items()
        ],
        "estaciones.json": [EstacionTrabajo(id=ESTACION, nombre="Mesa 1")],
        "tipo_reparacion_estaciones.json": [
            TipoReparacionEstacion(
                tipo_reparacion_id=tipo, estacion_id=ESTACION
            )
            for tipo in tipos
        ],
        "usuarios.json": [
            Usuario(
                id=RECEPCION, nombre="Recepcion", rol=RolUsuario.RECEPCION
            ),
            Usuario(
                id=COORDINADOR,
                nombre="Coordinacion",
                rol=RolUsuario.COORDINADOR_RMA,
            ),
            Usuario(id=TECNICO_A, nombre="Tecnico A", rol=RolUsuario.TECNICO),
            Usuario(id=TECNICO_B, nombre="Tecnico B", rol=RolUsuario.TECNICO),
        ],
    }
    for archivo, entidades in catalogos.items():
        escribir_json_atomico(
            directorio / "catalogs" / archivo,
            [entidad.model_dump(mode="json") for entidad in entidades],
        )


def _cliente(tmp_path, stock: str) -> TestClient:
    _sembrar(tmp_path, stock)
    return TestClient(create_app(Settings(data_dir=tmp_path)))


def _fijar_stock(tmp_path, stock: str) -> None:
    ruta = tmp_path / "catalogs" / "insumos.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos[0]["stock_fisico"] = stock
    escribir_json_atomico(ruta, datos)


def _archivo(tmp_path, orden_id: str) -> bytes:
    return (tmp_path / "ordenes" / f"{orden_id}.json").read_bytes()


def _repos(tmp_path):
    contexto = construir_contexto(Settings(data_dir=tmp_path))
    return contexto.ordenes, contexto.catalogos


def _stock_fisico(tmp_path) -> Decimal:
    _, catalogos = _repos(tmp_path)
    return catalogos.obtener_insumo(INSUMO).stock_fisico


def _disponible(tmp_path) -> Decimal:
    ordenes, catalogos = _repos(tmp_path)
    return stock_disponible_global(
        catalogos.obtener_insumo(INSUMO), ordenes.listar()
    )


def _movimientos(tmp_path, orden_id: str) -> list[dict]:
    ordenes, _ = _repos(tmp_path)
    return [
        m.model_dump(mode="json")
        for m in ordenes.obtener(orden_id).movimientos_insumo
    ]


def _definida(cliente, tipo) -> dict:
    orden_id = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "Cliente", "telefono": "341-1"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "No carga.",
            },
        },
    ).json()["id"]
    respuesta = definir_y_finalizar(
        cliente,
        orden_id,
        json={"usuario_id": RECEPCION, "tipo_reparacion_id": tipo},
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _iniciada(cliente, orden_id, tecnico) -> str:
    """Encola, toma e inicia DET-001: devuelve la Ejecucion abierta."""
    cliente.post(
        f"/api/orders/{orden_id}/queue",
        json={"usuario_id": COORDINADOR, "prioridad": 1},
    )
    tomada = cliente.post(
        f"/api/orders/{orden_id}/take",
        json={"usuario_id": tecnico, "estacion_id": ESTACION},
    )
    assert tomada.status_code == 200, tomada.text
    iniciada = cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/start",
        json={"usuario_id": tecnico},
    )
    assert iniciada.status_code == 200, iniciada.text
    (ejecucion,) = [
        e
        for e in iniciada.json()["ejecuciones"]
        if e["estado"] == "EN_PROGRESO"
    ]
    return ejecucion["id"]


def _completar(cliente, orden_id, ejecucion_id, tecnico, cantidad):
    return cliente.post(
        f"/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
        json={
            "usuario_id": tecnico,
            "insumos_utilizados": [
                {"insumo_id": INSUMO, "cantidad": cantidad}
            ],
        },
    )


def _impacto(cliente, orden_id):
    return cliente.get(
        f"/api/orders/{orden_id}/details/DET-001/resources/override-preview"
    )


def _override(cliente, orden_id, usuario=COORDINADOR, **extra):
    return cliente.post(
        f"/api/orders/{orden_id}/details/DET-001/resources/override",
        json={"usuario_id": usuario, "motivo": MOTIVO, **extra},
    )


# --- Ejemplo obligatorio de la decision --------------------------------------


def test_override_conserva_la_reserva_ajena_y_no_bloquea_su_consumo(tmp_path):
    with _cliente(tmp_path, stock="5") as cliente:
        orden_a = _definida(cliente, TIPO_CUATRO)["id"]
        ejecucion_a = _iniciada(cliente, orden_a, TECNICO_A)  # reserva 4
        assert _disponible(tmp_path) == Decimal("1")
        reservas_a = [
            m
            for m in _movimientos(tmp_path, orden_a)
            if m["tipo"] == "RESERVA"
        ]
        assert [m["cantidad"] for m in reservas_a] == ["4"]

        orden_b = _definida(cliente, TIPO_TRES)
        assert orden_b["current_process"] == "PROC-REP-100"
        orden_b = orden_b["id"]

        # Advertencia previa: fisico, reservado, disponible, requerido.
        impacto = _impacto(cliente, orden_b)
        assert impacto.status_code == 200, impacto.text
        cuerpo = impacto.json()
        (insumo,) = cuerpo["insumos"]
        assert {
            clave: insumo[clave]
            for clave in (
                "insumo_id",
                "stock_fisico",
                "reservado_otras_ordenes",
                "reservado_esta_orden",
                "disponible",
                "requerido",
                "disponible_resultante",
            )
        } == {
            "insumo_id": INSUMO,
            "stock_fisico": "5",
            "reservado_otras_ordenes": "4",
            "reservado_esta_orden": "0",
            "disponible": "1",
            "requerido": "3",
            "disponible_resultante": "-2",
        }
        assert cuerpo["deja_disponible_negativo"] is True
        assert cuerpo["hay_reservas_de_otras_ordenes"] is True
        assert "negativo" in cuerpo["advertencia"].lower()

        # Sin confirmacion explicita no se aplica nada.
        antes = _archivo(tmp_path, orden_b)
        sin_confirmar = _override(cliente, orden_b)
        assert sin_confirmar.status_code == 409, sin_confirmar.text
        assert sin_confirmar.json()["error"]["codigo"] == CODIGO_CONFIRMACION
        assert _archivo(tmp_path, orden_b) == antes

        # Confirmado: queda registrado quien, cuando, por que y el impacto.
        confirmado = _override(cliente, orden_b, confirmado=True)
        assert confirmado.status_code == 200, confirmado.text
        orden = confirmado.json()
        assert orden["estado_workflow"] == "HABILITADA"
        (autorizacion,) = [
            p
            for p in orden["historial"]
            if p["referencia_id"] == "ACC-REP-049"
        ]
        assert autorizacion["usuario_id"] == COORDINADOR
        assert autorizacion["fecha"] is not None
        assert MOTIVO in autorizacion["observacion"]
        assert "disponible resultante -2" in autorizacion["observacion"]

        # OR-B reserva 3 con override (sin tocar la reserva de OR-A).
        ejecucion_b = _iniciada(cliente, orden_b, TECNICO_B)
        assert _disponible(tmp_path) == Decimal("-2")
        assert [
            m
            for m in _movimientos(tmp_path, orden_a)
            if m["tipo"] == "RESERVA"
        ] == reservas_a

        # OR-B consume 3: fisico 5 -> 2; OR-A sigue reservando 4.
        respuesta = _completar(cliente, orden_b, ejecucion_b, TECNICO_B, "3")
        assert respuesta.status_code == 200, respuesta.text
        assert _stock_fisico(tmp_path) == Decimal("2")
        assert _disponible(tmp_path) == Decimal("-2")
        assert _movimientos(tmp_path, orden_a) == reservas_a

        # OR-A consume sus 4 reservadas: no se bloquea.
        respuesta = _completar(cliente, orden_a, ejecucion_a, TECNICO_A, "4")
        assert respuesta.status_code == 200, respuesta.text
        assert _stock_fisico(tmp_path) == Decimal("-2")
        assert _disponible(tmp_path) == Decimal("-2")

        movimientos_a = _movimientos(tmp_path, orden_a)
        consumos = [m for m in movimientos_a if m["tipo"] == "CONSUMO"]
        assert [
            (m["cantidad"], m["movimiento_origen_id"]) for m in consumos
        ] == [("4", reservas_a[0]["id"])]
        assert not [
            m for m in movimientos_a if m["tipo"] == "LIBERACION_RESERVA"
        ]

        # Trazabilidad del faltante fisico resultante.
        paso_210 = [
            p
            for p in respuesta.json()["historial"]
            if p["referencia_id"] == "PROC-REP-210"
        ][-1]
        assert "Faltante fisico" in paso_210["observacion"]
        assert "-2" in paso_210["observacion"]

        # Un reintento no duplica consumos ni vuelve a descontar.
        reintento = _completar(cliente, orden_a, ejecucion_a, TECNICO_A, "4")
        assert reintento.status_code == 409
        assert _movimientos(tmp_path, orden_a) == movimientos_a
        assert _stock_fisico(tmp_path) == Decimal("-2")


def test_la_reserva_previa_se_consume_aunque_el_override_deje_negativo(
    tmp_path,
):
    """El nucleo del bug, sin depender de la vista previa del override."""
    with _cliente(tmp_path, stock="5") as cliente:
        orden_a = _definida(cliente, TIPO_CUATRO)["id"]
        ejecucion_a = _iniciada(cliente, orden_a, TECNICO_A)
        orden_b = _definida(cliente, TIPO_TRES)["id"]
        assert _override(cliente, orden_b, confirmado=True).status_code == 200
        ejecucion_b = _iniciada(cliente, orden_b, TECNICO_B)
        assert (
            _completar(
                cliente, orden_b, ejecucion_b, TECNICO_B, "3"
            ).status_code
            == 200
        )

        respuesta = _completar(cliente, orden_a, ejecucion_a, TECNICO_A, "4")

        assert respuesta.status_code == 200, respuesta.text
        assert _stock_fisico(tmp_path) == Decimal("-2")
        orden = respuesta.json()
        assert orden["ejecuciones"][0]["estado"] == "COMPLETADO"
        assert orden["reparaciones_detail"][0]["estado"] == "COMPLETO"


# --- Advertencia y confirmacion ----------------------------------------------


def test_override_con_stock_disponible_suficiente(tmp_path):
    """Detalle bloqueado antes de que llegara stock: sin riesgo negativo."""
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _definida(cliente, TIPO_UNA)["id"]
        _fijar_stock(tmp_path, "10")

        cuerpo = _impacto(cliente, orden_id).json()
        (insumo,) = cuerpo["insumos"]
        assert (
            insumo["disponible"],
            insumo["requerido"],
            insumo["disponible_resultante"],
        ) == ("10", "1", "9")
        assert cuerpo["deja_disponible_negativo"] is False
        assert cuerpo["hay_reservas_de_otras_ordenes"] is False

        respuesta = _override(cliente, orden_id, confirmado=True)
        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["estado_workflow"] == "HABILITADA"


def test_override_con_stock_insuficiente_exige_confirmacion(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _definida(cliente, TIPO_UNA)["id"]
        antes = _archivo(tmp_path, orden_id)

        for extra in ({}, {"confirmado": False}):
            respuesta = _override(cliente, orden_id, **extra)
            assert respuesta.status_code == 409, respuesta.text
            error = respuesta.json()["error"]
            assert error["codigo"] == CODIGO_CONFIRMACION
            assert "requerido 1" in error["mensaje"]
        assert _archivo(tmp_path, orden_id) == antes

        respuesta = _override(cliente, orden_id, confirmado=True)
        assert respuesta.status_code == 200, respuesta.text


@pytest.mark.parametrize("usuario", [TECNICO_A, RECEPCION])
def test_override_sin_permisos_es_rechazado(tmp_path, usuario):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _definida(cliente, TIPO_UNA)["id"]
        antes = _archivo(tmp_path, orden_id)

        respuesta = _override(
            cliente, orden_id, usuario=usuario, confirmado=True
        )

        assert respuesta.status_code == 409, respuesta.text
        assert respuesta.json()["error"]["codigo"] == "PRECONDICION_INVALIDA"
        assert _archivo(tmp_path, orden_id) == antes


def test_la_vista_previa_de_un_detalle_inexistente_es_404(tmp_path):
    with _cliente(tmp_path, stock="0") as cliente:
        orden_id = _definida(cliente, TIPO_UNA)["id"]

        respuesta = cliente.get(
            f"/api/orders/{orden_id}/details/DET-999/resources/override-preview"
        )

        assert respuesta.status_code == 404
