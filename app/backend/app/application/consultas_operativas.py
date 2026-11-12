"""Consultas de solo lectura: antecedentes del Equipo y reportes operativos.

- Antecedentes (BR-REP-022, FEAT-REP-001): las Ordenes de un Equipo por su
  IMEI o numero de serie, con sus trabajos, garantias y entrega. Solo
  consulta: no decide que dos registros sean el mismo Equipo fisico (la
  reutilizacion confirmada y los equipos sin IMEI siguen pendientes, ABI-05).
- Reportes operativos (primera version, DC29 / ABI-15 sigue abierto para el
  diseno completo): metricas calculables con el modelo existente, sin
  umbrales ni politicas nuevas (por ejemplo, no se define que es una Orden
  "demorada": se informa la antiguedad y los dias sin movimiento).

Las consultas GET siguen la regla vigente: cualquier usuario autenticado
(los permisos de consulta configurables, DC27B, siguen pendientes).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domain.equipos import coincide_identificacion
from app.domain.models import (
    EstadoEjecucion,
    EstadoReparacionDetail,
    OrdenReparacion,
    OrigenCancelacion,
    OrigenOrden,
    ResultadoControl,
    TipoMovimientoInsumo,
)
from app.services.pagos import credito_pendiente, es_cobrable

from .contexto import ApplicationContext

# --- Antecedentes del Equipo ----------------------------------------------


@dataclass(frozen=True)
class TrabajoAntecedente:
    detalle_id: str
    tipo_reparacion_id: str
    estado: str
    garantia_dias: int


@dataclass(frozen=True)
class Antecedente:
    orden_id: str
    origen: str
    estado_workflow: str
    creada_en: datetime
    entregada_en: datetime | None
    falla_reportada: str
    orden_origen_id: str | None
    trabajos: tuple[TrabajoAntecedente, ...]
    coincide_por: tuple[str, ...]


@dataclass(frozen=True)
class AntecedentesEquipo:
    imei: str | None
    numero_serie: str | None
    sin_identificacion: bool
    ordenes: tuple[Antecedente, ...] = ()


def _limpio(valor: str | None) -> str | None:
    texto = "".join((valor or "").split()).upper()
    return texto or None


def antecedentes_del_equipo(
    contexto: ApplicationContext,
    *,
    imei: str | None,
    numero_serie: str | None,
    excluir_orden_id: str | None = None,
) -> AntecedentesEquipo:
    """Las Ordenes del Equipo por IMEI o numero de serie, de la mas nueva a
    la mas vieja. Sin ninguno de los dos no hay con que buscar (ABI-05)."""
    if not _limpio(imei) and not _limpio(numero_serie):
        return AntecedentesEquipo(
            imei=imei, numero_serie=numero_serie, sin_identificacion=True
        )
    with contexto.lectura():
        ordenes = contexto.ordenes.listar_por_identificacion_equipo(
            imei=imei, numero_serie=numero_serie
        )
    resultado = []
    for orden in sorted(ordenes, key=lambda o: o.created_at, reverse=True):
        if orden.id == excluir_orden_id:
            continue
        motivos = []
        if _limpio(imei) and coincide_identificacion(orden, imei, None):
            motivos.append("IMEI")
        if _limpio(numero_serie) and coincide_identificacion(
            orden, None, numero_serie
        ):
            motivos.append("NUMERO_SERIE")
        resultado.append(
            Antecedente(
                orden_id=orden.id,
                origen=orden.origen.value,
                estado_workflow=orden.estado_workflow.value,
                creada_en=orden.created_at,
                entregada_en=orden.entrega.fecha if orden.entrega else None,
                falla_reportada=orden.equipo.falla_reportada,
                orden_origen_id=orden.orden_origen_id,
                trabajos=tuple(
                    TrabajoAntecedente(
                        detalle_id=d.id,
                        tipo_reparacion_id=d.tipo_reparacion_id,
                        estado=d.estado.value,
                        garantia_dias=d.garantia_dias,
                    )
                    for d in orden.reparaciones_detail
                ),
                coincide_por=tuple(motivos),
            )
        )
    return AntecedentesEquipo(
        imei=imei,
        numero_serie=numero_serie,
        sin_identificacion=False,
        ordenes=tuple(resultado),
    )


# --- Reportes operativos --------------------------------------------------


@dataclass
class ReporteOperativo:
    generado_en: datetime
    ordenes_por_estado: dict[str, int] = field(default_factory=dict)
    ordenes_por_origen: dict[str, int] = field(default_factory=dict)
    trabajos_por_tecnico: list[dict] = field(default_factory=list)
    tiempos_por_estacion: list[dict] = field(default_factory=list)
    pendientes: list[dict] = field(default_factory=list)
    reprocesos: dict[str, int] = field(default_factory=dict)
    consumo_insumos: list[dict] = field(default_factory=list)
    cobros: dict[str, str] = field(default_factory=dict)


def _horas(desde: datetime, hasta: datetime) -> Decimal:
    return Decimal(str(round((hasta - desde).total_seconds() / 3600, 2)))


def reporte_operativo(contexto: ApplicationContext) -> ReporteOperativo:
    ahora = contexto.ahora()
    with contexto.lectura():
        ordenes: list[OrdenReparacion] = contexto.ordenes.listar()
    reporte = ReporteOperativo(generado_en=ahora)

    por_estado: dict[str, int] = defaultdict(int)
    por_origen: dict[str, int] = defaultdict(int)
    tecnicos: dict[str, dict] = defaultdict(
        lambda: {"completadas": 0, "interrumpidas": 0, "puntaje": 0}
    )
    estaciones: dict[str, dict] = defaultdict(
        lambda: {"ejecuciones": 0, "horas": Decimal("0")}
    )
    consumo: dict[str, Decimal] = defaultdict(Decimal)
    reprocesos = {
        "controles_rechazados": 0,
        "redefiniciones": 0,
        "descartes_tecnicos": 0,
        "garantias_rma": 0,
        "excepciones_de_garantia": 0,
    }
    cobrado = devuelto = pendiente = a_favor = Decimal("0")

    for orden in ordenes:
        por_estado[orden.estado_workflow.value] += 1
        por_origen[orden.origen.value] += 1
        detalles = {d.id: d for d in orden.reparaciones_detail}
        estacion_de_toma = {t.id: t.estacion_id for t in orden.tomas}
        for ejecucion in orden.ejecuciones:
            fila = tecnicos[ejecucion.usuario_id]
            if ejecucion.estado is EstadoEjecucion.COMPLETADO:
                fila["completadas"] += 1
                detalle = detalles.get(ejecucion.reparacion_detail_id)
                if detalle is not None:
                    fila["puntaje"] += detalle.puntaje
            elif ejecucion.estado is EstadoEjecucion.INTERRUMPIDO:
                fila["interrumpidas"] += 1
            if ejecucion.fin is not None:
                estacion = estacion_de_toma.get(
                    ejecucion.toma_orden_id, "SIN_ESTACION"
                )
                estaciones[estacion]["ejecuciones"] += 1
                estaciones[estacion]["horas"] += _horas(
                    ejecucion.inicio, ejecucion.fin
                )
        for detalle in orden.reparaciones_detail:
            reprocesos["controles_rechazados"] += sum(
                1
                for c in detalle.controles
                if c.resultado is ResultadoControl.RECHAZADO
            )
            reprocesos["redefiniciones"] += len(
                detalle.definiciones_anteriores
            )
            if (
                detalle.estado is EstadoReparacionDetail.CANCELADO
                and detalle.cancelacion is not None
                and detalle.cancelacion.origen
                is OrigenCancelacion.DESCARTE_TECNICO
            ):
                reprocesos["descartes_tecnicos"] += 1
        if orden.origen is OrigenOrden.RMA_GARANTIA_REPARACION:
            reprocesos["garantias_rma"] += 1
            reprocesos["excepciones_de_garantia"] += sum(
                1 for v in orden.vigencia_garantia_origen if v.excepcion
            )
        for movimiento in orden.movimientos_insumo:
            if movimiento.tipo is TipoMovimientoInsumo.CONSUMO:
                consumo[movimiento.insumo_id] += movimiento.cantidad
        if es_cobrable(orden):
            cobrado += orden.resumen_pago.pagado
            devuelto += orden.resumen_pago.devuelto
            if not orden.esta_cerrada and orden.saldo > 0:
                pendiente += orden.saldo
            a_favor += credito_pendiente(orden)
        if not orden.esta_cerrada:
            ultimo = max(
                (p.fecha for p in orden.historial), default=orden.created_at
            )
            reporte.pendientes.append(
                {
                    "orden_id": orden.id,
                    "estado_workflow": orden.estado_workflow.value,
                    "origen": orden.origen.value,
                    "dias_abierta": (ahora - orden.created_at).days,
                    "dias_sin_movimiento": (ahora - ultimo).days,
                }
            )

    reporte.ordenes_por_estado = dict(sorted(por_estado.items()))
    reporte.ordenes_por_origen = dict(sorted(por_origen.items()))
    reporte.trabajos_por_tecnico = [
        {"usuario_id": usuario, **valores}
        for usuario, valores in sorted(tecnicos.items())
    ]
    reporte.tiempos_por_estacion = [
        {
            "estacion_id": estacion,
            "ejecuciones": v["ejecuciones"],
            "horas_totales": f"{v['horas']:.2f}",
            "horas_promedio": (
                f"{(v['horas'] / v['ejecuciones']):.2f}"
                if v["ejecuciones"]
                else "0.00"
            ),
        }
        for estacion, v in sorted(estaciones.items())
    ]
    reporte.pendientes.sort(key=lambda p: p["dias_abierta"], reverse=True)
    reporte.reprocesos = reprocesos
    reporte.consumo_insumos = [
        {"insumo_id": insumo, "cantidad": f"{cantidad.normalize():f}"}
        for insumo, cantidad in sorted(consumo.items())
    ]
    reporte.cobros = {
        "cobrado": f"{cobrado:.2f}",
        "devuelto": f"{devuelto:.2f}",
        "saldo_pendiente_ordenes_abiertas": f"{pendiente:.2f}",
        "credito_a_favor_pendiente": f"{a_favor:.2f}",
    }
    return reporte
