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
        2. validar que ningun stock quede negativo (salvo override);
        3. guardar la Orden;
        4. descontar del stock fisico lo efectivamente consumido.

    Solo el CONSUMO baja ``stock_fisico``. La LIBERACION_RESERVA cierra
    la reserva sin tocarlo, porque esa unidad nunca salio del deposito.

    El MVP no implementa transacciones distribuidas: si el paso 4 fallara
    despues del 3, la Orden quedaria con el consumo registrado y el
    catalogo sin actualizar. El paso 2 hace improbable ese caso, y el
    orden elegido preserva primero la historia de la Orden, que es la
    fuente de verdad de lo que ocurrio.

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

    # Un stock fisico negativo solo es admisible si el consumo viene de un
    # Detalle con override de factibilidad valido (BR-REP-003). Es la
    # unica politica de stock negativo; el override de otro Detalle no la
    # habilita.
    ejecucion = next(
        e for e in nueva_orden.ejecuciones if e.id == ejecucion_id
    )
    permite_negativo = tiene_override_factibilidad(
        nueva_orden, ejecucion.reparacion_detail_id
    )

    # Validar todo antes de escribir nada.
    stocks_resultantes: list[tuple[str, Decimal]] = []
    for insumo_id, consumido in sorted(consumos.items()):
        insumo = catalogos_repo.obtener_insumo(insumo_id)
        resultante = insumo.stock_fisico - consumido
        if resultante < CERO and not permite_negativo:
            raise PrecondicionInvalidaError(
                f"El consumo de {consumido} de {insumo_id} dejaria el stock "
                f"fisico en {resultante}: hay {insumo.stock_fisico}."
            )
        stocks_resultantes.append((insumo_id, resultante))

    ordenes_repo.guardar(nueva_orden)

    for insumo_id, resultante in stocks_resultantes:
        catalogos_repo.actualizar_stock_insumo(insumo_id, resultante)

    return nueva_orden


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
