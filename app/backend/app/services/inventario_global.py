"""Inventario visto a traves de TODAS las Ordenes.

``app.services.inventario`` responde sobre una sola Orden, que es lo
unico que un aggregate puede saber. Pero la disponibilidad real de un
insumo depende de lo que hayan reservado las demas Ordenes, y esa
pregunta no le corresponde a ninguna ``OrdenReparacion``: ninguna conoce
a las otras, y ningun modelo Pydantic accede a un repository.

Por eso vive aqui, fuera del aggregate: funciones puras sobre una
coleccion de Ordenes, mas un coordinador que usa los repositories.

Semantica de stock acordada:

    RESERVA             -> compromete stock, NO toca stock_fisico
    CONSUMO             -> reduce stock_fisico, cierra la reserva
    LIBERACION_RESERVA  -> NO toca stock_fisico, cierra la reserva

    stock_disponible = stock_fisico - reservas_activas_globales

Los insumos que una Orden PREVE usar no comprometen nada: mientras
ningun tecnico haya iniciado la Ejecucion de ese Detalle (PROC-REP-185),
el stock sigue disponible para cualquier otra Orden. La factibilidad
(PROC-REP-080) solo consulta.
"""

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    Insumo,
    OrdenReparacion,
    TipoMovimientoInsumo,
)
from app.repositories import CatalogosRepository, OrdenReparacionRepository

from .exceptions import PrecondicionInvalidaError
from .inventario import (
    cantidad_pendiente,
    generar_movimientos_inventario,
    inventario_aplicado,
)
from .recursos import tiene_override_factibilidad

logger = logging.getLogger(__name__)

CERO = Decimal("0")


def reservas_activas_globales(
    ordenes: Iterable[OrdenReparacion],
) -> dict[str, Decimal]:
    """Cantidad reservada y todavia pendiente, por insumo.

    Una RESERVA sigue activa mientras no la hayan cerrado -total o
    parcialmente- los CONSUMO y LIBERACION_RESERVA que la referencian
    por ``movimiento_origen_id``.
    """
    pendientes: dict[str, Decimal] = {}

    for orden in ordenes:
        movimientos = orden.movimientos_insumo
        for movimiento in movimientos:
            if movimiento.tipo is not TipoMovimientoInsumo.RESERVA:
                continue
            pendiente = cantidad_pendiente(movimiento, movimientos)
            if pendiente > CERO:
                pendientes[movimiento.insumo_id] = (
                    pendientes.get(movimiento.insumo_id, CERO) + pendiente
                )

    return pendientes


def cantidad_reservada_global(
    insumo_id: str,
    ordenes: Iterable[OrdenReparacion],
) -> Decimal:
    """Total reservado y pendiente de ese insumo en todas las Ordenes."""
    return reservas_activas_globales(ordenes).get(insumo_id, CERO)


def stock_disponible_global(
    insumo: Insumo,
    ordenes: Iterable[OrdenReparacion],
) -> Decimal:
    """Stock fisico menos lo reservado por cualquier Orden.

    Nunca se persiste: siempre se calcula.
    """
    return insumo.stock_fisico - cantidad_reservada_global(insumo.id, ordenes)


def reservas_externas_a(
    orden_id: str,
    ordenes: Iterable[OrdenReparacion],
) -> dict[str, Decimal]:
    """Reservas activas de las OTRAS Ordenes, por insumo.

    Es lo que se le pasa a PROC-REP-080 y PROC-REP-185: la Orden que se
    esta operando ya descuenta sus propias reservas, y esto aporta lo
    unico que no puede saber por si misma.
    """
    return reservas_activas_globales(
        orden for orden in ordenes if orden.id != orden_id
    )


def cargar_reservas_externas(
    orden_id: str,
    ordenes_repo: OrdenReparacionRepository,
) -> dict[str, Decimal]:
    """``reservas_externas_a`` leyendo las Ordenes persistidas."""
    return reservas_externas_a(orden_id, ordenes_repo.listar())


def aplicar_movimientos_inventario(
    orden: OrdenReparacion,
    *,
    ejecucion_id: str,
    fecha: datetime,
    ordenes_repo: OrdenReparacionRepository,
    catalogos_repo: CatalogosRepository,
) -> OrdenReparacion:
    """PROC-REP-210 con sus dos efectos persistidos.

    Encapsula la secuencia completa para que quien la invoque -hoy un
    test, manana la API- no tenga que coordinarla a mano:

        1. generar los movimientos dentro de la Orden (service 210);
        2. calcular el stock fisico resultante y, si queda negativo,
           dejar constancia del faltante fisico en el paso 210;
        3. descontar del stock fisico lo efectivamente consumido;
        4. guardar la Orden.

    Solo el CONSUMO baja ``stock_fisico``. La LIBERACION_RESERVA cierra
    la reserva sin tocarlo, porque esa unidad nunca salio del deposito.

    Decision de negocio E3 (MVP v2): todo CONSUMO de este paso cierra una
    RESERVA de la propia Orden -``generar_movimientos_inventario``
    rechaza usar mas de lo reservado-, y esa reserva es un derecho que la
    Orden obtuvo en PROC-REP-185. Por eso el consumo nunca se bloquea
    porque el stock fisico ya no alcance: si otra Orden consumio con
    override (o el stock se ajusto a mano), el fisico puede quedar
    negativo y el faltante queda trazado; no se inventan existencias ni
    se borran movimientos.

    El MVP no tiene transacciones entre archivos (E4): el stock se escribe
    primero -no tiene control de version- y la Orden despues -el
    repository puede rechazar una version obsoleta-. Si guardar la Orden
    falla, el stock vuelve a su valor anterior; si falla el stock, la Orden
    no se guarda. Asi ninguno de los dos queda con un consumo que el otro
    no tiene y el tecnico puede reintentar. Lo unico que queda fuera es
    que falle tambien esa restauracion: se registra en el log como
    inconsistencia a revisar a mano.

    Es IDEMPOTENTE: si esa Ejecucion ya aplico su inventario, devuelve la
    Orden sin generar movimientos, sin volver a descontar stock y sin
    escribir. Un reintento de la futura API es seguro.
    """
    if inventario_aplicado(orden, ejecucion_id):
        return orden.model_copy(deep=True)

    nueva_orden = generar_movimientos_inventario(
        orden, ejecucion_id=ejecucion_id, fecha=fecha
    )

    consumos = _consumos_de_la_ejecucion(nueva_orden, ejecucion_id)

    # Calcular todo antes de escribir nada.
    stocks: list[tuple[str, Decimal, Decimal]] = []  # (id, antes, despues)
    faltantes: list[str] = []
    for insumo_id, consumido in sorted(consumos.items()):
        insumo = catalogos_repo.obtener_insumo(insumo_id)
        resultante = insumo.stock_fisico - consumido
        stocks.append((insumo_id, insumo.stock_fisico, resultante))
        if resultante < CERO:
            faltantes.append(
                f"{insumo_id} queda en {resultante} tras consumir "
                f"{consumido} (habia {insumo.stock_fisico})"
            )

    if faltantes:
        ejecucion = next(
            e for e in nueva_orden.ejecuciones if e.id == ejecucion_id
        )
        respaldo = (
            "consumo con override de factibilidad"
            if tiene_override_factibilidad(
                nueva_orden, ejecucion.reparacion_detail_id
            )
            else "consumo respaldado por la reserva de esta Orden"
        )
        nueva_orden = _anotar_faltante_fisico(
            nueva_orden,
            f"Faltante fisico: {'; '.join(faltantes)}. {respaldo}.",
        )

    escritos: list[tuple[str, Decimal]] = []
    try:
        for insumo_id, anterior, resultante in stocks:
            catalogos_repo.actualizar_stock_insumo(insumo_id, resultante)
            escritos.append((insumo_id, anterior))
        ordenes_repo.guardar(nueva_orden)
    except Exception:
        _restaurar_stock(catalogos_repo, escritos)
        raise

    return nueva_orden


def _restaurar_stock(
    catalogos_repo: CatalogosRepository,
    escritos: Sequence[tuple[str, Decimal]],
) -> None:
    """Deshace los descuentos de stock ya escritos (compensacion, E4).

    Si la restauracion misma falla, no tapa el error original: queda en
    el log para revisarlo a mano.
    """
    for insumo_id, anterior in reversed(escritos):
        try:
            catalogos_repo.actualizar_stock_insumo(insumo_id, anterior)
        except Exception:
            logger.exception(
                "No se pudo restaurar el stock de %s a %s tras un fallo de "
                "escritura de PROC-REP-210: revisar el inventario.",
                insumo_id,
                anterior,
            )


def _anotar_faltante_fisico(
    orden: OrdenReparacion,
    observacion: str,
) -> OrdenReparacion:
    """Deja el faltante fisico en el paso PROC-REP-210 recien registrado.

    ``generar_movimientos_inventario`` acaba de agregar ese paso al final
    del historial de esta copia de la Orden, todavia sin persistir: se
    completa su observacion en lugar de inventar un nodo nuevo.
    """
    ultimo = orden.historial[-1]
    if ultimo.process_id != "PROC-REP-210":
        raise PrecondicionInvalidaError(
            "El faltante fisico se anota sobre el paso PROC-REP-210."
        )
    orden.historial[-1] = ultimo.model_copy(
        update={"observacion": observacion}
    )
    return orden


def _consumos_de_la_ejecucion(
    orden: OrdenReparacion,
    ejecucion_id: str,
) -> dict[str, Decimal]:
    """Total consumido por insumo en esa Ejecucion."""
    consumos: dict[str, Decimal] = {}

    for movimiento in orden.movimientos_insumo:
        if movimiento.tipo is not TipoMovimientoInsumo.CONSUMO:
            continue
        if movimiento.ejecucion_id != ejecucion_id:
            continue
        consumos[movimiento.insumo_id] = (
            consumos.get(movimiento.insumo_id, CERO) + movimiento.cantidad
        )

    return consumos


def stock_disponible_por_insumo(
    insumos: Sequence[Insumo],
    ordenes: Iterable[OrdenReparacion],
) -> dict[str, Decimal]:
    """Disponibilidad de cada insumo del catalogo. Util para diagnostico."""
    reservado = reservas_activas_globales(ordenes)
    return {
        insumo.id: insumo.stock_fisico - reservado.get(insumo.id, CERO)
        for insumo in insumos
    }
