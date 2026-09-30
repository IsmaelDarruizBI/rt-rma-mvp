"""Fixture del escenario HP-REP-001 de PROC-REP V1.3.

"Reparacion estandar de cliente externo": Orden CLIENTE_EXTERNO con un
unico Detalle conocido desde el ingreso, sin desvios operativos ni
tecnicos, pagada al retirar y entregada.

Datos ficticios de prueba: no representan clientes, equipos ni precios
reales. Los IDs ``PROC-REP-*`` del historial se mantienen exactamente
como estan definidos en ``business/``.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain.models import (
    Cliente,
    Documento,
    DocumentosOrden,
    EjecucionReparacion,
    Equipo,
    EstacionTrabajo,
    EstadoControl,
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    HistorialWorkflow,
    Insumo,
    MovimientoInsumo,
    OrdenReparacion,
    OrigenOrden,
    Pago,
    ReparacionDetail,
    ResumenPago,
    RolUsuario,
    TipoMovimientoInsumo,
    TipoPago,
    TipoReparacion,
    TipoReparacionEstacion,
    TipoReparacionInsumos,
    TomaOrden,
    Usuario,
)

INICIO = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)


def _t(minutos: int) -> datetime:
    """Momento relativo al inicio del escenario, para legibilidad."""
    return INICIO + timedelta(minutes=minutos)


# --- Catalogos (referenciados por ID desde la Orden, nunca embebidos) ---

TIPO_REPARACION = TipoReparacion(
    id="TREP-001",
    nombre="Cambio de bateria",
    precio=Decimal("80000"),
    puntaje=10,
    garantia_dias=90,
)

INSUMO_BATERIA = Insumo(
    id="INS-001",
    codigo="BAT-IP14",
    nombre="Bateria iPhone 14",
    stock_fisico=Decimal("5"),
)

INSUMOS_PREVISTOS = TipoReparacionInsumos(
    tipo_reparacion_id="TREP-001",
    insumo_id="INS-001",
    cantidad=Decimal("1"),
)

ESTACION = EstacionTrabajo(id="EST-001", nombre="Estacion 1")

COMPATIBILIDAD = TipoReparacionEstacion(
    tipo_reparacion_id="TREP-001",
    estacion_id="EST-001",
)

TECNICO = Usuario(id="TECH-001", nombre="Tecnico Uno", rol=RolUsuario.TECNICO)
RECEPCION = Usuario(
    id="RECEP-001",
    nombre="Recepcion Uno",
    rol=RolUsuario.RECEPCION,
)
ADMINISTRADOR = Usuario(
    id="ADMIN-001",
    nombre="Admin Uno",
    rol=RolUsuario.ADMINISTRADOR,
)


def construir_orden_hp_rep_001() -> OrdenReparacion:
    """Devuelve la Orden en su estado FINAL segun HP-REP-001.

    Estado esperado: workflow ENTREGADA, Detalle COMPLETO con control
    APROBADO, toma CERRADA, ejecucion COMPLETADO, saldo 0, comprobante
    final y garantia generados, y la reserva ya consumida (ambos
    movimientos conservados).
    """
    detalle = ReparacionDetail(
        id="DET-001",
        tipo_reparacion_id=TIPO_REPARACION.id,
        # Snapshot tomado del catalogo al crear el Detalle (PROC-REP-070).
        precio=TIPO_REPARACION.precio,
        puntaje=TIPO_REPARACION.puntaje,
        garantia_dias=TIPO_REPARACION.garantia_dias,
        estado=EstadoReparacionDetail.COMPLETO,
        control_estado=EstadoControl.APROBADO,
        control_usuario_id=RECEPCION.id,
        control_fecha=_t(160),
        control_observaciones="Equipo enciende y carga correctamente.",
    )

    toma = TomaOrden(
        id="TOM-001",
        usuario_id=TECNICO.id,
        estacion_id=ESTACION.id,
        estado=EstadoTomaOrden.CERRADA,
        inicio=_t(60),
        fin=_t(150),
    )

    ejecucion = EjecucionReparacion(
        id="EJE-001",
        reparacion_detail_id=detalle.id,
        toma_orden_id=toma.id,
        usuario_id=TECNICO.id,
        estado=EstadoEjecucion.COMPLETADO,
        inicio=_t(65),
        fin=_t(145),
        observaciones="Bateria reemplazada sin novedades.",
    )

    # PROC-REP-185: reserva real al iniciar la Ejecucion.
    reserva = MovimientoInsumo(
        id="MOV-001",
        tipo=TipoMovimientoInsumo.RESERVA,
        insumo_id=INSUMO_BATERIA.id,
        reparacion_detail_id=detalle.id,
        cantidad=INSUMOS_PREVISTOS.cantidad,
        fecha=_t(65),
    )

    # PROC-REP-210: la reserva se consume. El movimiento original se
    # conserva: no se modifica, se referencia.
    consumo = MovimientoInsumo(
        id="MOV-002",
        tipo=TipoMovimientoInsumo.CONSUMO,
        insumo_id=INSUMO_BATERIA.id,
        reparacion_detail_id=detalle.id,
        ejecucion_id=ejecucion.id,
        cantidad=INSUMOS_PREVISTOS.cantidad,
        movimiento_origen_id=reserva.id,
        fecha=_t(146),
    )

    # PROC-REP-266: pago final al retirar, que deja el saldo en 0.
    pago_final = Pago(
        id="PAG-001",
        monto=detalle.precio,
        tipo_pago=TipoPago.PAGO,
        metodo="EFECTIVO",
        usuario_id=ADMINISTRADOR.id,
        fecha=_t(185),
    )

    resumen_pago = ResumenPago(pagos=[pago_final])

    documentos = DocumentosOrden(
        comprobante_recepcion=Documento(
            generado=True,
            fecha_generacion=_t(10),
        ),
        comprobante_final=Documento(generado=True, fecha_generacion=_t(190)),
        garantia_reparacion=Documento(
            generado=True,
            fecha_generacion=_t(190),
        ),
    )

    historial = [
        HistorialWorkflow(
            process_id="PROC-REP-040",
            accion="CREAR_ORDEN",
            fecha=_t(0),
            usuario_id=RECEPCION.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-070",
            accion="DEFINIR_DETALLES",
            fecha=_t(5),
            usuario_id=RECEPCION.id,
            reparacion_detail_id=detalle.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-060",
            accion="GENERAR_COMPROBANTE_RECEPCION",
            fecha=_t(10),
        ),
        HistorialWorkflow(
            process_id="PROC-REP-080",
            accion="VALIDAR_FACTIBILIDAD",
            fecha=_t(15),
            reparacion_detail_id=detalle.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-140",
            accion="HABILITAR_ORDEN",
            fecha=_t(20),
        ),
        HistorialWorkflow(
            process_id="PROC-REP-150",
            accion="DEFINIR_PRIORIDAD",
            fecha=_t(25),
            usuario_id=RECEPCION.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-170",
            accion="INGRESAR_A_COLA",
            fecha=_t(30),
        ),
        HistorialWorkflow(
            process_id="PROC-REP-180",
            accion="TOMAR_ORDEN",
            fecha=_t(60),
            usuario_id=TECNICO.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-181",
            accion="SELECCIONAR_DETALLE",
            fecha=_t(62),
            usuario_id=TECNICO.id,
            reparacion_detail_id=detalle.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-185",
            accion="RESERVAR_INSUMOS",
            fecha=_t(65),
            usuario_id=TECNICO.id,
            reparacion_detail_id=detalle.id,
            ejecucion_id=ejecucion.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-200",
            accion="REGISTRAR_EJECUCION_REAL",
            fecha=_t(145),
            usuario_id=TECNICO.id,
            reparacion_detail_id=detalle.id,
            ejecucion_id=ejecucion.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-210",
            accion="GENERAR_MOVIMIENTOS_INVENTARIO",
            fecha=_t(146),
            reparacion_detail_id=detalle.id,
            ejecucion_id=ejecucion.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-211",
            accion="EVALUAR_SITUACION_ORDEN",
            fecha=_t(150),
            observacion="Todos terminales, existe completo.",
        ),
        HistorialWorkflow(
            process_id="PROC-REP-220",
            accion="REALIZAR_CONTROL_TECNICO",
            fecha=_t(160),
            usuario_id=RECEPCION.id,
            reparacion_detail_id=detalle.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-245",
            accion="CONSOLIDAR_PUNTAJE",
            fecha=_t(165),
            reparacion_detail_id=detalle.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-240",
            accion="MARCAR_REPARACION_LISTA",
            fecha=_t(170),
        ),
        HistorialWorkflow(
            process_id="PROC-REP-260",
            accion="NOTIFICAR_CLIENTE",
            fecha=_t(175),
        ),
        HistorialWorkflow(
            process_id="PROC-REP-265",
            accion="VALIDAR_CONDICION_ENTREGA",
            fecha=_t(180),
            observacion="Saldo pendiente: entrega bloqueada.",
        ),
        HistorialWorkflow(
            process_id="PROC-REP-266",
            accion="REGISTRAR_PAGO",
            fecha=_t(185),
            usuario_id=ADMINISTRADOR.id,
        ),
        HistorialWorkflow(
            process_id="PROC-REP-265",
            accion="REVALIDAR_CONDICION_ENTREGA",
            fecha=_t(186),
            observacion="Saldo 0: entrega habilitada.",
        ),
        HistorialWorkflow(
            process_id="PROC-REP-280",
            accion="GENERAR_COMPROBANTE_FINAL",
            fecha=_t(190),
        ),
        HistorialWorkflow(
            process_id="PROC-REP-270",
            accion="ENTREGAR_EQUIPO",
            fecha=_t(195),
            usuario_id=ADMINISTRADOR.id,
        ),
    ]

    return OrdenReparacion(
        id="OR-001",
        origen=OrigenOrden.CLIENTE_EXTERNO,
        estado_workflow=EstadoWorkflow.ENTREGADA,
        current_process="EVT-REP-999",
        cliente=Cliente(
            id="CLI-001",
            nombre="Cliente de Prueba",
            telefono="341-0000000",
            email="cliente.prueba@example.com",
        ),
        equipo=Equipo(
            id="EQP-001",
            marca="Apple",
            modelo="iPhone 14",
            falla_reportada="La bateria se descarga en pocas horas.",
            numero_serie="SN-PRUEBA-0001",
        ),
        prioridad=0,
        reparaciones_detail=[detalle],
        tomas=[toma],
        ejecuciones=[ejecucion],
        movimientos_insumo=[reserva, consumo],
        resumen_pago=resumen_pago,
        documentos=documentos,
        historial=historial,
        created_at=_t(0),
        updated_at=_t(195),
    )
