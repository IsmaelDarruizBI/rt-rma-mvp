"""Garantia por Detalle segun el check-in (iteracion 1 del UAT).

Con check-in, 90 dias; sin check-in, 30. Se completa sola en cada
Detalle (sugerida) y Recepcion o Coordinacion la pueden ajustar con
motivo antes de la entrega: se conservan la sugerida, la definitiva y
quien la cambio. El plazo corre desde la entrega, nunca desde la creacion
ni desde el fin de la reparacion, y figura en el certificado de garantia.
"""

from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.fixtures.api_salidas import (
    BATERIA,
    COORDINADOR,
    PANTALLA,
    RECEPCION,
    TECNICO,
    agregar,
    aprobar,
    archivo,
    conflicto,
    detalle,
    ejecutar,
    notificar_pagar_entregar,
    ok,
    sembrar,
    tomar,
)
from tests.fixtures.ingreso_inicial import (
    agregar_otros,
    complementarias,
    crear_con_recepcion,
    del_tipo,
    generar_ingreso,
    ingresada,
)
from tests.test_api_hp_rep_002 import _crear_orden_rt
from tests.test_documentos_custodia_entrega import INICIO, Reloj

MOTIVO = "Garantia extendida por convenio."


@pytest.fixture
def reloj():
    return Reloj(INICIO)


@pytest.fixture
def cliente(tmp_path, reloj):
    sembrar(tmp_path, "10")
    app = create_app(Settings(data_dir=tmp_path))
    app.state.contexto = replace(app.state.contexto, ahora=reloj)
    with TestClient(app) as test_client:
        yield test_client


def _ajustar(
    cliente, orden_id, detalle_id, dias, motivo=MOTIVO, usuario=RECEPCION
):
    return cliente.post(
        f"/api/orders/{orden_id}/details/{detalle_id}/warranty",
        json={"usuario_id": usuario, "dias": dias, "motivo": motivo},
    )


def _garantias(orden) -> dict[str, tuple[int, int | None]]:
    return {
        d["id"]: (d["garantia_dias"], d["garantia_dias_sugerida"])
        for d in orden["reparaciones_detail"]
    }


@pytest.mark.parametrize(("checkin", "dias"), [(True, 90), (False, 30)])
def test_se_completa_segun_el_checkin(cliente, checkin, dias):
    orden_id = crear_con_recepcion(cliente, checkin=checkin)
    agregar(cliente, orden_id, BATERIA)
    agregar(cliente, orden_id, PANTALLA)
    orden = ok(agregar_otros(cliente, orden_id))

    # Igual para todos los trabajos, aunque el catalogo diga otra cosa.
    assert _garantias(orden) == {
        "DET-001": (dias, dias),
        "DET-002": (dias, dias),
        "DET-003": (dias, dias),
    }


def test_sin_dato_de_checkin_rige_el_catalogo(cliente):
    """RT_INTERNO no registra check-in: conserva el plazo del Tipo."""
    orden_id = _crear_orden_rt(cliente)

    orden = agregar(cliente, orden_id, PANTALLA)

    assert _garantias(orden) == {"DET-001": (60, 60)}


def test_corregir_el_checkin_recalcula_la_sugerida(cliente):
    orden_id = crear_con_recepcion(cliente, checkin=True)
    agregar(cliente, orden_id)

    orden = ok(
        cliente.put(
            f"/api/orders/{orden_id}/reception",
            json={
                "usuario_id": RECEPCION,
                "estado_fisico": "Sin golpes.",
                "checkin": False,
            },
        )
    )

    assert _garantias(orden) == {"DET-001": (30, 30)}


def test_ajuste_manual_autorizado(cliente, tmp_path, reloj):
    orden_id = ingresada(cliente, BATERIA, PANTALLA)
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    assert ("AJUSTAR_GARANTIA", "DET-001") in complementarias(orden)
    reloj.avanzar(hours=1)

    ajustada = ok(_ajustar(cliente, orden_id, "DET-001", 180))

    assert _garantias(ajustada) == {"DET-001": (180, 90), "DET-002": (90, 90)}
    (ajuste,) = detalle(ajustada, "DET-001")["ajustes_garantia"]
    assert ajuste == {
        "dias_anteriores": 90,
        "dias_nuevos": 180,
        "motivo": MOTIVO,
        "usuario_id": RECEPCION,
        "fecha": "2026-10-01T14:00:00Z",
    }
    # Coordinacion tambien; un tecnico no.
    ok(_ajustar(cliente, orden_id, "DET-002", 60, usuario=COORDINADOR))
    antes = archivo(tmp_path, orden_id)
    conflicto(_ajustar(cliente, orden_id, "DET-002", 15, usuario=TECNICO))
    assert "ya tiene 60" in conflicto(
        _ajustar(cliente, orden_id, "DET-002", 60)
    )
    conflicto(_ajustar(cliente, orden_id, "DET-002", 15, motivo="  "))
    assert _ajustar(cliente, orden_id, "DET-002", 731).status_code == 422
    assert archivo(tmp_path, orden_id) == antes


def test_un_ajuste_manual_no_lo_pisa_el_checkin(cliente):
    orden_id = crear_con_recepcion(cliente, checkin=True)
    agregar(cliente, orden_id)
    ok(_ajustar(cliente, orden_id, "DET-001", 120))

    orden = ok(
        cliente.put(
            f"/api/orders/{orden_id}/reception",
            json={
                "usuario_id": RECEPCION,
                "estado_fisico": "Sin golpes.",
                "checkin": False,
            },
        )
    )

    garantia, sugerida = _garantias(orden)["DET-001"]
    assert garantia == 120
    assert sugerida == 30


def test_el_plazo_corre_desde_la_entrega(cliente, reloj):
    orden_id = ingresada(cliente, BATERIA, PANTALLA)
    ok(_ajustar(cliente, orden_id, "DET-002", 45))
    reloj.avanzar(days=3)
    tomar(cliente, orden_id, TECNICO)
    ejecutar(cliente, orden_id, "DET-001", BATERIA)
    ejecutar(cliente, orden_id, "DET-002", PANTALLA)
    ok(aprobar(cliente, orden_id, "DET-001"))
    ok(aprobar(cliente, orden_id, "DET-002"))
    # La entrega llega bastante despues del fin tecnico.
    reloj.avanzar(days=17)

    orden = notificar_pagar_entregar(cliente, orden_id)

    assert orden["estado_workflow"] == "ENTREGADA"
    assert not [
        c for c, _ in complementarias(orden) if c == "AJUSTAR_GARANTIA"
    ]
    (garantia,) = del_tipo(cliente, orden_id, "GARANTIA")
    contenido = garantia["contenido"]
    assert contenido["fecha_inicio"].startswith("2026-10-21")
    vencimientos = {
        cobertura["detalle_id"]: (
            cobertura["garantia_dias"],
            date.fromisoformat(cobertura["vence"]),
        )
        for cobertura in contenido["coberturas"]
    }
    assert vencimientos == {
        "DET-001": (90, date(2027, 1, 19)),
        "DET-002": (45, date(2026, 12, 5)),
    }
    # Despues de entregar ya no se ajusta.
    conflicto(_ajustar(cliente, orden_id, "DET-001", 30), "ORDEN_CERRADA")


def test_el_comprobante_de_ingreso_muestra_el_checkin(cliente):
    orden_id = crear_con_recepcion(cliente, checkin=False)
    agregar(cliente, orden_id)

    ok(generar_ingreso(cliente, orden_id))

    (ingreso,) = del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")
    assert ingreso["contenido"]["checkin"] is False
