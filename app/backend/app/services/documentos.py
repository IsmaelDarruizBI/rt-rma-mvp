"""Documentos de la Orden.

Nodos cubiertos: PROC-REP-050/060 (comprobante de recepcion) y
PROC-REP-280 (comprobante final y garantia de reparacion).
Features: FEAT-REP-001, FEAT-REP-007, FEAT-REP-008.

El MVP solo registra que el documento fue emitido y cuando: todavia no
se genera ningun PDF ni contenido.
"""

from datetime import datetime

from app.domain.models import Documento, OrdenReparacion
from app.domain.politicas import politica_de

from .exceptions import PrecondicionInvalidaError
from .pagos import condicion_entrega_cumplida
from .revisiones import finalizada_sin_reparacion, lista_para_cierre
from .workflow import registrar_paso


def generar_comprobante_recepcion(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-050 -> PROC-REP-060 si corresponde (FEAT-REP-001).

    La rama la fija ``PoliticaOrigen.requiere_comprobante_recepcion``
    (BR-REP-016), no un origen hardcodeado: CLIENTE_EXTERNO y
    RMA_GARANTIA_REPARACION lo exigen, RT_INTERNO no (HP-REP-002 no
    acredita que un cliente dejo el equipo, no hay cliente). Cuando la
    politica dice "No", PROC-REP-050 igual queda registrado -la decision
    se tomo- pero PROC-REP-060 no se ejecuta.

    PROC-REP-060 es ACT-SYSTEM: no lo ejecuta una persona, asi que no
    recibe Usuario y el historial queda sin actor humano.
    """
    if orden.documentos.comprobante_recepcion.generado:
        raise PrecondicionInvalidaError(
            "El comprobante de recepcion ya fue generado."
        )

    requiere = politica_de(orden.origen).requiere_comprobante_recepcion

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-050",
        accion="REQUIERE_COMPROBANTE_RECEPCION",
        fecha=fecha,
        observacion="Si" if requiere else "No",
    )
    if not requiere:
        return nueva_orden

    nueva_orden = registrar_paso(
        nueva_orden,
        process_id="PROC-REP-060",
        accion="GENERAR_COMPROBANTE_RECEPCION",
        fecha=fecha,
    )
    nueva_orden.documentos.comprobante_recepcion = Documento(
        generado=True,
        fecha_generacion=fecha,
    )
    return nueva_orden


def generar_comprobante_final(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-280: comprobante final y garantia de reparacion.

    Se genera DESPUES de que PROC-REP-265 confirma la condicion de
    entrega, para que el saldo informado sea el definitivo.

    La garantia de reparacion se emite unicamente si hubo reparacion: una
    Orden SIN_REPARACION (PROC-REP-069, BR-REP-010) recibe el comprobante
    final con Subtotal 0 y sin garantia.
    """
    if not lista_para_cierre(orden):
        raise PrecondicionInvalidaError(
            f"El comprobante final se emite sobre una Orden con resultado "
            f"(REPARACION_LISTA o SIN_REPARACION); esta en "
            f"{orden.estado_workflow.value}."
        )
    if orden.current_process != "PROC-REP-265":
        raise PrecondicionInvalidaError(
            "Falta validar la condicion de entrega (PROC-REP-265) "
            "antes de emitir el comprobante final; la Orden esta en "
            f"{orden.current_process}."
        )
    if not condicion_entrega_cumplida(orden):
        raise PrecondicionInvalidaError(
            f"No se emite el comprobante final con saldo pendiente: "
            f"{orden.saldo}."
        )

    sin_reparacion = finalizada_sin_reparacion(orden)
    observacion = f"Total {orden.total} / Saldo {orden.saldo}"
    if sin_reparacion:
        observacion += " / SIN_REPARACION: sin garantia de reparacion"

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-280",
        accion="GENERAR_COMPROBANTE_FINAL",
        fecha=fecha,
        observacion=observacion,
    )
    nueva_orden.documentos.comprobante_final = Documento(
        generado=True,
        fecha_generacion=fecha,
    )
    if not sin_reparacion:
        nueva_orden.documentos.garantia_reparacion = Documento(
            generado=True,
            fecha_generacion=fecha,
        )
    return nueva_orden
