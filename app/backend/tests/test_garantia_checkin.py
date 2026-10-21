"""Garantia por Detalle segun el check-in (UAT-009: check-in al cierre).

El check-in (si se pudieron verificar las funciones basicas del equipo) ya
no se pide al ingresar: se registra con la reparacion terminada y aprobada,
antes de entregar. Con check-in, 90 dias; sin check-in, 30, en cada
Detalle (sugerida). Recepcion o Coordinacion la pueden ajustar con motivo
antes de la entrega y el check-in nunca pisa ese ajuste. En Cliente
Externo con trabajos realizados no se entrega sin check-in. El plazo corre
desde la entrega y figura en el comprobante final y en la garantia.
"""

from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import OrigenOrden
from app.domain.politicas import politica_de
from app.main import create_app
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    COORDINADOR,
    PANTALLA,
    RECEPCION,
    TECNICO,
    agregar,
    aprobar,
    archivo,
    codigos,
    conflicto,
    detalle,
    ejecutar,
    notificar_pagar_entregar,
    ok,
    repo_ordenes,
    sembrar,
    tomar,
)
from tests.fixtures.custodia import RECEPTOR, registrar_checkin
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


def _lista(cliente, orden_id, *tipos) -> dict:
    """Ingresada, reparada y aprobada en control: REPARACION_LISTA."""
    tomar(cliente, orden_id, TECNICO)
    for indice, tipo in enumerate(tipos, start=1):
        ejecutar(cliente, orden_id, f"DET-{indice:03d}", tipo)
    for indice in range(1, len(tipos) + 1):
        orden = ok(aprobar(cliente, orden_id, f"DET-{indice:03d}"))
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    return orden


def _notificar_y_pagar(cliente, orden_id) -> dict:
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": RECEPCION,
                "monto": orden["resumen"]["saldo"],
                "metodo": "EFECTIVO",
            },
        )
    )
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _entregar(cliente, orden_id):
    return cliente.post(
        f"/api/orders/{orden_id}/deliver",
        json={"usuario_id": ADMINISTRADOR, **RECEPTOR},
    )


def _accion(orden, codigo) -> dict | None:
    return next(
        (a for a in orden["acciones_disponibles"] if a["codigo"] == codigo),
        None,
    )


# --- Ingreso: sin check-in ---------------------------------------------------


def test_el_ingreso_no_pide_checkin_y_rige_el_catalogo(cliente):
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id, BATERIA)
    agregar(cliente, orden_id, PANTALLA)
    orden = ok(agregar_otros(cliente, orden_id))
    assert orden["recepcion"]["datos"]["checkin"] is None
    # Hasta el check-in rige el plazo del Tipo (Otros: el reducido).
    assert _garantias(orden) == {
        "DET-001": (90, 90),
        "DET-002": (60, 60),
        "DET-003": (30, 30),
    }

    orden = ok(generar_ingreso(cliente, orden_id))

    assert orden["estado_workflow"] == "EN_COLA"
    (ingreso,) = del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")
    assert ingreso["contenido"]["checkin"] is None
    assert "REGISTRAR_CHECKIN" not in codigos(orden)


def test_el_alta_y_la_correccion_ignoran_un_checkin_enviado(cliente):
    """Un cliente viejo que todavia lo manda no lo registra."""
    respuesta = cliente.post(
        "/api/orders",
        json={
            "usuario_id": RECEPCION,
            "cliente": {"nombre": "Ana Gomez", "telefono": "341-555"},
            "equipo": {
                "marca": "Apple",
                "modelo": "iPhone 14",
                "falla_reportada": "La bateria dura poco.",
            },
            "recepcion": {"estado_fisico": "Sin golpes.", "checkin": True},
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    orden_id = respuesta.json()["id"]
    assert respuesta.json()["recepcion"]["datos"]["checkin"] is None

    orden = ok(
        cliente.put(
            f"/api/orders/{orden_id}/reception",
            json={
                "usuario_id": RECEPCION,
                "estado_fisico": "Raya leve.",
                "checkin": False,
            },
        )
    )

    assert orden["recepcion"]["datos"]["checkin"] is None
    assert orden["recepcion"]["registros_checkin"] == []


def test_sin_dato_de_checkin_rige_el_catalogo(cliente):
    """RT_INTERNO no registra check-in: conserva el plazo del Tipo."""
    orden_id = _crear_orden_rt(cliente)

    orden = agregar(cliente, orden_id, PANTALLA)

    assert _garantias(orden) == {"DET-001": (60, 60)}


def test_solo_cliente_externo_exige_el_checkin_para_entregar():
    externo = politica_de(OrigenOrden.CLIENTE_EXTERNO)
    interno = politica_de(OrigenOrden.RT_INTERNO)
    garantia = politica_de(OrigenOrden.RMA_GARANTIA_REPARACION)

    assert externo.requiere_checkin_en_entrega
    assert not interno.requiere_checkin_en_entrega
    assert not garantia.requiere_checkin_en_entrega


# --- Check-in antes de la entrega -------------------------------------------


@pytest.mark.parametrize(("realizado", "dias"), [(True, 90), (False, 30)])
def test_el_checkin_antes_de_entregar_asigna_la_garantia(
    cliente, reloj, realizado, dias
):
    orden_id = ingresada(cliente, BATERIA, PANTALLA)
    orden = _lista(cliente, orden_id, BATERIA, PANTALLA)
    accion = _accion(orden, "REGISTRAR_CHECKIN")
    assert accion is not None
    assert set(accion["roles"]) == {"ADMINISTRADOR", "RECEPCION"}
    reloj.avanzar(hours=2)

    orden = ok(registrar_checkin(cliente, orden_id, realizado))

    # Por Detalle, aunque el catalogo diga otra cosa.
    assert _garantias(orden) == {
        "DET-001": (dias, dias),
        "DET-002": (dias, dias),
    }
    assert orden["recepcion"]["datos"]["checkin"] is realizado
    assert orden["recepcion"]["registros_checkin"] == [
        {
            "realizado": realizado,
            "usuario_id": RECEPCION,
            "fecha": "2026-10-01T15:00:00Z",
        }
    ]
    # No mueve el proceso.
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    assert orden["current_process"] == "PROC-REP-240"


def test_el_checkin_no_pisa_un_ajuste_manual(cliente, tmp_path):
    orden_id = ingresada(cliente, BATERIA, PANTALLA)
    ok(_ajustar(cliente, orden_id, "DET-001", 120))
    _lista(cliente, orden_id, BATERIA, PANTALLA)

    orden = ok(registrar_checkin(cliente, orden_id, False))
    assert _garantias(orden) == {"DET-001": (120, 30), "DET-002": (30, 30)}

    # Se puede volver a registrar antes de entregar; el ajuste sigue.
    orden = ok(registrar_checkin(cliente, orden_id, True))
    assert _garantias(orden) == {"DET-001": (120, 90), "DET-002": (90, 90)}
    registros = orden["recepcion"]["registros_checkin"]
    assert [registro["realizado"] for registro in registros] == [False, True]
    (ajuste,) = detalle(orden, "DET-001")["ajustes_garantia"]
    assert ajuste["dias_nuevos"] == 120

    # Repetir el mismo resultado no agrega nada (reintento).
    antes = archivo(tmp_path, orden_id)
    ok(registrar_checkin(cliente, orden_id, True))
    assert archivo(tmp_path, orden_id) == antes


def test_un_ajuste_despues_del_checkin_se_conserva(cliente):
    orden_id = ingresada(cliente, BATERIA)
    _lista(cliente, orden_id, BATERIA)
    ok(registrar_checkin(cliente, orden_id, False))
    ok(_ajustar(cliente, orden_id, "DET-001", 60))

    orden = ok(registrar_checkin(cliente, orden_id, True))

    assert _garantias(orden) == {"DET-001": (60, 90)}


def test_el_checkin_solo_con_la_reparacion_lista_y_por_quien_entrega(
    cliente, tmp_path
):
    orden_id = ingresada(cliente, BATERIA, PANTALLA)
    antes = archivo(tmp_path, orden_id)
    # En cola: todavia no.
    mensaje = conflicto(registrar_checkin(cliente, orden_id))
    assert "reparacion lista" in mensaje
    assert archivo(tmp_path, orden_id) == antes
    tomar(cliente, orden_id, TECNICO)
    ejecutar(cliente, orden_id, "DET-001", BATERIA)
    ejecutar(cliente, orden_id, "DET-002", PANTALLA)
    orden = ok(aprobar(cliente, orden_id, "DET-001"))
    # Con un trabajo todavia sin aprobar, tampoco.
    assert "REGISTRAR_CHECKIN" not in codigos(orden)
    conflicto(registrar_checkin(cliente, orden_id))
    ok(aprobar(cliente, orden_id, "DET-002"))
    antes = archivo(tmp_path, orden_id)

    # Un tecnico o Coordinacion no lo registran.
    conflicto(registrar_checkin(cliente, orden_id, usuario=TECNICO))
    conflicto(registrar_checkin(cliente, orden_id, usuario=COORDINADOR))
    assert archivo(tmp_path, orden_id) == antes
    # Administracion si.
    orden = ok(registrar_checkin(cliente, orden_id, usuario=ADMINISTRADOR))
    (registro,) = orden["recepcion"]["registros_checkin"]
    assert registro["usuario_id"] == ADMINISTRADOR


def test_sin_checkin_no_se_entrega(cliente, tmp_path):
    orden_id = ingresada(cliente, BATERIA)
    _lista(cliente, orden_id, BATERIA)

    # Notificar y cobrar siguen igual, sin check-in.
    orden = _notificar_y_pagar(cliente, orden_id)

    entregar = _accion(orden, "ENTREGAR")
    assert entregar["bloqueo"] == "Falta registrar el check-in"
    assert _accion(orden, "REGISTRAR_CHECKIN") is not None
    # Presentacion: no "lista para entregar" sino pendiente del check-in;
    # el workflow sigue en REPARACION_LISTA.
    principal = orden["situacion"]
    assert orden["estado_workflow"] == "REPARACION_LISTA"
    assert principal["codigo"] == "PENDIENTE_CHECKIN"
    assert principal["titulo"] == (
        "Pendiente de verificación de funciones básicas"
    )
    assert [t["titulo"] for t in principal["tareas"]] == [
        "Registrar el check-in",
        "Entregar el equipo",
    ]
    antes = archivo(tmp_path, orden_id)
    assert "check-in" in conflicto(_entregar(cliente, orden_id))
    assert archivo(tmp_path, orden_id) == antes

    orden = ok(registrar_checkin(cliente, orden_id, False))
    assert _accion(orden, "ENTREGAR")["bloqueo"] is None
    assert orden["situacion"]["codigo"] == "LISTA_PARA_ENTREGAR"

    orden = ok(_entregar(cliente, orden_id))
    assert orden["estado_workflow"] == "ENTREGADA"
    # Entregada, el check-in ya no se registra.
    conflicto(registrar_checkin(cliente, orden_id, True), "ORDEN_CERRADA")


def test_una_orden_anterior_con_checkin_del_ingreso_se_entrega(
    cliente, tmp_path
):
    """El check-in registrado al ingresar (antes de UAT-009) vale."""
    orden_id = ingresada(cliente, BATERIA)
    repo = repo_ordenes(tmp_path)
    anterior = repo.obtener(orden_id)
    anterior.recepcion.datos.checkin = True
    repo.guardar(anterior)
    orden = _lista(cliente, orden_id, BATERIA)
    # Se puede volver a registrar, pero no hace falta.
    assert _accion(orden, "REGISTRAR_CHECKIN") is not None

    orden = _notificar_y_pagar(cliente, orden_id)

    assert _accion(orden, "ENTREGAR")["bloqueo"] is None
    orden = ok(_entregar(cliente, orden_id))
    assert orden["estado_workflow"] == "ENTREGADA"
    assert orden["recepcion"]["registros_checkin"] == []
    (final,) = del_tipo(cliente, orden_id, "COMPROBANTE_ENTREGA")
    assert final["contenido"]["checkin"] is True


# --- Ajuste manual -----------------------------------------------------------


def test_ajuste_manual_autorizado(cliente, tmp_path, reloj):
    orden_id = ingresada(cliente, BATERIA, PANTALLA)
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    assert ("AJUSTAR_GARANTIA", "DET-001") in complementarias(orden)
    reloj.avanzar(hours=1)

    ajustada = ok(_ajustar(cliente, orden_id, "DET-001", 180))

    assert _garantias(ajustada) == {"DET-001": (180, 90), "DET-002": (60, 60)}
    (ajuste,) = detalle(ajustada, "DET-001")["ajustes_garantia"]
    assert ajuste == {
        "dias_anteriores": 90,
        "dias_nuevos": 180,
        "motivo": MOTIVO,
        "usuario_id": RECEPCION,
        "fecha": "2026-10-01T14:00:00Z",
    }
    # Coordinacion tambien; un tecnico no.
    ok(_ajustar(cliente, orden_id, "DET-002", 75, usuario=COORDINADOR))
    antes = archivo(tmp_path, orden_id)
    conflicto(_ajustar(cliente, orden_id, "DET-002", 15, usuario=TECNICO))
    assert "ya tiene 75" in conflicto(
        _ajustar(cliente, orden_id, "DET-002", 75)
    )
    conflicto(_ajustar(cliente, orden_id, "DET-002", 15, motivo="  "))
    assert _ajustar(cliente, orden_id, "DET-002", 731).status_code == 422
    assert archivo(tmp_path, orden_id) == antes


# --- Desde la entrega --------------------------------------------------------


def test_el_plazo_corre_desde_la_entrega(cliente, reloj):
    orden_id = ingresada(cliente, BATERIA, PANTALLA)
    ok(_ajustar(cliente, orden_id, "DET-002", 45))
    reloj.avanzar(days=3)
    _lista(cliente, orden_id, BATERIA, PANTALLA)
    # La entrega llega bastante despues del fin tecnico; el check-in
    # (realizado) lo registra el atajo de entrega.
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
    # El comprobante final lleva el check-in y la garantia de cada trabajo.
    (final,) = del_tipo(cliente, orden_id, "COMPROBANTE_ENTREGA")
    assert final["contenido"]["checkin"] is True
    assert {
        trabajo["detalle_id"]: (
            trabajo["garantia_dias"],
            date.fromisoformat(trabajo["garantia_vence"]),
        )
        for trabajo in final["contenido"]["trabajos_realizados"]
    } == vencimientos
    # Despues de entregar ya no se ajusta.
    conflicto(_ajustar(cliente, orden_id, "DET-001", 30), "ORDEN_CERRADA")
