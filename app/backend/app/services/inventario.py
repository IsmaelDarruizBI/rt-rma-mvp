"""Inventario: disponibilidad, reservas pendientes y movimientos.

Nodos cubiertos: PROC-REP-210 (BR-REP-005). Los helpers de
disponibilidad los usan tambien PROC-REP-080 (factibilidad, que solo
consulta) y PROC-REP-185 (reserva real, BR-REP-006).

Una reserva no tiene estado propio: lo pendiente se deriva siempre de
los movimientos que la referencian.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    EleccionPieza,
    EstadoEjecucion,
    Insumo,
    InsumoUtilizado,
    MovimientoInsumo,
    OrdenReparacion,
    ReparacionDetail,
    TipoMovimientoInsumo,
    TipoReparacionInsumos,
)

from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .identificadores import nuevo_id
from .workflow import registrar_paso

CERO = Decimal("0")
# Observacion de PROC-REP-210 cuando un override termina con insumos que
# el stock no respaldaba (P-06): sin movimiento ni descuento posterior.
PREFIJO_SIN_RESPALDO = "Utilizado sin respaldo de stock"

# DEC-AJ-14: la liberacion de la pieza sustituida despues de reservar (y
# antes de consumir) lleva esta observacion. No es PROC-REP-210: no cuenta
# para ``inventario_aplicado``.
PREFIJO_SUSTITUCION = "Sustitucion de pieza"

# Movimientos que cierran (total o parcialmente) una reserva previa.
_CIERRAN_RESERVA = (
    TipoMovimientoInsumo.CONSUMO,
    TipoMovimientoInsumo.LIBERACION_RESERVA,
    TipoMovimientoInsumo.DESPERDICIO,
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


def piezas_vigentes(detalle: ReparacionDetail) -> dict[str, EleccionPieza]:
    """DEC-AJ-14: la pieza elegida vigente de cada requisito del Detalle.

    Por requisito, la ultima eleccion registrada; si esa eleccion anulo la
    pieza (``insumo_id`` vacio) el requisito no tiene pieza. Solo cuentan
    las elecciones del Tipo vigente del Detalle: las de una definicion
    anterior (redefinido a otro Tipo) no se reservan.
    """
    ultimas: dict[str, EleccionPieza] = {}
    for eleccion in detalle.piezas:
        ultimas[eleccion.requisito_id] = eleccion
    return {
        requisito_id: eleccion
        for requisito_id, eleccion in ultimas.items()
        if eleccion.insumo_id is not None
        and eleccion.tipo_reparacion_id == detalle.tipo_reparacion_id
    }


def insumos_previstos_del_detalle(
    detalle: ReparacionDetail,
    relaciones: Sequence[TipoReparacionInsumos],
) -> list[TipoReparacionInsumos]:
    """Lo que el Detalle preve consumir y reserva al iniciar (BR-REP-006).

    Los insumos previstos concretos de su Tipo (como siempre) mas la pieza
    elegida de cada requisito (DEC-AJ-14), con la cantidad de la eleccion.
    Una linea por insumo, con las cantidades sumadas: si una pieza elegida
    coincide con un previsto concreto, se pide (y se reserva) la suma. Sin
    piezas elegidas es exactamente ``insumos_previstos_de``.
    """
    cantidades: dict[str, Decimal] = {}
    for previsto in insumos_previstos_de(
        detalle.tipo_reparacion_id, relaciones
    ):
        cantidades[previsto.insumo_id] = (
            cantidades.get(previsto.insumo_id, CERO) + previsto.cantidad
        )
    for eleccion in piezas_vigentes(detalle).values():
        insumo_id = eleccion.insumo_id
        assert insumo_id is not None
        cantidades[insumo_id] = (
            cantidades.get(insumo_id, CERO) + eleccion.cantidad
        )
    return [
        TipoReparacionInsumos(
            tipo_reparacion_id=detalle.tipo_reparacion_id,
            insumo_id=insumo_id,
            cantidad=cantidad,
        )
        for insumo_id, cantidad in cantidades.items()
    ]


def _previstos(
    detalle_o_tipo: ReparacionDetail | str,
    relaciones: Sequence[TipoReparacionInsumos],
) -> list[TipoReparacionInsumos]:
    """Los previstos de un Detalle (con sus piezas elegidas) o, por
    compatibilidad, los de un Tipo."""
    if isinstance(detalle_o_tipo, ReparacionDetail):
        return insumos_previstos_del_detalle(detalle_o_tipo, relaciones)
    return insumos_previstos_de(detalle_o_tipo, relaciones)


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


def faltantes_del_detalle(
    detalle_o_tipo: ReparacionDetail | str,
    movimientos: Sequence[MovimientoInsumo],
    insumos: Sequence[Insumo],
    insumos_previstos: Sequence[TipoReparacionInsumos],
    reservas_externas: Mapping[str, Decimal] | None = None,
) -> list[str]:
    """IDs (ordenados) de los insumos previstos que hoy no alcanzan.

    Unica logica de disponibilidad por Detalle: la usan la factibilidad
    (PROC-REP-080) y la reserva real (PROC-REP-185/186). Compara lo
    previsto por el Tipo de Reparacion contra ``stock_fisico`` menos las
    reservas propias (``movimientos``) y ajenas (``reservas_externas``,
    insumo_id -> cantidad). No decide nada sobre overrides: eso es del
    llamador.

    DEC-AJ-14: con un Detalle, lo previsto incluye la pieza elegida de
    cada requisito (``insumos_previstos_del_detalle``). Los requisitos sin
    pieza elegida los evalua ``services.piezas.faltantes_con_requisitos``.
    """
    ajenas = reservas_externas or {}
    faltantes: set[str] = set()
    previstos = _previstos(detalle_o_tipo, insumos_previstos)
    for previsto in previstos:
        insumo = buscar_insumo(previsto.insumo_id, insumos)
        disponible = stock_disponible(
            insumo, movimientos, ajenas.get(insumo.id, CERO)
        )
        if disponible < previsto.cantidad:
            faltantes.add(insumo.id)
    return sorted(faltantes)


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


def cantidad_reservable(requerido: Decimal, disponible: Decimal) -> Decimal:
    """Lo que un override puede reservar: solo lo realmente disponible.

    P-06 (UAT): nunca mas que el disponible (que ya descuenta las reservas
    de otras Ordenes) ni menos que cero. El resto es el faltante, que no
    se reserva ni se descuenta nunca.
    """
    return min(requerido, max(disponible, CERO))


@dataclass(frozen=True)
class ImpactoStockInsumo:
    """Situacion de UN insumo previsto ante un override (E3, BR-REP-003).

    Es lo que el usuario ve -y confirma- antes de autorizar:

        reservado  = reservado por otras Ordenes + por esta Orden
        disponible = stock fisico - reservado
        a_reservar = lo que alcanza del requerido (``cantidad_reservable``)
        faltante   = requerido - a_reservar

    No se persiste: se calcula contra el catalogo y las reservas vigentes.
    """

    insumo_id: str
    codigo: str
    nombre: str
    stock_fisico: Decimal
    reservado_otras_ordenes: Decimal
    reservado_esta_orden: Decimal
    requerido: Decimal

    @property
    def reservado(self) -> Decimal:
        return self.reservado_otras_ordenes + self.reservado_esta_orden

    @property
    def disponible(self) -> Decimal:
        return self.stock_fisico - self.reservado

    @property
    def a_reservar(self) -> Decimal:
        return cantidad_reservable(self.requerido, self.disponible)

    @property
    def faltante(self) -> Decimal:
        return self.requerido - self.a_reservar

    def describir(self) -> str:
        """Una linea legible, para el historial y los mensajes."""
        return (
            f"{self.insumo_id}: fisico {self.stock_fisico}, reservado "
            f"{self.reservado} (otras Ordenes {self.reservado_otras_ordenes}"
            f"), disponible {self.disponible}, requerido {self.requerido}, "
            f"se reserva {self.a_reservar}, faltante {self.faltante}"
        )


def impacto_en_stock_del_detalle(
    orden: OrdenReparacion,
    detalle_id: str,
    insumos: Sequence[Insumo],
    insumos_previstos: Sequence[TipoReparacionInsumos],
    reservas_externas: Mapping[str, Decimal] | None = None,
) -> list[ImpactoStockInsumo]:
    """Impacto de forzar ese Detalle sobre cada insumo que preve (E3).

    Usa la misma aritmetica que ``stock_disponible``: el stock fisico, las
    reservas pendientes de esta Orden (``orden.movimientos_insumo``) y las
    de las demas (``reservas_externas``). Solo consulta: no reserva ni
    toca ninguna reserva, propia o ajena.
    """
    detalle = next(
        (d for d in orden.reparaciones_detail if d.id == detalle_id), None
    )
    if detalle is None:
        raise EntidadNoEncontradaError(
            f"La Orden {orden.id} no tiene el Detalle {detalle_id}."
        )

    ajenas = reservas_externas or {}
    impactos: list[ImpactoStockInsumo] = []
    for previsto in insumos_previstos_del_detalle(detalle, insumos_previstos):
        insumo = buscar_insumo(previsto.insumo_id, insumos)
        propias = sum(
            (
                cantidad_pendiente(reserva, orden.movimientos_insumo)
                for reserva in reservas_activas(orden.movimientos_insumo)
                if reserva.insumo_id == insumo.id
            ),
            CERO,
        )
        impactos.append(
            ImpactoStockInsumo(
                insumo_id=insumo.id,
                codigo=insumo.codigo,
                nombre=insumo.nombre,
                stock_fisico=insumo.stock_fisico,
                reservado_otras_ordenes=ajenas.get(insumo.id, CERO),
                reservado_esta_orden=propias,
                requerido=previsto.cantidad,
            )
        )
    return impactos


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

    DEC-AJ-14: la liberacion de una pieza sustituida durante la Ejecucion
    (``es_liberacion_por_sustitucion``) no es PROC-REP-210 y no cuenta.
    """
    return any(
        movimiento.ejecucion_id == ejecucion_id
        and movimiento.tipo in _CIERRAN_RESERVA
        and not es_liberacion_por_sustitucion(movimiento)
        for movimiento in orden.movimientos_insumo
    )


def es_liberacion_por_sustitucion(movimiento: MovimientoInsumo) -> bool:
    """La LIBERACION_RESERVA de una pieza sustituida despues de reservar
    (DEC-AJ-14): la registra una persona, con la observacion
    ``PREFIJO_SUSTITUCION``, mientras la Ejecucion sigue en curso."""
    return (
        movimiento.tipo is TipoMovimientoInsumo.LIBERACION_RESERVA
        and movimiento.usuario_id is not None
        and (movimiento.observacion or "").startswith(PREFIJO_SUSTITUCION)
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
    tope_override: Mapping[str, Decimal] | None = None,
) -> OrdenReparacion:
    """PROC-REP-210: consume lo utilizado y libera lo que sobro.

    BR-REP-005. Lee ``EjecucionReparacion.insumos_utilizados`` -la
    fuente de verdad de lo efectivamente usado- y lo compara contra las
    reservas pendientes de ese Detalle:

        utilizado == reservado -> CONSUMO
        utilizado <  reservado -> CONSUMO (si > 0) + LIBERACION_RESERVA
        utilizado >  reservado -> error de dominio (fuera de HP-REP-001)

    Con override vigente del Detalle (P-06) el llamador pasa
    ``tope_override``: por insumo, las unidades que existen para esta
    Orden (fisico menos reservas de otras Ordenes). Entonces se descuenta
    a lo sumo ``min(utilizado, reservado, tope)``; lo reservado que no se
    descuenta se libera, y lo utilizado de mas no genera movimiento: queda
    en el paso 210 como "utilizado sin respaldo de stock". Nunca se deja
    un descuento pendiente para una reposicion futura.

    Solo se concilia una Ejecucion terminal (COMPLETADO o INTERRUMPIDO,
    VAR-REP-003): una EN_PROGRESO se rechaza. Para el inventario ambos
    resultados son iguales: lo utilizado se consume y lo reservado que no
    se uso se libera.

    La RESERVA original nunca se modifica ni se elimina: los nuevos
    movimientos la referencian por ``movimiento_origen_id``. Todos se
    generan con ``usuario_id=None`` porque el nodo es ACT-SYSTEM.

    DEC-MI-10: el desperdicio declarado sale como DESPERDICIO (tambien
    cierra la reserva) y cada movimiento lleva el lote de su linea.

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

    # DEC-MI-10: lo que sale de cada insumo, en el orden de las lineas:
    # (tipo, lote, cantidad). El desperdicio sale como DESPERDICIO, no
    # como CONSUMO; los dos cierran la reserva.
    porciones: dict[
        str, list[tuple[TipoMovimientoInsumo, str | None, Decimal]]
    ]
    porciones = {}
    for linea in ejecucion.insumos_utilizados:
        lista = porciones.setdefault(linea.insumo_id, [])
        if linea.cantidad > CERO:
            lista.append(
                (TipoMovimientoInsumo.CONSUMO, linea.lote_id, linea.cantidad)
            )
        if linea.desperdicio > CERO:
            lista.append(
                (
                    TipoMovimientoInsumo.DESPERDICIO,
                    linea.lote_id,
                    linea.desperdicio,
                )
            )

    a_descontar: dict[str, Decimal] = {}
    sin_respaldo: list[str] = []
    for insumo_id in sorted(insumos_involucrados):
        reservado = sum(
            (
                cantidad_pendiente(reserva, orden.movimientos_insumo)
                for reserva in pendientes
                if reserva.insumo_id == insumo_id
            ),
            CERO,
        )
        utilizado = sum(
            (cantidad for _, _, cantidad in porciones.get(insumo_id, [])),
            CERO,
        )
        if tope_override is None:
            if utilizado > reservado:
                raise PrecondicionInvalidaError(
                    f"El insumo {insumo_id} se utilizo o desperdicio por "
                    f"{utilizado} pero solo habia {reservado} reservado: no "
                    "se consume sin reserva."
                )
            a_descontar[insumo_id] = utilizado
            continue
        tope = max(tope_override.get(insumo_id, CERO), CERO)
        a_descontar[insumo_id] = min(utilizado, reservado, tope)
        if utilizado > a_descontar[insumo_id]:
            sin_respaldo.append(
                f"{insumo_id} utilizado {utilizado}, descontado "
                f"{a_descontar[insumo_id]}, sin respaldo "
                f"{utilizado - a_descontar[insumo_id]}"
            )

    nuevos: list[MovimientoInsumo] = []

    for insumo_id in sorted(insumos_involucrados):
        # Las porciones, recortadas a lo que efectivamente se descuenta.
        restante = a_descontar[insumo_id]
        partes: list[list] = []
        for tipo, lote_id, cantidad in porciones.get(insumo_id, []):
            tomada = min(cantidad, restante)
            if tomada > CERO:
                partes.append([tipo, lote_id, tomada])
            restante -= tomada
        reservas_del_insumo = [
            reserva for reserva in pendientes if reserva.insumo_id == insumo_id
        ]

        for reserva in reservas_del_insumo:
            pendiente = cantidad_pendiente(reserva, orden.movimientos_insumo)
            while pendiente > CERO and partes:
                tipo, lote_id, cantidad = partes[0]
                usada = min(cantidad, pendiente)
                nuevos.append(
                    MovimientoInsumo(
                        id=nuevo_id("MOV"),
                        tipo=tipo,
                        insumo_id=insumo_id,
                        reparacion_detail_id=detalle_id,
                        ejecucion_id=ejecucion.id,
                        cantidad=usada,
                        movimiento_origen_id=reserva.id,
                        fecha=fecha,
                        lote_id=lote_id,
                    )
                )
                pendiente -= usada
                partes[0][2] = cantidad - usada
                if partes[0][2] <= CERO:
                    partes.pop(0)
            if pendiente > CERO:
                nuevos.append(
                    MovimientoInsumo(
                        id=nuevo_id("MOV"),
                        tipo=TipoMovimientoInsumo.LIBERACION_RESERVA,
                        insumo_id=insumo_id,
                        reparacion_detail_id=detalle_id,
                        ejecucion_id=ejecucion.id,
                        cantidad=pendiente,
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
        observacion=(
            f"{PREFIJO_SIN_RESPALDO} (override): {'; '.join(sin_respaldo)}"
            if sin_respaldo
            else None
        ),
    )
    nueva_orden.movimientos_insumo.extend(nuevos)

    return nueva_orden
