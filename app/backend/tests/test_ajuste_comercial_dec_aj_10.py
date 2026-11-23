"""Ajuste Comercial: permisos, reversion, correccion, evidencia, recalculos,
historial y comprobantes (DEC-AJ-10, bloque 5 de la iteracion 2).

- D-10.1: cambiar o quitar un ajuste vigente exige el permiso de su clase y
  el de la nueva; el permiso del DESCUENTO no modifica una CORTESIA.
- D-10.2: revertir el vigente de un destino (vuelve a regir el anterior no
  revertido) y corregir (revertir + registrar, enlazados) con
  AJUSTE_REVERTIR; nunca toca pagos ni devoluciones.
- D-10.3: nada despues de la entrega.
- D-10.4: evidencia de cada registro y de los recalculos por redefinicion o
  cancelacion.
Los comprobantes (D-10.5) estan en ``test_ajuste_comercial_comprobantes``.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.models import (
    CausaRecalculo,
    ClaseAjuste,
    RolUsuario,
    TipoDescuento,
    TipoReparacion,
    Usuario,
)
from app.services import PrecondicionInvalidaError, permisos
from app.services.descuentos import aplicar_descuento, corregir_ajuste
from app.services.redefinicion import aplicar_redefinicion
from tests.fixtures import api_salidas as f
from tests.fixtures.custodia import entregar
from tests.fixtures.ingreso_inicial import ingresada

FECHA = datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path) as test_client:
        yield test_client


def _ajustar(
    cliente,
    orden_id,
    tipo,
    valor,
    *,
    detalle_id=None,
    clase="DESCUENTO",
    usuario=f.RECEPCION,
    motivo="Acuerdo comercial.",
):
    return cliente.post(
        f"/api/orders/{orden_id}/discount",
        json={
            "usuario_id": usuario,
            "tipo": tipo,
            "valor": valor,
            "motivo": motivo,
            "clase": clase,
            "detalle_id": detalle_id,
        },
    )


def _revertir(cliente, orden_id, ajuste_id, usuario=f.ADMINISTRADOR):
    return cliente.post(
        f"/api/orders/{orden_id}/adjustments/{ajuste_id}/revert",
        json={"usuario_id": usuario, "motivo": "Se cargo por error."},
    )


def _corregir(
    cliente,
    orden_id,
    ajuste_id,
    tipo,
    valor,
    clase="DESCUENTO",
    usuario=f.ADMINISTRADOR,
):
    return cliente.post(
        f"/api/orders/{orden_id}/adjustments/{ajuste_id}/correct",
        json={
            "usuario_id": usuario,
            "tipo": tipo,
            "valor": valor,
            "clase": clase,
            "motivo": "El valor acordado era otro.",
        },
    )


def _pagar(cliente, orden_id, monto):
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": f.RECEPCION,
                "monto": monto,
                "metodo": "EFECTIVO",
            },
        )
    )


def _total(orden) -> Decimal:
    return Decimal(orden["resumen"]["total"])


def _acciones_ajuste(orden) -> list[str]:
    return [
        paso["accion"]
        for paso in orden["historial"]
        if paso["referencia_id"] == "ACC-REP-072"
    ]


def _usuario(codigo, rol) -> Usuario:
    return Usuario(id=codigo, nombre=codigo, rol=rol)


# --- D-10.1: permisos -----------------------------------------------------


def test_el_permiso_del_descuento_no_modifica_una_cortesia(cliente, tmp_path):
    """Con la CORTESIA solo de Administracion, Recepcion (que tiene el
    DESCUENTO) no reemplaza ni quita la cortesia vigente."""
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    f.ok(
        _ajustar(
            cliente,
            orden_id,
            "PORCENTAJE",
            "10",
            clase="CORTESIA",
            usuario=f.ADMINISTRADOR,
        )
    )
    orden = f.repo_ordenes(tmp_path).obtener(orden_id)
    recepcion = _usuario(f.RECEPCION, RolUsuario.RECEPCION)
    with permisos.politica_vigente(
        lambda: {"CORTESIA": (RolUsuario.ADMINISTRADOR,)}
    ):
        for tipo, valor in (
            (TipoDescuento.IMPORTE, Decimal("1000")),
            (None, None),
        ):
            with pytest.raises(PrecondicionInvalidaError):
                aplicar_descuento(
                    orden,
                    tipo=tipo,
                    valor=valor,
                    motivo="Cambio.",
                    usuario=recepcion,
                    fecha=FECHA,
                )
        # Un descuento en otro destino (un trabajo) sigue permitido.
        nueva = aplicar_descuento(
            orden,
            tipo=TipoDescuento.IMPORTE,
            valor=Decimal("1000"),
            motivo="Promocion.",
            usuario=recepcion,
            fecha=FECHA,
            detalle_id="DET-001",
        )
    assert nueva.ajuste_de_detalle("DET-001").clase is ClaseAjuste.DESCUENTO


def test_cambiar_un_descuento_por_una_cortesia_exige_los_dos_permisos(
    cliente, tmp_path
):
    orden_id = f.definida(cliente, f.BATERIA)
    f.ok(_ajustar(cliente, orden_id, "PORCENTAJE", "10"))
    orden = f.repo_ordenes(tmp_path).obtener(orden_id)
    coordinador = _usuario(f.COORDINADOR, RolUsuario.COORDINADOR_RMA)
    with permisos.politica_vigente(
        lambda: {"DESCUENTO": (RolUsuario.RECEPCION,)}
    ):
        with pytest.raises(PrecondicionInvalidaError):
            aplicar_descuento(
                orden,
                tipo=TipoDescuento.PORCENTAJE,
                valor=Decimal("20"),
                motivo="Cortesia.",
                usuario=coordinador,
                fecha=FECHA,
                clase=ClaseAjuste.CORTESIA,
            )


# --- D-10.2: reversion ----------------------------------------------------


def test_revertir_el_vigente_vuelve_a_regir_el_anterior(cliente, tmp_path):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)  # 130000
    f.ok(_ajustar(cliente, orden_id, "PORCENTAJE", "10"))
    orden = f.ok(_ajustar(cliente, orden_id, "IMPORTE", "5000"))
    primero, segundo = orden["descuentos"]
    assert _total(orden) == Decimal("125000")

    # Solo el vigente: el anterior no se revierte.
    assert "no es el vigente" in f.conflicto(
        _revertir(cliente, orden_id, primero["id"])
    )
    # Solo con el permiso (por defecto, Administracion).
    antes = f.archivo(tmp_path, orden_id)
    for usuario in (f.RECEPCION, f.COORDINADOR):
        f.conflicto(_revertir(cliente, orden_id, segundo["id"], usuario))
    assert f.archivo(tmp_path, orden_id) == antes

    revertida = f.ok(_revertir(cliente, orden_id, segundo["id"]))

    assert _total(revertida) == Decimal("117000")
    assert revertida["resumen"]["descuento"]["descripcion"] == "10 %"
    reversion = revertida["descuentos"][1]["reversion"]
    assert reversion["usuario_id"] == f.ADMINISTRADOR
    assert reversion["motivo"] == "Se cargo por error."
    # El registro se conserva; no se agrega otro.
    assert len(revertida["descuentos"]) == 2
    assert _acciones_ajuste(revertida)[-1] == "REVERTIR_AJUSTE_COMERCIAL"
    paso = revertida["historial"][-1]
    assert paso["usuario_id"] == f.ADMINISTRADOR
    assert "Se cargo por error." in paso["observacion"]
    # No se revierte dos veces.
    assert "ya fue revertido" in f.conflicto(
        _revertir(cliente, orden_id, segundo["id"])
    )
    # Revertir tambien el primero deja la Orden sin ajuste.
    sin_ajuste = f.ok(_revertir(cliente, orden_id, primero["id"]))
    assert _total(sin_ajuste) == Decimal("130000")
    assert sin_ajuste["resumen"]["descuento"] is None
    # Un ajuste inexistente.
    assert _revertir(cliente, orden_id, "AJ-NO-EXISTE").status_code == 404


def test_si_el_anterior_quito_el_ajuste_no_queda_ninguno(cliente):
    orden_id = f.definida(cliente, f.BATERIA)
    f.ok(_ajustar(cliente, orden_id, "PORCENTAJE", "10"))
    f.ok(_ajustar(cliente, orden_id, None, None))
    orden = f.ok(_ajustar(cliente, orden_id, "IMPORTE", "5000"))
    ultimo = orden["descuentos"][-1]

    revertida = f.ok(_revertir(cliente, orden_id, ultimo["id"]))

    assert revertida["resumen"]["descuento"] is None
    assert _total(revertida) == Decimal("80000")
    # Un retiro no es un ajuste vigente: no se revierte.
    quitado = orden["descuentos"][1]
    assert quitado["tipo"] is None
    assert "no es el vigente" in f.conflicto(
        _revertir(cliente, orden_id, quitado["id"])
    )


def test_revertir_por_trabajo_no_toca_el_de_la_orden(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    f.ok(_ajustar(cliente, orden_id, "PORCENTAJE", "10", detalle_id="DET-002"))
    orden = f.ok(_ajustar(cliente, orden_id, "PORCENTAJE", "10"))
    del_trabajo = orden["descuentos"][0]

    revertida = f.ok(_revertir(cliente, orden_id, del_trabajo["id"]))

    assert revertida["resumen"]["ajustes_detalle"] == []
    assert revertida["resumen"]["descuento"]["descripcion"] == "10 %"
    # El de la Orden se aplica ahora sobre 130000.
    assert _total(revertida) == Decimal("117000")
    assert revertida["historial"][-1]["reparacion_detail_id"] == "DET-002"


def test_la_reversion_deja_saldo_a_favor_sin_tocar_los_pagos(cliente):
    orden_id = ingresada(cliente)  # 80000
    f.ok(_ajustar(cliente, orden_id, "IMPORTE", "20000"))
    orden = f.ok(_ajustar(cliente, orden_id, "IMPORTE", "5000"))
    pagada = _pagar(cliente, orden_id, "75000")
    pagos = pagada["pagos"]

    revertida = f.ok(
        _revertir(cliente, orden_id, orden["descuentos"][1]["id"])
    )

    assert _total(revertida) == Decimal("60000")
    assert Decimal(revertida["resumen"]["saldo"]) == Decimal("-15000")
    assert revertida["resumen"]["situacion_financiera"] == "SALDO_A_FAVOR"
    assert revertida["pagos"] == pagos
    finanzas = f.ok(cliente.get(f"/api/orders/{orden_id}/finances"))
    assert [m["tipo"] for m in finanzas["movimientos"]] == ["PAGO"]


def test_despues_de_la_entrega_no_se_revierte_ni_corrige(cliente, tmp_path):
    orden_id = ingresada(cliente)
    orden = f.ok(_ajustar(cliente, orden_id, "IMPORTE", "10000"))
    ajuste_id = orden["descuentos"][0]["id"]
    f.tomar(cliente, orden_id, f.TECNICO)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": f.RECEPCION}
        )
    )
    _pagar(cliente, orden_id, "70000")
    f.ok(entregar(cliente, orden_id, f.ADMINISTRADOR))
    antes = f.archivo(tmp_path, orden_id)

    f.conflicto(_revertir(cliente, orden_id, ajuste_id), "ORDEN_CERRADA")
    f.conflicto(
        _corregir(cliente, orden_id, ajuste_id, "IMPORTE", "1000"),
        "ORDEN_CERRADA",
    )
    assert f.archivo(tmp_path, orden_id) == antes


# --- D-10.2: correccion ---------------------------------------------------


def test_corregir_revierte_y_registra_el_correcto_enlazados(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    orden = f.ok(_ajustar(cliente, orden_id, "PORCENTAJE", "10"))
    equivocado = orden["descuentos"][0]

    corregida = f.ok(
        _corregir(
            cliente, orden_id, equivocado["id"], "IMPORTE", "3000", "CORTESIA"
        )
    )

    revertido, correcto = corregida["descuentos"]
    assert revertido["reversion"]["usuario_id"] == f.ADMINISTRADOR
    assert correcto["corrige_a"] == equivocado["id"]
    assert (correcto["clase"], correcto["tipo"], correcto["valor"]) == (
        "CORTESIA",
        "IMPORTE",
        "3000",
    )
    assert correcto["detalle_id"] is None
    assert _total(corregida) == Decimal("127000")
    # Una sola operacion en el historial.
    assert _acciones_ajuste(corregida) == [
        "APLICAR_AJUSTE_COMERCIAL",
        "CORREGIR_AJUSTE_COMERCIAL",
    ]


def test_una_correccion_invalida_no_cambia_nada(cliente, tmp_path):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    orden = f.ok(
        _ajustar(cliente, orden_id, "PORCENTAJE", "10", detalle_id="DET-002")
    )
    ajuste_id = orden["descuentos"][0]["id"]
    antes = f.archivo(tmp_path, orden_id)

    # Supera el precio del trabajo (50000).
    assert "no puede superar" in f.conflicto(
        _corregir(cliente, orden_id, ajuste_id, "IMPORTE", "50001")
    )
    # Recepcion no tiene el permiso de reversion.
    f.conflicto(
        _corregir(
            cliente,
            orden_id,
            ajuste_id,
            "IMPORTE",
            "1000",
            usuario=f.RECEPCION,
        )
    )
    assert f.archivo(tmp_path, orden_id) == antes


def test_corregir_exige_el_permiso_de_la_clase_nueva(cliente, tmp_path):
    orden_id = f.definida(cliente, f.BATERIA)
    orden_api = f.ok(_ajustar(cliente, orden_id, "PORCENTAJE", "10"))
    orden = f.repo_ordenes(tmp_path).obtener(orden_id)
    administrador = _usuario(f.ADMINISTRADOR, RolUsuario.ADMINISTRADOR)
    with permisos.politica_vigente(
        lambda: {"CORTESIA": (RolUsuario.RECEPCION,)}
    ):
        with pytest.raises(PrecondicionInvalidaError):
            corregir_ajuste(
                orden,
                ajuste_id=orden_api["descuentos"][0]["id"],
                tipo=TipoDescuento.PORCENTAJE,
                valor=Decimal("100"),
                clase=ClaseAjuste.CORTESIA,
                usuario=administrador,
                motivo="Era una cortesia.",
                fecha=FECHA,
            )


# --- D-10.4: evidencia y recalculos ----------------------------------------


def test_cada_registro_guarda_su_evidencia(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    f.ok(_ajustar(cliente, orden_id, "PORCENTAJE", "10", detalle_id="DET-002"))
    f.ok(_ajustar(cliente, orden_id, "IMPORTE", "5000"))
    orden = f.ok(_ajustar(cliente, orden_id, None, None))

    evidencia = [
        (r["precio_original"], r["importe_aplicado"], r["precio_final"])
        for r in orden["descuentos"]
    ]
    assert evidencia == [
        ("50000", "5000", "45000"),
        ("125000", "5000", "120000"),
        # Quitar: la base que vio quien lo quito, sin ajuste.
        ("125000", "0", "125000"),
    ]
    assert _acciones_ajuste(orden) == [
        "APLICAR_AJUSTE_COMERCIAL",
        "APLICAR_AJUSTE_COMERCIAL",
        "QUITAR_AJUSTE_COMERCIAL",
    ]
    cambio = f.ok(
        _ajustar(cliente, orden_id, "PORCENTAJE", "50", detalle_id="DET-002")
    )
    assert _acciones_ajuste(cambio)[-1] == "CAMBIAR_AJUSTE_COMERCIAL"


def test_cancelar_un_trabajo_deja_el_recalculo_de_los_ajustes(cliente):
    orden_id = f.definida(cliente, f.BATERIA, f.PANTALLA)
    f.ok(_ajustar(cliente, orden_id, "PORCENTAJE", "10", detalle_id="DET-002"))
    orden = f.ok(_ajustar(cliente, orden_id, "PORCENTAJE", "10"))
    del_trabajo, de_la_orden = (r["id"] for r in orden["descuentos"])

    cancelada = f.ok(f.cancelar_detalle(cliente, orden_id, "DET-002"))

    recalculos = [
        (
            r["ajuste_id"],
            r["causa"],
            r["precio_anterior"],
            r["precio_nuevo"],
            r["importe_anterior"],
            r["importe_nuevo"],
            r["usuario_id"],
        )
        for r in cancelada["recalculos_ajuste"]
    ]
    assert recalculos == [
        (del_trabajo, "CANCELACION", "50000", "0", "5000", "0", f.RECEPCION),
        (
            de_la_orden,
            "CANCELACION",
            "125000",
            "80000",
            "12500",
            "8000",
            f.RECEPCION,
        ),
    ]
    assert _acciones_ajuste(cancelada)[-2:] == [
        "RECALCULAR_AJUSTE_COMERCIAL",
        "RECALCULAR_AJUSTE_COMERCIAL",
    ]
    # No es un ajuste nuevo.
    assert len(cancelada["descuentos"]) == 2
    assert _total(cancelada) == Decimal("72000")


def test_redefinir_un_trabajo_deja_el_recalculo(cliente, tmp_path):
    orden_id = f.definida(cliente, f.BATERIA)
    f.ok(_ajustar(cliente, orden_id, "PORCENTAJE", "10", detalle_id="DET-001"))
    # Un importe fijo menor que el precio nuevo no cambia: sin recalculo.
    f.ok(_ajustar(cliente, orden_id, "IMPORTE", "1000"))
    orden = f.repo_ordenes(tmp_path).obtener(orden_id)
    tecnico = _usuario(f.TECNICO, RolUsuario.TECNICO)

    redefinida = aplicar_redefinicion(
        orden,
        detalle_id="DET-001",
        tipo_reparacion=TipoReparacion(
            id="TR-009",
            nombre="Cambio de conector",
            precio=Decimal("60000"),
            puntaje=5,
            garantia_dias=30,
        ),
        usuario=tecnico,
        fecha=FECHA,
    )

    (recalculo,) = redefinida.recalculos_ajuste
    assert recalculo.causa is CausaRecalculo.REDEFINICION
    assert recalculo.detalle_id == "DET-001"
    assert (recalculo.precio_anterior, recalculo.precio_nuevo) == (
        Decimal("80000"),
        Decimal("60000"),
    )
    assert (recalculo.importe_anterior, recalculo.importe_nuevo) == (
        Decimal("8000"),
        Decimal("6000"),
    )
    assert redefinida.historial[-1].accion == "RECALCULAR_AJUSTE_COMERCIAL"
    assert redefinida.historial[-2].accion == "REDEFINIR_DETALLE"
