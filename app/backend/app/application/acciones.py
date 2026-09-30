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
``if origen == ...: acciones_de_hp1()`` ni equivalente. Para
CLIENTE_EXTERNO -el unico origen operativo en Slice 0- el resultado es
identico al de antes de este refactor, salvo el cambio deliberado de
BR-REP-017: Registrar Pago ya no queda abierto a cualquier rol.
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
ACCION_LIBERAR_ORDEN = "LIBERAR_ORDEN"
ACCION_NOTIFICAR = "NOTIFICAR"
ACCION_REGISTRAR_PAGO = "REGISTRAR_PAGO"
ACCION_ENTREGAR = "ENTREGAR"

CERO = Decimal("0")


@dataclass(frozen=True)
class AccionDisponible:
    """Accion humana que la Orden admite ahora mismo.

    ``roles`` lista TODOS los actores autorizados: un nodo puede
    declarar ``actores_alternativos`` en PROC-REP V1.3 (por ejemplo
    PROC-REP-150 y PROC-REP-270), y entonces son varios sin jerarquia.
    """

    codigo: str
    etiqueta: str
    roles: tuple[RolUsuario, ...] = ()
    detalle_id: str | None = None
    ejecucion_id: str | None = None


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
    ahi, el control SI es granular por Detalle (PROC-REP-230): cada uno
    se aprueba de forma independiente.
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


def acciones_disponibles(orden: OrdenReparacion) -> list[AccionDisponible]:
    """Acciones humanas que corresponden al estado actual de la Orden.

    Una Orden ENTREGADA no admite ninguna: el proceso termino.
    """
    if orden.estado_workflow is EstadoWorkflow.ENTREGADA:
        return []

    politica = politica_de(orden.origen)

    acciones: list[AccionDisponible] = []
    estado = orden.estado_workflow
    alcanzados = nodos_alcanzados(orden)

    if estado is EstadoWorkflow.REQUERIMIENTO:
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

    lista = estado is EstadoWorkflow.REPARACION_LISTA
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

    return acciones
