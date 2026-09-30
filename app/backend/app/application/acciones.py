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
from app.services import ejecucion_activa, toma_activa
from app.services.ordenes import ROLES_ENTREGA, ROLES_PRIORIZACION
from app.services.pagos import ROLES_PAGO

from .progreso import nodos_alcanzados

# Codigos de accion que la API expone. Cada uno es exactamente un
# endpoint de comando.
ACCION_DEFINIR_REPARACION = "DEFINIR_REPARACION"
ACCION_ENCOLAR = "ENCOLAR"
ACCION_TOMAR = "TOMAR"
ACCION_INICIAR_DETALLE = "INICIAR_DETALLE"
ACCION_COMPLETAR_EJECUCION = "COMPLETAR_EJECUCION"
ACCION_APROBAR_CONTROL = "APROBAR_CONTROL"
ACCION_NOTIFICAR = "NOTIFICAR"
ACCION_REGISTRAR_PAGO = "REGISTRAR_PAGO"
ACCION_ENTREGAR = "ENTREGAR"
ACCION_INFORMAR_RT = "INFORMAR_RT"
ACCION_DEVOLVER_RT = "DEVOLVER_RT"

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
    """
    for detalle in orden.reparaciones_detail:
        if (
            detalle.estado is EstadoReparacionDetail.DEFINIDO
            and detalle.condicion is CondicionReparacionDetail.SIN_BLOQUEO
        ):
            return detalle.id
    return None


def _espera_control(orden: OrdenReparacion) -> bool:
    """Todos los Detalles terminados y ninguno controlado todavia."""
    if not orden.reparaciones_detail:
        return False
    if ejecucion_activa(orden) is not None:
        return False
    return all(
        detalle.estado is EstadoReparacionDetail.COMPLETO
        and detalle.control_estado is EstadoControl.PENDIENTE
        for detalle in orden.reparaciones_detail
    )


def acciones_disponibles(orden: OrdenReparacion) -> list[AccionDisponible]:
    """Acciones humanas que corresponden al estado actual de la Orden.

    Una Orden ENTREGADA no admite ninguna: el proceso termino. Lo mismo
    vale para RT_INTERNO al llegar a EVT-REP-999: ese origen no pasa por
    ENTREGADA (el estado terminal sigue pendiente de definicion, ver
    ``devolver_equipo_rt``), asi que el fin de proceso se detecta por
    ``current_process`` para no dejar acciones abiertas.
    """
    if (
        orden.estado_workflow is EstadoWorkflow.ENTREGADA
        or orden.current_process == "EVT-REP-999"
    ):
        return []

    politica = politica_de(orden.origen)

    acciones: list[AccionDisponible] = []
    estado = orden.estado_workflow
    alcanzados = nodos_alcanzados(orden)

    sin_detalles = not orden.reparaciones_detail
    if estado is EstadoWorkflow.REQUERIMIENTO and sin_detalles:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_DEFINIR_REPARACION,
                etiqueta="Definir la reparacion",
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
    trabajable = detalle_trabajable(orden)

    if toma_activa(orden) is not None and en_curso is None and trabajable:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_INICIAR_DETALLE,
                etiqueta="Iniciar el Detalle",
                roles=(RolUsuario.TECNICO,),
                detalle_id=trabajable,
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

    lista = estado is EstadoWorkflow.REPARACION_LISTA
    if not lista and _espera_control(orden):
        acciones.append(
            AccionDisponible(
                codigo=ACCION_APROBAR_CONTROL,
                etiqueta="Aprobar el control tecnico",
                roles=(RolUsuario.RECEPCION,),
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

    entrega_habilitada = lista and notificada and (
        not es_cobrable or orden.saldo <= CERO
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
