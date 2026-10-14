"""Decision del cliente por Detalle: PROC-REP-046 -> 047 [-> 300 | 305].

Nodos de V1.4 (FEAT-REP-002), solo para los Origenes que exigen la
autorizacion del cliente (``PoliticaOrigen.requiere_autorizacion_cliente``).
Recepcion registra, en UNA operacion, la respuesta del cliente sobre uno o
varios Detalles: cada uno se AUTORIZA o se RECHAZA sobre su definicion
vigente. "Sin respuesta" no es una decision: el Detalle no se incluye y
sigue pendiente, sin bloquear a los demas (BR-REP-037).

PROC-REP-047 enruta el resultado comercial, con las tres salidas de V1.4:

- ``ACEPTA_TRABAJOS``: todo lo decidido se autoriza.
- ``RECHAZA_ALGUNOS_DETALLES``: algun rechazo, pero queda trabajo
  pendiente o en curso; cada rechazado se cancela por PROC-REP-300.
- ``RECHAZA_TODOS_LOS_TRABAJOS``: se rechaza todo lo que quedaba por hacer;
  se cancela por PROC-REP-305. Lo COMPLETO nunca se toca.

Los rechazos se cancelan con los services de siempre
(``services.cancelaciones``), con origen ``RECHAZO_CLIENTE``. Que sigue
-factibilidad de los autorizados, habilitacion o PROC-REP-211- lo compone
la capa de aplicacion. Todo se valida antes de modificar nada: una
operacion mixta se aplica completa o no se aplica.

Desistimiento posterior (``registrar_desistimiento_cliente``): el cliente
habia autorizado un trabajo y lo deja sin efecto antes de que se realice.
Tambien es una decision de PROC-REP-046 (V1.4: "registra la autorizacion o
el desistimiento"), pero no reemplaza la autorizacion -que queda en la
historia-: se cancela el Detalle con origen ``DESISTIMIENTO_CLIENTE``. El
desistimiento de TODOS los trabajos rechaza ademas lo que seguia pendiente
y exige que nada lo impida (Ejecucion activa o reservas sin conciliar): si
algo lo impide, no se cancela nada.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.domain.models import (
    CanalComunicacion,
    CondicionReparacionDetail,
    EstadoReparacionDetail,
    OrdenReparacion,
    OrigenCancelacion,
    RegistroAutorizacionCliente,
    ReparacionDetail,
    ResultadoAutorizacion,
    RolUsuario,
    Usuario,
)

from .autorizacion import validar_actor
from .autorizacion_cliente import (
    EstadoAutorizacion,
    decision_vigente,
    estado_autorizacion,
    pendiente_de_autorizacion,
    requiere_autorizacion_cliente,
)
from .cancelaciones import (
    cancelar_detalle,
    cancelar_orden,
    exigir_orden_cancelable,
    tiene_ejecucion_activa,
    tiene_reservas_sin_conciliar,
    validar_cancelacion_detalle,
)
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .reparaciones import definicion_finalizada
from .workflow import registrar_paso

NODO_DECISION_CLIENTE = "PROC-REP-046"
NODO_RESULTADO_CLIENTE = "PROC-REP-047"


class ResultadoComercial(str, Enum):
    """Salida de PROC-REP-047 (V1.4): que decidio el cliente."""

    ACEPTA_TRABAJOS = "ACEPTA_TRABAJOS"
    RECHAZA_ALGUNOS_DETALLES = "RECHAZA_ALGUNOS_DETALLES"
    RECHAZA_TODOS_LOS_TRABAJOS = "RECHAZA_TODOS_LOS_TRABAJOS"


@dataclass(frozen=True)
class DecisionDetalle:
    """Respuesta del cliente sobre UN Detalle.

    ``version_definicion`` es la definicion sobre la que el cliente
    respondio: si ya no es la vigente, la respuesta no se aplica
    (BR-REP-029).
    """

    detalle_id: str
    version_definicion: int
    resultado: ResultadoAutorizacion


def _motivo_del_rechazo(
    canal: CanalComunicacion,
    observaciones: str | None,
) -> str:
    motivo = f"Rechazo del cliente ({canal.value})"
    if observaciones:
        motivo += f": {observaciones}"
    return motivo


def _por_que_no_espera_decision(detalle: ReparacionDetail) -> str:
    if detalle.estado is EstadoReparacionDetail.COMPLETO:
        return "esta COMPLETO: el trabajo realizado no se autoriza ni rechaza"
    if detalle.estado is EstadoReparacionDetail.EN_PROGRESO:
        return "tiene una Ejecucion activa"
    if detalle.estado is EstadoReparacionDetail.CANCELADO:
        return "esta CANCELADO"
    if detalle.condicion is CondicionReparacionDetail.REQUIERE_DEFINICION:
        return (
            "requiere redefinicion: la definicion nueva pedira su propia "
            "decision"
        )
    return f"esta {detalle.estado.value}"


def _validar_decision(
    orden: OrdenReparacion,
    decision: DecisionDetalle,
) -> ReparacionDetail:
    """El Detalle existe, la respuesta es de su definicion vigente y espera
    decision. Una decision registrada nunca se reemplaza (reintentos)."""
    detalle = next(
        (d for d in orden.reparaciones_detail if d.id == decision.detalle_id),
        None,
    )
    if detalle is None:
        raise EntidadNoEncontradaError(
            f"La Orden {orden.id} no tiene el Detalle {decision.detalle_id}."
        )
    vigente = detalle.version_definicion
    if decision.version_definicion != vigente:
        raise PrecondicionInvalidaError(
            f"La respuesta es sobre la definicion v"
            f"{decision.version_definicion} del Detalle {detalle.id}, pero "
            f"la vigente es v{vigente}: una decision sobre otra definicion "
            "no la autoriza ni la rechaza (BR-REP-029)."
        )
    estado = estado_autorizacion(orden, detalle)
    if estado in (EstadoAutorizacion.AUTORIZADO, EstadoAutorizacion.RECHAZADO):
        registrada = decision_vigente(detalle)
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle.id} ya tiene la decision del cliente para "
            f"su definicion vigente (v{vigente}): {estado.value} por "
            f"{registrada.usuario_id} el {registrada.fecha:%Y-%m-%d %H:%M}. "
            "Una decision registrada no se reemplaza."
        )
    if estado is not EstadoAutorizacion.PENDIENTE:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle.id} no espera una decision del cliente: "
            f"{_por_que_no_espera_decision(detalle)}."
        )
    return detalle


def _resultado_comercial(
    orden: OrdenReparacion,
    autorizados: Sequence[str],
    rechazados: Sequence[str],
) -> ResultadoComercial:
    if not rechazados:
        return ResultadoComercial.ACEPTA_TRABAJOS
    sin_terminar = {
        detalle.id
        for detalle in orden.reparaciones_detail
        if detalle.estado
        in (
            EstadoReparacionDetail.DEFINIDO,
            EstadoReparacionDetail.EN_PROGRESO,
        )
    }
    if not autorizados and set(rechazados) == sin_terminar:
        return ResultadoComercial.RECHAZA_TODOS_LOS_TRABAJOS
    return ResultadoComercial.RECHAZA_ALGUNOS_DETALLES


def registrar_decision_cliente(
    orden: OrdenReparacion,
    *,
    decisiones: Sequence[DecisionDetalle],
    usuario: Usuario,
    canal: CanalComunicacion,
    fecha: datetime,
    observaciones: str | None = None,
) -> tuple[OrdenReparacion, tuple[str, ...]]:
    """PROC-REP-046 -> 047 [-> 300 | 305]: registra la decision del cliente.

    ACT-RECEP. Exige la definicion finalizada (los Detalles y sus precios
    ya se presentaron al cliente) y al menos una decision; cada Detalle a
    lo sumo una vez, PENDIENTE y con la version vigente. Cada decision
    queda en el Detalle (``autorizaciones``) y en el historial (046, con
    canal y observaciones). Los rechazados se cancelan con origen
    ``RECHAZO_CLIENTE``; los autorizados quedan listos para PROC-REP-080.

    Devuelve la Orden y los IDs autorizados (para su factibilidad).
    """
    validar_actor(usuario, RolUsuario.RECEPCION)
    if not requiere_autorizacion_cliente(orden):
        raise PrecondicionInvalidaError(
            f"Una Orden {orden.origen.value} no requiere la autorizacion del "
            "cliente por Detalle."
        )
    if not orden.reparaciones_detail:
        raise PrecondicionInvalidaError(
            "La Orden no tiene Detalles: no hay trabajos que autorizar."
        )
    if not definicion_finalizada(orden):
        raise PrecondicionInvalidaError(
            "Primero hay que finalizar la definicion de los Detalles: el "
            "cliente decide sobre los trabajos y precios definitivos."
        )
    if not decisiones:
        raise PrecondicionInvalidaError(
            "No hay decisiones para registrar. Si el cliente todavia no "
            "respondio no se registra nada: los Detalles siguen pendientes."
        )
    ids = [decision.detalle_id for decision in decisiones]
    if len(set(ids)) != len(ids):
        raise PrecondicionInvalidaError(
            "Cada Detalle se decide una sola vez por operacion."
        )

    observaciones = (observaciones or "").strip() or None
    motivo_rechazo = _motivo_del_rechazo(canal, observaciones)
    for decision in decisiones:
        _validar_decision(orden, decision)
    autorizados = [
        decision.detalle_id
        for decision in decisiones
        if decision.resultado is ResultadoAutorizacion.AUTORIZADO
    ]
    rechazados = [
        decision.detalle_id
        for decision in decisiones
        if decision.resultado is ResultadoAutorizacion.RECHAZADO
    ]
    for detalle_id in rechazados:
        validar_cancelacion_detalle(
            orden,
            detalle_id=detalle_id,
            usuario=usuario,
            motivo=motivo_rechazo,
        )
    resultado = _resultado_comercial(orden, autorizados, rechazados)

    nueva_orden = orden
    for decision in decisiones:
        observacion = (
            f"{decision.resultado.value} (definicion v"
            f"{decision.version_definicion}, canal {canal.value})"
        )
        if observaciones:
            observacion += f": {observaciones}"
        nueva_orden = registrar_paso(
            nueva_orden,
            process_id=NODO_DECISION_CLIENTE,
            accion="REGISTRAR_DECISION_CLIENTE",
            fecha=fecha,
            usuario_id=usuario.id,
            reparacion_detail_id=decision.detalle_id,
            observacion=observacion,
        )
        detalle = next(
            d
            for d in nueva_orden.reparaciones_detail
            if d.id == decision.detalle_id
        )
        detalle.autorizaciones.append(
            RegistroAutorizacionCliente(
                version_definicion=decision.version_definicion,
                resultado=decision.resultado,
                usuario_id=usuario.id,
                fecha=fecha,
                canal=canal,
                observaciones=observaciones,
            )
        )
    nueva_orden = registrar_paso(
        nueva_orden,
        process_id=NODO_RESULTADO_CLIENTE,
        accion="QUE_DECIDIO_EL_CLIENTE",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=resultado.value,
    )

    if resultado is ResultadoComercial.RECHAZA_TODOS_LOS_TRABAJOS:
        nueva_orden = cancelar_orden(
            nueva_orden,
            usuario=usuario,
            motivo=motivo_rechazo,
            fecha=fecha,
            origen=OrigenCancelacion.RECHAZO_CLIENTE,
        )
    else:
        for detalle_id in rechazados:
            nueva_orden = cancelar_detalle(
                nueva_orden,
                detalle_id=detalle_id,
                usuario=usuario,
                motivo=motivo_rechazo,
                fecha=fecha,
                origen=OrigenCancelacion.RECHAZO_CLIENTE,
            )
    return nueva_orden, tuple(autorizados)


# --- Desistimiento posterior a la autorizacion -------------------------------


@dataclass(frozen=True)
class AnalisisDesistimiento:
    """Que pasaria si el cliente desiste de todos los trabajos cancelables.

    ``rechazables``: pendientes de autorizacion (se registra su rechazo).
    ``desistibles``: ya autorizados y todavia cancelables (desistimiento).
    ``bloqueantes``: lo que impide el desistimiento total, con el motivo.
    ``conservados``: lo COMPLETO, que nunca se cancela.
    """

    rechazables: tuple[str, ...]
    desistibles: tuple[str, ...]
    bloqueantes: tuple[tuple[str, str], ...]
    conservados: tuple[str, ...]

    @property
    def cancelables(self) -> tuple[str, ...]:
        return self.rechazables + self.desistibles


def analizar_desistimiento(orden: OrdenReparacion) -> AnalisisDesistimiento:
    """Clasifica cada Detalle frente a un desistimiento total. Solo lee.

    Usa las mismas protecciones que la cancelacion (Ejecucion activa,
    reservas sin conciliar): la UI muestra exactamente lo que el comando va
    a exigir.
    """
    rechazables: list[str] = []
    desistibles: list[str] = []
    bloqueantes: list[tuple[str, str]] = []
    conservados: list[str] = []
    for detalle in orden.reparaciones_detail:
        if detalle.estado is EstadoReparacionDetail.CANCELADO:
            continue
        if detalle.estado is EstadoReparacionDetail.COMPLETO:
            conservados.append(detalle.id)
        elif tiene_ejecucion_activa(orden, detalle.id):
            bloqueantes.append(
                (
                    detalle.id,
                    "tiene una Ejecucion activa: hay que completarla o "
                    "interrumpirla (PROC-REP-200)",
                )
            )
        elif tiene_reservas_sin_conciliar(orden, detalle.id):
            bloqueantes.append(
                (detalle.id, "tiene reservas de insumos sin conciliar")
            )
        elif pendiente_de_autorizacion(orden, detalle):
            rechazables.append(detalle.id)
        else:
            desistibles.append(detalle.id)
    return AnalisisDesistimiento(
        rechazables=tuple(rechazables),
        desistibles=tuple(desistibles),
        bloqueantes=tuple(bloqueantes),
        conservados=tuple(conservados),
    )


def _exigir_desistimiento_posible(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    motivo: str,
) -> None:
    validar_actor(usuario, RolUsuario.RECEPCION)
    if not requiere_autorizacion_cliente(orden):
        raise PrecondicionInvalidaError(
            f"Una Orden {orden.origen.value} no tiene decisiones del cliente "
            "por Detalle: se cancela con la cancelacion interna."
        )
    if not motivo.strip():
        raise PrecondicionInvalidaError(
            "El desistimiento del cliente exige un motivo."
        )
    if not definicion_finalizada(orden):
        raise PrecondicionInvalidaError(
            "La definicion todavia no se le presento al cliente: no hay "
            "nada de lo que desistir (se cancela con la cancelacion "
            "interna)."
        )
    exigir_orden_cancelable(orden)


def _registrar_rechazo(
    orden: OrdenReparacion,
    detalle_id: str,
    *,
    usuario: Usuario,
    canal: CanalComunicacion,
    motivo: str,
    fecha: datetime,
) -> OrdenReparacion:
    """046 RECHAZADO de un Detalle pendiente, con su registro de decision."""
    version = next(
        d for d in orden.reparaciones_detail if d.id == detalle_id
    ).version_definicion
    nueva_orden = registrar_paso(
        orden,
        process_id=NODO_DECISION_CLIENTE,
        accion="REGISTRAR_DECISION_CLIENTE",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=(
            f"RECHAZADO (definicion v{version}, canal {canal.value}): {motivo}"
        ),
    )
    next(
        d for d in nueva_orden.reparaciones_detail if d.id == detalle_id
    ).autorizaciones.append(
        RegistroAutorizacionCliente(
            version_definicion=version,
            resultado=ResultadoAutorizacion.RECHAZADO,
            usuario_id=usuario.id,
            fecha=fecha,
            canal=canal,
            observaciones=motivo,
        )
    )
    return nueva_orden


def _registrar_desistimiento(
    orden: OrdenReparacion,
    detalle_id: str,
    *,
    usuario: Usuario,
    canal: CanalComunicacion,
    motivo: str,
    fecha: datetime,
) -> OrdenReparacion:
    """046 DESISTE de un Detalle ya autorizado: su autorizacion no cambia."""
    detalle = next(d for d in orden.reparaciones_detail if d.id == detalle_id)
    previa = decision_vigente(detalle)
    antecedente = (
        f"autorizado por {previa.usuario_id} el {previa.fecha:%Y-%m-%d %H:%M}"
        if previa is not None
        else "sin decision registrada"
    )
    return registrar_paso(
        orden,
        process_id=NODO_DECISION_CLIENTE,
        accion="REGISTRAR_DESISTIMIENTO_CLIENTE",
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=(
            f"DESISTE (definicion v{detalle.version_definicion}, "
            f"{antecedente}; canal {canal.value}): {motivo}"
        ),
    )


def registrar_desistimiento_cliente(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    canal: CanalComunicacion,
    motivo: str,
    fecha: datetime,
    detalle_id: str | None = None,
) -> OrdenReparacion:
    """El cliente desiste: de UN Detalle autorizado, o de todo lo cancelable.

    ACT-RECEP, motivo obligatorio. Con ``detalle_id``, el Detalle tiene que
    haber sido autorizado (uno pendiente se rechaza con
    ``registrar_decision_cliente``) y seguir cancelable. Sin
    ``detalle_id`` es el desistimiento TOTAL: los pendientes se rechazan,
    los autorizados se desisten y lo COMPLETO se conserva; si algun Detalle
    lo impide (``AnalisisDesistimiento.bloqueantes``) no se cancela nada.

    Registra PROC-REP-046 por Detalle (rechazo o desistimiento, con canal y
    motivo), 047 y la cancelacion (300 o 305) con origen
    ``DESISTIMIENTO_CLIENTE`` / ``RECHAZO_CLIENTE``. Las autorizaciones
    anteriores no se tocan. Que sigue lo decide PROC-REP-211 (caller).
    """
    _exigir_desistimiento_posible(orden, usuario=usuario, motivo=motivo)
    motivo = motivo.strip()

    if detalle_id is None:
        analisis = analizar_desistimiento(orden)
        if analisis.bloqueantes:
            impedimentos = "; ".join(
                f"{bloqueado} {razon}"
                for bloqueado, razon in analisis.bloqueantes
            )
            raise PrecondicionInvalidaError(
                "No se registra el desistimiento de todos los trabajos: "
                f"{impedimentos}. Primero hay que resolverlo; no se cancelo "
                "nada."
            )
        if not analisis.cancelables:
            raise PrecondicionInvalidaError(
                "No quedan trabajos cancelables: lo que queda esta COMPLETO "
                "o ya CANCELADO."
            )
        rechazados = list(analisis.rechazables)
        desistidos = list(analisis.desistibles)
        motivo_cancelacion = (
            f"El cliente desiste de todos los trabajos ({canal.value}): "
            f"{motivo}"
        )
    else:
        detalle = next(
            (d for d in orden.reparaciones_detail if d.id == detalle_id),
            None,
        )
        if detalle is None:
            raise EntidadNoEncontradaError(
                f"La Orden {orden.id} no tiene el Detalle {detalle_id}."
            )
        if pendiente_de_autorizacion(orden, detalle):
            raise PrecondicionInvalidaError(
                f"El Detalle {detalle_id} sigue pendiente de autorizacion: no "
                "hubo autorizacion de la que desistir. Corresponde registrar "
                "el rechazo del cliente."
            )
        rechazados = []
        desistidos = [detalle_id]
        motivo_cancelacion = (
            f"El cliente desiste despues de autorizar ({canal.value}): "
            f"{motivo}"
        )
    for cancelable in rechazados + desistidos:
        validar_cancelacion_detalle(
            orden,
            detalle_id=cancelable,
            usuario=usuario,
            motivo=motivo_cancelacion,
        )
    resultado = _resultado_comercial(orden, [], rechazados + desistidos)

    nueva_orden = orden
    for rechazado in rechazados:
        nueva_orden = _registrar_rechazo(
            nueva_orden,
            rechazado,
            usuario=usuario,
            canal=canal,
            motivo=motivo,
            fecha=fecha,
        )
    for desistido in desistidos:
        nueva_orden = _registrar_desistimiento(
            nueva_orden,
            desistido,
            usuario=usuario,
            canal=canal,
            motivo=motivo,
            fecha=fecha,
        )
    nueva_orden = registrar_paso(
        nueva_orden,
        process_id=NODO_RESULTADO_CLIENTE,
        accion="QUE_DECIDIO_EL_CLIENTE",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=resultado.value,
    )

    origenes = {
        rechazado: OrigenCancelacion.RECHAZO_CLIENTE
        for rechazado in rechazados
    } | {
        desistido: OrigenCancelacion.DESISTIMIENTO_CLIENTE
        for desistido in desistidos
    }
    if resultado is ResultadoComercial.RECHAZA_TODOS_LOS_TRABAJOS:
        return cancelar_orden(
            nueva_orden,
            usuario=usuario,
            motivo=motivo_cancelacion,
            fecha=fecha,
            origen=OrigenCancelacion.DESISTIMIENTO_CLIENTE,
            origenes=origenes,
        )
    for cancelable, origen in origenes.items():
        nueva_orden = cancelar_detalle(
            nueva_orden,
            detalle_id=cancelable,
            usuario=usuario,
            motivo=motivo_cancelacion,
            fecha=fecha,
            origen=origen,
        )
    return nueva_orden
