"""Ingreso inicial simplificado de CLIENTE_EXTERNO (iteracion 1, UAT-008).

Recepcion crea la Orden, carga los trabajos con su precio y genera el
comprobante de ingreso y autorizacion. Ese unico comando confirma la
recepcion fisica, finaliza la definicion, registra la autorizacion
inicial de los trabajos incluidos, emite el comprobante y deja la Orden
en la cola con prioridad 4. Todo en una operacion: sin estados parciales
y sin duplicados ante un reintento.

    HTTP -> router -> application -> services -> repositories -> JSON
"""

import json
import threading

import pytest

from app.application import construir_contexto, generar_comprobante_ingreso
from app.core.config import Settings
from app.services import PrecondicionInvalidaError
from tests.fixtures.api_salidas import (
    BATERIA,
    COORDINADOR,
    PANTALLA,
    RECEPCION,
    TECNICO,
    agregar,
    archivo,
    cliente_http,
    codigos,
    conflicto,
    ids,
    ok,
)
from tests.fixtures.ingreso_inicial import (
    ESTADO_FISICO,
    NOTA_INTERNA,
    OBSERVACIONES,
    crear_con_recepcion,
    del_tipo,
    documentos,
    generar_ingreso,
    ingresada,
)
from tests.test_api_hp_rep_002 import _crear_orden_rt


@pytest.fixture
def cliente(tmp_path):
    with cliente_http(tmp_path) as test_client:
        yield test_client


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _acciones(orden: dict) -> list[str]:
    return [
        accion["codigo"]
        for grupo in (
            "acciones_disponibles",
            "acciones_autorizacion",
            "acciones_custodia",
        )
        for accion in orden[grupo]
    ]


# --- El camino normal --------------------------------------------------------


def test_antes_de_generar_no_hay_confirmacion_ni_autorizacion_sueltas(
    cliente,
):
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id)

    orden = _orden(cliente, orden_id)

    assert codigos(orden)[:2] == [
        "AGREGAR_DETALLE",
        "GENERAR_COMPROBANTE_INGRESO",
    ]
    acciones = _acciones(orden)
    assert "CONFIRMAR_RECEPCION" not in acciones
    assert "FINALIZAR_DEFINICION" not in acciones
    assert "REGISTRAR_DECISION_CLIENTE" not in acciones
    (generar,) = [
        a
        for a in orden["acciones_disponibles"]
        if a["codigo"] == "GENERAR_COMPROBANTE_INGRESO"
    ]
    assert generar["roles"] == ["RECEPCION"]
    assert generar["bloqueo"] is None


def test_generar_confirma_finaliza_autoriza_emite_y_encola(cliente):
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id, BATERIA)
    agregar(cliente, orden_id, PANTALLA)

    orden = ok(generar_ingreso(cliente, orden_id))

    # Custodia confirmada, definicion cerrada, trabajos autorizados.
    assert orden["custodia"]["estado"] == "EN_CUSTODIA"
    assert orden["recepcion"]["confirmacion"]["usuario_id"] == RECEPCION
    assert [
        d["estado_autorizacion"] for d in orden["reparaciones_detail"]
    ] == [
        "AUTORIZADO",
        "AUTORIZADO",
    ]
    for detalle in orden["reparaciones_detail"]:
        (decision,) = detalle["autorizaciones"]
        assert decision["canal"] == "PRESENCIAL"
        assert decision["usuario_id"] == RECEPCION
    # En la cola con la prioridad predeterminada, sin pasar por Coordinacion.
    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["prioridad"] == 4
    assert "ENCOLAR" not in codigos(orden)
    assert "TOMAR" in codigos(orden)
    # Cada evento queda en el historial, en el orden del proceso.
    pasos = ids(orden)
    for anterior, siguiente in [
        ("ACC-REP-024", "PROC-REP-050"),
        ("PROC-REP-050", "PROC-REP-060"),
        ("PROC-REP-060", "PROC-REP-046"),
        ("PROC-REP-047", "PROC-REP-080"),
        ("PROC-REP-090", "PROC-REP-140"),
        ("PROC-REP-140", "PROC-REP-150"),
        ("PROC-REP-150", "PROC-REP-170"),
    ]:
        assert pasos.index(anterior) < pasos.index(siguiente), pasos
    assert pasos.count("PROC-REP-046") == 2
    (prioridad,) = [
        p for p in orden["historial"] if p["referencia_id"] == "PROC-REP-150"
    ]
    assert prioridad["observacion"] == "4 (predeterminada)"
    (emision,) = [
        p for p in orden["historial"] if p["referencia_id"] == "ACC-REP-060"
    ]
    assert "ING-01" in emision["observacion"]
    assert emision["usuario_id"] == RECEPCION
    # Un solo documento inicial: no se emite un comprobante de recepcion
    # aparte ni uno de autorizacion.
    assert [d["tipo"] for d in documentos(cliente, orden_id)] == [
        "COMPROBANTE_INGRESO"
    ]
    custodia = [a["codigo"] for a in orden["acciones_custodia"]]
    assert "EMITIR_COMPROBANTE_RECEPCION" not in custodia
    assert "CONFIRMAR_RECEPCION" not in custodia
    # Desistir sigue disponible; decidir o emitir otro comprobante, no.
    assert {a["codigo"] for a in orden["acciones_autorizacion"]} <= {
        "DESISTIR_DETALLE",
        "DESISTIR_TODO",
    }


def test_el_comprobante_de_ingreso_tiene_lo_del_cliente_y_nada_interno(
    cliente,
):
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id, BATERIA)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/reception/notes",
            json={
                "usuario_id": RECEPCION,
                "texto": "Trae la caja original.",
            },
        )
    )
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/reception/notes",
            json={
                "usuario_id": RECEPCION,
                "texto": "Pidio descuento, no prometer nada.",
                "interna": True,
            },
        )
    )
    ok(generar_ingreso(cliente, orden_id))

    (documento,) = del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")

    contenido = documento["contenido"]
    assert documento["version"] == 1
    assert contenido["cliente"]["nombre"] == "Ana Gomez"
    assert contenido["equipo"]["modelo"] == "iPhone 14"
    assert contenido["estado_fisico"] == ESTADO_FISICO
    assert contenido["accesorios"] == ["Cargador"]
    assert contenido["observaciones"] == OBSERVACIONES
    assert contenido["notas"] == ["Trae la caja original."]
    # UAT-009: el check-in se registra antes de la entrega, no aca.
    assert contenido["checkin"] is None
    assert contenido["recepcion_fisica"] == "EN_CUSTODIA"
    assert contenido["confirmada_por"]["id"] == RECEPCION
    assert contenido["fecha_ingreso"] is not None
    assert documento["fecha_emision"] is not None
    (trabajo,) = contenido["trabajos"]
    assert trabajo["nombre"] == "Cambio de bateria"
    assert trabajo["precio"] == "80000"
    assert contenido["subtotal"] == "80000"
    assert contenido["descuento"] is None
    assert contenido["total"] == "80000"
    assert "recepción" in contenido["leyenda"]
    assert "autorización" in contenido["leyenda"]
    # Las notas internas no salen en el documento.
    texto = str(contenido)
    assert NOTA_INTERNA not in texto
    assert "no prometer nada" not in texto
    # Pero la app las conserva.
    orden = _orden(cliente, orden_id)
    assert orden["recepcion"]["datos"]["notas_internas"] == NOTA_INTERNA
    assert [n["interna"] for n in orden["recepcion"]["notas"]] == [False, True]


def test_el_pdf_del_comprobante_de_ingreso(cliente, tmp_path):
    orden_id = ingresada(cliente)
    (documento,) = del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")
    antes = archivo(tmp_path, orden_id)

    respuesta = cliente.get(
        f"/api/orders/{orden_id}/documents/{documento['id']}/pdf"
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"] == "application/pdf"
    assert respuesta.content.startswith(b"%PDF-")
    pdf = respuesta.content
    assert "COMPROBANTE DE INGRESO".encode("cp1252") in pdf
    assert ESTADO_FISICO.encode("cp1252") in pdf
    assert OBSERVACIONES.encode("cp1252") in pdf
    assert b"Cambio de bateria" in pdf
    assert NOTA_INTERNA.encode("cp1252") not in pdf
    # Descargarlo no registra nada: no prueba que el cliente lo recibio.
    assert archivo(tmp_path, orden_id) == antes


# --- Consistencia: reintentos, faltantes y alcance ---------------------------


def test_un_reintento_no_duplica_nada(cliente, tmp_path):
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id)
    primera = ok(generar_ingreso(cliente, orden_id))
    antes = archivo(tmp_path, orden_id)

    segunda = ok(generar_ingreso(cliente, orden_id))

    assert archivo(tmp_path, orden_id) == antes
    assert segunda["historial"] == primera["historial"]
    assert len(del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")) == 1


def test_doble_clic_simultaneo_emite_un_solo_comprobante(cliente, tmp_path):
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id)
    contexto = construir_contexto(Settings(data_dir=tmp_path))
    errores: list[Exception] = []

    def generar():
        try:
            generar_comprobante_ingreso(
                contexto, orden_id=orden_id, usuario_id=RECEPCION
            )
        except Exception as error:  # pragma: no cover - se informa abajo
            errores.append(error)

    hilos = [threading.Thread(target=generar) for _ in range(4)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert errores == []
    orden = _orden(cliente, orden_id)
    assert len(del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")) == 1
    assert ids(orden).count("PROC-REP-170") == 1
    assert ids(orden).count("ACC-REP-024") == 1


@pytest.mark.parametrize(
    ("datos", "falta"),
    [({"estado_fisico": None}, "estado fisico")],
)
def test_falta_informacion_obligatoria(cliente, tmp_path, datos, falta):
    orden_id = crear_con_recepcion(cliente, **datos)
    agregar(cliente, orden_id)
    orden = _orden(cliente, orden_id)
    (generar,) = [
        a
        for a in orden["acciones_disponibles"]
        if a["codigo"] == "GENERAR_COMPROBANTE_INGRESO"
    ]
    assert falta in generar["bloqueo"]
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(generar_ingreso(cliente, orden_id))

    assert falta in mensaje
    assert archivo(tmp_path, orden_id) == antes


def test_sin_trabajos_no_se_genera(cliente, tmp_path):
    orden_id = crear_con_recepcion(cliente)
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(generar_ingreso(cliente, orden_id))

    assert "trabajo" in mensaje
    assert archivo(tmp_path, orden_id) == antes


def test_solo_recepcion_lo_genera(cliente, tmp_path):
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    for usuario in (TECNICO, COORDINADOR):
        conflicto(generar_ingreso(cliente, orden_id, usuario=usuario))

    assert archivo(tmp_path, orden_id) == antes


def test_rt_interno_no_tiene_comprobante_de_ingreso(cliente, tmp_path):
    orden_id = _crear_orden_rt(cliente)
    agregar(cliente, orden_id)
    orden = _orden(cliente, orden_id)
    assert "GENERAR_COMPROBANTE_INGRESO" not in codigos(orden)
    assert "FINALIZAR_DEFINICION" in codigos(orden)

    conflicto(generar_ingreso(cliente, orden_id))


# --- Los comandos sueltos no eluden el comprobante ---------------------------


def _confirmar(cliente, orden_id, usuario=RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/reception/confirm",
        json={"usuario_id": usuario},
    )


def _finalizar(cliente, orden_id, usuario=RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/definition/finalize",
        json={"usuario_id": usuario},
    )


def _autorizar(cliente, orden_id, usuario=RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/authorizations",
        json={
            "usuario_id": usuario,
            "canal": "PRESENCIAL",
            "decisiones": [
                {
                    "detalle_id": "DET-001",
                    "version_definicion": 1,
                    "resultado": "AUTORIZADO",
                }
            ],
        },
    )


@pytest.mark.parametrize("con_trabajos", [False, True])
def test_en_el_ingreso_inicial_no_se_confirma_finaliza_ni_autoriza_suelto(
    cliente, tmp_path, con_trabajos
):
    orden_id = crear_con_recepcion(cliente)
    if con_trabajos:
        agregar(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    for respuesta in (
        _confirmar(cliente, orden_id),
        _finalizar(cliente, orden_id),
        _autorizar(cliente, orden_id),
    ):
        mensaje = conflicto(respuesta)
        assert "comprobante de ingreso" in mensaje

    # Nada quedo a medias: ni custodia, ni definicion, ni autorizacion.
    assert archivo(tmp_path, orden_id) == antes
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    assert orden["custodia"]["estado"] == "PENDIENTE_CONFIRMACION"
    assert not {"PROC-REP-050", "PROC-REP-080", "PROC-REP-046"} & set(
        ids(orden)
    )


def test_tampoco_los_roles_que_podian_confirmar(cliente, tmp_path):
    """Administracion confirmaba la recepcion: en el ingreso inicial
    tampoco puede hacerlo por separado."""
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    conflicto(_confirmar(cliente, orden_id, usuario="ADMIN-001"))

    assert archivo(tmp_path, orden_id) == antes


def test_despues_del_comprobante_no_se_duplica_nada(cliente, tmp_path):
    orden_id = ingresada(cliente)
    antes = archivo(tmp_path, orden_id)

    conflicto(_confirmar(cliente, orden_id))  # ya confirmada
    conflicto(_finalizar(cliente, orden_id))  # ya finalizada
    conflicto(_autorizar(cliente, orden_id))  # ya autorizada
    ok(generar_ingreso(cliente, orden_id))  # reintento: devuelve lo mismo

    assert archivo(tmp_path, orden_id) == antes
    orden = ok(cliente.get(f"/api/orders/{orden_id}"))
    assert ids(orden).count("ACC-REP-024") == 1
    assert ids(orden).count("PROC-REP-047") == 1
    (detalle,) = orden["reparaciones_detail"]
    assert len(detalle["autorizaciones"]) == 1
    assert [d["tipo"] for d in documentos(cliente, orden_id)] == [
        "COMPROBANTE_INGRESO"
    ]


def test_sin_check_in_se_genera_el_comprobante(cliente):
    """UAT-009: el ingreso no pide el check-in; hasta registrarlo, antes
    de la entrega, rige el plazo del Tipo."""
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id)
    orden = _orden(cliente, orden_id)
    (generar,) = [
        a
        for a in orden["acciones_disponibles"]
        if a["codigo"] == "GENERAR_COMPROBANTE_INGRESO"
    ]
    assert generar["bloqueo"] is None

    orden = ok(generar_ingreso(cliente, orden_id))

    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["recepcion"]["datos"]["checkin"] is None
    assert orden["reparaciones_detail"][0]["garantia_dias"] == 90


def test_los_otros_origenes_y_la_revision_siguen_igual(cliente):
    # RT_INTERNO: finaliza como siempre (sin confirmacion de recepcion).
    rt = _crear_orden_rt(cliente)
    agregar(cliente, rt)
    assert ok(_finalizar(cliente, rt))["estado_workflow"] == "HABILITADA"
    # CLIENTE_EXTERNO enviado a revision: confirmar, finalizar y la
    # decision del cliente son pasos explicitos.
    revisada = crear_con_recepcion(cliente)
    ok(
        cliente.post(
            f"/api/orders/{revisada}/send-to-review",
            json={"usuario_id": RECEPCION},
        )
    )
    ok(_confirmar(cliente, revisada))
    ok(
        cliente.post(
            f"/api/orders/{revisada}/technical-review",
            json={"usuario_id": TECNICO, "resultado": "Bateria agotada."},
        )
    )
    ok(
        cliente.post(
            f"/api/orders/{revisada}/review/details",
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": BATERIA},
        )
    )
    ok(_finalizar(cliente, revisada))
    orden = ok(_autorizar(cliente, revisada))
    assert orden["estado_workflow"] == "HABILITADA"
    assert "ENCOLAR" in codigos(orden)


def test_la_autorizacion_posterior_sigue_explicita(cliente):
    """Revision tecnica: los trabajos se autorizan con la decision del
    cliente, nunca solos."""
    orden_id = crear_con_recepcion(cliente)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/send-to-review",
            json={"usuario_id": RECEPCION},
        )
    )
    orden = _orden(cliente, orden_id)

    assert orden["estado_workflow"] == "EN_REVISION"
    assert "GENERAR_COMPROBANTE_INGRESO" not in codigos(orden)
    # Fuera del ingreso inicial, la confirmacion vuelve a ser un paso.
    assert "CONFIRMAR_RECEPCION" in [
        a["codigo"] for a in orden["acciones_custodia"]
    ]
    conflicto(generar_ingreso(cliente, orden_id))


def test_un_solo_comprobante_aunque_despues_se_autorice_mas(cliente):
    orden_id = ingresada(cliente)

    orden = _orden(cliente, orden_id)

    # Lo autorizado no cambio: no hay otro comprobante que emitir.
    assert "EMITIR_COMPROBANTE_AUTORIZACION" not in [
        a["codigo"] for a in orden["acciones_autorizacion"]
    ]
    respuesta = cliente.post(
        f"/api/orders/{orden_id}/documents/authorization-receipt",
        json={"usuario_id": RECEPCION},
    )
    assert respuesta.status_code in (200, 409), respuesta.text
    assert del_tipo(cliente, orden_id, "COMPROBANTE_AUTORIZACION") == []


def test_falla_a_mitad_de_camino_no_deja_estados_parciales(
    cliente, tmp_path, monkeypatch
):
    """Si la emision falla, ni la confirmacion ni la autorizacion quedan."""
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    def falla(*_, **__):
        raise PrecondicionInvalidaError("Fallo simulado al emitir.")

    monkeypatch.setattr(
        "app.application.ingreso_inicial.emitir_comprobante_ingreso", falla
    )

    conflicto(generar_ingreso(cliente, orden_id))

    assert archivo(tmp_path, orden_id) == antes


# --- Presentacion: pendiente de comprobante y autorizado ---------------------


def test_antes_del_comprobante_pendiente_y_despues_autorizado(cliente):
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id)

    orden = _orden(cliente, orden_id)

    # El estado interno no cambia; la presentacion se deriva.
    assert orden["ingreso_inicial"] is True
    (detalle,) = orden["reparaciones_detail"]
    assert detalle["estado_autorizacion"] == "PENDIENTE"
    assert detalle["pendiente_comprobante_ingreso"] is True
    assert detalle["autorizado_en_ingreso"] is False
    bandejas = ok(
        cliente.get("/api/work/inbox", params={"usuario_id": RECEPCION})
    )
    (definicion,) = [
        b for b in bandejas["bandejas"] if b["codigo"] == "DEFINICION"
    ]
    (item,) = definicion["ordenes"]
    assert item["trabajos"][0]["pendiente_comprobante_ingreso"] is True

    orden = ok(generar_ingreso(cliente, orden_id))

    assert orden["ingreso_inicial"] is False
    (detalle,) = orden["reparaciones_detail"]
    assert detalle["estado_autorizacion"] == "AUTORIZADO"
    assert detalle["pendiente_comprobante_ingreso"] is False
    assert detalle["autorizado_en_ingreso"] is True


def test_una_autorizacion_posterior_no_es_la_del_ingreso(cliente):
    """Redefinido despues del ingreso, el trabajo vuelve a esperar al
    cliente con la representacion de siempre."""
    orden_id = ingresada(cliente)
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/take",
            json={"usuario_id": TECNICO, "estacion_id": "EST-001"},
        )
    )
    ejecucion = ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/start",
            json={"usuario_id": TECNICO},
        )
    )["ejecuciones"][0]["id"]
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/executions/{ejecucion}"
            "/requires-redefinition",
            json={
                "usuario_id": TECNICO,
                "insumos_utilizados": [],
                "motivo": "Tambien falla la pantalla.",
            },
        )
    )
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/technical-review",
            json={"usuario_id": TECNICO, "resultado": "Pantalla partida"},
        )
    )
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/details/DET-001/redefine",
            json={"usuario_id": RECEPCION, "tipo_reparacion_id": PANTALLA},
        )
    )

    (detalle,) = orden["reparaciones_detail"]
    assert detalle["version_definicion"] == 2
    assert detalle["estado_autorizacion"] == "PENDIENTE"
    assert detalle["pendiente_comprobante_ingreso"] is False
    assert detalle["autorizado_en_ingreso"] is False
    orden = ok(
        cliente.post(
            f"/api/orders/{orden_id}/authorizations",
            json={
                "usuario_id": RECEPCION,
                "canal": "WHATSAPP",
                "decisiones": [
                    {
                        "detalle_id": "DET-001",
                        "version_definicion": 2,
                        "resultado": "AUTORIZADO",
                    }
                ],
            },
        )
    )
    (detalle,) = orden["reparaciones_detail"]
    assert detalle["estado_autorizacion"] == "AUTORIZADO"
    assert detalle["autorizado_en_ingreso"] is False


# --- Ordenes anteriores: sin estados sin salida ------------------------------


def _intake(cliente, orden_id, **extra):
    return cliente.post(
        f"/api/orders/{orden_id}/documents/intake-receipt",
        json={"usuario_id": RECEPCION, **extra},
    )


def test_una_orden_anterior_confirmada_sin_checkin_genera_el_comprobante(
    cliente, tmp_path
):
    """Anterior a la iteracion 1: recepcion confirmada sin check-in. Ya no
    se corrige el ingreso ni hace falta: el check-in es del cierre."""
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id)
    ruta = tmp_path / "ordenes" / f"{orden_id}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["recepcion"]["confirmacion"] = {
        "usuario_id": RECEPCION,
        "fecha": datos["created_at"],
        "observaciones": None,
    }
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    orden = ok(_intake(cliente, orden_id))

    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["recepcion"]["datos"]["checkin"] is None
    (ingreso,) = del_tipo(cliente, orden_id, "COMPROBANTE_INGRESO")
    assert ingreso["contenido"]["checkin"] is None
    # La recepcion ya estaba confirmada: no se vuelve a confirmar.
    assert "ACC-REP-024" not in ids(orden)


def test_el_comprobante_no_registra_un_checkin_enviado(cliente):
    """Un cliente viejo que todavia lo manda: se ignora."""
    orden_id = crear_con_recepcion(cliente)
    agregar(cliente, orden_id)

    orden = ok(_intake(cliente, orden_id, checkin=False))

    assert orden["estado_workflow"] == "EN_COLA"
    assert orden["recepcion"]["datos"]["checkin"] is None
    assert orden["reparaciones_detail"][0]["garantia_dias"] == 90


def test_si_falta_otro_dato_no_queda_nada_a_medias(cliente, tmp_path):
    orden_id = crear_con_recepcion(cliente, estado_fisico=None)
    agregar(cliente, orden_id)
    antes = archivo(tmp_path, orden_id)

    mensaje = conflicto(_intake(cliente, orden_id))

    assert "estado fisico" in mensaje
    assert archivo(tmp_path, orden_id) == antes
