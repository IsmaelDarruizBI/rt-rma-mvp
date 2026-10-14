"""Gestion operativa del inventario: consulta, ingresos y ajustes.

Tres cantidades por insumo, sin duplicar ningun valor derivado:

    fisico      ``Insumo.stock_fisico`` (unica fuente, en el catalogo)
    reservado   RESERVA activas de TODAS las Ordenes (``MovimientoInsumo``)
    disponible  fisico - reservado (puede ser negativo: override o faltante)

Dos clases de movimiento, cada una donde nace:

- dentro de cada Orden, trazados a un Detalle: RESERVA, CONSUMO,
  LIBERACION_RESERVA (``MovimientoInsumo``, PROC-REP-185/210);
- fuera de las Ordenes, en el historico del catalogo: INGRESO,
  AJUSTE_POSITIVO, AJUSTE_NEGATIVO (``MovimientoStock``).

El historial de un insumo es la union de ambas, ordenada por fecha: no se
fabrica ningun movimiento. Un ingreso o un ajuste cambian el fisico y
NUNCA tocan reservas: si un ajuste deja el disponible negativo, las
reservas siguen intactas y se exige confirmacion explicita; el faltante
queda como evidencia y se corrige con un movimiento nuevo.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    Insumo,
    MovimientoStock,
    OrdenReparacion,
    RolUsuario,
    TipoMovimientoInsumo,
    Usuario,
)

from .autorizacion import validar_alguno_de
from .exceptions import ConfirmacionRequeridaError, PrecondicionInvalidaError
from .identificadores import nuevo_id
from .inventario import cantidad_pendiente

CERO = Decimal("0")

# Provisorios, a validar con Rosario Tecno.
ROLES_GESTION_STOCK = (
    RolUsuario.ADMINISTRADOR,
    RolUsuario.COORDINADOR_RMA,
)
ROLES_REVALIDACION_RECURSOS = (
    RolUsuario.ADMINISTRADOR,
    RolUsuario.COORDINADOR_RMA,
)

TIPOS_OPERATIVOS = (
    TipoMovimientoInsumo.INGRESO,
    TipoMovimientoInsumo.AJUSTE_POSITIVO,
    TipoMovimientoInsumo.AJUSTE_NEGATIVO,
)


# --- Situacion de cada insumo ------------------------------------------------


@dataclass(frozen=True)
class ReservaVigente:
    """Una RESERVA todavia pendiente (ni consumida ni liberada)."""

    orden_id: str
    detalle_id: str
    movimiento_id: str
    ejecucion_id: str | None
    cantidad: Decimal
    fecha: datetime


@dataclass(frozen=True)
class SituacionInsumo:
    """Fisico, reservado y disponible de un insumo, con sus reservas."""

    insumo: Insumo
    reservas: tuple[ReservaVigente, ...]

    @property
    def reservado(self) -> Decimal:
        return sum((reserva.cantidad for reserva in self.reservas), CERO)

    @property
    def disponible(self) -> Decimal:
        return self.insumo.stock_fisico - self.reservado

    @property
    def faltante(self) -> bool:
        """Disponible o fisico negativos: hay que reponer o corregir."""
        return self.disponible < 0 or self.insumo.stock_fisico < 0

    @property
    def ordenes_con_reserva(self) -> int:
        return len({reserva.orden_id for reserva in self.reservas})

    @property
    def detalles_con_reserva(self) -> int:
        return len(
            {
                (reserva.orden_id, reserva.detalle_id)
                for reserva in self.reservas
            }
        )


def reservas_vigentes_por_insumo(
    ordenes: Iterable[OrdenReparacion],
) -> dict[str, list[ReservaVigente]]:
    """Reservas activas de todas las Ordenes, por insumo (una pasada).

    Misma regla que ``reservas_activas_globales``: una RESERVA sigue activa
    mientras los CONSUMO y LIBERACION_RESERVA que la referencian no la
    cierren.
    """
    vigentes: dict[str, list[ReservaVigente]] = {}
    for orden in ordenes:
        movimientos = orden.movimientos_insumo
        for movimiento in movimientos:
            if movimiento.tipo is not TipoMovimientoInsumo.RESERVA:
                continue
            pendiente = cantidad_pendiente(movimiento, movimientos)
            if pendiente <= CERO:
                continue
            vigentes.setdefault(movimiento.insumo_id, []).append(
                ReservaVigente(
                    orden_id=orden.id,
                    detalle_id=movimiento.reparacion_detail_id,
                    movimiento_id=movimiento.id,
                    ejecucion_id=movimiento.ejecucion_id,
                    cantidad=pendiente,
                    fecha=movimiento.fecha,
                )
            )
    return vigentes


def situacion_inventario(
    insumos: Sequence[Insumo],
    ordenes: Iterable[OrdenReparacion],
) -> list[SituacionInsumo]:
    """Situacion de cada insumo del catalogo, en el orden del catalogo."""
    vigentes = reservas_vigentes_por_insumo(ordenes)
    return [
        SituacionInsumo(
            insumo=insumo, reservas=tuple(vigentes.get(insumo.id, ()))
        )
        for insumo in insumos
    ]


def filtrar_situaciones(
    situaciones: Sequence[SituacionInsumo],
    *,
    buscar: str | None = None,
    solo_faltantes: bool = False,
) -> list[SituacionInsumo]:
    """Busqueda por codigo o nombre (sin distinguir mayusculas)."""
    texto = (buscar or "").strip().lower()
    return [
        situacion
        for situacion in situaciones
        if (
            not texto
            or texto in situacion.insumo.codigo.lower()
            or texto in situacion.insumo.nombre.lower()
            or texto in situacion.insumo.id.lower()
        )
        and (not solo_faltantes or situacion.faltante)
    ]


# --- Historial ---------------------------------------------------------------


@dataclass(frozen=True)
class MovimientoHistorial:
    """Un movimiento de inventario tal como se registro.

    ``origen`` dice donde vive: ``ORDEN`` (trazado a un Detalle) o
    ``INVENTARIO`` (ingreso o ajuste). ``stock_anterior``/``resultante``
    solo existen en los operativos: el fisico de cada consumo no se
    registraba y no se reconstruye.
    """

    id: str
    origen: str
    tipo: TipoMovimientoInsumo
    insumo_id: str
    cantidad: Decimal
    fecha: datetime
    usuario_id: str | None
    orden_id: str | None = None
    detalle_id: str | None = None
    ejecucion_id: str | None = None
    movimiento_origen_id: str | None = None
    observacion: str | None = None
    referencia: str | None = None
    stock_anterior: Decimal | None = None
    stock_resultante: Decimal | None = None
    disponible_resultante: Decimal | None = None


def historial_movimientos(
    ordenes: Iterable[OrdenReparacion],
    movimientos_stock: Iterable[MovimientoStock],
    *,
    insumo_id: str | None = None,
    tipo: TipoMovimientoInsumo | None = None,
) -> list[MovimientoHistorial]:
    """Todos los movimientos registrados, del mas antiguo al mas reciente.

    Union de los movimientos de cada Orden y del historico operativo; sin
    movimientos ficticios.
    """
    historial: list[MovimientoHistorial] = []
    for orden in ordenes:
        for movimiento in orden.movimientos_insumo:
            historial.append(
                MovimientoHistorial(
                    id=movimiento.id,
                    origen="ORDEN",
                    tipo=movimiento.tipo,
                    insumo_id=movimiento.insumo_id,
                    cantidad=movimiento.cantidad,
                    fecha=movimiento.fecha,
                    usuario_id=movimiento.usuario_id,
                    orden_id=orden.id,
                    detalle_id=movimiento.reparacion_detail_id,
                    ejecucion_id=movimiento.ejecucion_id,
                    movimiento_origen_id=movimiento.movimiento_origen_id,
                    observacion=movimiento.observacion,
                )
            )
    for movimiento in movimientos_stock:
        historial.append(
            MovimientoHistorial(
                id=movimiento.id,
                origen="INVENTARIO",
                tipo=movimiento.tipo,
                insumo_id=movimiento.insumo_id,
                cantidad=movimiento.cantidad,
                fecha=movimiento.fecha,
                usuario_id=movimiento.usuario_id,
                observacion=movimiento.motivo,
                referencia=movimiento.referencia,
                stock_anterior=movimiento.stock_anterior,
                stock_resultante=movimiento.stock_resultante,
                disponible_resultante=movimiento.disponible_resultante,
            )
        )
    return sorted(
        (
            movimiento
            for movimiento in historial
            if (insumo_id is None or movimiento.insumo_id == insumo_id)
            and (tipo is None or movimiento.tipo is tipo)
        ),
        # Orden estable: con la misma fecha (reloj de baja resolucion)
        # se conserva el orden en que cada Orden o el historico los
        # registro.
        key=lambda movimiento: movimiento.fecha,
    )


@dataclass(frozen=True)
class EvidenciaFaltante:
    """Registro que muestra un faltante de un insumo (no se borra nunca)."""

    fecha: datetime
    origen: str
    descripcion: str
    orden_id: str | None = None
    movimiento_id: str | None = None


def evidencias_de_faltante(
    insumo_id: str,
    ordenes: Iterable[OrdenReparacion],
    movimientos_stock: Iterable[MovimientoStock],
) -> list[EvidenciaFaltante]:
    """Donde quedo registrado un faltante de ese insumo.

    - Un consumo que dejo el fisico negativo: PROC-REP-210 lo anota en el
      historial de la Orden ("Faltante fisico: ...").
    - Un ajuste negativo que dejo el disponible negativo.

    Corregir el faltante (ingreso o ajuste positivo) no borra esto.
    """
    evidencias: list[EvidenciaFaltante] = []
    for orden in ordenes:
        for paso in orden.historial:
            observacion = paso.observacion or ""
            if (
                paso.process_id == "PROC-REP-210"
                and observacion.startswith("Faltante fisico")
                and insumo_id in observacion
            ):
                evidencias.append(
                    EvidenciaFaltante(
                        fecha=paso.fecha,
                        origen="CONSUMO",
                        descripcion=observacion,
                        orden_id=orden.id,
                    )
                )
    for movimiento in movimientos_stock:
        if (
            movimiento.insumo_id == insumo_id
            and movimiento.tipo == TipoMovimientoInsumo.AJUSTE_NEGATIVO
            and movimiento.disponible_resultante < 0
        ):
            evidencias.append(
                EvidenciaFaltante(
                    fecha=movimiento.fecha,
                    origen=movimiento.tipo.value,
                    descripcion=(
                        f"Se restaron {movimiento.cantidad}: el disponible "
                        f"quedo en {movimiento.disponible_resultante} "
                        f"(reservado {movimiento.reservado}). "
                        f"Motivo: {movimiento.motivo}"
                    ),
                    movimiento_id=movimiento.id,
                )
            )
    return sorted(evidencias, key=lambda evidencia: evidencia.fecha)


# --- Ingresos y ajustes ------------------------------------------------------


def _cantidad_valida(cantidad: Decimal) -> Decimal:
    if not cantidad.is_finite() or cantidad <= 0:
        raise PrecondicionInvalidaError(
            "La cantidad debe ser un numero mayor que cero."
        )
    return cantidad


def _texto(valor: str | None) -> str | None:
    return (valor or "").strip() or None


def registrar_movimiento_operativo(
    situacion: SituacionInsumo,
    *,
    tipo: TipoMovimientoInsumo,
    cantidad: Decimal,
    usuario: Usuario,
    fecha: datetime,
    motivo: str,
    existentes: Sequence[MovimientoStock],
    referencia: str | None = None,
    operacion_id: str | None = None,
    confirmado: bool = False,
) -> MovimientoStock:
    """Arma un ingreso o ajuste valido; quien lo persiste es el caller.

    Reglas:

    - Administracion o Coordinacion; motivo obligatorio; cantidad > 0.
    - Un reintento (mismo ``operacion_id``) o la misma referencia en otro
      movimiento del mismo tipo e insumo no se aplican dos veces.
    - El fisico no puede quedar negativo por un movimiento manual: solo
      un consumo respaldado por una reserva u override puede llevarlo ahi
      (PROC-REP-210), y queda trazado como faltante.
    - Todo ajuste negativo exige ``confirmado``, quede como quede el
      disponible; si lo deja negativo, el aviso lo dice: las reservas no
      se tocan y el faltante queda registrado. Un ingreso o un ajuste
      positivo solo suman al fisico: no pueden producir ninguna condicion
      excepcional y no piden confirmacion.
    """
    validar_alguno_de(usuario, ROLES_GESTION_STOCK)
    if tipo not in TIPOS_OPERATIVOS:
        raise PrecondicionInvalidaError(
            f"{tipo.value} no es un movimiento operativo de inventario."
        )
    cantidad = _cantidad_valida(cantidad)
    motivo = _texto(motivo)
    if motivo is None:
        raise PrecondicionInvalidaError(
            "El ingreso o ajuste de stock exige un motivo."
        )
    referencia = _texto(referencia)
    insumo = situacion.insumo
    for existente in existentes:
        if operacion_id and existente.operacion_id == operacion_id:
            raise PrecondicionInvalidaError(
                f"La operacion ya se registro como {existente.id}: no se "
                "aplica dos veces."
            )
        if (
            referencia
            and existente.insumo_id == insumo.id
            and existente.tipo is tipo
            and (existente.referencia or "").lower() == referencia.lower()
        ):
            raise PrecondicionInvalidaError(
                f"La referencia {existente.referencia} ya se uso en "
                f"{existente.id} ({tipo.value} de {insumo.id})."
            )

    signo = -1 if tipo is TipoMovimientoInsumo.AJUSTE_NEGATIVO else 1
    resultante = insumo.stock_fisico + signo * cantidad
    if resultante < 0:
        raise PrecondicionInvalidaError(
            f"El ajuste dejaria el stock fisico de {insumo.codigo} en "
            f"{resultante}: un movimiento manual no puede llevarlo por "
            f"debajo de cero (hay {insumo.stock_fisico})."
        )
    disponible = resultante - situacion.reservado
    if tipo is TipoMovimientoInsumo.AJUSTE_NEGATIVO and not confirmado:
        aviso = (
            f"El ajuste resta {cantidad} de {insumo.codigo}: fisico "
            f"{insumo.stock_fisico} -> {resultante}, disponible "
            f"{situacion.disponible} -> {disponible}."
        )
        if disponible < 0:
            aviso += (
                f" Deja el disponible negativo: hay {situacion.reservado} "
                f"reservadas por {situacion.ordenes_con_reserva} Orden(es), "
                "que se conservan, y el faltante quedara registrado."
            )
        raise ConfirmacionRequeridaError(
            f"{aviso} Confirma el ajuste negativo para registrarlo."
        )

    return MovimientoStock(
        id=nuevo_id("MST"),
        tipo=tipo,
        insumo_id=insumo.id,
        cantidad=cantidad,
        stock_anterior=insumo.stock_fisico,
        stock_resultante=resultante,
        reservado=situacion.reservado,
        disponible_resultante=disponible,
        usuario_id=usuario.id,
        fecha=fecha,
        motivo=motivo,
        referencia=referencia,
        operacion_id=_texto(operacion_id),
    )


def tipo_de_ajuste(diferencia: Decimal) -> TipoMovimientoInsumo:
    """Una diferencia de unidades: positiva suma, negativa resta."""
    if not diferencia.is_finite() or diferencia == 0:
        raise PrecondicionInvalidaError(
            "El ajuste debe ser una diferencia distinta de cero."
        )
    return (
        TipoMovimientoInsumo.AJUSTE_POSITIVO
        if diferencia > 0
        else TipoMovimientoInsumo.AJUSTE_NEGATIVO
    )
