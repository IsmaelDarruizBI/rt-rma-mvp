"""Validaciones de los modelos de dominio, independientes del escenario."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.models import (
    Cliente,
    Equipo,
    EstadoPago,
    EstadoReparacionDetail,
    EstadoWorkflow,
    HistorialWorkflow,
    MovimientoInsumo,
    OrdenReparacion,
    OrigenOrden,
    Pago,
    ReparacionDetail,
    ResumenPago,
    TipoMovimientoInsumo,
    TipoPago,
    TipoReparacion,
    TipoReparacionInsumos,
)

AHORA = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)


def _pago(identificador: str, monto: str) -> Pago:
    """Pago minimo valido, para armar escenarios de cobro."""
    return Pago(
        id=identificador,
        monto=Decimal(monto),
        tipo_pago=TipoPago.PAGO,
        metodo="EFECTIVO",
        usuario_id="ADMIN-001",
        fecha=AHORA,
    )


def _detalle(identificador: str, precio: str) -> ReparacionDetail:
    """Detalle minimo valido, con su snapshot de precio."""
    return ReparacionDetail(
        id=identificador,
        tipo_reparacion_id="TREP-001",
        precio=Decimal(precio),
        puntaje=10,
        garantia_dias=90,
    )


def _orden_minima(
    identificador: str,
    detalles: list[ReparacionDetail] | None = None,
    pagos: list[Pago] | None = None,
) -> OrdenReparacion:
    """Orden valida, con los Detalles y pagos que el test necesite."""
    return OrdenReparacion(
        id=identificador,
        origen=OrigenOrden.CLIENTE_EXTERNO,
        estado_workflow=EstadoWorkflow.REQUERIMIENTO,
        current_process="PROC-REP-040",
        cliente=Cliente(
            id="CLI-001",
            nombre="Cliente",
            telefono="341-0000000",
        ),
        equipo=Equipo(
            id="EQP-001",
            marca="Apple",
            modelo="iPhone 14",
            falla_reportada="No carga.",
        ),
        reparaciones_detail=detalles or [],
        resumen_pago=ResumenPago(pagos=pagos or []),
        created_at=AHORA,
        updated_at=AHORA,
    )


# 1) Cliente requiere nombre y telefono.


def test_cliente_requiere_nombre_y_telefono():
    with pytest.raises(ValidationError) as error:
        Cliente(id="CLI-001")

    campos_faltantes = {e["loc"][0] for e in error.value.errors()}
    assert campos_faltantes == {"nombre", "telefono"}


def test_cliente_email_es_opcional():
    cliente = Cliente(id="CLI-001", nombre="Cliente", telefono="341-0000000")

    assert cliente.email is None


# 2) Importes negativos son rechazados.


def test_precio_negativo_en_tipo_reparacion_es_rechazado():
    with pytest.raises(ValidationError):
        TipoReparacion(
            id="TREP-001",
            nombre="Cambio de bateria",
            precio=Decimal("-1"),
            puntaje=10,
            garantia_dias=90,
        )


def test_precio_negativo_en_detalle_es_rechazado():
    with pytest.raises(ValidationError):
        _detalle("DET-001", "-1")


def test_monto_de_pago_debe_ser_mayor_a_cero():
    with pytest.raises(ValidationError):
        _pago("PAG-001", "0")

    with pytest.raises(ValidationError):
        _pago("PAG-002", "-100")


# 3) Cantidades de insumo <= 0 son rechazadas.


@pytest.mark.parametrize("cantidad", ["0", "-1"])
def test_cantidad_de_insumo_no_positiva_es_rechazada(cantidad: str):
    with pytest.raises(ValidationError):
        TipoReparacionInsumos(
            tipo_reparacion_id="TREP-001",
            insumo_id="INS-001",
            cantidad=Decimal(cantidad),
        )


def test_cantidad_de_insumo_positiva_es_aceptada():
    relacion = TipoReparacionInsumos(
        tipo_reparacion_id="TREP-001",
        insumo_id="INS-001",
        cantidad=Decimal("1"),
    )

    assert relacion.cantidad == Decimal("1")


# Ciclo tecnico del Detalle: sin RESERVADO ni APROBADO.


def test_estado_detalle_solo_tiene_el_ciclo_tecnico():
    valores = {estado.value for estado in EstadoReparacionDetail}

    # CANCELADO (PROC-REP-300/305, BR-REP-014) es el segundo estado
    # terminal del ciclo tecnico; reserva y aprobacion siguen afuera.
    assert valores == {"DEFINIDO", "EN_PROGRESO", "COMPLETO", "CANCELADO"}


def test_estado_detalle_no_incluye_reservado():
    assert not hasattr(EstadoReparacionDetail, "RESERVADO")

    with pytest.raises(ValueError):
        EstadoReparacionDetail("RESERVADO")


def test_estado_detalle_no_incluye_aprobado():
    assert not hasattr(EstadoReparacionDetail, "APROBADO")

    with pytest.raises(ValueError):
        EstadoReparacionDetail("APROBADO")


def test_detalle_nace_definido():
    assert _detalle("DET-001", "80000").estado is (
        EstadoReparacionDetail.DEFINIDO
    )


# 4) pagado se calcula en ResumenPago, que ya no almacena el total.


def test_pagado_suma_los_pagos_registrados():
    resumen = ResumenPago(
        pagos=[_pago("PAG-001", "30000"), _pago("PAG-002", "20000")],
    )

    assert resumen.pagado == Decimal("50000")


def test_pagado_sin_pagos_es_cero():
    assert ResumenPago().pagado == Decimal("0")


def test_resumen_pago_no_almacena_total():
    assert "total" not in ResumenPago.model_fields
    # Pagos y devoluciones de dinero (BR-REP-038): ningun total propio.
    assert set(ResumenPago.model_fields) == {"pagos", "devoluciones"}


# 5) total y saldo derivan en OrdenReparacion.


def test_total_deriva_de_los_detalles():
    orden = _orden_minima(
        "OR-001",
        detalles=[_detalle("DET-001", "80000"), _detalle("DET-002", "20000")],
    )

    assert orden.total == Decimal("100000")


def test_total_sin_detalles_es_cero():
    assert _orden_minima("OR-001").total == Decimal("0")


def test_saldo_es_total_menos_pagado():
    orden = _orden_minima(
        "OR-001",
        detalles=[_detalle("DET-001", "80000")],
        pagos=[_pago("PAG-001", "30000")],
    )

    assert orden.saldo == Decimal("50000")


def test_cambiar_el_precio_de_un_detalle_actualiza_total_y_saldo():
    orden = _orden_minima(
        "OR-001",
        detalles=[_detalle("DET-001", "80000")],
        pagos=[_pago("PAG-001", "80000")],
    )

    assert orden.total == Decimal("80000")
    assert orden.saldo == Decimal("0")
    assert orden.estado_pago is EstadoPago.PAGADO

    # Sin tocar ResumenPago: no hay nada que sincronizar a mano.
    orden.reparaciones_detail[0].precio = Decimal("120000")

    assert orden.total == Decimal("120000")
    assert orden.saldo == Decimal("40000")
    assert orden.estado_pago is EstadoPago.PARCIAL


def test_agregar_un_detalle_actualiza_total_y_saldo():
    orden = _orden_minima(
        "OR-001",
        detalles=[_detalle("DET-001", "80000")],
        pagos=[_pago("PAG-001", "80000")],
    )

    orden.reparaciones_detail.append(_detalle("DET-002", "20000"))

    assert orden.total == Decimal("100000")
    assert orden.saldo == Decimal("20000")
    assert orden.estado_pago is EstadoPago.PARCIAL


# 6) estado_pago: PENDIENTE -> PARCIAL -> PAGADO.


def test_estado_pago_pendiente_sin_detalles():
    """Sin Detalles no hay nada que cobrar todavia: no esta pagada."""
    orden = _orden_minima("OR-001")

    assert orden.total == Decimal("0")
    assert orden.saldo == Decimal("0")
    assert orden.estado_pago is EstadoPago.PENDIENTE


def test_estado_pago_pagado_con_detalle_de_precio_cero():
    """Con Detalles definidos, un total de 0 si esta saldado."""
    orden = _orden_minima("OR-001", detalles=[_detalle("DET-001", "0")])

    assert orden.total == Decimal("0")
    assert orden.saldo == Decimal("0")
    assert orden.estado_pago is EstadoPago.PAGADO


def test_estado_pago_distingue_sin_detalles_de_total_cero():
    sin_detalles = _orden_minima("OR-001")
    con_detalle_gratuito = _orden_minima(
        "OR-002",
        detalles=[_detalle("DET-001", "0")],
    )

    assert sin_detalles.total == con_detalle_gratuito.total == Decimal("0")
    assert sin_detalles.saldo == con_detalle_gratuito.saldo == Decimal("0")
    assert sin_detalles.estado_pago is not con_detalle_gratuito.estado_pago


def test_estado_pago_pendiente_sin_pagos():
    orden = _orden_minima("OR-001", detalles=[_detalle("DET-001", "80000")])

    assert orden.estado_pago is EstadoPago.PENDIENTE


def test_estado_pago_parcial_con_saldo_pendiente():
    orden = _orden_minima(
        "OR-001",
        detalles=[_detalle("DET-001", "80000")],
        pagos=[_pago("PAG-001", "30000")],
    )

    assert orden.estado_pago is EstadoPago.PARCIAL


def test_estado_pago_pagado_con_saldo_cero():
    orden = _orden_minima(
        "OR-001",
        detalles=[_detalle("DET-001", "80000")],
        pagos=[_pago("PAG-001", "80000")],
    )

    assert orden.saldo == Decimal("0")
    assert orden.estado_pago is EstadoPago.PAGADO


def test_estado_pago_recorre_los_tres_estados():
    detalles = [_detalle("DET-001", "80000")]

    pendiente = _orden_minima("OR-001", detalles=list(detalles))
    parcial = _orden_minima(
        "OR-002",
        detalles=[_detalle("DET-001", "80000")],
        pagos=[_pago("PAG-001", "30000")],
    )
    pagado = _orden_minima(
        "OR-003",
        detalles=[_detalle("DET-001", "80000")],
        pagos=[_pago("PAG-001", "30000"), _pago("PAG-002", "50000")],
    )

    estados = [pendiente.estado_pago, parcial.estado_pago, pagado.estado_pago]

    assert estados == [
        EstadoPago.PENDIENTE,
        EstadoPago.PARCIAL,
        EstadoPago.PAGADO,
    ]


# MovimientoInsumo: usuario opcional e inmutabilidad.


def test_movimiento_acepta_usuario_none():
    movimiento = MovimientoInsumo(
        id="MOV-001",
        tipo=TipoMovimientoInsumo.RESERVA,
        insumo_id="INS-001",
        reparacion_detail_id="DET-001",
        cantidad=Decimal("1"),
        fecha=AHORA,
    )

    assert movimiento.usuario_id is None


def test_movimiento_admite_usuario_cuando_lo_ejecuta_una_persona():
    movimiento = MovimientoInsumo(
        id="MOV-003",
        tipo=TipoMovimientoInsumo.DEVOLUCION,
        insumo_id="INS-001",
        reparacion_detail_id="DET-001",
        cantidad=Decimal("1"),
        usuario_id="TECH-001",
        fecha=AHORA,
    )

    assert movimiento.usuario_id == "TECH-001"


def test_movimiento_es_inmutable():
    movimiento = MovimientoInsumo(
        id="MOV-001",
        tipo=TipoMovimientoInsumo.RESERVA,
        insumo_id="INS-001",
        reparacion_detail_id="DET-001",
        cantidad=Decimal("1"),
        fecha=AHORA,
    )

    with pytest.raises(ValidationError):
        movimiento.tipo = TipoMovimientoInsumo.CONSUMO


def test_cantidad_de_movimiento_debe_ser_mayor_a_cero():
    with pytest.raises(ValidationError):
        MovimientoInsumo(
            id="MOV-001",
            tipo=TipoMovimientoInsumo.RESERVA,
            insumo_id="INS-001",
            reparacion_detail_id="DET-001",
            cantidad=Decimal("0"),
            fecha=AHORA,
        )


# 7) Las listas no se comparten entre instancias.


def test_listas_de_ordenes_distintas_no_comparten_referencias():
    primera = _orden_minima("OR-001")
    segunda = _orden_minima("OR-002")

    listas = [
        "reparaciones_detail",
        "tomas",
        "ejecuciones",
        "movimientos_insumo",
        "historial",
    ]

    for nombre in listas:
        assert getattr(primera, nombre) is not getattr(segunda, nombre)

    primera.historial.append(
        HistorialWorkflow(
            process_id="PROC-REP-040",
            accion="CREAR_ORDEN",
            fecha=AHORA,
        )
    )

    assert len(primera.historial) == 1
    assert segunda.historial == []


def test_submodelos_por_defecto_no_se_comparten():
    primera = _orden_minima("OR-001")
    segunda = _orden_minima("OR-002")

    assert primera.resumen_pago is not segunda.resumen_pago
    assert primera.documentos is not segunda.documentos
    assert primera.documentos.comprobante_final is not (
        segunda.documentos.comprobante_final
    )
