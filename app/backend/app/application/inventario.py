"""Inventario operativo: consulta, ingresos, ajustes y revalidacion.

    consultar_inventario          fisico, reservado y disponible por insumo
    detalle_de_insumo             reservas vigentes, historial y faltantes
    movimientos_de_inventario     historial de todos los movimientos
    registrar_ingreso_stock       INGRESO (Administracion, Coordinacion)
    registrar_ajuste_stock        AJUSTE_POSITIVO / AJUSTE_NEGATIVO
    revalidar_ordenes_pendientes  revalidacion masiva de recursos, tambien
                                  con factibilidad parcial

Los ingresos y ajustes leen las reservas de todas las Ordenes y reescriben
el stock del catalogo: corren en la seccion critica de inventario, la misma
que la reserva (185) y el consumo (210). Las reglas viven en
``services.inventario_operativo``; aca solo se cargan datos y se persiste.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    EstadoWorkflow,
    MovimientoStock,
    OrdenReparacion,
    TipoMovimientoInsumo,
)
from app.repositories import RepositoryError
from app.services import (
    ACCION_REVALIDAR_RECURSOS,
    ROLES_REVALIDACION_RECURSOS,
    DomainError,
    EvidenciaFaltante,
    MovimientoHistorial,
    PrecondicionInvalidaError,
    ResultadoEvaluacionOrden,
    SituacionInsumo,
    cargar_reservas_externas,
    desbloquear_detalles_con_recursos,
    detalles_bloqueados_por_recursos,
    detalles_pendientes_de_autorizacion,
    evidencias_de_faltante,
    faltantes_de_detalles_bloqueados,
    filtrar_situaciones,
    fue_habilitada,
    historial_movimientos,
    registrar_accion_funcional,
    registrar_espera_recursos,
    registrar_movimiento_operativo,
    situacion_de_la_orden,
    situacion_inventario,
    tipo_de_ajuste,
    validar_alguno_de,
)

from .concurrencia import seccion_critica_inventario
from .contexto import ApplicationContext
from .ingreso import _validar_y_habilitar
from .modificacion import orden_para_modificar

NODOS_ESPERANDO_RECURSOS = ("PROC-REP-100", "PROC-REP-120")


@dataclass(frozen=True)
class DetalleInsumo:
    """Un insumo con sus reservas, su historial y sus faltantes."""

    situacion: SituacionInsumo
    movimientos: list[MovimientoHistorial]
    faltantes: list[EvidenciaFaltante]


@dataclass(frozen=True)
class ResultadoMovimientoStock:
    """El movimiento registrado y como quedo el insumo."""

    movimiento: MovimientoStock
    situacion: SituacionInsumo


# --- Consultas ---------------------------------------------------------------


def consultar_inventario(
    contexto: ApplicationContext,
    *,
    buscar: str | None = None,
    solo_faltantes: bool = False,
) -> list[SituacionInsumo]:
    """Todos los insumos (o los que coinciden), con sus tres cantidades."""
    situaciones = situacion_inventario(
        contexto.catalogos.listar_insumos(), contexto.ordenes.listar()
    )
    return filtrar_situaciones(
        situaciones, buscar=buscar, solo_faltantes=solo_faltantes
    )


def detalle_de_insumo(
    contexto: ApplicationContext,
    insumo_id: str,
) -> DetalleInsumo:
    """Situacion, reservas vigentes, historial y evidencia de faltantes."""
    insumo = contexto.catalogos.obtener_insumo(insumo_id)
    ordenes = contexto.ordenes.listar()
    movimientos_stock = contexto.catalogos.listar_movimientos_stock()
    (situacion,) = situacion_inventario([insumo], ordenes)
    return DetalleInsumo(
        situacion=situacion,
        movimientos=historial_movimientos(
            ordenes, movimientos_stock, insumo_id=insumo_id
        ),
        faltantes=evidencias_de_faltante(
            insumo_id, ordenes, movimientos_stock
        ),
    )


def movimientos_de_inventario(
    contexto: ApplicationContext,
    *,
    insumo_id: str | None = None,
    tipo: TipoMovimientoInsumo | None = None,
) -> list[MovimientoHistorial]:
    """Historial de movimientos, opcionalmente de un insumo o un tipo."""
    return historial_movimientos(
        contexto.ordenes.listar(),
        contexto.catalogos.listar_movimientos_stock(),
        insumo_id=insumo_id,
        tipo=tipo,
    )


# --- Ingresos y ajustes ------------------------------------------------------


def _registrar_movimiento(
    contexto: ApplicationContext,
    *,
    insumo_id: str,
    usuario_id: str,
    tipo: TipoMovimientoInsumo,
    cantidad: Decimal,
    motivo: str,
    referencia: str | None,
    operacion_id: str | None,
    confirmado: bool,
) -> ResultadoMovimientoStock:
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with seccion_critica_inventario():
        insumo = contexto.catalogos.obtener_insumo(insumo_id)
        ordenes = contexto.ordenes.listar()
        (situacion,) = situacion_inventario([insumo], ordenes)
        movimiento = registrar_movimiento_operativo(
            situacion,
            tipo=tipo,
            cantidad=cantidad,
            usuario=usuario,
            fecha=fecha,
            motivo=motivo,
            existentes=contexto.catalogos.listar_movimientos_stock(),
            referencia=referencia,
            operacion_id=operacion_id,
            confirmado=confirmado,
        )
        insumo = contexto.catalogos.registrar_movimiento_stock(movimiento)
        (situacion,) = situacion_inventario([insumo], ordenes)
    return ResultadoMovimientoStock(movimiento=movimiento, situacion=situacion)


def registrar_ingreso_stock(
    contexto: ApplicationContext,
    *,
    insumo_id: str,
    usuario_id: str,
    cantidad: Decimal,
    motivo: str,
    referencia: str | None = None,
    operacion_id: str | None = None,
) -> ResultadoMovimientoStock:
    """Entrada de existencias: suma al fisico, no toca reservas."""
    return _registrar_movimiento(
        contexto,
        insumo_id=insumo_id,
        usuario_id=usuario_id,
        tipo=TipoMovimientoInsumo.INGRESO,
        cantidad=cantidad,
        motivo=motivo,
        referencia=referencia,
        operacion_id=operacion_id,
        confirmado=True,
    )


def registrar_ajuste_stock(
    contexto: ApplicationContext,
    *,
    insumo_id: str,
    usuario_id: str,
    diferencia: Decimal,
    motivo: str,
    referencia: str | None = None,
    operacion_id: str | None = None,
    confirmado: bool = False,
) -> ResultadoMovimientoStock:
    """Ajuste expresado como diferencia de unidades (+ suma, - resta).

    Todo ajuste negativo exige ``confirmado``; las reservas nunca se
    modifican.
    """
    tipo = tipo_de_ajuste(diferencia)
    return _registrar_movimiento(
        contexto,
        insumo_id=insumo_id,
        usuario_id=usuario_id,
        tipo=tipo,
        cantidad=abs(diferencia),
        motivo=motivo,
        referencia=referencia,
        operacion_id=operacion_id,
        confirmado=confirmado,
    )


# --- Revalidacion masiva de recursos -----------------------------------------


class ResultadoRevalidacion:
    """Valores de ``ResultadoRevalidacionOrden.resultado``."""

    TRABAJABLE = "TRABAJABLE"
    SIGUE_ESPERANDO = "SIGUE_ESPERANDO"
    OTRA_INTERVENCION = "OTRA_INTERVENCION"
    SIN_CAMBIOS = "SIN_CAMBIOS"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ResultadoRevalidacionOrden:
    """Que paso con una Orden en la revalidacion masiva.

    ``detalles_revalidados``: los Detalles que tenian recursos y quedaron
    trabajables en esta revalidacion.
    """

    orden_id: str
    resultado: str
    detalle: str
    current_process: str | None = None
    estado_workflow: str | None = None
    detalles_revalidados: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResultadoRevalidacionMasiva:
    """Resumen de la revalidacion: una entrada por Orden evaluada."""

    usuario_id: str
    fecha: datetime
    ordenes: Sequence[ResultadoRevalidacionOrden]

    def _contar(self, resultado: str) -> int:
        return sum(1 for orden in self.ordenes if orden.resultado == resultado)

    @property
    def evaluadas(self) -> int:
        return len(self.ordenes)

    @property
    def trabajables(self) -> int:
        return self._contar(ResultadoRevalidacion.TRABAJABLE)

    @property
    def siguen_esperando(self) -> int:
        return self._contar(ResultadoRevalidacion.SIGUE_ESPERANDO)

    @property
    def otra_intervencion(self) -> int:
        return self._contar(ResultadoRevalidacion.OTRA_INTERVENCION)

    @property
    def sin_cambios(self) -> int:
        return self._contar(ResultadoRevalidacion.SIN_CAMBIOS)

    @property
    def errores(self) -> int:
        return self._contar(ResultadoRevalidacion.ERROR)


# La Orden sigue operando: hay Detalles trabajables o uno en ejecucion.
_OPERANDO = (
    ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE,
    ResultadoEvaluacionOrden.EN_EJECUCION,
)


def _candidata(orden: OrdenReparacion) -> bool:
    """Orden abierta que espera recursos (100/120) o que tiene algun
    Detalle realmente bloqueado por recursos, este en el nodo que este."""
    if orden.esta_cerrada or orden.estado_workflow in (
        EstadoWorkflow.CANCELADA,
        EstadoWorkflow.ENTREGADA,
    ):
        return False
    return orden.current_process in NODOS_ESPERANDO_RECURSOS or bool(
        detalles_bloqueados_por_recursos(orden)
    )


def _con_factibilidad_parcial(orden: OrdenReparacion) -> bool:
    """Ya habilitada (PROC-REP-140 ocurrio) y operando mientras algun
    Detalle espera recursos."""
    return (
        orden.current_process not in NODOS_ESPERANDO_RECURSOS
        and fue_habilitada(orden)
        and situacion_de_la_orden(orden) in _OPERANDO
    )


def _describir_faltantes(faltantes: Mapping[str, Sequence[str]]) -> str:
    return "; ".join(
        f"{detalle_id} [{', '.join(insumos)}]"
        for detalle_id, insumos in sorted(faltantes.items())
        if insumos
    )


def _resultado(
    orden: OrdenReparacion,
    resultado: str,
    detalle: str,
    revalidados: Sequence[str] = (),
) -> ResultadoRevalidacionOrden:
    return ResultadoRevalidacionOrden(
        orden_id=orden.id,
        resultado=resultado,
        detalle=detalle,
        current_process=orden.current_process,
        estado_workflow=orden.estado_workflow.value,
        detalles_revalidados=tuple(revalidados),
    )


def _clasificar(
    orden: OrdenReparacion,
    revalidados: Sequence[str],
) -> ResultadoRevalidacionOrden:
    """Resultado de una Orden que esperaba en 100/120, tras 080 -> 090."""
    proceso = orden.current_process
    ultimo = orden.historial[-1].observacion if orden.historial else None
    if proceso == "PROC-REP-140":
        resultado = ResultadoRevalidacion.TRABAJABLE
        detalle = "Habilitada: tiene Detalles trabajables (PROC-REP-140)."
        if detalles_bloqueados_por_recursos(orden):
            detalle += " Algun Detalle sigue bloqueado por recursos."
    elif proceso in ("PROC-REP-170", "PROC-REP-211") and (
        situacion_de_la_orden(orden) in _OPERANDO
    ):
        resultado = ResultadoRevalidacion.TRABAJABLE
        detalle = (
            "Ya habilitada: sigue sin repetir PROC-REP-140, "
            f"{orden.estado_workflow.value} y con su prioridad ({proceso})."
        )
        if detalles_bloqueados_por_recursos(orden):
            detalle += " Algun Detalle sigue bloqueado por recursos."
    elif proceso == "PROC-REP-100":
        resultado = ResultadoRevalidacion.SIGUE_ESPERANDO
        detalle = f"Sigue sin recursos suficientes. {ultimo or ''}".strip()
    elif proceso == "PROC-REP-129":
        resultado = ResultadoRevalidacion.OTRA_INTERVENCION
        detalle = "Espera la autorizacion del cliente (PROC-REP-129)."
    else:
        resultado = ResultadoRevalidacion.OTRA_INTERVENCION
        detalle = f"Quedo en {proceso}: requiere revisarla."
    return _resultado(orden, resultado, detalle, revalidados)


def revalidar_ordenes_pendientes(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
) -> ResultadoRevalidacionMasiva:
    """Revalida contra el stock actual los Detalles bloqueados por recursos.

    Candidatas: Ordenes abiertas en PROC-REP-100/120 o con algun Detalle
    realmente bloqueado por recursos, sin depender del nodo principal.
    Cada una se procesa por separado, en su seccion critica, con la misma
    pregunta de PROC-REP-080 (``faltantes_de_detalles_bloqueados``):

    - Si ningun Detalle bloqueado tiene recursos todavia, la Orden no se
      toca (SIGUE_ESPERANDO): revalidar otra vez no duplica transiciones.
    - Esperando recursos (100/120): las transiciones existentes -110 No ->
      120 desde 100, y 120 -> 080 -> 090 -> 140 | 100-; una Orden ya
      habilitada no repite 140: 090 -> 211 y vuelve a la cola con su
      prioridad (``habilitar_o_reevaluar``).
    - Factibilidad parcial (habilitada y operando): los Detalles con
      recursos pasan a SIN_BLOQUEO como accion funcional, sin recorrer
      nodos ni repetir 140, sin tocar la toma, la Ejecucion en curso ni la
      prioridad (``desbloquear_detalles_con_recursos``).
    - En otra espera (revision tecnica, decision del cliente): se informa
      sin modificarla.

    Nunca reserva stock (la reserva sigue en PROC-REP-185) ni evalua
    Detalles pendientes de autorizacion o de revision. Una Orden que
    cambio en el medio no se toca (SIN_CAMBIOS); un error en una no frena
    a las demas.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, ROLES_REVALIDACION_RECURSOS)
    fecha = contexto.ahora()

    candidatas = sorted(
        (orden for orden in contexto.ordenes.listar() if _candidata(orden)),
        key=lambda orden: (orden.created_at, orden.id),
    )
    resultados: list[ResultadoRevalidacionOrden] = []
    for candidata in candidatas:
        try:
            resultados.append(
                _revalidar_una(contexto, candidata.id, usuario.id, fecha)
            )
        except PrecondicionInvalidaError as error:
            pendientes = sorted(detalles_pendientes_de_autorizacion(candidata))
            detalle = str(error)
            if pendientes:
                detalle = (
                    "Espera tambien la decision del cliente sobre "
                    f"{', '.join(pendientes)}: la revalidacion no la presume. "
                    "Registra la decision (o forza el Detalle bloqueado)."
                )
            resultados.append(
                _resultado(
                    candidata, ResultadoRevalidacion.OTRA_INTERVENCION, detalle
                )
            )
        except (DomainError, RepositoryError) as error:
            resultados.append(
                ResultadoRevalidacionOrden(
                    orden_id=candidata.id,
                    resultado=ResultadoRevalidacion.ERROR,
                    detalle=str(error),
                )
            )
    return ResultadoRevalidacionMasiva(
        usuario_id=usuario.id, fecha=fecha, ordenes=resultados
    )


def _revalidar_una(
    contexto: ApplicationContext,
    orden_id: str,
    usuario_id: str,
    fecha: datetime,
) -> ResultadoRevalidacionOrden:
    with (
        seccion_critica_inventario(),
        orden_para_modificar(contexto, orden_id) as orden,
    ):
        if not _candidata(orden):
            return _resultado(
                orden,
                ResultadoRevalidacion.SIN_CAMBIOS,
                f"Ya no espera recursos ({orden.current_process}): no se "
                "modifico.",
            )
        esperando = orden.current_process in NODOS_ESPERANDO_RECURSOS
        if not esperando and not _con_factibilidad_parcial(orden):
            return _resultado(
                orden,
                ResultadoRevalidacion.OTRA_INTERVENCION,
                "Tiene Detalles bloqueados por recursos, pero la Orden "
                f"espera otra intervencion ({orden.current_process}): no se "
                "modifico.",
            )

        faltantes = faltantes_de_detalles_bloqueados(
            orden,
            insumos=contexto.catalogos.listar_insumos(),
            insumos_previstos=(
                contexto.catalogos.listar_tipo_reparacion_insumos()
            ),
            reservas_externas=cargar_reservas_externas(
                orden.id, contexto.ordenes
            ),
        )
        con_recursos = sorted(
            detalle_id
            for detalle_id, insumos in faltantes.items()
            if not insumos
        )
        sin_recursos = _describir_faltantes(faltantes)
        ya_trabajable = (
            esperando
            and situacion_de_la_orden(orden)
            is ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE
        )
        if not con_recursos and not ya_trabajable:
            detalle = (
                f"Sin recursos todavia: {sin_recursos}. No se modifico."
                if sin_recursos
                else "Sin Detalles bloqueados por recursos para revalidar."
            )
            pendientes = sorted(detalles_pendientes_de_autorizacion(orden))
            if pendientes:
                detalle += (
                    " Espera tambien la decision del cliente sobre "
                    f"{', '.join(pendientes)}."
                )
            return _resultado(
                orden, ResultadoRevalidacion.SIGUE_ESPERANDO, detalle
            )

        if not esperando:
            orden = desbloquear_detalles_con_recursos(
                orden,
                detalle_ids=con_recursos,
                usuario_id=usuario_id,
                fecha=fecha,
            )
            contexto.ordenes.guardar(orden)
            detalle = (
                f"Factibilidad parcial: {', '.join(con_recursos)} ya tiene "
                f"recursos y quedo trabajable. La Orden sigue en "
                f"{orden.current_process}: sin nueva habilitacion; toma, "
                "Ejecucion y prioridad sin cambios."
            )
            if sin_recursos:
                detalle += f" Sin recursos todavia: {sin_recursos}."
            return _resultado(
                orden, ResultadoRevalidacion.TRABAJABLE, detalle, con_recursos
            )

        orden = registrar_accion_funcional(
            orden,
            accion_id=ACCION_REVALIDAR_RECURSOS,
            accion="REVALIDAR_RECURSOS",
            fecha=fecha,
            usuario_id=usuario_id,
            observacion="Revalidacion de las Ordenes que esperan recursos",
        )
        if orden.current_process == "PROC-REP-100":
            orden = registrar_espera_recursos(orden, fecha=fecha)
        orden = _validar_y_habilitar(contexto, orden, fecha=fecha)
        contexto.ordenes.guardar(orden)
    sigue_bloqueado = set(detalles_bloqueados_por_recursos(orden))
    return _clasificar(
        orden,
        [d for d in con_recursos if d not in sigue_bloqueado],
    )
