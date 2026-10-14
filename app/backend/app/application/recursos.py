"""Tramo de recursos (EXC-REP-001): esperar y revalidar.

    esperar_recursos     PROC-REP-110 (No) -> 120
    revalidar_recursos   PROC-REP-120 -> 080 -> 090 [-> 140 | -> 211 | -> 100]
    impacto_override     lectura: impacto en el stock de forzar un Detalle
    forzar_detalle_por_recursos
                         autorizacion transversal del Detalle (EXC-REP-002)
                         [en PROC-REP-100: 110 (Si) -> 130 -> 140 | -> 211]

Esperar y revalidar son eventos de sistema, sin actor humano: PROC-REP-120
es ACT-SYSTEM y la rama No de PROC-REP-110 no declara actor. El override es
de ACT-COORD. En el MVP un boton dispara
manualmente el evento de revalidacion ("cambio de disponibilidad de
insumos") que V1.3 describe.

El circuito no pertenece solo al ingreso: PROC-REP-120 tambien se alcanza
desde PROC-REP-211 en otros slices, con la Orden ya habilitada (por
ejemplo, tras una reserva fallida, EXC-REP-003). La habilitacion inicial
(PROC-REP-140) es un hito historico unico: una Orden ya habilitada sigue
por PROC-REP-211, sin repetir 140 ni la priorizacion
(``habilitar_o_reevaluar``).
"""

from dataclasses import dataclass

from app.domain.models import OrdenReparacion
from app.services import (
    ConfirmacionRequeridaError,
    ImpactoStockInsumo,
    autorizar_override_recursos,
    cargar_reservas_externas,
    continuar_por_override,
    exigir_espera_por_recursos,
    habilitar_o_reevaluar,
    impacto_en_stock_del_detalle,
    registrar_espera_recursos,
    validar_override_recursos,
)

from .concurrencia import seccion_critica_inventario
from .contexto import ApplicationContext
from .ingreso import _validar_y_habilitar
from .modificacion import orden_para_modificar


@dataclass(frozen=True)
class ImpactoOverride:
    """Lo que el Coordinador ve y confirma antes de forzar un Detalle (E3).

    Por cada insumo previsto: stock fisico, reservado (por otras Ordenes y
    por esta), disponible, requerido y disponible resultante. Las reservas
    de otras Ordenes se informan, nunca se tocan.
    """

    orden_id: str
    detalle_id: str
    insumos: tuple[ImpactoStockInsumo, ...]

    @property
    def deja_disponible_negativo(self) -> bool:
        return any(i.disponible_resultante < 0 for i in self.insumos)

    @property
    def hay_reservas_de_otras_ordenes(self) -> bool:
        return any(i.reservado_otras_ordenes > 0 for i in self.insumos)

    @property
    def advertencia(self) -> str:
        if self.deja_disponible_negativo:
            return (
                "El override deja el disponible en negativo. Las reservas "
                "de otras Ordenes se conservan y esas Ordenes podran "
                "completar igual sus Ejecuciones; si el stock fisico no "
                "alcanza, el faltante quedara registrado."
            )
        if self.hay_reservas_de_otras_ordenes:
            return (
                "Hay unidades reservadas por otras Ordenes: el override no "
                "las toca y el disponible alcanza."
            )
        return "El disponible alcanza: el override no deja faltantes."

    def describir(self) -> str:
        if not self.insumos:
            return "el Detalle no preve insumos"
        return "; ".join(insumo.describir() for insumo in self.insumos)


def _impacto_override(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
    detalle_id: str,
) -> ImpactoOverride:
    impactos = impacto_en_stock_del_detalle(
        orden,
        detalle_id,
        insumos=contexto.catalogos.listar_insumos(),
        insumos_previstos=contexto.catalogos.listar_tipo_reparacion_insumos(),
        reservas_externas=cargar_reservas_externas(orden.id, contexto.ordenes),
    )
    return ImpactoOverride(
        orden_id=orden.id, detalle_id=detalle_id, insumos=tuple(impactos)
    )


def esperar_recursos(
    contexto: ApplicationContext,
    *,
    orden_id: str,
) -> OrdenReparacion:
    """La Orden no fuerza el Detalle bloqueado y espera (110 No -> 120)."""
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_espera_recursos(orden, fecha=fecha)
        contexto.ordenes.guardar(orden)
    return orden


def revalidar_recursos(
    contexto: ApplicationContext,
    *,
    orden_id: str,
) -> OrdenReparacion:
    """Revalida la factibilidad contra el stock global actual (120 -> 080).

    Con al menos un Detalle trabajable, los Detalles que ahora tienen
    recursos vuelven a SIN_BLOQUEO y 090 Si -> 140 (HABILITADA) si la Orden
    nunca se habilito, o 090 Si -> 211 -> cola si ya se habilito
    (``habilitar_o_reevaluar``). Si todavia no hay ninguno: 090 Ninguno
    trabajable -> 100, y la Orden queda de nuevo lista para esperar (cada
    ciclo conserva su historial). No crea Detalles ni repite
    045/050/060/065/068/070/075; no reserva ni modifica el stock.
    """
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        exigir_espera_por_recursos(orden)
        orden = _validar_y_habilitar(contexto, orden, fecha=fecha)
        contexto.ordenes.guardar(orden)
    return orden


def impacto_override(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
) -> ImpactoOverride:
    """Vista previa del override de UN Detalle (E3). Solo lee."""
    orden = contexto.ordenes.obtener(orden_id)
    return _impacto_override(contexto, orden, detalle_id)


def forzar_detalle_por_recursos(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
    usuario_id: str,
    motivo: str,
    confirmado: bool,
) -> OrdenReparacion:
    """Un Coordinador autoriza el override de UN Detalle bloqueado.

    BR-REP-003 / EXC-REP-002: capacidad transversal por Detalle. Siempre
    registra la misma autorizacion (``autorizar_override_recursos``) y deja
    ese Detalle SIN_BLOQUEO; no reserva ni descuenta stock (la reserva es
    PROC-REP-185 y el consumo PROC-REP-210, donde el override habilita un
    disponible / stock negativo).

    E3: antes de aplicar se calcula el impacto en el stock y se exige
    ``confirmado``. Sin confirmacion explicita no se registra nada (409
    CONFIRMACION_REQUERIDA, con el impacto en el mensaje); confirmado, el
    impacto queda en el historial junto al motivo. Los permisos y el
    estado del Detalle se validan primero.

    Solo si la Orden esta detenida en PROC-REP-100 ("ningun Detalle
    trabajable") el proceso continua 110 "Si" -> 130 y, sin fabricar un
    090 "Si", -> 140 si nunca se habilito o -> 211 (cola) si ya se habilito:
    140 no se repite (``habilitar_o_reevaluar``). Con factibilidad parcial
    (Orden habilitada, en cola, tomada o en reparacion) no se recorre
    ningun nodo: no vuelve a 140, no cierra la toma ni toca la Ejecucion en
    curso. Persiste una sola vez.

    Corre en la seccion critica de inventario: el impacto lee las
    reservas de todas las Ordenes.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with (
        seccion_critica_inventario(),
        orden_para_modificar(contexto, orden_id) as orden,
    ):
        validar_override_recursos(
            orden, detalle_id=detalle_id, usuario=usuario, motivo=motivo
        )
        impacto = _impacto_override(contexto, orden, detalle_id)
        if not confirmado:
            raise ConfirmacionRequeridaError(
                f"El override del Detalle {detalle_id} requiere "
                f"confirmacion explicita. Impacto: {impacto.describir()}. "
                f"{impacto.advertencia}"
            )

        orden = autorizar_override_recursos(
            orden,
            detalle_id=detalle_id,
            usuario=usuario,
            motivo=motivo,
            fecha=fecha,
            impacto=impacto.describir(),
        )
        if orden.current_process == "PROC-REP-100":
            orden = continuar_por_override(
                orden, detalle_id=detalle_id, usuario=usuario, fecha=fecha
            )
            orden = habilitar_o_reevaluar(orden, fecha=fecha)

        contexto.ordenes.guardar(orden)
    return orden
