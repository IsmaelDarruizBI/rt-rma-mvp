"""Comprobante de autorizacion: los trabajos que el cliente autorizo.

Lo emite Recepcion a pedido (nunca el proceso). Lista solo los Detalles
con una autorizacion vigente y sin cancelar, con su precio y el total; los
pendientes, rechazados y cancelados no figuran. Una version nueva solo se
emite si cambio lo autorizado, con el motivo calculado, y la anterior se
conserva sin cambios. El PDF se arma del snapshot: descargarlo no
modifica la Orden.
"""

from decimal import Decimal

from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    PANTALLA,
    RECEPCION,
    TECNICO,
    agregar,
    archivo,
    autorizar_todo,
    conflicto,
    decidir,
    definida,
    ejecutar,
    notificar_pagar_entregar,
    ok,
    por_revision,
    tomada,
)
from tests.test_api_hp_rep_002 import _crear_orden_rt
from tests.test_desistimiento_cliente import desistir
from tests.test_inventario_operativo import _cliente

ACCION = "EMITIR_COMPROBANTE_AUTORIZACION"


def _orden(cliente, orden_id) -> dict:
    return ok(cliente.get(f"/api/orders/{orden_id}"))


def _emitir(cliente, orden_id, usuario=RECEPCION):
    return cliente.post(
        f"/api/orders/{orden_id}/documents/authorization-receipt",
        json={"usuario_id": usuario},
    )


def _ofrecida(orden: dict) -> bool:
    return any(a["codigo"] == ACCION for a in orden["acciones_autorizacion"])


def _comprobantes(cliente, orden_id) -> list[dict]:
    documentos = ok(cliente.get(f"/api/orders/{orden_id}/documents"))
    return [
        documento
        for documento in documentos["emitidos"]
        if documento["tipo"] == "COMPROBANTE_AUTORIZACION"
    ]


def _pdf(cliente, orden_id, documento_id):
    return cliente.get(f"/api/orders/{orden_id}/documents/{documento_id}/pdf")


def _dos_trabajos_presentados(cliente) -> str:
    """Dos trabajos presentados al cliente, esperando su decision.

    En CLIENTE_EXTERNO la decision explicita es del camino de revision (y
    de las redefiniciones): el ingreso inicial los autoriza con el
    comprobante de ingreso, que reemplaza al primero de autorizacion.
    """
    return por_revision(cliente, BATERIA, PANTALLA)


def _autorizada(cliente) -> str:
    """Un trabajo presentado y autorizado por el cliente (revision)."""
    orden_id = definida(cliente, autorizar=False)
    autorizar_todo(cliente, orden_id)
    return orden_id


# --- Cuando se ofrece -------------------------------------------------------


def test_no_se_ofrece_antes_de_autorizar_ni_se_emite_solo(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente, autorizar=False)

        orden = _orden(cliente, orden_id)

        assert not _ofrecida(orden)
        assert _comprobantes(cliente, orden_id) == []
        mensaje = conflicto(_emitir(cliente, orden_id))
        assert "No hay trabajos autorizados" in mensaje

        autorizar_todo(cliente, orden_id)
        orden = _orden(cliente, orden_id)

        # Autorizar no lo emite: solo queda ofrecido.
        assert _ofrecida(orden)
        accion = next(
            a for a in orden["acciones_autorizacion"] if a["codigo"] == ACCION
        )
        assert accion["roles"] == ["RECEPCION"]
        assert _comprobantes(cliente, orden_id) == []


def test_rt_interno_no_lo_ofrece_ni_lo_emite(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _crear_orden_rt(cliente)
        agregar(cliente, orden_id)
        ok(
            cliente.post(
                f"/api/orders/{orden_id}/definition/finalize",
                json={"usuario_id": RECEPCION},
            )
        )

        assert not _ofrecida(_orden(cliente, orden_id))
        assert "no registra la autorizacion" in conflicto(
            _emitir(cliente, orden_id)
        )


def test_solo_recepcion_lo_emite(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _autorizada(cliente)
        antes = archivo(tmp_path, orden_id)

        for usuario in (TECNICO, ADMINISTRADOR):
            assert "requiere el rol RECEPCION" in conflicto(
                _emitir(cliente, orden_id, usuario)
            )

        assert archivo(tmp_path, orden_id) == antes


# --- Contenido ---------------------------------------------------------------


def test_autorizacion_parcial_lista_solo_lo_autorizado(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = por_revision(cliente, BATERIA, PANTALLA, PANTALLA)
        # DET-001 autorizado, DET-002 rechazado, DET-003 sin respuesta.
        ok(
            decidir(
                cliente,
                orden_id,
                {"DET-001": "AUTORIZADO", "DET-002": "RECHAZADO"},
                canal="TELEFONO",
            )
        )

        orden = ok(_emitir(cliente, orden_id))

        (documento,) = _comprobantes(cliente, orden_id)
        assert documento["id"] == f"{orden_id}-AUT-01"
        assert documento["version"] == 1
        assert documento["vigente"] is True
        assert documento["motivo"] is None
        assert documento["usuario_id"] == RECEPCION
        contenido = documento["contenido"]
        assert contenido["orden_id"] == orden_id
        assert contenido["cliente"]["nombre_apellido"] == "Cliente"
        assert contenido["equipo"]["modelo"] == "iPhone 14"
        (trabajo,) = contenido["trabajos"]
        assert trabajo["detalle_id"] == "DET-001"
        assert trabajo["version_definicion"] == 1
        assert trabajo["canal"] == "TELEFONO"
        assert trabajo["autorizado_en"] is not None
        assert trabajo["registrado_por"]["id"] == RECEPCION
        assert Decimal(trabajo["precio"]) == Decimal("80000")
        assert Decimal(contenido["total_autorizado"]) == Decimal("80000")
        assert "No es un comprobante de pago" in contenido["leyenda"]
        # Trazabilidad: la emision queda en el historial.
        paso = orden["historial"][-1]
        assert paso["referencia_id"] == "ACC-REP-060"
        assert paso["accion"] == "EMITIR_DOCUMENTO"
        assert paso["usuario_id"] == RECEPCION
        assert f"{orden_id}-AUT-01 (version 1)" in paso["observacion"]
        # Ya refleja lo autorizado: no se vuelve a ofrecer.
        assert not _ofrecida(orden)


def test_un_cancelado_despues_de_autorizar_no_figura(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _dos_trabajos_presentados(cliente)
        autorizar_todo(cliente, orden_id)
        ok(desistir(cliente, orden_id, "DET-002"))

        ok(_emitir(cliente, orden_id))

        (documento,) = _comprobantes(cliente, orden_id)
        trabajos = documento["contenido"]["trabajos"]
        assert [t["detalle_id"] for t in trabajos] == ["DET-001"]
        assert Decimal(documento["contenido"]["total_autorizado"]) == (
            Decimal("80000")
        )


# --- Versiones y duplicados --------------------------------------------------


def test_un_reintento_no_duplica_el_comprobante(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _autorizada(cliente)
        ok(_emitir(cliente, orden_id))
        guardado = archivo(tmp_path, orden_id)

        orden = ok(_emitir(cliente, orden_id))

        assert len(_comprobantes(cliente, orden_id)) == 1
        assert archivo(tmp_path, orden_id) == guardado
        assert not _ofrecida(orden)


def test_otro_trabajo_autorizado_da_una_version_nueva(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _dos_trabajos_presentados(cliente)
        ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
        ok(_emitir(cliente, orden_id))
        (primera,) = _comprobantes(cliente, orden_id)

        ok(decidir(cliente, orden_id, {"DET-002": "AUTORIZADO"}))
        assert _ofrecida(_orden(cliente, orden_id))
        orden = ok(_emitir(cliente, orden_id))

        anterior, nueva = _comprobantes(cliente, orden_id)
        # La anterior se conserva tal cual, solo deja de ser la vigente.
        assert anterior["id"] == primera["id"]
        assert anterior["contenido"] == primera["contenido"]
        assert anterior["vigente"] is False
        assert nueva["id"] == f"{orden_id}-AUT-02"
        assert nueva["version"] == 2
        assert nueva["vigente"] is True
        assert nueva["reemplaza_a"] == primera["id"]
        assert nueva["motivo"] == (
            "Cambiaron los trabajos autorizados: se autorizó «Cambio de "
            "pantalla»."
        )
        assert [t["detalle_id"] for t in nueva["contenido"]["trabajos"]] == [
            "DET-001",
            "DET-002",
        ]
        assert Decimal(nueva["contenido"]["total_autorizado"]) == Decimal(
            "130000"
        )
        assert (
            f"{orden_id}-AUT-02 (version 2)"
            in (orden["historial"][-1]["observacion"])
        )
        assert not _ofrecida(orden)


def test_el_comprobante_de_recepcion_sigue_igual(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _autorizada(cliente)
        ok(_emitir(cliente, orden_id))

        documentos = ok(cliente.get(f"/api/orders/{orden_id}/documents"))

        tipos = [documento["tipo"] for documento in documentos["emitidos"]]
        assert tipos == ["COMPROBANTE_RECEPCION", "COMPROBANTE_AUTORIZACION"]
        recepcion = documentos["emitidos"][0]
        assert recepcion["id"] == f"{orden_id}-REC-01"
        assert recepcion["vigente"] is True
        assert "trabajos" not in recepcion["contenido"]
        assert documentos["marcas"]["comprobante_recepcion"]["generado"]


# --- PDF ---------------------------------------------------------------------


def test_pdf_del_comprobante(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _autorizada(cliente)
        ok(_emitir(cliente, orden_id))
        guardado = archivo(tmp_path, orden_id)
        documento_id = f"{orden_id}-AUT-01"

        respuesta = _pdf(cliente, orden_id, documento_id)

        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"] == "application/pdf"
        assert (
            f'filename="{documento_id}.pdf"'
            in respuesta.headers["content-disposition"]
        )
        pdf = respuesta.content
        assert pdf.startswith(b"%PDF-1.4")
        assert pdf.rstrip().endswith(b"%%EOF")
        texto = pdf.decode("cp1252")
        assert "COMPROBANTE DE AUTORIZACIÓN" in texto
        assert f"Orden {orden_id}" in texto
        assert "No es un comprobante de pago." in texto
        assert "Total autorizado" in texto
        assert "$ 80.000,00" in texto
        assert "Firma" not in texto
        # Del snapshot: mismo PDF cada vez, sin tocar la Orden.
        assert _pdf(cliente, orden_id, documento_id).content == pdf
        assert archivo(tmp_path, orden_id) == guardado


def test_pdf_solo_del_comprobante_de_autorizacion(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _autorizada(cliente)

        respuesta = _pdf(cliente, orden_id, f"{orden_id}-REC-01")
        assert "no se descarga como PDF" in conflicto(respuesta)
        assert _pdf(cliente, orden_id, f"{orden_id}-AUT-09").status_code == (
            404
        )


# --- Identificadores de trazabilidad -----------------------------------------


def test_cada_emision_con_su_system_action_y_nunca_acc_rep_026(tmp_path):
    """REC a pedido: ACC-REP-002. AUT: ACC-REP-060. ACC-REP-026 es la
    entrega del equipo (hp-rep-001.yaml): ninguna emision la usa, tampoco
    al entregar (la entrega queda en PROC-REP-270 y EVT-REP-999)."""
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _dos_trabajos_presentados(cliente)
        rec_01 = _comprobantes_de(cliente, orden_id, "COMPROBANTE_RECEPCION")
        ok(
            cliente.post(
                f"/api/orders/{orden_id}/documents/reception-receipt",
                json={
                    "usuario_id": RECEPCION,
                    "motivo": "Recepcion confirmada",
                },
            )
        )
        ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
        ok(_emitir(cliente, orden_id))
        (aut_01,) = _comprobantes(cliente, orden_id)
        ok(decidir(cliente, orden_id, {"DET-002": "AUTORIZADO"}))
        ok(_emitir(cliente, orden_id))
        tomada(cliente, orden_id)
        ejecutar(cliente, orden_id, "DET-001", BATERIA)
        ejecutar(cliente, orden_id, "DET-002", PANTALLA)
        for detalle_id in ("DET-001", "DET-002"):
            ok(
                cliente.post(
                    f"/api/orders/{orden_id}/control/approve",
                    json={"usuario_id": RECEPCION, "detalle_id": detalle_id},
                )
            )
        entregada = notificar_pagar_entregar(cliente, orden_id)

        historial = entregada["historial"]
        assert entregada["estado_workflow"] == "ENTREGADA"
        assert "ACC-REP-026" not in [p["referencia_id"] for p in historial]
        recepcion = [
            p for p in historial if p["referencia_id"] == "ACC-REP-002"
        ]
        autorizacion = [
            p for p in historial if p["referencia_id"] == "ACC-REP-060"
        ]
        assert [p["observacion"].split(" ")[0] for p in recepcion] == [
            f"{orden_id}-REC-02"
        ]
        assert [p["observacion"].split(" ")[0] for p in autorizacion] == [
            f"{orden_id}-AUT-01",
            f"{orden_id}-AUT-02",
        ]
        assert all(
            p["tipo_referencia"] == "FUNCTIONAL_ACTION"
            for p in recepcion + autorizacion
        )
        # Versiones y snapshots: las anteriores siguen tal cual se emitieron.
        documentos = ok(cliente.get(f"/api/orders/{orden_id}/documents"))
        por_id = {d["id"]: d for d in documentos["emitidos"]}
        assert por_id[rec_01[0]["id"]]["contenido"] == rec_01[0]["contenido"]
        assert por_id[f"{orden_id}-REC-02"]["reemplaza_a"] == rec_01[0]["id"]
        assert por_id[aut_01["id"]]["contenido"] == aut_01["contenido"]
        assert por_id[aut_01["id"]]["vigente"] is False
        assert por_id[f"{orden_id}-AUT-02"]["vigente"] is True


def _comprobantes_de(cliente, orden_id, tipo) -> list[dict]:
    documentos = ok(cliente.get(f"/api/orders/{orden_id}/documents"))
    return [d for d in documentos["emitidos"] if d["tipo"] == tipo]
