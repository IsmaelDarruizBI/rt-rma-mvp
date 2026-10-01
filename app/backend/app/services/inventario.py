"""Inventario: disponibilidad, reservas pendientes y movimientos.

Nodos cubiertos: PROC-REP-210 (BR-REP-005). Los helpers de
disponibilidad los usan tambien PROC-REP-080 (factibilidad, que solo
consulta) y PROC-REP-185 (reserva real, BR-REP-006).

Una reserva no tiene estado propio: lo pendiente se deriva siempre de
los movimientos que la referencian.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    EstadoEjecucion,
    Insumo,
    InsumoUtilizado,
    MovimientoInsumo,
    OrdenReparacion,
    TipoMovimientoInsumo,
    TipoReparacionInsumos,
)

from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .identificadores import nuevo_id
from .workflow import registrar_paso

CERO = Decimal("0")

# Movimientos que cierran (total o parcialmente) una reserva previa.
_CIERRAN_RESERVA = (
    TipoMovimientoInsumo.CONSUMO,
    TipoMovimientoInsumo.LIBERACION_RESERVA,
)


def insumos_previstos_de(
    tipo_reparacion_id: str,
    relaciones: Sequence[TipoReparacionInsumos],
) -> list[TipoReparacionInsumos]:
    """Insumos que un Tipo de Reparacion preve consumir."""
    return [
        relacion
        for relacion in relaciones
        if relacion.tipo_reparacion_id == tipo_reparacion_id
    ]


def buscar_insumo(insumo_id: str, insumos: Sequence[Insumo]) -> Insumo:
    """Resuelve un insumo del catalogo o falla explicitamente."""
    for insumo in insumos:
        if insumo.id == insumo_id:
            return insumo
    raise EntidadNoEncontradaError(f"Insumo inexistente: {insumo_id}")


def cantidad_pendiente(
    reserva: MovimientoInsumo,
    movimientos: Iterable[MovimientoInsumo],
) -> Decimal:
    """Cantidad de una reserva que todavia no se consumio ni libero.

    pendiente = RESERVA - CONSUMO relacionado
                        - LIBERACION_RESERVA relacionada
    """
    if reserva.tipo is not TipoMovimientoInsumo.RESERVA:
        return CERO

    cerrado = sum(
        (
            movimiento.cantidad
            for movimiento in movimientos
            if movimiento.movimiento_origen_id == reserva.id
            and movimiento.tipo in _CIERRAN_RESERVA
        ),
        CERO,
    )
    return reserva.cantidad - cerrado


def reservas_activas(
    movimientos: Sequence[MovimientoInsumo],
) -> list[MovimientoInsumo]:
    """Reservas con cantidad pendiente mayor a cero."""
    return [
        movimiento
        for movimiento in movimientos
        if movimiento.tipo is TipoMovimientoInsumo.RESERVA
        and cantidad_pendiente(movimiento, movimientos) > CERO
    ]


def hay_reservas_activas(movimientos: Sequence[MovimientoInsumo]) -> bool:
    """True si queda alguna reserva sin cerrar."""
    return bool(reservas_activas(movimientos))


def stock_disponible(
    insumo: Insumo,
    movimientos: Sequence[MovimientoInsumo],
    reservas_externas: Decimal = CERO,
) -> Decimal:
    """Stock fisico menos lo reservado y todavia pendiente.

        disponible = stock_fisico - reservas propias - reservas ajenas

    ``movimientos`` son los de UNA Orden: es lo unico que un aggregate
    puede conocer. ``reservas_externas`` es lo que han reservado las
    demas Ordenes, que el llamador obtiene de
    ``app.services.inventario_global`` cuando trabaja contra la
    persistencia. Su default en cero mantiene el calculo puramente en
    memoria, sin repositories.
    """
    propias = sum(
        (
            cantidad_pendiente(reserva, movimientos)
            for reserva in reservas_activas(movimientos)
            if reserva.insumo_id == insumo.id
        ),
        CERO,
    )
    return insumo.stock_fisico - propias - reservas_externas


def inventario_aplicado(
    orden: OrdenReparacion,
    ejecucion_id: str,
) -> bool:
    """True si esa Ejecucion ya genero sus movimientos de inventario.

    Se deduce del propio ledger, sin ningun flag persistido: si existe
    algun movimiento resolutivo -CONSUMO o LIBERACION_RESERVA- trazado a
    esa Ejecucion, PROC-REP-210 ya corrio para ella.

    Borde conocido: una Ejecucion sin insumos previstos no genera
    movimiento alguno, asi que nunca se la detecta como aplicada.
    Reaplicarla tampoco produce movimientos ni toca el stock -que es lo
    que la idempotencia protege-, solo vuelve a registrar el paso.
    """
    return any(
        movimiento.ejecucion_id == ejecucion_id
        and movimiento.tipo in _CIERRAN_RESERVA
        for movimiento in orden.movimientos_insumo
    )


def crear_reserva(
    *,
    insumo_id: str,
    reparacion_detail_id: str,
    cantidad: Decimal,
    fecha: datetime,
) -> MovimientoInsumo:
    """Movimiento de RESERVA generado por el sistema (PROC-REP-185).

    ``usuario_id`` queda en None: el nodo es ACT-SYSTEM. La trazabilidad
    hacia el tecnico se obtiene por la Ejecucion asociada al Detalle.
    """
    return MovimientoInsumo(
        id=nuevo_id("MOV"),
        tipo=TipoMovimientoInsumo.RESERVA,
        insumo_id=insumo_id,
        reparacion_detail_id=reparacion_detail_id,
        cantidad=cantidad,
        fecha=fecha,
    )


def _cantidad_utilizada(
    insumo_id: str,
    insumos_utilizados: Sequence[InsumoUtilizado],
) -> Decimal:
    """Total realmente utilizado de un insumo en una Ejecucion."""
    return sum(
        (
            utilizado.cantidad
            for utilizado in insumos_utilizados
            if utilizado.insumo_id == insumo_id
        ),
        CERO,
    )


def generar_movimientos_inventario(
    orden: OrdenReparacion,
    *,
    ejecucion_id: str,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-210: consume lo utilizado y libera lo que sobro.

    BR-REP-005. Lee ``EjecucionReparacion.insumos_utilizados`` -la
    fuente de verdad de lo efectivamente usado- y lo compara contra las
    reservas pendientes de ese Detalle:

        utilizado == reservado -> CONSUMO
        utilizado <  reservado -> CONSUMO (si > 0) + LIBERACION_RESERVA
        utilizado >  reservado -> error de dominio (fuera de HP-REP-001)

    Solo se concilia una Ejecucion terminal (COMPLETADO o INTERRUMPIDO,
    VAR-REP-003): una EN_PROGRESO se rechaza. Para el inventario ambos
    resultados son iguales: lo utilizado se consume y lo reservado que no
    se uso se libera.

    La RESERVA original nunca se modifica ni se elimina: los nuevos
    movimientos la referencian por ``movimiento_origen_id``. Todos se
    generan con ``usuario_id=None`` porque el nodo es ACT-SYSTEM.

    El desperdicio que V1.3 tambien contempla en este nodo queda fuera
    del alcance del MVP.

    Es IDEMPOTENTE: si esa Ejecucion ya aplico su inventario, devuelve la
    Orden tal cual esta -sin movimientos nuevos y sin registrar el paso
    otra vez-, para que un reintento no duplique consumos.
    """
    ejecucion = next(
        (e for e in orden.ejecuciones if e.id == ejecucion_id),
        None,
    )
    if ejecucion is None:
        raise EntidadNoEncontradaError(
            f"La Orden no tiene la Ejecucion {ejecucion_id}"
        )
    if ejecucion.estado is EstadoEjecucion.EN_PROGRESO:
        raise PrecondicionInvalidaError(
            f"El inventario se concilia desde una Ejecucion terminada "
            f"(COMPLETADO o INTERRUMPIDO); la Ejecucion {ejecucion_id} "
            f"sigue EN_PROGRESO."
        )

    if inventario_aplicado(orden, ejecucion_id):
        return orden.model_copy(deep=True)

    detalle_id = ejecucion.reparacion_detail_id
    pendientes = [
        reserva
        for reserva in reservas_activas(orden.movimientos_insumo)
        if reserva.reparacion_detail_id == detalle_id
    ]

    # Se valida todo antes de generar ningun movimiento.
    insumos_involucrados = {reserva.insumo_id for reserva in pendientes}
    insumos_involucrados.update(
        utilizado.insumo_id for utilizado in ejecucion.insumos_utilizados
    )

    for insumo_id in sorted(insumos_involucrados):
        reservado = sum(
            (
                cantidad_pendiente(reserva, orden.movimientos_insumo)
                for reserva in pendientes
                if reserva.insumo_id == insumo_id
            ),
            CERO,
        )
        utilizado = _cantidad_utilizada(
            insumo_id, ejecucion.insumos_utilizados
        )
        if utilizado > reservado:
            raise PrecondicionInvalidaError(
                f"El insumo {insumo_id} se utilizo por {utilizado} pero solo "
                f"habia {reservado} reservado: el MVP no modela desperdicio "
                "ni consumo sin reserva."
            )

    nuevos: list[MovimientoInsumo] = []

    for insumo_id in sorted(insumos_involucrados):
        restante = _cantidad_utilizada(insumo_id, ejecucion.insumos_utilizados)
        reservas_del_insumo = [
            reserva for reserva in pendientes if reserva.insumo_id == insumo_id
        ]

        for reserva in reservas_del_insumo:
            pendiente = cantidad_pendiente(reserva, orden.movimientos_insumo)
            consumido = min(restante, pendiente)
            liberado = pendiente - consumido
            restante -= consumido

            if consumido > CERO:
                nuevos.append(
                    MovimientoInsumo(
                        id=nuevo_id("MOV"),
                        tipo=TipoMovimientoInsumo.CONSUMO,
                        insumo_id=insumo_id,
                        reparacion_detail_id=detalle_id,
                        ejecucion_id=ejecucion.id,
                        cantidad=consumido,
                        movimiento_origen_id=reserva.id,
                        fecha=fecha,
                    )
                )
            if liberado > CERO:
                nuevos.append(
                    MovimientoInsumo(
                        id=nuevo_id("MOV"),
                        tipo=TipoMovimientoInsumo.LIBERACION_RESERVA,
                        insumo_id=insumo_id,
                        reparacion_detail_id=detalle_id,
                        ejecucion_id=ejecucion.id,
                        cantidad=liberado,
                        movimiento_origen_id=reserva.id,
                        fecha=fecha,
                    )
                )

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-210",
        accion="GENERAR_MOVIMIENTOS_INVENTARIO",
        fecha=fecha,
        reparacion_detail_id=detalle_id,
        ejecucion_id=ejecucion.id,
    )
    nueva_orden.movimientos_insumo.extend(nuevos)

    return nueva_orden
