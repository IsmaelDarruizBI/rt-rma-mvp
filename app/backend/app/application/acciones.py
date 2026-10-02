"""Acciones humanas disponibles, derivadas del estado real de la Orden.

Dos preguntas que la UI necesita y que no le corresponde responder a
ella, porque dependen del proceso funcional y no de la pantalla: que
accion humana corresponde ahora, y a que rol. Nada de esto autoriza
nada: la autorizacion y las precondiciones las siguen validando los
services cuando el comando llega. Esto es solo lo que la pantalla puede
ofrecer.

Las acciones se derivan de:

    estado_workflow, origen/politica, situacion tecnica de los
    Detalles, toma activa, ejecucion activa, condicion comercial

NUNCA de a que Scenario "pertenece" la Orden: no hay ningun
``if origen == ...: acciones_de_hp1()`` ni equivalente. La politica
(``domain.politicas.politica_de``) es lo unico que distingue el
comportamiento por Origen -CLIENTE_EXTERNO (HP-REP-001) y RT_INTERNO
(HP-REP-002) comparten esta misma funcion-, nunca un ``if`` sobre el
Origen o el Scenario.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.domain.models import (
    CondicionReparacionDetail,
    EstadoControl,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    RolUsuario,
)
from app.domain.politicas import CondicionComercial, politica_de
from app.services import (
    ejecucion_activa,
    requiere_definicion,
    revision_vigente,
    toma_activa,
)
from app.services.ordenes import ROLES_ENTREGA, ROLES_PRIORIZACION
from app.services.pagos import ROLES_PAGO, condicion_entrega_cumplida
from app.services.reparaciones import definicion_finalizada
from app.services.revisiones import (
    finalizada_sin_reparacion,
    lista_para_cierre,
    revision_tecnica_realizada,
)

from .progreso import nodos_alcanzados

# Codigos de accion que la API expone. Cada uno es exactamente un
# endpoint de comando.
ACCION_AGREGAR_DETALLE = "AGREGAR_DETALLE"
ACCION_FINALIZAR_DEFINICION = "FINALIZAR_DEFINICION"
ACCION_ENCOLAR = "ENCOLAR"
ACCION_TOMAR = "TOMAR"
ACCION_INICIAR_DETALLE = "INICIAR_DETALLE"
ACCION_COMPLETAR_EJECUCION = "COMPLETAR_EJECUCION"
ACCION_INTERRUMPIR_EJECUCION = "INTERRUMPIR_EJECUCION"
ACCION_APROBAR_CONTROL = "APROBAR_CONTROL"
ACCION_LIBERAR_ORDEN = "LIBERAR_ORDEN"
ACCION_NOTIFICAR = "NOTIFICAR"
ACCION_REGISTRAR_PAGO = "REGISTRAR_PAGO"
ACCION_ENTREGAR = "ENTREGAR"
ACCION_INFORMAR_RT = "INFORMAR_RT"
ACCION_DEVOLVER_RT = "DEVOLVER_RT"
ACCION_INICIAR_GARANTIA_RMA = "INICIAR_GARANTIA_RMA"
ACCION_ENVIAR_A_REVISION = "ENVIAR_A_REVISION"
ACCION_REALIZAR_REVISION = "REALIZAR_REVISION"
ACCION_AGREGAR_DETALLE_DESDE_REVISION = "AGREGAR_DETALLE_DESDE_REVISION"
ACCION_FINALIZAR_SIN_REPARACION = "FINALIZAR_SIN_REPARACION"
ACCION_ESPERAR_RECURSOS = "ESPERAR_RECURSOS"
ACCION_REVALIDAR_RECURSOS = "REVALIDAR_RECURSOS"
ACCION_OVERRIDE_RECURSOS = "OVERRIDE_RECURSOS"
ACCION_REQUIERE_REDEFINICION = "REQUIERE_REDEFINICION"
ACCION_REVISAR_DETALLE = "REVISAR_DETALLE"
ACCION_REDEFINIR_DETALLE = "REDEFINIR_DETALLE"

# EXC-REP-004: circuito de revision posterior (125 espera, 126 revision).
_NODOS_REVISION_POSTERIOR = ("PROC-REP-125", "PROC-REP-126")

CERO = Decimal("0")


@dataclass(frozen=True)
class AccionDisponible:
    """Un paso que la Orden admite ahora mismo, humano o de sistema.

    ``roles`` lista TODOS los actores autorizados: un nodo puede
    declarar ``actores_alternativos`` en PROC-REP V1.3 (por ejemplo
    PROC-REP-150 y PROC-REP-270), y entonces son varios sin jerarquia.
    ``roles: ()`` con ``requiere_actor: True`` (default) significa que el
    negocio TODAVIA no definio el rol (por ejemplo Registrar Pago antes
    de BR-REP-017): sigue siendo una accion humana, solo que cualquier
    usuario activo puede ejecutarla.

    ``requiere_actor`` es una dimension distinta: ``False`` marca un
    ``PROC-REP-*`` declarado ``actor: ACT-SYSTEM`` en el Business Process
    (por ejemplo PROC-REP-290). Ahi NO hay ningun actor humano que
    autorizar -ni "cualquiera", ni "todavia sin definir"-: no
    corresponde exigir ``usuario_id`` en el comando. El MVP igual lo
    expone como paso demostrable en la UI para poder disparar el nodo.
    """

    codigo: str
    etiqueta: str
    roles: tuple[RolUsuario, ...] = ()
    detalle_id: str | None = None
    ejecucion_id: str | None = None
    requiere_actor: bool = True


def detalle_trabajable(orden: OrdenReparacion) -> str | None:
    """Primer Detalle DEFINIDO y SIN_BLOQUEO, que es el que se puede iniciar.

    Consistente con ``services.resolucion._es_trabajable``: un Detalle
    DEFINIDO pero bloqueado (``REQUIERE_DEFINICION`` o
    ``BLOQUEADO_POR_RECURSOS``) no es trabajable.

    Se conserva para compatibilidad (``application.happy_path`` y los
    tests que ya la importan). ``acciones_disponibles`` usa la version
    plural, ``detalles_trabajables``: con Multi-Detalle puede haber mas
    de uno, y no le corresponde a este modulo elegir cual por el
    tecnico (PROC-REP-181).
    """
    for detalle in orden.reparaciones_detail:
        if (
            detalle.estado is EstadoReparacionDetail.DEFINIDO
            and detalle.condicion is CondicionReparacionDetail.SIN_BLOQUEO
        ):
            return detalle.id
    return None


def detalles_trabajables(orden: OrdenReparacion) -> list[str]:
    """Todos los Detalles DEFINIDO y SIN_BLOQUEO, en orden de aparicion.

    Con Multi-Detalle puede haber mas de un Detalle trabajable a la vez:
    la eleccion de cual iniciar ahora es del tecnico (PROC-REP-181), no
    algo que esta funcion deba decidir.
    """
    return [
        detalle.id
        for detalle in orden.reparaciones_detail
        if detalle.estado is EstadoReparacionDetail.DEFINIDO
        and detalle.condicion is CondicionReparacionDetail.SIN_BLOQUEO
    ]


def _detalles_en_espera_de_control(orden: OrdenReparacion) -> list[str]:
    """Detalles con control PENDIENTE, aprobables ahora mismo.

    PROC-REP-220 solo se alcanza cuando la Orden ENTERA es terminal
    (todos sus Detalles COMPLETO, igual que exige
    ``services.reparaciones.aprobar_control_tecnico``): mientras quede
    algun Detalle DEFINIDO o EN_PROGRESO no se ofrece ninguna accion de
    control, ni siquiera para un Detalle que ya este COMPLETO. Una vez
    ahi, el control SI es granular por Detalle (PROC-REP-220): cada uno
    se aprueba de forma independiente. PROC-REP-230 es, en cambio, la
    decision global "todos los Detalles aprobados".
    """
    if ejecucion_activa(orden) is not None:
        return []
    if any(
        detalle.estado is not EstadoReparacionDetail.COMPLETO
        for detalle in orden.reparaciones_detail
    ):
        return []
    return [
        detalle.id
        for detalle in orden.reparaciones_detail
        if detalle.control_estado is EstadoControl.PENDIENTE
    ]


def _overrides_de_recursos(
    orden: OrdenReparacion,
) -> list[AccionDisponible]:
    """EXC-REP-002 / BR-REP-003: override, capacidad transversal por Detalle.

    Una accion de Coordinador RMA por cada Detalle PENDIENTE (DEFINIDO)
    bloqueado por recursos, este la Orden detenida en PROC-REP-100/120 o
    con factibilidad parcial (habilitada, en cola, tomada o en reparacion).
    """
    return [
        AccionDisponible(
            codigo=ACCION_OVERRIDE_RECURSOS,
            etiqueta="Forzar el Detalle bloqueado (override)",
            roles=(RolUsuario.COORDINADOR_RMA,),
            detalle_id=detalle.id,
        )
        for detalle in orden.reparaciones_detail
        if detalle.estado is EstadoReparacionDetail.DEFINIDO
        and detalle.condicion
        is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
    ]


def acciones_disponibles(orden: OrdenReparacion) -> list[AccionDisponible]:
    """Acciones humanas que corresponden al estado actual de la Orden.

    Una Orden ENTREGADA solo admite INICIAR_GARANTIA_RMA (una unica
    accion a nivel Orden, si tiene Cliente y Detalles que puedan originar
    la garantia): su proceso termino. Lo mismo
    vale para RT_INTERNO al llegar a EVT-REP-999: ese origen no pasa por
    ENTREGADA (el estado terminal sigue pendiente de definicion, ver
    ``devolver_equipo_rt``), asi que el fin de proceso se detecta por
    ``current_process`` para no dejar acciones abiertas.
    """
    if (
        orden.estado_workflow is EstadoWorkflow.ENTREGADA
        and orden.cliente is not None
    ):
        # HP-REP-003: el proceso de ESTA Orden termino, pero Recepcion
        # puede iniciar UNA garantia RMA eligiendo 1..N de sus Detalles
        # (la seleccion es del formulario, no una accion por Detalle). La
        # garantia siempre entra en revision tecnica (BR-REP-019).
        if not orden.reparaciones_detail:
            return []
        return [
            AccionDisponible(
                codigo=ACCION_INICIAR_GARANTIA_RMA,
                etiqueta="Iniciar garantia RMA",
                roles=(RolUsuario.RECEPCION,),
            )
        ]

    if (
        orden.estado_workflow is EstadoWorkflow.ENTREGADA
        or orden.current_process == "EVT-REP-999"
    ):
        return []

    politica = politica_de(orden.origen)

    acciones: list[AccionDisponible] = []
    estado = orden.estado_workflow
    alcanzados = nodos_alcanzados(orden)

    # EXC-REP-001: en PROC-REP-100/120 el circuito de recursos tiene
    # prioridad sobre el hito de workflow (REQUERIMIENTO / EN_REVISION
    # siguen siendo el ultimo hito, pero ya no corresponde definir ni
    # encolar). Son acciones de sistema (sin actor humano). Las
    # capacidades transversales (pago) siguen valiendo mas abajo.
    en_recursos = orden.current_process in (
        "PROC-REP-100",
        "PROC-REP-120",
    )
    overrides = _overrides_de_recursos(orden)
    if en_recursos:
        estado = None
        acciones.append(
            AccionDisponible(
                codigo=(
                    ACCION_ESPERAR_RECURSOS
                    if orden.current_process == "PROC-REP-100"
                    else ACCION_REVALIDAR_RECURSOS
                ),
                etiqueta=(
                    "Esperar recursos (no forzar el Detalle bloqueado)"
                    if orden.current_process == "PROC-REP-100"
                    else "Revalidar la disponibilidad de recursos"
                ),
                roles=(),
                requiere_actor=False,
            )
        )
        # En PROC-REP-100 el override convive con "esperar" (las dos ramas
        # de PROC-REP-110); en 120 autoriza el Detalle hasta revalidar.
        acciones.extend(overrides)

    # EXC-REP-004: en PROC-REP-125/126 cada Detalle pendiente se revisa
    # (Tecnico, PROC-REP-126) y, ya revisado en su ciclo actual, se
    # redefine (Recepcion, PROC-REP-127). Como en 100/120, el hito de
    # workflow (EN_REPARACION) no ofrece nada propio.
    if orden.current_process in _NODOS_REVISION_POSTERIOR:
        estado = None
        for detalle in orden.reparaciones_detail:
            if not requiere_definicion(detalle):
                continue
            if revision_vigente(orden, detalle.id):
                acciones.append(
                    AccionDisponible(
                        codigo=ACCION_REDEFINIR_DETALLE,
                        etiqueta="Redefinir la reparacion del Detalle",
                        roles=(RolUsuario.RECEPCION,),
                        detalle_id=detalle.id,
                    )
                )
            else:
                acciones.append(
                    AccionDisponible(
                        codigo=ACCION_REVISAR_DETALLE,
                        etiqueta="Realizar la revision tecnica del Detalle",
                        roles=(RolUsuario.TECNICO,),
                        detalle_id=detalle.id,
                    )
                )

    # Definicion de Detalles: agregar y finalizar son acciones distintas.
    # La definicion se cierra al validar la factibilidad (PROC-REP-080).
    definicion_abierta = not definicion_finalizada(orden)

    if estado is EstadoWorkflow.REQUERIMIENTO and definicion_abierta:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_AGREGAR_DETALLE,
                etiqueta="Agregar un Detalle de reparacion",
                roles=(RolUsuario.RECEPCION,),
            )
        )
        # PROC-REP-045 tiene dos ramas: Detalles conocidos o revision. Con
        # al menos un Detalle cargado la revision ya no corresponde y se
        # puede cerrar la carga.
        acciones.append(
            AccionDisponible(
                codigo=(
                    ACCION_FINALIZAR_DEFINICION
                    if orden.reparaciones_detail
                    else ACCION_ENVIAR_A_REVISION
                ),
                etiqueta=(
                    "Finalizar la definicion"
                    if orden.reparaciones_detail
                    else "Enviar a revision tecnica (sin diagnostico)"
                ),
                roles=(RolUsuario.RECEPCION,),
            )
        )

    if (
        estado is EstadoWorkflow.EN_REVISION
        and definicion_abierta
        and not finalizada_sin_reparacion(orden)
    ):
        if not revision_tecnica_realizada(orden):
            acciones.append(
                AccionDisponible(
                    codigo=ACCION_REALIZAR_REVISION,
                    etiqueta="Realizar la revision tecnica",
                    roles=(RolUsuario.TECNICO,),
                )
            )
        else:
            acciones.append(
                AccionDisponible(
                    codigo=ACCION_AGREGAR_DETALLE_DESDE_REVISION,
                    etiqueta="Agregar un Detalle luego de la revision",
                    roles=(RolUsuario.RECEPCION,),
                )
            )
            # PROC-REP-068: sin Detalles todavia se puede concluir
            # SIN_REPARACION (069); con al menos uno, solo finalizar.
            acciones.append(
                AccionDisponible(
                    codigo=(
                        ACCION_FINALIZAR_DEFINICION
                        if orden.reparaciones_detail
                        else ACCION_FINALIZAR_SIN_REPARACION
                    ),
                    etiqueta=(
                        "Finalizar la definicion"
                        if orden.reparaciones_detail
                        else "Finalizar sin reparacion"
                    ),
                    roles=(RolUsuario.RECEPCION,),
                )
            )

    if estado is EstadoWorkflow.HABILITADA:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_ENCOLAR,
                etiqueta="Priorizar e ingresar a la cola",
                roles=ROLES_PRIORIZACION,
            )
        )

    if estado is EstadoWorkflow.EN_COLA and toma_activa(orden) is None:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_TOMAR,
                etiqueta="Tomar la Orden",
                roles=(RolUsuario.TECNICO,),
            )
        )

    en_curso = ejecucion_activa(orden)
    toma = toma_activa(orden)

    if toma is not None and en_curso is None:
        for trabajable in detalles_trabajables(orden):
            acciones.append(
                AccionDisponible(
                    codigo=ACCION_INICIAR_DETALLE,
                    etiqueta="Iniciar el Detalle",
                    roles=(RolUsuario.TECNICO,),
                    detalle_id=trabajable,
                )
            )
        acciones.append(
            AccionDisponible(
                codigo=ACCION_LIBERAR_ORDEN,
                etiqueta="Liberar la Orden (PROC-REP-212/213)",
                roles=(RolUsuario.TECNICO,),
            )
        )

    if estado is EstadoWorkflow.EN_REPARACION and en_curso is not None:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_COMPLETAR_EJECUCION,
                etiqueta="Registrar la ejecucion realizada",
                roles=(RolUsuario.TECNICO,),
                detalle_id=en_curso.reparacion_detail_id,
                ejecucion_id=en_curso.id,
            )
        )
        # VAR-REP-003: la otra salida de PROC-REP-200. Continuar luego es
        # iniciar una Ejecucion nueva, no una accion propia.
        acciones.append(
            AccionDisponible(
                codigo=ACCION_INTERRUMPIR_EJECUCION,
                etiqueta="Interrumpir la ejecucion",
                roles=(RolUsuario.TECNICO,),
                detalle_id=en_curso.reparacion_detail_id,
                ejecucion_id=en_curso.id,
            )
        )
        # EXC-REP-004: tercer resultado de PROC-REP-200. Igual que los
        # otros dos, solo lo acepta el tecnico propietario (service).
        acciones.append(
            AccionDisponible(
                codigo=ACCION_REQUIERE_REDEFINICION,
                etiqueta="El Detalle requiere redefinicion",
                roles=(RolUsuario.TECNICO,),
                detalle_id=en_curso.reparacion_detail_id,
                ejecucion_id=en_curso.id,
            )
        )

    # Factibilidad parcial: el override se ofrece igual, despues de las
    # acciones propias del taller, sin exigir que toda la Orden este
    # bloqueada ni reiniciar nada (BR-REP-003).
    if not en_recursos:
        acciones.extend(overrides)

    # REPARACION_LISTA (240) o SIN_REPARACION (069): ambos siguen al
    # cierre por Origen (PROC-REP-250).
    lista = lista_para_cierre(orden)
    if not lista:
        for pendiente in _detalles_en_espera_de_control(orden):
            acciones.append(
                AccionDisponible(
                    codigo=ACCION_APROBAR_CONTROL,
                    etiqueta="Aprobar el control tecnico",
                    roles=(RolUsuario.RECEPCION,),
                    detalle_id=pendiente,
                )
            )

    notificada = "PROC-REP-260" in alcanzados

    if politica.requiere_notificacion and lista and not notificada:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_NOTIFICAR,
                etiqueta="Notificar al cliente",
                roles=(RolUsuario.RECEPCION,),
            )
        )

    es_cobrable = politica.condicion_comercial == CondicionComercial.COBRABLE
    if orden.reparaciones_detail and es_cobrable and orden.saldo > CERO:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_REGISTRAR_PAGO,
                etiqueta="Registrar un pago",
                roles=ROLES_PAGO,
            )
        )

    entrega_habilitada = (
        lista and notificada and condicion_entrega_cumplida(orden)
    )
    if politica.requiere_entrega_cliente and entrega_habilitada:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_ENTREGAR,
                etiqueta="Entregar el equipo",
                roles=ROLES_ENTREGA,
            )
        )

    informado_rt = "PROC-REP-290" in alcanzados

    if politica.requiere_informar_rt and lista and not informado_rt:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_INFORMAR_RT,
                etiqueta="Informar el resultado a Gestion RT",
                # PROC-REP-290 es actor: ACT-SYSTEM (no hay actor humano
                # que autorizar), distinto de "rol todavia sin definir".
                roles=(),
                requiere_actor=False,
            )
        )

    if politica.requiere_informar_rt and informado_rt:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_DEVOLVER_RT,
                etiqueta="Devolver el equipo a Gestion RT",
                roles=ROLES_ENTREGA,
            )
        )

    return acciones
