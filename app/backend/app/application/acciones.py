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
    EstadoCustodia,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    RolUsuario,
    Usuario,
)
from app.domain.politicas import CondicionComercial, politica_de
from app.services import (
    ROLES_CANCELACION,
    ROLES_COMPROBANTE_AUTORIZACION,
    ROLES_RECEPCION_EQUIPO,
    comprobante_autorizacion_emitible,
    custodia_por_definir,
    devolucion_pendiente,
    ejecucion_activa,
    es_trabajable,
    estado_custodia,
    evidencias_de_equipo,
    motivo_bloqueo_ejecucion,
    pendiente_de_autorizacion,
    requiere_definicion,
    revision_vigente,
    toma_activa,
)
from app.services.ordenes import ROLES_ENTREGA, ROLES_PRIORIZACION
from app.services.pagos import (
    ROLES_ANULACION_PAGO,
    ROLES_DEVOLUCION_DINERO,
    ROLES_PAGO,
    admite_pago,
    anulable,
    condicion_entrega_cumplida,
    credito_pendiente,
)
from app.services.reparaciones import definicion_finalizada
from app.services.revisiones import (
    finalizada_sin_reparacion,
    lista_para_cierre,
    revision_tecnica_realizada,
)

from .autorizacion_cliente import (
    decision_registrable,
    desistimiento_total_ofrecible,
    detalles_desistibles,
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
ACCION_RECHAZAR_CONTROL = "RECHAZAR_CONTROL"
ACCION_REGISTRAR_DEVOLUCION = "REGISTRAR_DEVOLUCION"
ACCION_CANCELAR_DETALLE = "CANCELAR_DETALLE"
ACCION_CANCELAR_ORDEN = "CANCELAR_ORDEN"
ACCION_REGISTRAR_DECISION_CLIENTE = "REGISTRAR_DECISION_CLIENTE"
ACCION_DESISTIR_DETALLE = "DESISTIR_DETALLE"
ACCION_DESISTIR_TODO = "DESISTIR_TODO"
ACCION_ANULAR_PAGO = "ANULAR_PAGO"
ACCION_DEVOLVER_DINERO = "REGISTRAR_DEVOLUCION_DINERO"
ACCION_REGISTRAR_DATOS_RECEPCION = "REGISTRAR_DATOS_RECEPCION"
ACCION_CONFIRMAR_RECEPCION = "CONFIRMAR_RECEPCION"
ACCION_EQUIPO_NO_RECIBIDO = "REGISTRAR_EQUIPO_NO_RECIBIDO"
ACCION_AGREGAR_OBSERVACION_RECEPCION = "AGREGAR_OBSERVACION_RECEPCION"
ACCION_EMITIR_COMPROBANTE_RECEPCION = "EMITIR_COMPROBANTE_RECEPCION"
ACCION_EMITIR_COMPROBANTE_AUTORIZACION = "EMITIR_COMPROBANTE_AUTORIZACION"

# Terminales de un Detalle: lo realizado y lo cancelado (BR-REP-012).
_TERMINALES = (
    EstadoReparacionDetail.COMPLETO,
    EstadoReparacionDetail.CANCELADO,
)

# EXC-REP-004: circuito de revision posterior (125 espera, 126 revision).
_NODOS_REVISION_POSTERIOR = ("PROC-REP-125", "PROC-REP-126")

# V1.4: la Orden espera la decision del cliente (ningun Detalle trabajable).
_NODO_ESPERA_AUTORIZACION = "PROC-REP-129"

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

    ``usuario_id`` restringe la accion a UNA persona dentro del rol: el
    titular de la toma activa para las acciones tecnicas sobre ella
    (E2). ``None`` significa que cualquier usuario con el rol puede.
    ``pago_id``: el Pago sobre el que actua un movimiento financiero.
    ``bloqueo``: la accion corresponde pero hoy no puede ejecutarse (por
    ejemplo, iniciar un Detalle sin la custodia del equipo confirmada); el
    backend la rechaza igual.
    """

    codigo: str
    etiqueta: str
    roles: tuple[RolUsuario, ...] = ()
    detalle_id: str | None = None
    ejecucion_id: str | None = None
    requiere_actor: bool = True
    usuario_id: str | None = None
    pago_id: str | None = None
    bloqueo: str | None = None


def puede_ejecutar(accion: AccionDisponible, usuario: Usuario) -> bool:
    """Si la accion le corresponde a ese usuario: activo, rol y titular.

    Lo mismo que exigen los services (``validar_actor``,
    ``validar_alguno_de``, ``validar_titular_de_la_toma``) y que lee la
    pantalla para ofrecer un formulario (``puedeEjecutar`` del frontend).
    No autoriza nada: el service valida igual al recibir el comando. Un
    paso de sistema no tiene actor: lo dispara cualquiera.
    """
    if not accion.requiere_actor:
        return True
    if not usuario.activo:
        return False
    if accion.roles and usuario.rol not in accion.roles:
        return False
    return accion.usuario_id is None or accion.usuario_id == usuario.id


def detalle_trabajable(orden: OrdenReparacion) -> str | None:
    """Primer Detalle trabajable, que es el que se puede iniciar.

    Consistente con ``services.resolucion._es_trabajable``: un Detalle
    DEFINIDO pero bloqueado (``REQUIERE_DEFINICION`` o
    ``BLOQUEADO_POR_RECURSOS``) o pendiente de autorizacion del cliente
    no es trabajable (``services.es_trabajable``).

    Se conserva para compatibilidad (``application.happy_path`` y los
    tests que ya la importan). ``acciones_disponibles`` usa la version
    plural, ``detalles_trabajables``: con Multi-Detalle puede haber mas
    de uno, y no le corresponde a este modulo elegir cual por el
    tecnico (PROC-REP-181).
    """
    trabajables = detalles_trabajables(orden)
    return trabajables[0] if trabajables else None


def detalles_trabajables(orden: OrdenReparacion) -> list[str]:
    """Todos los Detalles trabajables, en orden de aparicion.

    Con Multi-Detalle puede haber mas de un Detalle trabajable a la vez:
    la eleccion de cual iniciar ahora es del tecnico (PROC-REP-181), no
    algo que esta funcion deba decidir.
    """
    return [
        detalle.id
        for detalle in orden.reparaciones_detail
        if es_trabajable(orden, detalle)
    ]


def _detalles_en_espera_de_control(orden: OrdenReparacion) -> list[str]:
    """Detalles realizados con control PENDIENTE, controlables ahora.

    PROC-REP-220 solo se alcanza cuando la Orden ENTERA es terminal
    (todos sus Detalles COMPLETO o CANCELADO, al menos uno COMPLETO, igual
    que exige ``services.reparaciones.aprobar_control_tecnico``): mientras
    quede algun Detalle DEFINIDO o EN_PROGRESO no se ofrece ninguna accion
    de control, ni siquiera para un Detalle que ya este COMPLETO. Una vez
    ahi, el control SI es granular por Detalle (PROC-REP-220): cada uno
    se aprueba o se rechaza de forma independiente. Los CANCELADO no se
    controlan, y un Detalle ya aprobado no se vuelve a ofrecer (E14).
    """
    if ejecucion_activa(orden) is not None:
        return []
    if any(
        detalle.estado not in _TERMINALES
        for detalle in orden.reparaciones_detail
    ):
        return []
    return [
        detalle.id
        for detalle in orden.reparaciones_detail
        if detalle.estado is EstadoReparacionDetail.COMPLETO
        and detalle.control_estado is EstadoControl.PENDIENTE
    ]


def _overrides_de_recursos(
    orden: OrdenReparacion,
) -> list[AccionDisponible]:
    """EXC-REP-002 / BR-REP-003: override, capacidad transversal por Detalle.

    Una accion de Coordinador RMA por cada Detalle PENDIENTE (DEFINIDO)
    bloqueado por recursos, este la Orden detenida en PROC-REP-100/120 o
    con factibilidad parcial (habilitada, en cola, tomada o en reparacion).
    Nunca para uno pendiente de autorizacion del cliente.
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
        and not pendiente_de_autorizacion(orden, detalle)
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

    # Orden CANCELADA: lo unico que puede quedar del flujo es devolver el
    # equipo (PROC-REP-270). Sin cobro, control ni entrega comercial; un
    # anticipo a devolver es de ``acciones_financieras``.
    if orden.estado_workflow is EstadoWorkflow.CANCELADA:
        if not devolucion_pendiente(orden):
            return []
        return [
            AccionDisponible(
                codigo=ACCION_REGISTRAR_DEVOLUCION,
                etiqueta="Registrar la devolucion del equipo",
                roles=ROLES_ENTREGA,
            )
        ]

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

    # V1.4: en PROC-REP-129 la Orden espera la decision del cliente; la
    # registra Recepcion por ``acciones_de_autorizacion``. El hito de
    # workflow no ofrece nada propio, igual que en 125.
    if orden.current_process == _NODO_ESPERA_AUTORIZACION:
        estado = None

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

    # Con solo Detalles pendientes de autorizacion (por ejemplo, un JSON
    # anterior) no hay nada que tomar: PROC-REP-172 lo rechazaria.
    if (
        estado is EstadoWorkflow.EN_COLA
        and toma_activa(orden) is None
        and detalles_trabajables(orden)
    ):
        acciones.append(
            AccionDisponible(
                codigo=ACCION_TOMAR,
                etiqueta="Tomar la Orden",
                roles=(RolUsuario.TECNICO,),
            )
        )

    en_curso = ejecucion_activa(orden)
    toma = toma_activa(orden)
    # E2: las acciones tecnicas sobre la toma son solo de su titular.
    titular = toma.usuario_id if toma is not None else None

    if toma is not None and en_curso is None:
        bloqueo = motivo_bloqueo_ejecucion(orden)
        for trabajable in detalles_trabajables(orden):
            acciones.append(
                AccionDisponible(
                    codigo=ACCION_INICIAR_DETALLE,
                    etiqueta="Iniciar el Detalle",
                    roles=(RolUsuario.TECNICO,),
                    detalle_id=trabajable,
                    usuario_id=titular,
                    bloqueo=bloqueo,
                )
            )
        acciones.append(
            AccionDisponible(
                codigo=ACCION_LIBERAR_ORDEN,
                etiqueta="Liberar la Orden (PROC-REP-212/213)",
                roles=(RolUsuario.TECNICO,),
                usuario_id=titular,
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
                usuario_id=titular,
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
                usuario_id=titular,
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
                usuario_id=titular,
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
            # PROC-REP-230 "No" -> 235: la otra salida del mismo control.
            acciones.append(
                AccionDisponible(
                    codigo=ACCION_RECHAZAR_CONTROL,
                    etiqueta="Rechazar el control (retrabajo)",
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


def acciones_de_cancelacion(orden: OrdenReparacion) -> list[AccionDisponible]:
    """Cancelaciones que la Orden admite ahora (PROC-REP-300/305/306).

    Van aparte de ``acciones_disponibles``: son capacidades excepcionales,
    posibles en casi cualquier momento del proceso, y la UI las presenta
    separadas -con confirmacion- de la accion que corresponde al flujo.
    Igual que el resto, no autorizan nada: los services validan rol y
    estado cuando el comando llega.

    - Cancelar un Detalle: cada Detalle PENDIENTE (DEFINIDO); nunca uno
      COMPLETO, CANCELADO o en ejecucion.
    - Cancelar la Orden: sin Ejecucion activa, y con al menos un Detalle
      pendiente o sin Detalles todavia.

    Ninguna sobre una Orden cerrada, CANCELADA, SIN_REPARACION o con la
    reparacion lista: ahi ya no queda nada pendiente que cancelar.
    """
    if (
        orden.esta_cerrada
        or orden.estado_workflow is EstadoWorkflow.CANCELADA
        or lista_para_cierre(orden)
    ):
        return []

    pendientes = [
        detalle.id
        for detalle in orden.reparaciones_detail
        if detalle.estado is EstadoReparacionDetail.DEFINIDO
    ]
    acciones = [
        AccionDisponible(
            codigo=ACCION_CANCELAR_DETALLE,
            etiqueta="Cancelar el Detalle",
            roles=ROLES_CANCELACION,
            detalle_id=detalle_id,
        )
        for detalle_id in pendientes
    ]
    if ejecucion_activa(orden) is None and (
        pendientes or not orden.reparaciones_detail
    ):
        acciones.append(
            AccionDisponible(
                codigo=ACCION_CANCELAR_ORDEN,
                etiqueta="Cancelar la Orden (trabajos pendientes)",
                roles=ROLES_CANCELACION,
            )
        )
    return acciones


def acciones_de_autorizacion(
    orden: OrdenReparacion,
) -> list[AccionDisponible]:
    """Decisiones comerciales del cliente que la Orden admite ahora.

    Aparte de ``acciones_disponibles``, como las cancelaciones: es un
    carril independiente de Recepcion (EVT-REP-003, BR-REP-037) que no
    detiene al tecnico ni depende del hito de workflow.

    - Registrar la decision (PROC-REP-046/047): una sola accion; que
      Detalles decidir lo elige el formulario.
    - Desistir de un Detalle ya autorizado y todavia cancelable.
    - Desistir de todos los trabajos cancelables, si queda trabajo ya
      autorizado sin terminar (aunque algo lo impida: la UI lo informa).
    - Generar el comprobante de autorizacion: hay trabajos autorizados que
      el ultimo comprobante no refleja (ninguno todavia, u otro trabajo
      autorizado despues). Nunca se emite solo.
    """
    acciones: list[AccionDisponible] = []
    if decision_registrable(orden):
        acciones.append(
            AccionDisponible(
                codigo=ACCION_REGISTRAR_DECISION_CLIENTE,
                etiqueta="Registrar la decision del cliente",
                roles=(RolUsuario.RECEPCION,),
            )
        )
    acciones.extend(
        AccionDisponible(
            codigo=ACCION_DESISTIR_DETALLE,
            etiqueta="El cliente desiste de este trabajo autorizado",
            roles=(RolUsuario.RECEPCION,),
            detalle_id=detalle_id,
        )
        for detalle_id in detalles_desistibles(orden)
    )
    if desistimiento_total_ofrecible(orden):
        acciones.append(
            AccionDisponible(
                codigo=ACCION_DESISTIR_TODO,
                etiqueta="Cliente desiste de todos los trabajos cancelables",
                roles=(RolUsuario.RECEPCION,),
            )
        )
    if comprobante_autorizacion_emitible(orden):
        acciones.append(
            AccionDisponible(
                codigo=ACCION_EMITIR_COMPROBANTE_AUTORIZACION,
                etiqueta="Generar el comprobante de autorizacion",
                roles=ROLES_COMPROBANTE_AUTORIZACION,
            )
        )
    return acciones


def acciones_financieras(orden: OrdenReparacion) -> list[AccionDisponible]:
    """Movimientos de dinero que la Orden admite ahora (FEAT-REP-007).

    Aparte de ``acciones_disponibles``: son capacidades transversales que
    la UI presenta en "Pagos y movimientos", no un paso del flujo.

    - Registrar un anticipo o un pago: hay saldo pendiente de cobro (o es
      una seña antes de definir los Detalles).
    - Anular un Pago vigente sin devoluciones (Administracion).
    - Devolver dinero: hay saldo a favor del cliente.

    Nada en una Orden cerrada ni en un Origen sin circuito comercial.
    """
    if orden.esta_cerrada:
        return []
    acciones: list[AccionDisponible] = []
    if admite_pago(orden):
        acciones.append(
            AccionDisponible(
                codigo=ACCION_REGISTRAR_PAGO,
                etiqueta=(
                    "Registrar un pago"
                    if lista_para_cierre(orden)
                    else "Registrar un anticipo"
                ),
                roles=ROLES_PAGO,
            )
        )
    if credito_pendiente(orden) > 0:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_DEVOLVER_DINERO,
                etiqueta="Devolver dinero al cliente",
                roles=ROLES_DEVOLUCION_DINERO,
            )
        )
    acciones.extend(
        AccionDisponible(
            codigo=ACCION_ANULAR_PAGO,
            etiqueta=f"Anular el pago {pago.id}",
            roles=ROLES_ANULACION_PAGO,
            pago_id=pago.id,
        )
        for pago in orden.resumen_pago.pagos
        if anulable(orden, pago)
    )
    return acciones


def acciones_de_custodia(orden: OrdenReparacion) -> list[AccionDisponible]:
    """Recepcion fisica y comprobante de recepcion, si corresponden ahora.

    Aparte de ``acciones_disponibles``: son capacidades transversales que
    la UI presenta en "Recepcion y custodia" y en "Documentos".

    - Registrar o corregir los datos del ingreso: mientras la recepcion no
      este confirmada y el equipo no haya salido. En una Orden anterior al
      registro de recepcion, es la regularizacion.
    - Confirmar la recepcion fisica: hay datos de ingreso sin decidir.
    - Registrar "Equipo no recibido": Orden cancelada con la custodia sin
      definir y sin evidencias de que el equipo estuvo en el local.
    - Agregar una observacion complementaria: hay datos de ingreso.
    - Emitir una version nueva del comprobante: el proceso ya emitio el
      primero (PROC-REP-060).

    Nada en una Orden cerrada.
    """
    if orden.esta_cerrada:
        return []
    politica = politica_de(orden.origen)
    estado = estado_custodia(orden)
    recepcion = orden.recepcion
    sin_salida = estado not in (
        EstadoCustodia.ENTREGADO,
        EstadoCustodia.DEVUELTO,
    )
    acciones: list[AccionDisponible] = []
    if sin_salida and (recepcion is None or not recepcion.decidida):
        acciones.append(
            AccionDisponible(
                codigo=ACCION_REGISTRAR_DATOS_RECEPCION,
                etiqueta=(
                    "Regularizar: registrar los datos del ingreso"
                    if recepcion is None
                    else "Corregir los datos del ingreso"
                ),
                roles=ROLES_RECEPCION_EQUIPO,
            )
        )
    if (
        politica.requiere_confirmacion_recepcion
        and recepcion is not None
        and not recepcion.decidida
        and sin_salida
    ):
        acciones.append(
            AccionDisponible(
                codigo=ACCION_CONFIRMAR_RECEPCION,
                etiqueta="Confirmar la recepcion fisica del equipo",
                roles=ROLES_RECEPCION_EQUIPO,
            )
        )
    if (
        politica.requiere_confirmacion_recepcion
        and orden.estado_workflow is EstadoWorkflow.CANCELADA
        and custodia_por_definir(orden)
        and not evidencias_de_equipo(orden)
    ):
        acciones.append(
            AccionDisponible(
                codigo=ACCION_EQUIPO_NO_RECIBIDO,
                etiqueta="Confirmar equipo no recibido",
                roles=ROLES_RECEPCION_EQUIPO,
            )
        )
    if recepcion is not None:
        acciones.append(
            AccionDisponible(
                codigo=ACCION_AGREGAR_OBSERVACION_RECEPCION,
                etiqueta="Agregar una observacion complementaria",
                roles=ROLES_RECEPCION_EQUIPO,
            )
        )
    if (
        politica.requiere_comprobante_recepcion
        and orden.documentos.comprobante_recepcion.generado
    ):
        acciones.append(
            AccionDisponible(
                codigo=ACCION_EMITIR_COMPROBANTE_RECEPCION,
                etiqueta="Emitir otra version del comprobante de recepcion",
                roles=ROLES_RECEPCION_EQUIPO,
            )
        )
    return acciones
